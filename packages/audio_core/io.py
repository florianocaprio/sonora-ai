"""Block-based local audio I/O and canonical sample timelines."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from math import gcd
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

BLOCK = 65_536
MIN_RATE, MAX_RATE = 8_000, 192_000
Progress = Callable[[int, int], None] | None
Cancelled = Callable[[], bool] | None
SOURCE_FORMATS = {"WAV", "WAVEX", "RF64", "W64", "AIFF", "FLAC", "MP3"}


def check_cancel(cancelled: Cancelled) -> None:
    if cancelled is not None and cancelled():
        raise InterruptedError("Elaborazione annullata.")


def validate_rate(value: int) -> int:
    if type(value) is not int or not MIN_RATE <= value <= MAX_RATE:
        raise ValueError(f"La frequenza deve essere un intero tra {MIN_RATE} e {MAX_RATE} Hz.")
    return value


def sample_region(start: int, end: int | None, frames: int) -> tuple[int, int]:
    end = frames if end is None else end
    if any(type(value) is not int for value in (start, end)) or not 0 <= start < end <= frames:
        raise ValueError(f"Regione non valida. Indicare [inizio, fine) entro {frames} campioni.")
    return start, end


def require_finite(data: np.ndarray) -> None:
    if not np.isfinite(data).all():
        raise ValueError("Il segnale contiene campioni NaN, infiniti o fuori scala float32.")


@contextmanager
def atomic_destination(destination: Path, *, suffix: str = ".audio") -> Iterator[Path]:
    """Keep partially written audio out of the authoritative asset path."""
    handle, name = tempfile.mkstemp(prefix=".sonora-", suffix=suffix, dir=destination.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        yield temporary
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def float_writer(destination: Path, rate: int, channels: int, frames: int) -> Iterator[sf.SoundFile]:
    container = "RF64" if frames * channels * 4 >= (2**32 - 4096) else "WAV"
    with atomic_destination(destination) as temporary:
        with sf.SoundFile(temporary, mode="w", samplerate=rate, channels=channels,
                          format=container, subtype="FLOAT") as writer:
            yield writer
            if writer.tell() != frames:
                raise RuntimeError("Il numero di campioni scritti differisce dalla timeline prevista.")


def audio_info(audio: sf.SoundFile, *, frames: int | None = None) -> dict:
    count = audio.frames if frames is None else frames
    return {
        "sample_rate": audio.samplerate,
        "sample_count": count,
        "channels": audio.channels,
        "channel_layout": "mono" if audio.channels == 1 else "stereo",
        "channel_order": ["C"] if audio.channels == 1 else ["L", "R"],
        "duration_seconds": count / audio.samplerate,
    }


def _require_mono_stereo(channels: int) -> None:
    if channels not in (1, 2):
        raise ValueError("Il decoder ha rilevato più di due canali. Fornire una conversione mono o stereo esplicita.")


def _process(arguments: list[str], *, timeout: int, cancelled: Cancelled = None) -> tuple[str, str]:
    """Run a local decoder with cancellation and bounded execution time."""
    from time import monotonic

    try:
        with subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, errors="replace") as process:
            deadline = monotonic() + timeout
            try:
                while True:
                    check_cancel(cancelled)
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"{Path(arguments[0]).name} ha superato il tempo limite.")
                    try:
                        out, err = process.communicate(timeout=min(0.25, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                process.kill()
                process.communicate()
                raise
            if process.returncode:
                detail = (err or out).strip().splitlines()
                tail = detail[-1][:250] if detail else f"codice {process.returncode}"
                raise ValueError(f"{Path(arguments[0]).name} ha rifiutato il file o l'operazione: {tail}")
            return out, err
    except FileNotFoundError as error:
        raise RuntimeError(f"Comando locale mancante: {Path(arguments[0]).name}.") from error


def _ffmpeg_decode(source: Path, temporary: Path, cancelled: Cancelled) -> dict:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not (ffmpeg and ffprobe):
        raise RuntimeError("FFmpeg e ffprobe sono richiesti per questo codec o contenitore.")
    source_args = [
        "-protocol_whitelist", "file", "-format_whitelist", "mov,mp3,aac,flac,aiff,wav",
        "-i", str(source.resolve()),
    ]
    out, _ = _process([
        ffprobe, "-v", "error", *source_args, "-select_streams", "a:0", "-show_entries",
        "stream=codec_name,channels,sample_rate,sample_fmt,bits_per_raw_sample,bit_rate,channel_layout:"
        "format=format_name", "-of", "json",
    ], timeout=30, cancelled=cancelled)
    parsed = json.loads(out)
    streams = parsed.get("streams", [])
    if not streams:
        raise ValueError("Il file non contiene una traccia audio decodificabile.")
    stream = streams[0]
    _require_mono_stereo(stream["channels"])
    codec = stream.get("codec_name")
    if codec not in ("aac", "mp3", "flac") and not (codec or "").startswith("pcm_"):
        raise ValueError(f"Codec audio non supportato: {codec}.")
    _process([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-xerror", "-nostdin", "-y", *source_args,
        "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le", "-rf64", "auto", "-f", "wav", str(temporary),
    ], timeout=7200, cancelled=cancelled)
    return {
        "codec": codec,
        "container": parsed.get("format", {}).get("format_name"),
        "source_sample_rate": int(stream["sample_rate"]),
        "source_layout": stream.get("channel_layout"),
        "bitrate_bps": int(stream["bit_rate"]) if stream.get("bit_rate", "").isdigit() else None,
        "source_bit_depth": int(stream["bits_per_raw_sample"])
        if stream.get("bits_per_raw_sample", "").isdigit() and codec.startswith("pcm_") else None,
        "decoder": "ffmpeg",
    }


def _core_audio_decode(source: Path, temporary: Path, cancelled: Cancelled) -> dict:
    """Use the macOS native decoder for AAC when FFmpeg is unavailable."""
    if sys.platform != "darwin" or not (shutil.which("afinfo") and shutil.which("afconvert")):
        raise RuntimeError("Installare FFmpeg e ffprobe per importare AAC/M4A.")
    out, err = _process(["/usr/bin/afinfo", str(source.resolve())], timeout=30, cancelled=cancelled)
    audio_format = re.search(r"Data format:\s+(\d+) ch,\s+([\d.]+) Hz,\s+'([^']+)'", out + err)
    if not audio_format or not audio_format[3].startswith("aac"):
        raise ValueError("Formato non riconosciuto dal decoder locale. Verificare il file o installare FFmpeg e ffprobe.")
    channels, rate = int(audio_format[1]), int(float(audio_format[2]))
    _require_mono_stereo(channels)
    _process([
        "/usr/bin/afconvert", "-f", "caff", "-d", "LEF32", str(source.resolve()), str(temporary),
    ], timeout=7200, cancelled=cancelled)
    return {
        "codec": audio_format[3].strip(),
        "container": "AAC",
        "source_sample_rate": rate,
        "source_layout": "mono" if channels == 1 else "stereo",
        "source_bit_depth": None,
        "bitrate_bps": None,
        "decoder": "Core Audio",
    }


def _format_source(audio: sf.SoundFile) -> dict:
    bit_depth = re.fullmatch(r"PCM_([0-9]+)", audio.subtype)
    bits = int(bit_depth[1]) if bit_depth else {"PCM_U8": 8, "PCM_S8": 8, "FLOAT": 32, "DOUBLE": 64}.get(audio.subtype)
    return {
        "codec": "mp3" if audio.format == "MP3" else ("flac" if audio.format == "FLAC" else audio.subtype.lower()),
        "container": audio.format,
        "source_sample_rate": audio.samplerate,
        "source_layout": "mono" if audio.channels == 1 else "stereo",
        "source_bit_depth": bits,
        "bitrate_bps": None,
        "decoder": "libsndfile",
    }


def _converted_frames(frames: int, input_rate: int, rate: int) -> int:
    return (frames * rate + input_rate - 1) // input_rate


def _resampled_blocks(audio: sf.SoundFile, rate: int) -> Iterator[np.ndarray]:
    """Use phase-aligned FIR context and crop to disjoint output blocks."""
    if rate == audio.samplerate:
        yield from audio.blocks(blocksize=BLOCK, dtype="float32", always_2d=True)
        return
    common = gcd(rate, audio.samplerate)
    up, down = rate // common, audio.samplerate // common
    input_step = max(1, BLOCK // down) * down
    # scipy.signal.resample_poly uses a symmetric FIR with half-length 10*max(up, down).
    # Align each context start to the rational phase lattice and extend beyond the FIR support.
    halo = (10 * max(up, down) + up - 1) // up + 2
    for start in range(0, audio.frames, input_step):
        end = min(start + input_step, audio.frames)
        left = max(0, (start - halo) // down * down)
        right = min(audio.frames, end + halo)
        audio.seek(left)
        block = audio.read(right - left, dtype="float32", always_2d=True)
        require_finite(block)
        output = resample_poly(block, up, down, axis=0, padtype="constant")
        first = (start - left) * up // down
        last = ((end - left) * up + down - 1) // down
        yield output[first:last]


def _canonicalize(audio: sf.SoundFile, destination: Path, target_rate: int | None,
                  progress: Progress, cancelled: Cancelled) -> dict:
    _require_mono_stereo(audio.channels)
    rate = validate_rate(target_rate if target_rate is not None else audio.samplerate)
    frames = _converted_frames(audio.frames, audio.samplerate, rate)
    if frames <= 0:
        raise ValueError("Il file non contiene campioni audio.")
    processed = 0
    with float_writer(destination, rate, audio.channels, frames) as writer:
        for block in _resampled_blocks(audio, rate):
            check_cancel(cancelled)
            require_finite(block)
            writer.write(block)
            processed += len(block)
            if progress:
                progress(processed, frames)
        check_cancel(cancelled)
    result = audio_info(audio, frames=frames)
    result.update(sample_rate=rate, duration_seconds=frames / rate)
    return result


def ingest(source: Path, destination: Path, sample_rate: int | None = None, *,
           progress: Progress = None, cancelled: Cancelled = None) -> dict:
    """Decode unmodified audio to a finite mono/stereo float32 project timeline."""
    check_cancel(cancelled)
    try:
        audio = sf.SoundFile(source)
    except sf.LibsndfileError:
        audio = None
    if audio is not None:
        with audio:
            if audio.format in SOURCE_FORMATS:
                return {**_format_source(audio), **_canonicalize(audio, destination, sample_rate, progress, cancelled)}
    with tempfile.TemporaryDirectory(prefix=".decode-", dir=destination.parent) as scratch:
        decoded = Path(scratch, "decoded.wav")
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            metadata = _ffmpeg_decode(source, decoded, cancelled)
        else:
            metadata = _core_audio_decode(source, decoded, cancelled)
        with sf.SoundFile(decoded) as input_audio:
            return {**metadata, **_canonicalize(input_audio, destination, sample_rate, progress, cancelled)}


def trim_audio(source: Path, destination: Path, start_sample: int, end_sample: int, *,
               progress: Progress = None, cancelled: Cancelled = None) -> dict:
    with sf.SoundFile(source) as audio:
        start, end = sample_region(start_sample, end_sample, audio.frames)
        frames = end - start
        audio.seek(start)
        done = 0
        with float_writer(destination, audio.samplerate, audio.channels, frames) as writer:
            for block in audio.blocks(frames=frames, blocksize=BLOCK, dtype="float32", always_2d=True):
                check_cancel(cancelled)
                require_finite(block)
                writer.write(block)
                done += len(block)
                if progress:
                    progress(done, frames)
            check_cancel(cancelled)
        return audio_info(audio, frames=frames)


_EXPORT_FORMATS = {"wav_float": ("WAV", "FLOAT"), "wav_pcm24": ("WAV", "PCM_24"), "flac": ("FLAC", "PCM_24")}
_FORMAT_ALIASES = {"float32": "wav_float", "pcm24": "wav_pcm24", "flac24": "flac"}


def export_audio(source: Path, destination: Path, *, sample_rate: int | None = None,
                 format: str = "wav_float", progress: Progress = None, cancelled: Cancelled = None) -> dict:
    """Export float32 or PCM24, failing before publication if integer PCM would saturate."""
    from .metrics import SignalMetrics, loudness

    key = _FORMAT_ALIASES.get(format, format)
    if key not in _EXPORT_FORMATS:
        raise ValueError("Formato non supportato. Scegliere WAV float32, WAV PCM24 o FLAC.")
    container, subtype = _EXPORT_FORMATS[key]
    with sf.SoundFile(source) as audio:
        if sample_rate is not None:
            validate_rate(sample_rate)
        rate = audio.samplerate if sample_rate is None else sample_rate
        frames = _converted_frames(audio.frames, audio.samplerate, rate)
        if container == "WAV" and frames * audio.channels * 4 >= (2**32 - 4096):
            container = "RF64"
        processed = 0
        with atomic_destination(destination) as temporary:
            with sf.SoundFile(temporary, "w", rate, audio.channels, subtype=subtype, format=container) as writer:
                for block in _resampled_blocks(audio, rate):
                    check_cancel(cancelled)
                    require_finite(block)
                    if subtype == "PCM_24" and (np.max(block) > 1 - 2**-23 or np.min(block) < -1):
                        raise ValueError("L'esportazione PCM24 saturerebbe. Ridurre il guadagno o scegliere WAV float32.")
                    writer.write(block)
                    processed += len(block)
                    if progress:
                        progress(processed, frames)
                if processed != frames:
                    raise RuntimeError("Il file esportato ha una durata diversa dalla timeline prevista.")
                check_cancel(cancelled)
            metrics = SignalMetrics(audio.channels)
            with sf.SoundFile(temporary) as exported:
                if exported.frames != frames:
                    raise RuntimeError("Il decoder ha riaperto un file di durata diversa dalla timeline prevista.")
                for block in exported.blocks(blocksize=BLOCK, dtype="float32", always_2d=True):
                    check_cancel(cancelled)
                    require_finite(block)
                    metrics.feed(block)
            measured = metrics.as_dict()
            measures = loudness(temporary, peak=measured["sample_peak"], cancelled=cancelled)
            check_cancel(cancelled)
        result = audio_info(audio, frames=frames)
        result.update(format=key, container=container, subtype=subtype, sample_rate=rate, duration_seconds=frames / rate)
        warnings = []
        if measured["samples_at_or_above_full_scale"]:
            warnings.append("Il file esportato raggiunge o supera il fondo scala in campioni.")
        return {**result, **measured, "loudness": measures,
                "true_peak_dbtp": measures["true_peak_dbtp"], "warnings": warnings}
