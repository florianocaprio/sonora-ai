"""Orchestrazione locale con fixture deterministica e integrazione con pesi reali opzionale."""

import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from services.api.app import create_app
from services.settings import Settings
from services.storage import Store
from services.worker.engine import run_job


def synthetic_audio():
    rate = 48000
    time = np.arange(rate // 2) / rate
    data = (0.07 * np.sin(2 * np.pi * 220 * time) + 0.025 * np.sin(2 * np.pi * 50 * time) + 0.06)
    data[6000] = 0.83
    data[14400:14640] = 0.0
    stream = io.BytesIO()
    sf.write(stream, data, rate, format="WAV", subtype="FLOAT")
    return stream.getvalue()


class StudioFlow(unittest.TestCase):
    def setUp(self):
        runtime = tempfile.TemporaryDirectory(prefix="sonora-test-")
        self.addCleanup(runtime.cleanup)
        self.settings = Settings(Path(runtime.name) / "runtime",
                                 Path(os.getenv("SONORA_TEST_MODEL_DIR", runtime.name)) / (
                                     "" if os.getenv("SONORA_TEST_MODEL_DIR") else "models"),
                                 8765, 20 << 20, Path(runtime.name) / "web")
        self.store = Store(self.settings.data)
        self.client = self.enterContext(TestClient(create_app(self.settings), base_url="http://127.0.0.1:8765"))
        self.token = self.client.get("/api/v1/session").json()["token"]
        self.headers = {"X-Sonora-Token": self.token}
        self.project = self.call("POST", "/projects", body={"name": "Restauro · fixture"}, expected=201)
        self.project_path = f"/projects/{self.project['id']}"

    def call(self, verb, path, body=None, *, expected=200, **kwargs):
        response = self.client.request(verb, f"/api/v1{path}", json=body,
                                       headers={**self.headers, **kwargs.pop("headers", {})}, **kwargs)
        if response.status_code != expected:
            self.fail(f"{verb} {path}: HTTP {response.status_code}, {response.text[:900]}")
        return response.json()

    def execute(self, queued, *, target="succeeded"):
        claimed = self.store.claim()
        self.assertEqual(claimed["id"], queued["id"])
        run_job(self.store, self.settings, claimed, threading.Event())
        job = self.call("GET", f"/jobs/{queued['id']}")
        self.assertEqual(job["status"], target, job)
        self.assertEqual(job["attempts"], 1)
        return job["result"]

    def enqueue(self, kind, body):
        return self.call("POST", f"{self.project_path}/{kind}", body=body, expected=202)

    def upload(self):
        raw = self.original_bytes = synthetic_audio()
        kwargs = dict(files={"file": ("sintesi.mp3.mpeg", raw, "application/octet-stream")},
                      headers={"Idempotency-Key": "fixture-import"})
        queued = self.call("POST", f"{self.project_path}/import", expected=202, **kwargs)
        self.assertEqual(queued["id"], self.call("POST", f"{self.project_path}/import", expected=202, **kwargs)["id"])
        self.assertEqual(len(list(self.store.uploads.iterdir())), 1)
        asset_id = self.execute(queued)["asset_id"]
        source = self.client.get(f"/api/v1{self.project_path}/assets/{asset_id}/source", headers=self.headers)
        self.assertEqual(source.content, raw)
        return asset_id

    def analysis_and_restore(self, asset_id):
        analysis_id = self.execute(self.enqueue("analyze", {"asset_id": asset_id}))["analysis_id"]
        project = self.call("GET", self.project_path)
        analysis = next(item for item in project["analyses"] if item["id"] == analysis_id)
        self.assertTrue(analysis["metrics"])
        if analysis["events"]:
            event_id = analysis["events"][0]["id"]
            reviewed = self.call("PATCH", f"{self.project_path}/analyses/{analysis_id}/events/{event_id}",
                                 body={"status": "confirmed", "note": "Verificato in fixture"})
            self.assertEqual(reviewed["events"][0]["status"], "confirmed")
        restored = self.execute(self.enqueue("restore", {"asset_id": asset_id, "profile": "high", "operations": [
            {"type": "microgap", "start_sample": 14400, "end_sample": 14640, "wet": 1, "params": {}},
            {"type": "dc_remove", "start_sample": 17000, "end_sample": 21900, "wet": 1, "params": {}},
        ]}))
        return restored["asset_id"]

    def mix_and_export(self, inputs):
        queued = self.enqueue("mix", {"tracks": {stem: {"asset_id": asset} for stem, asset in inputs.items()}})
        mix_id = self.execute(queued)["asset_id"]
        record = self.execute(self.enqueue("export", {"mix_id": mix_id, "format": "wav_pcm24"}))
        project = self.call("GET", self.project_path)
        exported = next(item for item in project["exports"] if item["id"] == record["export_id"])
        names = {item["name"]: item["url"] for item in exported["artifacts"]}
        self.assertTrue({"master.wav", "manifest.json", "report.html"} <= names.keys())
        report = self.client.get(names["manifest.json"]).json()
        self.assertEqual(report["project_id"], self.project["id"])
        self.assertEqual(set(report["tracks"]), {"master", *inputs.keys()})
        master = self.client.get(names["master.wav"])
        self.assertEqual(sf.info(io.BytesIO(master.content)).subtype, "PCM_24")
        offline = Store(self.settings.data).project(self.project["id"])
        self.assertEqual(offline["mixer"]["tracks"], project["mixer"]["tracks"])
        self.assertEqual(offline["exports"], project["exports"])
        return project

    def test_fixture_pipeline_without_ai(self):
        asset = self.upload()
        result = self.call("GET", f"{self.project_path}/assets/{asset}/waveform?bins=32")
        self.assertEqual(len(result["peaks"]), 32)
        tile = self.call("GET", f"{self.project_path}/assets/{asset}/spectrogram?columns=12")
        self.assertIn("fft_size", tile)
        media = self.client.get(f"/api/v1{self.project_path}/assets/{asset}/media", headers={"Range": "bytes=0-15"})
        self.assertEqual(media.status_code, 206)
        self.assertEqual(len(media.content), 16)
        restored = self.analysis_and_restore(asset)
        self.call("POST", f"{self.project_path}/mix", body={"tracks": {"original": {"asset_id": restored}}},
                  expected=422)
        self.call("PATCH", f"{self.project_path}/assets/{restored}", body={"status": "approved"})
        self.mix_and_export({"original": restored})
        copy = self.call("POST", f"{self.project_path}/duplicate", body={"name": "Copia"}, expected=201)
        self.assertGreater(len(copy["assets"]), 2)
        self.assertNotEqual(copy["assets"][0]["id"], asset)
        copied = next(item for item in copy["assets"] if item["kind"] == "original")
        actual = self.client.get(f"/api/v1/projects/{copy['id']}/assets/{copied['id']}/source", headers=self.headers)
        self.assertEqual(actual.content, self.original_bytes)

    def test_loopback_token_and_origin(self):
        self.assertEqual(self.client.get("/api/v1/projects").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/session", headers={"Host": "external.test:8765"}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/session", headers={"Origin": "https://external.test"}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/session", headers={"Sec-Fetch-Site": "same-site"}).status_code, 403)

    def test_cancel_retry_recover_and_idempotency(self):
        asset = self.upload()
        body = {"asset_id": asset}
        headers = {"Idempotency-Key": "analysis"}
        queued = self.call("POST", f"{self.project_path}/analyze", body=body, headers=headers, expected=202)
        self.assertEqual(self.call("POST", f"/jobs/{queued['id']}/cancel")["status"], "cancelled")
        self.assertEqual(self.call("POST", f"/jobs/{queued['id']}/retry")["status"], "queued")
        self.assertEqual(self.store.claim()["id"], queued["id"])
        self.store.recover()
        self.assertEqual(self.call("GET", f"/jobs/{queued['id']}")["status"], "failed")
        self.call("POST", f"{self.project_path}/analyze", body={**body, "depth": "deep"}, headers=headers, expected=409)
        response = self.client.get(f"/api/v1/jobs/{queued['id']}/events")
        self.assertEqual(json.loads(response.text.split("data: ")[1])["status"], "failed")

    def test_missing_model_is_blocked(self):
        if os.getenv("SONORA_TEST_MODEL_DIR"):
            self.skipTest("Il percorso reale dei pesi è attivo per questa sessione.")
        asset = self.upload()
        self.execute(self.enqueue("separate", {"asset_id": asset, "model_id": "dbs-tiger-dnr", "backend": "cpu"}),
                     target="blocked")

    def test_real_checkpoint_pipeline(self):
        model = os.getenv("SONORA_TEST_MODEL")
        if not model or not os.getenv("SONORA_TEST_MODEL_DIR"):
            self.skipTest("Configura SONORA_TEST_MODEL e SONORA_TEST_MODEL_DIR per l'inferenza reale.")
        from packages.model_adapters import ModelUnavailable, verify_model

        backend = os.getenv("SONORA_TEST_BACKEND", "cpu")
        if backend == "mps":
            import torch
            if not torch.backends.mps.is_available():
                self.skipTest("MPS non disponibile in questo processo.")
        try:
            verify_model(self.settings.models, model)
        except ModelUnavailable as error:
            self.skipTest(str(error))
        original = self.upload()
        separation = self.execute(self.enqueue("separate", {"asset_id": original, "model_id": model, "backend": backend}))
        stems = separation["asset_ids"]
        self.assertEqual(set(stems), {"dialogue", "music", "effects", "residual"})
        restored = self.analysis_and_restore(stems["dialogue"])
        self.call("PATCH", f"{self.project_path}/assets/{restored}", body={"status": "approved"})
        self.mix_and_export({"dialogue": restored, "music": stems["music"], "effects": stems["effects"]})
