"""Reversible and region-bound PCM repair operations."""

from pathlib import Path
import tempfile
from typing import Callable

import numpy as np
from scipy import signal
import soundfile as sf

from .analysis import _operation
from .filters import number, peaking_eq
from .io import (
    BLOCK, Cancelled, Progress, audio_info, check_cancel, float_writer, require_finite, sample_region,
)
from .metrics import SignalMetrics

VERSION = "sonora-restoration/1"
SUPPORTED = ("dc_remove", "dehum", "declick", "peq", "microgap")
PRESETS = ("basic", "medium", "high")
MAX_OPERATIONS = 128
MAX_PROPOSALS = 32


def propose_operations(events: list[dict], preset: str, stem: str, *,
                       start_sample: int = 0, end_sample: int | None = None,
                       sample_rate: int = 48_000) -> list[dict]:
    """Return editable suggestions, leaving uncertain repairs to operator review."""
    preset = preset.lower()
    if preset not in PRESETS:
        raise ValueError("Scegliere Basic, Medium oppure High.")
    cap = {"original": 0.65, "dialogue": 0.7, "music": 0.45, "effects": 0.4, "residual": 0.45}
    wet = cap.get(stem, 0.5)
    result = []
    for event in events:
        if event.get("status") in ("dismissed", "repaired"):
            continue
        proposal = event.get("proposed_operation")
        if not proposal:
            continue
        kind = proposal["type"]
        if kind == "microgap" and preset != "high":
            continue
        if kind == "dehum" and stem in ("music", "effects") and event.get("status") != "confirmed":
            continue
        first, last = proposal["start_sample"], proposal["end_sample"]
        left, right = max(start_sample, first), min(last, end_sample if end_sample is not None else last)
        if right <= left or (kind in ("microgap", "declick") and (left, right) != (first, last)):
            continue
        result.append(_operation(kind, left, right, dict(proposal["params"]), wet=1.0 if kind == "microgap" else wet))
        if len(result) >= MAX_PROPOSALS - 1:
            break
    if preset == "medium" and end_sample is not None and start_sample < end_sample:
        correction = {"dialogue": (2300, 0.8), "music": (350, -0.5), "effects": (170, -0.5)}
        if stem in correction:
            hz, gain = correction[stem]
            result.append(_operation("peq", start_sample, end_sample,
                                     {"frequency_hz": min(hz, sample_rate * 0.45), "gain_db": gain, "q": 0.8},
                                     wet=0.75))
    return result


def _read(audio: sf.SoundFile, start: int, frames: int) -> np.ndarray:
    audio.seek(start)
    data = audio.read(frames, dtype="float32", always_2d=True)
    require_finite(data)
    return data


def _mean(audio: sf.SoundFile, start: int, end: int, cancelled: Cancelled) -> np.ndarray:
    values = np.zeros(audio.channels)
    for first in range(start, end, BLOCK):
        check_cancel(cancelled)
        values += _read(audio, first, min(BLOCK, end - first)).sum(axis=0, dtype=np.float64)
    return values / (end - start)


