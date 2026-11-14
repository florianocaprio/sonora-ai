"""Heuristic analysis with explicit stem-specific thresholds and sample regions."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from .io import BLOCK, Cancelled, Progress, audio_info, check_cancel, require_finite, sample_region
from .metrics import SignalMetrics, db, loudness, unavailable_loudness

MAX_EVENTS = 512
VERSION = "sonora-detectors/1"

STEM_PROFILES = {
    "original": {"impulse_factor": 10.0, "silence_dbfs": -78.0, "hum_ratio": 0.32},
    "dialogue": {"impulse_factor": 8.0, "silence_dbfs": -76.0, "hum_ratio": 0.25},
    "music": {"impulse_factor": 16.0, "silence_dbfs": -85.0, "hum_ratio": 0.55},
    "effects": {"impulse_factor": 20.0, "silence_dbfs": -90.0, "hum_ratio": 0.62},
    "residual": {"impulse_factor": 14.0, "silence_dbfs": -83.0, "hum_ratio": 0.42},
    "master": {"impulse_factor": 12.0, "silence_dbfs": -80.0, "hum_ratio": 0.42},
    "difference": {"impulse_factor": 14.0, "silence_dbfs": -83.0, "hum_ratio": 0.42},
}
DEPTHS = {"quick": (0.5, 2.0), "standard": (0.25, 1.0), "deep": (0.125, 0.5)}
DEPTH_ALIASES = {"rapid": "quick", "rapida": "quick", "approfondita": "deep"}


def _runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    transitions = np.diff(np.r_[False, mask, False].astype(np.int8))
    return np.flatnonzero(transitions == 1), np.flatnonzero(transitions == -1)


def _operation(kind: str, start: int, end: int, params: dict | None = None, *, wet: float = 1.0) -> dict:
    return {"type": kind, "start_sample": start, "end_sample": end,
            "wet": wet, "bypass": False, "params": params or {}}


def _event(kind: str, start: int, end: int, *, severity: float, confidence: float,
           evidence: dict, proposed: dict | None = None) -> dict:
    return {
        "type": kind,
        "start_sample": start,
        "end_sample": end,
        "severity": severity,
        "confidence": confidence,
        "confidence_kind": "heuristic_score",
        "evidence": evidence,
        "detector": VERSION,
        "origin": "unknown",
        "status": "unreviewed",
        "proposed_operation": proposed,
    }


@lru_cache(maxsize=24)
def _spectrum_window(size: int) -> np.ndarray:
    return np.hanning(size)[:, None]


@dataclass
class _Spectrum:
    rate: int
    fft_size: int
    noise_log: np.ndarray
    power: np.ndarray
    hum_frames: int = 0
    spectral_frames: int = 0

    def feed(self, block: np.ndarray) -> tuple[int | None, float]:
        block = block[np.isfinite(block).all(axis=1)]
        if len(block) < max(32, self.rate // 4):
            return None, 0.0
        zero_mean = block - block.mean(axis=0)
        window = _spectrum_window(len(block))
        transform = np.fft.rfft(zero_mean * window, n=self.fft_size, axis=0)
        power = (np.abs(transform) ** 2).sum(axis=1)
        total = float(power.sum())
        if total <= 0:
            return None, 0.0
        self.power += power / total
        self.spectral_frames += 1
        maximum = float(power.max())
        frequency = np.fft.rfftfreq(self.fft_size, 1 / self.rate)
        candidates = []
        for hum in (50, 60):
            band = np.abs(frequency - hum) <= 2.5
            if band.any():
                candidates.append((hum, float(power[band].max() / maximum), float(power[band].sum() / total)))
        frequency_hz, relative, energy = max(candidates, key=lambda item: item[2], default=(None, 0.0, 0.0))
        return frequency_hz, min(relative, energy * 4)

    def quiet_floor(self, data: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
        level = db(rms)
        if level is not None:
            self.noise_log[int(np.clip(np.floor(level) + 150, 0, len(self.noise_log) - 1))] += 1

    def summary(self) -> dict:
        floor = None
        windows = int(self.noise_log.sum())
        if windows:
            floor = int(np.searchsorted(np.cumsum(self.noise_log), max(1, windows * 0.1))) - 150
        band = None
        if self.spectral_frames:
            cumulative = np.cumsum(self.power)
            bin_ = int(np.searchsorted(cumulative, cumulative[-1] * 0.95))
            band = bin_ * self.rate / self.fft_size
        return {
            "noise_floor_estimate_dbfs": floor,
            "noise_floor_definition": "10° percentile dell'RMS escluso il silenzio digitale, bin da 1 dB.",
            "spectral_energy_95_hz": band,
            "spectral_windows": self.spectral_frames,
        }


def _impulses(samples: np.ndarray, start: int, profile: dict, sensitivity: float) -> list[dict]:
    if len(samples) < 3:
        return []
    const = profile["impulse_factor"] * (1.45 - 0.9 * sensitivity)
    delta = samples[1:-1] - (samples[:-2] + samples[2:]) * 0.5
    median = np.median(np.abs(delta), axis=0)
    amplitude = np.abs(delta)
    threshold = np.maximum(0.018, median * const)
    neighbor_delta = np.abs(samples[:-2] - samples[2:])
    isolated = (amplitude >= threshold) & (amplitude > 3 * neighbor_delta)
    anomalies = np.flatnonzero(np.any(isolated, axis=1))
    return [
        _event("impulse", start + int(index) + 1, start + int(index) + 2,
               severity=float(np.clip(amplitude[index].max() * 2, 0.05, 1)),
               confidence=0.55, evidence={"deviation": float(amplitude[index].max()), "threshold": float(threshold.max())},
               proposed=_operation("declick", start + int(index) + 1, start + int(index) + 2,
                                   {"threshold": float(threshold.min())}))
        for index in anomalies[:MAX_EVENTS + 1]
    ]


def _dropouts(samples: np.ndarray, start: int, rate: int, profile: dict) -> list[dict]:
    level = 10 ** (profile["silence_dbfs"] / 20)
    silent = np.max(np.abs(samples), axis=1) < level
    gaps = []
    starts, stops = _runs(silent)
    context = max(1, rate // 250)
    minimum = max(2, rate // 2000)
    maximum = max(minimum, rate // 50)
    for left, right in zip(starts, stops, strict=True):
        length = int(right - left)
        if not (minimum <= length <= maximum and left >= context and right + context <= len(samples)):
            continue
        neighbor = min(np.max(np.abs(samples[left - context:left])), np.max(np.abs(samples[right:right + context])))
        if neighbor < 0.015:
            continue
        first, last = start + int(left), start + int(right)
        gaps.append(_event("possible_microgap", first, last, severity=min(1.0, length / maximum), confidence=0.6,
                           evidence={"nearby_peak": float(neighbor), "duration_ms": length * 1000 / rate},
                           proposed=_operation("microgap", first, last, {"max_duration_ms": 20.0})))
        if len(gaps) > MAX_EVENTS:
            break
    return gaps


def analyze(source: Path, stem: str, *, start_sample: int = 0, end_sample: int | None = None,
            sensitivity: float = 0.5, depth: str = "standard", progress: Progress = None,
            cancelled: Cancelled = None) -> dict:
    """Analyze a region without editing signal, limiting the number of reported markers."""
    if stem not in STEM_PROFILES:
        raise ValueError("Profilo di analisi sconosciuto.")
    if type(sensitivity) not in (float, int) or not np.isfinite(sensitivity) or not 0 <= sensitivity <= 1:
        raise ValueError("La sensibilità deve essere compresa tra 0 e 1.")
    depth = DEPTH_ALIASES.get(depth, depth)
    if depth not in DEPTHS:
        raise ValueError("Scegliere profondità quick, standard o deep.")
    profile = STEM_PROFILES[stem]
    events: list[dict] = []
    truncated = 0
    above_scale = 0
    newest: dict[str, dict] = {}

    def record(event: dict, *, group: str | None = None) -> None:
        nonlocal truncated
        if group:
            previous = newest.get(group)
            if previous is not None and event["start_sample"] <= previous["end_sample"]:
                previous["end_sample"] = max(previous["end_sample"], event["end_sample"])
                previous["severity"] = max(previous["severity"], event["severity"])
                if previous.get("proposed_operation"):
                    previous["proposed_operation"]["end_sample"] = previous["end_sample"]
                return
            newest[group] = event
        if len(events) < MAX_EVENTS:
            events.append(event)
        else:
            truncated += 1

    with sf.SoundFile(source) as audio:
        rate = audio.samplerate
        start, end = sample_region(start_sample, end_sample, audio.frames)
        frames = end - start
        info = audio_info(audio, frames=frames)
        whole_file = start == 0 and end == audio.frames
        window_seconds, spectrum_seconds = DEPTHS[depth]
        blocksize = max(1, round(window_seconds * rate))
        spectrum_interval = max(1, round(spectrum_seconds / window_seconds))
        fft_size = 1 << max(128, rate).bit_length()
        metrics = SignalMetrics(audio.channels)
        spectrum = _Spectrum(rate, fft_size, np.zeros(220, dtype=np.int64), np.zeros(fft_size // 2 + 1))
        # One halo around each window avoids losing impulsive samples and short gaps at block borders.
        halo = max(2, rate // 40)
        for count, cursor in enumerate(range(start, end, blocksize)):
            check_cancel(cancelled)
            stop = min(cursor + blocksize, end)
            left, right = max(start, cursor - halo), min(end, stop + halo)
            audio.seek(left)
            samples = audio.read(right - left, dtype="float32", always_2d=True)
            block = samples[cursor - left:stop - left]
            metrics.feed(block)
            finite = np.isfinite(samples).all()
            if not finite:
                mask = ~np.isfinite(block).all(axis=1)
                for first, last in zip(*_runs(mask), strict=True):
                    record(_event("invalid_samples", cursor + int(first), cursor + int(last),
                                  severity=1.0, confidence=1.0, evidence={"non_finite": int(last - first)}),
                           group="invalid_samples")
            else:
                for event in _impulses(samples, left, profile, sensitivity):
                    if cursor <= event["start_sample"] < stop:
                        record(event)
                for event in _dropouts(samples, left, rate, profile):
                    if cursor <= event["start_sample"] < stop:
                        record(event)
                near = np.abs(samples) >= 0.97
                identical = (samples[1:] == samples[:-1]) & near[1:] & near[:-1]
                for first, last in zip(*_runs(identical.sum(axis=1) > 0), strict=True):
                    if last - first >= 2 and left + int(last) >= cursor and left + int(first) < stop:
                        record(_event("possible_flat_top", left + int(first), left + int(last) + 1, severity=0.85,
                                      confidence=0.72, evidence={"plateau_samples": int(last - first) + 1}),
                               group="clip")
                spectrum.quiet_floor(block)
                if count % spectrum_interval == 0:
                    # A half-second analysis window resolves 50/60 Hz even in the deepest temporal profile.
                    spectral_length = min(rate // 2, frames)
                    spectral_start = max(start, min(cursor, end - spectral_length))
                    audio.seek(spectral_start)
                    spectral = audio.read(spectral_length, dtype="float32", always_2d=True)
                    frequency, score = spectrum.feed(spectral)
                    if frequency is not None and score >= profile["hum_ratio"] * (1.35 - sensitivity * 0.6):
                        record(_event("possible_hum", cursor, stop, severity=min(1.0, score), confidence=0.6,
                                      evidence={"frequency_hz": frequency, "tonal_score": score},
                                      proposed=_operation("dehum", cursor, stop, {"frequency_hz": frequency, "q": 24.0})),
                               group=f"hum-{frequency}")
            above_scale += int(np.count_nonzero(np.abs(block) > 1.0))
            if progress:
                progress(stop - start, frames)
        check_cancel(cancelled)

    measured = {**metrics.as_dict(), **spectrum.summary(), "samples_over_full_scale": above_scale}
    offset = measured["dc_offset"]
    if offset is not None and max(map(abs, offset)) > 0.0035 * (1.4 - sensitivity * 0.6):
        record(_event("dc_offset", start, end, severity=min(1.0, max(map(abs, offset)) * 15),
                      confidence=0.82, evidence={"mean_by_channel": offset},
                      proposed=_operation("dc_remove", start, end)))
    if whole_file and not measured["non_finite_values"]:
        measured["loudness"] = loudness(source, peak=measured["sample_peak"], cancelled=cancelled)
    elif measured["non_finite_values"]:
        measured["loudness"] = unavailable_loudness("L'asset contiene campioni non finiti.")
    else:
        measured["loudness"] = unavailable_loudness("Misure loudnorm disponibili solo per l'asset intero.")
    return {
        **info,
        "metrics": measured,
        "events": sorted(events, key=lambda event: (event["start_sample"], event["end_sample"], event["type"])),
        "truncated_events": truncated,
        "settings": {"stem": stem, "depth": depth, "sensitivity": sensitivity,
                     "start_sample": start, "end_sample": end, "profile": profile,
                     "window_seconds": window_seconds, "spectrum_stride_seconds": spectrum_seconds,
                     "detector": VERSION},
    }


def waveform(source: Path, bins: int = 512, *, start_sample: int = 0,
             end_sample: int | None = None) -> list[float]:
    if type(bins) is not int or not 1 <= bins <= 4096:
        raise ValueError("Il numero di intervalli waveform deve essere tra 1 e 4096.")
    with sf.SoundFile(source) as audio:
        start, end = sample_region(start_sample, end_sample, audio.frames)
        audio.seek(start)
        result = np.zeros(bins, dtype=np.float32)
        frames = end - start
        cursor = 0
        for block in audio.blocks(frames=frames, blocksize=BLOCK, dtype="float32", always_2d=True):
            require_finite(block)
            indices = np.arange(cursor, cursor + len(block), dtype=np.int64) * bins // frames
            np.maximum.at(result, indices, np.max(np.abs(block), axis=1))
            cursor += len(block)
        return result.tolist()


def spectrogram(source: Path, *, start_sample: int = 0, end_sample: int | None = None,
                columns: int = 160, fft_size: int = 512) -> dict:
    """Return a bounded tile of Hann-window magnitude in dBFS with linear frequencies."""
    if type(columns) is not int or not 1 <= columns <= 512 or type(fft_size) is not int or fft_size not in (
        128, 256, 512, 1024, 2048, 4096
    ):
        raise ValueError("Risoluzione dello spettrogramma non valida.")
    spectra = []
    with sf.SoundFile(source) as audio:
        start, end = sample_region(start_sample, end_sample, audio.frames)
        positions = start + np.arange(columns, dtype=np.int64) * (end - start) // columns
        window = _spectrum_window(fft_size)
        for center in positions:
            left, right = int(center) - fft_size // 2, int(center) + fft_size // 2
            first, last = max(0, left), min(audio.frames, right)
            data = np.zeros((fft_size, audio.channels), dtype=np.float64)
            audio.seek(first)
            data[first - left:last - left] = audio.read(last - first, dtype="float64", always_2d=True)
            require_finite(data)
            transform = np.abs(np.fft.rfft(data * window, axis=0)).max(axis=1) * 2 / window.sum()
            transform[0] *= 0.5
            transform[-1] *= 0.5
            spectra.append((20 * np.log10(np.maximum(transform, 10**-6))).round(1).tolist())
        return {"start_sample": start, "end_sample": end, "columns": spectra, "sample_rate": audio.samplerate,
                "fft_size": fft_size, "frequency_bin_hz": audio.samplerate / fft_size, "minimum_dbfs": -120}
