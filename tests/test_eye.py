import unittest
from types import SimpleNamespace

from eye_detector import EyeMonitor, eye_openness, measure_eyes, LEFT_EYE, RIGHT_EYE


def face(lid_gap=0.04):
    marks = [SimpleNamespace(x=0.5, y=0.5) for _ in range(468)]
    for indices, start in ((LEFT_EYE, 0.30), (RIGHT_EYE, 0.60)):
        coords = ((start, 0.4), (start + 0.12, 0.4),
                  (start + 0.04, 0.4 - lid_gap / 2),
                  (start + 0.08, 0.4 - lid_gap / 2),
                  (start + 0.04, 0.4 + lid_gap / 2),
                  (start + 0.08, 0.4 + lid_gap / 2))
        for index, (x, y) in zip(indices, coords):
            marks[index].x, marks[index].y = x, y
    return marks


class EyeTests(unittest.TestCase):
    def test_openness_uses_both_eyes_and_rejects_small_faces(self):
        self.assertGreater(eye_openness(face(), 640, 480), 0.20)
        self.assertLess(eye_openness(face(0.008), 640, 480), 0.20)
        self.assertIsNone(eye_openness(face(), 30, 30))
        self.assertIsNone(eye_openness(None, 640, 480))

    def test_one_visible_eye_can_be_measured(self):
        marks = face()
        marks[RIGHT_EYE[0]].x = float("nan")
        measured = measure_eyes(marks, 640, 480)
        self.assertIsNotNone(measured.left_ratio)
        self.assertIsNone(measured.right_ratio)
        self.assertEqual(measured.openness, measured.left_ratio)

    def test_blink_and_prolonged_closure(self):
        monitor = EyeMonitor()
        monitor.update(0.3, 0)
        monitor.update(0.1, 0.1)
        self.assertEqual(monitor.update(0.3, 0.3).status, "Tracking")
        self.assertEqual(len(monitor.blinks), 1)
        for tenth in range(4, 21):
            result = monitor.update(0.1, tenth / 10)
        self.assertEqual(result.status, "Possible fatigue")
        self.assertEqual(monitor.update(0.3, 2.1).status, "Tracking")
        monitor.update(0.1, 2.2)
        self.assertEqual(monitor.update(None, 2.3).status, "Not Detected")
        self.assertEqual(monitor.update(0.3, 2.4).status, "Tracking")
        self.assertEqual(len(monitor.blinks), 1)
        self.assertEqual(monitor.update(None, 3.3).status, "Not Detected")
        self.assertEqual(monitor.update(0.3, 3.4).blink_count, 0)

    def test_low_blink_rate_and_missing_face_reset(self):
        monitor = EyeMonitor()
        for tenth in range(601):
            result = monitor.update(0.3, tenth / 10)
            if tenth == 50:
                self.assertEqual(result.blinks_per_minute, 0)
        self.assertEqual(result.status, "Possible strain")
        self.assertEqual(result.blinks_per_minute, 0)
        self.assertEqual(monitor.update(None, 60.1).status, "Not Detected")
        self.assertEqual(monitor.update(0.3, 60.2).status, "Possible strain")

    def test_relative_cutoff_counts_blinks_for_narrow_eyes(self):
        monitor = EyeMonitor()
        for tenth in range(11):
            monitor.update(0.18, tenth / 10)
        closed = monitor.update(0.07, 1.1)
        reopened = monitor.update(0.18, 1.2)
        self.assertLess(closed.closed_threshold, 0.20)
        self.assertEqual(reopened.blink_count, 1)
        self.assertEqual(reopened.left_ratio, 0.18)

    def test_closed_fraction_is_an_independent_fatigue_indicator(self):
        monitor = EyeMonitor()
        result = None
        for tenth in range(201):
            # Repeated short closures: no individual closure reaches 1.5 s.
            openness = 0.1 if tenth % 10 < 4 else 0.3
            result = monitor.update(openness, tenth / 10)
        self.assertIn("Eyes closed often", result.reasons)
        self.assertEqual(result.status, "Possible fatigue")


if __name__ == "__main__":
    unittest.main()
