import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from tracking_overlay import draw_tracking, points_in_frame, demo_landmarks
from web_server import Dashboard


class OverlayTests(unittest.TestCase):
    def test_missing_tracking_does_not_draw_an_invented_skeleton(self):
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        with patch('cv2.line') as line, patch('cv2.circle') as circle:
            counts = draw_tracking(frame)
        line.assert_not_called()
        circle.assert_not_called()
        self.assertEqual(counts, {'body': 0, 'eyes': 0, 'hand': 0, 'simulated': False})

    def test_hidden_invalid_and_out_of_frame_points_are_excluded(self):
        points = [SimpleNamespace(x=.5, y=.5, visibility=.9),
                  SimpleNamespace(x=.5, y=.5, visibility=.2),
                  SimpleNamespace(x=float('nan'), y=.5, visibility=.9),
                  SimpleNamespace(x=1.1, y=.5, visibility=.9)]
        self.assertEqual(set(points_in_frame(points, range(5), 640, 480, .65)), {0})

    def test_detected_points_get_connections_and_labels(self):
        pose, hand = demo_landmarks()
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        with patch('cv2.line') as line, patch('cv2.putText') as text:
            counts = draw_tracking(frame, pose=pose, hand=hand)
        self.assertEqual(counts['body'], 11)
        self.assertEqual(counts['hand'], 21)
        self.assertGreater(line.call_count, 20)
        labels = [call.args[1] for call in text.call_args_list]
        self.assertIn('L shoulder', labels)
        self.assertIn('Index tip', labels)
        self.assertFalse(any(label.startswith(('DETECTED', 'Body ', 'Eyes ', 'Hand ')) for label in labels))

    def test_only_selected_confident_hand_is_used(self):
        hand = SimpleNamespace(landmark=['selected'])
        def result(label, score):
            return SimpleNamespace(multi_hand_landmarks=[hand], multi_handedness=[
                SimpleNamespace(classification=[SimpleNamespace(label=label, score=score)])])
        settings = {'web': {'writing_hand': 'right'}}
        self.assertIsNone(Dashboard.selected_hand(result('Left', .99), settings))
        self.assertIsNone(Dashboard.selected_hand(result('Right', .5), settings))
        self.assertEqual(Dashboard.selected_hand(result('Right', .99), settings), ['selected'])
