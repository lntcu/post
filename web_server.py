"""Loopback-only dashboard, camera workers, and browser-facing measurements."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import math
import secrets
import threading
import time
import webbrowser
from urllib.parse import urlparse

from settings import load_settings, save_settings

WEB_DEFAULTS = {
    "posture_alerts": True, "eye_alerts": True, "break_alerts": True,
    "sensitivity": "balanced", "break_minutes": 20, "cooldown_seconds": 60,
    "quiet_start": "", "quiet_end": "", "side_source": "",
}


def validate_preferences(payload, current):
    """Validate the entire update before changing any running configuration."""
    if not isinstance(payload, dict):
        raise ValueError("Settings must be an object.")
    result = {**current, "web": {**WEB_DEFAULTS, **current.get("web", {})}}
    for key, value in payload.items():
        if key in ("notifications", "posture_alerts", "eye_alerts", "break_alerts"):
            if type(value) is not bool:
                raise ValueError(f"{key} must be on or off.")
        elif key in ("camera", "alert_seconds", "break_minutes", "cooldown_seconds"):
            limits = {"camera": (0, 20), "alert_seconds": (1, 120),
                      "break_minutes": (1, 120), "cooldown_seconds": (10, 3600)}
            low, high = limits[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}.")
            if key == "camera" and type(value) is not int:
                raise ValueError("Camera index must be a whole number.")
        elif key == "view":
            if value not in ("auto", "front", "side"):
                raise ValueError("Choose a front, side, or automatic view.")
        elif key == "sensitivity":
            if value not in ("gentle", "balanced", "sensitive"):
                raise ValueError("Choose a supported sensitivity.")
        elif key in ("quiet_start", "quiet_end"):
            if not isinstance(value, str):
                raise ValueError("Quiet hours must be HH:MM.")
            if value:
                try:
                    parsed_time = datetime.strptime(value, "%H:%M")
                    if parsed_time.strftime("%H:%M") != value:
                        raise ValueError("Use HH:MM.")
                except ValueError:
                    raise ValueError("Quiet hours must be HH:MM.") from None
        elif key == "side_source":
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError("Enter a camera index or direct stream URL.")
            if value:
                if value.isdigit():
                    if not 0 <= int(value) <= 20:
                        raise ValueError("Side camera index must be 0–20.")
                else:
                    parsed = urlparse(value)
                    if parsed.scheme not in ("http", "https", "rtsp") or not parsed.hostname:
                        raise ValueError("Use a direct http(s) or rtsp stream URL.")
        else:
            raise ValueError(f"Unknown setting: {key}")
        if key in WEB_DEFAULTS:
            result["web"][key] = value
        else:
            result[key] = value
    side = result["web"]["side_source"]
    if side.isdigit() and int(side) == result["camera"]:
        raise ValueError("Front and side cameras must be different.")
    if bool(result["web"]["quiet_start"]) != bool(result["web"]["quiet_end"]):
        raise ValueError("Set both quiet-hour times, or clear both.")
    return result


def quiet_now(preferences, now=None):
    start, end = preferences["quiet_start"], preferences["quiet_end"]
    if not start or not end:
        return False
    current = (now or datetime.now()).strftime("%H:%M")
    return start <= current < end if start < end else current >= start or current < end


METRICS = (
    ("torso_angle", "Torso lean", "torso_degrees", "degrees"),
    ("shoulder_angle", "Shoulder tilt", "shoulder_degrees", "degrees"),
    ("head_forward", "Forward head", "head_forward_ratio", "ratio"),
    ("head_tilt", "Head tilt", "head_tilt_degrees", "degrees"),
    ("head_turn", "Head turn", "head_turn_ratio", "ratio"),
    ("shoulder_clearance", "Raised shoulders", "shoulder_elevation_ratio", "ratio"),
    ("elbow_spread", "Elbows away from body", "elbow_spread_ratio", "ratio"),
    ("face_width", "Closer to camera", "face_scale_ratio", "scale"),
)


def describe_snapshot(snap, detector):
    """Expose observable cues and availability, never a medical or health score."""
    from main import POSTURE_GUIDANCE, EYE_GUIDANCE
    measured, baseline = snap.measured, detector.baseline
    rows = []
    mode = measured.view if measured else detector.view
    for field, label, threshold, unit in METRICS:
        if (mode == "front" and field == "head_forward") or (mode == "side" and field not in ("torso_angle", "head_forward")):
            continue
        value = getattr(measured, field, None)
        reference = getattr(baseline, field, None)
        available = value is not None and reference is not None
        delta = (reference - value if field == "shoulder_clearance" else value - reference) if available else None
        if unit == "scale" and available:
            delta = (value / reference - 1) * 100 if reference else None
        rows.append({"name": label, "available": available and delta is not None,
                     "delta": round(delta, 2) if delta is not None else None,
                     "unit": "°" if unit == "degrees" else "%" if unit == "scale" else "ratio",
                     "threshold": round((getattr(detector.thresholds, threshold) - 1) * 100 if unit == "scale"
                                        else getattr(detector.thresholds, threshold), 2),
                     "issue": label in snap.assessment.reasons,
                     "guidance": POSTURE_GUIDANCE.get(label, "")})
    available_count = sum(row["available"] for row in rows)
    if measured is None:
        confidence, explanation = "Unavailable", "Body landmarks are missing. No posture conclusion is available."
    elif baseline is None:
        confidence, explanation = "Setting up", "Hold a comfortable upright position to establish your reference."
    elif measured.view != baseline.view:
        confidence, explanation = "Unavailable", "View differs from calibration. Recalibrate or choose a fixed view."
        for row in rows:
            row["available"] = False
    elif available_count < len(rows):
        confidence, explanation = "Limited", "Some body parts are hidden; only available measurements are assessed."
    else:
        confidence, explanation = "Available", "Required landmarks are visible. This is tracking coverage, not validated accuracy."
    if snap.eye.status == "Not Detected":
        eye_label = "Eyes unavailable"
    elif snap.eye.reasons:
        eye_label = "Eye cue detected"
    else:
        eye_label = "Eyes tracked"
    status = ("Set up your camera" if snap.phase == "positioning" else
              "Learning your reference" if snap.phase == "calibrating" else
              "Tracking unavailable" if confidence == "Unavailable" else
              "Adjustment suggested" if snap.assessment.reasons else
              "Available measurements near reference" if confidence == "Limited" else "Near your reference")
    return {"phase": snap.phase, "status": status, "confidence": confidence,
            "confidence_detail": explanation, "metrics": rows,
            "guidance": [POSTURE_GUIDANCE.get(r, r) for r in snap.assessment.reasons],
            "calibration_hint": snap.calibration_hint,
            "calibration_remaining": snap.calibration_remaining, "view": mode,
            "eye": {**asdict(snap.eye), "status": eye_label,
                    "guidance": [EYE_GUIDANCE.get(r, r) for r in snap.eye.reasons],
                    "confidence": "Unavailable" if snap.eye.openness is None else "Limited" if
                    (snap.eye.left_ratio is None or snap.eye.right_ratio is None) else "Available"},
            "still_seconds": snap.activity.still_seconds, "activity_tracked": snap.activity.tracked,
            "fps": round(snap.fps, 1), "warning": snap.warning,
            "eye_warning": bool(snap.eye.warning), "break_warning": snap.activity.warning}


class Dashboard:
    def __init__(self, args):
        self.args = args
        self.settings = load_settings()
        self.settings.update(camera=args.camera, view=args.view, alert_seconds=args.alert_seconds,
                             notifications=args.notifications)
        self.settings["web"] = {**WEB_DEFAULTS, **self.settings.get("web", {})}
        if args.side_camera is not None:
            self.settings["web"]["side_source"] = str(args.side_camera)
        elif args.side_url:
            self.settings["web"]["side_source"] = args.side_url
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.started = False
        self.paused = False
        self.revision = 0
        self.snoozed_until = 0.0
        self.frames = {}
        self.cameras = {}
        self.last_notifications = {}
        self.active_notifications = set()
        self.token = secrets.token_urlsafe(32)
        self.threads = []

    def launch(self):
        for name in ("front", "side"):
            thread = threading.Thread(target=self.worker, args=(name,), daemon=True)
            thread.start()
            self.threads.append(thread)
        thread = threading.Thread(target=self.notify_worker, daemon=True)
        thread.start()
        self.threads.append(thread)

    def state(self):
        with self.lock:
            quiet = quiet_now(self.settings["web"])
            snooze = max(0, int(self.snoozed_until - time.monotonic()))
            cameras = json.loads(json.dumps(self.cameras))
            for name, camera in cameras.items():
                if camera.get("updated_at") is not None and time.monotonic() - camera["updated_at"] > 5:
                    cameras[name] = {"error": "Camera feed is delayed. Waiting for fresh measurements…", "confidence": "Unavailable"}
            alerts = []
            if self.started and not self.paused and not quiet and not snooze:
                for name, camera in cameras.items():
                    if camera.get("warning") and self.settings["web"]["posture_alerts"]:
                        alerts.extend(f"{name.title()}: {cue}" for cue in camera["guidance"])
                    if name == "front" and camera.get("eye_warning") and self.settings["web"]["eye_alerts"]:
                        alerts.extend(camera["eye"]["guidance"])
                    if name == "front" and camera.get("break_warning") and self.settings["web"]["break_alerts"]:
                        alerts.append("Change position or take a short break.")
            return {"started": self.started, "paused": self.paused, "cameras": cameras,
                    "settings": self.settings, "alerts": alerts, "quiet": quiet,
                    "snooze_seconds": snooze, "demo": self.args.demo,
                    "desktop_notifications_supported": __import__('sys').platform == "darwin"}

    def command(self, payload):
        action = payload.get("action")
        with self.lock:
            if action == "settings":
                updated = validate_preferences(payload.get("settings"), self.settings)
                save_settings(updated)
                # Alert-only changes do not require a fresh camera calibration.
                if any(updated[k] != self.settings[k] for k in ("camera", "view")) or updated["web"]["side_source"] != self.settings["web"]["side_source"]:
                    self.revision += 1
                    self.cameras.clear()
                    self.frames.clear()
                self.settings = updated
            elif action == "start":
                self.started = True
                self.paused = False
                self.revision += 1
            elif action == "pause":
                self.paused = not self.paused
                self.revision += 1
                self.cameras.clear()
                self.frames.clear()
            elif action == "recalibrate":
                self.revision += 1
                self.cameras.clear()
            elif action == "snooze":
                minutes = payload.get("minutes", 10)
                if type(minutes) not in (int, float) or not math.isfinite(minutes) or not 1 <= minutes <= 120:
                    raise ValueError("Snooze must be 1–120 minutes.")
                self.snoozed_until = time.monotonic() + minutes * 60
            elif action == "unsnooze":
                self.snoozed_until = 0
            elif action == "stop":
                self.started = False
                self.revision += 1
                self.cameras.clear()
                self.frames.clear()
            else:
                raise ValueError("Unknown action.")
        return self.state()

    def notify_worker(self):
        from notifications import MacNotifier
        notifier = MacNotifier()
        while not self.stop.wait(0.5):
            state = self.state()
            events = set(state["alerts"])
            now = time.monotonic()
            fresh = sorted(message for message in events - self.active_notifications
                           if now - self.last_notifications.get(message, -math.inf)
                           >= state["settings"]["web"]["cooldown_seconds"])
            if fresh and not self.args.demo:
                # One banner for simultaneous cues, rather than a burst of alerts.
                if state["settings"]["notifications"] and notifier.enabled:
                    summary = " ".join(fresh[:3])
                    if len(fresh) > 3:
                        summary += " More details in the dashboard."
                    notifier._send(summary)
                if getattr(self.args, "sound", False):
                    from main import maybe_beep
                    maybe_beep(True)
                for message in fresh:
                    self.last_notifications[message] = now
            self.active_notifications = events

    def worker(self, name):
        import cv2
        from main import Monitor, demo_measurement, open_side_capture
        from posture_detector import Thresholds
        from debug_tui import landmark_visibility
        from eye_detector import measure_eyes
        from contextlib import ExitStack
        capture = None
        identity = None
        monitor = None
        previous = None
        retry_at = 0
        stack = ExitStack()
        pose = face = None
        demo_start = time.monotonic()
        try:
            while not self.stop.is_set():
                with self.lock:
                    settings = {**self.settings, "web": dict(self.settings["web"])}
                    revision = self.revision
                    enabled = self.started and not self.paused
                source = settings["camera"] if name == "front" else settings["web"]["side_source"]
                if name == "side" and not source:
                    enabled = False
                new_identity = (source, settings["view"] if name == "front" else "side", revision)
                if not enabled:
                    if capture is not None:
                        capture.release()
                        capture = None
                    identity = None
                    self.stop.wait(.1)
                    continue
                if identity != new_identity:
                    if capture is not None:
                        capture.release()
                        capture = None
                    monitor = Monitor(new_identity[1], settings["alert_seconds"])
                    identity = new_identity
                    demo_start = time.monotonic()
                    previous = None
                    retry_at = 0
                    if pose:
                        pose.reset()
                    if face:
                        face.reset()
                now = time.monotonic()
                monitor.alert.delay_seconds = settings["alert_seconds"]
                monitor.activity.reminder_seconds = settings["web"]["break_minutes"] * 60
                scale = {"gentle": 1.35, "balanced": 1, "sensitive": .75}[settings["web"]["sensitivity"]]
                monitor.detector.thresholds = Thresholds(**{
                    key: (1 + (value - 1) * scale if key == "face_scale_ratio" else value * scale)
                    for key, value in asdict(Thresholds()).items()})
                if self.args.demo:
                    import numpy as np
                    frame = np.full((540, 960, 3), (43, 52, 42), dtype=np.uint8)
                    cv2.putText(frame, "DEMO / SYNTHETIC FEED", (55, 225), cv2.FONT_HERSHEY_SIMPLEX, 1, (210, 230, 210), 2)
                    cv2.putText(frame, "No camera is being used", (55, 275), cv2.FONT_HERSHEY_SIMPLEX, .7, (180, 200, 180), 1)
                    measured = demo_measurement(now - demo_start, monitor.detector.view)
                    eyes = .12 if 8 <= (now - demo_start) % 19 < 10 else .29
                    visibility = {}
                else:
                    if capture is None:
                        if now < retry_at:
                            self.stop.wait(.1)
                            continue
                        src = int(source) if str(source).isdigit() else source
                        candidate = open_side_capture(cv2, src)
                        if not candidate.isOpened():
                            candidate.release()
                            self.publish_error(name, "Camera unavailable. Check camera permissions, connection, and selected index. Retrying…", revision)
                            retry_at = now + 3
                            continue
                        capture = candidate
                    ok, frame = capture.read()
                    if not ok:
                        capture.release()
                        capture = None
                        monitor.reset()
                        self.publish_error(name, "Camera disconnected. Check the connection; retrying…", revision)
                        retry_at = now + 3
                        continue
                    if pose is None:
                        import mediapipe as mp
                        pose = stack.enter_context(mp.solutions.pose.Pose(model_complexity=1, min_detection_confidence=.6, min_tracking_confidence=.6))
                        if name == "front":
                            face = stack.enter_context(mp.solutions.face_mesh.FaceMesh(max_num_faces=1, min_detection_confidence=.6, min_tracking_confidence=.6))
                    frame = cv2.flip(frame, 1)
                    height, width = frame.shape[:2]
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    # Preserve aspect ratio, so inference sees the same geometry as the feed.
                    small = cv2.resize(rgb, (640, max(1, round(height * 640 / width)))) if width > 640 else rgb
                    result = pose.process(small)
                    landmarks = result.pose_landmarks.landmark if result.pose_landmarks else None
                    face_result = face.process(rgb) if face else None
                    face_landmarks = face_result.multi_face_landmarks[0].landmark if face_result and face_result.multi_face_landmarks else None
                    measured = monitor.detector.measure(landmarks, width, height)
                    eyes = measure_eyes(face_landmarks, width, height) if face else None
                    visibility = landmark_visibility(landmarks)
                now = time.monotonic()
                fps = 1 / (now - previous) if previous and now > previous else 0
                previous = now
                snap = monitor.update(measured, now, fps, visibility, name, eyes)
                data = describe_snapshot(snap, monitor.detector)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                data["lighting"] = "Too dark" if gray.mean() < 45 else "Very bright" if gray.mean() > 230 else "Usable"
                if not self.args.demo and data["lighting"] != "Usable":
                    lighting_hint = ("Increase the light on your face." if data["lighting"] == "Too dark"
                                     else "Reduce glare or bright backlighting.")
                    if data["confidence"] == "Available":
                        data["confidence"] = "Limited"
                        data["confidence_detail"] = lighting_hint + " Lighting can reduce measurement reliability."
                    if data["eye"]["confidence"] == "Available":
                        data["eye"]["confidence"] = "Limited"
                    if data["phase"] != "monitoring":
                        data["calibration_hint"] = lighting_hint + " " + data["calibration_hint"]
                data["updated_at"] = now
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                with self.lock:
                    if revision == self.revision and self.started and not self.paused:
                        self.cameras[name] = data
                        if ok:
                            self.frames[name] = encoded.tobytes()
                self.stop.wait(.06)
        except Exception as exc:
            self.publish_error(name, f"Camera processing stopped ({type(exc).__name__}). Check installation and restart the server.", revision)
        finally:
            if capture is not None:
                capture.release()
            stack.close()

    def publish_error(self, name, message, revision):
        with self.lock:
            if self.revision == revision:
                self.cameras[name] = {"error": message, "confidence": "Unavailable"}
                self.frames.pop(name, None)


class Server(ThreadingHTTPServer):
    daemon_threads = True


def make_handler(dashboard):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, data, content_type="application/json"):
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def allowed(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {"error": "Use the localhost address printed by the server."})
            path = urlparse(self.path).path
            if path == "/api/state":
                return self.reply(200, dashboard.state())
            if path == "/api/session":
                return self.reply(200, {"token": dashboard.token})
            if path.startswith("/feed/"):
                name = path.rsplit("/", 1)[-1].removesuffix(".jpg")
                with dashboard.lock:
                    frame = dashboard.frames.get(name)
                return self.reply(200, frame, "image/jpeg") if frame else self.reply(503, {"error": "Waiting for camera"})
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "application/javascript"), "/style.css": ("style.css", "text/css")}
            if path in assets:
                filename, mime = assets[path]
                return self.reply(200, (Path(__file__).parent / "web" / filename).read_bytes(), mime)
            self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if not self.allowed() or self.headers.get("X-Dashboard-Token") != dashboard.token:
                return self.reply(403, {"error": "Reload the dashboard to reconnect."})
            if urlparse(self.path).path != "/api/command":
                return self.reply(404, {"error": "Not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Invalid request size.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Request must be an object.")
                self.reply(200, dashboard.command(payload))
            except (ValueError, TypeError, OSError) as exc:
                self.reply(400, {"error": str(exc)})
    return Handler


def run_web(args):
    dashboard = Dashboard(args)
    server = Server(("127.0.0.1", args.port), make_handler(dashboard))
    dashboard.launch()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Posture Monitor: {url}\nOpen the dashboard and choose Start setup. Press Ctrl+C here to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        dashboard.stop.set()
        server.server_close()
        for thread in dashboard.threads:
            thread.join(timeout=4)
    return 0
