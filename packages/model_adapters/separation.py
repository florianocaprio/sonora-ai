"""Windowed cinematic source separation with a project-rate reconstruction residual."""

from __future__ import annotations

import json
import math
import os
import resource
import shutil
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Iterator

import numpy as np
import soundfile as sf
import soxr
from numpy.typing import NDArray

from .registry import (
    CONFIG_DIR,
    STEREO_NOTICE,
    Cancelled,
    ModelManifest,
    ModelUnavailable,
    Progress,
    check_cancelled,
    checkpoint_path,
    get_manifest,
    probe_capabilities,
    verify_model,
)

if TYPE_CHECKING:
    import torch


STEMS = ("dialogue", "music", "effects")
READ_FRAMES = 65536
ALGORITHM_VERSION = "1.0.0"
_STEM_KEYS = {"dialogue": "speech", "music": "music", "effects": "sfx"}


class SeparationAdapter:
    """One local model instance with an explicit lifecycle and cancellation."""

    def __init__(self, model_dir: Path, model_id: str, backend: str):
        self.manifest = get_manifest(model_id)
        self.model_dir = model_dir
        self.model_id = model_id
        self.backend = backend
        self._model: torch.nn.Module | None = None
        self._cancelled = Event()

    def probe_capabilities(self) -> dict:
        return probe_capabilities(self.model_id)

    def load(self, *, cancelled: Cancelled = lambda: False) -> None:
        if self.backend not in self.probe_capabilities()["backends"]:
            raise ModelUnavailable(f"Backend {self.backend} non disponibile per {self.model_id}.")
        import torch

        verify_model(self.model_dir, self.model_id, cancelled=cancelled)
        checkpoint = checkpoint_path(self.model_dir, self.manifest)
        try:
            config = json.loads((CONFIG_DIR / f"{self.model_id}.json").read_text())
            if self.model_id == "dbs-tiger-dnr":
                from safetensors.torch import load_file
                from ._vendor.dbs.models.tiger import DBSTIGER

                model = DBSTIGER(**config)
                weights = load_file(str(checkpoint))
            else:
                from ._vendor.bandit.models.bandit.bandit import Bandit

                model = Bandit(**config)
                state = torch.load(checkpoint, map_location="cpu", weights_only=True, mmap=True)
                weights = {
                    key.removeprefix("model."): tensor
                    for key, tensor in state["state_dict"].items()
                    if key.startswith("model.")
                }
            model.load_state_dict(weights, strict=True)
            self._model = model.eval().float().to(self.backend)
        except (RuntimeError, ValueError, OSError, KeyError) as error:
            raise ModelUnavailable(f"Caricamento di {self.model_id} non riuscito: {error}") from error

    def separate(self, window: NDArray[np.float32], *, cancelled: Cancelled = lambda: False) -> NDArray[np.float32]:
        """Run each input channel independently. Return [stem, sample, channel]."""
        import torch

        if self._model is None:
            raise ModelUnavailable("Carica il checkpoint prima della separazione.")
        max_frames = self.manifest["window_seconds"] * self.manifest["sample_rate"]
        if window.ndim != 2 or not 0 < len(window) <= max_frames or window.shape[1] not in (1, 2):
            raise ValueError(f"La finestra deve contenere da 1 a {max_frames} campioni mono o stereo.")
        if not np.isfinite(window).all():
            raise ValueError("La finestra contiene NaN o Inf.")
        outputs = np.empty((len(STEMS), *window.shape), dtype=np.float32)
        for channel in range(window.shape[1]):
            check_cancelled(lambda: self._cancelled.is_set() or cancelled())
            input_tensor = torch.from_numpy(window[:, channel].copy()).reshape(1, 1, -1).to(self.backend)
            try:
                with torch.inference_mode():
                    if self.model_id == "dbs-tiger-dnr":
                        raw = self._model(input_tensor)[0].cpu().numpy()
                        outputs[:, :, channel] = raw[[self.manifest["outputs"].index(stem) for stem in STEMS]]
                    else:
                        estimates = self._model({"mixture": {"audio": input_tensor}})["estimates"]
                        for index, stem in enumerate(STEMS):
                            outputs[index, :, channel] = estimates[_STEM_KEYS[stem]]["audio"][0, 0].cpu().numpy()
            except (RuntimeError, NotImplementedError) as error:
                message = str(error).lower()
                if "out of memory" in message or "allocation" in message:
                    raise ModelUnavailable("Memoria insufficiente. Libera memoria oppure prova il backend CPU.") from error
                if self.backend == "mps":
                    raise ModelUnavailable(f"Metal non ha completato l’inferenza. Puoi scegliere CPU. Dettaglio: {error}") from error
                raise RuntimeError(f"Inferenza CPU non riuscita: {error}") from error
        if not np.isfinite(outputs).all():
            raise RuntimeError("Il modello ha restituito NaN o Inf. Output scartato.")
        return outputs

    def cancel(self) -> None:
        self._cancelled.set()

    def unload(self) -> None:
        self._model = None
        if self.backend == "mps" and "mps" in self.probe_capabilities()["backends"]:
            import torch

            torch.mps.empty_cache()


