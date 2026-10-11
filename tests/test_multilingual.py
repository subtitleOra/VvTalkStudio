import copy
import hashlib
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from engine import analyze
from languages import (apply_unit_overrides, english_syllables, japanese_moras,
                       normalize_language, normalize_pronunciation_override, rebuild_note_metadata, text_units)
from workbench import build_document, flatten_document


class MultilingualTests(unittest.TestCase):
    def test_japanese_dictionary_moras_and_original_offsets(self):
        self.assertEqual(japanese_moras("キャーットパン"), ["きゃ", "ー", "っ", "と", "ぱ", "ん"])
        units = text_units("今日は、一緒に帰りましょう。", "ja")
        self.assertEqual(len(units), 13)
        self.assertEqual([u["lyric"] for u in units[:3]], ["きょ", "ー", "わ"])
        self.assertEqual(units[1]["reading"], "お")
        self.assertEqual(units[0]["source_text"], "今日")
        self.assertEqual(units[0]["word_accent"], 1)
        self.assertEqual([u["accent"] for u in units[:2]], [1, 0])
        self.assertEqual((units[0]["text_position"], units[0]["text_end"]), (0, 2))
        self.assertEqual(units[2]["following"], "、")
        self.assertEqual(len(text_units("時々。", "ja")), 4)

    def test_geminate_is_unvoiced_and_long_nasal_keep_their_moras(self):
        result = analyze({"text": "きゃーっと、パン。", "language": "ja", "smoothing_ms": 0})
        self.assertEqual([n["mora_kind"] for n in result["notes"]],
                         ["regular", "long", "geminate", "regular", "regular", "nasal"])
        geminate = result["notes"][2]
        closure = [p["pitch"] for p in result["curve"] if geminate["start"] + .01 < p["time"] < geminate["end"] - .01]
        self.assertTrue(closure)
        self.assertTrue(all(value is None for value in closure))
        self.assertTrue(all(n["tone"] == 0 and n["language"] == "ja" for n in result["notes"]))
        self.assertEqual(result["stats"]["pitch_method"], "japanese_dictionary_accent")

    def test_whole_word_reading_can_change_mora_count_and_survives_save(self):
        original = build_document({"text": "今日は。", "language": "ja"})
        edited = build_document({"text": "今日は。", "language": "ja", "word_readings": {"0": "コンニチ"}})
        self.assertEqual(original["character_count"], 3)
        self.assertEqual(edited["character_count"], 5)
        self.assertEqual(edited["sections"][0]["word_readings"], {"0": "コンニチ"})
        self.assertEqual(build_document(json.loads(json.dumps(edited))), edited)
        result = flatten_document(edited)
        self.assertEqual(result["word_readings"], {"0": "コンニチ"})
        self.assertEqual(len(rebuild_note_metadata(result)), 5)
        with self.assertRaisesRegex(ValueError, "词语起点"):
            text_units("今日は。", "ja", {"1": "きょう"})

    def test_japanese_reading_accent_duration_override_and_reset(self):
        document = build_document({"text": "今日は。", "language": "ja"})
        row = document["sections"][0]["characters"][0]
        row.update(pronunciation_override="キュ", accent_override=0,
                   duration_override_ms=480, pause_override_ms=80)
        rebuilt = build_document(json.loads(json.dumps(document)))
        row = rebuilt["sections"][0]["characters"][0]
        self.assertEqual((row["reading"], row["auto_reading"], row["accent"], row["auto_accent"]), ("きゅ", "きょ", 0, 1))
        self.assertEqual((row["duration_ms"], row["pause_after_ms"]), (480, 80))
        self.assertEqual(build_document(rebuilt), rebuilt)
        row.update(pronunciation_override=None, accent_override=None)
        reset = build_document(rebuilt)["sections"][0]["characters"][0]
        self.assertEqual((reset["reading"], reset["accent"], reset["duration_ms"]), ("きょ", 1, 480))

    def test_english_dictionary_preserves_case_apostrophe_and_stress_groups(self):
        units = text_units("Let's go HOME together today?", "en")
        self.assertEqual([u["lyric"] for u in units], ["Let's", "go", "HOME", "together", "today"])
        self.assertEqual(units[3]["stress"], [0, 1, 0])
        self.assertEqual(units[4]["stress"], [0, 1])
        self.assertEqual(units[3]["syllable_count"], 3)
        self.assertEqual([p for s in units[3]["syllables"] for p in s["phonemes"]], units[3]["phonemes"])
        self.assertEqual(units[-1]["following"], "?")
        self.assertEqual(text_units("LET’S.", "en")[0]["phonemes"], units[0]["phonemes"])
        self.assertEqual(english_syllables(["HH", "AH0", "L", "OW1"]),
                         [{"phonemes": ["HH", "AH0"], "stress": 0, "weight": .9},
                          {"phonemes": ["L", "OW1"], "stress": 1, "weight": 1.25}])

    def test_english_pronunciation_and_stress_recompute_effective_metadata(self):
        document = build_document({"text": "Hello home.", "language": "en"})
        row = document["sections"][0]["characters"][0]
        row.update(pronunciation_override="hh ah0 l ow1", stress_override=[1, 0], duration_override_ms=640)
        rebuilt = build_document(document)
        note = rebuilt["sections"][0]["result"]["notes"][0]
        self.assertEqual(note["reading"], "HH AH1 L OW0")
        self.assertEqual(note["phonemes"], ["HH", "AH1", "L", "OW0"])
        self.assertEqual(note["stress"], [1, 0])
        self.assertEqual([s["stress"] for s in note["syllables"]], [1, 0])
        self.assertEqual(note["pronunciation_override"], "HH AH0 L OW1")
        self.assertAlmostEqual(note["end"] - note["start"], .64)
        self.assertEqual(build_document(json.loads(json.dumps(rebuilt))), rebuilt)
        row = rebuilt["sections"][0]["characters"][0]
        row.update(stress_override=None, pronunciation_override=None)
        reset = build_document(rebuilt)["sections"][0]["characters"][0]
        self.assertEqual(reset["stress"], [0, 1])
        self.assertEqual(reset["reading_source"], "cmudict")

    def test_raw_result_metadata_rebuild_does_not_mutate_curve_or_geometry(self):
        result = analyze({"text": "Hello home.", "language": "en"})
        result["notes"][0].update(pronunciation_override="HH OW1 M", stress_override=[2])
        before = copy.deepcopy(result)
        metadata = rebuild_note_metadata(result)
        self.assertEqual(result, before)
        self.assertEqual(metadata[0]["syllable_count"], 1)
        self.assertEqual(metadata[0]["reading"], "HH OW2 M")
        self.assertFalse(any(key in metadata[0] for key in ("start", "end", "key", "curve")))
        self.assertEqual(metadata[0]["auto_reading"], "HH AH0 L OW1")

    def test_unknown_english_word_has_honest_warning_until_manually_read(self):
        result = analyze({"text": "Xyzzyplugh.", "language": "en"})
        self.assertEqual(result["notes"][0]["reading_source"], "unknown")
        self.assertEqual(result["notes"][0]["phonemes"], [])
        self.assertTrue(any("未收录" in warning for warning in result["warnings"]))
        supplied = [{"pronunciation_override": "Z IH1 Z IY0 P L AH1 G"}]
        corrected = analyze({"text": "Xyzzyplugh.", "language": "en", "unit_overrides": supplied})
        self.assertEqual(corrected["notes"][0]["reading_source"], "manual")
        self.assertEqual(corrected["notes"][0]["syllable_count"], 3)
        self.assertFalse(any("未收录" in warning for warning in corrected["warnings"]))

    def test_sentence_question_changes_final_pitch_without_mandarin_tones(self):
        for language, text in (("en", "Coming home"), ("ja", "はな")):
            statement = analyze({"text": text + ".", "language": language, "smoothing_ms": 0})
            question = analyze({"text": text + "?", "language": language, "smoothing_ms": 0})
            last = statement["notes"][-1]
            begin = last["start"] + .8 * (last["end"] - last["start"])
            pitches = lambda r: [p["pitch"] for p in r["curve"] if begin < p["time"] < last["end"] and p["pitch"] is not None]
            self.assertGreater(np.mean(pitches(question)) - np.mean(pitches(statement)), 1.5)
            self.assertTrue(all(n["tone"] == 0 for n in question["notes"]))

    def test_reference_uses_same_units_and_overrides_do_not_change_f0(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "speech.wav"
            rate = 16000
            times = np.arange(round(1.4 * rate)) / rate
            samples = (.3 * np.sin(2 * np.pi * 220 * times) * 32767).astype("<i2")
            with wave.open(str(audio), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(rate)
                stream.writeframes(samples.tobytes())
            for language, text, override in (("ja", "はな。", {"pronunciation_override": "ハ", "accent_override": 1}),
                                              ("en", "Hello home.", {"pronunciation_override": "HH AH0 L OW1", "stress_override": [1, 0]})):
                units = text_units(text, language)
                payload = {"mode": "reference", "language": language, "text": text, "audio_path": str(audio),
                           "smoothing_ms": 0, "alignment": [{"lyric": u["lyric"], "start": i * .7, "end": (i + 1) * .7}
                                                              for i, u in enumerate(units)]}
                original = analyze(payload)
                overridden = analyze({**payload, "unit_overrides": [override, {}]})
                self.assertEqual(original["curve"], overridden["curve"])
                self.assertEqual(overridden["language"], language)
                self.assertAlmostEqual(overridden["stats"]["pitch_median"], 57, delta=.03)
                self.assertEqual([n["lyric"] for n in overridden["notes"]], [u["lyric"] for u in units])

    def test_split_sections_preserve_all_text_and_global_note_offsets(self):
        text = "Hello world.\n\nLet's go home? " + "together " * 130
        document = build_document({"text": text, "language": "en"})
        self.assertEqual("".join(s["text"] for s in document["sections"]), text)
        self.assertGreater(len(document["sections"]), 3)
        self.assertTrue(all(len(s["characters"]) <= 120 for s in document["sections"]))
        result = flatten_document(document)
        self.assertEqual([n["text_position"] for n in result["notes"]], [u["text_position"] for u in text_units(text, "en")])
        self.assertEqual(build_document(json.loads(json.dumps(document))), document)

    def test_language_and_override_validation(self):
        self.assertEqual(normalize_language(), "zh")
        for invalid in ("de", "JA", "", 1, False):
            with self.assertRaises(ValueError):
                normalize_language(invalid)
        for reading in ("hello", "HH AH L OW1", "HH AH3", "HH1 AH0", "", "ZZ AH0"):
            with self.assertRaises(ValueError):
                normalize_pronunciation_override(reading, "en")
        for reading in ("きょう", "東京", "kyo", "ゃ"):
            with self.assertRaises(ValueError):
                normalize_pronunciation_override(reading, "ja")
        for language, text, override in (("en", "Hello", {"stress_override": [1]}),
                                         ("ja", "はな", {"accent_override": 1.0}),
                                         ("zh", "你", {"pronunciation_override": "ni3"})):
            units = text_units(text, language)
            with self.assertRaises(ValueError):
                apply_unit_overrides(units, [override] + [{} for _ in units[1:]])
        document = build_document({"text": "Hello.", "language": "en"})
        document["sections"][0]["characters"][0]["language"] = "ja"
        with self.assertRaisesRegex(ValueError, "语言"):
            build_document(document)

    def test_legacy_chinese_pitch_geometry_are_unchanged(self):
        payload = {"text": "今天，我们一起回家吧。明天再见。"}
        implicit = flatten_document(build_document(payload))
        explicit = flatten_document(build_document({**payload, "language": "zh"}))
        self.assertEqual(implicit, explicit)
        baseline = {"notes": [{key: n[key] for key in ("lyric", "pinyin", "tone", "start", "end", "key")}
                               for n in implicit["notes"]], "curve": implicit["curve"], "duration": implicit["duration"]}
        digest = hashlib.sha256(json.dumps(baseline, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(digest, "74536d65247eb4634796ff57f24092a0a3c44a06922bb84e22394753c181bd2d")
        legacy = build_document(payload)
        del legacy["language"]
        for section in legacy["sections"]:
            del section["language"]
            for row in section["characters"]:
                del row["language"]
        self.assertEqual(flatten_document(legacy), implicit)


if __name__ == "__main__":
    unittest.main()
