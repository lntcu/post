import unittest
from types import SimpleNamespace
from unittest.mock import patch

from notifications import MacNotifier


def snapshot(*, reasons=(), eye_reasons=(), still=False, lost=False, disconnected=False):
    return SimpleNamespace(
        phase="monitoring",
        source="phone disconnected" if disconnected else "camera",
        warning=bool(reasons),
        assessment=SimpleNamespace(
            status="Not Detected" if lost else "Poor" if reasons else "Good",
            reasons=reasons),
        eye=SimpleNamespace(
            warning="Rest your eyes" if eye_reasons else None,
            reasons=eye_reasons),
        activity=SimpleNamespace(warning=still),
    )


class NotificationTests(unittest.TestCase):
    def test_distinct_issues_notify_with_cooldown(self):
        with patch("notifications.sys.platform", "darwin"):
            notifier = MacNotifier(repeat_seconds=60)
        with patch.object(notifier, "_send") as send:
            notifier.update(snapshot(), now=0)
            send.assert_not_called()
            front = snapshot(reasons=("Torso lean", "Shoulder tilt"),
                             eye_reasons=("Low blink rate",), still=True)
            side = snapshot(reasons=("Forward head",))
            notifier.update(front, side, now=1)
            self.assertEqual(send.call_count, 3)
            notifier.update(front, side, now=2)
            self.assertEqual(send.call_count, 3)
            notifier.update(snapshot(), now=3)
            notifier.update(front, side, now=4)
            self.assertEqual(send.call_count, 3)
            notifier.update(snapshot(), now=65)
            notifier.update(front, side, now=66)
            self.assertEqual(send.call_count, 6)

    def test_snooze_suppresses_and_resumes_alerts(self):
        with patch("notifications.sys.platform", "darwin"):
            notifier = MacNotifier()
        with patch.object(notifier, "_send") as send, patch("notifications.time.monotonic", return_value=10):
            notifier.snooze(600)
            notifier.update(snapshot(reasons=("Torso lean",)), now=100)
            send.assert_not_called()
            notifier.update(snapshot(reasons=("Torso lean",)), now=610)
            send.assert_called_once()

    def test_tracking_loss_and_phone_disconnect_notify(self):
        with patch("notifications.sys.platform", "darwin"):
            notifier = MacNotifier()
        with patch.object(notifier, "_send") as send:
            notifier.update(snapshot(lost=True), snapshot(disconnected=True), now=0)
            self.assertEqual(send.call_count, 1)  # phone disconnect is immediate
            notifier.update(snapshot(lost=True), snapshot(disconnected=True), now=3)
            self.assertEqual(send.call_count, 2)  # tracking loss waits three seconds

    def test_disabled_notifications_send_nothing(self):
        notifier = MacNotifier(enabled=False)
        with patch.object(notifier, "_send") as send:
            notifier.update(snapshot(reasons=("Torso lean",), still=True), now=0)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
