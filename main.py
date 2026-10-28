"""Webcam posture monitor with optional terminal diagnostics."""

from __future__ import annotations

import argparse
import sys
import time

from alerts import AlertTimer
from activity_monitor import ActivityMonitor
from eye_detector import EyeMonitor, measure_eyes
from posture_detector import Assessment, Measurements, PostureDetector

CALIBRATION_SECONDS = 5.0
WINDOW_NAME = "Posture + Eye Monitor"
DEBUG_WINDOW_NAME = "Measurements and Debug"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local webcam posture and eye monitor")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index (default: 0)")
    parser.add_argument("--view", choices=("auto", "front", "side"), default="auto")
    parser.add_argument("--alert-seconds", type=float, default=5.0)
    parser.add_argument("--sound", action="store_true", help="Windows beep when warning starts")
    parser.add_argument("--tui", action="store_true", help="Live terminal measurements")
    parser.add_argument("--demo", action="store_true", help="Camera-free simulation; requires --tui")
    args = parser.parse_args()
    if args.alert_seconds <= 0:
        parser.error("--alert-seconds must be positive")
    if args.demo and not args.tui:
        parser.error("--demo requires --tui")
    if args.tui and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("--tui requires an interactive terminal")
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

    def __init__(self, view: str, alert_seconds: float) -> None:
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

        if self.detector.baseline is None:
            self.alert.reset()
            if measured is None or (self.calibration_view and measured.view != self.calibration_view):
                self.samples.clear()
                self.calibration_start = None
                self.calibration_view = None
            else:
                if self.calibration_start is None:
                    self.calibration_start = now
                    self.calibration_view = measured.view
                self.samples.append(measured)
                if now - self.calibration_start >= CALIBRATION_SECONDS:
                    self.detector.calibrate(self.samples)
                    self.samples.clear()
            remaining = (max(0.0, CALIBRATION_SECONDS - (now - self.calibration_start))
                         if self.calibration_start is not None else CALIBRATION_SECONDS)
            return DebugSnapshot("calibrating" if measured else "waiting for landmarks",
                                 Assessment("Calibrating" if measured else "Not Detected", None),
                                 measured, remaining,
                                 0.0, False, fps, landmarks, source, eye, activity)
        assessment = self.detector.assess(measured)
        warning, elapsed = self.alert.update(assessment.status, now)
        return DebugSnapshot("monitoring", assessment, measured, 0.0,
                             elapsed, warning, fps, landmarks, source, eye, activity)


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
    line(f"Nearly still: {snap.activity.still_seconds / 60:.1f} min   |   Measurements in Debug window",
         51, (185, 190, 195), 0.47)
    guidance = preview_guidance(snap)
    for index, (message, urgent) in enumerate(guidance[:3]):
        line(message, 79 + index * 26, (70, 100, 255) if urgent else (0, 210, 255), 0.52)
    if len(guidance) > 3:
        line(f"+{len(guidance) - 3} more issue(s) in Debug window", 157,
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
    """Prioritize distinct issues; the debug window contains every reason."""
    if snap.phase != "monitoring":
        if snap.measured is None:
            return [("Pose not tracked: show your shoulders and hips.", False),
                    ("Keep your face visible for eye measurements.", False)]
        return [(f"Calibrating: sit comfortably upright for {snap.calibration_remaining:.1f}s.", False),
                ("Keep your face, shoulders, and hips in view.", False)]

    activity = ([('Long stillness: change position or take a short break.', True)]
                if snap.activity.warning else [])
    posture = [(POSTURE_GUIDANCE.get(reason, reason), snap.warning)
               for reason in snap.assessment.reasons]
    eyes = [(EYE_GUIDANCE.get(reason, reason), True)
            for reason in snap.eye.reasons]
    if snap.assessment.status == "Not Detected":
        posture.append(("Pose not tracked: show your shoulders and hips.", False))
    if snap.eye.status == "Not Detected":
        eyes.append(("Eyes not tracked: face the camera in good light.", False))
    guidance = activity + posture[:1] + eyes[:1] + posture[1:] + eyes[1:]
    return guidance or [("Measurements in range: stay comfortable and move often.", False)]


def draw_debug_window(cv2, snap, monitor: Monitor):
    """Render detailed CV measurements in a separate OpenCV window."""
    import numpy as np

    canvas = np.full((700, 1080, 3), (30, 32, 36), dtype=np.uint8)
    white, muted, green, amber, red = ((245, 245, 245), (185, 190, 195),
                                       (80, 210, 100), (0, 210, 255), (60, 80, 255))

    def put(text: str, x: int, y: int, color=white, scale=0.56) -> None:
        cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, 1, cv2.LINE_AA)

    def fmt(number, digits=2):
        return f"{number:.{digits}f}" if number is not None else "--"

    def metric(label, current, baseline, limit, y, digits=2):
        change = current - baseline if current is not None and baseline is not None else None
        put(f"{label:<17} {fmt(current, digits):>7}  {fmt(baseline, digits):>7}  {fmt(change, digits):>7}  {limit}", 20, y)

    measured, base = snap.measured, monitor.detector.baseline
    thresholds = monitor.detector.thresholds
    put("POSTURE + EYE MONITOR  /  LIVE MEASUREMENTS", 20, 32, white, 0.72)
    put(f"{snap.source}    {snap.fps:.1f} FPS    view: {monitor.detector.view}    phase: {snap.phase}", 20, 62, muted)
    cv2.line(canvas, (20, 77), (1060, 77), (90, 95, 100), 1)
    posture_color = red if snap.warning else green if snap.assessment.status == "Good" else amber
    eye_color = red if snap.eye.warning else green if snap.eye.status == "Tracking" else amber
    put(f"POSTURE  {snap.assessment.status}  score {snap.assessment.score if snap.assessment.score is not None else '--'}", 20, 107, posture_color, 0.65)
    put(f"EYES  {snap.eye.status}", 565, 107, eye_color, 0.65)
    put("Indicator             Now     Base    Delta    Limit", 20, 140, muted, 0.49)
    metric("Torso angle", measured.torso_angle if measured else None,
           base.torso_angle if base else None, f"{thresholds.torso_degrees:.0f} deg", 170, 1)
    metric("Shoulder tilt", measured.shoulder_angle if measured and measured.view == "front" else None,
           base.shoulder_angle if base and base.view == "front" else None,
           f"{thresholds.shoulder_degrees:.0f} deg", 200, 1)
    metric("Forward head", measured.head_forward if measured else None,
           base.head_forward if base else None, f"{thresholds.head_forward_ratio:.2f}", 230)
    metric("Head tilt", measured.head_tilt if measured else None,
           base.head_tilt if base else None, f"{thresholds.head_tilt_degrees:.0f} deg", 260, 1)
    metric("Head turn", measured.head_turn if measured else None,
           base.head_turn if base else None, f"{thresholds.head_turn_ratio:.2f}", 290)
    metric("Shoulder gap", measured.shoulder_clearance if measured else None,
           base.shoulder_clearance if base else None,
           f"{thresholds.shoulder_elevation_ratio:.2f}", 320)
    metric("Elbow spread", measured.elbow_spread if measured else None,
           base.elbow_spread if base else None, f"{thresholds.elbow_spread_ratio:.2f}", 350)
    face_scale = (measured.face_width / base.face_width
                  if measured and base and measured.face_width is not None and base.face_width else None)
    put(f"Face size / baseline: {fmt(face_scale)}   alert at {thresholds.face_scale_ratio:.2f}", 20, 390)
    put("Closer to camera is a relative cue, not screen distance.", 20, 420, muted, 0.46)
    put(f"Still: {snap.activity.still_seconds / 60:.1f} min   reminder: {monitor.activity.reminder_seconds / 60:.0f} min", 20, 460,
        red if snap.activity.warning else white)
    put("Posture indicators:", 20, 505, muted)
    from textwrap import wrap
    for index, reason in enumerate(wrap(", ".join(snap.assessment.reasons), width=42)[:4]):
        put(reason, 20, 533 + index * 25, amber)
    if snap.activity.warning:
        put("Change position / take a short break", 20, 610, red)

    eye = snap.eye
    put(f"Left / right ratio: {fmt(eye.left_ratio, 3)} / {fmt(eye.right_ratio, 3)}", 565, 155)
    put(f"Mean openness: {fmt(eye.openness, 3)}", 565, 185)
    put(f"Open reference: {fmt(eye.open_baseline, 3)}", 565, 215)
    put(f"Closed cutoff: {fmt(eye.closed_threshold, 3)}", 565, 245)
    put(f"Blinks (rolling 60s): {eye.blink_count}", 565, 285)
    put(f"Blink rate: {fmt(eye.blinks_per_minute, 1)} / min", 565, 315)
    put(f"Closed now: {eye.closed_seconds:.1f} s", 565, 345)
    fraction = eye.closed_fraction * 100 if eye.closed_fraction is not None else None
    put(f"Closed fraction (30s): {fmt(fraction, 0)}%", 565, 375)
    put(f"Since last blink: {eye.since_blink:.1f} s", 565, 405)
    put("Eye indicators:", 565, 455, muted)
    for index, reason in enumerate(eye.reasons[:4]):
        put(reason, 565, 483 + index * 25, amber)
    if eye.warning:
        put(eye.warning, 565, 600, red)
    elif eye.status == "Not Detected":
        put("Show at least one eye to camera", 565, 600, amber)

    cv2.line(canvas, (20, 636), (1060, 636), (90, 95, 100), 1)
    visible = [f"{name} {fmt(value, 2)}" for name, value in snap.landmarks.items()]
    put("Pose visibility: " + "   ".join(visible[:4]), 20, 659, muted, 0.47)
    put("   ".join(visible[4:]), 20, 682, muted, 0.47)
    return canvas


