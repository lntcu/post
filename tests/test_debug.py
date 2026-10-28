import unittest
from unittest.mock import patch

import cv2
import numpy as np

from alerts import AlertTimer
from debug_tui import Dashboard
from eye_detector import EyeAssessment
from main import Monitor, demo_measurement, draw_debug_window, draw_overlay, preview_guidance
from posture_detector import PostureDetector


class FakeScreen:
    def __init__(self, key):
        self.key = key
        self.lines = {}

    def getch(self):
        return self.key

    def getmaxyx(self):
        return (32, 110)

    def erase(self):
        self.lines = {}

    def addnstr(self, row, column, value, limit, attr):
        self.lines[row] = value[:limit]

    def refresh(self):
        pass


class DebugTests(unittest.TestCase):
    def test_demo_calibrates_warns_and_clears(self):
        monitor = Monitor("side", 5)
        good = demo_measurement(0, "side")
        poor = demo_measurement(7, "side")
        self.assertEqual(monitor.update(good, 0, 20, {}, "demo").phase, "calibrating")
        monitor.update(good, 5, 20, {}, "demo")
        self.assertEqual(monitor.update(good, 5.1, 20, {}, "demo").assessment.status, "Good")
        self.assertFalse(monitor.update(poor, 6, 20, {}, "demo").warning)
        self.assertTrue(monitor.update(poor, 11, 20, {}, "demo").warning)
        self.assertEqual(monitor.update(good, 13, 20, {}, "demo").assessment.status, "Good")
        self.assertFalse(monitor.update(None, 16, 20, {}, "demo").warning)
        self.assertEqual(monitor.update(None, 16, 20, {}, "demo").assessment.status, "Not Detected")

    def test_dashboard_controls_only_view_and_recalibration(self):
        dashboard = Dashboard.__new__(Dashboard)
        dashboard.screen = FakeScreen(ord("+"))
        detector = PostureDetector()
        alert = AlertTimer()
        self.assertIsNone(dashboard.input(detector, alert))
        self.assertEqual(detector.thresholds.torso_degrees, 12.0)
        self.assertEqual(alert.delay_seconds, 5.0)
        dashboard.screen.key = ord("v")
        self.assertEqual(dashboard.input(detector, alert), "recalibrate")
        self.assertEqual(detector.view, "front")

    def test_dashboard_shows_pose_and_eye_measurements(self):
        monitor = Monitor("front", 5)
        measured = demo_measurement(0, "front")
        snap = monitor.update(measured, 0, 20, {}, "demo", 0.30)
        dashboard = Dashboard.__new__(Dashboard)
        dashboard.screen = FakeScreen(-1)
        dashboard.colors_enabled = False
        dashboard.draw(snap, monitor.detector, monitor.alert)
        lines = dashboard.screen.lines
        self.assertIn("Torso angle", lines[6])
        self.assertIn("Shoulder tilt", lines[7])
        self.assertIn("Head tilt", lines[9])
        self.assertIn("Elbow spread", lines[12])
        self.assertIn("Eye ratio", lines[18])
        self.assertIn("Blinks", lines[20])

    def test_debug_window_has_measurements_and_camera_overlay_stays_simple(self):
        monitor = Monitor("front", 5)
        measured = demo_measurement(0, "front")
        snap = monitor.update(measured, 0, 20, {}, "demo", 0.30)
        frame = np.zeros((720, 960, 3), dtype=np.uint8)
        labels = []
        original = cv2.putText

        def record(image, label, *args):
            labels.append(label)
            return original(image, label, *args)

        with patch.object(cv2, "putText", side_effect=record):
            draw_overlay(cv2, frame, snap, monitor)
        self.assertIn("Posture:", " ".join(labels))
        self.assertNotIn("Torso angle", " ".join(labels))
        labels.clear()
        with patch.object(cv2, "putText", side_effect=record):
            debug_frame = draw_debug_window(cv2, snap, monitor)
        self.assertEqual(debug_frame.shape, (700, 1080, 3))
        text = " ".join(labels)
        for label in ("Torso angle", "Head tilt", "Elbow spread", "Face size",
                      "Still:", "Left / right ratio", "Blink rate"):
            self.assertIn(label, text)

    def test_static_break_reminder_reaches_main_preview(self):
        monitor = Monitor("front", 5)
        monitor.activity.reminder_seconds = 1
        measured = demo_measurement(0, "front")
        monitor.update(measured, 0, 20, {}, "demo", 0.30)
        monitor.update(measured, 5, 20, {}, "demo", 0.30)
        monitor.activity.reset()
        monitor.update(measured, 5.1, 20, {}, "demo", 0.30)
        snap = monitor.update(measured, 6.1, 20, {}, "demo", 0.30)
        self.assertTrue(snap.activity.warning)
        frame = np.zeros((720, 960, 3), dtype=np.uint8)
        labels = []
        original = cv2.putText

        def record(image, label, *args):
            labels.append(label)
            return original(image, label, *args)

        with patch.object(cv2, "putText", side_effect=record):
            draw_overlay(cv2, frame, snap, monitor)
        self.assertIn("Long stillness: change position or take a short break.", labels)

    def test_preview_names_detected_problems_and_actions(self):
        monitor = Monitor("front", 5)
        good = demo_measurement(0, "front")
        monitor.update(good, 0, 20, {}, "demo", 0.30)
        monitor.update(good, 5, 20, {}, "demo", 0.30)
        poor = demo_measurement(7, "front")
        snap = monitor.update(poor, 6, 20, {}, "demo", 0.30)
        snap.eye = EyeAssessment("Possible strain", reasons=("Low blink rate",))
        guidance = preview_guidance(snap)
        self.assertTrue(any("Torso leaning: bring" in text for text, _ in guidance))
        self.assertTrue(any("Blinking infrequently: blink" in text for text, _ in guidance))
        self.assertTrue(any("Uneven shoulders:" in text for text, _ in guidance))
        self.assertLess(guidance.index(next(item for item in guidance if "Blinking" in item[0])), 3)


if __name__ == "__main__":
    unittest.main()
