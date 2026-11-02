"""Single-camera pen observation using blue tip-side and green rear markers.

Markers define the visible shaft, not the physical tip or contact with paper.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PenObservation:
    tip_side: tuple[float, float]
    rear: tuple[float, float]


def detect_pen(frame, hand):
    if hand is None:
        return None
    import cv2
    import numpy as np
    height, width = frame.shape[:2]
    palm = math.dist((hand[5].x * width, hand[5].y * height),
                     (hand[17].x * width, hand[17].y * height))
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    centers = []
    for low, high in (((95, 100, 60), (130, 255, 255)), ((40, 90, 60), (85, 255, 255))):
        mask = cv2.inRange(hsv, np.array(low, np.uint8), np.array(high, np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            if area < 6 or area > max(50, palm * palm * .35) or perimeter <= 0:
                continue
            if 4 * math.pi * area / perimeter ** 2 < .25:
                continue
            moments = cv2.moments(contour)
            center = (moments['m10'] / moments['m00'], moments['m01'] / moments['m00'])
            if min(math.dist(center, (p.x * width, p.y * height)) for p in hand) <= palm * 3:
                candidates.append(center)
        centers.append(candidates)
    pairs = [(a, b) for a in centers[0] for b in centers[1] if palm * .35 < math.dist(a, b) < palm * 5]
    # Ambiguous colored objects cannot identify a particular pen.
    if len(pairs) != 1:
        return None
    return PenObservation(*pairs[0])


def pen_features(pen, points, palm):
    if pen is None:
        return {}
    a, b = pen.tip_side, pen.rear
    axis = (b[0] - a[0], b[1] - a[1])
    length = math.hypot(*axis)
    hand = (points[9][0] - points[0][0], points[9][1] - points[0][1])
    norm = math.hypot(*hand) * length
    if length < 1 or norm < 1 or palm <= 0:
        return {}
    angle = math.degrees(math.acos(max(-1., min(1., sum(x*y for x, y in zip(axis, hand)) / norm))))
    result = {'pen_angle': angle}
    for name, index in (('thumb', 4), ('index', 8), ('middle', 12)):
        offset = (points[index][0] - a[0], points[index][1] - a[1])
        result[f'pen_{name}_distance'] = abs(axis[0] * offset[1] - axis[1] * offset[0]) / length / palm
    # Signed position along the shaft from the blue marker, not distance to nib.
    pinch = tuple((points[4][i] + points[8][i]) / 2 - a[i] for i in range(2))
    result['pen_hold_position'] = sum(x*y for x, y in zip(pinch, axis)) / length / palm
    return result
