"""Streaming signal measures and optional FFmpeg broadcast measurements."""

from math import log10, sqrt
from pathlib import Path
import json
import re
import shutil

import numpy as np
import soundfile as sf

from .io import Cancelled, _process


def db(value: float) -> float | None:
    return 20 * log10(value) if value > 0 else None


class SignalMetrics:
    def __init__(self, channels: int):
        self.channels = channels
        self.samples = 0
        self.peak = np.zeros(channels)
        self.sums = np.zeros(channels)
        self.squares = np.zeros(channels)
        self.cross = 0.0
        self.nonfinite = 0
        self.clip_risk = 0

    def feed(self, block: np.ndarray) -> None:
        self.samples += len(block)
        finite = np.isfinite(block)
        self.nonfinite += int(np.count_nonzero(~finite))
        data = np.where(finite, block, 0).astype(np.float64, copy=False)
        self.peak = np.maximum(self.peak, np.max(np.abs(data), axis=0))
        self.sums += data.sum(axis=0)
        self.squares += np.einsum("ij,ij->j", data, data)
        self.clip_risk += int(np.count_nonzero(np.abs(data) >= 1))
        if self.channels == 2:
            self.cross += float(np.dot(data[:, 0], data[:, 1]))

    def as_dict(self) -> dict:
        peak = float(self.peak.max())
        number = self.samples * self.channels - self.nonfinite
        rms = sqrt(float(self.squares.sum()) / number) if number else 0.0
        dc = (self.sums / self.samples).tolist() if number and not self.nonfinite else None
        correlation = balance = None
        if self.channels == 2 and self.samples and not self.nonfinite:
            left, right = self.squares
            if min(left, right) > 0:
                balance = 10 * log10(float(right / left))
                centered = self.squares - self.sums**2 / self.samples
                if min(centered) > 0:
                    correlation = float(np.clip(
                        (self.cross - self.sums[0] * self.sums[1] / self.samples) /
                        sqrt(float(centered[0] * centered[1])), -1, 1
                    ))
        return {
            "sample_peak": peak if number else None,
            "sample_peak_dbfs": db(peak) if number else None,
            "rms_dbfs": db(rms),
            "crest_factor_db": db(peak / rms) if rms else None,
            "dc_offset": dc,
            "non_finite_values": self.nonfinite,
            "samples_at_or_above_full_scale": self.clip_risk,
            "stereo_correlation": correlation,
            "stereo_balance_db": balance,
        }


_LOUDNESS_KEYS = ("integrated_lufs", "true_peak_dbtp", "lra_lu", "momentary_lufs", "short_term_lufs")


def unavailable_loudness(reason: str) -> dict:
    return {**dict.fromkeys(_LOUDNESS_KEYS), "backend": None, "reason": reason}


def _tail_loudness(ffmpeg: str, source: Path, duration: float, cancelled: Cancelled) -> tuple[float | None, float | None]:
    # Scan at most the last four seconds to bound the 10 Hz FFmpeg log.
    if duration < 0.4:
        return None, None
    _, output = _process([
        ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-v", "info", "-protocol_whitelist", "file",
        "-ss", f"{max(0, duration - 4.0):.9f}", "-i", str(source.resolve()), "-map", "0:a:0",
        "-af", "ebur128=framelog=info", "-f", "null", "-",
    ], timeout=30, cancelled=cancelled)
    matches = re.findall(r"M:\s*(-?[\d.]+)\s+S:\s*(-?[\d.]+)", output)
    if not matches:
        return None, None
    momentary, short_term = map(float, matches[-1])
    return (momentary if momentary > -120 else None,
            short_term if short_term > -120 and duration >= 3.0 else None)


def loudness(source: Path, *, peak: float | None, cancelled: Cancelled = None) -> dict:
    """Read FFmpeg's input measurements. Processed normalization output is discarded."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return unavailable_loudness("FFmpeg non disponibile.")
    if not peak:
        return unavailable_loudness("Il segnale è silenzioso o non misurabile.")
    duration = sf.info(source).duration
    try:
        _, output = _process([
            ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-v", "info", "-protocol_whitelist", "file",
            "-i", str(source.resolve()), "-map", "0:a:0", "-af",
            "loudnorm=print_format=json", "-f", "null", "-",
        ], timeout=7200, cancelled=cancelled)
        match = re.search(r'\{\s*"input_i".*?\}', output, flags=re.S)
        if not match:
            raise ValueError("Il filtro loudnorm ha omesso le misure.")
        data = json.loads(match[0])
        measured = {}
        for key, field in zip(_LOUDNESS_KEYS[:3], ("input_i", "input_tp", "input_lra"), strict=True):
            value = float(data[field])
            measured[key] = value if np.isfinite(value) else None
        if duration < 0.4:
            measured["integrated_lufs"] = None
        if duration < 3.0:
            measured["lra_lu"] = None
    except (ValueError, RuntimeError, TimeoutError, KeyError) as error:
        return unavailable_loudness(f"Misura loudnorm non disponibile. {error}")
    try:
        measured["momentary_lufs"], measured["short_term_lufs"] = _tail_loudness(ffmpeg, source, duration, cancelled)
        backend = "FFmpeg loudnorm/ebur128"
        reason = "Alcune finestre hanno durata o energia insufficiente." if None in measured.values() else None
    except (ValueError, RuntimeError, TimeoutError):
        measured.update(momentary_lufs=None, short_term_lufs=None)
        backend = "FFmpeg loudnorm"
        reason = "Misure terminali indisponibili. Verificare il filtro ebur128."
    return {**measured, "backend": backend, "reason": reason}
