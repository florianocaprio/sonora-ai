"""Pinned model manifests and explicitly requested checkpoint downloads."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import tempfile
from functools import cache
from importlib.util import find_spec
from pathlib import Path
from typing import Callable, TypedDict
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener


class ModelUnavailable(RuntimeError):
    """The requested checkpoint or backend cannot be used in this environment."""


class SeparationCancelled(InterruptedError):
    """Cancellation requested between bounded processing units."""


class ModelManifest(TypedDict):
    id: str
    name: str
    authors: list[str]
    repository: str
    code_revision: str
    code_license: str
    weights_license: str
    weights_revision: str
    weights_url: str
    checkpoint: str
    sha256: str
    size_bytes: int
    sample_rate: int
    native_channels: int
    outputs: list[str]
    precision: str
    window_seconds: int
    hop_seconds: int
    overlap: str
    declared_backends: list[str]


Progress = Callable[[int, int], None]
Cancelled = Callable[[], bool]
BLOCK_BYTES = 1024 * 1024
CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "models"
STEREO_NOTICE = "I canali L/R sono separati indipendentemente. L’immagine stereo può cambiare."


@cache
def _manifests() -> dict[str, ModelManifest]:
    models: list[ModelManifest] = json.loads((CONFIG_DIR / "registry.json").read_text())
    return {entry["id"]: entry for entry in models}


def get_manifest(model_id: str) -> ModelManifest:
    try:
        return _manifests()[model_id]
    except KeyError as error:
        raise ValueError(f"Modello sconosciuto: {model_id}") from error


@cache
def _torch_backends(model_id: str) -> tuple[str, ...]:
    try:
        import torch
        if model_id == "bandit-v2":
            import torchaudio  # noqa: F401
    except (ImportError, OSError):
        return ()
    supported = get_manifest(model_id)["declared_backends"]
    return tuple(backend for backend in supported if backend != "mps" or torch.backends.mps.is_available())


def probe_capabilities(model_id: str) -> dict:
    manifest = get_manifest(model_id)
    modules = ("torch", "safetensors", "einops") if model_id == "dbs-tiger-dnr" else ("torch", "torchaudio")
    missing = [module for module in modules if find_spec(module) is None]
    backends = [] if missing else list(_torch_backends(model_id))
    return {
        "backends": backends,
        "backend_detail": "Backend disponibili in questo processo."
        if backends else "Dipendenze di inferenza mancanti o incompatibili.",
        "missing_dependencies": missing,
        "mps_fallback_enabled_by_environment": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1",
        "stereo_mode": "independent_lr",
        "stereo_warning": STEREO_NOTICE,
        "input_channels": [1, 2],
        "native_sample_rate": manifest["sample_rate"],
    }


def checkpoint_path(model_dir: Path, manifest: ModelManifest) -> Path:
    return model_dir / manifest["id"] / manifest["checkpoint"]


def check_cancelled(cancelled: Cancelled) -> None:
    if cancelled():
        raise SeparationCancelled("Operazione annullata.")


def _never_cancelled() -> bool:
    return False


def _status(model_dir: Path, manifest: ModelManifest) -> dict:
    capabilities = probe_capabilities(manifest["id"])
    path = checkpoint_path(model_dir, manifest)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        size = None

    status = "available"
    detail = "Checkpoint scaricabile su richiesta."
    if size == manifest["size_bytes"]:
        status = "installed"
        detail = "Checkpoint presente. Verifica SHA-256 all’avvio di ogni inferenza."
    elif size is not None:
        status = "blocked"
        detail = "Dimensione errata. Reinstalla il checkpoint."
    if not capabilities["backends"]:
        status = "blocked"
        detail = capabilities["backend_detail"]
    return {**manifest, **capabilities, "status": status, "status_detail": detail}


def list_models(model_dir: Path) -> list[dict]:
    return [_status(model_dir, manifest) for manifest in _manifests().values()]


def verify_model(model_dir: Path, model_id: str, *, cancelled: Cancelled = _never_cancelled) -> dict:
    manifest = get_manifest(model_id)
    path = checkpoint_path(model_dir, manifest)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for data in iter(lambda: source.read(BLOCK_BYTES), b""):
                check_cancelled(cancelled)
                digest.update(data)
    except FileNotFoundError as error:
        raise ModelUnavailable(f"Checkpoint di {model_id} assente. Esegui sonora models install {model_id}.") from error
    if digest.hexdigest() != manifest["sha256"]:
        raise ModelUnavailable(f"SHA-256 errato per {model_id}. Reinstalla il checkpoint.")
    return {**_status(model_dir, manifest), "status": "verified", "status_detail": "SHA-256 conforme al manifest."}


class _TLSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ModelUnavailable("Il server del modello ha proposto un download senza HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def install_model(
    model_dir: Path,
    model_id: str,
    *,
    progress: Progress | None = None,
    cancelled: Cancelled = _never_cancelled,
) -> dict:
    manifest = get_manifest(model_id)
    path = checkpoint_path(model_dir, manifest)
    total = manifest["size_bytes"]
    if path.exists():
        try:
            return verify_model(model_dir, model_id, cancelled=cancelled)
        except ModelUnavailable:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(path.parent).free < total:
        raise ModelUnavailable(f"Servono {total} byte liberi per installare {model_id}.")
    import certifi

    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    opener = build_opener(HTTPSHandler(context=context), _TLSRedirects())
    check_cancelled(cancelled)
    temporary_path = None
    try:
        digest = hashlib.sha256()
        downloaded = 0
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as target:
            temporary_path = Path(target.name)
            with opener.open(manifest["weights_url"], timeout=30) as source:
                for data in iter(lambda: source.read(BLOCK_BYTES), b""):
                    check_cancelled(cancelled)
                    downloaded += len(data)
                    if downloaded > total:
                        raise ModelUnavailable("Il file remoto è più grande della dimensione nel manifest.")
                    digest.update(data)
                    target.write(data)
                    if progress is not None:
                        progress(downloaded, total)
            target.flush()
            os.fsync(target.fileno())
        if downloaded != total or digest.hexdigest() != manifest["sha256"]:
            raise ModelUnavailable("Download incompleto o SHA-256 errato. Riprova l’installazione.")
        check_cancelled(cancelled)
        temporary_path.replace(path)
    except (URLError, TimeoutError, OSError) as error:
        if isinstance(error, SeparationCancelled):
            raise
        raise ModelUnavailable(f"Download di {model_id} non riuscito: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return {**_status(model_dir, manifest), "status": "verified", "status_detail": "SHA-256 conforme al manifest."}
