"""Deterministic block-based stereo and mono mixing."""

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy import signal
import soundfile as sf

from packages.audio_core.filters import number, peaking_eq
from packages.audio_core.io import (
    BLOCK, Cancelled, Progress, atomic_destination, audio_info, check_cancel, float_writer, require_finite,
)
from packages.audio_core.metrics import SignalMetrics, loudness
from .limiter import LimiterSettings, limit_master

VERSION = "sonora-dsp/2"
TRACKS = {"dialogue", "music", "effects", "residual", "original"}


def _boolean(value: bool, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} deve essere un valore booleano.")
    return value


def _automation_points(points: list[dict], name: str, frames: int, minimum: float,
                       maximum: float) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(points, list) or len(points) > 2000:
        raise ValueError(f"La curva {name} deve contenere fino a 2000 punti.")
    positions, values = [], []
    for point in points:
        if not isinstance(point, dict):
            raise ValueError(f"Punto automazione {name} non valido.")
        sample = point.get("sample")
        if type(sample) is not int or not 0 <= sample < frames or (positions and sample <= positions[-1]):
            raise ValueError(f"I campioni della curva {name} devono essere univoci, crescenti e interni alla timeline.")
        value = point.get("value")
        if name == "mute" and type(value) is bool:
            value = int(value)
        values.append(number(value, f"Valore automazione {name}", minimum, maximum))
        positions.append(sample)
    return np.asarray(positions, dtype=np.int64), np.asarray(values)


@dataclass
class _Filter:
    b: np.ndarray
    a: np.ndarray
    state: np.ndarray

    def apply(self, data: np.ndarray) -> np.ndarray:
        result, self.state = signal.lfilter(self.b, self.a, data, axis=0, zi=self.state)
        return result


@dataclass
class _Compressor:
    rate: int
    threshold: float
    ratio: float
    knee: float
    attack: float
    release: float
    makeup: float
    current_db: float = 0
    max_reduction_db: float = 0

    def apply(self, data: np.ndarray) -> np.ndarray:
        step = 32
        block_peak = np.max(np.abs(data), axis=1)
        offsets = np.arange(0, len(data), step)
        peaks = np.maximum.reduceat(block_peak, offsets)
        levels = 20 * np.log10(np.maximum(peaks, 1e-12))
        delta = levels - self.threshold
        factor = 1 / self.ratio - 1
        curve = factor * np.maximum(0, delta)
        if self.knee:
            in_knee = np.abs(delta) < self.knee / 2
            curve[in_knee] = factor * (delta[in_knee] + self.knee / 2) ** 2 / (2 * self.knee)
        lengths = np.diff(np.r_[offsets, len(data)])
        attack_coeff = np.exp(-lengths / (self.attack * self.rate / 1000))
        release_coeff = np.exp(-lengths / (self.release * self.rate / 1000))
        gains = np.empty(len(peaks) + 1)
        gains[0] = self.current_db
        current = self.current_db
        for index, target in enumerate(curve):
            coeff = attack_coeff[index] if target < current else release_coeff[index]
            current = float(target + coeff * (current - target))
            gains[index + 1] = current
        self.current_db = current
        self.max_reduction_db = max(self.max_reduction_db, float(-gains.min()))
        interpolated = np.interp(np.arange(len(data)), np.r_[offsets, len(data)], gains)
        return data * np.power(10, (interpolated[:, None] + self.makeup) / 20)


