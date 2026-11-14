"""Coda locale. Il worker pubblica gli artefatti soltanto dopo il calcolo completo."""

import errno
import fcntl
import html
import logging
import os
import shutil
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from services.settings import Settings
from services.storage import Store, encode, now, sha256, uid

NAMES = {"original": "Originale", "dialogue": "Dialoghi", "music": "Musica", "effects": "Effetti",
         "residual": "Residuo di ricostruzione", "master": "Master", "difference": "Differenza"}
log = logging.getLogger("sonora.worker")


def inspect_audio(path: Path) -> dict:
    import soundfile as sf

    info = sf.info(path)
    return {"sample_rate": info.samplerate, "sample_count": info.frames,
            "channels": info.channels, "layout": {1: "mono", 2: "stereo"}.get(info.channels),
            "subtype": info.subtype}


class Task:
    def __init__(self, store, settings, job, stop):
        self.store = store
        self.settings = settings
        self.job = job
        self.job_id = job["id"]
        self.project = job["project_id"]
        self.payload = job["payload"]
        self.folder = store.write_path(self.job_id)
        self.artifacts = []
        self.stop = stop
        self.stage = "Avvio"
        self.last_update = 0.0

    def cancelled(self):
        return self.stop.is_set() or self.store.job(self.job_id)["status"] == "cancelling"

    def phase(self, text):
        self.stage = text
        self.last_update = time.monotonic()
        self.store.progress(self.job_id, text)
        if self.cancelled():
            raise InterruptedError()

    def progress(self, done, total):
        timestamp = time.monotonic()
        if timestamp - self.last_update > 0.35 or done == total:
            self.last_update = timestamp
            self.store.progress(self.job_id, self.stage, done, total)
        if self.cancelled():
            raise InterruptedError()

    def asset(self, identifier):
        return self.store.asset(self.project, identifier)

    def path(self, asset):
        return self.store.local_path(asset["path"])

    def add_asset(self, stem, kind, status, parent, path, metadata, name=None):
        values = self.store.asset_values(self.job, stem, kind, status, parent, name or NAMES[stem], path, metadata)
        self.artifacts.append(("assets", values))
        return values[0]

    def run(self):
        # Un job ripetuto riusa solo input validati. I file della vecchia esecuzione sono parziali.
        if self.folder.exists():
            shutil.rmtree(self.folder)
        self.folder.mkdir(mode=0o700)
        handlers = {
            "import": self.ingest, "separate": self.separate, "analyze": self.analyze,
            "restore": self.restore, "mix": self.mix, "export": self.export, "install_model": self.install_model,
        }
        return handlers[self.job["type"]]()

    def ingest(self):
        from packages.audio_core import ingest

        self.phase("Decodifica e verifica del file")
        path = self.store.local_path(self.payload["upload"])
        output = self.folder / "original.wav"
        metadata = ingest(path, output, self.payload.get("sample_rate"),
                          progress=self.progress, cancelled=self.cancelled)
        actual = inspect_audio(output)
        identifier = self.add_asset("original", "original", "approved", None, output, {
            **metadata, **actual, "source_sha256": self.payload["source_sha256"],
            "source_size_bytes": self.payload["size"], "source_name": self.payload["name"],
        }, self.payload["name"])
        return {"asset_id": identifier}

    @contextmanager
    def inference_lock(self):
        self.settings.models.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.settings.models / "inference.lock").open("a+") as lock:
            while not self.cancelled():
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.stop.wait(0.25)
            if self.cancelled():
                raise InterruptedError()
            yield

    def separate(self):
        from packages.audio_core import trim_audio
        from packages.model_adapters import separate_audio

        asset = self.asset(self.payload["asset_id"])
        source = self.path(asset)
        start = self.payload["start_sample"]
        end = self.payload["end_sample"] or asset["metadata"]["sample_count"]
        region = start != 0 or end != asset["metadata"]["sample_count"]
        if region:
            self.phase("Lettura della regione di prova")
            excerpt = self.folder / "excerpt.wav"
            trim_audio(source, excerpt, start, end, progress=self.progress, cancelled=self.cancelled)
            source = excerpt
        self.phase("Inferenza locale")
        with self.inference_lock():
            metadata = separate_audio(source, self.folder, self.settings.models, self.payload["model_id"],
                                      self.payload["backend"], progress=self.progress, cancelled=self.cancelled)
        if region:
            source.unlink()
        versions = {}
        self.phase("Verifica e registrazione degli stem")
        for stem in ("dialogue", "music", "effects", "residual"):
            path = self.folder / f"{stem}.wav"
            audio = inspect_audio(path)
            if audio["sample_count"] != end - start or any(
                audio[key] != asset["metadata"][key] for key in ("sample_rate", "channels")
            ):
                raise RuntimeError(f"Timeline o canali incoerenti nello stem {NAMES[stem]}.")
            versions[stem] = self.add_asset(
                stem, "preview" if region else "separated", "approved", asset["id"], path,
                {**audio, "start_sample": start, "end_sample": end, "model": metadata,
                 "source_sha256": asset["metadata"]["sha256"]},
            )
        return {"asset_ids": versions, "model": metadata}

    def analyze(self):
        from packages.audio_core import analyze

        asset = self.asset(self.payload["asset_id"])
        self.phase("Analisi del segnale")
        data = analyze(self.path(asset), asset["stem"], start_sample=self.payload["start_sample"],
                       end_sample=self.payload["end_sample"], sensitivity=self.payload["sensitivity"],
                       depth=self.payload["depth"], progress=self.progress, cancelled=self.cancelled)
        existing = self.store.project(self.project)["analyses"]
        reviewed = {
            (event["type"], event["start_sample"], event["end_sample"]): event
            for analysis in reversed(existing) if analysis["asset_id"] == asset["id"]
            for event in analysis["events"] if event["status"] != "unreviewed" or event.get("note")
        }
        for event in data["events"]:
            key = (event["type"], event["start_sample"], event["end_sample"])
            previous = reviewed.get(key, {})
            event["id"] = uid()
            event["status"] = previous.get("status", "unreviewed")
            event["note"] = previous.get("note")
            event["origin"] = "source" if asset["stem"] == "original" else "unknown"
            event["stem"] = asset["stem"]
            event["source_version_id"] = asset["id"]
        identifier = uid()
        self.artifacts.append(("analyses", (identifier, self.project, asset["id"], encode(data), now())))
        return {"analysis_id": identifier}

    def restore(self):
        from packages.audio_core import analyze, difference_audio, restore

        asset = self.asset(self.payload["asset_id"])
        source = self.path(asset)
        output = self.folder / "restored.wav"
        self.phase("Elaborazione del piano di restauro")
        operations = self.payload["operations"]
        generative = any(op["type"] == "inpaint" and not op.get("bypass") for op in operations)
        if asset["status"] != "approved":
            raise ValueError("La sorgente della patch richiede una versione approvata.")
        metadata = restore(source, output, operations, progress=self.progress, cancelled=self.cancelled,
                           neural=(lambda src, dest, op: self.neural_patch(src, dest, op, asset["stem"])) if generative else None)
        identifier = self.add_asset(asset["stem"], "restored", "proposed", asset["id"], output, {
            **inspect_audio(output), **metadata, "profile": self.payload["profile"],
            "requested_operations": operations, "source_sha256": asset["metadata"]["sha256"],
        }, f"Patch generata · {NAMES[asset['stem']]}" if generative else None)
        self.phase("Calcolo della differenza")
        delta = self.folder / "difference.wav"
        difference_audio(source, output, delta, cancelled=self.cancelled)
        difference = self.add_asset("difference", "difference", "proposed", identifier, delta,
                                    {**inspect_audio(delta), "algorithm": "restored-minus-source-v1"})
        self.phase("Verifica del segnale restaurato")
        after = analyze(output, asset["stem"], depth="quick", progress=self.progress, cancelled=self.cancelled)
        for event in after["events"]:
            event.update(id=uid(), status="unreviewed", note=None, stem=asset["stem"], origin="unknown",
                         source_version_id=identifier)
        analysis = uid()
        self.artifacts.append(("analyses", (analysis, self.project, identifier, encode(after), now())))
        return {"asset_id": identifier, "difference_id": difference, "analysis_id": analysis}

    def neural_patch(self, source, destination, operation, stem):
        from packages.inpainting import inpaint

        self.phase(f"Inpainting neurale · {NAMES[stem]}")
        with self.inference_lock():
            result = inpaint(source, destination, operation["start_sample"], operation["end_sample"],
                             self.settings.models, stem=stem, seed=int(operation["params"].get("seed", 0)),
                             progress=self.progress, cancelled=self.cancelled)
        self.phase("Elaborazione del piano di restauro")
        return result

    def mix(self):
        from packages.dsp_core import render_mix

        paths = {}
        inputs = {}
        tracks = {}
        for stem, track in self.payload["tracks"].items():
            identifier = track["asset_id"]
            asset = self.asset(identifier)
            if asset["status"] != "approved" or asset["kind"] == "preview":
                raise ValueError(f"Seleziona una versione completa e approvata per {NAMES[stem]}.")
            paths[stem] = self.path(asset)
            inputs[stem] = identifier
            tracks[stem] = {key: value for key, value in track.items() if key != "asset_id"}
            if stem == "residual" and "mute" not in track:
                tracks[stem]["mute"] = True
        self.phase("Rendering DSP del mix")
        output = self.folder / "master.wav"
        config = {"tracks": tracks, "master": self.payload["master"]}
        metadata = render_mix(paths, output, config, progress=self.progress, cancelled=self.cancelled)
        identifier = self.add_asset("master", "separated", "approved", None, output, {
            **inspect_audio(output), **metadata, "inputs": inputs, "config": config,
        })
        return {"asset_id": identifier}

    def export(self):
        from packages.audio_core import export_audio

        mix = self.asset(self.payload["mix_id"])
        inputs = mix["metadata"]["inputs"]
        fmt = self.payload["format"]
        extension = "flac" if fmt == "flac" else "wav"
        export_id = uid()
        project = self.store.project(self.project)
        warnings = []
        artifact_list = []
        records = {}
        names = {"dialogue": "dialoghi", "music": "musica", "effects": "effetti",
                 "residual": "residuo", "original": "originale", "master": "master"}

        def artifact(path):
            artifact_list.append({
                "name": path.name, "size": path.stat().st_size, "sha256": sha256(path),
                "url": f"/api/v1/projects/{self.project}/exports/{export_id}/files/{path.name}",
            })

        for stem, asset_id in {"master": mix["id"], **inputs}.items():
            asset = self.asset(asset_id)
            if asset["status"] != "approved":
                raise ValueError("Una versione del mix è stata rifiutata. Renderizza nuovamente il master.")
            self.phase(f"Esportazione · {NAMES[stem]}")
            filename = f"{names[stem]}-{asset['kind']}.{extension}" if stem != "master" else f"master.{extension}"
            destination = self.folder / filename
            measured = export_audio(self.path(asset), destination, format=fmt,
                                    sample_rate=self.payload["sample_rate"],
                                    progress=self.progress, cancelled=self.cancelled)
            if stem == "master":
                ceiling = mix["metadata"].get("ceiling_dbtp", mix["metadata"]["config"]["master"].get("ceiling_dbtp"))
                true_peak = measured.get("true_peak_dbtp")
                if (mix["metadata"].get("limiter") or {}).get("active"):
                    from packages.dsp_core.limiter import measure_true_peak

                    native_peak = measure_true_peak(destination, cancelled=self.cancelled)
                    measured["verification_true_peak_dbtp"] = native_peak
                    measurements = [value for value in (true_peak, native_peak) if value is not None]
                    true_peak = max(measurements, default=None)
                if ceiling is not None and true_peak is None:
                    warnings.append("Ceiling dopo conversione non verificabile senza true peak.")
                elif ceiling is not None and true_peak > ceiling:
                    warnings.append("True peak dopo conversione sopra il ceiling dichiarato.")
            artifact(destination)
            provenance = []
            ancestor = asset
            while ancestor is not None:
                if ancestor["status"] != "approved":
                    raise ValueError("La provenienza contiene una versione non approvata. Renderizza di nuovo il master.")
                provenance.append({key: ancestor[key] for key in ("id", "stem", "kind", "status", "metadata")})
                ancestor = self.asset(ancestor["parent_id"]) if ancestor["parent_id"] else None
            records[stem] = {"version": asset_id, "output": filename, "measurement": measured,
                             "provenance": provenance}
            reported = measured.get("warnings") or []
            if isinstance(reported, list):
                warnings.extend(str(item) for item in reported)
        self.phase("Compilazione di manifest e report")
        warnings = list(dict.fromkeys(warnings + list(mix["metadata"].get("warnings") or [])))
        report = {"schema_version": 1, "project_id": self.project, "project_name": project["name"],
                  "created_at": now(), "format": fmt, "mixer": mix["metadata"]["config"],
                  "warnings": warnings, "tracks": records, "audio_artifacts": artifact_list.copy(),
                  "analyses": project["analyses"]}
        manifest = self.folder / "manifest.json"
        manifest.write_text(encode(report) + "\n", encoding="utf-8")
        artifact(manifest)
        report_file = self.folder / "report.html"
        report_file.write_text(report_html(report), encoding="utf-8")
        artifact(report_file)
        payload = {"artifacts": artifact_list, "warnings": warnings, "job_id": self.job_id}
        self.artifacts.append(("exports", (export_id, self.project, encode(payload), now())))
        return {"export_id": export_id}

    def install_model(self):
        from services.model_catalog import install_model

        self.phase("Download e verifica del modello")
        return install_model(self.settings.models, self.payload["model_id"],
                             progress=self.progress, cancelled=self.cancelled)


