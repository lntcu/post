"""Eye measurements and simple attention cues from MediaPipe Face Mesh."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Sequence

# Corners, paired upper lid points, then paired lower lid points.
LEFT_EYE = (33, 133, 160, 158, 144, 153)
RIGHT_EYE = (362, 263, 385, 387, 380, 373)


@dataclass(frozen=True)
class EyeMeasurements:
    left_ratio: float | None
    right_ratio: float | None

    @property
    def openness(self) -> float:
        available = [ratio for ratio in (self.left_ratio, self.right_ratio) if ratio is not None]
        return sum(available) / len(available)


@dataclass(frozen=True)
class EyeAssessment:
    status: str
    openness: float | None = None
    blinks_per_minute: float | None = None
    closed_seconds: float = 0.0
    warning: str | None = None
    left_ratio: float | None = None
    right_ratio: float | None = None
    open_baseline: float | None = None
    closed_threshold: float | None = None
    blink_count: int = 0
    closed_fraction: float | None = None
    since_blink: float = 0.0
    reasons: tuple[str, ...] = ()


def measure_eyes(landmarks: Sequence[object] | None, width: int,
                 height: int) -> EyeMeasurements | None:
    """Return eye aspect ratios in image pixels when at least one eye is trackable."""
    if landmarks is None or len(landmarks) <= max(RIGHT_EYE) or width <= 0 or height <= 0:
        return None

    def ratio(indices: tuple[int, ...]) -> float | None:
        points = []
        for index in indices:
            mark = landmarks[index]
            x, y = float(mark.x), float(mark.y)
            if not (math.isfinite(x) and math.isfinite(y) and
                    -0.1 <= x <= 1.1 and -0.1 <= y <= 1.1):
                return None
            points.append((x * width, y * height))

        def distance(a: int, b: int) -> float:
            return math.dist(points[a], points[b])

        span = distance(0, 1)
        if span < 5:
            return None
        return (distance(2, 4) + distance(3, 5)) / (2 * span)

    left, right = ratio(LEFT_EYE), ratio(RIGHT_EYE)
    return EyeMeasurements(left, right) if left is not None or right is not None else None


def eye_openness(landmarks: Sequence[object] | None, width: int,
                 height: int) -> float | None:
    """Backward compatible average eye ratio helper."""
    measured = measure_eyes(landmarks, width, height)
    return measured.openness if measured else None


class EyeMonitor:
    """Track blinks and sustained closure with a recent personal open-eye level."""

    def __init__(self, low_blinks_per_minute: float = 6.0,
                 prolonged_closure_seconds: float = 1.5) -> None:
        self.low_blinks_per_minute = low_blinks_per_minute
        self.prolonged_closure_seconds = prolonged_closure_seconds
        self.reset()

    def reset(self) -> None:
        self.observed_since: float | None = None
        self.last_seen: float | None = None
        self.closed_since: float | None = None
        self.last_blink: float | None = None
        self.is_closed = False
        self.blinks: deque[float] = deque()
        self.open_samples: deque[tuple[float, float]] = deque()
        self.closure_samples: deque[tuple[float, bool]] = deque()

    def update(self, measured: EyeMeasurements | float | None, now: float) -> EyeAssessment:
        if measured is None:
            if self.last_seen is None or now - self.last_seen > 0.75:
                self.reset()
            else:
                # Keep the rolling blink history through a brief tracking miss,
                # but never bridge a closure across frames we could not inspect.
                self.is_closed = False
                self.closed_since = None
                self.closure_samples.append((now, False))
            return EyeAssessment("Not Detected")
        if isinstance(measured, (float, int)):
            measured = EyeMeasurements(float(measured), float(measured))
        openness = measured.openness
        if not math.isfinite(openness):
            self.reset()
            return EyeAssessment("Not Detected")
        if self.last_seen is not None and (now < self.last_seen or now - self.last_seen > 0.75):
            self.reset()  # A gap cannot be interpreted as a blink.
        if self.observed_since is None:
            self.observed_since = now
        self.last_seen = now

        while self.open_samples and self.open_samples[0][0] < now - 30:
            self.open_samples.popleft()
        reference = max(value for _, value in self.open_samples) if self.open_samples else None
        # Closed frames must not drag the open-eye reference downward.
        if reference is None or openness >= reference * 0.8:
            self.open_samples.append((now, openness))
        recent = sorted(value for _, value in self.open_samples)
        baseline = max(recent) if len(recent) < 10 else recent[int(0.9 * (len(recent) - 1))]
        threshold = max(0.07, min(0.28, baseline * 0.72))

        if not self.is_closed and openness < threshold:
            self.is_closed = True
            self.closed_since = now
        elif self.is_closed and openness > threshold * 1.08:
            duration = now - self.closed_since
            if 0.02 <= duration <= 0.8:
                self.blinks.append(now)
                self.last_blink = now
            self.is_closed = False
            self.closed_since = None

        self.closure_samples.append((now, self.is_closed))
        while self.closure_samples and self.closure_samples[0][0] < now - 30:
            self.closure_samples.popleft()
        while self.blinks and self.blinks[0] < now - 60:
            self.blinks.popleft()
        observed = now - self.observed_since
        window = min(60.0, observed)
        count = len(self.blinks)
        rate = 60 * count / window if window >= 5 else None
        closed_fraction = None
        if observed >= 10 and len(self.closure_samples) >= 2:
            samples = list(self.closure_samples)
            covered = samples[-1][0] - samples[0][0]
            if covered > 0:
                closed_time = sum((end[0] - start[0]) for start, end in
                                  zip(samples, samples[1:]) if start[1])
                closed_fraction = closed_time / covered
        closed_seconds = now - self.closed_since if self.closed_since is not None else 0.0
        since_blink = now - (self.last_blink if self.last_blink is not None else self.observed_since)

        reasons = []
        if closed_seconds >= self.prolonged_closure_seconds:
            reasons.append("Prolonged closure")
        if observed >= 20 and closed_fraction is not None and closed_fraction >= 0.25:
            reasons.append("Eyes closed often")
        if observed >= 30 and rate is not None and rate < self.low_blinks_per_minute:
            reasons.append("Low blink rate")
        if observed >= 20 and since_blink >= 20 and not self.is_closed:
            reasons.append("Long time without a blink")

        fatigue = any(reason in reasons for reason in ("Prolonged closure", "Eyes closed often"))
        status = "Possible fatigue" if fatigue else "Possible strain" if reasons else "Tracking"
        warning = ("Rest your eyes if tired" if fatigue else
                   "Blink and look away" if reasons else None)
        return EyeAssessment(status, openness, rate, closed_seconds, warning,
                             measured.left_ratio, measured.right_ratio, baseline,
                             threshold, count, closed_fraction, since_blink, tuple(reasons))
