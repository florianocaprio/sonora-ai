"""Offline sample-aligned true-peak limiting for the master bus."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage, signal
import soundfile as sf

from packages.audio_core.filters import number
from packages.audio_core.io import BLOCK, Cancelled, check_cancel, float_writer, require_finite
from packages.audio_core.metrics import SignalMetrics, db, loudness

OVERSAMPLING = 8
HALO = 64
INTERPOLATOR = OVERSAMPLING * signal.firwin(
    2 * HALO * OVERSAMPLING + 1, 1 / OVERSAMPLING, window=("kaiser", 10.0),
)
DETECTOR_MARGIN_DB = 0.20
VERIFICATION_MARGIN_DB = 0.05


@dataclass(frozen=True)
class LimiterSettings:
    enabled: bool = False
    lookahead_ms: float = 5.0
    release_ms: float = 80.0

    @classmethod
    def parse(cls, config: dict | None) -> "LimiterSettings":
        if config is None:
            return cls()
        if not isinstance(config, dict) or config.keys() - {"enabled", "lookahead_ms", "release_ms"}:
            raise ValueError("Le impostazioni del limiter non sono valide.")
        enabled = config.get("enabled", False)
        if type(enabled) is not bool:
            raise ValueError("L'attivazione del limiter deve essere un valore booleano.")
        return cls(enabled, number(config.get("lookahead_ms", 5), "Lookahead del limiter in ms", 1, 20),
                   number(config.get("release_ms", 80), "Rilascio del limiter in ms", 10, 1000))

    def describe(self, *, active: bool) -> dict:
        return {
            "enabled": self.enabled, "active": active, "lookahead_ms": self.lookahead_ms,
            "release_ms": self.release_ms, "oversampling": OVERSAMPLING if active else None,
            "detector_margin_db": DETECTOR_MARGIN_DB if active else None,
            "gain_reduction_db": None, "verification_trim_db": None, "measured_true_peak_dbtp": None,
        }


def _frame_peaks(audio: sf.SoundFile, start: int, end: int) -> tuple[np.ndarray, np.ndarray]:
    """Return original frames and the linked peak across their reconstruction phases."""
    left = max(0, start - HALO)
    right = min(audio.frames, end + HALO)
    audio.seek(left)
    data = audio.read(right - left, dtype="float64", always_2d=True)
    require_finite(data)
    interpolated = signal.upfirdn(INTERPOLATOR, data, up=OVERSAMPLING, axis=0)
    first = (start - left + HALO) * OVERSAMPLING
    last = first + (end - start) * OVERSAMPLING
    phases = interpolated[first:last].reshape(end - start, OVERSAMPLING, audio.channels)
    samples = data[start - left:end - left]
    peaks = np.maximum(np.max(np.abs(phases), axis=(1, 2)), np.max(np.abs(samples), axis=1))
    return samples, peaks


def _release_gain(target: np.ndarray, attenuation: float, release_samples: float) -> tuple[np.ndarray, float]:
    """Apply d[n] = max(1 - target[n], d[n-1] exp(-1 / release_samples))."""
    attenuation_curve = np.empty_like(target)
    # Bound each exponent so extreme settings never overflow.
    step = int(release_samples * 64)
    for offset in range(0, len(target), step):
        group = target[offset:offset + step]
        exponent = np.exp(np.arange(1, len(group) + 1) / release_samples)
        weighted = np.maximum(attenuation, (1 - group) * exponent)
        current = np.maximum.accumulate(weighted) / exponent
        attenuation_curve[offset:offset + len(group)] = current
        attenuation = float(current[-1])
    return np.clip(1 - attenuation_curve, 0, 1), attenuation


def _apply_envelope(source: Path, destination: Path, ceiling: float,
                    settings: LimiterSettings, cancelled: Cancelled) -> float | None:
    minimum_gain = 1.0
    attenuation = 0.0
    amplitude = 10 ** ((ceiling - DETECTOR_MARGIN_DB) / 20)
    with sf.SoundFile(source) as audio:
        lookahead = max(1, round(audio.samplerate * settings.lookahead_ms / 1000))
        release = audio.samplerate * settings.release_ms / 1000
        window = lookahead + 1
        with float_writer(destination, audio.samplerate, audio.channels, audio.frames) as writer:
            for start in range(0, audio.frames, BLOCK):
                check_cancel(cancelled)
                end = min(audio.frames, start + BLOCK)
                first = max(0, start - lookahead)
                last = min(audio.frames, end + lookahead)
                samples, peaks = _frame_peaks(audio, first, last)
                upcoming = ndimage.maximum_filter1d(peaks, size=window, origin=-(window // 2), mode="constant")
                target = amplitude / np.maximum(amplitude, upcoming)
                # Each member of the trailing average already accounts for the current peak.
                attack = ndimage.uniform_filter1d(target, size=window, origin=(window - 1) // 2, mode="nearest")
                local = slice(start - first, end - first)
                gain, attenuation = _release_gain(attack[local], attenuation, release)
                minimum_gain = min(minimum_gain, float(gain.min()))
                writer.write((samples[local] * gain[:, None]).astype(np.float32))
            check_cancel(cancelled)
    return float(-20 * np.log10(minimum_gain)) if minimum_gain > 0 else None


def _scan(source: Path, cancelled: Cancelled) -> tuple[dict, float | None]:
    peak = 0.0
    with sf.SoundFile(source) as audio:
        if audio.channels not in (1, 2) or audio.frames == 0:
            raise ValueError("La misura true peak richiede un asset mono o stereo con almeno un campione.")
        metrics = SignalMetrics(audio.channels)
        for start in range(0, audio.frames, BLOCK):
            check_cancel(cancelled)
            samples, peaks = _frame_peaks(audio, start, min(audio.frames, start + BLOCK))
            metrics.feed(samples)
            peak = max(peak, float(peaks.max()))
    return metrics.as_dict(), db(peak)


def measure_true_peak(source: Path, *, cancelled: Cancelled = None) -> float | None:
    """Measure native 8× reconstructed true peak on a reopenable mono/stereo asset."""
    return _scan(source, cancelled)[1]


def _measure(source: Path, cancelled: Cancelled) -> tuple[dict, dict, float | None, float | None, float | None]:
    measured, native = _scan(source, cancelled)
    broadcast = loudness(source, peak=measured["sample_peak"], cancelled=cancelled)
    reference = broadcast["true_peak_dbtp"]
    maximum = max((value for value in (native, reference) if value is not None), default=None)
    return measured, broadcast, native, reference, maximum


def limit_master(source: Path, destination: Path, *, ceiling: float,
                 settings: LimiterSettings, cancelled: Cancelled) -> tuple[dict, dict, dict]:
    """Render and verify float output before the mixer's outer atomic publish."""
    reduction = _apply_envelope(source, destination, ceiling, settings, cancelled)
    metrics, broadcast, native, reference, maximum = _measure(destination, cancelled)
    trim = 0.0
    if maximum is not None and maximum > ceiling:
        trim = maximum - ceiling + VERIFICATION_MARGIN_DB
        amplitude = 10 ** (-trim / 20)
        with sf.SoundFile(destination) as audio, float_writer(
            destination, audio.samplerate, audio.channels, audio.frames,
        ) as writer:
            for block in audio.blocks(blocksize=BLOCK, dtype="float64", always_2d=True):
                check_cancel(cancelled)
                writer.write((block * amplitude).astype(np.float32))
        metrics, broadcast, native, reference, maximum = _measure(destination, cancelled)
        if maximum is not None and maximum > ceiling:
            raise RuntimeError("Il limiter non ha rispettato il ceiling misurato. Il master non è stato pubblicato.")
    return metrics, broadcast, {
        **settings.describe(active=True),
        "algorithm": "sonora-true-peak-limiter/1",
        "gain_reduction_db": reduction + trim if reduction is not None else None,
        "verification_trim_db": trim,
        "measured_true_peak_dbtp": maximum,
        "native_true_peak_dbtp": native,
        "reference_true_peak_dbtp": reference,
    }
