"""Shared DSP parameters and peaking biquad design."""

import math

import numpy as np


def number(value: float, name: str, lower: float, upper: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} deve essere compreso tra {lower:g} e {upper:g}.")
    return float(value)


def peaking_eq(rate: int, frequency: float, gain_db: float, q: float) -> tuple[np.ndarray, np.ndarray]:
    """Peaking equalizer from the W3C Audio EQ Cookbook."""
    amplitude = 10 ** (gain_db / 40)
    omega = 2 * math.pi * frequency / rate
    alpha = math.sin(omega) / (2 * q)
    both = -2 * math.cos(omega)
    return (
        np.array([1 + alpha * amplitude, both, 1 - alpha * amplitude]),
        np.array([1 + alpha / amplitude, both, 1 - alpha / amplitude]),
    )
