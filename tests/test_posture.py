import unittest
from types import SimpleNamespace

from alerts import AlertTimer
from activity_monitor import ActivityMonitor
from posture_detector import Measurements, PostureDetector


def landmarks():
    points = [SimpleNamespace(x=0.5, y=0.5, visibility=0.9) for _ in range(33)]
    for index, x, y in (
        (0, 0.5, 0.15),
        (7, 0.44, 0.20), (8, 0.56, 0.20),
        (11, 0.4, 0.35), (12, 0.6, 0.35),
        (23, 0.4, 0.72), (24, 0.6, 0.72),
    ):
        points[index].x, points[index].y = x, y
    return points


class PostureTests(unittest.TestCase):
    def test_front_lean_and_shoulder_tilt(self):
        detector = PostureDetector(view="front")
        points = landmarks()
        baseline = detector.measure(points, 640, 480)
        self.assertTrue(detector.calibrate([baseline] * 5))
        self.assertEqual(detector.assess(baseline).status, "Good")
        points[11].x += 0.08
        points[12].x += 0.08
        self.assertIn("Torso lean", detector.assess(detector.measure(points, 640, 480)).reasons)

        points = landmarks()
        points[12].y += 0.08
        self.assertIn("Shoulder tilt", detector.assess(detector.measure(points, 640, 480)).reasons)

    def test_side_forward_head_and_visibility(self):
        detector = PostureDetector(view="side")
        points = landmarks()
        for i in (0, 7, 11, 23):
            points[i].x = {0: 0.65, 7: 0.58, 11: 0.5, 23: 0.5}[i]
        for i in (8, 12, 24):
            points[i].visibility = 0.1
        baseline = detector.measure(points, 640, 480)
        detector.calibrate([baseline])
        points[7].x += 0.1
        assessment = detector.assess(detector.measure(points, 640, 480))
        self.assertIn("Forward head", assessment.reasons)
        points[11].visibility = 0.1
        self.assertEqual(detector.assess(detector.measure(points, 640, 480)).status, "Not Detected")

    def test_neck_shoulder_arm_and_relative_face_size(self):
        detector = PostureDetector(view="front")
        detector.calibrate([detector.measure(landmarks(), 640, 480)])

        points = landmarks()
        points[8].y += 0.07
        self.assertIn("Head tilt", detector.assess(detector.measure(points, 640, 480)).reasons)

        points = landmarks()
        points[0].x += 0.04
        self.assertIn("Head turn", detector.assess(detector.measure(points, 640, 480)).reasons)

        points = landmarks()
        points[11].y = points[12].y = 0.27
        self.assertIn("Raised shoulders", detector.assess(detector.measure(points, 640, 480)).reasons)

        points = landmarks()
        points[13].x, points[14].x = 0.2, 0.8
        self.assertIn("Elbows away from body", detector.assess(detector.measure(points, 640, 480)).reasons)

        points = landmarks()
        points[7].x, points[8].x = 0.40, 0.60
        self.assertIn("Closer to camera", detector.assess(detector.measure(points, 640, 480)).reasons)

    def test_static_sitting_reminder_resets_after_meaningful_movement(self):
        monitor = ActivityMonitor(reminder_seconds=10)
        still = Measurements("front", 0, 0, None, body_center=(0.5, 0.5))
        moved = Measurements("front", 0, 0, None, body_center=(0.6, 0.5))
        self.assertFalse(monitor.update(still, 0).warning)
        for second in range(1, 11):
            result = monitor.update(still, second)
        self.assertTrue(result.warning)
        self.assertFalse(monitor.update(moved, 11).warning)
        self.assertEqual(monitor.update(moved, 12).still_seconds, 1)
        self.assertFalse(monitor.update(None, 13).tracked)
        self.assertEqual(monitor.update(moved, 14).still_seconds, 3)
        self.assertFalse(monitor.update(None, 17).tracked)
        self.assertEqual(monitor.update(moved, 18).still_seconds, 0)

    def test_warning_requires_continuous_poor_time(self):
        timer = AlertTimer(5)
        self.assertEqual(timer.update("Poor", 10), (False, 0))
        self.assertEqual(timer.update("Poor", 14.9)[0], False)
        self.assertEqual(timer.update("Poor", 15)[0], True)
        self.assertEqual(timer.update("Not Detected", 15.1)[0], False)
        self.assertEqual(timer.update("Poor", 20)[0], False)
        self.assertEqual(timer.update("Good", 24)[0], False)


if __name__ == "__main__":
    unittest.main()
