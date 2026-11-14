"""Local, self-supervised waveform prediction for short dialogue and effects gaps."""

from dataclasses import dataclass
from hashlib import sha256
from math import ceil, gcd
from pathlib import Path

import numpy as np
from scipy import signal
import soundfile as sf

from packages.audio_core.io import Cancelled, Progress, check_cancel, require_finite

MODEL_IDS = {"dialogue": "contextual-dialogue", "effects": "contextual-effects"}


@dataclass(frozen=True)
class Profile:
    rate: int
    max_gap_ms: int
    order: int
    context_seconds: float
    hidden: int
    noise: float


PROFILES = {
    "dialogue": Profile(rate=16000, max_gap_ms=80, order=24, context_seconds=0.6, hidden=24, noise=0.0),
    "effects": Profile(rate=24000, max_gap_ms=120, order=32, context_seconds=0.8, hidden=32, noise=0.65),
}
MIN_GAP_MS = 20
MIN_SIDE_MS = 250
TRAIN_STEPS = 48


def _resample(audio: np.ndarray, source: int, target: int) -> np.ndarray:
    if source == target:
        return audio
    divisor = gcd(source, target)
    return signal.resample_poly(audio, target // divisor, source // divisor, axis=0)


def _context(audio: sf.SoundFile, first: int, last: int, profile: Profile):
    """Read only real context. The selected samples never enter the predictor."""
    project_rate = audio.samplerate
    quota = round(profile.context_seconds * project_rate)
    left_start = max(0, first - quota)
    audio.seek(left_start)
    left = audio.read(first - left_start, dtype="float32", always_2d=True)
    audio.seek(last)
    right = audio.read(min(audio.frames - last, quota), dtype="float32", always_2d=True)
    require_finite(left)
    require_finite(right)
    return left, right


def _pitch_lag(context: np.ndarray, rate: int) -> int | None:
    """Detect a repeating period from the latest voiced context, using normalized autocorrelation."""
    values = context[-round(rate * 0.060):].mean(axis=1, dtype=np.float64)
    values -= values.mean()
    window = values[round(rate / 65):]
    energy = np.linalg.norm(window)
    if energy < 1e-6:
        return None
    lags = np.arange(round(rate / 450), round(rate / 65) + 1)
    start = len(values) - len(window)
    scores = []
    for lag in lags:
        prior = values[start - lag:-lag]
        norm = energy * np.linalg.norm(prior)
        scores.append(np.dot(window, prior) / norm if norm > 0 else 0)
    peaks, _ = signal.find_peaks(scores, height=0.45)
    if not len(peaks):
        return None
    best = max(scores[index] for index in peaks)
    index = next(index for index in peaks if scores[index] >= best - 0.05)
    return int(lags[index])


def _lags(context: np.ndarray, profile: Profile) -> np.ndarray:
    pitch = _pitch_lag(context, profile.rate) if not profile.noise else None
    offsets = list(range(1, profile.order + 1))
    if pitch:
        offsets.extend(range(pitch - 3, pitch + 4))
    elif profile.noise:
        offsets.extend((48, 64, 96, 128))
    return np.array(sorted(set(offsets)))


def _learn(context: np.ndarray, profile: Profile, *, seed: int, cancelled: Cancelled, tick):
    """Solve a regularized linear skip, then train a bounded non-linear residual."""
    import torch
    from torch import nn

    lags = _lags(context, profile)
    targets = np.arange(lags[-1], len(context))
    inputs = context[targets[:, None] - lags].reshape(len(targets), -1)
    outputs = context[targets]
    # Keep every held-out block out of both training inputs and training targets.
    held_out = (np.arange(len(context)) // 1024) % 5 == 1
    history = held_out[targets[:, None] - lags]
    train = ~held_out[targets] & ~history.any(axis=1)
    validate = held_out[targets] & history.all(axis=1)
    x = torch.from_numpy(np.ascontiguousarray(inputs[train]))
    y = torch.from_numpy(np.ascontiguousarray(outputs[train]))
    x_eval = torch.from_numpy(np.ascontiguousarray(inputs[validate]))
    y_eval = torch.from_numpy(np.ascontiguousarray(outputs[validate]))
    ridge = torch.eye(x.shape[1], dtype=torch.float32) * (len(x) * 0.0005)
    linear = torch.linalg.solve(x.T @ x + ridge, x.T @ y)
    with torch.random.fork_rng(devices=[]):
        model = nn.Sequential(nn.Linear(x.shape[1], profile.hidden), nn.Tanh(),
                              nn.Linear(profile.hidden, y.shape[1], bias=False))
    with torch.no_grad():
        # A local generator leaves global RNG state untouched.
        rng = torch.Generator().manual_seed(seed)
        model[0].weight.uniform_(-0.1, 0.1, generator=rng)
        model[0].bias.zero_()
        model[2].weight.zero_()

    # Track the best holdout loss and reject a direction that regresses by more than 0.2%.
    optimizer = torch.optim.Adam(model.parameters(), lr=0.004)
    best = None
    with torch.no_grad():
        baseline = float((y_eval - x_eval @ linear).square().mean())
    best_loss = float("inf")
    for step in range(TRAIN_STEPS):
        check_cancel(cancelled)
        batch = torch.randint(len(x), (384,), generator=rng)
        features = x[batch]
        residual = y[batch] - features @ linear
        loss = (0.25 * model(features) - residual).square().mean()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if (step + 1) % 8 == 0:
            with torch.no_grad():
                eval_loss = float((x_eval @ linear + 0.25 * model(x_eval) - y_eval).square().mean())
                if eval_loss < best_loss:
                    best_loss = eval_loss
                    best = tuple(weight.detach().clone() for weight in model.parameters())
        tick()

    if best is None or best_loss > baseline * 1.002:
        with torch.no_grad():
            model[2].weight.zero_()
        best = tuple(weight.detach() for weight in model.parameters())
        best_loss = baseline
    hidden, bias, output = (weight.numpy() for weight in best)
    params = linear.numpy(), hidden.T.copy(), bias, output.T.copy()
    residual = outputs - (inputs @ params[0] + 0.25 * np.tanh(inputs @ params[1] + bias) @ params[3])
    return lags, params, residual, baseline, best_loss


def _forecast(context: np.ndarray, count: int, profile: Profile, *, seed: int, cancelled, tick):
    lags, params, residual, baseline, loss = _learn(context, profile, seed=seed, cancelled=cancelled, tick=tick)
    linear, hidden, bias, output = params
    total = int(lags[-1])
    values = np.empty((total + count, context.shape[1]), dtype=np.float32)
    values[:total] = context[-total:]
    # Preserve channel relationships by drawing a single joint residual vector per sample.
    generator = np.random.default_rng(seed)
    noise = residual[generator.integers(len(residual), size=count)] * profile.noise
    ceiling = min(3.5, 1.25 * float(np.max(np.abs(context), initial=0)))
    for index in range(total, total + count):
        if (index - total) % 128 == 0:
            check_cancel(cancelled)
        features = values[index - lags].reshape(-1)
        result = features @ linear + 0.25 * np.tanh(features @ hidden + bias) @ output
        values[index] = np.clip(result + noise[index - total], -ceiling, ceiling)
    return values[total:], baseline, loss, output


def restore_gap(audio: sf.SoundFile, first: int, last: int, stem: str, *, seed: int,
                progress: Progress, cancelled: Cancelled) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Mask source gap, train on both observed sides, and combine two forecasts."""
    profile = PROFILES[stem]
    left, right = _context(audio, first, last, profile)
    project_rate = audio.samplerate
    work_left = _resample(left, project_rate, profile.rate)
    work_right = _resample(right[::-1], project_rate, profile.rate)
    scale = float(max(np.sqrt(np.mean(np.square(work_left, dtype=np.float64))),
                      np.sqrt(np.mean(np.square(work_right, dtype=np.float64)))))
    if scale < 1e-7:
        raise ValueError("Contesto troppo silenzioso per stimare una patch contestuale.")
    count = ceil((last - first) * profile.rate / project_rate)
    done = 0

    def tick():
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, 2 * TRAIN_STEPS)

    fwd, baseline_left, loss_left, weights_left = _forecast(work_left / scale, count, profile,
                                                            seed=seed, cancelled=cancelled, tick=tick)
    backward_seed = seed ^ 0x1472
    bwd, baseline_right, loss_right, weights_right = _forecast(work_right / scale, count, profile,
                                                               seed=backward_seed, cancelled=cancelled, tick=tick)
    if not (weights_left.any() or weights_right.any()):
        raise ValueError("Il contesto non ha prodotto una stima neurale valida. Scegli una regione più corta o vicina a segnale continuo.")
    # Complementary spatial blend across the gap. A power-complementary blend
    # retains energy in effects when the two synthesized residuals are incoherent.
    gain = ((1 - np.cos(np.linspace(0, np.pi, count))) / 2).astype(np.float32)[:, None]
    if profile.noise:
        combined = fwd * np.sqrt(1 - gain) + bwd[::-1] * np.sqrt(gain)
    else:
        combined = fwd * (1 - gain) + bwd[::-1] * gain
    restored = _resample(combined * scale, profile.rate, project_rate)[:last - first].copy()
    require_finite(restored)
    return restored, left[-1], right[0], {
        "algorithm": "contextual-waveform-predictor/1",
        "weights_origin": "fitted_from_observed_context",
        "model_id": MODEL_IDS[stem],
        "native_sample_rate": profile.rate,
        "training_context_frames": [len(left), len(right)],
        "training_steps_per_direction": TRAIN_STEPS,
        "one_step_validation_mse_normalized": [loss_left, loss_right],
        "one_step_linear_mse_normalized": [baseline_left, baseline_right],
        "neural_residual_active": True,
        "context_sha256": sha256(left.tobytes() + right.tobytes()).hexdigest(),
        "stereo_mode": "joint" if audio.channels == 2 else "mono",
    }