def _apply_region(source: Path, destination: Path, operation: dict,
                  progress: Progress, cancelled: Cancelled) -> dict:
    kind = operation.get("type")
    params = operation.get("params", {})
    if kind not in SUPPORTED or not isinstance(params, dict):
        raise ValueError("Tipo o parametri dell'intervento di restauro non supportati.")
    with sf.SoundFile(source) as audio:
        start, end = sample_region(operation.get("start_sample", 0), operation.get("end_sample"), audio.frames)
        wet = number(operation.get("wet", 1.0), "Wet", 0, 1)
        rate = audio.samplerate
        offset = np.zeros(audio.channels)
        filter_ = None
        state = None
        interpolated = None
        changed = 0
        threshold = 0.0
        if kind == "dc_remove" and wet:
            offset = _mean(audio, start, end, cancelled)
        elif kind in ("dehum", "peq"):
            frequency = number(params.get("frequency_hz", 50 if kind == "dehum" else 1000),
                               "Frequenza", 1, rate * 0.49)
            q = number(params.get("q", 24.0 if kind == "dehum" else 0.8), "Q", 0.1, 80)
            if kind == "dehum":
                filter_ = signal.iirnotch(frequency, q, fs=rate)
            else:
                gain = number(params.get("gain_db", 0), "Guadagno EQ", -24, 24)
                filter_ = peaking_eq(rate, frequency, gain, q)
            state = np.zeros((2, audio.channels), dtype=np.float64)
            context_start = max(0, start - rate)
            if start > context_start:
                _, state = signal.lfilter(*filter_, _read(audio, context_start, start - context_start), axis=0, zi=state)
        elif kind == "microgap":
            max_ms = number(params.get("max_duration_ms", 20), "Durata massima in ms", 0.1, 20)
            if (end - start) * 1000 / rate > max_ms or start < 1 or end >= audio.frames:
                raise ValueError("Micro-gap eccessivo o privo di un campione di contesto su entrambi i lati.")
            neighbors = np.vstack((_read(audio, start - 1, 1), _read(audio, end, 1)))
            alpha = np.arange(1, end - start + 1, dtype=np.float64)[:, None] / (end - start + 1)
            interpolated = neighbors[0] + alpha * (neighbors[1] - neighbors[0])
        elif kind == "declick":
            threshold = number(params.get("threshold", 0.08), "Soglia de-click", 0.001, 2)

        metrics = SignalMetrics(audio.channels)
        ramp = max(1, min(round(rate * 0.008), (end - start - 1) // 2))
        with float_writer(destination, rate, audio.channels, audio.frames) as writer:
            for cursor in range(0, audio.frames, BLOCK):
                check_cancel(cancelled)
                block = _read(audio, cursor, min(BLOCK, audio.frames - cursor))
                left, right = max(cursor, start), min(cursor + len(block), end)
                if left < right and wet:
                    portion = block[left - cursor:right - cursor]
                    blend = wet
                    if kind == "dc_remove":
                        processed = portion - offset
                    elif filter_ is not None:
                        processed, state = signal.lfilter(*filter_, portion, axis=0, zi=state)
                    elif interpolated is not None:
                        processed = interpolated[left - start:right - start]
                    else:
                        processed = portion.copy()
                        first, last = max(left, 1), min(right, audio.frames - 1)
                        if last > first:
                            context = _read(audio, first - 1, last - first + 2)
                            repairs = (context[:-2] + context[2:]) * 0.5
                            delta = np.abs(context[1:-1] - repairs)
                            local = np.abs(context[2:] - context[:-2])
                            mask = (delta >= threshold) & (delta > 3 * local)
                            processed[first - left:last - left] = np.where(mask, repairs, context[1:-1])
                    if kind in ("dc_remove", "dehum", "peq"):
                        indices = np.arange(left, right)
                        fade_left = (indices - start) / ramp if start else 1.0
                        fade_right = (end - 1 - indices) / ramp if end < audio.frames else 1.0
                        blend = wet * np.minimum(1.0, np.minimum(fade_left, fade_right))
                        blend = (blend if np.ndim(blend) else np.full(len(portion), blend))[:, None]
                    replacement = (portion + blend * (processed - portion)).astype(np.float32)
                    changed += int(np.count_nonzero(np.any(replacement != portion, axis=1)))
                    portion[:] = replacement
                require_finite(block)
                metrics.feed(block)
                writer.write(block)
                if progress:
                    progress(cursor + len(block), audio.frames)
            check_cancel(cancelled)
        return {
            **audio_info(audio),
            "operation": {**operation, "start_sample": start, "end_sample": end, "wet": wet,
                          "changed_frames": changed, "classification": "reconstructed" if kind == "microgap" else "dsp"},
            "metrics": metrics.as_dict(),
        }


def restore(source: Path, destination: Path, operations: list[dict], *,
            progress: Progress = None, cancelled: Cancelled = None,
            neural: Callable[[Path, Path, dict], dict] | None = None) -> dict:
    """Apply ordered operations without touching samples outside their declared regions."""
    if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
        raise ValueError(f"Specificare fino a {MAX_OPERATIONS} interventi ordinati.")
    if any(not isinstance(operation, dict) for operation in operations):
        raise ValueError("Gli interventi devono essere oggetti JSON.")
    active = []
    for operation in operations:
        bypass = operation.get("bypass", False)
        if type(bypass) is not bool:
            raise ValueError("Il bypass deve essere un valore booleano.")
        if not bypass:
            active.append(operation)
    frames = sf.info(source).frames
    completed = []
    generated = []
    has_active = bool(active)
    total = frames * max(1, len(active))
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=destination.parent) as scratch:
        if not active:
            active = [{"type": "dc_remove", "wet": 0.0}]
        current = source
        for index, operation in enumerate(active):
            target = Path(scratch) / f"{index}.wav"
            if operation.get("type") == "inpaint":
                if neural is None:
                    raise ValueError("L’inpainting richiede un adattatore neurale locale.")
                provenance = neural(current, target, operation)
                with sf.SoundFile(target) as audio:
                    info = audio_info(audio)
                region = {key: operation[key] for key in ("start_sample", "end_sample")}
                generated.append(dict(provenance, **region, classification="generated"))
                operation_info = {**operation, "classification": "generated"}
                if progress:
                    progress((index + 1) * frames, total)
            else:
                info = _apply_region(current, target, operation,
                                     (lambda done, _, index=index: progress(index * frames + done, total)) if progress else None,
                                     cancelled)
                operation_info = info.pop("operation")
            if has_active:
                completed.append(operation_info)
            if index:
                current.unlink()
            current = target
        check_cancel(cancelled)
        target.replace(destination)
    return {**info, "operations": completed, "algorithm_version": VERSION, "generated_regions": generated, "reconstructed_regions": [
        {"start_sample": operation["start_sample"], "end_sample": operation["end_sample"],
         "algorithm": "linear_interpolation"}
        for operation in completed if operation["classification"] == "reconstructed" and operation["changed_frames"]
    ]}


def difference_audio(source: Path, restored: Path, destination: Path, *, cancelled: Cancelled = None) -> dict:
    """Write the sample-aligned restored version minus its input."""
    with sf.SoundFile(source) as before, sf.SoundFile(restored) as after:
        if (before.samplerate, before.channels, before.frames) != (after.samplerate, after.channels, after.frames):
            raise ValueError("Il confronto differenza richiede versioni con timeline e canali identici.")
        with float_writer(destination, before.samplerate, before.channels, before.frames) as writer:
            for start in range(0, before.frames, BLOCK):
                check_cancel(cancelled)
                frames = min(BLOCK, before.frames - start)
                result = _read(after, start, frames) - _read(before, start, frames)
                require_finite(result)
                writer.write(result)
            check_cancel(cancelled)
        return audio_info(before)