def report_html(report):
    escape = lambda value: html.escape(str(value))
    tracks = []
    for stem, detail in report["tracks"].items():
        measured = detail["measurement"]
        tracks.append(f"<tr><th>{escape(NAMES[stem])}</th><td>{escape(detail['output'])}</td>"
                      f"<td>{escape(measured.get('sample_rate', '—'))} Hz</td>"
                      f"<td>{escape(measured.get('sample_count', '—'))}</td></tr>")
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in report["warnings"])
    return f"""<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Report SONORA AI</title><style>body{{font:16px system-ui;color:#15212c;margin:5vw;line-height:1.45}}
table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #ddd;text-align:left;padding:8px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}@media print{{body{{margin:0}}}}</style>
<h1>SONORA AI · Report tecnico</h1><p>{escape(report['project_name'])} · {escape(report['created_at'])}</p>
<table><thead><tr><th>Traccia</th><th>File</th><th>Frequenza</th><th>Campioni</th></tr></thead>
<tbody>{''.join(tracks)}</tbody></table>
<h2>Avvisi</h2>{f'<ul>{warnings}</ul>' if warnings else '<p>Nessun avviso registrato.</p>'}
<p>Le misure mancanti compaiono come null. Le segnalazioni sono euristiche e hanno uno stato di revisione.</p>
<h2>Misure e provenienza</h2><pre>{escape(encode(report))}</pre></html>"""


