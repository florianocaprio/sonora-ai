"""Regressioni dei confini della patch e prova opzionale con i pesi ufficiali."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from packages import inpainting
from packages.audio_core.io import BLOCK
from packages.model_adapters.registry import ModelUnavailable


class InpaintingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.wav"
        self.output = self.root / "candidate.wav"

    def write(self, samples, rate):
        sf.write(self.source, samples, rate, subtype="FLOAT")

    def test_catalog_matches_real_weights_and_missing_model(self):
        model = next(item for item in inpainting.list_models(self.root) if item["id"] == inpainting.MODEL_ID)
        self.assertEqual(model["task"], "inpainting")
        self.assertEqual(model["status"], "available")
        self.assertEqual(model["native_sample_rate"], 22050)
        self.assertEqual(model["min_gap_ms"], 20)
        self.assertEqual(model["max_gap_ms"], 250)
        self.assertEqual(len(model["sha256"]), 64)
        with self.assertRaisesRegex(ModelUnavailable, "Checkpoint.*assente"):
            inpainting.verify_model(self.root)

    def test_rejects_gap_without_context_and_in_place_writes(self):
        self.write(np.zeros(88200, dtype=np.float32), 44100)
        with self.assertRaisesRegex(ValueError, "almeno 250 ms"):
            inpainting.inpaint(self.source, self.output, 0, 1500, self.root)
        with self.assertRaisesRegex(ValueError, "20 a 250 ms"):
            inpainting.inpaint(self.source, self.output, 12000, 12500, self.root)
        with self.assertRaisesRegex(ValueError, "destinazione distinta"):
            inpainting.inpaint(self.source, self.source, 12000, 13500, self.root)
        self.assertFalse(self.output.exists())

    @staticmethod
    def stub_denoise(_model, observed, first, last, *, seed, progress, cancelled):
        reconstructed = observed.copy()
        reconstructed[first:last, :] = (0.2, -0.2)
        return reconstructed

    @patch("packages.inpainting.engine.verify_model")
    @patch("packages.inpainting.engine._load_denoiser")
    @patch("packages.inpainting.engine._diffuse", new=stub_denoise.__func__)
    def test_exact_multiblock_replacement_and_sample_rate(self, _load, verify):
        verify.return_value = {"backends": ["cpu"], "sha256": "fixture", "weights_revision": "fixture",
                               "code_revision": "fixture", "training_domain": "fixture"}
        for rate in (8000, 44100, 48000, 192000):
            with self.subTest(rate=rate):
                start = BLOCK - rate // 50
                end = start + rate // 13
                frames = end + rate
                samples = np.column_stack((np.arange(frames) % 31, np.arange(frames) % 23)).astype(np.float32) / 1000
                self.write(samples, rate)
                metadata = inpainting.inpaint(self.source, self.output, start, end, self.root, seed=123)
                restored, actual_rate = sf.read(self.output, dtype="float32", always_2d=True)
                self.assertEqual(metadata["classification"], "generated")
                self.assertEqual(metadata["stereo_mode"], "independent_lr")
                self.assertEqual(metadata["seed"], 123)
                self.assertEqual(restored.shape, samples.shape)
                self.assertEqual(actual_rate, rate)
                np.testing.assert_array_equal(restored[:start], samples[:start])
                np.testing.assert_array_equal(restored[end:], samples[end:])
                self.assertGreater(restored[(start + end) // 2, 0], 0.16)
                self.assertLess(restored[(start + end) // 2, 1], -0.16)

    def test_cancellation_leaves_existing_output_unmodified(self):
        self.write(np.zeros(88200, dtype=np.float32), 44100)
        self.output.write_bytes(b"protected")
        with self.assertRaises(InterruptedError):
            inpainting.inpaint(self.source, self.output, 12500, 14000, self.root, cancelled=lambda: True)
        self.assertEqual(self.output.read_bytes(), b"protected")

    def test_real_piano_gap(self):
        root = os.getenv("SONORA_TEST_INPAINT_MODEL_DIR")
        if not root:
            self.skipTest("Imposta SONORA_TEST_INPAINT_MODEL_DIR per i pesi ufficiali.")
        rate = 48000
        time = np.arange(3 * rate) / rate
        clean = np.zeros(len(time), dtype=np.float64)
        for pitch, onset in [(48, 0.03), (60, 0.28), (64, 0.49), (67, 0.71), (72, 1.04)]:
            note_time = np.maximum(time - onset, 0)
            frequency = 440 * 2 ** ((pitch - 69) / 12)
            for partial in range(1, 7):
                envelope = (1 - np.exp(-note_time * 240)) * np.exp(-(1 + 0.42 * partial) * note_time)
                partial_frequency = frequency * partial * (1 + 0.0001 * partial**2)
                clean += np.sin(2 * np.pi * partial_frequency * note_time) * envelope * (0.08 / partial**1.7)
        clean = clean.astype(np.float32)
        start, end = round(rate * 0.82), round(rate * 0.90)
        masked = clean.copy()
        masked[start:end] = 0
        self.write(masked, rate)
        progress = []
        metadata = inpainting.inpaint(self.source, self.output, start, end, Path(root), seed=42,
                                     progress=lambda done, total: progress.append((done, total)))
        reconstructed, actual_rate = sf.read(self.output, dtype="float32")
        np.testing.assert_array_equal(reconstructed[:start], masked[:start])
        np.testing.assert_array_equal(reconstructed[end:], masked[end:])
        self.assertEqual(actual_rate, rate)
        self.assertEqual(reconstructed.shape, clean.shape)
        self.assertEqual(metadata["backend"], "cpu")
        self.assertGreater(np.linalg.norm(reconstructed[start:end]), 0.05)
        self.assertTrue(np.isfinite(reconstructed).all())
        self.assertEqual(progress[-1], (metadata["inference_steps_per_channel"],) * 2)
        rms_error = np.sqrt(np.mean((reconstructed[start:end] - clean[start:end])**2))
        masked_rms_error = np.sqrt(np.mean(clean[start:end]**2))
        print(f"RMSE patch={rms_error:.6f}; RMSE maschera muta={masked_rms_error:.6f}; "
              f"tempo inferenza={metadata['inference_seconds']:.2f}s; "
              f"RSS massimo processo={metadata['process_peak_rss_bytes']:,} B")
