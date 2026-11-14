"""Reference-based evaluation for an additive three-stem local fixture."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from .separation import STEMS, separate_audio


def _db_ratio(power: float, baseline: float) -> float | None:
    return 10 * math.log10(power / baseline) if power > 0 and baseline > 0 else None


def _measure(estimated: NDArray, reference: NDArray) -> dict:
    """Measure SI-SDR and projected crosstalk on demeaned aligned samples."""
    references = reference.reshape(len(STEMS), -1).astype(np.float64)
    signals = estimated.reshape(len(STEMS), -1).astype(np.float64)
    references -= references.mean(axis=1, keepdims=True)
    signals -= signals.mean(axis=1, keepdims=True)
    coefficients = np.linalg.lstsq(references.T, signals.T, rcond=None)[0]
    output = {}
    for index, stem in enumerate(STEMS):
        target = references[index]
        actual = signals[index]
        reference_power = float(np.dot(target, target))
        scale = float(np.dot(actual, target) / reference_power)
        model_target = scale * target
        error = actual - model_target
        target_amplitude = np.square(model_target).sum()
        error_power = np.square(error).sum()
        own_component_power = coefficients[index, index] ** 2 * reference_power
        crosstalk = {
            name: _db_ratio(coefficients[source_index, index] ** 2 * np.square(references[source_index]).sum(),
                            own_component_power)
            for source_index, name in enumerate(STEMS)
            if source_index != index
        }
        output[stem] = {
            "si_sdr_db": _db_ratio(target_amplitude, error_power),
            "projected_gain_db": _db_ratio(scale ** 2, 1),
            "projected_crosstalk_db_relative_to_own_component": crosstalk,
        }
    return output


def compare(fixture: Path, model_dir: Path, backend: str, models: list[str], start: int, end: int) -> dict:
    """Read identically aligned reference stems, create the mix and compare outputs."""
    if start < 0 or end <= start or end - start > 2_880_000:
        raise ValueError("Scegli una regione positiva e non superiore a 2 880 000 campioni.")
    references = []
    rate = None
    shape = None
    for stem in ("dialogue", "music", "sfx"):
        values, sample_rate = sf.read(fixture / f"{stem}.flac", start=start, stop=end,
                                      dtype="float32", always_2d=True)
        if len(values) != end - start or (rate is not None and (sample_rate != rate or shape != values.shape)):
            raise ValueError("Gli stem devono coprire l’intera regione e condividere timeline e canali.")
        if not np.isfinite(values).all() or not np.any(values != values[0]):
            raise ValueError(f"La regione dello stem {stem} è costante o non finita.")
        rate, shape = sample_rate, values.shape
        references.append(values)
    ref_array = np.stack(references)
    mix = np.sum(ref_array, axis=0, dtype=np.float32)
    report = {
        "start_sample": start,
        "end_sample": end,
        "sample_rate": rate,
        "channels": shape[-1],
        "null_db_reason": "Il numeratore o il denominatore del rapporto di potenza è nullo.",
        "models": {},
    }
    with tempfile.TemporaryDirectory(prefix="sonora-reference-") as temporary:
        work = Path(temporary)
        source = work / "mix.wav"
        sf.write(source, mix, rate, subtype="FLOAT")
        for model in models:
            dest = work / model
            provenance = separate_audio(source, dest, model_dir, model, backend,
                                        progress=lambda *_: None, cancelled=lambda: False)
            files = [sf.read(dest / f"{stem}.wav", dtype="float32", always_2d=True)[0] for stem in STEMS]
            report["models"][model] = {
                "provenance": provenance,
                "measurements": _measure(np.stack(files), ref_array),
            }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--backend", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--models", nargs="+", default=["dbs-tiger-dnr", "bandit-v2"])
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    args = parser.parse_args()
    report = compare(args.references, args.model_dir, args.backend, args.models, args.start, args.end)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
