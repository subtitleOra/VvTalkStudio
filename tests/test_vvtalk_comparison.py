import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))
from adapters import write_vsqx
from import_vsqx import read_vsqx

sys.path.insert(0, str(ROOT / "tests"))
from helpers import vsqx_decoder as qa


def legacy_fixture(path):
    # Controller values and the three note timings are from the real temp(2).vsqx.
    events = [(0, 2136), (100, -377), (200, -3418), (227, -4236),
              (228, -4295), (230, -4347), (419, -935), (420, -781), (422, -626), (582, -686)]
    controllers = '<cc><t>1</t><v id="S">17</v></cc>' + ''.join(
        f'<cc><t>{tick}</t><v id="P">{value}</v></cc>' for tick, value in events)
    notes = ''.join(f'<note><t>{onset}</t><dur>{duration}</dur><n>61</n><y>{lyric}</y><p /></note>'
                    for onset, duration, lyric in [(0, 225, "zhu"), (227, 190, "lao"), (419, 164, "shi")])
    path.write_text('<vsq4 xmlns="http://www.yamaha.co.jp/vocaloid/schema/vsq4/">'
                    '<masterTrack><resolution>480</resolution><preMeasure>0</preMeasure>'
                    '<timeSig><m>0</m><nu>4</nu><de>4</de></timeSig>'
                    '<tempo><t>0</t><v>12000</v></tempo></masterTrack>'
                    '<vsTrack><vsPart><t>1920</t>' + controllers + notes + '</vsPart></vsTrack></vsq4>',
                    encoding="utf-8")
    return path


class OriginalVvTalkComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.path = legacy_fixture(self.folder / "original.vsqx")

    def tearDown(self):
        self.temporary.cleanup()

    def test_independent_decoder_keeps_initial_pbs_and_masks_note_gaps(self):
        decoded = qa.decode_vsqx(self.path)
        self.assertEqual(decoded["project_offset_seconds"], 2)
        self.assertAlmostEqual(qa.pitch_at(decoded, 0), 61 + 2136 * 2 / 8192)
        self.assertAlmostEqual(qa.pitch_at(decoded, 1 / 960), 61 + 2136 * 17 / 8192)
        self.assertIsNone(qa.pitch_at(decoded, 226 / 960))
        self.assertAlmostEqual(qa.pitch_at(decoded, 227 / 960), 61 - 4236 * 17 / 8192)
        root = ET.parse(self.path).getroot()
        namespace = {"v": "http://www.yamaha.co.jp/vocaloid/schema/vsq4/"}
        root.find("v:masterTrack/v:preMeasure", namespace).text = "1"
        ET.ElementTree(root).write(self.path, encoding="utf-8")
        self.assertEqual(qa.decode_vsqx(self.path)["project_offset_seconds"], 0)

    def test_real_legacy_values_roundtrip_preserves_geometry_and_absolute_pitch(self):
        before_hash = qa.digest(self.path)
        imported = read_vsqx(self.path)
        self.assertEqual(imported["source_offset_seconds"], 2)
        self.assertAlmostEqual(imported["curve"][0]["pitch"], 61 + 2136 * 2 / 8192, delta=1e-6)
        case = qa.roundtrip_actual(self.path, self.folder / "studio.vsqx", read_vsqx, write_vsqx)
        self.assertTrue(case["passed"], case)
        self.assertTrue(case["geometry_equal"])
        self.assertEqual(qa.digest(self.path), before_hash)
        self.assertGreater(case["error"]["count"], 10)
        self.assertLessEqual(case["error"]["max_abs_cents"], case["allowed_quantization_cents"])
        self.assertEqual(case["studio"]["pbs_events"][0]["tick"], 0)


if __name__ == "__main__":
    unittest.main()
