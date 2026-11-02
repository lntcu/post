"""Webcam posture monitor with optional terminal diagnostics."""

from __future__ import annotations

import argparse
import math
import sys
import time

from alerts import AlertTimer
from activity_monitor import ActivityMonitor
from eye_detector import EyeMonitor, measure_eyes
from posture_detector import Assessment, Measurements, PostureDetector
from settings import load_settings, save_settings

CALIBRATION_SECONDS = 5.0
WINDOW_NAME = "Posture + Eye Monitor"
SIDE_WINDOW_NAME = "Phone side view"


def parse_args() -> argparse.Namespace:
    saved = load_settings()
    parser = argparse.ArgumentParser(description="Local webcam posture and eye monitor")
    parser.add_argument("--port", type=int, default=8765, help="Local web dashboard port")
    parser.add_argument("--app", action="store_true", help="Open a dedicated Chrome/Edge app window when available")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    parser.add_argument("--legacy-gui", action="store_true", help="Use the previous OpenCV controls")
    parser.add_argument("--camera", type=int, default=saved["camera"], help="OpenCV camera index")
    side = parser.add_mutually_exclusive_group()
    side.add_argument("--side-camera", type=int, help="Phone exposed as a USB/Continuity webcam camera index")
    side.add_argument("--side-url", help="Phone camera MJPEG/RTSP stream URL on the local network")
    parser.add_argument("--view", choices=("auto", "front", "side"), default=saved["view"])
    parser.add_argument("--alert-seconds", type=float, default=saved["alert_seconds"])
    parser.add_argument("--sound", action="store_true", help="Windows beep when warning starts")
    parser.add_argument("--no-notifications", action="store_true",
                        help="Disable macOS posture, eye, activity, and camera notifications")
    parser.add_argument("--tui", action="store_true", help="Live terminal measurements")
    parser.add_argument("--no-gui", action="store_true", help="Run with camera preview only")
    parser.add_argument("--demo", action="store_true", help="Camera-free simulation in the dashboard or terminal")
    args = parser.parse_args()
    if not math.isfinite(args.alert_seconds) or args.alert_seconds <= 0:
        parser.error("--alert-seconds must be positive")
    if args.side_camera is not None and args.side_camera == args.camera:
        parser.error("--side-camera must differ from --camera")
    if args.side_url and not args.side_url.startswith(("http://", "https://", "rtsp://")):
        parser.error("--side-url must be an http(s) or rtsp stream URL")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be 0–65535")
    if args.demo and (args.legacy_gui or args.no_gui):
        parser.error("--demo uses the web dashboard or --tui")
    if args.tui and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("--tui requires an interactive terminal")
    args.notifications = saved["notifications"] and not args.no_notifications
    return args


def maybe_beep(enabled: bool) -> None:
    if enabled and sys.platform == "win32":
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except RuntimeError:
            pass


