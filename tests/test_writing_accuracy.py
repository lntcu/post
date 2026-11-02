"""Geometry invariance, pen observations, sensor separation and validation boundaries."""
import json
import math
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace as Point
import unittest
from unittest.mock import patch

import numpy as np

from coaching import assessment
from pen_detector import PenObservation, detect_pen, pen_features
from writing_detector import HandMeasurement, WritingMonitor, measure_hand
from writing_validation import ChangeModel, WritingRecorder, train
from web_server import Dashboard, WEB_DEFAULTS


def hand():
    # Non-collinear joints with measurable thumb, index and middle articulation.
    coordinates = [(0, 0, 0), (-.3, .2, .1), (-.5, .4, .15), (-.4, .65, .2), (-.2, .8, .25),
                   (-.4, .6, 0), (-.4, 1., .1), (-.25, 1.2, .3), (-.1, 1.1, .45),
                   (0, .7, 0), (0, 1.1, .1), (.15, 1.3, .2), (.25, 1.15, .4),
                   (.2, .6, 0), (.2, .9, .1), (.3, 1., .2), (.4, .9, .3),
                   (.4, .5, 0), (.4, .75, .1), (.5, .85, .2), (.6, .75, .3)]
    world = [Point(x=x*.08, y=y*.08, z=z*.08) for x, y, z in coordinates]
    image = [Point(x=.5+x*.16, y=.65-y*.16) for x, y, _ in coordinates]
    return image, world


def calibrate(features=None, source='world'):
    monitor = WritingMonitor(calibration_seconds=2)
    for i in range(41):
        result = monitor.update(HandMeasurement(.3, .2, 5., features or {}, source), i*.05)
    assert result['phase'] == 'monitoring'
    return monitor