class _Chain:
    def __init__(self, config: dict, rate: int, channels: int, frames: int, *, master: bool = False,
                 residual: bool = False):
        if not isinstance(config, dict):
            raise ValueError("Le impostazioni di un canale devono essere un oggetto JSON.")
        common = {"gain_db", "trim_db", "bypass", "eq", "compressor"}
        allowed = common | ({"ceiling_dbtp", "limiter"} if master else {"pan", "mute", "solo", "polarity", "automation"})
        unknown = config.keys() - allowed
        if unknown:
            raise ValueError(f"Impostazioni del mixer sconosciute: {', '.join(sorted(unknown))}.")
        self.bypass = _boolean(config.get("bypass", False), "Bypass")
        self.gain = number(config.get("gain_db", 0), "Fader in dB", -120, 36)
        self.trim = number(config.get("trim_db", 0), "Trim in dB", -80, 36)
        self.pan = number(config.get("pan", 0), "Pan/balance", -1, 1)
        self.mute = _boolean(config.get("mute", residual), "Mute")
        self.solo = _boolean(config.get("solo", False), "Solo")
        self.polarity = -1 if _boolean(config.get("polarity", False), "Inverti polarità") else 1
        self.ceiling = number(config["ceiling_dbtp"], "Ceiling in dBTP", -30, 0) if config.get("ceiling_dbtp") is not None else None
        self.automation = {}
        self.rate = rate
        automation = config.get("automation")
        if automation is None:
            automation = {}
        if not isinstance(automation, dict):
            raise ValueError("L'automazione deve essere un oggetto JSON.")
        bounds = {"gain_db": (-120, 36), "pan": (-1, 1), "mute": (0, 1)}
        for key, points in automation.items():
            if key not in bounds:
                raise ValueError(f"Automazione {key} non supportata.")
            samples, values = _automation_points(points, key, frames, *bounds[key])
            if len(samples):
                self.automation[key] = samples, values
        self.filters = []
        eq = config.get("eq")
        if eq is None:
            eq = []
        if isinstance(eq, dict):
            eq = [eq]
        if not isinstance(eq, list) or len(eq) > 8:
            raise ValueError("L'equalizzatore deve contenere fino a 8 bande.")
        for band in eq:
            if not isinstance(band, dict):
                raise ValueError("Banda EQ non valida.")
            frequency = number(band.get("frequency_hz", 1000), "Frequenza EQ", 10, rate * 0.49)
            gain = number(band.get("gain_db", 0), "Guadagno EQ in dB", -24, 24)
            q = number(band.get("q", 1), "Q", 0.1, 25)
            if gain:
                b, a = peaking_eq(rate, frequency, gain, q)
                self.filters.append(_Filter(b, a, np.zeros((2, channels))))
        compressor = config.get("compressor")
        self.compressor = None
        if compressor is not None:
            if not isinstance(compressor, dict):
                raise ValueError("Il compressore deve essere un oggetto JSON o null.")
            self.compressor = _Compressor(
                rate=rate,
                threshold=number(compressor.get("threshold_db", -18), "Soglia in dBFS", -80, 0),
                ratio=number(compressor.get("ratio", 3), "Rapporto", 1, 20),
                knee=number(compressor.get("knee_db", 6), "Knee in dB", 0, 40),
                attack=number(compressor.get("attack_ms", 10), "Attacco in ms", 0.1, 1000),
                release=number(compressor.get("release_ms", 100), "Rilascio in ms", 0.1, 5000),
                makeup=number(compressor.get("makeup_db", 0), "Makeup in dB", -24, 24),
            )

    @property
    def pans_mono(self) -> bool:
        return self.pan != 0 or "pan" in self.automation

    @property
    def gain_reduction(self) -> float | None:
        return self.compressor.max_reduction_db if self.compressor is not None and not self.bypass else None

    def apply(self, data: np.ndarray, start: int, *, output_channels: int) -> np.ndarray:
        if self.mute:
            return np.zeros((len(data), output_channels), dtype=np.float64)
        position = np.arange(start, start + len(data)) if self.automation else None
        fader = self.gain
        pan = self.pan
        if "gain_db" in self.automation:
            fader = np.interp(position, *self.automation["gain_db"])[:, None]
        if "pan" in self.automation:
            pan = np.interp(position, *self.automation["pan"])
        if self.trim:
            data = data * 10 ** (self.trim / 20)
        if not self.bypass:
            for filter_ in self.filters:
                data = filter_.apply(data)
            if self.compressor is not None:
                data = self.compressor.apply(data)
        if np.any(fader) or self.polarity < 0:
            data = data * (self.polarity * np.power(10, fader / 20))
        if "mute" in self.automation:
            samples, values = self.automation["mute"]
            # Make each 0/1 transition a click-resistant 5 ms ramp; neighboring points may shorten it.
            fade = np.r_[np.minimum(samples[:-1] + max(1, round(self.rate * 0.005)), samples[1:]),
                         samples[-1] + max(1, round(self.rate * 0.005))]
            xp = np.ravel(np.column_stack((samples, fade)))
            fp = np.ravel(np.column_stack((np.r_[values[0], values[:-1]], values)))
            data = data * (1 - np.interp(position, xp, fp))[:, None]
        if data.shape[1] == 1 and output_channels == 2:
            angle = (pan + 1) * np.pi / 4
            left, right = np.cos(angle), np.sin(angle)
            return data * np.stack((left, right), axis=-1)
        if output_channels == 2 and np.any(pan):
            left, right = 1 - np.maximum(pan, 0), 1 + np.minimum(pan, 0)
            return data * np.stack((left, right), axis=-1)
        return data


