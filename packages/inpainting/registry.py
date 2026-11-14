"""Catalogo del checkpoint per il restauro generativo."""

import json
from functools import cache
from importlib.util import find_spec
from pathlib import Path
from typing import cast

from packages.model_adapters.registry import (
    CheckpointManifest,
    checkpoint_status,
    install_checkpoint,
    verify_checkpoint,
)

MODEL_ID = "diffusion-inpaint"
CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "inpainting"


@cache
def manifest() -> CheckpointManifest:
    return cast(CheckpointManifest, json.loads((CONFIG_DIR / f"{MODEL_ID}.json").read_text()))


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
    return [checkpoint_status(model_dir, manifest(), _capabilities())]


def install_model(model_dir: Path, model_id: str = MODEL_ID, *, progress=None, cancelled=None) -> dict:
    _require_id(model_id)
    return install_checkpoint(model_dir, manifest(), _capabilities(), progress=progress,
                              cancelled=cancelled or _continue)


def verify_model(model_dir: Path, model_id: str = MODEL_ID, *, cancelled=None) -> dict:
    _require_id(model_id)
    return verify_checkpoint(model_dir, manifest(), _capabilities(), cancelled=cancelled or _continue)


def _continue() -> bool:
    return False