class AccuracyTests(unittest.TestCase):
    def test_world_features_are_invariant_to_rigid_rotation_translation_and_scale(self):
        image, world = hand()
        first = measure_hand(image, 1000, 800, world=world)
        angle = 1.1
        rotated = [Point(x=3*(p.x*math.cos(angle)+p.z*math.sin(angle))+.8,
                         y=3*p.y-.3, z=3*(-p.x*math.sin(angle)+p.z*math.cos(angle))+.2) for p in world]
        second = measure_hand(image, 1000, 800, world=rotated)
        self.assertEqual(first.geometry_source, 'world')
        self.assertAlmostEqual(first.pinch_ratio, second.pinch_ratio)
        self.assertAlmostEqual(first.finger_curl, second.finger_curl)
        for key in first.features:
            self.assertAlmostEqual(first.features[key], second.features[key], places=8)

    def test_joint_features_distinguish_changes_with_identical_legacy_measurements(self):
        monitor = calibrate({'middle_pip': 120., 'thumb_opposition': .3})
        for i in range(1, 61):
            result = monitor.update(HandMeasurement(.3, .2, 5., {'middle_pip': 170., 'thumb_opposition': .3}, 'world'), 2+i*.05, delay=1)
        self.assertTrue(result['warning'])
        self.assertFalse(any(row['issue'] for row in result['metrics'][:3]))
        self.assertTrue(next(row for row in result['metrics'] if row.get('key') == 'middle_pip')['issue'])
        self.assertLess(result['family_scores']['fingers'], 100)

    def test_pen_detects_markers_and_rejects_ambiguous_pairs(self):
        import cv2
        image, _ = hand()
        frame = np.zeros((800, 1000, 3), np.uint8)
        cv2.circle(frame, (520, 480), 7, (255, 0, 0), -1)
        cv2.circle(frame, (590, 400), 7, (0, 255, 0), -1)
        pen = detect_pen(frame, image)
        self.assertIsNotNone(pen)
        self.assertAlmostEqual(pen.tip_side[0], 520)
        cv2.circle(frame, (650, 480), 7, (255, 0, 0), -1)
        self.assertIsNone(detect_pen(frame, image))

    def test_pen_relative_features_are_translation_and_scale_invariant(self):
        image, _ = hand()
        points = [(p.x*1000, p.y*800) for p in image]
        pen = PenObservation((520, 480), (590, 400))
        palm = math.dist(points[5], points[17])
        a = pen_features(pen, points, palm)
        transform = lambda p: (p[0]*2+15, p[1]*2-35)
        b = pen_features(PenObservation(transform(pen.tip_side), transform(pen.rear)), [transform(p) for p in points], palm*2)
        for key in a:
            self.assertAlmostEqual(a[key], b[key])
        monitor = calibrate(a)
        moved = dict(a, pen_hold_position=a['pen_hold_position']+.8)
        for i in range(1, 41):
            result = monitor.update(HandMeasurement(.3, .2, 5., moved, 'world'), 2+i*.05, delay=.5)
        self.assertTrue(result['warning'])
        self.assertLess(result['family_scores']['pen'], 100)

    def test_coordinate_modes_never_mix_and_default_calibration_is_twelve_seconds(self):
        monitor = WritingMonitor()
        for i in range(121):
            result = monitor.update(HandMeasurement(.3, .2), i*.1)
            if i == 50:
                self.assertEqual(result['phase'], 'calibrating')
        self.assertEqual(result['phase'], 'monitoring')
        result = calibrate().update(HandMeasurement(.3, .2, geometry_source='image'), 2.1)
        self.assertEqual(result['phase'], 'positioning')

    def test_missing_pen_does_not_reuse_old_measurements(self):
        monitor = calibrate({'pen_angle': 30.})
        result = monitor.update(HandMeasurement(.3, .2, 5., {}, 'world'), 2.1)
        self.assertIsNone(result['family_scores']['pen'])
        self.assertFalse(result['pen_observed'])

    def test_score_gives_families_equal_weight(self):
        rows = [{'name': str(i), 'available': True, 'delta': 0, 'threshold': 1} for i in range(10)]
        source = {'phase': 'monitoring', 'metrics': rows, 'family_scores': {'fingers': 100, 'pen': 0, 'wrist': None, 'pressure': None}}
        self.assertEqual(assessment(source, 'Grip', hand=True)['score'], 50)

    def test_sensor_ingestion_validates_expires_and_separates_grip_and_tip(self):
        preferences = {'camera': 0, 'view': 'front', 'alert_seconds': 5, 'notifications': False, 'web': WEB_DEFAULTS.copy()}
        args = Point(camera=0, view='front', alert_seconds=5, notifications=False, side_camera=None, side_url=None, demo=True)
        with patch('web_server.load_settings', return_value=preferences):
            dashboard = Dashboard(args)
        for force in (float('nan'), -1, True):
            with self.assertRaises(ValueError):
                dashboard.command({'action': 'writing_pressure', 'kind': 'grip_force', 'newtons': force, 'device': 'test'})
        dashboard.command({'action': 'writing_pressure', 'kind': 'tip_force', 'newtons': .8, 'device': 'tip-test'})
        self.assertEqual(dashboard.current_pressure(), {'tip_force': .8})
        dashboard.pressure_readings['tip_force']['time'] -= 1
        self.assertEqual(dashboard.current_pressure(), {})
        monitor = calibrate({'grip_force': 2., 'tip_force': .8})
        for i in range(1, 31):
            result = monitor.update(HandMeasurement(.3, .2, 5., {'grip_force': 4., 'tip_force': .8}, 'world'), 2+i*.05, delay=.5)
        self.assertTrue(result['warning'])
        self.assertTrue(next(r for r in result['metrics'] if r.get('key') == 'grip_force')['issue'])
        self.assertFalse(next(r for r in result['metrics'] if r.get('key') == 'tip_force')['issue'])

    def test_world_landmarks_match_selected_hand_not_first_detection(self):
        image, world = hand()
        args = Point(camera=0, view='front', alert_seconds=5, notifications=False, side_camera=None, side_url=None, demo=True)
        with patch('web_server.load_settings', return_value={'web': WEB_DEFAULTS.copy()}):
            dashboard = Dashboard(args)
        result = Point(multi_hand_landmarks=[Point(landmark=[]), Point(landmark=image)],
                       multi_hand_world_landmarks=[Point(landmark=[]), Point(landmark=world)],
                       multi_handedness=[Point(classification=[Point(label='Left', score=.99)]), Point(classification=[Point(label='Right', score=.99)])])
        measured = dashboard.extract_hand(result, np.zeros((800, 1000, 3), np.uint8), None, dashboard.settings)
        self.assertEqual(measured.geometry_source, 'world')
        self.assertAlmostEqual(measured.pinch_ratio, measure_hand(image, 1000, 800, world=world).pinch_ratio)


