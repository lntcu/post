"""Track sustained low movement from visible upper-body pose measurements."""

from __future__ import annotations

from dataclasses import dataclass
import math

from posture_detector import Measurements


@dataclass(frozen=True)
class ActivityAssessment:
    still_seconds: float = 0.0
    warning: bool = False
    tracked: bool = False


class ActivityMonitor:
    def __init__(self, reminder_seconds: float = 20 * 60,
                 movement_ratio: float = 0.04) -> None:
        self.reminder_seconds = reminder_seconds
        self.movement_ratio = movement_ratio
        self.reset()

    def reset(self) -> None:
        self.anchor: Measurements | None = None
        self.still_since: float | None = None
        self.last_seen: float | None = None

    def update(self, measured: Measurements | None, now: float) -> ActivityAssessment:
        if measured is None or measured.body_center is None:
            if self.last_seen is None or now - self.last_seen > 2.0:
                self.reset()
            return ActivityAssessment()
        if self.last_seen is not None and (now < self.last_seen or now - self.last_seen > 2.0):
            self.reset()
        self.last_seen = now
        if self.anchor is None or self.anchor.view != measured.view:
            self.anchor = measured
            self.still_since = now
        else:
            anchor = self.anchor
            moved = math.dist(anchor.body_center, measured.body_center) >= self.movement_ratio
            moved |= abs(anchor.torso_angle - measured.torso_angle) >= 8.0
            if anchor.head_tilt is not None and measured.head_tilt is not None:
                moved |= abs(anchor.head_tilt - measured.head_tilt) >= 10.0
            if anchor.head_forward is not None and measured.head_forward is not None:
                moved |= abs(anchor.head_forward - measured.head_forward) >= 0.12
            if moved:
                self.anchor = measured
                self.still_since = now
        elapsed = max(0.0, now - self.still_since)
        return ActivityAssessment(elapsed, elapsed >= self.reminder_seconds, True)
