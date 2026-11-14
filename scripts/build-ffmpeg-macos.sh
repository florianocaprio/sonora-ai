#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -sm)" != "Darwin arm64" ]]; then
  echo "Serve macOS ARM64 nativo." >&2
  exit 1
fi
dest="$(pwd)/.sonora/tools/bin"
if [[ -x "$dest/ffmpeg" && -x "$dest/ffprobe" ]] &&
  "$dest/ffmpeg" -version | head -n 1 | grep -q 'version 9\.0\.2'; then
  exit 0
fi
echo "Compilazione locale FFmpeg 9.0.2. Servono Xcode Command Line Tools, rete e spazio temporaneo."
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
archive="$scratch/ffmpeg-9.0.2.tar.xz"
curl --fail --silent --show-error --location --proto '=https' \
  https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz -o "$archive"
printf '%s  %s\n' 8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e "$archive" |
  shasum -a 256 -c -
tar -xJf "$archive" -C "$scratch"
mkdir -p "$dest" "$scratch/build"
cd "$scratch/build"
"$scratch/ffmpeg-9.0.2/configure" --disable-doc --disable-debug --disable-ffplay \
  --disable-network --disable-autodetect --disable-shared --enable-static > "$scratch/configure.log" ||
  { tail -n 30 "$scratch/configure.log" >&2; exit 1; }
make -j "${SONORA_BUILD_JOBS:-8}" ffmpeg ffprobe > "$scratch/build.log" ||
  { tail -n 30 "$scratch/build.log" >&2; exit 1; }
install -m 755 ffmpeg ffprobe "$dest/"
"$dest/ffmpeg" -version | sed -n '1p'
