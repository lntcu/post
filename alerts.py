"""Time sustained poor posture without accumulating invisible or good frames."""

from __future__ import annotations


class AlertTimer:
    def __init__(self, delay_seconds: float = 5.0) -> None:
        if delay_seconds <= 0:
            raise ValueError("delay_seconds must be positive")
        self.delay_seconds = delay_seconds
        self.poor_since: float | None = None
        self.warning = False

    def reset(self) -> None:
        self.poor_since = None
        self.warning = False

    def update(self, status: str, now: float) -> tuple[bool, float]:
        """Return (warning active, consecutive poor seconds)."""
        if status != "Poor":
            self.reset()
            return False, 0.0
        if self.poor_since is None or now < self.poor_since:
            self.poor_since = now
        elapsed = now - self.poor_since
        self.warning = elapsed >= self.delay_seconds
        return self.warning, elapsed
