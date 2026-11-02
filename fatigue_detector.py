"""Local, heuristic tiredness cues from the existing Face Mesh eye tracker."""
from collections import deque
from dataclasses import dataclass

from eye_detector import EyeAssessment


BREAK_GUIDANCE = "You may be tired. Take a 2-minute break and look away from the screen."


@dataclass(frozen=True)
class FatigueAssessment:
    status: str = "Unavailable"
    warning: bool = False
    reasons: tuple[str, ...] = ()
    guidance: str = "Keep your eyes visible to the front camera."
    slow_closures: int = 0


class FatigueMonitor:
    """Detect prolonged/frequent closure and three slow closures in 60 seconds.

    Thresholds are comfort-reminder heuristics, not validated fatigue estimates.
    A brief reminder hold allows users to read it after reopening their eyes.
    Missing tracking clears all evidence rather than interpreting gaps as closure.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.last_seen = None
        self.previous_closed = 0.0
        self.slow_closures = deque()
        self.remind_until = 0.0
        self.reasons = ()

    def update(self, eye: EyeAssessment, now: float) -> FatigueAssessment:
        if eye.openness is None:
            self.reset()
            return FatigueAssessment()
        if self.last_seen is not None and not 0 <= now - self.last_seen <= .75:
            self.reset()
        elapsed = now - self.last_seen if self.last_seen is not None else 0.0
        self.last_seen = now
        # Count completed closures, once each; normal short blinks are excluded.
        if self.previous_closed > 0 and self.previous_closed + elapsed >= .5 and eye.closed_seconds == 0:
            self.slow_closures.append(now)
        self.previous_closed = eye.closed_seconds
        while self.slow_closures and self.slow_closures[0] < now - 60:
            self.slow_closures.popleft()
        reasons = []
        if eye.closed_seconds >= 1.5:
            reasons.append("Prolonged eye closure")
        if "Eyes closed often" in eye.reasons:
            reasons.append("Frequent eye closure")
        if len(self.slow_closures) >= 3:
            reasons.append("Repeated slow eye closures")
        if reasons:
            self.reasons = tuple(reasons)
            self.remind_until = now + 15
        if now < self.remind_until:
            return FatigueAssessment("Possible tiredness", True, self.reasons,
                                     BREAK_GUIDANCE, len(self.slow_closures))
        return FatigueAssessment("Observing eye patterns", slow_closures=len(self.slow_closures),
                                 guidance="No tiredness cues detected. Take regular breaks when you need them.")
