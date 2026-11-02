"""Pixel-model routing, rated-image scoring and asynchronous lifecycle contracts."""
import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from grip_image_model import (GripImageService, ImageExamples, crop_hand,
                              decode_photo, unit_vector)


def vector(index=0):
    result = np.zeros(512, np.float32)
    result[index] = 1.
    return result


def fake_result():
    return {'phase': 'ready', 'score': 73, 'score_kind': 'recognition_match',
            'score_label': 'Pen-holding image match', 'pen_present': True,
            'label': 'tripod', 'label_text': 'Tripod', 'guidance': 'Compare the image examples.'}


class FakeModel:
    def analyze(self, image, examples):
        return fake_result(), vector()


def dashboard_args(demo=False):
    return SimpleNamespace(camera=0, view='front', alert_seconds=5,
                           notifications=False, side_camera=None, side_url=None, demo=demo)


class GripImageTests(unittest.TestCase):
    def test_photo_decode_and_limits(self):
        output = BytesIO()
        Image.new('RGB', (1500, 500)).save(output, format='JPEG')
        image = decode_photo(base64.b64encode(output.getvalue()).decode())
        self.assertEqual(image.size, (1024, 341))
        for invalid in ('not base64', '', None, 'x'*6_000_001):
            with self.subTest(invalid=str(invalid)[:20]), self.assertRaises(ValueError):
                decode_photo(invalid)

    def test_pixels_remain_usable_when_hand_tracking_is_absent(self):
        frame = np.zeros((480, 640, 3), np.uint8)
        pixels, box = crop_hand(frame)
        self.assertEqual(box, [0, 0, 640, 480])
        self.assertEqual(pixels.shape, frame.shape)
        hand = [SimpleNamespace(x=.3+(i%5)*.05, y=.3+(i//5)*.04) for i in range(21)]
        pixels, box = crop_hand(frame, hand)
        self.assertLess(pixels.shape[0], 480)
        self.assertLess(pixels.shape[1], 640)

    def test_ratings_are_learned_from_image_examples_not_grip_type(self):
        with tempfile.TemporaryDirectory() as folder:
            examples = ImageExamples(Path(folder)/'examples.json')
            self.assertIsNone(examples.predict(vector()))
            examples.add(vector(), 'tripod', 20)
            self.assertIsNone(examples.predict(vector())['rating'])
            examples.add(vector(1), 'fisted', 90)
            self.assertEqual(examples.predict(vector())['rating'], 20)
            self.assertEqual(examples.predict(vector(1))['rating'], 90)
            self.assertEqual(examples.predict(vector())['label'], 'tripod')
            restored = ImageExamples(examples.path)
            self.assertEqual(restored.status()['count'], 2)
            data = json.loads(examples.path.read_text())
            self.assertEqual(set(data['examples'][0]), {'id', 'label', 'rating', 'embedding'})
            with self.assertRaises(ValueError):
                examples.add(vector(), 'tripod', 100)
            for label, rating in (('bad_label', 50), ('tripod', float('nan')), ('tripod', True), ('tripod', 101)):
                with self.assertRaises(ValueError):
                    examples.add(vector(2), label, rating)

    def test_incompatible_library_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'examples.json'
            path.write_text('{"schema":"wrong"}')
            examples = ImageExamples(path)
            with self.assertRaises(ValueError):
                examples.add(vector(), 'tripod', 50)
            self.assertEqual(json.loads(path.read_text())['schema'], 'wrong')

    def test_embedding_validation(self):
        for invalid in (np.zeros(512), np.ones(3), np.full(512, float('nan'))):
            with self.assertRaises(ValueError):
                unit_vector(invalid)

    def test_live_model_runs_outside_camera_and_refuses_stale_results(self):
        with tempfile.TemporaryDirectory() as folder:
            stop = threading.Event()
            service = GripImageService(Path(folder)/'examples.json', stop, FakeModel())
            service.submit(np.zeros((80, 80, 3), np.uint8), None, (1, 0))
            try:
                deadline = time.monotonic()+2
                while service.snapshot((1, 0)).get('phase') != 'ready' and time.monotonic() < deadline:
                    time.sleep(.01)
                result = service.snapshot((1, 0))
                self.assertEqual(result['score'], 73)
                self.assertEqual(service.snapshot((2, 0))['phase'], 'waiting')
                self.assertEqual(service.snapshot((1, 0), time.monotonic()+6)['phase'], 'waiting')
                service.add_example('tripod', 70, 'camera', (1, 0))
                service.reset()
                with self.assertRaises(ValueError):
                    service.add_example('tripod', 70, 'camera', (1, 0))
            finally:
                stop.set(); service.wake.set(); service.thread.join(timeout=2)

    def test_reset_discards_inflight_result_even_when_identity_is_reused(self):
        entered, release = threading.Event(), threading.Event()
        class SlowModel:
            def analyze(self, image, examples):
                entered.set(); release.wait(2)
                return fake_result(), vector()
        with tempfile.TemporaryDirectory() as folder:
            stop = threading.Event()
            service = GripImageService(Path(folder)/'examples.json', stop, SlowModel())
            service.submit(np.zeros((80, 80, 3), np.uint8), None, (1, 0))
            self.assertTrue(entered.wait(2))
            service.reset()
            with service.lock:
                service.active_identity = (1, 0)
            release.set()
            stop.set(); service.wake.set(); service.thread.join(timeout=2)
            self.assertEqual(service.result, {})



if __name__ == '__main__':
    unittest.main()
