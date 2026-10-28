import unittest
from unittest.mock import patch

import cv2
import numpy as np

from alerts import AlertTimer
from debug_tui import Dashboard
from eye_detector import EyeAssessment
from main import (Monitor, calibration_instruction, demo_measurement,
                  draw_overlay, draw_side_overlay, preview_guidance)
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

    def test_camera_overlay_stays_simple_and_side_feed_has_status(self):
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
        self.assertIn("Details in terminal", " ".join(labels))
        side = Monitor("side", 5)
        side_snap = side.update(demo_measurement(0, "side"), 0, 20, {}, "phone")
        labels.clear()
        with patch.object(cv2, "putText", side_effect=record):
            draw_side_overlay(cv2, frame, side_snap)
        self.assertIn("PHONE SIDE VIEW", " ".join(labels))

    def test_calibration_guides_framing_and_waits_for_valid_pose(self):
        from dataclasses import replace

        monitor = Monitor("side", 5)
        good = demo_measurement(0, "side")
        far = replace(good, torso_scale=0.05)
        near = replace(good, torso_scale=0.9)
        self.assertIn("closer", calibration_instruction(far, "side"))
        self.assertIn("back", calibration_instruction(near, "side"))
        self.assertEqual(calibration_instruction(replace(good, torso_scale=0.5), "side"), "")
        self.assertIn("right", calibration_instruction(replace(good, body_center=(0.1, 0.5)), "side"))
        snap = monitor.update(far, 0, 20, {}, "phone")
        self.assertEqual(snap.phase, "positioning")
        self.assertIsNone(monitor.calibration_start)
        monitor.update(good, 2, 20, {}, "phone")
        moving = replace(good, body_center=(0.6, 0.5))
        self.assertIn("Hold still", monitor.update(moving, 3, 20, {}, "phone").calibration_hint)
        self.assertIsNone(monitor.calibration_start)
        monitor.update(good, 4, 20, {}, "phone")
        monitor.update(good, 9, 20, {}, "phone")
        self.assertEqual(monitor.update(good, 9.1, 20, {}, "phone").assessment.status, "Good")

    def test_side_dashboard_shows_independent_posture(self):
        front = Monitor("front", 5)
        side = Monitor("side", 5)
        front_snap = front.update(demo_measurement(0, "front"), 0, 20, {}, "laptop")
        side_snap = side.update(demo_measurement(0, "side"), 0, 20, {}, "phone")
        dashboard = Dashboard.__new__(Dashboard)
        dashboard.screen = FakeScreen(-1)
        dashboard.screen.getmaxyx = lambda: (40, 110)
        dashboard.colors_enabled = False
        dashboard.draw(front_snap, front.detector, front.alert, side_snap, side.detector)
        self.assertIn("PHONE SIDE VIEW", dashboard.screen.lines[31])
        self.assertIn("Forward head", dashboard.screen.lines[36])

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