def render_mix(inputs: dict[str, Path], destination: Path, config: dict, *,
               progress: Progress = None, cancelled: Cancelled = None) -> dict:
    """Use the same authoritative renderer for preview and final master."""
    if not inputs or set(inputs) - TRACKS:
        raise ValueError("Selezionare almeno una traccia riconosciuta del mixer.")
    if not isinstance(config, dict) or config.keys() - {"tracks", "master"}:
        raise ValueError("Configurazione del mixer non valida.")
    settings = config.get("tracks", {})
    if not isinstance(settings, dict) or set(settings) - TRACKS:
        raise ValueError("Impostazioni delle tracce non valide.")

    with ExitStack() as stack:
        audios = {stem: stack.enter_context(sf.SoundFile(path)) for stem, path in sorted(inputs.items())}
        guide = next(iter(audios.values()))
        timeline = guide.samplerate, guide.frames, guide.channels
        rate, frames, input_channels = timeline
        if input_channels not in (1, 2) or frames == 0 or any(
            (audio.samplerate, audio.frames, audio.channels) != timeline for audio in audios.values()
        ):
            raise ValueError("Il mixer richiede asset mono o stereo con timeline e canali identici.")
        chains = {stem: _Chain(settings.get(stem, {}), rate, input_channels, frames, residual=stem == "residual")
                  for stem in audios}
        has_solo = any(chain.solo for chain in chains.values())
        selected = {stem: chain for stem, chain in chains.items() if not chain.mute and (not has_solo or chain.solo)}
        channels = 2 if input_channels == 2 or any(chain.pans_mono for chain in selected.values()) else 1
        master_config = config.get("master", {})
        master = _Chain(master_config, rate, channels, frames, master=True)
        limiter = LimiterSettings.parse(master_config.get("limiter"))
        active = limiter.enabled and not master.bypass
        ceiling = -1.0 if limiter.enabled and master.ceiling is None else master.ceiling
        limiter_info = limiter.describe(active=False)
        track_metrics = {stem: SignalMetrics(channels) for stem in audios}
        master_metrics = SignalMetrics(channels)
        with atomic_destination(destination, suffix=".wav") as temporary:
            render_path = temporary
            if active:
                scratch = stack.enter_context(TemporaryDirectory(prefix=".limiter-", dir=destination.parent))
                render_path = Path(scratch, "unlimited.wav")
            with float_writer(render_path, rate, channels, frames) as writer:
                for start in range(0, frames, BLOCK):
                    check_cancel(cancelled)
                    count = min(BLOCK, frames - start)
                    mixed = np.zeros((count, channels), dtype=np.float64)
                    for stem, chain in selected.items():
                        block = audios[stem].read(count, dtype="float64", always_2d=True)
                        require_finite(block)
                        processed = chain.apply(block, start, output_channels=channels)
                        require_finite(processed)
                        track_metrics[stem].feed(processed)
                        mixed += processed
                    result = master.apply(mixed, start, output_channels=channels).astype(np.float32)
                    require_finite(result)
                    if not active:
                        master_metrics.feed(result)
                    writer.write(result)
                    if progress:
                        progress(start + count, frames)
            if active:
                metrics, measures, limiter_info = limit_master(render_path, temporary, ceiling=ceiling,
                                                                settings=limiter, cancelled=cancelled)
            else:
                metrics = master_metrics.as_dict()
                measures = loudness(temporary, peak=metrics["sample_peak"], cancelled=cancelled)
            check_cancel(cancelled)
        warnings = []
        if metrics["samples_at_or_above_full_scale"]:
            warnings.append("Il master float arriva a fondo scala o lo supera. Verificare il gain prima di esportare in PCM.")
        ceiling_exceeded = None
        true_peak = limiter_info["measured_true_peak_dbtp"] if active else measures["true_peak_dbtp"]
        if ceiling is not None:
            if active and true_peak is None and metrics["sample_peak"] == 0:
                ceiling_exceeded = False
            elif true_peak is None:
                warnings.append("Il ceiling non è verificabile. Misura true peak non disponibile.")
            else:
                ceiling_exceeded = true_peak > ceiling
                if ceiling_exceeded:
                    warnings.append("True peak sopra il ceiling dichiarato. Regolare il master e ricalcolare.")
        metadata = audio_info(guide)
        metadata.update(channels=channels, channel_layout="stereo" if channels == 2 else "mono",
                        channel_order=["L", "R"] if channels == 2 else ["C"])
        meters = {**metrics, "true_peak_dbtp": true_peak,
                  "loudness": measures, "gain_reduction_db": master.gain_reduction}
        return {
            **metadata,
            **meters,
            "metrics": meters,
            "algorithm_version": VERSION,
            "ceiling_dbtp": ceiling,
            "ceiling_exceeded": ceiling_exceeded,
            "limiter": limiter_info,
            "residual_included": "residual" in selected,
            "tracks": {stem: {**meter.as_dict(), "gain_reduction_db": chains[stem].gain_reduction,
                              "included": stem in selected} for stem, meter in track_metrics.items()},
            "warnings": warnings,
        }