class Monitor:
    """Calibration and alert state shared by webcam and demo paths."""

    def __init__(self, view: str, alert_seconds: float, calibration_seconds: float = CALIBRATION_SECONDS) -> None:
        self.calibration_seconds = calibration_seconds
        self.detector = PostureDetector(view=view)
        self.alert = AlertTimer(alert_seconds)
        self.eyes = EyeMonitor()
        self.activity = ActivityMonitor()
        self.samples: list[Measurements] = []
        self.calibration_start: float | None = None
        self.calibration_view: str | None = None

    def reset(self) -> None:
        self.detector.baseline = None
        self.samples.clear()
        self.calibration_start = None
        self.calibration_view = None
        self.alert.reset()
        self.eyes.reset()
        self.activity.reset()

    def update(self, measured: Measurements | None, now: float, fps: float,
               landmarks: dict[str, float | None], source: str,
               openness: float | None = None):
        from debug_tui import DebugSnapshot

        eye = self.eyes.update(openness, now)
        activity = self.activity.update(measured, now)

        hint = calibration_instruction(measured, self.detector.view)
        if self.detector.baseline is None:
            self.alert.reset()
            if not hint and self.samples and measured is not None:
                first = self.samples[0]
                moved = (measured.torso_angle is not None and first.torso_angle is not None
                         and abs(measured.torso_angle - first.torso_angle) > 8.0)
                if measured.body_center and first.body_center:
                    moved |= math.dist(measured.body_center, first.body_center) > 0.05
                if moved:
                    hint = "Hold still in your comfortable upright position."
            if hint or (self.calibration_view and measured.view != self.calibration_view):
                self.samples.clear()
                self.calibration_start = None
                self.calibration_view = None
            else:
                if self.calibration_start is None:
                    self.calibration_start = now
                    self.calibration_view = measured.view
                self.samples.append(measured)
                if now - self.calibration_start >= self.calibration_seconds:
                    self.detector.calibrate(self.samples)
                    self.samples.clear()
            remaining = (max(0.0, self.calibration_seconds - (now - self.calibration_start))
                         if self.calibration_start is not None else self.calibration_seconds)
            return DebugSnapshot("calibrating" if not hint else "positioning",
                                 Assessment("Calibrating" if not hint else "Not Detected", None),
                                 measured, remaining,
                                 0.0, False, fps, landmarks, source, eye, activity, hint)
        assessment = self.detector.assess(measured)
        warning, elapsed = self.alert.update(assessment.status, now)
        return DebugSnapshot("monitoring", assessment, measured, 0.0,
                             elapsed, warning, fps, landmarks, source, eye, activity)


def calibration_instruction(measured: Measurements | None, view: str) -> str:
    """Give framing feedback before accepting an upright baseline."""
    if measured is None:
        return ("Show your ear, nose, and shoulder side-on to the phone."
                if view == "side" else "Show your face and both shoulders to the camera.")
    if view == "side" and measured.head_forward is None:
        return "Turn side-on so your ear and nose are visible."
    if measured.torso_scale is not None:
        minimum, maximum = (0.08, 0.62) if view == "side" else (0.07, 0.45)
        if measured.torso_scale < minimum:
            return ("Move the phone closer; your upper body is too small."
                    if view == "side" else "Move closer so your head and shoulders are clear.")
        if measured.torso_scale > maximum:
            return ("Move the phone back slightly so your ear and shoulder fit."
                    if view == "side" else "Move back slightly so your head and shoulders fit.")
    if measured.body_center is not None:
        x, y = measured.body_center
        if x < 0.28:
            return "Move toward the right side of the picture."
        if x > 0.72:
            return "Move toward the left side of the picture."
        if y < (0.15 if view == "side" else 0.12):
            return "Lower the camera or sit slightly farther back."
        if y > (0.85 if view == "side" else 0.78):
            return "Raise the camera or sit slightly farther back."
    return ""


def draw_overlay(cv2, frame, snap, monitor: Monitor) -> None:
    """Keep the preview readable while naming problems and next actions."""
    panel = frame.copy()
    width, height = frame.shape[1], frame.shape[0]
    cv2.rectangle(panel, (0, 0), (width, 165), (20, 20, 20), -1)
    cv2.rectangle(panel, (0, height - 38), (width, height), (20, 20, 20), -1)
    cv2.addWeighted(panel, 0.7, frame, 0.3, 0, frame)

    def line(text: str, y: int, color=(245, 245, 245), scale=0.55) -> None:
        if cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] > width - 28:
            while text and cv2.getTextSize(text + "...", cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] > width - 28:
                text = text[:-1]
            text = text.rstrip() + "..."
        cv2.putText(frame, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, 1, cv2.LINE_AA)

    score = snap.assessment.score
    posture = snap.assessment.status
    line(f"Posture: {posture}{f' ({score})' if score is not None else ''}   |   Eyes: {snap.eye.status}", 27)
    line(f"Nearly still: {snap.activity.still_seconds / 60:.1f} min   |   Details in terminal with --tui",
         51, (185, 190, 195), 0.47)
    guidance = preview_guidance(snap)
    for index, (message, urgent) in enumerate(guidance[:3]):
        line(message, 79 + index * 26, (70, 100, 255) if urgent else (0, 210, 255), 0.52)
    if len(guidance) > 3:
        line(f"+{len(guidance) - 3} more issue(s) in terminal dashboard", 157,
             (185, 190, 195), 0.44)
    line("Q quit  |  R recalibrate  |  V switch view", height - 13, (235, 235, 235), 0.47)