def _wav(path: Path, rate: int, channels: int, frames: int) -> sf.SoundFile:
    container = "RF64" if frames * channels * 4 >= 2**32 - 4096 else "WAV"
    return sf.SoundFile(path, "w", samplerate=rate, channels=channels, format=container, subtype="FLOAT")


def _resample_input(source: sf.SoundFile, path: Path, rate: int, cancelled: Cancelled) -> None:
    stream = soxr.ResampleStream(source.samplerate, rate, source.channels)
    with _wav(path, rate, source.channels, round(source.frames * rate / source.samplerate)) as output:
        while source.tell() < source.frames:
            check_cancelled(cancelled)
            signal = source.read(READ_FRAMES, dtype="float32", always_2d=True)
            if not np.isfinite(signal).all():
                raise ValueError("L’audio canonico contiene NaN o Inf.")
            output.write(stream.resample_chunk(signal, last=source.tell() >= source.frames))
    source.seek(0)


def _window(source: sf.SoundFile, start: int, frames: int, reflect: bool) -> NDArray[np.float32]:
    end = start + frames
    left = max(start, 0)
    right = min(end, source.frames)
    source.seek(left)
    audio = source.read(right - left, dtype="float32", always_2d=True)
    result = np.zeros((frames, source.channels), dtype=np.float32)
    offset = left - start
    result[offset:offset + len(audio)] = audio
    if reflect and start < 0:
        amount = min(-start, source.frames - 1)
        if amount:
            source.seek(1)
            result[offset - amount:offset] = source.read(amount, dtype="float32", always_2d=True)[::-1]
    if reflect and end > source.frames:
        amount = min(end - source.frames, source.frames - 1)
        if amount:
            source.seek(source.frames - amount - 1)
            result[right - start:right - start + amount] = source.read(amount, dtype="float32", always_2d=True)[::-1]
    return result


