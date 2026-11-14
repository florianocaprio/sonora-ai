"""Neural optimization, data isolation and stereo conservation on controlled gaps."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import signal
import soundfile as sf

from packages import inpainting


def fixtures(rate):
    times = np.arange(2 * rate) / rate
    speech = sum(gain * np.sin(2 * np.pi * frequency * times + phase)
                 for frequency, phase, gain in (
                     (140, 0, .09), (280, .7, .038), (420, .9, .024), (700, .4, .027), (1120, 1.3, .009),
                 ))
    speech *= .85 + .12 * np.cos(2 * np.pi * 3.1 * times)
    motor = sum(gain * np.sin(2 * np.pi * frequency * times + phase)
                for frequency, phase, gain in ((145, 0, .09), (290, .7, .04), (437, .3, .024)))
    motor *= .9 + .1 * np.sin(2 * np.pi * .7 * times)
    noise = np.random.default_rng(22).normal(0, .009, len(times))
    motor += signal.sosfilt(signal.butter(4, .15, output="sos"), noise)
    return {"dialogue": speech, "effects": motor}


class ContextualInpaintingTests(unittest.TestCase):
    def test_models_are_ready_without_checkpoints(self):
        directory = Path("/unused")
        extended = {m["stems"][0]: m for m in inpainting.list_models(directory)}
        self.assertEqual(extended["music"]["id"], inpainting.MODEL_ID)
        self.assertIsNone(inpainting.model_for_stem("original"))
        for stem, max_gap in (("dialogue", 80), ("effects", 120)):
            identifier = inpainting.model_for_stem(stem)
            self.assertEqual(inpainting.verify_model(directory, identifier)["status"], "ready")
            self.assertEqual(inpainting.model_limits(stem), (20, max_gap, 250))
            self.assertFalse(extended[stem]["checkpoint_required"])
            self.assertFalse(extended[stem]["can_install"])

    def test_learns_short_gaps_with_unchanged_exterior_and_no_mask_leakage(self):
        rate = 48000
        first = int(0.915 * rate)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.wav"
            target = root / "target.wav"
            for stem, clean in fixtures(rate).items():
                with self.subTest(stem=stem):
                    maximum = inpainting.model_limits(stem)[1]
                    last = first + maximum * rate // 1000
                    original = np.column_stack((clean, -.5 * clean)).astype("float32")
                    contaminated = original.copy()
                    contaminated[first:last] = 0
                    sf.write(source, contaminated, rate, subtype="FLOAT")
                    counts = []
                    metadata = inpainting.inpaint(source, target, first, last, root, stem=stem, seed=11,
                                                   progress=lambda done, total: counts.append((done, total)))
                    patched, actual_rate = sf.read(target, dtype="float32", always_2d=True)
                    expected = original[first:last]
                    candidate = patched[first:last]
                    fade = np.linspace(0, 1, last - first)[:, None]
                    linear = (1 - fade) * original[first-1] + fade * original[last]
                    self.assertEqual(metadata["classification"], "generated")
                    self.assertEqual(metadata["stereo_mode"], "joint")
                    self.assertTrue(metadata["neural_residual_active"])
                    self.assertEqual(counts[-1], (96, 96))
                    self.assertEqual(actual_rate, rate)
                    self.assertTrue(np.isfinite(patched).all())
                    error = np.sqrt(np.mean((candidate - expected) ** 2))
                    self.assertLess(error, float(np.sqrt(np.mean(expected ** 2))) * 0.45)
                    self.assertLess(error, float(np.sqrt(np.mean((linear - expected) ** 2))) * 0.45)
                    self.assertLess(np.max(np.abs(.5 * candidate[:, 0] + candidate[:, 1])), .0003)
                    np.testing.assert_array_equal(patched[:first].view("uint32"), original[:first].view("uint32"))
                    np.testing.assert_array_equal(patched[last:].view("uint32"), original[last:].view("uint32"))
                    contaminated[first:last] = 0.93
                    sf.write(source, contaminated, rate, subtype="FLOAT")
                    again = inpainting.inpaint(source, target, first, last, root, stem=stem, seed=11)
                    np.testing.assert_array_equal(sf.read(target, dtype="float32", always_2d=True)[0], patched)
                    self.assertEqual(metadata["context_sha256"], again["context_sha256"])

    def test_invalid_gap_cancel_and_silence_do_not_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.wav"
            target = root / "target.wav"
            sf.write(source, np.zeros(96000, dtype="float32"), 48000, subtype="FLOAT")
            with self.assertRaisesRegex(ValueError, "20 a 80"):
                inpainting.inpaint(source, target, 24000, 28800, root, stem="dialogue")
            with self.assertRaisesRegex(ValueError, "silenzioso"):
                inpainting.inpaint(source, target, 24000, 28800, root, stem="effects")
            with self.assertRaises(InterruptedError):
                inpainting.inpaint(source, target, 24000, 28800, root, stem="effects",
                                   cancelled=lambda: True)
            self.assertFalse(target.exists())
