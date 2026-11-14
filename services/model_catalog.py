"""Catalogo unificato per i modelli locali, con compiti distinti."""
from pathlib import Path

from packages import model_adapters


def list_models(model_dir: Path) -> list[dict]:
    from packages import inpainting

    return [
        *(dict(model, task="separation") for model in model_adapters.list_models(model_dir)),
        *inpainting.list_models(model_dir),
    ]


def is_restoration_model(model_id: str) -> bool:
    from packages.inpainting import model_for_stem

    return model_id in {model_for_stem(stem) for stem in ("dialogue", "music", "effects")}


def verify_model(model_dir: Path, model_id: str) -> dict:
    from packages import inpainting

    if is_restoration_model(model_id):
        return inpainting.verify_model(model_dir, model_id)
    return dict(model_adapters.verify_model(model_dir, model_id), task="separation")


def install_model(model_dir: Path, model_id: str, *, progress=None, cancelled=lambda: False) -> dict:
    from packages import inpainting

    adapter = inpainting if is_restoration_model(model_id) else model_adapters
    return adapter.install_model(model_dir, model_id, progress=progress, cancelled=cancelled)
