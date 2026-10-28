"""Minimal mouse-driven control window using the app's existing OpenCV dependency."""

import cv2
import numpy as np


class ControlWindow:
    NAME = "Posture Monitor — Controls"

    def __init__(self, settings):
        self.camera = settings["camera"]
        self.view = settings["view"]
        self.delay = settings["alert_seconds"]
        self.notifications = settings["notifications"]
        self.paused = False
        self.action = None
        self.status = "Starting camera"
        self.detail = ""
        self.buttons = []
        cv2.namedWindow(self.NAME, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(self.NAME, self._click)
        self.draw()

    def _click(self, event, x, y, flags, userdata):
        if event != cv2.EVENT_LBUTTONUP:
            return
        for x1, y1, x2, y2, action in self.buttons:
            if x1 <= x <= x2 and y1 <= y <= y2:
                if action == "pause":
                    self.paused = not self.paused
                    self.action = "pause" if self.paused else "resume"
                elif action == "camera":
                    self.camera = (self.camera + 1) % 6
                    self.action = action
                elif action == "view":
                    choices = ("auto", "front", "side")
                    self.view = choices[(choices.index(self.view) + 1) % 3]
                    self.action = action
                elif action == "delay":
                    choices = (3.0, 5.0, 10.0, 15.0)
                    self.delay = choices[(choices.index(self.delay) + 1) % 4] if self.delay in choices else 5.0
                    self.action = action
                elif action == "notifications":
                    self.notifications = not self.notifications
                    self.action = action
                else:
                    self.action = action
                self.draw()
                return

    def poll(self):
        try:
            if cv2.getWindowProperty(self.NAME, cv2.WND_PROP_VISIBLE) < 1:
                return "quit"
        except cv2.error:
            return "quit"
        action, self.action = self.action, None
        return action

    def show_error(self, message):
        self.status = "Camera unavailable"
        self.detail = message
        self.draw()

    def show_status(self, snap, side=None):
        if self.paused:
            self.status = "Paused"
            self.detail = "Select Resume to continue."
        elif snap.phase == "positioning":
            self.status = "Set up camera"
            self.detail = snap.calibration_hint
        elif snap.phase == "calibrating":
            self.status = "Calibrating"
            self.detail = f"Hold upright for {snap.calibration_remaining:.0f} more seconds."
        elif snap.assessment.status == "Not Detected":
            self.status = "Body not tracked"
            self.detail = "Show your face and shoulders to the camera."
        else:
            self.status = f"Posture: {snap.assessment.status}"
            self.detail = ("Eyes not tracked" if snap.eye.status == "Not Detected"
                           else f"Eyes: {snap.eye.status}")
            if side and side.source == "phone disconnected":
                self.detail += " | Side camera disconnected"
        self.draw()

    def draw(self):
        image = np.full((345, 390, 3), (248, 248, 246), dtype=np.uint8)
        ink = (40, 40, 40)
        muted = (110, 110, 110)
        cv2.putText(image, "POSTURE MONITOR", (16, 27), cv2.FONT_HERSHEY_SIMPLEX, .48, muted, 1, cv2.LINE_AA)
        cv2.putText(image, self.status[:30], (16, 62), cv2.FONT_HERSHEY_SIMPLEX, .72, ink, 2, cv2.LINE_AA)
        cv2.putText(image, self.detail[:47], (16, 85), cv2.FONT_HERSHEY_SIMPLEX, .42, muted, 1, cv2.LINE_AA)
        self.buttons = []

        def button(label, box, action, filled=False):
            x1, y1, x2, y2 = box
            cv2.rectangle(image, (x1, y1), (x2, y2), (55, 55, 55) if filled else (220, 220, 218), -1 if filled else 1)
            cv2.putText(image, label, (x1 + 10, y1 + 23), cv2.FONT_HERSHEY_SIMPLEX, .46,
                        (255, 255, 255) if filled else ink, 1, cv2.LINE_AA)
            self.buttons.append((x1, y1, x2, y2, action))

        button("Resume" if self.paused else "Pause", (16, 108, 115, 143), "pause", True)
        button("Recalibrate", (123, 108, 265, 143), "recalibrate")
        button("Quit", (273, 108, 374, 143), "quit")
        button(f"Camera  {self.camera}  >", (16, 166, 188, 204), "camera")
        button(f"View  {self.view}  >", (202, 166, 374, 204), "view")
        button(f"Alert after  {self.delay:g}s  >", (16, 216, 188, 254), "delay")
        button("Notifications  " + ("on" if self.notifications else "off"),
               (202, 216, 374, 254), "notifications")
        button("Snooze alerts for 10 min", (16, 270, 374, 308), "snooze")
        cv2.putText(image, "Camera preview opens separately", (16, 331),
                    cv2.FONT_HERSHEY_SIMPLEX, .4, muted, 1, cv2.LINE_AA)
        cv2.imshow(self.NAME, image)

    def close(self):
        try:
            cv2.destroyWindow(self.NAME)
        except cv2.error:
            pass
