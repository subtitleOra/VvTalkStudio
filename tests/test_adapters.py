import copy
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
import adapters
from native_acep import read_acep
from import_vsqx import read_vsqx


def example():
    return {"bpm": 120, "duration": 1.25,
            "notes": [{"start": 0, "end": 0.5, "key": 60, "lyric": "重", "pinyin_override": "chong2"},
                      {"start": 0.75, "end": 1.25, "key": 62, "lyric": "来"}],
            "curve": [{"time": 0, "pitch": 61}, {"time": 0.25, "pitch": 62},
                      {"time": 0.5, "pitch": None}, {"time": 0.75, "pitch": 61},
                      {"time": 1, "pitch": 62}, {"time": 1.25, "pitch": None}]}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_validation_rejects_bad_data_before_creating_artifact(self):
        variants = []
        for field, value in (("duration", math.nan), ("bpm", True)):
            data = example()
            data[field] = value
            variants.append(data)
        for field, value in (("end", 0), ("key", 60.5), ("lyric", ""), ("pinyin_override", "bad9")):
            data = example()
            data["notes"][0][field] = value
            variants.append(data)
        data = example()
        data["notes"][1]["start"] = .4
        variants.append(data)
        data = example()
        data["curve"][1]["time"] = -.1
        variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(ValueError):
                adapters.export_project(data, None, self.folder / "new", "synthv", ROOT / "templates/speech_template.acep")
        self.assertFalse((self.folder / "new").exists())

    def test_svp_native_absolute_controls_seconds_blicks_pronunciation_and_source_unchanged(self):
        source = example()
        snapshot = copy.deepcopy(source)
        path = adapters.write_svp(source, self.folder / "speech.svp")
        data = json.loads(path.read_text(encoding="utf-8"))
        group = data["tracks"][0]["mainGroup"]
        self.assertEqual(group["notes"][0]["duration"], adapters.BLICK_PER_QUARTER)
        self.assertEqual(group["notes"][1]["onset"], round(1.5 * adapters.BLICK_PER_QUARTER))
        self.assertEqual(group["notes"][0]["lyrics"], "chong")
        self.assertEqual(data["version"], 196)
        self.assertEqual(group["parameters"]["pitchDelta"]["points"], [])
        self.assertEqual(group["pitchControls"][0], {"pos": 0, "pitch": 61, "id": "0", "type": "curve",
                         "points": [0, 0, round(.5 * adapters.BLICK_PER_QUARTER), 1]})
        self.assertEqual(group["pitchControls"][1]["pos"], round(1.5 * adapters.BLICK_PER_QUARTER))
        self.assertEqual(group["pitchControls"][1]["pitch"], 61)
        self.assertEqual(group["notes"][0]["attributes"]["languageOverride"], "mandarin")
        self.assertEqual(group["notes"][0]["scriptData"]["vvtalkstudio.pinyinOverride"], "chong2")
        self.assertEqual(snapshot, source)

    def test_voiced_segments_preserve_silence_and_identical_time_marker(self):
        source = example()
        source["curve"].insert(3, {"time": .5, "pitch": 70})
        data = adapters.synthv_payload(source)
        self.assertEqual(len(data["segments"]), 2)
        self.assertEqual(data["segments"][0], [[0, 61], [.25, 62]])
        self.assertEqual(data["notes"][0]["sourceLyrics"], "重")
        self.assertEqual(data["notes"][0]["pinyinOverride"], "chong2")
        source["curve"] = [{"time": 0, "pitch": None}, {"time": 1.25, "pitch": None}]
        self.assertEqual(adapters.synthv_payload(source)["segments"], [])

    def read_xml(self, path):
        root = ET.parse(path).getroot()
        for item in root.iter():
            item.tag = item.tag.rsplit("}", 1)[-1]
        return root

    def test_vsqx_pit_pbs_units_and_pause_reset(self):
        root = self.read_xml(adapters.write_vsqx(example(), self.folder / "speech.vsqx"))
        self.assertEqual(root.findtext("masterTrack/resolution"), "480")
        self.assertEqual(root.findtext("masterTrack/preMeasure"), "0")
        self.assertEqual(root.findtext("masterTrack/tempo/v"), "12000")
        notes = root.findall("vsTrack/vsPart/note")
        self.assertEqual(notes[0].findtext("dur"), "480")
        self.assertEqual(notes[1].findtext("t"), "720")
        self.assertEqual(notes[0].findtext("y"), "chong")
        self.assertEqual(notes[0].find("p").get("lock"), "0")
        events = {(int(cc.findtext("t")), cc.find("v").get("id")): int(cc.findtext("v"))
                  for cc in root.findall("vsTrack/vsPart/cc")}
        self.assertEqual(events[(0, "S")], 2)
        self.assertEqual(events[(0, "P")], 4096)
        self.assertEqual(events[(480, "P")], 0)
        self.assertEqual(events[(720, "P")], -4096)
        self.assertEqual(events[(1200, "P")], 0)

    def test_note_boundary_adjusts_relative_pitch_even_between_samples(self):
        data = example()
        data["notes"][0].update(end=.3, pinyin_override=None)
        data["notes"][1].update(start=.3)
        data["curve"] = [{"time": 0, "pitch": 61}, {"time": .6, "pitch": 61},
                         {"time": 1.25, "pitch": None}]
        root = self.read_xml(adapters.write_vsqx(data, self.folder / "boundary.vsqx"))
        events = {(int(cc.findtext("t")), cc.find("v").get("id")): int(cc.findtext("v"))
                  for cc in root.findall("vsTrack/vsPart/cc")}
        self.assertEqual(events[(288, "P")], -4096)

    def test_note_start_keeps_same_tick_source_samples_from_three_actual_cases(self):
        cases = [
            ("一", 1.073710, 1.266910, [(1.072000, 62.015519), (1.074000, 62.428263), (1.076000, 62.824708)]),
            ("天", 2.773996, 2.983996, [(2.772293, 62.860551), (2.774293, 62.890253), (2.776293, 62.920812)]),
            ("再", 2.986080, 3.179280, [(2.984293, 64.366707), (2.986293, 64.404538), (2.988293, 64.439981)]),
        ]
        for lyric, start, end, points in cases:
            with self.subTest(lyric=lyric):
                data = {"bpm": 120, "duration": end, "notes": [{"lyric": lyric, "start": start, "end": end, "key": 61}],
                        "curve": [{"time": t, "pitch": p} for t, p in points]}
                root = self.read_xml(adapters.write_vsqx(data, self.folder / "collision.vsqx"))
                events = {(int(cc.findtext("t")), cc.find("v").get("id")): int(cc.findtext("v"))
                          for cc in root.findall("vsTrack/vsPart/cc")}
                pbs = events[(0, "S")]
                tick = round(start * 960)
                self.assertEqual(tick, round(points[1][0] * 960))
                decoded = 61 + events[(tick, "P")] * pbs / 8192
                self.assertAlmostEqual(decoded, points[1][1], delta=pbs / 8192 / 2 + 1e-8)

    def test_note_start_rebases_previous_note_sample_at_same_tick(self):
        data = {"bpm": 120, "duration": .8,
                "notes": [{"lyric": "你", "start": 0, "end": .3002, "key": 60},
                          {"lyric": "好", "start": .3002, "end": .8, "key": 64}],
                "curve": [{"time": 0, "pitch": 60}, {"time": .3001, "pitch": 62},
                          {"time": .6, "pitch": 64}, {"time": .8, "pitch": None}]}
        root = self.read_xml(adapters.write_vsqx(data, self.folder / "rebase.vsqx"))
        events = {(int(cc.findtext("t")), cc.find("v").get("id")): int(cc.findtext("v"))
                  for cc in root.findall("vsTrack/vsPart/cc")}
        pbs = events[(0, "S")]
        self.assertEqual(round(.3001 * 960), round(.3002 * 960))
        expected = 62 + 2 * (.3002 - .3001) / (.6 - .3001)
        decoded = 64 + events[(round(.3002 * 960), "P")] * pbs / 8192
        self.assertAlmostEqual(decoded, expected, delta=pbs / 8192 / 2 + 1e-8)

    def test_vsqx_quantization_and_pbs_overflow_fail_explicitly(self):
        data = example()
        data["notes"][0].update(start=.0003, end=.0004)
        data["notes"][1].update(start=.0004)
        with self.assertRaisesRegex(ValueError, "量化"):
            adapters.write_vsqx(data, self.folder / "short.vsqx")
        data = example()
        data["curve"][0]["pitch"] = 85
        with self.assertRaisesRegex(ValueError, "24 半音"):
            adapters.write_vsqx(data, self.folder / "range.vsqx")

    def test_export_ace_native_file_can_be_read_back(self):
        data = example()
        data["notes"][0]["pinyin_override"] = None
        exported = adapters.export_project(data, None, self.folder, "ace", ROOT / "templates/speech_template.acep")
        project = read_acep(Path(exported["files"][0]["path"]))
        patterns = [p for track in project["tracks"] for p in track.get("patterns", []) if p.get("notes")]
        self.assertEqual(len(patterns), 1)
        self.assertEqual(len(patterns[0]["notes"]), 2)
        self.assertEqual(patterns[0]["notes"][1]["pos"], 720)
        self.assertEqual(len(patterns[0]["parameters"]["pitchDelta"]), 2)

    def test_all_targets_long_document_preserve_section_offsets(self):
        from workbench import build_document, flatten_document
        document = build_document({"text": "你好。欢迎回来。"})
        result = flatten_document(document)
        exported = adapters.export_project(result, document, self.folder, "all", ROOT / "templates/speech_template.acep")
        self.assertEqual({file["format"] for file in exported["files"]},
                         {"acep", "svp", "vsqx"})
        self.assertTrue(all(Path(file["path"]).is_file() for file in exported["files"]))
        ace_path = next(file["path"] for file in exported["files"] if file["format"] == "acep")
        project = read_acep(Path(ace_path))
        patterns = [p for track in project["tracks"] for p in track.get("patterns", []) if p.get("notes")]
        self.assertEqual(len(patterns), 2)
        self.assertEqual(patterns[1]["pos"], round(document["sections"][1]["offset"] * 960))

    def test_installer_preserves_previous_script(self):
        previous = self.folder / "VvTalkStudio_Import.js"
        previous.write_text("previous-user-version", encoding="utf-8")
        installed = adapters.install_synthv_script(self.folder)
        self.assertEqual(Path(installed["backup"]).read_text(encoding="utf-8"), "previous-user-version")
        self.assertIn("getClientInfo", previous.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            adapters.install_synthv_script(self.folder / "absent")

    def language_example(self, language):
        data = example()
        data["language"] = language
        if language == "ja":
            data["notes"][0].update(lyric="こ", reading="こ", pinyin_override=None)
            data["notes"][1].update(lyric="ー", reading="お", pronunciation_override="ー", mora_kind="long")
        else:
            data["notes"][0].update(lyric="hello", phonemes=["HH", "AH0", "L", "OW1"],
                                    pronunciation_override="HH AH0 L OW1", pinyin_override=None)
            data["notes"][1].update(lyric="world", phonemes=["W", "ER1", "L", "D"])
        return data

    def test_language_defaults_and_invalid_mixed_language_are_checked(self):
        self.assertEqual(adapters.validate_result(example())["language"], "zh")
        for mutate in (lambda d: d.update(language="fr"),
                       lambda d: d["notes"][1].update(language="en"),
                       lambda d: d["notes"][0].update(pinyin_override="he1")):
            data = self.language_example("ja")
            mutate(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                adapters.validate_result(data)

    def test_japanese_and_english_svp_vsqx_and_import_metadata(self):
        for language, bank, host_language, lyric in [("ja", "0", "japanese", "こ"),
                                                    ("en", "1", "english", "hello")]:
            data = self.language_example(language)
            with self.subTest(language=language):
                svp = json.loads(adapters.write_svp(data, self.folder / "language.svp").read_text(encoding="utf-8"))
                self.assertEqual(svp["tracks"][0]["mainRef"]["database"]["languageOverride"], host_language)
                self.assertEqual(svp["tracks"][0]["mainGroup"]["notes"][0]["lyrics"], lyric)
                if language == "ja":
                    self.assertEqual(svp["tracks"][0]["mainGroup"]["notes"][1]["lyrics"], "お")
                path = adapters.write_vsqx(data, self.folder / "language.vsqx")
                xml = self.read_xml(path)
                self.assertEqual(xml.findtext("vVoiceTable/vVoice/bs"), bank)
                self.assertEqual(xml.findtext("vsTrack/vsPart/singer/bs"), bank)
                self.assertEqual(xml.findtext("vsTrack/vsPart/note/y"), lyric)
                imported = read_vsqx(path, language=language)
                self.assertEqual(imported["language"], language)
                self.assertTrue(all(n["language"] == language for n in imported["notes"]))
                self.assertEqual(imported["notes"][0]["lyric"], lyric)
                if language == "en":
                    self.assertEqual(imported["notes"][0]["phonemes"], ["HH", "AH0", "L", "OW1"])
                    with self.assertRaisesRegex(ValueError, "英语词数量"):
                        read_vsqx(path, text="hello", language="en")

    def test_offline_ace_language_voices_japanese_long_vowel_and_english_syllables(self):
        for language, language_code, voice_id, seed_code in [("ja", "JPN", 34, 30), ("en", "ENG", 56, 110)]:
            source = self.language_example(language)
            original = copy.deepcopy(source)
            with self.subTest(language=language), patch("pronunciation.ace_read", side_effect=AssertionError("Export called the live editor")):
                exported = adapters.export_project(source, None, self.folder / language, "ace", ROOT / "templates/speech_template.acep")
                project = read_acep(exported["files"][0]["path"])
            track = project["tracks"][0]
            self.assertEqual(track["language"], language_code)
            self.assertEqual(track["singers"][0]["singer"]["router"], 13)
            self.assertEqual(track["singers"][0]["singer"]["id"], voice_id)
            self.assertEqual(track["singers"][0]["singer"]["composition"][0]["code"], seed_code)
            notes = track["patterns"][0]["notes"]
            self.assertTrue(all(n["language"] == language_code for n in notes))
            if language == "ja":
                self.assertEqual([(n["lyric"], n["syllable"]) for n in notes], [("こ", "k o"), ("お", "o")])
            else:
                self.assertEqual([n["syllable"] for n in notes], ["hh ah", "l ow", "w er l d"])
                self.assertEqual([n["lyric"] for n in notes], ["hello", "hello", "world"])
                self.assertEqual(notes[0]["pos"], 0)
                self.assertEqual(notes[0]["pos"] + notes[0]["dur"], notes[1]["pos"])
                self.assertEqual(notes[1]["pos"] + notes[1]["dur"], 480)
                self.assertEqual(notes[2]["pos"], 720)
                self.assertEqual(notes[2]["pos"] + notes[2]["dur"], 1200)
                self.assertEqual(notes[1]["extraInfo"]["vvtalkStudio"]["sourceWord"], "hello")
            lanes = track["patterns"][0]["parameters"]["pitchDelta"]
            self.assertEqual([p["points"] for p in lanes], [[0, 61, 240, 62], [720, 61, 960, 62]])
            self.assertEqual(source, original)

    def test_english_stress_override_changes_syllable_duration_without_losing_word_geometry(self):
        data = self.language_example("en")
        data["notes"][0].update(phonemes=["HH", "AH1", "L", "OW0"], stress_override=[1, 0])
        exported = adapters.export_project(data, None, self.folder, "ace", ROOT / "templates/speech_template.acep")
        notes = read_acep(exported["files"][0]["path"])["tracks"][0]["patterns"][0]["notes"]
        self.assertGreater(notes[0]["dur"], notes[1]["dur"])
        self.assertEqual(notes[0]["dur"] + notes[1]["dur"], 480)

    def test_all_export_reports_unsupported_ace_reading_and_retains_other_targets(self):
        data = self.language_example("en")
        data["notes"][0].update(lyric="qzxqzx", phonemes=[], pronunciation_override=None)
        with self.assertRaisesRegex(ValueError, "没有可用读音"):
            adapters.export_project(data, None, self.folder / "ace-only", "ace", ROOT / "templates/speech_template.acep")
        exported = adapters.export_project(data, None, self.folder / "all", "all", ROOT / "templates/speech_template.acep")
        self.assertEqual({file["format"] for file in exported["files"]}, {"svp", "vsqx"})
        self.assertTrue(any("ACE Studio 未导出" in warning for warning in exported["warnings"]))

    def test_long_ace_rejects_section_language_mismatch(self):
        from native_acep import build_long_acep
        document = {"language": "en", "bpm": 120, "sections": [
            {"offset": 0, "duration": 1.25, "result": self.language_example("ja")}]}
        with self.assertRaisesRegex(ValueError, "各段落的语言"):
            build_long_acep(document, ROOT / "templates/speech_template.acep", self.folder / "mixed.acep")
        self.assertFalse((self.folder / "mixed.acep").exists())

    def test_export_rejects_document_and_result_language_mismatch_before_writing(self):
        with self.assertRaisesRegex(ValueError, "分析结果与长文工程的语言"):
            adapters.export_project(self.language_example("en"), {"language": "ja"},
                                    self.folder / "invalid", "all", ROOT / "templates/speech_template.acep")
        self.assertFalse((self.folder / "invalid").exists())

    def test_external_japanese_vsqx_long_vowel_normalizes_without_losing_source_label(self):
        data = self.language_example("ja")
        path = adapters.write_vsqx(data, self.folder / "external-long.vsqx")
        xml = self.read_xml(path)
        xml.findall("vsTrack/vsPart/note")[1].find("y").text = "ー"
        ET.ElementTree(xml).write(path, encoding="utf-8", xml_declaration=True)
        imported = read_vsqx(path, language="ja")
        self.assertEqual(imported["notes"][1]["lyric"], "お")
        self.assertEqual(imported["notes"][1]["source_lyric"], "ー")
        self.assertEqual(imported["notes"][1]["mora_kind"], "long")
        from languages import text_units
        self.assertEqual(len(text_units(imported["text"], "ja")), 2)
        xml.findall("vsTrack/vsPart/note")[0].find("y").text = "ー"
        ET.ElementTree(xml).write(path, encoding="utf-8", xml_declaration=True)
        with self.assertRaisesRegex(ValueError, "日语独立长音"):
            read_vsqx(path, language="ja")

    def test_single_engine_export_contains_exactly_one_project_file(self):
        source = example()
        source["notes"][0]["pinyin_override"] = None
        for target, suffix in [("ace", ".acep"), ("synthv", ".svp"), ("vocaloid5", ".vsqx"), ("vocaloid6", ".vsqx")]:
            destination = self.folder / target
            with self.subTest(target=target):
                exported = adapters.export_project(source, None, destination, target, ROOT / "templates/speech_template.acep")
                self.assertEqual(len(exported["files"]), 1)
                contents = list(destination.iterdir())
                self.assertEqual(len(contents), 1)
                self.assertTrue(contents[0].is_file())
                self.assertEqual(contents[0].suffix, suffix)

    def test_stock_voice_and_seed_namespaces_are_distinct_and_repair_preserves_notes(self):
        from native_acep import configure_ace_voice
        original = read_acep(ROOT / "templates/speech_template.acep")["tracks"][0]
        snapshot = copy.deepcopy(original)
        for language, voice_id, seed_code in [("zh", 8, 6), ("ja", 34, 30), ("en", 56, 110)]:
            with self.subTest(language=language):
                corrected = configure_ace_voice(original, language)
                singer = corrected["singers"][0]["singer"]
                self.assertEqual((singer["id"], singer["router"], singer["composition"][0]["code"]),
                                 (voice_id, 13, seed_code))
                self.assertEqual(corrected["patterns"], original["patterns"])
                self.assertEqual(corrected["soundSourceMetadata"], original["soundSourceMetadata"])
                self.assertEqual(corrected["extraInfo"]["vvtalkStudio"]["seedRef"], f"seed:{seed_code}")
        self.assertEqual(original, snapshot)

    def test_old_voice_cache_without_seed_identity_is_rejected(self):
        from pronunciation import ace_voice_for_language
        with patch("pronunciation._ace_snapshot", return_value={"voices": {"en": {"id": 56, "ref": "singer:56"}}}):
            with self.assertRaisesRegex(ValueError, "离线兼容声库信息"):
                ace_voice_for_language.__wrapped__("en")

    def test_native_svp_independent_decode_preserves_source_samples_and_silence_gaps(self):
        data = example()
        data["bpm"] = 87.5
        path = adapters.write_svp(data, self.folder / "native.svp")
        project = json.loads(path.read_text(encoding="utf-8"))
        rate = project["time"]["tempo"][0]["bpm"] * 705600000 / 60
        controls = project["tracks"][0]["mainGroup"]["pitchControls"]
        decoded = []
        for control in controls:
            points = control["points"]
            decoded.extend(((control["pos"] + tick) / rate, control["pitch"] + pitch)
                           for tick, pitch in zip(points[::2], points[1::2]))
        expected = [(p["time"], p["pitch"]) for p in data["curve"] if p["pitch"] is not None]
        self.assertEqual(len(decoded), len(expected))
        for (time, pitch), (expected_time, expected_pitch) in zip(decoded, expected):
            self.assertAlmostEqual(time, expected_time, delta=.5 / rate + 1e-12)
            self.assertAlmostEqual(pitch, expected_pitch, delta=1e-12)
        end = (controls[0]["pos"] + controls[0]["points"][-2]) / rate
        begin = controls[1]["pos"] / rate
        self.assertLess(end, .5)
        self.assertGreaterEqual(begin, .75 - .5 / rate)

    def test_native_svp_single_measurement_uses_constant_one_blick_curve(self):
        data = example()
        data["curve"] = [{"time": .1, "pitch": 63.25}, {"time": .2, "pitch": None}]
        path = adapters.write_svp(data, self.folder / "single.svp")
        control = json.loads(path.read_text(encoding="utf-8"))["tracks"][0]["mainGroup"]["pitchControls"][0]
        self.assertEqual(control["type"], "curve")
        self.assertEqual(control["points"], [0, 0, 1, 0])
        self.assertEqual(control["pitch"], 63.25)

    @unittest.skipUnless(shutil.which("node"), "Node not available for mock host")
    def test_sv2_script_uses_host_time_axis_native_curve_and_single_undo(self):
        script = self.folder / "import.js"
        adapters.write_synthv_script(example(), script)
        mock = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const log = {undo: 0, groups: [], tracks: [], messages: []};
function create(type) {
    const obj = {type, notes: [], controls: [], refs: []};
    ['Name','Onset','Duration','Pitch','Lyrics','LanguageOverride','Points','Position','Target','TimeOffset','PitchOffset'].forEach(k => {
        obj['set'+k] = v => obj[k.toLowerCase()] = v;
    });
    obj.setScriptData = (k,v) => { obj[k] = v; };
    obj.addNote = n => obj.notes.push(n);
    obj.addPitchControl = n => obj.controls.push(n);
    obj.addGroupReference = n => obj.refs.push(n);
    return obj;
}
const axis = {getBlickFromSeconds: t => t <= .6 ? t*1000 : 600+(t-.6)*2000};
const project = {getTimeAxis: () => axis, newUndoRecord: () => log.undo++, addNoteGroup: g => log.groups.push(g), addTrack: t => log.tracks.push(t)};
const context = {SV: {create, getProject: () => project, showMessageBox: (t,m) => log.messages.push(m), finish: () => {}, getHostClipboard: () => ''}};
vm.createContext(context); vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.main();
assert.strictEqual(log.undo, 1); assert.strictEqual(log.groups.length, 1); assert.strictEqual(log.tracks.length, 1);
const g = log.groups[0];
assert.strictEqual(g.notes[0].duration, 500); assert.strictEqual(g.notes[1].onset, 900);
assert.strictEqual(g.controls.length, 2); assert.strictEqual(g.controls[0].type, 'PitchControlCurve');
assert.strictEqual(g.controls[0].pitch, 61); assert.strictEqual(g.controls[0].points[1][0], 250);
assert.strictEqual(g.controls[0].points[1][1], 1); assert.strictEqual(g.controls[1].position, 900);
context.EMBEDDED_DATA.notes[0].pitch = NaN; context.main(); assert.strictEqual(log.undo, 1);
context.EMBEDDED_DATA.notes[0].pitch = 60;
['ja', 'en'].forEach((lang, index) => {
    context.EMBEDDED_DATA.language = lang;
    context.EMBEDDED_DATA.notes.forEach(n => { n.language = lang; n.pinyinOverride = null; n.lyrics = lang === 'ja' ? 'こ' : 'hello'; });
    context.EMBEDDED_DATA.notes[0].pronunciationOverride = lang === 'ja' ? 'こ' : 'HH AH0 L OW1';
    context.main(); assert.strictEqual(log.undo, index + 2);
    const n = log.groups[index + 1].notes[0];
    assert.strictEqual(n.languageoverride, lang === 'ja' ? 'japanese' : 'english');
    assert.strictEqual(n['vvtalkstudio.language'], lang);
    assert.strictEqual(n['vvtalkstudio.pronunciationOverride'], context.EMBEDDED_DATA.notes[0].pronunciationOverride);
});
context.EMBEDDED_DATA.language = 'fr'; context.main(); assert.strictEqual(log.undo, 3);
console.log('SV2 mock host: curves, units, undo, language override and metadata passed');
'''
        completed = subprocess.run([shutil.which("node"), "-e", mock, str(script)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
