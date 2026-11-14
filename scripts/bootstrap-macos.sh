#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -sm)" != "Darwin arm64" ]]; then
  echo "Usa una shell ARM64 nativa su macOS." >&2
  exit 1
fi
python="${SONORA_BOOTSTRAP_PYTHON:-python3.11}"
"$python" -c 'import platform,sys; assert platform.machine() == "arm64" and sys.version_info[:2] == (3,11), "Serve Python 3.11 ARM64"'
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (process.arch !== "arm64" || major < 22 || (major === 22 && minor < 12)) throw new Error("Serve Node ARM64 22.12 o successivo");'
command -v pnpm >/dev/null
if [[ -x .sonora/tools/bin/ffmpeg && -x .sonora/tools/bin/ffprobe ]]; then
  export PATH="$(pwd)/.sonora/tools/bin:$PATH"
fi
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "FFmpeg e ffprobe estendono i codec supportati e abilitano loudness e true peak."
fi
echo "Installazione isolata in .venv e node_modules. PyTorch e i binari richiedono qualche centinaio di MB."
"$python" -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements-macos-arm64.lock
.venv/bin/python -m pip check
pnpm install --frozen-lockfile
pnpm run build
scripts/sonora doctor
