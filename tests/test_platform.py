import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import platform_support


class PlatformSupportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_data_dir_honours_override_and_macos_default(self):
        with patch.dict(os.environ, {"VVTALK_DATA_DIR": str(self.folder)}):
            self.assertEqual(platform_support.data_dir(), self.folder)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VVTALK_DATA_DIR", None)
            with patch.object(platform_support, "IS_WINDOWS", False), \
                 patch.object(platform_support, "IS_MACOS", True):
                self.assertEqual(platform_support.data_dir(),
                                 Path.home() / "Library" / "Application Support" / "VvTalkStudio")

    def test_macos_webview_options_use_wkwebview_and_persistent_storage(self):
        with patch.object(platform_support, "IS_WINDOWS", False), \
             patch.object(platform_support, "IS_MACOS", True):
            options = platform_support.webview_start_options(self.folder / "storage")
        self.assertEqual(options, {"gui": "cocoa", "private_mode": False})

    def test_windows_webview_options_keep_edgechromium_storage_path(self):
        with patch.object(platform_support, "IS_WINDOWS", True), \
             patch.object(platform_support, "IS_MACOS", False):
            options = platform_support.webview_start_options(self.folder / "storage")
        self.assertEqual(options, {"gui": "edgechromium", "private_mode": False,
                                   "storage_path": str(self.folder / "storage")})

    def test_macos_host_and_cli_paths(self):
        with patch.object(platform_support, "IS_WINDOWS", False), \
             patch.object(platform_support, "IS_MACOS", True):
            hosts = platform_support.host_paths()
            candidates = [str(path) for path in platform_support.ace_cli_candidates()]
        self.assertIn("ACE Studio.app", str(hosts["ace"]))
        self.assertIn("Synthesizer V Studio 2 Pro.app", str(hosts["synthv"]))
        self.assertTrue(any(path.endswith("Contents/Helpers/acestudio-cli") for path in candidates))

    def test_ace_cli_override_wins(self):
        with patch.dict(os.environ, {"VVTALK_ACE_CLI": str(self.folder / "custom-cli")}):
            self.assertEqual(platform_support.ace_cli_candidates()[0], self.folder / "custom-cli")

    def test_synthv_scripts_dir_macos(self):
        with patch.object(platform_support, "IS_WINDOWS", False), \
             patch.object(platform_support, "IS_MACOS", True), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VVTALK_SV_SCRIPTS_DIR", None)
            directory = platform_support.synthv_scripts_dir()
        self.assertEqual(directory, Path.home() / "Library" / "Application Support" /
                         "Dreamtonics" / "Synthesizer V Studio 2" / "scripts")

    def test_creation_flags_are_zero_on_macos(self):
        with patch.object(platform_support, "IS_WINDOWS", False):
            self.assertEqual(platform_support.creation_flags(), 0)


if __name__ == "__main__":
    unittest.main()
