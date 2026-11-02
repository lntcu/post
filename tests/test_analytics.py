import csv
import io
from pathlib import Path
import tempfile
import unittest

from analytics import Analytics


def state(*, tracked=True, changed=False, paused=False, writing=False):
    return {'started': True, 'paused': paused,
            'cameras': {'front': {'phase': 'monitoring', 'confidence': 'Limited' if tracked else 'Unavailable',
                        'metrics': [{'name': 'Head tilt', 'available': tracked, 'issue': changed}],
                        'eye': {'confidence': 'Available', 'blinks_per_minute': 12},
                        'activity_tracked': True, 'still_seconds': 10}},
            'writing': {'phase': 'monitoring', 'confidence': 'Limited' if writing else 'Unavailable', 'changed': writing}}


class AnalyticsTests(unittest.TestCase):
    def test_session_alignment_weights_time_and_excludes_pauses_and_missing_scores(self):
        analytics = Analytics(Path('/unused'), demo=True)
        analytics.start(now=0)
        snapshot = state()
        snapshot['coaching'] = {'parts': [{'score': 100}, {'score': None}]}
        analytics.record(snapshot, now=2)
        snapshot['coaching']['parts'] = [{'score': 0}]
        analytics.record(snapshot, now=3)
        self.assertEqual(analytics.summary()['average_alignment'], 67)
        self.assertEqual(analytics.summary()['alignment_seconds'], 3)
        snapshot['coaching']['parts'] = [{'score': None}]
        analytics.record(snapshot, now=4)
        snapshot['paused'] = True
        analytics.record(snapshot, now=5)
        snapshot['paused'] = False
        analytics.record(snapshot, now=20)
        analytics.record(snapshot, now=30)
        self.assertEqual(analytics.summary()['average_alignment'], 67)
        self.assertEqual(analytics.summary()['alignment_seconds'], 3)
        analytics.start(now=31)
        self.assertIsNone(analytics.summary()['average_alignment'])

    def test_session_alignment_includes_observed_eyes_and_zero_scores(self):
        analytics = Analytics(Path('/unused'), demo=True)
        analytics.start(now=0)
        snapshot = state()
        snapshot['coaching'] = {'parts': [{'score': 0}, {'score': None}]}
        snapshot['cameras']['front']['eye'].update(openness=.3, closed_fraction=.1,
            reasons=['Low blink rate', 'Low blink rate'])
        analytics.record(snapshot, now=1)
        self.assertEqual(analytics.summary()['average_alignment'], 38)
        # Unobserved eyes must not become a perfect score.
        snapshot['cameras']['front']['eye']['confidence'] = 'Unavailable'
        analytics.record(snapshot, now=2)
        self.assertEqual(analytics.summary()['average_alignment'], 19)

    def test_time_weighting_denominators_and_untracked(self):
        analytics = Analytics(Path('/unused'), demo=True)
        analytics.start(now=0)
        analytics.record(state(), now=1)
        analytics.record(state(changed=True), now=2)
        analytics.record(state(tracked=False), now=3)
        summary = analytics.summary()
        self.assertEqual(summary['active_seconds'], 3)
        self.assertEqual(summary['tracked_seconds'], 2)
        self.assertEqual(summary['near_percent'], 50)
        self.assertEqual(summary['coverage_percent'], 66.7)
        self.assertEqual(summary['top_issues'], [{'name': 'Head tilt', 'seconds': 1}])
        self.assertEqual(summary['average_blink_rate'], 12)
        self.assertEqual(summary['timeline'][0]['active'], 3)

    def test_second_camera_cannot_be_silently_counted_as_near_reference(self):
        analytics = Analytics(Path('/unused'), demo=True)
        analytics.start(now=0)
        snapshot = state()
        snapshot['settings'] = {'web': {'side_source': '1'}}
        analytics.record(snapshot, now=1)
        self.assertEqual(analytics.summary()['tracked_seconds'], 0)
        snapshot['cameras']['side'] = {'phase': 'monitoring', 'confidence': 'Limited',
                                      'metrics': [{'name': 'Forward head', 'available': True, 'issue': True}]}
        analytics.record(snapshot, now=2)
        summary = analytics.summary()
        self.assertEqual(summary['near_percent'], 0)
        self.assertEqual(summary['tracked_seconds'], 1)
        self.assertEqual(summary['top_issues'][0]['name'], 'Side · Forward head')

    def test_pause_long_gap_and_recalibration_do_not_invent_time(self):
        analytics = Analytics(Path('/unused'), demo=True)
        analytics.start(now=0)
        analytics.record(state(), now=1)
        analytics.record(state(paused=True), now=2)
        analytics.record(state(), now=100)
        analytics.record(state(writing=True), now=101)
        analytics.record(state(), now=150)
        self.assertEqual(analytics.summary()['active_seconds'], 2)
        self.assertEqual(analytics.summary()['writing_seconds'], 1)
        analytics.suspend()
        analytics.record(state(), now=151)
        self.assertEqual(analytics.summary()['active_seconds'], 2)

    def test_persistence_privacy_export_and_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'analytics.sqlite3'
            analytics = Analytics(path)
            analytics.start(now=0)
            analytics.record(state(), now=1)
            analytics.finish()
            restored = Analytics(path)
            self.assertEqual(len(restored.history()), 1)
            self.assertEqual(restored.history()[0]['near_percent'], 100)
            records = list(csv.reader(io.StringIO(restored.export_csv().decode())))
            self.assertEqual(len(records), 2)
            self.assertNotIn('landmarks', path.read_bytes().decode(errors='ignore'))
            analytics.clear()
            self.assertEqual(analytics.history(), [])
            self.assertIsNone(analytics.summary())

    def test_demo_and_disabled_history_never_create_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'analytics.sqlite3'
            for demo, persist in ((True, True), (False, False)):
                analytics = Analytics(path, demo=demo)
                analytics.start(persist=persist, now=0)
                analytics.record(state(), now=1)
                analytics.finish()
                self.assertFalse(path.exists())

    def test_disabled_history_stops_future_saves(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'analytics.sqlite3'
            analytics = Analytics(path)
            analytics.start(now=0)
            analytics.record(state(), now=1)
            analytics.set_persistence(False)
            analytics.record(state(changed=True), now=2)
            analytics.finish()
            self.assertEqual(Analytics(path).history()[0]['active_seconds'], 1)
    def test_private_intervals_are_not_saved_retroactively(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'analytics.sqlite3'
            analytics = Analytics(path)
            analytics.start(persist=False, now=0)
            analytics.record(state(), now=1)
            private_id = analytics.summary()['id']
            analytics.set_persistence(True)
            self.assertNotEqual(analytics.summary()['id'], private_id)
            analytics.record(state(changed=True), now=2)
            analytics.record(state(changed=True), now=3)
            analytics.finish()
            saved = analytics.history()
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]['active_seconds'], 1)
            self.assertEqual(saved[0]['near_seconds'], 0)
            self.assertNotIn('timeline', saved[0])
            self.assertTrue(analytics.detail(saved[0]['id'])['timeline'])



if __name__ == '__main__':
    unittest.main()