def handle_action(action: str | None, monitor: Monitor) -> bool:
    if action == "quit":
        return True
    if action == "recalibrate":
        monitor.reset()
    return False


def run_camera(args: argparse.Namespace, dashboard=None) -> int:
    import cv2
    import mediapipe as mp
    from debug_tui import landmark_visibility

    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open camera {args.camera}. Check permissions/index.")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    monitor = Monitor(args.view, args.alert_seconds)
    missing_frames = 0
    previous_frame = None
    previous_warning = False
    last_dashboard_draw = 0.0
    pose_api = mp.solutions.pose
    try:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.namedWindow(DEBUG_WINDOW_NAME, cv2.WINDOW_NORMAL)
        with pose_api.Pose(
            static_image_mode=False,
            # Full model ships with this wheel; Lite downloads at startup.
            model_complexity=1,
            smooth_landmarks=True,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6,
        ) as pose, mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=False,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6,
        ) as face_mesh:
            while True:
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
                pose_rgb = (cv2.resize(rgb, (640, 480))
                            if width > 640 or height > 480 else rgb)
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
                                      "webcam", openness)
                active_warning = snap.warning or bool(snap.eye.warning) or snap.activity.warning
                if active_warning and not previous_warning:
                    maybe_beep(args.sound)
                previous_warning = active_warning
                draw_overlay(cv2, frame, snap, monitor)
                cv2.imshow(WINDOW_NAME, frame)
                cv2.imshow(DEBUG_WINDOW_NAME, draw_debug_window(cv2, snap, monitor))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    monitor.reset()
                if key == ord("v"):
                    choices = ("auto", "front", "side")
                    monitor.detector.view = choices[
                        (choices.index(monitor.detector.view) + 1) % len(choices)]
                    monitor.reset()
                if dashboard is not None:
                    if now - last_dashboard_draw >= 0.1:
                        dashboard.draw(snap, monitor.detector, monitor.alert)
                        last_dashboard_draw = now
                    if handle_action(dashboard.input(monitor.detector, monitor.alert), monitor):
                        break
    finally:
        capture.release()
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
        return run_camera(args)
    except (RuntimeError, KeyboardInterrupt) as exc:
        if str(exc):
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
