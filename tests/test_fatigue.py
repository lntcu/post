import unittest

from eye_detector import EyeMonitor
from fatigue_detector import BREAK_GUIDANCE, FatigueMonitor


class FatigueTests(unittest.TestCase):
    def setUp(self):
        self.eyes = EyeMonitor()
        self.fatigue = FatigueMonitor()

    def sample(self, value, now):
        return self.fatigue.update(self.eyes.update(value, now), now)

    def test_prolonged_closure_prompts_break_and_holds_after_reopening(self):
        self.sample(.3, 0)
        for tick in range(1, 22):
            result = self.sample(.1, tick / 10)
        self.assertTrue(result.warning)
        self.assertEqual(result.guidance, BREAK_GUIDANCE)
        self.assertIn('Prolonged eye closure', result.reasons)
        self.assertTrue(self.sample(.3, 2.2).warning)
        for tick in range(23, 180):
            result = self.sample(.3, tick / 10)
        self.assertFalse(result.warning)

    def test_normal_blinks_and_no_blinks_do_not_imply_tiredness(self):
        for tick in range(700):
            result = self.sample(.1 if tick % 50 == 1 else .3, tick / 10)
            self.assertFalse(result.warning)
        self.assertEqual(result.slow_closures, 0)

    def test_completed_duration_includes_last_interval_before_reopening(self):
        self.sample(.3, 0)
        for tick in range(1, 6):
            self.sample(.1, tick / 10)
        self.assertEqual(self.sample(.3, .6).slow_closures, 1)

    def test_three_slow_closures_trigger_and_age_out(self):
        for tick in range(101):
            # Three 0.7s closures, separated by open eyes.
            result = self.sample(.1 if tick % 30 in range(10, 17) and tick < 80 else .3, tick / 10)
        self.assertTrue(result.warning)
        self.assertEqual(result.slow_closures, 3)
        self.assertIn('Repeated slow eye closures', result.reasons)
        for tick in range(101, 850):
            result = self.sample(.3, tick / 10)
        self.assertFalse(result.warning)
        self.assertEqual(result.slow_closures, 0)

    def test_missing_tracking_and_time_gaps_clear_tiredness(self):
        for tick in range(25):
            result = self.sample(.3 if tick == 0 else .1, tick / 10)
        self.assertTrue(result.warning)
        self.assertFalse(self.sample(None, 2.5).warning)
        self.assertEqual(self.sample(None, 2.6).status, 'Unavailable')
        self.assertFalse(self.sample(.3, 2.7).warning)
        for tick in range(28, 50):
            result = self.sample(.1, tick / 10)
        self.assertTrue(result.warning)
        self.assertFalse(self.sample(.3, 9).warning)
        self.assertFalse(self.sample(.3, 8).warning)

    def test_frequent_short_closures_are_separate_cue(self):
        for tick in range(250):
            result = self.sample(.1 if tick % 10 in range(2, 6) else .3, tick / 10)
        self.assertTrue(result.warning)
        self.assertIn('Frequent eye closure', result.reasons)


if __name__ == '__main__':
    unittest.main()