POSTURE_GUIDANCE = {
    "Torso lean": "Torso leaning: bring your trunk back over your hips.",
    "Shoulder tilt": "Uneven shoulders: level them and check arm support.",
    "Forward head": "Head forward: bring your ears back above shoulders.",
    "Head tilt": "Head tilted: gently return your head to level.",
    "Head turn": "Head turned: face the screen more directly.",
    "Raised shoulders": "Raised shoulders: lower and relax your shoulders.",
    "Elbows away from body": "Elbows flared: bring them closer to your sides.",
    "Closer to camera": "Leaning closer: move toward your calibrated position.",
}
EYE_GUIDANCE = {
    "Low blink rate": "Blinking infrequently: blink fully and look away.",
    "Long time without a blink": "Long stare: blink and refocus away from the screen.",
    "Prolonged closure": "Eyes closed: pause and rest if you feel tired.",
    "Eyes closed often": "Frequent eye closure: pause and rest your eyes.",
}


def preview_guidance(snap) -> list[tuple[str, bool]]:
    """Prioritize distinct issues for the preview."""
    if snap.phase != "monitoring":
        if snap.calibration_hint:
            return [(snap.calibration_hint, False),
                    ("Hold a comfortable upright position once framed.", False)]
        if snap.measured is None:
            return [("Pose not tracked: show your face and shoulders.", False),
                    ("Keep your face visible for eye measurements.", False)]
        return [(f"Calibrating: sit comfortably upright for {snap.calibration_remaining:.1f}s.", False),
                ("Keep your face and shoulders in view.", False)]

    activity = ([('Long stillness: change position or take a short break.', True)]
                if snap.activity.warning else [])
    posture = [(POSTURE_GUIDANCE.get(reason, reason), snap.warning)
               for reason in snap.assessment.reasons]
    eyes = [(EYE_GUIDANCE.get(reason, reason), True)
            for reason in snap.eye.reasons]
    if snap.assessment.status == "Not Detected":
        posture.append(("Pose not tracked: show your face and shoulders.", False))
    if snap.eye.status == "Not Detected":
        eyes.append(("Eyes not tracked: face the camera in good light.", False))
    guidance = activity + posture[:1] + eyes[:1] + posture[1:] + eyes[1:]
    return guidance or [("Measurements in range: stay comfortable and move often.", False)]


def handle_action(action: str | None, monitor: Monitor,
                  side_monitor: Monitor | None = None) -> bool:
    if action == "quit":
        return True
    if action == "recalibrate":
        monitor.reset()
        if side_monitor is not None:
            side_monitor.reset()
    return False


def draw_side_overlay(cv2, frame, snap) -> None:
    """Show the phone image and its independent posture result."""
    height, width = frame.shape[:2]
    panel = frame.copy()
    cv2.rectangle(panel, (0, 0), (width, 145), (20, 20, 20), -1)
    cv2.rectangle(panel, (0, height - 35), (width, height), (20, 20, 20), -1)
    cv2.addWeighted(panel, 0.7, frame, 0.3, 0, frame)

    def line(message, y, color=(245, 245, 245)):
        while message and cv2.getTextSize(message, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)[0][0] > width - 28:
            message = message[:-1]
        cv2.putText(frame, message, (14, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.52, color, 1, cv2.LINE_AA)

    line(f"PHONE SIDE VIEW | Posture: {snap.assessment.status} | Score: {snap.assessment.score if snap.assessment.score is not None else '--'}", 28)
    if snap.source == "phone disconnected":
        line("Phone disconnected. Check the cable or stream URL; retrying.", 60,
             (0, 210, 255))
    elif snap.phase != "monitoring":
        line(snap.calibration_hint or f"Sit upright and hold still: {snap.calibration_remaining:.1f}s", 60, (0, 210, 255))
        line("Place phone side-on; show ear, nose, and shoulder.", 88)
    else:
        reasons = snap.assessment.reasons
        line(POSTURE_GUIDANCE.get(reasons[0], reasons[0]) if reasons else "Side posture in range.",
             60, (70, 100, 255) if snap.warning else (0, 210, 255))
        if snap.warning:
            line("Correct your side posture.", 88, (70, 100, 255))
    line("Q quit  |  R recalibrate both views", height - 12)


def open_side_capture(cv2, source):
    if isinstance(source, int):
        capture = cv2.VideoCapture(source)
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_ZOOM, 0)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        return capture
    # FFmpeg timeouts keep a lost network phone from freezing the laptop feed.
    return cv2.VideoCapture(source, cv2.CAP_FFMPEG, [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000,
    ])


