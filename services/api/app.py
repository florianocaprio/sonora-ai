"""API FastAPI v1 e distribuzione dello studio sulla stessa origine locale."""

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from packages.contracts import (Analyze, EventPatch, Export, Mix, Profile, ProjectName, ProjectPatch,
                                Rate, Restore, Separate, VersionPatch)
from services.settings import Settings, hardware
from services.storage import Conflict, Missing, Store, TERMINAL, uid

COOKIE = "sonora_session"
API = "/api/v1"


def create_app(settings: Settings | None = None):
    settings = settings or Settings.load()
    token = secrets.token_urlsafe(32)
    allowed_hosts = {"127.0.0.1", "localhost", "[::1]"}
    allowed_ports = {str(settings.port), "5173"}
    ui = settings.web

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings.data)
        yield

    application = FastAPI(title="SONORA AI", version="1.0.0", lifespan=lifespan,
                          openapi_url=f"{API}/openapi.json", docs_url=None, redoc_url=None)
    router = APIRouter(prefix=API)

    def store():
        return application.state.store

    def loopback(authority: str):
        host, _, port = authority.lower().rpartition(":")
        return host in allowed_hosts and port in allowed_ports

    def authorized(value: str | None):
        return value is not None and hmac.compare_digest(token.encode(), value.encode())

    @application.middleware("http")
    async def boundary(request: Request, call_next):
        if not loopback(request.headers.get("host", "")):
            return JSONResponse({"detail": "Host locale non autorizzato."}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or not loopback(parsed.netloc) or parsed.path or parsed.query or parsed.fragment:
                return JSONResponse({"detail": "Origine non autorizzata."}, status_code=403)
        path = request.url.path
        if path.startswith(API + "/"):
            fetch_site = request.headers.get("sec-fetch-site")
            if fetch_site in {"cross-site", "same-site"}:
                return JSONResponse({"detail": "Origine del browser non autorizzata."}, status_code=403)
            safe = request.method in {"GET", "HEAD"}
            if request.method == "POST" and path.endswith("/import"):
                try:
                    length = int(request.headers.get("content-length", "-1"))
                except ValueError:
                    return JSONResponse({"detail": "Lunghezza upload non valida."}, status_code=400)
                if length < 0:
                    return JSONResponse({"detail": "L'upload richiede Content-Length."}, status_code=411)
                if length > settings.max_upload + 65536:
                    return JSONResponse({"detail": "File oltre il limite di importazione."}, status_code=413)
            public = safe and path in {f"{API}/session", f"{API}/health"}
            alternative = safe and (path.endswith(("/media", "/events")) or "/files/" in path)
            if not public and not authorized(request.headers.get("x-sonora-token")):
                if not alternative or not authorized(request.cookies.get(COOKIE)):
                    return JSONResponse({"detail": "Sessione locale scaduta. Ricarica SONORA AI."}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if path.startswith(API + "/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @application.exception_handler(Missing)
    async def missing(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @application.exception_handler(Conflict)
    async def conflict(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @application.exception_handler(ValueError)
    async def invalid(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @router.get("/session")
    def session(response: Response):
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path=API)
        return {"token": token}

    @router.get("/health")
    def health():
        return {**hardware(), "data_dir": str(settings.data), "schema_version": 1,
                "disk_free_bytes": shutil.disk_usage(settings.data).free, "max_upload_bytes": settings.max_upload}

    @router.get("/projects")
    def projects():
        return store().projects()

    @router.post("/projects", status_code=201)
    def create_project(body: ProjectName):
        return store().create_project(body.name)

    @router.get("/projects/{project_id}")
    def project(project_id: str):
        return store().project(project_id)

    @router.post("/projects/{project_id}/duplicate", status_code=201)
    def duplicate(project_id: str, body: ProjectName):
        return store().create_project(body.name, source=project_id)

    @router.patch("/projects/{project_id}")
    def patch_project(project_id: str, body: ProjectPatch):
        return store().patch_project(project_id, body.model_dump(exclude_none=True))

    @router.get("/models")
    def models():
        from packages.model_adapters import list_models

        return list_models(settings.models)

    @router.get("/models/{model_id}/verify")
    def verify(model_id: str):
        from packages.model_adapters import ModelUnavailable, verify_model

        try:
            return verify_model(settings.models, model_id)
        except ModelUnavailable as error:
            raise Conflict(str(error)) from error

    @router.post("/models/{model_id}/install", status_code=202)
    def install(model_id: str, idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
        if model_id not in {item["id"] for item in models()}:
            raise Missing("Modello")
        return store().enqueue(None, "install_model", {"model_id": model_id}, idempotency_key)

    @router.get("/jobs")
    def global_jobs():
        return store().global_jobs()

    @router.get("/jobs/{job_id}")
    def job(job_id: str):
        return store().job(job_id)

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return store().cancel(job_id)

    @router.post("/jobs/{job_id}/retry")
    def retry(job_id: str):
        return store().retry(job_id)

    @router.get("/jobs/{job_id}/events")
    async def events(job_id: str, request: Request):
        await run_in_threadpool(store().job, job_id)

        async def generate():
            previous = None
            heartbeat = 0
            while not await request.is_disconnected():
                state = await run_in_threadpool(store().job, job_id)
                if state != previous:
                    yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
                    previous = state
                    heartbeat = 0
                elif heartbeat >= 20:
                    yield ": sonoro\n\n"
                    heartbeat = 0
                if state["status"] in TERMINAL:
                    return
                heartbeat += 1
                await asyncio.sleep(0.6)

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})

    @router.post("/projects/{project_id}/import", status_code=202)
    def upload(project_id: str, file: Annotated[UploadFile, File()],
               sample_rate: Annotated[Rate | None, Form()] = None,
               idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
        project = store().project(project_id)
        if project["archived"]:
            raise Conflict("Riapri il progetto archiviato prima di importare.")
        name = (file.filename or "audio").replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(ch for ch in name if ch.isprintable()).strip()[:240] or "audio"
        identifier = uid()
        disk_file = store().uploads / f"{identifier}.source"
        if file.size and file.size > settings.max_upload:
            raise HTTPException(413, "File oltre il limite di importazione.")
        if file.size and shutil.disk_usage(settings.data).free < file.size + (16 << 20):
            raise HTTPException(507, "Spazio disco insufficiente per importare l'originale.")
        size = 0
        digest = hashlib.sha256()
        try:
            with disk_file.open("xb") as output:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload:
                        raise HTTPException(413, "File oltre il limite di importazione.")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not size:
                raise ValueError("Il file audio è vuoto.")
            checksum = digest.hexdigest()
            fingerprint = f"{checksum}:{sample_rate}:{name}"
            payload = {"name": name, "upload": store().relative(disk_file), "source_sha256": checksum,
                       "size": size, "sample_rate": sample_rate, "fingerprint": fingerprint}
            queued = store().enqueue(project_id, "import", payload, idempotency_key,
                                     fingerprint=fingerprint, job_id=identifier)
            if queued["id"] != identifier:
                disk_file.unlink()
            return queued
        except BaseException:
            disk_file.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()

    def asset_and_region(project_id, body):
        asset = store().asset(project_id, body.asset_id)
        count = asset["metadata"]["sample_count"]
        if not 0 <= body.start_sample < (body.end_sample or count) <= count:
            raise ValueError("Regione fuori dalla timeline dell'asset selezionato.")
        return asset

    @router.post("/projects/{project_id}/separate", status_code=202)
    def separate(project_id: str, body: Separate, idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
        if asset_and_region(project_id, body)["kind"] != "original":
            raise ValueError("Seleziona una versione Originale da separare.")
        return store().enqueue(project_id, "separate", body.model_dump(), idempotency_key)

    @router.post("/projects/{project_id}/analyze", status_code=202)
    def analyze(project_id: str, body: Analyze, idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
        asset_and_region(project_id, body)
        return store().enqueue(project_id, "analyze", body.model_dump(), idempotency_key)

    @router.post("/projects/{project_id}/restore", status_code=202)
    def restore(project_id: str, body: Restore, idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
        asset = store().asset(project_id, body.asset_id)
        if asset["status"] != "approved" or asset["kind"] == "preview" or asset["stem"] in {"master", "difference", "residual"}:
            raise ValueError("Seleziona un originale o uno stem completo e approvato.")
        if any(operation.end_sample > asset["metadata"]["sample_count"] for operation in body.operations):
            raise ValueError("Il piano supera la durata dell'asset.")
        return store().enqueue(project_id, "restore", body.model_dump(), idempotency_key)

    @router.post("/projects/{project_id}/mix", status_code=202)
    def mix(project_id: str, body: Mix, idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
        payload = body.model_dump(exclude_none=True)
        for stem, track in body.tracks.items():
            asset = store().asset(project_id, track.asset_id)
            if asset["stem"] != stem or asset["status"] != "approved" or asset["kind"] == "preview":
                raise ValueError(f"Versione non disponibile per il canale {stem}.")
            if stem == "residual" and "mute" not in track.model_fields_set:
                payload["tracks"][stem]["mute"] = True
        return store().enqueue(project_id, "mix", payload, idempotency_key)

    @router.post("/projects/{project_id}/export", status_code=202)
    def export(project_id: str, body: Export, idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
        if store().asset(project_id, body.mix_id)["stem"] != "master":
            raise ValueError("Renderizza prima un master con il mixer.")
        return store().enqueue(project_id, "export", body.model_dump(), idempotency_key)

    @router.patch("/projects/{project_id}/assets/{asset_id}")
    def approve(project_id: str, asset_id: str, body: VersionPatch):
        return store().set_approval(project_id, asset_id, body.status)

    @router.get("/projects/{project_id}/assets/{asset_id}/media")
    def media(project_id: str, asset_id: str):
        asset = store().asset(project_id, asset_id)
        return FileResponse(store().local_path(asset["path"]), media_type="audio/wav")

    @router.get("/projects/{project_id}/assets/{asset_id}/source")
    def original_source(project_id: str, asset_id: str):
        asset = store().asset(project_id, asset_id)
        if asset["kind"] != "original":
            raise Missing("File sorgente")
        job_id = asset["metadata"].get("job_id")
        payload = store().job(job_id, private=True)["payload"]
        return FileResponse(store().local_path(payload["upload"]), filename=payload["name"],
                            media_type="application/octet-stream")

    @router.get("/projects/{project_id}/assets/{asset_id}/waveform")
    def waveform_view(project_id: str, asset_id: str, bins: Annotated[int, Query(ge=8, le=4096)] = 512,
                 start_sample: Annotated[int, Query(ge=0)] = 0, end_sample: Annotated[int | None, Query(gt=0)] = None):
        from packages.audio_core import waveform

        asset = store().asset(project_id, asset_id)
        peaks = waveform(store().local_path(asset["path"]), bins, start_sample=start_sample, end_sample=end_sample)
        return {"peaks": peaks}

    @router.get("/projects/{project_id}/assets/{asset_id}/spectrogram")
    def spectrogram_view(project_id: str, asset_id: str,
                         start_sample: Annotated[int, Query(ge=0)] = 0,
                         end_sample: Annotated[int | None, Query(gt=0)] = None,
                         columns: Annotated[int, Query(ge=8, le=512)] = 160,
                         fft_size: Annotated[int, Query(ge=128, le=4096)] = 512):
        from packages.audio_core import spectrogram

        asset = store().asset(project_id, asset_id)
        return spectrogram(store().local_path(asset["path"]), start_sample=start_sample, end_sample=end_sample,
                           columns=columns, fft_size=fft_size)

    @router.get("/projects/{project_id}/assets/{asset_id}/plan")
    def plan(project_id: str, asset_id: str, profile: Profile = "basic", analysis_id: str | None = None):
        from packages.audio_core import propose_operations

        asset = store().asset(project_id, asset_id)
        if analysis_id:
            analysis = store().analysis(project_id, analysis_id)
            if analysis["asset_id"] != asset_id:
                raise ValueError("L'analisi non appartiene alla versione selezionata.")
        else:
            analysis = next((item for item in store().project(project_id)["analyses"] if item["asset_id"] == asset_id), {})
        meta = asset["metadata"]
        return {"operations": propose_operations(analysis.get("events", ()), profile, asset["stem"],
                                                 end_sample=meta["sample_count"], sample_rate=meta["sample_rate"])}

    @router.patch("/projects/{project_id}/analyses/{analysis_id}/events/{event_id}")
    def review(project_id: str, analysis_id: str, event_id: str, body: EventPatch):
        return store().review_event(project_id, analysis_id, event_id, body.model_dump(exclude_unset=True, exclude_none=True))

    @router.get("/projects/{project_id}/exports/{export_id}/files/{filename}")
    def download(project_id: str, export_id: str, filename: str):
        record = store().export(project_id, export_id)
        if filename not in {item["name"] for item in record["artifacts"]}:
            raise Missing("File esportato")
        destination = store().write_path(record["job_id"]) / filename
        if filename == "report.html":
            return FileResponse(destination, media_type="text/html",
                                headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
        return FileResponse(destination, filename=filename)

    application.include_router(router)

    @application.get("/{path:path}", include_in_schema=False)
    def static(path: str):
        if path.startswith("api/"):
            raise Missing("Endpoint")
        if not (ui / "index.html").is_file():
            return Response("Interfaccia assente. Esegui pnpm install e pnpm run build.", status_code=503,
                            media_type="text/plain")
        candidate = (ui / path).resolve()
        if not candidate.is_relative_to(ui.resolve()):
            raise Missing("File")
        if candidate.is_file():
            return FileResponse(candidate)
        if path.startswith("assets/"):
            raise Missing("File")
        return FileResponse(ui / "index.html")

    return application


app = create_app()
