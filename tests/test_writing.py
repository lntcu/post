import unittest
from types import SimpleNamespace

from writing_detector import HandMeasurement, WritingMonitor, measure_hand


class WritingTests(unittest.TestCase):
    def calibrated(self):
        monitor = WritingMonitor(calibration_seconds=5)
        for index in range(51):
            result = monitor.update(HandMeasurement(.25, .15, None), index * .1)
        self.assertEqual(result['phase'], 'monitoring')
        return monitor

    def test_missing_or_tiny_hand_is_unavailable(self):
        self.assertIsNone(measure_hand(None, 640, 480))
        points = [SimpleNamespace(x=.5, y=.5) for _ in range(21)]
        self.assertIsNone(measure_hand(points, 640, 480))
        points[0].x = float('nan')
        self.assertIsNone(measure_hand(points, 640, 480))
        result = self.calibrated().update(None, 6)
        self.assertEqual(result['confidence'], 'Unavailable')
        self.assertFalse(result['warning'])

    def test_calibration_resets_on_motion_and_requires_enough_samples(self):
        monitor = WritingMonitor(calibration_seconds=5)
        monitor.update(HandMeasurement(.25, .15), 0)
        result = monitor.update(HandMeasurement(.25, .15), 6)
        self.assertEqual(result['phase'], 'calibrating')
        self.assertEqual(result['remaining'], 5)
        monitor.update(HandMeasurement(1., .15), 6.1)
        self.assertIsNone(monitor.baseline)

    def test_calibration_tolerates_brief_misses_without_counting_unseen_time(self):
        monitor = WritingMonitor(calibration_seconds=5)
        for index in range(91):
            # Drop every fifth frame, as can happen with a partly occluded pen grip.
            result = monitor.update(None if index % 5 == 4 else HandMeasurement(.25, .15), index * .1)
            if index == 50:
                self.assertIsNone(monitor.baseline)  # Missing intervals are not calibrated time.
        self.assertEqual(result['phase'], 'monitoring')
        self.assertIsNotNone(monitor.baseline)
        self.assertEqual(monitor.update(None, 9.1)['confidence'], 'Unavailable')
        self.assertEqual(monitor.update(HandMeasurement(.25, .15), 9.2)['phase'], 'monitoring')

    def test_long_tracking_gap_restarts_incomplete_calibration(self):
        monitor = WritingMonitor(calibration_seconds=5)
        for index in range(21):
            monitor.update(HandMeasurement(.25, .15), index * .1)
        monitor.update(None, 3.)
        result = monitor.update(HandMeasurement(.25, .15), 3.1)
        self.assertEqual(result['remaining'], 5)
        self.assertIsNone(monitor.baseline)

    def test_warning_is_delayed_and_clears_on_missing_tracking(self):
        monitor = self.calibrated()
        result = monitor.update(HandMeasurement(.9, .15), 5.1, delay=2)
        self.assertFalse(result['changed'])  # One jump is smoothed before assessment.
        self.assertFalse(result['warning'])
        # Continue observed frames; do not bridge an invisible gap.
        for index in range(1, 23):
            result = monitor.update(HandMeasurement(.9, .15), 5.1 + index * .1, delay=2)
        self.assertTrue(result['warning'])
        self.assertEqual(result['confidence'], 'Limited')
        self.assertFalse(result['metrics'][2]['available'])
        self.assertFalse(monitor.update(None, 7.4)['warning'])
        self.assertFalse(monitor.update(HandMeasurement(.9, .15), 7.5)['warning'])
        self.assertIn('correctness cannot be determined', result['limitation'])

    def test_normalized_hand_geometry_is_scale_invariant(self):
        points = [SimpleNamespace(x=.5, y=.5) for _ in range(21)]
        points[5] = SimpleNamespace(x=.4, y=.5)
        points[17] = SimpleNamespace(x=.6, y=.5)
        points[4] = SimpleNamespace(x=.43, y=.4)
        points[8] = SimpleNamespace(x=.48, y=.4)
        points[6] = SimpleNamespace(x=.43, y=.45)
        first = measure_hand(points, 640, 480)
        second = measure_hand(points, 1280, 960)
        self.assertAlmostEqual(first.pinch_ratio, second.pinch_ratio)
        self.assertAlmostEqual(first.finger_curl, second.finger_curl)
        self.assertIsNone(first.wrist_degrees)

    def test_natural_writing_range_is_learned_and_does_not_drift(self):
        monitor = WritingMonitor(calibration_seconds=5)
        for index in range(51):
            offset = (-.18, 0, .18)[index % 3]
            result = monitor.update(HandMeasurement(.3 + offset, .2), index * .1)
        self.assertEqual(result['phase'], 'monitoring')
        self.assertAlmostEqual(monitor.thresholds[0], .54)
        self.assertFalse(monitor.update(HandMeasurement(.75, .2), 5.1)['changed'])
        original = monitor.baseline
        for index in range(60):
            result = monitor.update(HandMeasurement(1.1, .2), 5.2 + index * .1, delay=2)
        self.assertTrue(result['warning'])
        self.assertEqual(monitor.baseline, original)
        self.assertLessEqual(monitor.thresholds[0], .35 * 1.75)

    def test_different_grip_shapes_learn_their_own_reference(self):
        for pinch, curl in ((.1, .65), (.8, .1), (1.2, .4)):
            monitor = WritingMonitor(calibration_seconds=5)
            for index in range(51):
                result = monitor.update(HandMeasurement(pinch, curl), index * .1)
            self.assertEqual(result['phase'], 'monitoring')
            self.assertFalse(result['changed'])

    def test_isolated_landmark_jump_is_filtered(self):
        monitor = self.calibrated()
        for index in range(3):
            monitor.update(HandMeasurement(.25, .15), 5.1 + index * .1)
        result = monitor.update(HandMeasurement(1.2, .15), 5.4)
        self.assertFalse(result['changed'])

    def test_alternating_issues_do_not_accumulate_warning_time(self):
        monitor = self.calibrated()
        for index in range(60):
            sample = HandMeasurement(.9, .15) if index % 10 < 5 else HandMeasurement(.25, .65)
            result = monitor.update(sample, 5.1 + index * .1, delay=2)
            self.assertFalse(result['warning'])

    def test_invalid_measurements_never_score_as_near_reference(self):
        monitor = self.calibrated()
        for sample in (HandMeasurement(float('nan'), .1), HandMeasurement(.2, float('inf')),
                       HandMeasurement(-1, .1), HandMeasurement(.2, 1.1)):
            result = monitor.update(sample, 6)
            self.assertEqual(result['confidence'], 'Unavailable')
            self.assertFalse(result['warning'])

    def test_filter_does_not_fill_in_missing_wrist(self):
        monitor = self.calibrated()
        monitor.baseline = HandMeasurement(.25, .15, 0)
        monitor.update(HandMeasurement(.25, .15, 10), 5.1)
        result = monitor.update(HandMeasurement(.25, .15), 5.2)
        self.assertFalse(result['metrics'][2]['available'])
    def test_wrist_projection_requires_matching_visible_forearm(self):
        points = [SimpleNamespace(x=.5, y=.5) for _ in range(21)]
        points[0] = SimpleNamespace(x=.5, y=.6)
        points[5] = SimpleNamespace(x=.4, y=.5)
        points[17] = SimpleNamespace(x=.6, y=.5)
        points[9] = SimpleNamespace(x=.5, y=.4)
        pose = [SimpleNamespace(x=0., y=0., visibility=0.) for _ in range(33)]
        pose[14] = SimpleNamespace(x=.5, y=.95, visibility=.9)
        pose[16] = SimpleNamespace(x=.5, y=.6, visibility=.9)
        measured = measure_hand(points, 640, 480, pose)
        self.assertAlmostEqual(measured.wrist_degrees, 0.)
        pose[14].visibility = .1
        self.assertIsNone(measure_hand(points, 640, 480, pose).wrist_degrees)



if __name__ == '__main__':
    unittest.main()
