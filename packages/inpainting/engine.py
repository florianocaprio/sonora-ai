"""Maschera temporale CQT-diffusion su una regione di restauro approvabile."""

from collections import defaultdict
from math import ceil, floor, gcd
from pathlib import Path
import platform
import resource
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from packages.audio_core.io import (
    BLOCK, Cancelled, Progress, audio_info, check_cancel, float_writer, require_finite, sample_region, validate_rate,
)
from packages.model_adapters.registry import ModelUnavailable, checkpoint_path

from .registry import MODEL_ID, manifest, verify_model

MODEL_RATE = 22050
CONTEXT_SAMPLES = 32768
MIN_GAP_MS, MAX_GAP_MS = 20, 250
MIN_SIDE_MS = 250
STEPS = 10

# The pinned upstream file contains OmegaConf training provenance. Its config
# classes may be replaced by inert objects, since the product uses fixed config.
_OMEGACONF_NAMES = (
    "omegaconf.base.Metadata",
    "omegaconf.base.ContainerMetadata",
    "omegaconf.dictconfig.DictConfig",
    "omegaconf.listconfig.ListConfig",
    "omegaconf.nodes.AnyNode",
)
_INERT_METADATA = [
    (type(name.rsplit(".", 1)[-1], (), {}), name) for name in _OMEGACONF_NAMES
]


def _load_denoiser(path: Path):
    import torch

    from ._vendor.network import Unet_CQT_oct_with_attention

    args = SimpleNamespace(
        exp=SimpleNamespace(sample_rate=MODEL_RATE, audio_len=CONTEXT_SAMPLES),
        network=SimpleNamespace(
            cqt=SimpleNamespace(num_octs=7, bins_per_oct=64, window="kaiser", beta=1),
            emb_dim=256, use_norm=True, use_fencoding=False,
            Ns=[64, 96, 96, 128, 128, 256, 256], Ss=[2] * 7,
            num_dils=[2, 3, 4, 5, 6, 7, 7], attention_layers=[0] * 8,
            attention_dict=SimpleNamespace(), bottleneck_type="res_dil_convs", num_bottleneck_layers=1,
        ),
    )
    with torch.serialization.safe_globals([*_INERT_METADATA, defaultdict, list, dict, int, Any]):
        checkpoint = torch.load(path, map_location="cpu", mmap=True, weights_only=True)
    with torch.random.fork_rng(devices=[]):
        model = Unet_CQT_oct_with_attention(args, "cpu")
    model.load_state_dict(checkpoint["ema"], strict=True)
    return model.eval().requires_grad_(False)


def _diffuse(model, signal: np.ndarray, first: int, last: int, *,
             seed: int, progress: Progress, cancelled: Cancelled) -> np.ndarray:
    """EDM preconditioning, Euler sampling, and projection onto observed samples."""
    import torch

    recovered = np.empty_like(signal)
    sigma_data = 0.063
    rho = 13
    schedule = (torch.linspace(1.0, 1e-4 ** (1 / rho), STEPS) ** rho).tolist() + [0.0]
    mask = torch.ones((1, CONTEXT_SAMPLES), dtype=torch.bool)
    mask[:, first:last] = False
    with torch.inference_mode():
        for channel in range(signal.shape[1]):
            observed = torch.from_numpy(signal[:, channel].copy()).reshape(1, -1)
            generator = torch.Generator(device="cpu").manual_seed(seed)
            state = torch.randn(observed.shape, generator=generator) * schedule[0]
            for step, (sigma, following) in enumerate(zip(schedule, schedule[1:]), start=1):
                check_cancel(cancelled)
                magnitude = (sigma * sigma + sigma_data * sigma_data) ** 0.5
                skip = (sigma_data / magnitude) ** 2
                out = sigma * sigma_data / magnitude
                conditioning = torch.tensor([[sigma]], dtype=torch.float32).log() / 4
                guess = skip * state + out * model(state / magnitude, conditioning)
                denoised = torch.where(mask, observed, guess)
                state = (following / sigma) * state + (1 - following / sigma) * denoised
                if progress:
                    progress(channel * STEPS + step, signal.shape[1] * STEPS)
            recovered[:, channel] = state.numpy()[0]
    return recovered


