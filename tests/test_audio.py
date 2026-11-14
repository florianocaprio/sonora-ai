"""Deterministic DSP regression tests with generated fixtures."""

from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import subprocess
import unittest

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from packages.audio_core import (
    analyze, difference_audio, export_audio, ingest, propose_operations, restore, spectrogram, trim_audio, waveform,
)
from packages.audio_core.io import BLOCK
from packages.dsp_core import render_mix


class AudioFixtureTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name, data, rate=48000, *, format="WAV", subtype="FLOAT"):
        path = self.root / name
        sf.write(path, data, rate, format=format, subtype=subtype)
        return path

    def read(self, path):
        return sf.read(path, dtype="float32", always_2d=True)[0]

    def test_ingest_uses_content_and_keeps_channels_and_float_headroom(self):
        before = np.array([[0.123, -0.456], [1.1, -1.2], [0, 0]], dtype=np.float32)
        original = self.write("mixed.mp3.mpeg", before)
        snapshot = original.read_bytes()
        decoded = self.root / "canonical.wav"
        meta = ingest(original, decoded, None)
        np.testing.assert_array_equal(self.read(decoded), before)
        self.assertEqual(original.read_bytes(), snapshot)
        self.assertEqual((meta["sample_count"], meta["sample_rate"], meta["channel_order"]), (3, 48000, ["L", "R"]))

    def test_mp3_with_extra_suffix_from_decoder(self):
        source = self.write("renamed.mp3.mpeg", np.full(4800, 0.1, dtype=np.float32),
                            format="MP3", subtype="MPEG_LAYER_III")
        destination = self.root / "decoded.wav"
        info = ingest(source, destination)
        self.assertEqual(info["codec"], "mp3")
        self.assertIsNone(info["source_bit_depth"])
        self.assertGreater(info["sample_count"], 0)

    def test_lossless_pcm_containers(self):
        data = np.arange(-2048, 2048, 4, dtype=np.float32) / 32768
        for container, ext in [("WAV", "wav"), ("AIFF", "aiff"), ("FLAC", "flac")]:
            with self.subTest(container=container):
                source = self.write(f"in.{ext}", data, format=container, subtype="PCM_16")
                target = self.root / f"out-{ext}.wav"
                info = ingest(source, target)
                np.testing.assert_array_equal(self.read(target)[:, 0], data)
                self.assertEqual(info["source_bit_depth"], 16)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe non installati")
    def test_aac_ffmpeg_and_timing(self):
        frames = 48000
        t = np.arange(frames) / 48000
        source = self.write("original.wav", np.column_stack((0.1 * np.sin(2 * np.pi * 440 * t), np.zeros(frames))))
        encoded = self.root / "encoded.m4a"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-c:a", "aac", str(encoded)], check=True)
        destination = self.root / "decoded.wav"
        result = ingest(encoded, destination)
        self.assertEqual(result["codec"], "aac")
        self.assertEqual(result["channels"], 2)
        self.assertIsNone(result["source_bit_depth"])
        self.assertAlmostEqual(result["sample_count"], frames, delta=1024)
        self.assertGreater(float(np.linalg.norm(self.read(destination)[:, 0])), 1.0)

    def test_multichannel_rejected_without_downmix(self):
        source = self.write("multi.wav", np.zeros((64, 4)))
        with self.assertRaisesRegex(ValueError, "più di due canali"):
            ingest(source, self.root / "mono.wav")
        self.assertFalse((self.root / "mono.wav").exists())

    def test_resampling_is_phase_aligned_through_block_boundaries(self):
        rng = np.random.default_rng(9)
        count = BLOCK * 3 + 331
        data = rng.standard_normal((count, 2)).astype(np.float32) * 0.05
        data[BLOCK // 147 * 147 - 2:BLOCK // 147 * 147 + 2, 1] += 0.4
        source = self.write("source.wav", data, rate=44100)
        target = self.root / "48khz.wav"
        info = ingest(source, target, 48000)
        expected = resample_poly(data, 160, 147, axis=0)
        self.assertEqual(info["sample_count"], len(expected))
        np.testing.assert_allclose(self.read(target), expected, atol=3e-7, rtol=0)

    def test_waveform_tile_trim_and_spectrogram(self):
        frames = 48000
        data = 0.2 * np.sin(2 * np.pi * 1500 * np.arange(frames) / frames)
        data[12340] = -0.55
        source = self.write("tone.wav", data)
        self.assertAlmostEqual(max(waveform(source, 20, start_sample=12000, end_sample=13000)), 0.55, places=6)
        tile = spectrogram(source, start_sample=6000, end_sample=9000, columns=12, fft_size=512)
        peak = int(np.argmax(tile["columns"][6]))
        self.assertAlmostEqual(peak * tile["frequency_bin_hz"], 1500, places=5)
        target = self.root / "trimmed.wav"
        self.assertEqual(trim_audio(source, target, 12000, 13000)["sample_count"], 1000)
        np.testing.assert_array_equal(self.read(target), self.read(source)[12000:13000])

    def test_analyze_exposes_heuristics_and_profile_thresholds(self):
        frames = 96000
        t = np.arange(frames) / 48000
        signal = np.column_stack([0.02 + 0.10 * np.sin(2 * np.pi * 50 * t)] * 2).astype(np.float32)
        signal[12500] = [0.8, 0.7]
        signal[19900:20140] = 0.0
        signal[48000:48003] = 0.985
        signal[82301] = 1.08
        source = self.write("defects.wav", signal)
        report = analyze(source, "dialogue", depth="deep")
        self.assertTrue({"impulse", "possible_microgap", "possible_hum", "dc_offset", "possible_flat_top"}
                        .issubset({item["type"] for item in report["events"]}))
        self.assertGreater(report["metrics"]["samples_over_full_scale"], 0)
        self.assertAlmostEqual(report["metrics"]["stereo_correlation"], 1, delta=0.01)
        self.assertTrue(all(event["confidence_kind"] == "heuristic_score" for event in report["events"]))
        music = analyze(source, "music")
        self.assertNotEqual(music["settings"]["profile"], report["settings"]["profile"])
        self.assertNotEqual(music["settings"]["window_seconds"], report["settings"]["window_seconds"])

    def test_nonfinite_rejected_at_import_and_marked_on_analysis(self):
        source = self.write("unsafe.wav", np.array([0.02, np.nan, np.inf], dtype=np.float32))
        target = self.root / "decode.wav"
        with self.assertRaisesRegex(ValueError, "NaN"):
            ingest(source, target)
        self.assertFalse(target.exists())
        diagnostics = analyze(source, "original")
        self.assertEqual(diagnostics["metrics"]["non_finite_values"], 2)
        self.assertEqual(diagnostics["events"][0]["type"], "invalid_samples")

    def test_silence_has_null_undefined_metrics(self):
        source = self.write("silent.wav", np.zeros((4800, 2), dtype=np.float32))
        result = analyze(source, "original")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["metrics"]["sample_peak"], 0.0)
        for key in ("sample_peak_dbfs", "crest_factor_db", "stereo_correlation"):
            self.assertIsNone(result["metrics"][key])
        self.assertIsNone(result["metrics"]["loudness"]["integrated_lufs"])

    def test_microgap_edits_only_region_and_reports_origin(self):
        data = np.repeat(np.linspace(-0.1, 0.1, BLOCK * 2 + 500, dtype=np.float32)[:, None], 2, axis=1)
        start, end = BLOCK - 7, BLOCK + 100
        corrupted = data.copy()
        corrupted[start:end] = 0
        source = self.write("gap.wav", corrupted)
        candidate = self.root / "candidate.wav"
        metadata = restore(source, candidate, [{"type": "microgap", "start_sample": start, "end_sample": end}])
        actual = self.read(candidate)
        np.testing.assert_array_equal(actual[:start], corrupted[:start])
        np.testing.assert_array_equal(actual[end:], corrupted[end:])
        np.testing.assert_allclose(actual[start:end], data[start:end], atol=1e-8, rtol=0)
        self.assertEqual(metadata["reconstructed_regions"], [
            {"start_sample": start, "end_sample": end, "algorithm": "linear_interpolation"},
        ])
        difference = self.root / "delta.wav"
        difference_audio(source, candidate, difference)
        np.testing.assert_array_equal(self.read(difference), actual - corrupted)

    def test_dehum_and_declick_reduce_fixture_defects(self):
        frames = 96000
        t = np.arange(frames) / 48000
        data = (0.025 * np.sin(2 * np.pi * 50 * t) + 0.06 * np.sin(2 * np.pi * 750 * t)).astype(np.float32)
        data[10001] += 0.8
        target = self.root / "restored.wav"
        source = self.write("hum-and-click.wav", data)
        restored = restore(source, target, [
            {"type": "declick", "start_sample": 10001, "end_sample": 10002, "params": {"threshold": 0.07}},
            {"type": "dehum", "start_sample": 0, "end_sample": frames, "params": {"frequency_hz": 50, "q": 24}},
        ])
        filtered = self.read(target)[:, 0]
        self.assertLess(abs(filtered[10001]), 0.09)
        for frequency, condition in [(50, 0.12), (750, 0.99)]:
            phase = np.exp(-2j * np.pi * frequency * t[-48000:])
            before = abs(np.dot(phase, data[-48000:]))
            after = abs(np.dot(phase, filtered[-48000:]))
            if frequency == 50:
                self.assertLess(after / before, condition)
            else:
                self.assertAlmostEqual(after / before, condition, delta=0.02)
        self.assertEqual(restored["sample_count"], frames)

    def test_presets_avoid_unconfirmed_musical_hum_and_gate_microgap(self):
        events = [
            {"status": "unreviewed", "proposed_operation": {"type": "dehum", "start_sample": 40, "end_sample": 48000,
                                                            "params": {"frequency_hz": 50}}},
            {"status": "confirmed", "proposed_operation": {"type": "microgap", "start_sample": 102, "end_sample": 300,
                                                           "params": {"max_duration_ms": 15}}},
        ]
        self.assertEqual(propose_operations(events, "basic", "music", end_sample=48000), [])
        self.assertEqual([row["type"] for row in propose_operations(events, "medium", "music", end_sample=48000)], ["peq"])
        self.assertEqual([row["type"] for row in propose_operations(events, "high", "music", end_sample=48000)], ["microgap"])

    def test_mix_sum_residual_selection_and_no_normalization(self):
        rng = np.random.default_rng(91)
        arrays = {stem: rng.uniform(-0.15, 0.15, (BLOCK + 333, 2)).astype(np.float32)
                  for stem in ("dialogue", "music", "effects", "residual")}
        inputs = {stem: self.write(f"{stem}.wav", data) for stem, data in arrays.items()}
        output = self.root / "mix.wav"
        info = render_mix(inputs, output, {"tracks": {}, "master": {"eq": None}})
        expected = np.add.reduce([samples.astype(np.float64) for name, samples in arrays.items() if name != "residual"])
        np.testing.assert_array_equal(self.read(output), expected.astype(np.float32))
        self.assertFalse(info["residual_included"])
        self.assertFalse(info["tracks"]["residual"]["included"])
        second = self.root / "solo.wav"
        tracks = {"residual": {"mute": False, "solo": True, "automation": None}}
        metadata = render_mix(inputs, second, {"tracks": tracks})
        np.testing.assert_array_equal(self.read(second), arrays["residual"])
        self.assertTrue(metadata["residual_included"])

    def test_mixer_automation_and_mono_panning(self):
        data = np.full(4800, 0.2, dtype=np.float32)
        source = self.write("mono.wav", data)
        out = self.root / "pan.wav"
        settings = {
            "gain_db": [{"sample": 0, "value": 0}, {"sample": 2500, "value": -20}],
            "pan": [{"sample": 0, "value": -1}, {"sample": 2500, "value": 1}],
            "mute": [{"sample": 0, "value": False}, {"sample": 3000, "value": True}],
        }
        info = render_mix({"music": source}, out, {"tracks": {"music": {"automation": settings}}})
        result = self.read(out)
        self.assertEqual(info["channels"], 2)
        np.testing.assert_allclose(result[0], [0.2, 0.0], atol=1e-7)
        np.testing.assert_allclose(result[2500], [0.0, 0.02], atol=1e-7)
        self.assertAlmostEqual(float(result[3120, 1]), 0.01, places=6)
        np.testing.assert_array_equal(result[3240:], 0)

    def test_compressor_and_eq_are_bypassable(self):
        rate = 48000
        data = 0.4 * np.sin(2 * np.pi * 750 * np.arange(BLOCK * 2) / rate)
        source = self.write("loud.wav", data)
        config = {"compressor": {"threshold_db": -24, "ratio": 4, "attack_ms": 2, "release_ms": 200},
                  "eq": [{"frequency_hz": 750, "gain_db": 2, "q": 1}]}
        effect = self.root / "processed.wav"
        result = render_mix({"music": source}, effect, {"tracks": {"music": config}})
        self.assertGreater(result["tracks"]["music"]["gain_reduction_db"], 8)
        self.assertLess(float(np.max(np.abs(self.read(effect)[BLOCK:]))), 0.2)
        bypassed = self.root / "bypassed.wav"
        render_mix({"music": source}, bypassed, {"tracks": {"music": {**config, "bypass": True}}})
        np.testing.assert_array_equal(self.read(bypassed), self.read(source))

    def test_export_integer_refuses_clipping_and_measures_after_conversion(self):
        loud = self.write("float.wav", np.array([0.2, -1.01], dtype=np.float32))
        destination = self.root / "export.wav"
        with self.assertRaisesRegex(ValueError, "saturerebbe"):
            export_audio(loud, destination, format="wav_pcm24")
        self.assertFalse(destination.exists())
        meta = export_audio(loud, destination, format="wav_float")
        self.assertGreater(meta["sample_peak_dbfs"], 0)
        self.assertTrue(meta["warnings"])
        moderate = self.write("moderate.wav", np.array([0.13, -0.17, -1.0], dtype=np.float32))
        flac = self.root / "export.flac"
        measured = export_audio(moderate, flac, format="flac")
        self.assertEqual(sf.info(flac).subtype, "PCM_24")
        self.assertEqual(measured["sample_count"], 3)
        self.assertEqual(measured["sample_peak"], 1.0)
        self.assertIn("true_peak_dbtp", measured)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg non installato")
    def test_loudness_and_inter_sample_peak_reference_tone(self):
        rate = 48000
        time = np.arange(rate * 5) / rate
        tone = 0.1 * np.sin(2 * np.pi * 1000 * time)
        source = self.write("reference.wav", tone)
        measured = export_audio(source, self.root / "measured.wav")
        self.assertAlmostEqual(measured["loudness"]["integrated_lufs"], -23.0, delta=0.2)
        self.assertAlmostEqual(measured["loudness"]["momentary_lufs"], -23.0, delta=0.2)
        self.assertAlmostEqual(measured["loudness"]["short_term_lufs"], -23.0, delta=0.2)
        self.assertAlmostEqual(measured["true_peak_dbtp"], -20.0, delta=0.12)
        inter = 0.75 * np.sin(2 * np.pi * 12000 * time + np.pi / 4)
        high = self.write("intersection.wav", inter)
        measured = render_mix({"original": high}, self.root / "true-peak.wav", {"master": {"ceiling_dbtp": -3}})
        self.assertGreater(measured["true_peak_dbtp"], measured["sample_peak_dbfs"] + 2.5)
        self.assertTrue(measured["ceiling_exceeded"])

    def test_cancellation_does_not_publish_partial_assets(self):
        source = self.write("long.wav", np.full(BLOCK * 2, 0.03))
        target = self.root / "not-produced.wav"
        progress = []
        with self.assertRaises(InterruptedError):
            restore(source, target, [{"type": "dc_remove", "wet": 0.5}],
                    progress=lambda done, total: progress.append((done, total)), cancelled=lambda: bool(progress))
        self.assertEqual(len(progress), 1)
        self.assertFalse(target.exists())
        self.assertEqual(sorted(item.name for item in self.root.iterdir()), ["long.wav"])


if __name__ == "__main__":
    unittest.main()
