"""Persistenza SQLite, proprietà degli artefatti e transazioni dei job."""

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = ("succeeded", "failed", "blocked", "cancelled")
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, mixer TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), type TEXT NOT NULL,
    status TEXT NOT NULL, stage TEXT NOT NULL, payload TEXT NOT NULL, processed INTEGER,
    total INTEGER, error TEXT, result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    heartbeat REAL, attempts INTEGER NOT NULL DEFAULT 0, idempotency TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), stem TEXT NOT NULL,
    kind TEXT NOT NULL, status TEXT NOT NULL, parent_id TEXT REFERENCES assets(id),
    name TEXT NOT NULL, path TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assets_project ON assets(project_id, created_at);
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
    asset_id TEXT NOT NULL REFERENCES assets(id), payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
    payload TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class Missing(LookupError):
    """Risorsa locale assente."""


class Conflict(ValueError):
    """Richiesta incompatibile con lo stato persistito."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid.uuid4().hex


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def checked(row, resource: str):
    if row is None:
        raise Missing(f"{resource} non trovato.")
    return row


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def decode_row(row, json_fields=()):
    record = dict(row)
    for field in json_fields:
        if record.get(field) is not None:
            record[field] = json.loads(record[field])
    return record


class Store:
    def __init__(self, data: Path):
        self.data = data
        self.blobs = data / "work"
        self.uploads = data / "uploads"
        self.blobs.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.uploads.mkdir(exist_ok=True, mode=0o700)
        self.database = data / "studio.sqlite3"
        with self.connect(autocommit=True) as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("Il database richiede una versione più recente di SONORA AI.")
            if version < SCHEMA_VERSION:
                db.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA}\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;")

    @contextmanager
    def connect(self, *, write: bool = False, autocommit: bool = False):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            elif not autocommit:
                db.execute("BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def local_path(self, relative: str) -> Path:
        path = (self.data / relative).resolve()
        if not path.is_relative_to(self.data.resolve()):
            raise ValueError("Percorso al di fuori dell'archivio audio.")
        return path

    def relative(self, file: Path) -> str:
        return file.resolve().relative_to(self.data.resolve()).as_posix()

    def write_path(self, job_id: str) -> Path:
        return self.blobs / job_id

    def projects(self):
        with self.connect() as db:
            identifiers = [r["id"] for r in db.execute("SELECT id FROM projects ORDER BY updated_at DESC")]
            return [self.project(project_id, db) for project_id in identifiers]

    def project(self, project_id, db=None):
        if db is None:
            with self.connect() as active:
                return self.project(project_id, active)
        row = checked(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(), "Progetto")
        project = decode_row(row, ("mixer",))
        project["archived"] = bool(project["archived"])
        project["assets"] = [self.public_asset(r) for r in db.execute(
            "SELECT * FROM assets WHERE project_id=? ORDER BY created_at,id", (project_id,))]
        project["jobs"] = [self.public_job(r) for r in db.execute(
            "SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC", (project_id,))]
        project["analyses"] = [self.public_analysis(r) for r in db.execute(
            "SELECT * FROM analyses WHERE project_id=? ORDER BY created_at DESC", (project_id,))]
        project["exports"] = [self.public_export(r) for r in db.execute(
            "SELECT * FROM exports WHERE project_id=? ORDER BY created_at DESC", (project_id,))]
        return project

    def create_project(self, name, source=None):
        identifier, timestamp = uid(), now()
        with self.connect(write=True) as db:
            db.execute("INSERT INTO projects(id,name,created_at,updated_at) VALUES(?,?,?,?)",
                       (identifier, name, timestamp, timestamp))
            if source:
                original = self.project(source, db)
                copies = {asset["id"]: uid() for asset in original["assets"]}
                for asset in original["assets"]:
                    row = self.asset(source, asset["id"], db)
                    db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)", (
                        copies[row["id"]], identifier, row["stem"], row["kind"], row["status"],
                        None, row["name"], row["path"], encode(row["metadata"]), timestamp))
                for asset in original["assets"]:
                    metadata = asset["metadata"]
                    if metadata.get("inputs"):
                        metadata["inputs"] = {
                            stem: copies.get(value, value) for stem, value in metadata["inputs"].items()
                        }
                    db.execute("UPDATE assets SET parent_id=?,metadata=? WHERE id=?",
                               (copies.get(asset["parent_id"]), encode(metadata), copies[asset["id"]]))
                for analysis in original["analyses"]:
                    payload = {key: value for key, value in analysis.items()
                               if key not in {"id", "asset_id", "created_at"}}
                    db.execute("INSERT INTO analyses VALUES(?,?,?,?,?)",
                               (uid(), identifier, copies[analysis["asset_id"]], encode(payload), timestamp))
                mixer = original.get("mixer")
                if mixer:
                    for track in mixer.get("tracks", {}).values():
                        track["asset_id"] = copies[track["asset_id"]]
                    db.execute("UPDATE projects SET mixer=? WHERE id=?", (encode(mixer), identifier))
            return self.project(identifier, db)

    def patch_project(self, project_id, patch):
        with self.connect(write=True) as db:
            row = checked(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(), "Progetto")
            db.execute("UPDATE projects SET name=?,archived=?,updated_at=? WHERE id=?", (
                patch.get("name", row["name"]), patch.get("archived", row["archived"]), now(), project_id))
            return self.project(project_id, db)

    @staticmethod
    def public_asset(row):
        return {k: v for k, v in decode_row(row, ("metadata",)).items() if k not in {"path", "project_id"}}

    def asset(self, project_id, asset_id, db=None):
        if db is None:
            with self.connect() as active:
                return self.asset(project_id, asset_id, active)
        return decode_row(checked(db.execute("SELECT * FROM assets WHERE id=? AND project_id=?",
                                             (asset_id, project_id)).fetchone(), "Versione audio"), ("metadata",))

    def set_approval(self, project_id, asset_id, status):
        with self.connect(write=True) as db:
            asset = self.asset(project_id, asset_id, db)
            if asset["kind"] != "restored":
                raise Conflict("La revisione riguarda soltanto le versioni restaurate.")
            db.execute("UPDATE assets SET status=? WHERE id=?", (status, asset_id))
            if status == "approved":
                source = asset["parent_id"]
                operations = asset["metadata"].get("requested_operations", ())
                for row in db.execute("SELECT * FROM analyses WHERE asset_id=?", (source,)).fetchall():
                    payload = json.loads(row["payload"])
                    for event in payload["events"]:
                        proposal = event.get("proposed_operation") or {}
                        if event["status"] == "confirmed" and any(
                            not op.get("bypass") and proposal.get("type") == op["type"]
                            and op["start_sample"] <= event["start_sample"] < event["end_sample"] <= op["end_sample"]
                            for op in operations
                        ):
                            event["status"] = "repaired"
                    db.execute("UPDATE analyses SET payload=? WHERE id=?", (encode(payload), row["id"]))
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
            record = self.asset(project_id, asset_id, db)
            return {k: v for k, v in record.items() if k not in {"path", "project_id"}}

    @staticmethod
    def public_analysis(row):
        return dict(json.loads(row["payload"]), id=row["id"],
                    asset_id=row["asset_id"], created_at=row["created_at"])

    def analysis(self, project_id, analysis_id, db=None):
        if db is None:
            with self.connect() as active:
                return self.analysis(project_id, analysis_id, active)
        return self.public_analysis(checked(db.execute(
            "SELECT * FROM analyses WHERE id=? AND project_id=?", (analysis_id, project_id)).fetchone(), "Analisi"))

    def review_event(self, project_id, analysis_id, event_id, patch):
        with self.connect(write=True) as db:
            analysis = self.analysis(project_id, analysis_id, db)
            event = checked(next((e for e in analysis["events"] if e["id"] == event_id), None), "Anomalia")
            updated = dict(event, **patch)
            limit = self.asset(project_id, analysis["asset_id"], db)["metadata"]["sample_count"]
            if not 0 <= updated["start_sample"] < updated["end_sample"] <= limit:
                raise ValueError("La regione dell'anomalia è fuori dalla timeline.")
            event.update(updated)
            if event.get("proposed_operation") and any(key in patch for key in ("start_sample", "end_sample")):
                event["proposed_operation"].update(start_sample=event["start_sample"], end_sample=event["end_sample"])
            db.execute("UPDATE analyses SET payload=? WHERE id=?",
                       (encode({k: v for k, v in analysis.items() if k not in {"id", "asset_id", "created_at"}}), analysis_id))
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
            return analysis

    @staticmethod
    def public_export(row):
        return dict(json.loads(row["payload"]), id=row["id"], created_at=row["created_at"])

    def export(self, project_id, export_id):
        with self.connect() as db:
            return self.public_export(checked(db.execute(
                "SELECT * FROM exports WHERE id=? AND project_id=?", (export_id, project_id)).fetchone(), "Esportazione"))

    @staticmethod
    def public_job(row):
        return {k: v for k, v in decode_row(row, ("result",)).items()
                if k not in {"payload", "idempotency", "heartbeat"}}

    def global_jobs(self):
        with self.connect() as db:
            return [self.public_job(row) for row in db.execute(
                "SELECT * FROM jobs WHERE project_id IS NULL ORDER BY created_at DESC,id")]

    def job(self, job_id, db=None, private=False):
        if db is None:
            with self.connect() as active:
                return self.job(job_id, active, private)
        row = checked(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone(), "Elaborazione")
        return decode_row(row, ("payload", "result")) if private else self.public_job(row)

    def enqueue(self, project_id, kind, payload, key=None, *, fingerprint=None, job_id=None):
        identifier, timestamp = job_id or uid(), now()
        token = None if key is None else encode([project_id, kind, key])
        with self.connect(write=True) as db:
            if project_id:
                project = checked(db.execute("SELECT archived FROM projects WHERE id=?", (project_id,)).fetchone(), "Progetto")
                if project["archived"]:
                    raise Conflict("Riapri il progetto archiviato per avviare un'elaborazione.")
            if token:
                existing = db.execute("SELECT * FROM jobs WHERE idempotency=?", (token,)).fetchone()
                if existing:
                    existing_payload = json.loads(existing["payload"])
                    equivalent = existing_payload == payload
                    if fingerprint:
                        equivalent = existing_payload.get("fingerprint") == fingerprint
                    if not equivalent:
                        raise Conflict("La chiave di idempotenza è associata a una richiesta diversa.")
                    return self.public_job(existing)
            db.execute("""INSERT INTO jobs(id,project_id,type,status,stage,payload,created_at,updated_at,idempotency)
                VALUES(?,?,?,'queued','In coda',?,?,?,?)""",
                       (identifier, project_id, kind, encode(payload), timestamp, timestamp, token))
            return self.job(identifier, db)

    def claim(self):
        with self.connect(write=True) as db:
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return None
            identifier = row["id"]
            db.execute("""UPDATE jobs SET status='running',stage='Avvio',updated_at=?,heartbeat=?,
                          attempts=attempts+1 WHERE id=?""", (now(), time.time(), identifier))
            return self.job(identifier, db, private=True)

    def recover(self):
        with self.connect(write=True) as db:
            db.execute("""UPDATE jobs SET status='failed', stage='Interrotto', updated_at=?,
                       error='Worker interrotto. Ripeti per ricominciare dagli input integri.'
                       WHERE status='running'""", (now(),))
            db.execute("""UPDATE jobs SET status='cancelled',stage='Annullato',updated_at=?
                       WHERE status='cancelling'""", (now(),))

    def cancel(self, identifier):
        with self.connect(write=True) as db:
            job = self.job(identifier, db)
            if job["status"] == "queued":
                db.execute("UPDATE jobs SET status='cancelled',stage='Annullato',updated_at=? WHERE id=?",
                           (now(), identifier))
            elif job["status"] == "running":
                db.execute("UPDATE jobs SET status='cancelling',stage='Annullamento',updated_at=? WHERE id=?",
                           (now(), identifier))
            return self.job(identifier, db)

    def retry(self, identifier):
        with self.connect(write=True) as db:
            job = self.job(identifier, db)
            if job["status"] not in {"failed", "blocked", "cancelled"}:
                raise Conflict("Puoi ripetere lavori falliti, bloccati o annullati.")
            db.execute("""UPDATE jobs SET status='queued',stage='In coda',error=NULL,result=NULL,
                          total=NULL,processed=NULL,heartbeat=NULL,updated_at=? WHERE id=?""", (now(), identifier))
            return self.job(identifier, db)

    def progress(self, identifier, stage=None, processed=None, total=None):
        with self.connect(write=True) as db:
            if stage is None:
                db.execute("UPDATE jobs SET heartbeat=? WHERE id=? AND status IN ('running','cancelling')",
                           (time.time(), identifier))
            else:
                db.execute("""UPDATE jobs SET stage=?,processed=?,total=?,updated_at=?,heartbeat=?
                              WHERE id=? AND status='running'""",
                           (stage, processed, total, now(), time.time(), identifier))

    def complete(self, identifier, stage, result, artifacts, status="succeeded", error=None):
        with self.connect(write=True) as db:
            job = self.job(identifier, db, private=True)
            if job["status"] == "cancelling":
                stage, status, result, error = "Annullato", "cancelled", None, None
            else:
                for table, values in artifacts:
                    placeholders = ",".join("?" for _ in values)
                    db.execute(f"INSERT INTO {table} VALUES({placeholders})", values)
                if job["project_id"] and status == "succeeded":
                    db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), job["project_id"]))
                    if job["type"] == "mix":
                        db.execute("UPDATE projects SET mixer=? WHERE id=?", (encode(job["payload"]), job["project_id"]))
            db.execute("""UPDATE jobs SET status=?,stage=?,result=?,error=?,updated_at=?,heartbeat=?
                          WHERE id=?""",
                       (status, stage, encode(result) if result is not None else None, error, now(), time.time(), identifier))
            return status

    def asset_values(self, job, stem, kind, status, parent, name, path, metadata):
        return (
            uid(), job["project_id"], stem, kind, status, parent, name, self.relative(path),
            encode(dict(metadata, sha256=sha256(path), schema_version=1, job_id=job["id"])), now(),
        )
