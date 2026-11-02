import unittest
from coaching import assessment, build_coaching, writing_posture_guidance


def source(delta=0, warning=False, name='Torso lean'):
    return {'phase': 'monitoring', 'warning': warning, 'metrics': [
        {'name': name, 'available': True, 'delta': delta, 'threshold': 10,
         'issue': delta >= 10, 'guidance': 'Relax and check your position.'}]}


class CoachingTests(unittest.TestCase):
    def test_alignment_score_and_escalation(self):
        for delta, warning, score, severity in ((0, False, 100, 'success'),
                                               (10, False, 50, 'suggestion'),
                                               (10, True, 50, 'warning'),
                                               (20, True, 0, 'attention')):
            with self.subTest(delta=delta, warning=warning):
                result = assessment(source(delta, warning), 'Posture')
                self.assertEqual(result['score'], score)
                self.assertEqual(result['severity'], severity)

    def test_one_sided_changes_do_not_reduce_score_in_other_direction(self):
        self.assertEqual(assessment(source(-30, name='Raised shoulders'), 'Posture')['score'], 100)
        self.assertEqual(assessment(source(-30, name='Wrist'), 'Grip', hand=True)['score'], 0)

    def test_missing_sources_and_pauses_never_score_as_good(self):
        for live in (True, False):
            result = build_coaching({'front': source()}, {}, True, live)
            self.assertIsNone(result['score'])
        result = build_coaching({'front': source()}, {}, False, True, side_enabled=True)
        self.assertIsNone(result['score'])
        self.assertEqual(len(result['parts']), 2)

    def test_partial_tracking_is_labeled_and_combined_equally(self):
        camera = source()
        camera['metrics'].append({'available': False})
        result = build_coaching({'front': camera}, source(10), True, True)
        self.assertEqual(result['score'], 75)
        self.assertEqual(result['coverage'], 'Limited')
        camera['error'] = 'Camera disconnected'
        self.assertIsNone(build_coaching({'front': camera}, source(), True, True)['score'])

    def test_writing_posture_cues_reference_paper_not_screen(self):
        from main import POSTURE_GUIDANCE
        cameras = {'front': {'guidance': [POSTURE_GUIDANCE['Head turn']], 'metrics': [
            {'name': 'Head turn', 'guidance': POSTURE_GUIDANCE['Head turn']}]}}
        writing_posture_guidance(cameras)
        self.assertIn('paper', cameras['front']['guidance'][0])
        self.assertNotIn('screen', cameras['front']['guidance'][0])
        self.assertEqual(cameras['front']['guidance'][0], cameras['front']['metrics'][0]['guidance'])
