"""Catalogo del checkpoint per il restauro generativo."""

import json
from functools import cache
from importlib.util import find_spec
from pathlib import Path
from typing import TypedDict, cast

from packages.audio_core.io import check_cancel
from packages.model_adapters.registry import (
    CheckpointManifest,
    ModelUnavailable,
    checkpoint_status,
    install_checkpoint,
    verify_checkpoint,
)

from .contextual import MIN_GAP_MS, MIN_SIDE_MS, MODEL_IDS, PROFILES

MODEL_ID = "diffusion-inpaint"
STEM_MODELS = {"music": MODEL_ID, **MODEL_IDS}


def model_for_stem(stem: str) -> str | None:
    return STEM_MODELS.get(stem)


def model_limits(stem: str) -> tuple[int, int, int]:
    """Return minimum gap, maximum gap and required context per side, in milliseconds."""
    if stem not in STEM_MODELS:
        raise ValueError("Scegli lo stem Dialoghi, Musica o Effetti per l’inpainting.")
    maximum = PROFILES[stem].max_gap_ms if stem in PROFILES else manifest()["max_gap_ms"]
    return MIN_GAP_MS, maximum, MIN_SIDE_MS


def _local_model(stem: str) -> dict:
    profile = PROFILES[stem]
    missing = [module for module in ("torch", "scipy", "soundfile") if find_spec(module) is None]
    return {
        "id": MODEL_IDS[stem],
        "name": "Inpainting contestuale · " + ("Dialoghi" if stem == "dialogue" else "Effetti"),
        "task": "inpainting",
        "stems": [stem],
        "status": "blocked" if missing else "ready",
        "status_detail": "Pesi stimati in memoria dal contesto dello stem per ogni patch.",
        "can_install": False,
        "checkpoint_required": False,
        "backends": [] if missing else ["cpu"],
        "backend_detail": "Dipendenze mancanti: " + ", ".join(missing) if missing else "CPU, float32",
        "missing_dependencies": missing,
        "stereo_mode": "joint",
        "input_channels": [1, 2],
        "native_sample_rate": profile.rate,
        "min_gap_ms": MIN_GAP_MS,
        "max_gap_ms": profile.max_gap_ms,
        "min_context_ms_per_side": MIN_SIDE_MS,
    }

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "inpainting"


class InpaintingManifest(CheckpointManifest):
    max_gap_ms: int


@cache
def manifest() -> InpaintingManifest:
    return cast(InpaintingManifest, json.loads((CONFIG_DIR / f"{MODEL_ID}.json").read_text()))


def _capabilities() -> dict:
    missing = [module for module in ("torch", "einops", "scipy", "soundfile") if find_spec(module) is None]
    return {
        "backends": [] if missing else ["cpu"],
        "backend_detail": "Dipendenze mancanti: " + ", ".join(missing) if missing else "CPU, float32",
        "missing_dependencies": missing,
        "input_channels": [1, 2],
        "stereo_mode": "independent_lr",
        "stereo_warning": "Ricostruzione sperimentale L/R indipendente, sviluppata per pianoforte solo.",
    }


def _require_id(model_id: str) -> None:
    if model_id != MODEL_ID:
        raise ValueError(f"Modello di inpainting sconosciuto: {model_id}")


def list_models(model_dir: Path) -> list[dict]:
    return [
        dict(checkpoint_status(model_dir, manifest(), _capabilities()), stems=["music"], checkpoint_required=True),
        *(_local_model(stem) for stem in PROFILES),
    ]


def install_model(model_dir: Path, model_id: str = MODEL_ID, *, progress=None, cancelled=None) -> dict:
    if model_id in MODEL_IDS.values():
        return verify_model(model_dir, model_id, cancelled=cancelled)
    _require_id(model_id)
    installed = install_checkpoint(model_dir, manifest(), _capabilities(), progress=progress,
                                   cancelled=cancelled or _continue)
    return dict(installed, stems=["music"], checkpoint_required=True)


def verify_model(model_dir: Path, model_id: str = MODEL_ID, *, cancelled=None) -> dict:
    check_cancel(cancelled)
    for stem, local_id in MODEL_IDS.items():
        if model_id == local_id:
            registered = _local_model(stem)
            if registered["status"] == "blocked":
                raise ModelUnavailable(registered["backend_detail"])
            return registered
    _require_id(model_id)
    verified = verify_checkpoint(model_dir, manifest(), _capabilities(), cancelled=cancelled or _continue)
    return dict(verified, stems=["music"], checkpoint_required=True)


def _continue() -> bool:
    return False
