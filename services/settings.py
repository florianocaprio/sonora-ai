"""Configurazione runtime locale e verifica dell'ambiente."""

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data: Path
    models: Path
    port: int
    max_upload: int
    web: Path

    @classmethod
    def load(cls):
        if platform.system() == "Darwin":
            data = Path.home() / "Library/Application Support/SONORA AI"
            models = Path.home() / "Library/Caches/SONORA AI/models"
        else:
            data = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "sonora-ai"
            models = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")) / "sonora-ai/models"
        data = Path(os.getenv("SONORA_DATA_DIR", data)).expanduser().resolve()
        models = Path(os.getenv("SONORA_MODEL_DIR", models)).expanduser().resolve()
        return cls(data, models, int(os.getenv("SONORA_PORT", "8765")),
                   int(os.getenv("SONORA_MAX_UPLOAD_BYTES", str(20 * 1024**3))),
                   ROOT / "apps/web/dist")


@lru_cache(maxsize=1)
def hardware() -> dict:
    platform_name = platform.platform()
    memory = None
    try:
        memory = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=2))
    except (OSError, ValueError, subprocess.SubprocessError):
        try:
            memory = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError):
            pass
    mps = False
    try:
        import torch

        mps = torch.backends.mps.is_available()
    except (ImportError, RuntimeError):
        pass
    return {
        "platform": platform_name, "machine": platform.machine(), "memory_bytes": memory,
        "mps": mps, "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
    }
