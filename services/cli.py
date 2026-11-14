"""Strumenti locali per avvio, diagnostica e modelli."""

import argparse
import fcntl
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from services.settings import ROOT, Settings, hardware


def display(data):
    print(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))


def probe_writable(directory):
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(dir=directory):
            return {"writable": True, "free_bytes": shutil.disk_usage(directory).free}
    except OSError as error:
        return {"writable": False, "detail": str(error)}


def port_free(port):
    with socket.socket() as local:
        try:
            local.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            local.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def tool_version(tool):
    binary = shutil.which(tool)
    if not binary:
        return None
    flag = "-version" if tool in {"ffmpeg", "ffprobe"} else "--version"
    try:
        result = subprocess.run([binary, flag], capture_output=True, text=True, timeout=5, check=True)
        return {"path": binary, "version": result.stdout.splitlines()[0]}
    except (OSError, subprocess.SubprocessError, IndexError) as error:
        return {"path": binary, "detail": str(error)}


def doctor(settings):
    import soundfile
    import torch

    from services.model_catalog import list_models

    data = {**hardware(), "python": platform.python_version(), "python_binary": sys.executable,
            "torch": torch.__version__, "mps_built": torch.backends.mps.is_built(),
            "tools": {tool: tool_version(tool) for tool in ("node", "pnpm", "ffmpeg", "ffprobe")},
            "libsndfile": soundfile.__libsndfile_version__,
            "libsndfile_formats": soundfile.available_formats(),
            "data_dir": str(settings.data), "data": probe_writable(settings.data),
            "model_dir": str(settings.models), "model_directory": probe_writable(settings.models),
            "web_built": (settings.web / "index.html").is_file(),
            "port": settings.port, "port_free": port_free(settings.port),
            "models": list_models(settings.models)}
    display(data)


def benchmark(settings, model, backend, source):
    from packages.audio_core import ingest
    from packages.model_adapters import separate_audio

    with tempfile.TemporaryDirectory(prefix="sonora-benchmark-") as folder:
        work = Path(folder)
        meta = ingest(source, work / "original.wav")
        start = time.monotonic()
        report = separate_audio(work / "original.wav", work, settings.models, model, backend,
                                progress=lambda *_: None, cancelled=lambda: False)
        elapsed = time.monotonic() - start
        display({"model": model, "backend": backend, "signal": meta, "wall_time_s": elapsed,
                 "real_time_factor": elapsed / (meta["sample_count"] / meta["sample_rate"]),
                 "provenance": report})


def process_identity(pid):
    try:
        return subprocess.check_output(["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
                                       text=True, timeout=3).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def serve(settings, dev=False):
    if not dev and not (settings.web / "index.html").is_file():
        raise ValueError("Build web assente. Esegui pnpm install e pnpm run build.")
    if not port_free(settings.port) or (dev and not port_free(5173)):
        raise ValueError("Porta occupata o non disponibile. Imposta SONORA_PORT oppure libera la porta.")
    settings.data.mkdir(parents=True, exist_ok=True, mode=0o700)
    stop_requested = False

    def request_stop(_signal, _frame):
        nonlocal stop_requested
        stop_requested = True

    with (settings.data / "serve.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("SONORA AI è già in esecuzione per questo archivio.") from None
        pid_record = settings.data / "serve.pid"
        pid_record.write_text(json.dumps({"pid": os.getpid(), "identity": process_identity(os.getpid())}))
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        children = []
        commands = [
            [sys.executable, "-m", "services.worker"],
            [sys.executable, "-m", "uvicorn", "services.api.app:app", "--host", "127.0.0.1",
             "--port", str(settings.port), "--no-access-log"],
        ]
        if dev:
            commands.append(["pnpm", "--filter", "@sonora/web", "dev", "--strictPort"])
        env = {**os.environ, "SONORA_API_TARGET": f"http://127.0.0.1:{settings.port}"}
        try:
            for command in commands:
                children.append(subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True))
            port = 5173 if dev else settings.port
            print(f"SONORA AI · http://127.0.0.1:{port}", flush=True)
            while not stop_requested:
                for child in children:
                    if child.poll() is not None:
                        raise ValueError(f"Un componente di SONORA AI si è arrestato (codice {child.returncode}).")
                time.sleep(0.25)
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
            for child in reversed(children):
                try:
                    child.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            pid_record.unlink(missing_ok=True)


def stop(settings):
    path = settings.data / "serve.pid"
    if not path.is_file():
        print("Nessuna istanza avviata con scripts/start.sh per questo archivio.")
        return
    record = json.loads(path.read_text())
    pid = record["pid"]
    if not record["identity"] or process_identity(pid) != record["identity"]:
        raise ValueError("Il PID salvato non è associato a un'istanza SONORA AI attiva.")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 45
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    if path.exists():
        raise ValueError("Arresto ancora in corso. Controlla il terminale di SONORA AI.")
    print("SONORA AI arrestato.")


def cli():
    parser = argparse.ArgumentParser(prog="sonora")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("serve").add_argument("--dev", action="store_true")
    sub.add_parser("stop")
    sub.add_parser("selftest").add_argument("--pattern", default="test_*.py")
    model_commands = sub.add_parser("models").add_subparsers(dest="action", required=True)
    model_commands.add_parser("list")
    model_commands.add_parser("install").add_argument("model_id")
    model_commands.add_parser("verify").add_argument("model_id")
    performance = sub.add_parser("benchmark")
    performance.add_argument("--model", required=True)
    performance.add_argument("--input", type=Path, required=True)
    performance.add_argument("--backend", choices=("cpu", "mps"), default="cpu")
    args = parser.parse_args()
    os.umask(0o077)
    settings = Settings.load()
    try:
        if args.command == "doctor":
            doctor(settings)
        elif args.command == "models":
            from services.model_catalog import install_model, list_models, verify_model

            if args.action == "list":
                display(list_models(settings.models))
            else:
                action = install_model if args.action == "install" else verify_model
                display(action(settings.models, args.model_id))
        elif args.command == "benchmark":
            benchmark(settings, args.model, args.backend, args.input)
        elif args.command == "selftest":
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=args.pattern)
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
        elif args.command == "serve":
            serve(settings, args.dev)
        else:
            stop(settings)
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
