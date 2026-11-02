import tempfile
import unittest
from pathlib import Path

from settings import load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_desktop_notifications_default_off_and_preserve_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preferences.json"
            self.assertFalse(load_settings(path)["notifications"])
            path.write_text('{}')
            self.assertFalse(load_settings(path)["notifications"])
            path.write_text('{"notifications": true}')
            self.assertTrue(load_settings(path)["notifications"])

    def test_round_trip_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preferences.json"
            saved = {"camera": 2, "view": "side", "alert_seconds": 10,
                     "notifications": False}
            save_settings(saved, path)
            self.assertEqual(load_settings(path), {**saved, "alert_seconds": 10.0})
            path.write_text('{"camera": -1, "view": "other", "alert_seconds": 0}')
            self.assertEqual(load_settings(path)["camera"], 0)
            self.assertEqual(load_settings(path)["view"], "auto")
            self.assertEqual(load_settings(path)["alert_seconds"], 5.0)

    def test_saved_image_mode_migrates_to_live_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preferences.json"
            path.write_text('{"web": {"writing_enabled": true, "writing_hand": "left", "writing_assessment": "image"}}')
            settings = load_settings(path)
            self.assertTrue(settings['web']['writing_enabled'])
            self.assertEqual(settings['web']['writing_hand'], 'left')
            self.assertEqual(settings['web']['writing_assessment'], 'geometry')


if __name__ == "__main__":
    unittest.main()
