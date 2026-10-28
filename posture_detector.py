"""Landmark geometry and personal-baseline posture classification."""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Sequence

import numpy as np


# MediaPipe Pose landmark indices. Keeping these here makes the geometry testable
# without importing MediaPipe or opening a webcam.
NOSE = 0
LEFT_EAR, RIGHT_EAR = 7, 8
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_ELBOW, RIGHT_ELBOW = 13, 14
LEFT_HIP, RIGHT_HIP = 23, 24


@dataclass(frozen=True)
class Measurements:
    view: str
    torso_angle: float  # degrees from image vertical, signed
    shoulder_angle: float  # degrees from image horizontal, signed
    head_forward: float | None  # ear ahead of shoulder / torso length
    head_tilt: float | None = None  # ear-line angle from horizontal, front view
    head_turn: float | None = None  # nose offset from ear midpoint / ear gap
    shoulder_clearance: float | None = None  # ear-to-shoulder gap / torso length
    elbow_spread: float | None = None  # elbow-to-shoulder horizontal gap / torso length
    face_width: float | None = None  # ear separation / image width
    body_center: tuple[float, float] | None = None  # normalized torso center


@dataclass(frozen=True)
class Assessment:
    status: str  # Good, Poor, or Not Detected
    score: int | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Thresholds:
    torso_degrees: float = 12.0
    shoulder_degrees: float = 8.0
    head_forward_ratio: float = 0.18
    head_tilt_degrees: float = 10.0
    head_turn_ratio: float = 0.18
    shoulder_elevation_ratio: float = 0.12
    elbow_spread_ratio: float = 0.25
    face_scale_ratio: float = 1.30


def _visible(landmark: object, minimum: float) -> bool:
    return (
        landmark is not None
        and float(getattr(landmark, "visibility", 1.0)) >= minimum
        and math.isfinite(float(landmark.x))
        and math.isfinite(float(landmark.y))
        and -0.1 <= float(landmark.x) <= 1.1
        and -0.1 <= float(landmark.y) <= 1.1
    )


def _point(landmark: object, width: int, height: int) -> np.ndarray:
    return np.array((landmark.x * width, landmark.y * height), dtype=float)