def run_job(store, settings, job, stop):
    from packages.model_adapters import ModelUnavailable

    task = Task(store, settings, job, stop)
    heartbeat_done = threading.Event()

    def heartbeat():
        while not heartbeat_done.wait(5):
            store.progress(job["id"])

    watch = threading.Thread(target=heartbeat, daemon=True)
    watch.start()
    try:
        result = task.run()
        if task.cancelled():
            raise InterruptedError()
        status = store.complete(job["id"], "Completato", result, task.artifacts)
    except InterruptedError:
        status = store.complete(job["id"], "Annullato", None, [], status="cancelled")
    except ModelUnavailable as error:
        status = store.complete(job["id"], "Bloccato", None, [], status="blocked", error=str(error))
    except MemoryError:
        status = store.complete(job["id"], "Errore", None, [], status="failed",
                                error="Memoria insufficiente. Riduci la regione o libera memoria.")
    except (LookupError, ValueError, RuntimeError, OSError) as error:
        message = str(error)
        if isinstance(error, OSError) and error.errno == errno.ENOSPC:
            message = "Spazio disco insufficiente. Libera spazio nell'archivio locale."
        status = store.complete(job["id"], "Errore", None, [], status="failed", error=message or type(error).__name__)
    except Exception:
        log.exception("Errore interno nel job %s", job["id"])
        status = store.complete(job["id"], "Errore interno", None, [], status="failed",
                                error="Errore interno. Consulta il log del worker locale e riprova.")
    finally:
        heartbeat_done.set()
        watch.join()
    if status != "succeeded":
        shutil.rmtree(task.folder, ignore_errors=True)
    return status


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.umask(0o077)
    settings = Settings.load()
    store = Store(settings.data)
    stop = threading.Event()

    def request_stop(_signal, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with (store.data / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Esiste già un worker SONORA AI per questo archivio.") from None
        store.recover()
        log.info("Worker pronto")
        while not stop.is_set():
            job = store.claim()
            if job:
                run_job(store, settings, job, stop)
            else:
                stop.wait(0.25)


if __name__ == "__main__":
    main()
