"""Dashboard contracts: privacy boundary, preferences, and missing measurements."""
from datetime import datetime
from http.client import HTTPConnection
import json
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from main import Monitor, demo_measurement
from web_server import (Dashboard, Server, WEB_DEFAULTS, describe_snapshot,
                        make_handler, quiet_now, validate_preferences)


def args():
    return SimpleNamespace(camera=0, view="front", alert_seconds=5,
                           notifications=False, side_camera=None, side_url=None, demo=True)


def preferences():
    return {"camera": 0, "view": "front", "alert_seconds": 5,
            "notifications": False, "web": WEB_DEFAULTS.copy()}


class WebTests(unittest.TestCase):
    def test_tiredness_reminders_obey_preferences_and_tracking(self):
        from fatigue_detector import BREAK_GUIDANCE
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.started = True
        dashboard.cameras['front'] = {'fatigue': {'warning': True, 'guidance': BREAK_GUIDANCE}}
        self.assertEqual(dashboard.state()['alerts'], [BREAK_GUIDANCE])
        self.assertEqual(dashboard.state()['notifications'][0]['category'], 'Tiredness')
        dashboard.settings['web']['fatigue_alerts'] = False
        self.assertEqual(dashboard.state()['alerts'], [])
        self.assertTrue(dashboard.state()['cameras']['front']['fatigue']['warning'])
        dashboard.settings['web']['fatigue_alerts'] = True
        dashboard.command({'action': 'snooze', 'minutes': 5})
        self.assertEqual(dashboard.state()['alerts'], [])
        dashboard.command({'action': 'unsnooze'})
        with patch('web_server.quiet_now', return_value=True):
            self.assertEqual(dashboard.state()['alerts'], [])
        dashboard.cameras['front']['updated_at'] = time.monotonic() - 10
        self.assertEqual(dashboard.state()['alerts'], [])
        self.assertNotIn('fatigue', dashboard.state()['cameras']['front'])
        with self.assertRaises(ValueError):
            validate_preferences({'fatigue_alerts': 'yes'}, preferences())
        self.assertFalse(validate_preferences({'fatigue_alerts': False}, preferences())['web']['fatigue_alerts'])

    def test_preferences_validate_atomically(self):
        original = preferences()
        for update in ({"camera": True}, {"camera": 1.5}, {"break_minutes": float('nan')},
                       {"posture_alerts": "false"}, {"side_source": "file:///tmp/camera"},
                       {"side_source": "0"}, {"quiet_start": "22:00"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_preferences(update, original)
        self.assertEqual(original, preferences())
        result = validate_preferences({"alert_seconds": 12, "sensitivity": "gentle",
                                       "side_source": "1"}, original)
        self.assertEqual(result['alert_seconds'], 12)
        self.assertEqual(result['web']['side_source'], '1')

    def test_voice_and_writing_preferences_are_validated(self):
        original = preferences()
        for update in ({"spoken_alerts": "yes"}, {"speech_volume": 2}, {"speech_rate": .1},
                       {"writing_hand": "either"}, {"writing_source": "00"},
                       {"side_source": "1", "writing_source": "01"}, {"history_enabled": 1}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_preferences(update, original)
        updated = validate_preferences({"writing_enabled": True, "writing_hand": "left",
                                        "writing_source": "2", "spoken_alerts": True}, original)
        self.assertEqual(updated['web']['writing_hand'], 'left')

    def test_writing_reminders_obey_categories_and_snooze(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.started = True
        dashboard.settings['web']['writing_enabled'] = True
        dashboard.writing = {'warning': True, 'guidance': ['Your grip geometry changed.']}
        self.assertEqual(dashboard.state()['alerts'], ['Your grip geometry changed.'])
        dashboard.settings['web']['writing_alerts'] = False
        self.assertEqual(dashboard.state()['alerts'], [])
        dashboard.settings['web']['writing_alerts'] = True
        dashboard.command({'action': 'snooze', 'minutes': 5})
        self.assertEqual(dashboard.state()['alerts'], [])

    def test_severity_notifications_and_score_respect_missing_tracking_and_snooze(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.started = True
        dashboard.cameras['front'] = {'phase': 'monitoring', 'warning': True,
            'guidance': ['Adjust torso'], 'metrics': [{'name': 'Torso lean', 'available': True,
                'delta': 20, 'threshold': 10, 'issue': True, 'guidance': 'Adjust torso'}]}
        state = dashboard.state()
        self.assertEqual(state['coaching']['score'], 0)
        self.assertEqual(state['notifications'][0]['severity'], 'attention')
        self.assertEqual(state['notifications'][0]['score'], 0)
        dashboard.command({'action': 'snooze', 'minutes': 5})
        state = dashboard.state()
        self.assertEqual(state['notifications'], [])
        self.assertEqual(state['coaching']['score'], 0)
        dashboard.cameras['front']['updated_at'] = time.monotonic() - 10
        self.assertIsNone(dashboard.state()['coaching']['score'])

    def test_break_pauses_cameras_and_snoozes_reminders(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        self.assertFalse(dashboard.started)
        dashboard.command({'action': 'start'})
        dashboard.command({'action': 'take_break'})
        state = dashboard.state()
        self.assertTrue(state['paused'])
        self.assertGreater(state['break_seconds'], 115)
        self.assertGreater(state['snooze_seconds'], 115)
        with self.assertRaises(ValueError):
            dashboard.command({'action': 'clear_history'})
        dashboard.command({'action': 'stop'})
        dashboard.command({'action': 'clear_history'})
        self.assertIsNone(dashboard.analytics.summary())
        self.assertFalse(dashboard.paused)

    def test_quiet_hours_cross_midnight(self):
        prefs = {**WEB_DEFAULTS, "quiet_start": "22:00", "quiet_end": "07:00"}
        for hour, expected in ((23, True), (3, True), (12, False), (7, False)):
            self.assertEqual(quiet_now(prefs, datetime(2026, 10, 28, hour)), expected)

    def test_break_completion_waits_for_resume_and_early_end_is_idempotent(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.command({'action': 'start'})
        dashboard.command({'action': 'take_break'})
        dashboard.break_until = time.monotonic() - 1
        state = dashboard.state()
        self.assertEqual(state['break_seconds'], 0)
        self.assertTrue(state['break_active'])
        self.assertTrue(state['paused'])
        dashboard.command({'action': 'end_break'})
        self.assertFalse(dashboard.state()['break_active'])
        self.assertFalse(dashboard.paused)
        revision = dashboard.revision
        dashboard.command({'action': 'end_break'})
        self.assertEqual(dashboard.revision, revision)
        self.assertFalse(dashboard.paused)
        dashboard.command({'action': 'take_break'})
        dashboard.command({'action': 'end_break'})
        self.assertEqual(dashboard.state()['snooze_seconds'], 0)
        dashboard.command({'action': 'take_break'})
        dashboard.command({'action': 'snooze', 'minutes': 10})
        dashboard.command({'action': 'end_break'})
        self.assertGreater(dashboard.state()['snooze_seconds'], 500)

    def test_snapshot_never_reassures_with_missing_measurements(self):
        monitor = Monitor("front", 5)
        sample = demo_measurement(0, "front")
        monitor.detector.calibrate([sample])
        snap = monitor.update(None, 10, 20, {}, 'test', None)
        data = describe_snapshot(snap, monitor.detector)
        self.assertEqual(data['confidence'], 'Unavailable')
        self.assertEqual(data['status'], 'Tracking unavailable')
        self.assertTrue(all(not row['available'] for row in data['metrics']))
        self.assertNotIn('score', data)
        snap = monitor.update(sample, 11, 20, {}, 'test', .29)
        data = describe_snapshot(snap, monitor.detector)
        self.assertEqual(data['status'], 'Near your reference')
        self.assertEqual(data['eye']['status'], 'Eyes tracked')
        poor = demo_measurement(8, 'front')
        snap = monitor.update(poor, 12, 20, {}, 'test', .29)
        data = describe_snapshot(snap, monitor.detector)
        raised = next(row for row in data['metrics'] if row['name'] == 'Raised shoulders')
        self.assertTrue(raised['issue'])
        self.assertGreater(raised['delta'], 0)

    def test_controls_suppress_alerts_without_hiding_measurements(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.started = True
        dashboard.cameras['front'] = {'warning': True, 'guidance': ['Adjust torso'],
                                      'eye_warning': True, 'eye': {'guidance': ['Blink']},
                                      'break_warning': True}
        self.assertEqual(len(dashboard.state()['alerts']), 3)
        dashboard.settings['web']['eye_alerts'] = False
        self.assertEqual(len(dashboard.state()['alerts']), 2)
        dashboard.command({'action': 'snooze', 'minutes': 10})
        self.assertEqual(dashboard.state()['alerts'], [])
        self.assertTrue(dashboard.state()['cameras']['front']['warning'])
        dashboard.command({'action': 'unsnooze'})
        self.assertEqual(len(dashboard.state()['alerts']), 2)
        dashboard.command({'action': 'pause'})
        self.assertEqual(dashboard.state()['cameras'], {})
        self.assertTrue(dashboard.state()['paused'])

    def test_desktop_notifications_group_simultaneous_cues(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.args.demo = False
        dashboard.settings['notifications'] = True
        dashboard.started = True
        dashboard.cameras['front'] = {'warning': True, 'guidance': ['Adjust torso', 'Relax shoulders'],
                                      'eye_warning': True, 'eye': {'guidance': ['Blink']},
                                      'break_warning': False}
        with patch('notifications.sys.platform', 'darwin'), \
             patch('notifications.MacNotifier._send') as send, \
             patch.object(dashboard.stop, 'wait', side_effect=[False, True]):
            dashboard.notify_worker()
            send.assert_called_once()
            self.assertIn('Blink', send.call_args.args[0])
            self.assertIn('Relax shoulders', send.call_args.args[0])

    def test_demo_never_sends_desktop_notifications(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.started = True
        dashboard.settings['notifications'] = True
        dashboard.cameras['front'] = {'warning': True, 'guidance': ['Adjust torso'],
                                      'eye_warning': False, 'break_warning': False}
        with patch('notifications.sys.platform', 'darwin'), \
             patch('notifications.MacNotifier._send') as send, \
             patch.object(dashboard.stop, 'wait', side_effect=[False, True]):
            dashboard.notify_worker()
            send.assert_not_called()

    def test_stale_measurements_are_not_reported_as_current(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.started = True
        dashboard.cameras['front'] = {'updated_at': time.monotonic() - 10,
                                      'warning': True, 'guidance': ['Old advice']}
        state = dashboard.state()
        self.assertIn('error', state['cameras']['front'])
        self.assertEqual(state['alerts'], [])

    def test_demo_worker_streams_only_after_start_and_pause_clears_it(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.launch()
        try:
            self.assertEqual(dashboard.frames, {})
            dashboard.command({'action': 'start'})
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                with dashboard.lock:
                    if dashboard.frames.get('front'):
                        break
                time.sleep(.05)
            with dashboard.lock:
                self.assertTrue(dashboard.frames.get('front', b'').startswith(b'\xff\xd8'))
                self.assertIn('metrics', dashboard.cameras['front'])
                self.assertIn('fatigue', dashboard.cameras['front'])
            dashboard.command({'action': 'pause'})
            time.sleep(.2)
            self.assertEqual(dashboard.frames, {})
            self.assertEqual(dashboard.cameras, {})
        finally:
            dashboard.stop.set()
            for thread in dashboard.threads:
                thread.join(timeout=3)

    def test_dedicated_writing_demo_feed_and_recalibration(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        dashboard.settings['web'].update(writing_enabled=True, writing_source='2')
        dashboard.launch()
        try:
            dashboard.command({'action': 'start'})
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                with dashboard.lock:
                    if dashboard.frames.get('writing') and dashboard.writing:
                        break
                time.sleep(.05)
            with dashboard.lock:
                self.assertTrue(dashboard.frames.get('writing', b'').startswith(b'\xff\xd8'))
                self.assertEqual(dashboard.writing['phase'], 'calibrating')
                old_revision = dashboard.writing_revision
            dashboard.command({'action': 'writing_calibrate'})
            self.assertEqual(dashboard.writing_revision, old_revision + 1)
            dashboard.command({'action': 'pause'})
            time.sleep(.2)
            self.assertEqual(dashboard.frames, {})
            self.assertEqual(dashboard.writing, {})
        finally:
            dashboard.stop.set()
            for thread in dashboard.threads:
                thread.join(timeout=3)

    def test_http_local_boundary_and_controls(self):
        with patch('web_server.load_settings', return_value=preferences()):
            dashboard = Dashboard(args())
        server = Server(('127.0.0.1', 0), make_handler(dashboard))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection('127.0.0.1', server.server_port)
        try:
            connection.request('GET', '/')
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'Session analytics', response.read())
            connection.request('GET', '/api/state', headers={'Host': 'attacker.example'})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            body = json.dumps({'action': 'start'})
            connection.request('POST', '/api/command', body)
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.request('POST', '/api/command', body, {'X-Dashboard-Token': dashboard.token})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())['started'])
            connection.request('GET', '/manifest.webmanifest')
            response = connection.getresponse()
            self.assertEqual(json.loads(response.read())['display'], 'standalone')
            connection.request('GET', '/api/analytics')
            response = connection.getresponse()
            self.assertIsNotNone(json.loads(response.read())['current'])
            connection.request('GET', '/api/export.csv')
            response = connection.getresponse()
            self.assertIn('attachment', response.getheader('Content-Disposition'))
            self.assertIn(b'near_reference_percent', response.read())
            connection.request('GET', '/api/analytics?id=nonexistent')
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
            connection.request('GET', '/feed/front.jpg')
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_web_preferences_persist(self):
        import tempfile
        from pathlib import Path
        from settings import load_settings, save_settings
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            saved = validate_preferences({'eye_alerts': False, 'break_minutes': 30}, preferences())
            save_settings(saved, path)
            self.assertEqual(load_settings(path), saved)


if __name__ == '__main__':
    unittest.main()
