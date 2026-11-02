"""Small, labeled CV overlays. Draw only finite, visible, in-frame landmarks."""
import math

POSE_LABELS = {0: 'Nose', 7: 'L ear', 8: 'R ear', 11: 'L shoulder', 12: 'R shoulder',
               13: 'L elbow', 14: 'R elbow', 15: 'L wrist', 16: 'R wrist', 23: 'L hip', 24: 'R hip'}
POSE_LINES = ((7, 11), (8, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
              (11, 23), (12, 24), (23, 24), (0, 7), (0, 8))
HAND_LINES = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
              (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
              (13, 17), (0, 17), (17, 18), (18, 19), (19, 20))
HAND_LABELS = {0: 'Wrist', 4: 'Thumb tip', 5: 'Index base', 8: 'Index tip', 12: 'Middle tip', 16: 'Ring tip', 20: 'Little tip'}
EYE_LINES = ((33, 160), (160, 158), (158, 133), (133, 153), (153, 144), (144, 33),
             (362, 385), (385, 387), (387, 263), (263, 373), (373, 380), (380, 362))


def points_in_frame(landmarks, indices, width, height, visibility=None):
    points = {}
    if landmarks is None:
        return points
    for index in indices:
        if index >= len(landmarks):
            continue
        p = landmarks[index]
        if visibility is not None and getattr(p, 'visibility', 0) < visibility:
            continue
        if math.isfinite(p.x) and math.isfinite(p.y) and 0 <= p.x < 1 and 0 <= p.y < 1:
            points[index] = (round(p.x * (width - 1)), round(p.y * (height - 1)))
    return points


def draw_tracking(frame, pose=None, face=None, hand=None, *, simulated=False):
    import cv2
    height, width = frame.shape[:2]
    scale = max(.35, min(.65, width / 1500))
    def label(text, point, color):
        size, baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        x = max(2, min(width - size[0] - 3, point[0] + 7))
        y = max(size[1] + 3, min(height - baseline - 3, point[1] - 7))
        cv2.rectangle(frame, (x - 2, y - size[1] - 2), (x + size[0] + 2, y + baseline + 2), (28, 28, 30), -1)
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
    def skeleton(points, lines, labels, color):
        for a, b in lines:
            if a in points and b in points:
                cv2.line(frame, points[a], points[b], color, 2, cv2.LINE_AA)
        for index, point in points.items():
            cv2.circle(frame, point, 4, (25, 25, 25), -1, cv2.LINE_AA)
            cv2.circle(frame, point, 2, color, -1, cv2.LINE_AA)
            if index in labels:
                label(labels[index], point, color)
    body = points_in_frame(pose, POSE_LABELS, width, height, .65)
    fingers = points_in_frame(hand, range(21), width, height)
    eyes = points_in_frame(face, {i for line in EYE_LINES for i in line}, width, height)
    skeleton(body, POSE_LINES, POSE_LABELS, (255, 190, 80))
    skeleton(eyes, EYE_LINES, {33: 'R eye', 263: 'L eye'}, (80, 210, 255))
    skeleton(fingers, HAND_LINES, HAND_LABELS, (165, 240, 100))
    if simulated:
        label('SIMULATED', (6, 28), (240, 240, 240))
    return {'body': len(body), 'eyes': len(eyes), 'hand': len(fingers), 'simulated': simulated}


def demo_landmarks(body=True, hand=True):
    """Clearly simulated example points for the camera-free UI demo."""
    from types import SimpleNamespace
    pose = [SimpleNamespace(x=0., y=0., visibility=0.) for _ in range(33)]
    for i, (x, y) in {0:(.49,.16), 7:(.54,.2), 8:(.44,.2), 11:(.62,.34), 12:(.36,.34),
                      13:(.7,.52), 14:(.28,.52), 15:(.62,.72), 16:(.38,.72), 23:(.58,.84), 24:(.4,.84)}.items():
        pose[i] = SimpleNamespace(x=x, y=y, visibility=.99)
    fingers = [SimpleNamespace(x=.62, y=.72) for _ in range(21)]
    for i, (x, y) in enumerate(((.62,.72), (.59,.69), (.56,.65), (.54,.61), (.52,.58),
                               (.61,.6), (.6,.54), (.59,.49), (.58,.44), (.64,.59), (.64,.52),
                               (.64,.46), (.64,.41), (.67,.6), (.68,.54), (.69,.49), (.7,.45),
                               (.7,.63), (.72,.58), (.74,.54), (.75,.51))):
        fingers[i] = SimpleNamespace(x=x, y=y)
    return pose if body else None, fingers if hand else None
