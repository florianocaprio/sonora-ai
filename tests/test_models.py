"""Model tests with synthetic orchestration and opt-in real checkpoints."""

import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from packages.model_adapters import (
    ModelUnavailable,
    SeparationCancelled,
    install_model,
    list_models,
    probe_capabilities,
    separate_audio,
    verify_model,
)
from packages.model_adapters import registry
from packages.model_adapters.benchmark import _measure
from packages.model_adapters.separation import STEMS, SeparationAdapter


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.models = self.work / "models"
        self.source = self.work / "source.wav"
        self.destination = self.work / "output"

    def _signal(self, rate, frames, channels=2):
        rng = np.random.default_rng(123)
        t = np.arange(frames) / rate
        rows = [np.sin(t * (720 + index * 200)) + rng.normal(0, 0.3, frames) for index in range(channels)]
        values = np.asarray(rows, dtype=np.float32).T * 0.2
        sf.write(self.source, values, rate, subtype="FLOAT")
        return values

    def _separate(self, model, backend="cpu", *, cancelled=lambda: False):
        progress = []
        metadata = separate_audio(
            self.source,
            self.destination,
            self.models,
            model,
            backend,
            progress=lambda done, total: progress.append((done, total)),
            cancelled=cancelled,
        )
        return metadata, progress

    def _read_and_check_sum(self, signal, rate):
        audio = []
        for stem in (*STEMS, "residual"):
            block, actual_rate = sf.read(self.destination / f"{stem}.wav", dtype="float32", always_2d=True)
            self.assertEqual(actual_rate, rate)
            self.assertEqual(block.shape, signal.shape)
            self.assertTrue(np.isfinite(block).all())
            audio.append(block)
        np.testing.assert_allclose(np.sum(audio, axis=0), signal, rtol=0, atol=2e-7)
        return audio

    def test_catalog_and_missing_model(self):
        entries = list_models(self.models)
        self.assertEqual([entry["id"] for entry in entries], ["dbs-tiger-dnr", "bandit-v2"])
        self.assertEqual(entries[0]["outputs"], ["music", "effects", "dialogue"])
        self.assertTrue(all(entry["stereo_mode"] == "independent_lr" for entry in entries))
        with self.assertRaisesRegex(ModelUnavailable, "Checkpoint.*assente"):
            verify_model(self.models, "dbs-tiger-dnr")
        with self.assertRaises(ValueError):
            verify_model(self.models, "../unexpected")

    def test_corrupt_checkpoint_is_rejected(self):
        checkpoint = self.models / "dbs-tiger-dnr" / "model.safetensors"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"not a model")
        with self.assertRaisesRegex(ModelUnavailable, "SHA-256 errato"):
            verify_model(self.models, "dbs-tiger-dnr")

    def test_install_validates_download_before_publication(self):
        model = registry.get_manifest("dbs-tiger-dnr")
        valid = b"download fixture"
        manifest = {
            **model,
            "size_bytes": len(valid),
            "sha256": hashlib.sha256(valid).hexdigest(),
        }
        checkpoint = registry.checkpoint_path(self.models, manifest)
        with patch.object(registry, "get_manifest", return_value=manifest), patch.object(
            registry, "build_opener",
        ) as opener:
            download = opener.return_value.open
            download.return_value = io.BytesIO(b"invalid payload!")
            with self.assertRaisesRegex(ModelUnavailable, "SHA-256 errato"):
                install_model(self.models, model["id"])
            self.assertEqual(list(checkpoint.parent.iterdir()), [])
            download.return_value = io.BytesIO(valid)
            progress = []
            result = install_model(self.models, model["id"], progress=lambda *args: progress.append(args))
            self.assertEqual(checkpoint.read_bytes(), valid)
            self.assertEqual(result["status"], "verified")
            self.assertEqual(progress, [(len(valid), len(valid))])
            self.assertEqual(list(checkpoint.parent.iterdir()), [checkpoint])

    def test_overlap_add_same_rate_and_both_protocols(self):
        for model, rate in (("dbs-tiger-dnr", 44100), ("bandit-v2", 48000)):
            with self.subTest(model=model):
                self.destination = self.work / model
                signal = self._signal(rate, rate * 9 + 17)
                # Identity windows are a transport fixture only, independent of trained weights.
                def predict(_adapter, window, **_callbacks):
                    return np.stack([window * 0.125, window * 0.5, window * -0.25])

                with patch.object(SeparationAdapter, "load"), patch.object(
                    SeparationAdapter, "separate", autospec=True, side_effect=predict,
                ):
                    result, progress = self._separate(model)
                count = progress[-1][1]
                self.assertGreater(count, 1)
                self.assertEqual(progress, [(index, count) for index in range(1, count + 1)])
                self.assertEqual(result["stereo_mode"], "independent_lr")
                self.assertEqual(result["sample_count"], len(signal))
                dialogue, music, effects, _ = self._read_and_check_sum(signal, rate)
                np.testing.assert_allclose(dialogue, signal * 0.125, rtol=0, atol=4e-8)
                np.testing.assert_allclose(music, signal * 0.5, rtol=0, atol=8e-8)
                np.testing.assert_allclose(effects, signal * -0.25, rtol=0, atol=4e-8)

    def test_resampling_keeps_timeline_and_cancellation_cleans_staging(self):
        signal = self._signal(48000, 5031)

        def predict(_adapter, window, **_callbacks):
            return np.stack([window, window * 0, window * 0])

        with patch.object(SeparationAdapter, "load"), patch.object(
            SeparationAdapter, "separate", autospec=True, side_effect=predict,
        ):
            with self.assertRaises(SeparationCancelled):
                self._separate("dbs-tiger-dnr", cancelled=lambda: True)
            self.assertEqual(list(self.destination.iterdir()), [])
            self._separate("dbs-tiger-dnr")
        self._read_and_check_sum(signal, 48000)

    def test_separation_rejects_unloaded(self):
        adapter = SeparationAdapter(self.models, "dbs-tiger-dnr", "cpu")
        with self.assertRaises(ModelUnavailable):
            adapter.separate(np.zeros((32, 1), dtype=np.float32))

    def test_reference_benchmark_gain_and_direction(self):
        reference = np.array([
            [1, -1, 1, -1],
            [1, 1, -1, -1],
            [1, -1, -1, 1],
        ], dtype=np.float32)
        estimate = reference.copy()
        estimate[0] = reference[0] * 0.5 + reference[1] * 0.1
        results = _measure(estimate, reference)
        dialogue = results["dialogue"]
        self.assertAlmostEqual(dialogue["projected_gain_db"], -6.0206, places=3)
        self.assertAlmostEqual(dialogue["si_sdr_db"], 13.9794, places=3)
        self.assertAlmostEqual(
            dialogue["projected_crosstalk_db_relative_to_own_component"]["music"], -13.9794, places=3,
        )

    def test_real_checkpoint(self):
        cache = os.environ.get("SONORA_TEST_MODEL_DIR")
        if not cache:
            self.skipTest("Indica SONORA_TEST_MODEL_DIR per usare un checkpoint identificato.")
        self.models = Path(cache)
        model = os.environ.get("SONORA_TEST_MODEL", "dbs-tiger-dnr")
        backend = os.environ.get("SONORA_TEST_BACKEND", "cpu")
        if backend not in probe_capabilities(model)["backends"]:
            self.skipTest(f"Backend {backend} indisponibile per {model}.")
        checkpoint = registry.checkpoint_path(self.models, registry.get_manifest(model))
        if not checkpoint.is_file():
            self.skipTest(f"Checkpoint assente per {model}.")
        verify_model(self.models, model)
        # Use a 48 kHz nonstationary signal and an odd frame count. For DBS this
        # covers conversion and exact project-frame cropping. Bandit is same-rate.
        rate = 48000
        signal = self._signal(rate, 24013, channels=1)
        result, _ = self._separate(model, backend)
        dialogue, music, effects, _ = self._read_and_check_sum(signal, rate)
        self.assertEqual(result["backend"], backend)
        self.assertTrue(all(np.max(np.abs(output)) > 1e-6 for output in (dialogue, music, effects)))
        self.assertFalse(np.array_equal(dialogue, music))


if __name__ == "__main__":
    unittest.main()