def _overlap_add(
    adapter: SeparationAdapter, source: sf.SoundFile, progress: Progress, cancelled: Cancelled,
) -> Iterator[tuple[NDArray[np.float32], bool]]:
    manifest = adapter.manifest
    rate = manifest["sample_rate"]
    window_frames = manifest["window_seconds"] * rate
    hop_frames = manifest["hop_seconds"] * rate
    bandit = manifest["overlap"] == "hann"
    if bandit:
        starts = range(hop_frames - window_frames, source.frames, hop_frames)
        taper = (0.5 - 0.5 * np.cos(np.arange(window_frames) * (2 * np.pi / window_frames))).astype(np.float32)
    else:
        count = 1 + max(0, (source.frames - window_frames + hop_frames - 1) // hop_frames)
        starts = range(0, count * hop_frames, hop_frames)
        if count == 1 and source.frames > hop_frames and adapter.backend != "mps":
            window_frames = source.frames
        taper = np.ones(window_frames, dtype=np.float32)
    sums = np.zeros((len(STEMS), window_frames, source.channels), dtype=np.float32)
    weights = np.zeros(window_frames, dtype=np.float32)

    for index, start in enumerate(starts):
        check_cancelled(cancelled)
        output = adapter.separate(_window(source, start, window_frames, bandit), cancelled=cancelled)
        sums += output * taper[None, :, None]
        weights += taper
        final = index == len(starts) - 1
        left = max(0, -start)
        right = min(source.frames - start, window_frames if final else hop_frames)
        progress(index + 1, len(starts))
        if left < right:
            if np.any(weights[left:right] == 0):
                raise RuntimeError("Overlap-add senza copertura per alcuni campioni.")
            yield sums[:, left:right] / weights[None, left:right, None], final
        if not final:
            sums[:, :-hop_frames] = sums[:, hop_frames:]
            sums[:, -hop_frames:] = 0
            weights[:-hop_frames] = weights[hop_frames:]
            weights[-hop_frames:] = 0


class _OutputWriter:
    """Restore project timeline and compute residual on project-domain samples."""

    def __init__(self, source: sf.SoundFile, model_rate: int, output_paths: dict[str, Path], stack: ExitStack):
        self.source = source
        self.model_rate = model_rate
        self.stream = None
        if source.samplerate != model_rate:
            self.stream = soxr.ResampleStream(model_rate, source.samplerate, len(STEMS) * source.channels)
        self.outputs = {
            stem: stack.enter_context(_wav(path, source.samplerate, source.channels, source.frames))
            for stem, path in output_paths.items()
        }
        self.stereo: dict[str, NDArray[np.float64]] = {
            stem: np.zeros(3, dtype=np.float64) for stem in (*self.outputs, "original")
        }

    def _measure_stereo(self, stem: str, signal: NDArray[np.float32]) -> None:
        if self.source.channels == 2:
            left = signal[:, 0].astype(np.float64)
            right = signal[:, 1].astype(np.float64)
            self.stereo[stem] += (np.dot(left, left), np.dot(right, right), np.dot(left, right))

    def stereo_metrics(self) -> dict:
        result = {}
        if self.source.channels == 2:
            for key, (left, right, product) in self.stereo.items():
                norm = math.sqrt(left * right)
                result[key] = {
                    "correlation": float(np.clip(product / norm, -1, 1)) if norm else None,
                    "balance_db_right_vs_left": 10 * math.log10(right / left) if right and left else None,
                    "unavailable_reason": None if norm else "Almeno un canale è in silenzio.",
                }
        return result

    def write(self, separated: NDArray[np.float32], final: bool) -> None:
        source = self.source
        interleaved = separated.transpose(1, 0, 2).reshape(-1, len(STEMS) * source.channels)
        if self.stream is not None:
            interleaved = self.stream.resample_chunk(interleaved, last=final)
        remaining = source.frames - source.tell()
        if final and len(interleaved) != remaining:
            difference = remaining - len(interleaved)
            max_rounding = math.ceil(source.samplerate / self.model_rate) + 1 if self.stream else 0
            if abs(difference) > max_rounding:
                raise RuntimeError("Il ricampionamento ha generato una durata incompatibile con il progetto.")
            if difference > 0:
                interleaved = np.pad(interleaved, ((0, difference), (0, 0)))
        interleaved = interleaved[:remaining]
        original = source.read(len(interleaved), dtype="float32", always_2d=True)
        sources = interleaved.reshape(len(original), len(STEMS), source.channels)
        residual = original - np.sum(sources, axis=1, dtype=np.float32)
        if not (np.isfinite(sources).all() and np.isfinite(residual).all()):
            raise RuntimeError("Audio separato o residuo non finito. Output scartato.")
        self._measure_stereo("original", original)
        self._measure_stereo("residual", residual)
        for index, stem in enumerate(STEMS):
            self._measure_stereo(stem, sources[:, index])
            self.outputs[stem].write(sources[:, index])
        self.outputs["residual"].write(residual)


def separate_audio(
    source: Path,
    destination: Path,
    model_dir: Path,
    model_id: str,
    backend: str,
    *,
    progress: Progress,
    cancelled: Cancelled,
) -> dict:
    """Create time-aligned float WAV stems in an isolated staging directory."""
    adapter = SeparationAdapter(model_dir, model_id, backend)
    manifest: ModelManifest = adapter.manifest
    files = (*STEMS, "residual")
    final_paths = {stem: destination / f"{stem}.wav" for stem in files}
    if any(path.exists() for path in final_paths.values()):
        raise ValueError("La destinazione degli stem contiene già un risultato.")
    destination.mkdir(parents=True, exist_ok=True)
    with sf.SoundFile(source) as original, tempfile.TemporaryDirectory(dir=destination) as temporary:
        if original.channels not in (1, 2) or original.frames <= 0:
            raise ValueError("La separazione richiede PCM mono o stereo con almeno un campione.")
        rate = manifest["sample_rate"]
        converted_frames = round(original.frames * rate / original.samplerate)
        if converted_frames <= 0:
            raise ValueError("Il file è troppo corto per la frequenza di campionamento del modello.")
        required_bytes = original.frames * original.channels * 4 * len(files)
        if original.samplerate != rate:
            required_bytes += converted_frames * original.channels * 4
        if shutil.disk_usage(destination).free < required_bytes + 32768:
            raise ModelUnavailable(f"Spazio insufficiente per gli stem. Servono almeno {required_bytes} byte.")

        with ExitStack() as stack:
            directory = Path(temporary)
            output_paths = {stem: directory / path.name for stem, path in final_paths.items()}
            inference_path = source
            if original.samplerate != rate:
                inference_path = directory / "model_input.wav"
                _resample_input(original, inference_path, rate, cancelled)
            inference_source = stack.enter_context(sf.SoundFile(inference_path))
            writer = _OutputWriter(original, rate, output_paths, stack)
            load_start = time.monotonic()
            try:
                adapter.load(cancelled=cancelled)
                model_load_seconds = time.monotonic() - load_start
                inference_start = time.monotonic()
                for block, final in _overlap_add(adapter, inference_source, progress, cancelled):
                    writer.write(block, final)
                inference_seconds = time.monotonic() - inference_start
                mps_bytes = None
                if backend == "mps":
                    import torch

                    mps_bytes = torch.mps.driver_allocated_memory()
            finally:
                adapter.unload()
            expected_frames = writer.source.frames
            if any(output.frames != expected_frames for output in writer.outputs.values()):
                raise RuntimeError("Il numero di campioni degli stem ottenuti non coincide con quello del progetto.")

        check_cancelled(cancelled)
        published = []
        try:
            for stem, file in output_paths.items():
                with file.open("rb") as stream:
                    os.fsync(stream.fileno())
                file.replace(final_paths[stem])
                published.append(final_paths[stem])
        except OSError:
            for file in published:
                file.unlink(missing_ok=True)
            raise

        import torch

        max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        warnings = [STEREO_NOTICE] if original.channels == 2 else []
        fallback = backend == "mps" and os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1"
        if fallback:
            warnings.append("L’ambiente consente fallback PyTorch su CPU. Le singole operazioni non sono tracciate.")
        return {
            "model": manifest,
            "model_id": model_id,
            "backend": backend,
            "algorithm_version": ALGORITHM_VERSION,
            "project_sample_rate": original.samplerate,
            "model_sample_rate": rate,
            "sample_count": original.frames,
            "channels": original.channels,
            "channel_order": ["mono"] if original.channels == 1 else ["left", "right"],
            "window_seconds": manifest["window_seconds"],
            "hop_seconds": manifest["hop_seconds"],
            "overlap": manifest["overlap"],
            "padding": (
                "reflect_at_edges_zero_beyond_short_context" if manifest["overlap"] == "hann"
                else "zero_padded_fixed_windows" if backend == "mps"
                else "zero_padded_except_single_window_with_more_than_half_context"
            ),
            "stereo_mode": "independent_lr" if original.channels == 2 else "mono",
            "warnings": warnings,
            "stereo_metrics": writer.stereo_metrics(),
            "resampler": f"libsoxr HQ / python-soxr {soxr.__version__}" if original.samplerate != rate else None,
            "torch_version": str(torch.__version__),
            "model_load_seconds": model_load_seconds,
            "inference_seconds": inference_seconds,
            "real_time_factor": inference_seconds * original.samplerate / original.frames,
            "mps_driver_bytes_end": mps_bytes,
            "mps_fallback_enabled_by_environment": fallback if backend == "mps" else None,
            "process_peak_rss_bytes": max_rss if sys.platform == "darwin" else max_rss * 1024,
        }
