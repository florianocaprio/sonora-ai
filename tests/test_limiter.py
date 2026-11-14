"""Numeric regressions for the native true-peak master limiter."""

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from scipy import signal
import soundfile as sf

from packages.audio_core.io import BLOCK, export_audio
from packages.dsp_core import render_mix
from packages.dsp_core.limiter import measure_true_peak


class LimiterTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.folder = Path(scratch.name)

    def write(self, name, audio, rate=48000):
        path = self.folder / name
        sf.write(path, np.asarray(audio, dtype=np.float32), rate, subtype="FLOAT")
        return path

    def limit(self, source, name="limited.wav", **master):
        path = self.folder / name
        result = render_mix({"original": source}, path, {"master": {"limiter": {"enabled": True}, **master}})
        return path, result

    @staticmethod
    def read(path):
        return sf.read(path, dtype="float32", always_2d=True)[0]

    @staticmethod
    def tapered_tone(rate, fraction, amplitude, phase, seconds=0.5):
        tone = amplitude * np.sin(2 * np.pi * fraction * np.arange(round(rate * seconds)) + np.deg2rad(phase))
        fade = np.sin(np.linspace(0, np.pi / 2, rate // 100)) ** 2
        tone[:len(fade)] *= fade
        tone[-len(fade):] *= fade[::-1]
        return np.repeat(tone[:, None], 2, axis=1)

    def test_ebu_3341_synthesized_steady_state_true_peaks(self):
        # Independent synthesis based on cases 15-19 of EBU Tech 3341 Table 1.
        cases = ((4, 0.5, 0, -6), (4, 0.5, 45, -6), (6, 0.5, 60, -6),
                 (8, 0.5, 67.5, -6), (4, 1.41, 45, 3))
        rate = 48000
        for divisor, amplitude, phase, reference in cases:
            with self.subTest(divisor=divisor, amplitude=amplitude, phase=phase):
                tone = self.tapered_tone(rate, 1 / divisor, amplitude, phase)
                original = self.write("tone.wav", tone, rate)
                peak = measure_true_peak(original)
                self.assertGreaterEqual(peak, reference - 0.4)
                self.assertLessEqual(peak, reference + 0.2)

    def test_intersample_only_overshoot_and_bit_exact_idle(self):
        rate = 48000
        tone = self.tapered_tone(rate, 0.25, 0.9, 45)
        source = self.write("tone.wav", tone, rate)
        ceiling = -2.0
        self.assertLess(20 * np.log10(np.abs(tone).max()), ceiling)
        self.assertGreater(measure_true_peak(source), ceiling + 1)
        path, result = self.limit(source, ceiling_dbtp=ceiling)
        self.assertEqual(self.read(path).shape, tone.shape)
        self.assertFalse(result["ceiling_exceeded"])
        self.assertGreater(result["limiter"]["gain_reduction_db"], 1)
        self.assertLessEqual(result["true_peak_dbtp"], ceiling)
        safe = self.write("safe.wav", tone * 0.1)
        output, idle = self.limit(safe)
        np.testing.assert_array_equal(self.read(output), self.read(safe))
        self.assertEqual(idle["ceiling_dbtp"], -1)
        self.assertEqual(idle["limiter"]["gain_reduction_db"], 0)

    def test_linked_lookahead_and_release_across_block_boundary(self):
        boundary = BLOCK
        distance = 80
        frames = boundary + 16000
        left = np.full(frames, 0.05, dtype=np.float32)
        left[boundary] = 1.5
        left[-1] = 1.2
        stereo = np.column_stack((left, -left * 0.25))
        source = self.write("impulses.wav", stereo)
        output, result = self.limit(source, ceiling_dbtp=-3)
        data = self.read(output)
        self.assertEqual(len(data), frames)
        np.testing.assert_allclose(data[:, 1], data[:, 0] * -0.25, atol=1e-8)
        self.assertEqual(np.argmax(np.abs(data[:, 0])), boundary)
        self.assertGreater(abs(data[-1, 0]), 0.5)
        self.assertLess(float(data[boundary - distance, 0]), 0.045)
        self.assertGreater(float(data[boundary + 12000, 0]), float(data[boundary + distance, 0]))
        self.assertLessEqual(result["true_peak_dbtp"], -3)

    def test_bypass_and_silence(self):
        source = self.write("input.wav", np.array([1.2, -1.2, 0.2], dtype="float32"))
        output, result = self.limit(source, bypass=True)
        self.assertFalse(result["limiter"]["active"])
        self.assertTrue(result["limiter"]["enabled"])
        np.testing.assert_array_equal(self.read(output), self.read(source))
        silent = self.write("silence.wav", np.zeros(1))
        output, result = self.limit(silent)
        self.assertIsNone(result["true_peak_dbtp"])
        self.assertFalse(result["ceiling_exceeded"])
        np.testing.assert_array_equal(self.read(output), self.read(silent))

    def test_coherent_across_supported_rates_and_pcm24(self):
        for rate in (8000, 44100, 48000, 96000, 192000):
            with self.subTest(rate=rate):
                source = self.write("tone.wav", self.tapered_tone(rate, 0.25, 1.4, 45, 0.1), rate)
                output, result = self.limit(source, ceiling_dbtp=-1)
                pcm = self.folder / "export.wav"
                converted = export_audio(output, pcm, format="wav_pcm24")
                self.assertEqual(converted["sample_count"], result["sample_count"])
                self.assertEqual(converted["sample_rate"], rate)
                self.assertLessEqual(measure_true_peak(pcm), -1)

    def test_independent_finite_reconstruction(self):
        rng = np.random.default_rng(318)
        tone = self.tapered_tone(48000, 0.45, 1.55, 17, 1)
        tone[14000:15000] += rng.standard_normal((1000, 2)) * 0.8
        source = self.write("transients.wav", tone)
        output, result = self.limit(source, ceiling_dbtp=-1.5)
        # Other window, finer grid and longer radius than the production detector.
        taps = signal.firwin(2 * 128 * 16 + 1, 1 / 16, window=("kaiser", 11))
        oversampled = signal.resample_poly(self.read(output).astype(np.float64), 16, 1, window=taps, axis=0)
        measured = 20 * np.log10(np.abs(oversampled).max())
        self.assertLessEqual(measured, -1.5 + 0.05)
        self.assertLessEqual(result["true_peak_dbtp"], -1.5)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg non disponibile")
    def test_independent_ffmpeg_verifies_master(self):
        source = self.write("tone.wav", self.tapered_tone(48000, 0.25, 1.41, 45))
        _, result = self.limit(source, ceiling_dbtp=-5)
        self.assertLessEqual(result["limiter"]["reference_true_peak_dbtp"], -5)
        self.assertEqual(result["limiter"]["reference_true_peak_dbtp"], result["loudness"]["true_peak_dbtp"])

    def test_cancelled_limiter_leaves_authoritative_destination_unchanged(self):
        source = self.write("source.wav", np.ones(BLOCK + 16))
        destination = self.write("destination.wav", np.zeros(32))
        before = destination.read_bytes()
        state = 0

        def cancelled():
            nonlocal state
            state += 1
            return state >= 4

        with self.assertRaises(InterruptedError):
            render_mix({"original": source}, destination, {"master": {"limiter": {"enabled": True}}},
                       cancelled=cancelled)
        self.assertEqual(destination.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["destination.wav", "source.wav"])