class ValidationTests(unittest.TestCase):
    def recording(self, participant):
        recorder = WritingRecorder()
        recorder.start(participant, 'usual', 0.)
        for i in range(60):
            label = 'normal' if i < 20 else 'grip_change' if i < 40 else 'camera_rotation'
            recorder.set_label(label)
            delta = 2. if label == 'grip_change' else .05
            result = {'phase': 'monitoring', 'metrics': [{'name': 'Index joint', 'available': True, 'delta': delta, 'threshold': 1.}]}
            recorder.record(HandMeasurement(.3, .2), result, i*.2)
        return recorder

    def test_recording_is_opt_in_labeled_and_bounded(self):
        recorder = WritingRecorder()
        recorder.record(None, {}, 0.)
        self.assertEqual(recorder.frames, [])
        with self.assertRaises(ValueError):
            recorder.start('', '', 0.)
        recorder.start('writer-a', 'usual', 0.)
        recorder.set_label('tracking_failure')
        recorder.record(None, {'phase': 'positioning'}, .1)
        self.assertEqual(json.loads(recorder.export().splitlines()[1])['label'], 'tracking_failure')
        self.assertNotIn('video', recorder.export())
        recorder.record(None, {}, 601.)
        self.assertFalse(recorder.active)

    def test_training_excludes_holdout_participant_and_reports_actual_results(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b, output = [Path(folder)/name for name in ('a.jsonl', 'b.jsonl', 'model.json')]
            a.write_text(self.recording('a').export()); b.write_text(self.recording('b').export())
            report = train([a, b], 'b', output)
            self.assertEqual(report['training_participants'], 1)
            self.assertEqual(report['normal_false_positive_rate'], 0)
            self.assertEqual(report['grip_change_recall'], 1)
            model = ChangeModel(json.loads(output.read_text()))
            self.assertGreater(model.predict([{'name': 'Index joint', 'available': True, 'delta': 2, 'threshold': 1}]), .5)
            self.assertIsNone(model.predict([]))
            with self.assertRaises(ValueError):
                train([a], 'a', output)
            with self.assertRaises(ValueError):
                train([a, a, b], 'b', output)


    def test_loaded_model_refuses_a_different_coordinate_source(self):
        model = ChangeModel({'schema': 'writing-change-model-v1', 'names': ['joint'],
                             'weights': [1., 0.], 'bias': 0., 'geometry_source': 'world'})
        rows = [{'name': 'joint', 'available': True, 'delta': 1., 'threshold': 1.}]
        self.assertIsNone(model.predict(rows, 'image'))
        self.assertGreater(model.predict(rows, 'world'), .5)
        self.assertIsNone(model.predict([{'name': 'unrelated', 'available': True}], 'world'))

    def test_http_recording_and_sensor_commands_preserve_authentication(self):
        from http.client import HTTPConnection
        import threading
        from web_server import Server, make_handler
        args = Point(camera=0, view='front', alert_seconds=5, notifications=False, side_camera=None, side_url=None, demo=True)
        with patch('web_server.load_settings', return_value={'web': WEB_DEFAULTS.copy()}):
            dashboard = Dashboard(args)
        server = Server(('127.0.0.1', 0), make_handler(dashboard))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection('127.0.0.1', server.server_port)
        headers = {'X-Dashboard-Token': dashboard.token}
        try:
            payload = {'action': 'writing_record_start', 'participant': 'a'}
            connection.request('POST', '/api/command', json.dumps(payload), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 400); response.read()
            dashboard.settings['web']['writing_enabled'] = True
            dashboard.command({'action': 'start'})
            connection.request('POST', '/api/command', json.dumps(payload))
            response = connection.getresponse()
            self.assertEqual(response.status, 403); response.read()
            connection.request('POST', '/api/command', json.dumps(payload), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())['writing_recording']['active'])
            dashboard.publish_writing({'phase': 'monitoring', 'metrics': []}, dashboard.revision, dashboard.writing_revision, HandMeasurement(.3, .2))
            connection.request('GET', '/api/writing-recording.jsonl')
            response = connection.getresponse()
            self.assertIn('attachment', response.getheader('Content-Disposition'))
            lines = [json.loads(line) for line in response.read().decode().splitlines()]
            self.assertEqual(lines[0]['schema'], 'writing-observations-v1')
            self.assertEqual(lines[1]['measurement']['pinch_ratio'], .3)
            self.assertNotIn('frames', dashboard.state()['writing_recording'])
            dashboard.command({'action': 'writing_record_label', 'label': 'grip_change'})
            dashboard.command({'action': 'writing_record_stop'})
            self.assertFalse(dashboard.writing_recorder.active)
            dashboard.command({'action': 'writing_pressure', 'kind': 'grip_force', 'newtons': 2., 'device': 'a'})
            revision = dashboard.writing_revision
            dashboard.command({'action': 'writing_pressure', 'kind': 'grip_force', 'newtons': 2., 'device': 'b'})
            self.assertEqual(dashboard.writing_revision, revision+1)
        finally:
            connection.close(); server.shutdown(); server.server_close(); thread.join()

    def test_model_rejects_nonfinite_or_wrong_dimension_coefficients(self):
        with self.assertRaises(ValueError):
            ChangeModel({'schema': 'writing-change-model-v1', 'names': ['a'], 'weights': [float('nan'), 0], 'bias': 0})
        with self.assertRaises(ValueError):
            ChangeModel({'schema': 'writing-change-model-v1', 'names': ['a'], 'weights': [0], 'bias': 0})


if __name__ == '__main__':
    unittest.main()