def _resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return audio
    factor = gcd(source_rate, target_rate)
    return resample_poly(audio, target_rate // factor, source_rate // factor, axis=0)


def _prepare_region(source, start_sample: int, end_sample: int):
    rate = validate_rate(source.samplerate)
    size = end_sample - start_sample
    if not MIN_GAP_MS * rate <= size * 1000 <= MAX_GAP_MS * rate:
        raise ValueError(f"L'inpainting richiede un intervallo da {MIN_GAP_MS} a {MAX_GAP_MS} ms.")
    min_context = ceil(MIN_SIDE_MS * rate / 1000)
    if min(start_sample, source.frames - end_sample) < min_context:
        raise ValueError(f"Servono almeno {MIN_SIDE_MS} ms di segnale prima e dopo la regione.")
    if source.channels not in (1, 2):
        raise ValueError("L'inpainting supporta file mono e stereo.")

    count = ceil(CONTEXT_SAMPLES * rate / MODEL_RATE)
    window_start = (start_sample + end_sample - count) // 2
    first = start_sample - window_start
    last = end_sample - window_start
    left = max(window_start, 0)
    right = min(window_start + count, source.frames)
    source.seek(left)
    signal = np.zeros((count, source.channels), dtype=np.float32)
    signal[left - window_start:right - window_start] = source.read(
        right - left, dtype="float32", always_2d=True
    )
    left_anchor, right_anchor = signal[first - 1].copy(), signal[last].copy()
    signal[first:last] = 0
    require_finite(signal)
    observed = _resample(signal, rate, MODEL_RATE)[:CONTEXT_SAMPLES]
    return observed, first, last, left_anchor, right_anchor


def _replace_region(source, destination: Path, start_sample: int, patch: np.ndarray, cancelled: Cancelled):
    """Copy audio in blocks and replace just the exact, half-open selected interval."""
    end_sample = start_sample + len(patch)
    with float_writer(destination, source.samplerate, source.channels, source.frames) as writer:
        source.seek(0)
        for start in range(0, source.frames, BLOCK):
            check_cancel(cancelled)
            count = min(BLOCK, source.frames - start)
            block = source.read(count, dtype="float32", always_2d=True)
            left, right = max(start, start_sample), min(start + count, end_sample)
            if left < right:
                block[left - start:right - start] = patch[left - start_sample:right - start_sample]
            require_finite(block)
            writer.write(block)
        check_cancel(cancelled)


def _fade_in_region(patch: np.ndarray, original_left: np.ndarray, original_right: np.ndarray, rate: int) -> int:
    fade = min(len(patch) // 3, max(2, round(rate * 0.003)))
    if fade > 1:
        gain = ((1 - np.cos(np.linspace(0, np.pi, fade))) / 2).astype(np.float32)[:, None]
        patch[:fade] = patch[:fade] * gain + original_left * (1 - gain)
        patch[-fade:] = patch[-fade:] * gain[::-1] + original_right * (1 - gain[::-1])
    return fade


def inpaint(
    source: Path, destination: Path, start_sample: int, end_sample: int, model_dir: Path, *,
    seed: int = 0, progress: Progress = None, cancelled: Cancelled = None,
) -> dict:
    """Render a candidate version with no modifications outside the selected gap."""
    import torch

    if source.resolve() == destination.resolve():
        raise ValueError("Usa una destinazione distinta dalla traccia sorgente.")
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Il seed deve essere un intero tra 0 e 2147483647.")

    check_cancel(cancelled)
    started = time.monotonic()
    with sf.SoundFile(source) as stream:
        start_sample, end_sample = sample_region(start_sample, end_sample, stream.frames)
        observed, first, last, left_anchor, right_anchor = _prepare_region(stream, start_sample, end_sample)
        rate = stream.samplerate
        model_first, model_last = floor(first * MODEL_RATE / rate), ceil(last * MODEL_RATE / rate)
        verified = verify_model(model_dir, cancelled=cancelled)
        if "cpu" not in verified["backends"]:
            raise ModelUnavailable(verified["backend_detail"])
        previous_threads = torch.get_num_threads()
        threads = min(previous_threads, 4)
        torch.set_num_threads(threads)
        try:
            model = _load_denoiser(checkpoint_path(model_dir, manifest()))
            inference_started = time.monotonic()
            recovered = _diffuse(model, observed, model_first, model_last,
                                 seed=seed, progress=progress, cancelled=cancelled)
            inference_s = time.monotonic() - inference_started
        finally:
            torch.set_num_threads(previous_threads)
        patch = _resample(recovered, MODEL_RATE, rate)[first:last].copy()
        if len(patch) != end_sample - start_sample:
            raise RuntimeError("La regione generata non coincide con l'intervallo richiesto.")
        require_finite(patch)
        fade = _fade_in_region(patch, left_anchor, right_anchor, rate)
        _replace_region(stream, destination, start_sample, patch, cancelled)
        signal = audio_info(stream)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        **signal,
        "classification": "generated",
        "algorithm": "cqt-diffusion-projection-v1",
        "model_id": MODEL_ID,
        "checkpoint_sha256": verified["sha256"],
        "weights_revision": verified["weights_revision"],
        "code_revision": verified["code_revision"],
        "training_domain": verified["training_domain"],
        "seed": seed,
        "backend": "cpu",
        "cpu_threads": threads,
        "start_sample": start_sample,
        "end_sample": end_sample,
        "native_sample_rate": MODEL_RATE,
        "context_samples_at_native_rate": CONTEXT_SAMPLES,
        "fade_samples_per_edge": fade,
        "inference_steps_per_channel": STEPS,
        "inference_seconds": inference_s,
        "wall_seconds": time.monotonic() - started,
        "process_peak_rss_bytes": peak_rss if platform.system() == "Darwin" else peak_rss * 1024,
        "stereo_mode": "independent_lr" if signal["channels"] == 2 else "mono",
    }
