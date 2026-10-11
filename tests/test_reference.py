import base64
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
from praatio import textgrid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import alignment
import server
from engine import analyze


def recording(path, silent=False):
    rate = 16000
    first = np.arange(round(.8 * rate)) / rate
    last = np.arange(round(.8 * rate)) / rate
    signal = np.zeros(round(1.9 * rate)) if silent else np.concatenate([
        .3 * np.sin(2 * np.pi * 220 * first), np.zeros(round(.3 * rate)),
        .3 * np.sin(2 * np.pi * 330 * last)])
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes((signal * 32767).astype("<i2").tobytes())
    return path


def grid_file(path, entries=None):
    grid = textgrid.Textgrid()
    grid.addTier(textgrid.IntervalTier("words", entries or [(0, .8, "ni3"), (1.1, 1.9, "hao3")], 0, 1.9))
    grid.save(str(path), format="long_textgrid", includeBlankSpaces=True)


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.audio = recording(self.folder / "recording.wav")
        self.intervals = [{"lyric": "你", "start": 0, "end": .8},
                          {"lyric": "好", "start": 1.1, "end": 1.9}]

    def tearDown(self):
        self.temporary.cleanup()

    def test_known_220_hz_pitch_change_and_unvoiced_silence(self):
        result = analyze({"mode": "reference", "text": "你好。", "audio_path": str(self.audio),
                          "alignment": self.intervals, "fmin": 75, "fmax": 600,
                          "pitch_mode": "absolute", "smoothing_ms": 0})
        first = [p["pitch"] for p in result["curve"] if .15 < p["time"] < .65 and p["pitch"] is not None]
        last = [p["pitch"] for p in result["curve"] if 1.25 < p["time"] < 1.75 and p["pitch"] is not None]
        self.assertAlmostEqual(float(np.median(first)), 57, delta=.03)
        self.assertAlmostEqual(float(np.median(last)), 69 + 12 * math.log2(330 / 440), delta=.03)
        self.assertTrue(all(p["pitch"] is None for p in result["curve"] if .9 < p["time"] < 1.0))
        self.assertEqual(result["notes"][1]["start"], 1.1)
        self.assertEqual(result["alignment_source"], "manual")

    def test_silent_recording_fails_at_export_validation(self):
        silent = recording(self.folder / "silent.wav", silent=True)
        result = analyze({"mode": "reference", "text": "你好", "audio_path": str(silent),
                          "alignment": self.intervals})
        with self.assertRaisesRegex(ValueError, "没有可导出"):
            server.validate_result(result)

    def test_pinyin_each_character_and_dictionary_validation(self):
        dictionary = self.folder / "dictionary.dict"
        dictionary.write_text("ni3 1.0 n i\nhao3 1.0 h ao\n", encoding="utf-8")
        chars, tokens = alignment.pinyin_tokens("你，好！", dictionary)
        self.assertEqual(chars, ["你", "好"])
        self.assertEqual(tokens, ["ni3", "hao3"])
        with self.assertRaisesRegex(ValueError, "不含这些读音"):
            alignment.pinyin_tokens("你好呀", dictionary)

    def test_word_tier_checks_labels_count_and_order(self):
        path = self.folder / "words.TextGrid"
        grid_file(path)
        self.assertEqual(alignment.read_word_intervals(path, ["你", "好"], ["ni3", "hao3"], 1.9), self.intervals)
        with self.assertRaisesRegex(ValueError, "台词有"):
            alignment.read_word_intervals(path, ["你"], ["ni3"], 1.9)
        with self.assertRaisesRegex(ValueError, "不一致"):
            alignment.read_word_intervals(path, ["你", "好"], ["ni2", "hao3"], 1.9)

    def test_mfa_isolated_child_environment_and_does_not_modify_original(self):
        dictionary = self.folder / "dictionary.dict"
        dictionary.write_text("ni3 1.0 n i\nhao3 1.0 h ao\n", encoding="utf-8")
        configuration = {"available": True, "environment": str(self.folder / "external"),
                         "dictionary": str(dictionary), "model": str(self.folder / "external/model.zip"),
                         "python": str(self.folder / "external/python.exe"), "script": str(self.folder / "external/mfa-script.py")}
        original_audio = self.audio.read_bytes()
        original_environment = dict(os.environ)
        def process(arguments, **kwargs):
            self.assertEqual(arguments[2], "align")
            self.assertEqual(arguments[-3:], ["--disable_mp", "-j", "1"])
            self.assertTrue(Path(kwargs["env"]["MFA_ROOT_DIR"]).is_relative_to(self.folder / "work"))
            self.assertEqual((Path(arguments[3]) / "speech.lab").read_text(encoding="utf-8"), "ni3 hao3")
            grid_file(Path(arguments[6]) / "speech.TextGrid")
            return subprocess.CompletedProcess(arguments, 0)
        with patch("alignment.detect_alignment", return_value=configuration), patch("alignment.subprocess.run", side_effect=process):
            result = alignment.align_audio(self.audio, "你好", self.folder / "work")
        self.assertEqual(result, self.intervals)
        self.assertEqual(self.audio.read_bytes(), original_audio)
        self.assertEqual(dict(os.environ), original_environment)

    def test_mfa_failure_never_returns_equal_timing(self):
        dictionary = self.folder / "dictionary.dict"
        dictionary.write_text("ni3 1.0 n i\nhao3 1.0 h ao\n", encoding="utf-8")
        configuration = {"available": True, "environment": str(self.folder), "dictionary": str(dictionary),
                         "model": "unused.zip", "python": "unused.exe", "script": "unused.py"}
        with patch("alignment.detect_alignment", return_value=configuration), patch("alignment.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ValueError, "未退回均分"):
                alignment.align_audio(self.audio, "你好", self.folder / "work")

    def test_upload_and_auto_alignment_reference_pipeline(self):
        with patch.multiple(server, DATA=self.folder, OUTPUTS=self.folder / "outputs", UPLOADS=self.folder / "uploads"):
            uploaded = server.upload({"name": "recording.wav", "kind": "audio", "data": base64.b64encode(self.audio.read_bytes()).decode("ascii")})
            with patch("server.align_audio", return_value=self.intervals, create=True) as align:
                response = server.reference({"audio_id": uploaded["id"], "text": "你好。", "alignment_mode": "auto", "smoothing_ms": 0})
            align.assert_called_once()
            self.assertEqual(response["result"]["alignment_source"], "mfa-local")
            self.assertEqual(response["result"]["notes"][1]["start"], 1.1)
            self.assertIsNone(response["document"])
            self.assertEqual(response["result"]["stats"]["pitch_method"], "praat_autocorrelation")

    def test_auto_alignment_failure_is_exposed_in_reference_pipeline(self):
        with patch.multiple(server, DATA=self.folder, OUTPUTS=self.folder / "outputs", UPLOADS=self.folder / "uploads"):
            uploaded = server.upload({"name": "recording.wav", "kind": "audio", "data": base64.b64encode(self.audio.read_bytes()).decode("ascii")})
            with patch("server.align_audio", side_effect=ValueError("MFA unavailable"), create=True):
                with self.assertRaisesRegex(ValueError, "MFA unavailable"):
                    server.reference({"audio_id": uploaded["id"], "text": "你好", "alignment_mode": "auto"})

    @unittest.skipUnless(os.environ.get("VVTALK_RUN_MFA_TEST") == "1", "Set VVTALK_RUN_MFA_TEST=1 for the existing local MFA installation")
    def test_real_local_mfa_with_existing_recording(self):
        reference = os.environ.get("VVTALK_TEST_REFERENCE_WAV")
        self.assertTrue(reference, "Set VVTALK_TEST_REFERENCE_WAV to your recording of 今天，我们一起回家吧。")
        source = Path(reference).expanduser().resolve()
        self.assertTrue(source.is_file(), "Required local reference recording is missing")
        before = source.read_bytes()
        words = alignment.align_audio(source, "今天，我们一起回家吧。", self.folder / "live")
        self.assertEqual(len(words), 9)
        self.assertEqual("".join(item["lyric"] for item in words), "今天我们一起回家吧")
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue(any(right["start"] - left["end"] > .05 for left, right in zip(words, words[1:])))


if __name__ == "__main__":
    unittest.main()
