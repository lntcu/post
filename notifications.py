"""macOS notifications for posture, eye, activity, and camera warnings."""

from __future__ import annotations

import subprocess
import sys
import time


class MacNotifier:
    def __init__(self, enabled: bool = True, repeat_seconds: float = 60.0) -> None:
        self.enabled = enabled and sys.platform == "darwin"
        self.repeat_seconds = repeat_seconds
        self.active: set[str] = set()
        self.last_sent: dict[str, float] = {}
        self.lost_since: dict[str, float] = {}
        self.snoozed_until = 0.0

    def snooze(self, seconds: float) -> None:
        self.snoozed_until = time.monotonic() + seconds
        self.active.clear()

    def is_snoozed(self, now: float) -> bool:
        return now < self.snoozed_until

    def update(self, front, side=None, now: float | None = None) -> None:
        """Report distinct issues once, with a cooldown if they briefly flicker."""
        now = time.monotonic() if now is None else now
        events: dict[str, str] = {}
        posture: list[str] = []

        for label, snap in (("Front", front), ("Side", side)):
            if snap is None:
                continue
            if snap.phase == "monitoring" and snap.warning:
                posture.extend(f"{label}: {reason}" for reason in snap.assessment.reasons)
            lost = snap.phase == "monitoring" and snap.assessment.status == "Not Detected"
            if lost:
                since = self.lost_since.setdefault(label, now)
                if now - since >= 3.0:
                    events[f"{label}:tracking"] = f"{label} camera lost posture tracking. Reposition the camera."
            else:
                self.lost_since.pop(label, None)

        if posture:
            events["posture"] = "Adjust posture: " + "; ".join(posture[:3]) + ("; more in preview" if len(posture) > 3 else "") + "."

        if side is not None and side.source == "phone disconnected":
            events["phone:disconnected"] = "Phone camera disconnected. Check its cable or stream."
        eye_reasons = getattr(front.eye, "reasons", ())
        if eye_reasons:
            events["eyes"] = "Eyes: " + "; ".join(eye_reasons[:2]) + ". Blink or rest your eyes."
        elif front.eye.warning:
            events["eyes"] = f"Eyes: {front.eye.warning}."
        if front.activity.warning:
            events["stillness"] = "Change position or take a short break."

        if self.is_snoozed(now):
            self.active.clear()
            return
        if self.enabled:
            for key, message in events.items():
                if key not in self.active and now - self.last_sent.get(key, float("-inf")) >= self.repeat_seconds:
                    self._send(message)
                    self.last_sent[key] = now
        self.active = set(events)

    @staticmethod
    def _send(message: str) -> None:
        # Use an argument list, and escape the AppleScript string literal.
        safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
        script = f'display notification "{safe_message}" with title "Posture Monitor"'
        try:
            subprocess.Popen(["osascript", "-e", script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