def run_camera(args: argparse.Namespace, dashboard=None) -> int:
    import cv2
    import mediapipe as mp
    import numpy as np
    from contextlib import ExitStack
    from debug_tui import landmark_visibility
    controls = None
    settings = {"camera": args.camera, "view": args.view,
                "alert_seconds": args.alert_seconds, "notifications": args.notifications}
    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open camera {args.camera}. Check permissions/index.")
    # Request a wide sensor mode, and reset hardware zoom where supported.
    # Drivers may ignore either request; landmark framing guidance remains useful.
    capture.set(cv2.CAP_PROP_ZOOM, 0)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if dashboard is None and not args.no_gui:
        from controls import ControlWindow
        controls = ControlWindow(settings)
    side_source = args.side_camera if args.side_camera is not None else args.side_url
    side_capture = None
    side_monitor = Monitor("side", args.alert_seconds) if side_source is not None else None
    side_snap = None
    last_side_retry = 0.0
    monitor = Monitor(args.view, args.alert_seconds)
    from notifications import MacNotifier
    notifier = MacNotifier(enabled=args.notifications)
    missing_frames = 0
    previous_frame = None
    previous_warning = False
    last_dashboard_draw = 0.0
    pose_api = mp.solutions.pose
    pose_options = dict(static_image_mode=False, model_complexity=1,
                        smooth_landmarks=True, min_detection_confidence=0.6,
                        min_tracking_confidence=0.6)
    try:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        if side_monitor:
            cv2.namedWindow(SIDE_WINDOW_NAME, cv2.WINDOW_NORMAL)
        with ExitStack() as stack:
            pose = stack.enter_context(pose_api.Pose(**pose_options))
            face_mesh = stack.enter_context(mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False, max_num_faces=1, refine_landmarks=False,
                min_detection_confidence=0.6, min_tracking_confidence=0.6))
            side_pose = stack.enter_context(pose_api.Pose(**pose_options)) if side_monitor else None
            while True:
                if controls:
                    action = controls.poll()
                    if action == "quit":
                        break
                    if action == "pause":
                        monitor.reset()
                        if side_monitor:
                            side_monitor.reset()
                        notifier.active.clear()
                    elif action == "resume" or action == "recalibrate":
                        monitor.reset()
                        if side_monitor:
                            side_monitor.reset()
                    elif action == "camera":
                        next_camera = controls.camera
                        candidate = cv2.VideoCapture(next_camera)
                        if candidate.isOpened():
                            capture.release()
                            capture = candidate
                            capture.set(cv2.CAP_PROP_ZOOM, 0)
                            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                            settings["camera"] = next_camera
                            save_settings(settings)
                            monitor.reset()
                        else:
                            candidate.release()
                            controls.camera = settings["camera"]
                            controls.show_error(f"Could not open camera {next_camera}.")
                    elif action == "view":
                        monitor.detector.view = controls.view
                        settings["view"] = controls.view
                        save_settings(settings)
                        monitor.reset()
                    elif action == "delay":
                        seconds = controls.delay
                        monitor.alert.delay_seconds = seconds
                        if side_monitor:
                            side_monitor.alert.delay_seconds = seconds
                        settings["alert_seconds"] = seconds
                        save_settings(settings)
                    elif action == "notifications":
                        notifier.enabled = controls.notifications and sys.platform == "darwin"
                        settings["notifications"] = controls.notifications
                        save_settings(settings)
                    elif action == "snooze":
                        notifier.snooze(10 * 60)
                        controls.detail = "System alerts snoozed for 10 minutes."
                        controls.draw()
                    if controls.paused:
                        controls.show_status(None)
                        cv2.waitKey(1)
                        time.sleep(0.05)
                        continue
                ok, frame = capture.read()
                if not ok:
                    missing_frames += 1
                    monitor.alert.reset()
                    monitor.calibration_start = None
                    monitor.samples.clear()
                    monitor.eyes.reset()
                    monitor.activity.reset()
                    previous_warning = False
                    if missing_frames >= 30:
                        raise RuntimeError("Camera stopped providing frames")
                    time.sleep(0.03)
                    continue
                missing_frames = 0
                frame = cv2.flip(frame, 1)
                height, width = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                pose_rgb = cv2.resize(rgb, (640, 480)) if width > 640 or height > 480 else rgb
                pose_rgb.flags.writeable = False
                result = pose.process(pose_rgb)
                face_result = face_mesh.process(rgb)
                landmarks = result.pose_landmarks.landmark if result.pose_landmarks else None
                face_landmarks = (face_result.multi_face_landmarks[0].landmark
                                  if face_result.multi_face_landmarks else None)
                openness = measure_eyes(face_landmarks, width, height)
                measured = monitor.detector.measure(landmarks, width, height)
                if result.pose_landmarks:
                    mp.solutions.drawing_utils.draw_landmarks(
                        frame, result.pose_landmarks, pose_api.POSE_CONNECTIONS)
                now = time.monotonic()
                fps = 1.0 / (now - previous_frame) if previous_frame is not None and now > previous_frame else 0.0
                previous_frame = now
                snap = monitor.update(measured, now, fps, landmark_visibility(landmarks),
                                      "laptop webcam", openness)

                if side_monitor:
                    if side_capture is None and now - last_side_retry >= 3.0:
                        last_side_retry = now
                        candidate = open_side_capture(cv2, side_source)
                        if candidate.isOpened():
                            side_capture = candidate
                            side_capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                            side_monitor.reset()
                        else:
                            candidate.release()
                    side_ok, side_frame = side_capture.read() if side_capture is not None else (False, None)
                    if side_ok:
                        side_frame = cv2.flip(side_frame, 1)
                        sh, sw = side_frame.shape[:2]
                        side_rgb = cv2.cvtColor(side_frame, cv2.COLOR_BGR2RGB)
                        side_rgb.flags.writeable = False
                        side_small = cv2.resize(side_rgb, (640, 480)) if sw > 640 or sh > 480 else side_rgb
                        side_small.flags.writeable = False
                        side_result = side_pose.process(side_small)
                        side_landmarks = side_result.pose_landmarks.landmark if side_result.pose_landmarks else None
                        side_measured = side_monitor.detector.measure(side_landmarks, sw, sh)
                        if side_result.pose_landmarks:
                            mp.solutions.drawing_utils.draw_landmarks(
                                side_frame, side_result.pose_landmarks, pose_api.POSE_CONNECTIONS)
                        side_snap = side_monitor.update(side_measured, now, fps,
                                                        landmark_visibility(side_landmarks), "phone side camera")
                    else:
                        if side_capture is not None:
                            side_capture.release()
                            side_capture = None
                            side_monitor.reset()
                            last_side_retry = now
                        side_frame = np.zeros((720, 960, 3), dtype=np.uint8)
                        side_snap = side_monitor.update(None, now, 0.0, {}, "phone disconnected")
                    draw_side_overlay(cv2, side_frame, side_snap)
                    cv2.imshow(SIDE_WINDOW_NAME, side_frame)

                notifier.update(snap, side_snap, now)
                active_warning = (snap.warning or bool(snap.eye.warning) or snap.activity.warning
                                  or bool(side_snap and side_snap.warning))
                if active_warning and not previous_warning and not notifier.is_snoozed(now):
                    maybe_beep(args.sound)
                previous_warning = active_warning
                if controls:
                    controls.show_status(snap, side_snap)
                draw_overlay(cv2, frame, snap, monitor)
                cv2.imshow(WINDOW_NAME, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    monitor.reset()
                    if side_monitor:
                        side_monitor.reset()
                if key == ord("v"):
                    choices = ("auto", "front", "side")
                    monitor.detector.view = choices[
                        (choices.index(monitor.detector.view) + 1) % len(choices)]
                    monitor.reset()
                    if controls:
                        controls.view = monitor.detector.view
                        settings["view"] = monitor.detector.view
                        save_settings(settings)
                if dashboard is not None:
                    if now - last_dashboard_draw >= 0.1:
                        dashboard.draw(snap, monitor.detector, monitor.alert,
                                       side_snap, side_monitor.detector if side_monitor else None)
                        last_dashboard_draw = now
                    if handle_action(dashboard.input(monitor.detector, monitor.alert),
                                     monitor, side_monitor):
                        break
    finally:
        capture.release()
        if side_capture is not None:
            side_capture.release()
        if controls:
            controls.close()
        cv2.destroyAllWindows()
    return 0


def demo_measurement(seconds: float, view: str) -> Measurements | None:
    """Repeat baseline -> bad posture -> corrected -> missing landmarks."""
    phase = seconds % 19.0
    mode = "side" if view == "auto" else view
    if phase >= 16.0:
        return None
    if phase < 6.0 or phase >= 13.0:
        return Measurements(mode, 0.0, 0.0, 0.10 if mode == "side" else None,
                            head_tilt=0.0 if mode == "front" else None,
                            head_turn=0.0 if mode == "front" else None,
                            shoulder_clearance=0.38 if mode == "front" else None,
                            elbow_spread=0.30 if mode == "front" else None,
                            face_width=0.12 if mode == "front" else None,
                            body_center=(0.5, 0.5))
    return Measurements(mode, 18.0, 12.0 if mode == "front" else 0.0,
                        0.34 if mode == "side" else None,
                        head_tilt=14.0 if mode == "front" else None,
                        head_turn=0.25 if mode == "front" else None,
                        shoulder_clearance=0.22 if mode == "front" else None,
                        elbow_spread=0.60 if mode == "front" else None,
                        face_width=0.16 if mode == "front" else None,
                        body_center=(0.56, 0.5))


def run_demo(args: argparse.Namespace, dashboard) -> int:
    monitor = Monitor(args.view, args.alert_seconds)
    start = time.monotonic()
    previous = None
    while True:
        now = time.monotonic()
        elapsed = now - start
        measured = demo_measurement(elapsed, monitor.detector.view)
        visibility = {name: (0.96 if measured else None) for name in
                      ("nose", "left ear", "right ear", "left shoulder", "right shoulder", "left hip", "right hip")}
        fps = 1 / (now - previous) if previous is not None and now > previous else 0.0
        snap = monitor.update(measured, now, fps,
                              visibility, "DEMO (synthetic)",
                              0.12 if 8 <= elapsed % 19 < 10 else 0.29)
        previous = now
        dashboard.draw(snap, monitor.detector, monitor.alert)
        action = dashboard.input(monitor.detector, monitor.alert)
        if handle_action(action, monitor):
            return 0
        if action == "recalibrate":
            start = time.monotonic()
        time.sleep(0.05)


def main() -> int:
    args = parse_args()
    try:
        if args.tui:
            import curses
            from debug_tui import Dashboard

            def run(screen):
                dashboard = Dashboard(screen)
                return run_demo(args, dashboard) if args.demo else run_camera(args, dashboard)

            return curses.wrapper(run)
        if not args.legacy_gui and not args.no_gui:
            from web_server import run_web
            return run_web(args)
        return run_camera(args)
    except (OSError, RuntimeError, KeyboardInterrupt) as exc:
        if str(exc):
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
