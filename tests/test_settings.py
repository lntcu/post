import tempfile
import unittest
from pathlib import Path

from settings import load_settings, save_settings


class SettingsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