class PostureDetector:
    def __init__(
        self,
        view: str = "auto",
        visibility: float = 0.55,
        thresholds: Thresholds | None = None,
    ) -> None:
        if view not in {"auto", "front", "side"}:
            raise ValueError("view must be auto, front, or side")
        self.view = view
        self.visibility = visibility
        self.thresholds = thresholds or Thresholds()
        self.baseline: Measurements | None = None

    def measure(
        self, landmarks: Sequence[object] | None, width: int, height: int
    ) -> Measurements | None:
        if landmarks is None or len(landmarks) <= RIGHT_HIP or width <= 0 or height <= 0:
            return None

        def valid(index: int) -> bool:
            return _visible(landmarks[index], self.visibility)

        def point(index: int) -> np.ndarray:
            return _point(landmarks[index], width, height)

        sides = ((LEFT_SHOULDER, LEFT_HIP, LEFT_EAR), (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_EAR))
        available = [side for side in sides if valid(side[0]) and valid(side[1])]
        if not available:
            return None

        both = len(available) == 2
        if self.view == "front" and not both:
            return None
        if self.view == "auto":
            if both:
                shoulder_gap = np.linalg.norm(point(LEFT_SHOULDER) - point(RIGHT_SHOULDER))
                torso_length = np.mean(
                    [np.linalg.norm(point(s) - point(h)) for s, h, _ in sides]
                )
                mode = "front" if shoulder_gap / max(torso_length, 1.0) >= 0.55 else "side"
            else:
                mode = "side"
        else:
            mode = self.view

        if mode == "front":
            shoulder = (point(LEFT_SHOULDER) + point(RIGHT_SHOULDER)) / 2
            hip = (point(LEFT_HIP) + point(RIGHT_HIP)) / 2
            shoulder_line = point(RIGHT_SHOULDER) - point(LEFT_SHOULDER)
            if abs(shoulder_line[0]) < 5:
                return None
            shoulder_angle = math.degrees(math.atan2(shoulder_line[1], shoulder_line[0]))
            # Handle mirrored / reversed shoulder ordering equivalently.
            shoulder_angle = ((shoulder_angle + 90) % 180) - 90
            head_forward = None
            torso_length = np.linalg.norm(shoulder - hip)
            body_center = ((shoulder[0] + hip[0]) / (2 * width),
                           (shoulder[1] + hip[1]) / (2 * height))
            head_tilt = head_turn = shoulder_clearance = elbow_spread = face_width = None
            if valid(LEFT_EAR) and valid(RIGHT_EAR):
                ears = point(RIGHT_EAR) - point(LEFT_EAR)
                if abs(ears[0]) >= 8:
                    head_tilt = math.degrees(math.atan2(ears[1], ears[0]))
                    head_tilt = ((head_tilt + 90) % 180) - 90
                    face_width = np.linalg.norm(ears) / width
                    if valid(NOSE):
                        nose_offset = point(NOSE)[0] - (point(LEFT_EAR)[0] + point(RIGHT_EAR)[0]) / 2
                        head_turn = nose_offset / abs(ears[0])
                shoulder_clearance = np.mean([
                    (point(s)[1] - point(e)[1]) / max(torso_length, 1.0)
                    for s, e in ((LEFT_SHOULDER, LEFT_EAR), (RIGHT_SHOULDER, RIGHT_EAR))
                ])
            if valid(LEFT_ELBOW) and valid(RIGHT_ELBOW):
                elbow_spread = np.mean([
                    abs(point(e)[0] - point(s)[0]) / max(torso_length, 1.0)
                    for s, e in ((LEFT_SHOULDER, LEFT_ELBOW),
                                 (RIGHT_SHOULDER, RIGHT_ELBOW))
                ])
        else:
            # Prefer the side whose shoulder and hip have the highest visibility.
            s, h, e = max(
                available,
                key=lambda side: min(
                    float(getattr(landmarks[side[0]], "visibility", 1.0)),
                    float(getattr(landmarks[side[1]], "visibility", 1.0)),
                ),
            )
            shoulder, hip = point(s), point(h)
            shoulder_angle = 0.0
            head_forward = None
            head_tilt = head_turn = shoulder_clearance = elbow_spread = face_width = None
            body_center = ((shoulder[0] + hip[0]) / (2 * width),
                           (shoulder[1] + hip[1]) / (2 * height))
            if valid(e) and valid(NOSE):
                # Nose determines which image direction is forward. If ambiguous,
                # skip the head metric instead of guessing.
                forward = point(NOSE)[0] - shoulder[0]
                if abs(forward) >= 0.08 * np.linalg.norm(shoulder - hip):
                    sign = math.copysign(1, forward)
                    head_forward = sign * (point(e)[0] - shoulder[0]) / max(
                        np.linalg.norm(shoulder - hip), 1.0
                    )

        torso = shoulder - hip
        length = np.linalg.norm(torso)
        if length < 35 or hip[1] - shoulder[1] < 20:
            return None
        torso_angle = math.degrees(math.atan2(torso[0], -torso[1]))
        return Measurements(mode, torso_angle, shoulder_angle, head_forward,
                            head_tilt, head_turn, shoulder_clearance,
                            elbow_spread, face_width, body_center)

    def calibrate(self, samples: Sequence[Measurements]) -> bool:
        if not samples:
            return False
        mode = samples[0].view
        if any(sample.view != mode for sample in samples):
            return False
        heads = [s.head_forward for s in samples if s.head_forward is not None]
        def median_optional(name: str) -> float | None:
            values = [getattr(sample, name) for sample in samples
                      if getattr(sample, name) is not None]
            return statistics.median(values) if values else None

        centers = [s.body_center for s in samples if s.body_center is not None]
        self.baseline = Measurements(
            mode,
            statistics.median(s.torso_angle for s in samples),
            statistics.median(s.shoulder_angle for s in samples),
            statistics.median(heads) if heads else None,
            median_optional("head_tilt"),
            median_optional("head_turn"),
            median_optional("shoulder_clearance"),
            median_optional("elbow_spread"),
            median_optional("face_width"),
            (statistics.median(c[0] for c in centers),
             statistics.median(c[1] for c in centers)) if centers else None,
        )
        return True

    def assess(self, current: Measurements | None) -> Assessment:
        baseline = self.baseline
        if current is None or baseline is None or current.view != baseline.view:
            return Assessment("Not Detected", None)

        t = self.thresholds
        deviations = {
            "Torso lean": abs(current.torso_angle - baseline.torso_angle) / t.torso_degrees
        }
        if current.view == "front":
            deviations["Shoulder tilt"] = (
                abs(current.shoulder_angle - baseline.shoulder_angle) / t.shoulder_degrees
            )
            if current.head_tilt is not None and baseline.head_tilt is not None:
                deviations["Head tilt"] = abs(current.head_tilt - baseline.head_tilt) / t.head_tilt_degrees
            if current.head_turn is not None and baseline.head_turn is not None:
                deviations["Head turn"] = abs(current.head_turn - baseline.head_turn) / t.head_turn_ratio
            if current.shoulder_clearance is not None and baseline.shoulder_clearance is not None:
                deviations["Raised shoulders"] = max(
                    0.0, baseline.shoulder_clearance - current.shoulder_clearance
                ) / t.shoulder_elevation_ratio
            if current.elbow_spread is not None and baseline.elbow_spread is not None:
                deviations["Elbows away from body"] = max(
                    0.0, current.elbow_spread - baseline.elbow_spread
                ) / t.elbow_spread_ratio
            if current.face_width is not None and baseline.face_width:
                deviations["Closer to camera"] = max(
                    0.0, current.face_width / baseline.face_width - 1.0
                ) / (t.face_scale_ratio - 1.0)
        elif current.head_forward is not None and baseline.head_forward is not None:
            deviations["Forward head"] = max(
                0.0, current.head_forward - baseline.head_forward
            ) / t.head_forward_ratio

        reasons = tuple(name for name, ratio in deviations.items() if ratio >= 1.0)
        # A simple relative score; 100 is the calibrated pose and 0 is a large deviation.
        score = int(round(max(0.0, 100.0 - 50.0 * max(deviations.values()))))
        return Assessment("Poor" if reasons else "Good", score, reasons)
