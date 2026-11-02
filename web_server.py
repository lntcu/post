"""Loopback-only dashboard, camera workers, and browser-facing measurements."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import math
import os
import secrets
import threading
import time
import webbrowser
from urllib.parse import parse_qs, urlparse

from settings import SETTINGS_PATH, load_settings, save_settings
from analytics import Analytics

WEB_DEFAULTS = {
    "posture_alerts": True, "eye_alerts": True, "break_alerts": True, "fatigue_alerts": True,
    "sensitivity": "balanced", "break_minutes": 20, "cooldown_seconds": 60,
    "quiet_start": "", "quiet_end": "", "side_source": "",
    "spoken_alerts": False, "speech_rate": 1.0, "speech_volume": .8, "speech_voice": "",
    "history_enabled": True, "writing_enabled": False, "writing_alerts": True,
    "writing_source": "", "writing_hand": "right", "writing_pen_markers": True, "writing_assessment": "geometry", "calibration_seconds": 4,
}


def validate_preferences(payload, current):
    """Validate the entire update before changing any running configuration."""
    if not isinstance(payload, dict):
        raise ValueError("Settings must be an object.")
    result = {**current, "web": {**WEB_DEFAULTS, **current.get("web", {})}}
    for key, value in payload.items():
        if key in ("notifications", "posture_alerts", "eye_alerts", "break_alerts", "fatigue_alerts", "spoken_alerts", "history_enabled", "writing_enabled", "writing_alerts", "writing_pen_markers"):
            if type(value) is not bool:
                raise ValueError(f"{key} must be on or off.")
        elif key in ("camera", "alert_seconds", "break_minutes", "cooldown_seconds", "speech_rate", "speech_volume", "calibration_seconds"):
            limits = {"camera": (0, 20), "alert_seconds": (1, 120),
                      "break_minutes": (1, 120), "cooldown_seconds": (10, 3600),
                      "speech_rate": (.5, 2), "speech_volume": (0, 1), "calibration_seconds": (2, 30)}
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
        elif key == "speech_voice":
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError("Choose a supported voice.")
        elif key == 'writing_assessment':
            if value != 'geometry':
                raise ValueError('Writing assessment uses live camera geometry.')
        elif key == "writing_hand":
            if value not in ("left", "right"):
                raise ValueError("Choose the left or right writing hand.")
        elif key in ("side_source", "writing_source"):
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
    writing = result["web"]["writing_source"]
    if writing and (writing == side or (writing.isdigit() and (int(writing) == result["camera"] or (side.isdigit() and int(writing) == int(side))))):
        raise ValueError("Use an unused desk camera index/URL, or leave it empty to use the front camera.")
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
        self.writing = {}
        self.writing_revision = 0
        from writing_validation import WritingRecorder, ChangeModel
        self.writing_recorder = WritingRecorder()
        self.pressure_readings = {}
        self.writing_model = None
        self.writing_model_error = ''
        model_path = os.environ.get('POSTURE_WRITING_MODEL')
        if model_path:
            try:
                self.writing_model = ChangeModel(json.loads(Path(model_path).read_text()))
            except (OSError, ValueError, TypeError, KeyError):
                self.writing_model_error = 'Writing change model could not be loaded. Check the model file.'
        self.analytics = Analytics(SETTINGS_PATH.with_name(".posture-eye-analytics.sqlite3"), demo=args.demo)
        self.break_until = 0.

    def launch(self):
        for name in ("front", "side"):
            thread = threading.Thread(target=self.worker, args=(name,), daemon=True)
            thread.start()
            self.threads.append(thread)
        for target in (self.notify_worker, self.telemetry_worker, self.writing_worker):
            thread = threading.Thread(target=target, daemon=True)
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
            writing = json.loads(json.dumps(self.writing))
            if writing.get("updated_at") is not None and time.monotonic() - writing["updated_at"] > 5:
                writing = {"phase": "positioning", "confidence": "Unavailable", "status": "Writing feed delayed", "metrics": [], "guidance": [], "warning": False}
            writing['assessment_mode'] = 'geometry'
            from coaching import build_coaching, writing_posture_guidance
            if self.settings["web"]["writing_enabled"]:
                writing_posture_guidance(cameras)
            coaching = build_coaching(cameras, writing, self.settings['web']['writing_enabled'],
                                      self.started and not self.paused, bool(self.settings['web']['side_source']))
            notifications = []
            def add_notification(text, category, severity='warning', score=None):
                notifications.append({'message': text, 'category': category, 'severity': severity, 'score': score})
            alerts = []
            if self.started and not self.paused and not quiet and not snooze:
                for name, camera in cameras.items():
                    fatigue = camera.get("fatigue", {})
                    if name == "front" and fatigue.get("warning") and self.settings["web"]["fatigue_alerts"]:
                        alerts.append(fatigue["guidance"])
                        add_notification(fatigue["guidance"], 'Tiredness', 'suggestion')
                    if camera.get("warning") and self.settings["web"]["posture_alerts"]:
                        for cue in camera['guidance']:
                            text = f"{name.title()}: {cue}"
                            alerts.append(text)
                            part = next((p for p in coaching['parts'] if p['label'] == ('Side posture' if name == 'side' else 'Posture')), {'severity': 'warning'})
                            add_notification(text, 'Posture', part['severity'] if part['severity'] in ('warning', 'attention') else 'warning', part.get('score'))
                    if name == "front" and camera.get("eye_warning") and self.settings["web"]["eye_alerts"]:
                        alerts.extend(camera['eye']['guidance'])
                        for cue in camera['eye']['guidance']:
                            add_notification(cue, 'Eyes')
                    if name == "front" and camera.get("break_warning") and self.settings["web"]["break_alerts"]:
                        alerts.append("Change position or take a short break.")
                        add_notification(alerts[-1], 'Movement', 'suggestion')
                if writing.get("warning") and self.settings["web"]["writing_enabled"] and self.settings["web"]["writing_alerts"]:
                    issues = [row for row in writing.get('metrics', []) if row.get('issue')]
                    priority = {'wrist': 0, 'fingers': 1, 'pen': 2, 'pressure': 3}
                    issue = min(issues, key=lambda row: priority.get(row.get('family'), 4), default=None)
                    cue = {'wrist': 'Turn the paper and support your forearm.',
                           'fingers': 'Relax your fingers and try a lighter grip.',
                           'pen': 'Check your pen position and try a few relaxed strokes.',
                           'pressure': 'Ease your grip and check the sensor.'}.get(issue.get('family') if issue else None)
                    if cue:
                        alerts.append(cue)
                    part = coaching['parts'][-1]
                    if cue:
                        add_notification(cue, 'Grip & wrist', part['severity'] if part['severity'] in ('warning', 'attention') else 'warning', part.get('score'))
            return {"started": self.started, "paused": self.paused, "cameras": cameras,
                    "settings": self.settings, "alerts": alerts, "notifications": notifications, "coaching": coaching, "quiet": quiet,
                    "snooze_seconds": snooze, "demo": self.args.demo,
                    "writing": writing, "writing_recording": self.writing_recorder.status(),
                    "writing_model_error": self.writing_model_error,
                    "pressure": {kind: {'device': r['device'], 'newtons': r['newtons'],
                                          'fresh': time.monotonic() - r['time'] <= .5}
                                 for kind, r in self.pressure_readings.items()},
                    "session": self.analytics.summary(), "history_error": self.analytics.error,
                    "break_seconds": math.ceil(max(0, self.break_until - time.monotonic())),
                    "break_active": bool(self.started and self.paused and self.break_until),
                    "desktop_notifications_supported": __import__('sys').platform == "darwin"}

    def command(self, payload):
        action = payload.get("action")
        with self.lock:
            if action == "settings":
                updated = validate_preferences(payload.get("settings"), self.settings)
                save_settings(updated)
                # Alert-only changes do not require a fresh camera calibration.
                if any(updated[k] != self.settings[k] for k in ("camera", "view")) or any(updated["web"][key] != self.settings["web"][key] for key in ("side_source", "writing_enabled", "writing_source", "writing_hand", "writing_pen_markers", "writing_assessment", "calibration_seconds")):
                    self.analytics.suspend()
                    self.revision += 1
                    self.cameras.clear()
                    self.frames.clear()
                    self.writing.clear()
                self.analytics.set_persistence(updated["web"]["history_enabled"])
                self.settings = updated
            elif action == 'writing_record_start':
                if not self.started or self.paused or not self.settings['web']['writing_enabled']:
                    raise ValueError('Start hand tracking before recording.')
                self.writing_recorder.start(payload.get('participant'), payload.get('style', ''), time.monotonic())
                self.writing_recorder.metadata['setup'] = {key: self.settings['web'][key]
                    for key in ('writing_hand', 'writing_pen_markers')}
                self.writing_recorder.metadata['demo'] = self.args.demo
            elif action == 'writing_record_label':
                self.writing_recorder.set_label(payload.get('label'))
            elif action == 'writing_record_stop':
                self.writing_recorder.active = False
            elif action == 'writing_pressure':
                kind, force, device = payload.get('kind'), payload.get('newtons'), payload.get('device')
                if kind not in ('grip_force', 'tip_force'):
                    raise ValueError('Specify grip_force or tip_force; tip force does not measure squeezing.')
                if type(force) not in (int, float) or not math.isfinite(force) or not 0 <= force <= 1000:
                    raise ValueError('Sensor force must be a finite value between 0 and 1000 newtons.')
                if not isinstance(device, str) or not device.strip() or len(device) > 80:
                    raise ValueError('Provide a sensor device identifier of 1–80 characters.')
                previous = self.pressure_readings.get(kind)
                if previous and previous['device'] != device:
                    self.writing_revision += 1
                    self.writing.clear()
                self.pressure_readings[kind] = {'device': device, 'newtons': force, 'time': time.monotonic()}
            elif action == "start":
                if self.snoozed_until == self.break_until:
                    self.snoozed_until = 0
                self.break_until = 0
                if not self.started:
                    self.analytics.start(self.settings["web"]["history_enabled"])
                self.started = True
                self.paused = False
                self.revision += 1
            elif action == "pause":
                self.analytics.suspend()
                self.writing.clear()
                self.paused = not self.paused
                if not self.paused:
                    if self.snoozed_until == self.break_until:
                        self.snoozed_until = 0
                    self.break_until = 0
                self.revision += 1
                self.cameras.clear()
                self.frames.clear()
            elif action == "recalibrate":
                self.analytics.suspend()
                self.writing.clear()
                self.revision += 1
                self.cameras.clear()
            elif action == "writing_calibrate":
                self.writing_revision += 1
                self.writing.clear()
            elif action == "take_break":
                if not self.started:
                    raise ValueError("Start a session before taking a break.")
                self.analytics.suspend()
                self.break_until = time.monotonic() + 120
                self.snoozed_until = self.break_until
                if self.started and not self.paused:
                    self.paused = True
                    self.revision += 1
                    self.cameras.clear()
                    self.frames.clear()
                    self.writing.clear()
            elif action == "end_break":
                # Idempotent: a repeated request must never pause a resumed session.
                if self.started and self.paused and self.break_until:
                    if self.snoozed_until == self.break_until:
                        self.snoozed_until = 0
                    self.break_until = 0
                    self.paused = False
                    self.revision += 1
                    self.cameras.clear()
                    self.frames.clear()
                    self.writing.clear()
            elif action == "clear_history":
                if self.started:
                    raise ValueError("Stop the current session before clearing history.")
                self.analytics.clear()
            elif action == "snooze":
                minutes = payload.get("minutes", 10)
                if type(minutes) not in (int, float) or not math.isfinite(minutes) or not 1 <= minutes <= 120:
                    raise ValueError("Snooze must be 1–120 minutes.")
                self.snoozed_until = time.monotonic() + minutes * 60
            elif action == "unsnooze":
                self.snoozed_until = 0
            elif action == "stop":
                self.paused = False
                self.break_until = 0
                self.analytics.finish()
                self.writing_recorder.active = False
                self.pressure_readings.clear()
                self.writing.clear()
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

    def telemetry_worker(self):
        while not self.stop.wait(1):
            self.analytics.record(self.state())

    def publish_writing(self, data, revision, hand_revision, measured=None):
        with self.lock:
            if revision == self.revision and hand_revision == self.writing_revision and self.started and not self.paused:
                if self.writing_model and data.get('phase') == 'monitoring':
                    data['learned_change'] = {'probability': self.writing_model.predict(data.get('metrics', []), data.get('geometry_source')),
                                              'validation': self.writing_model.report}
                self.writing_recorder.record(measured, data, time.monotonic())
                self.writing = {**data, "updated_at": time.monotonic()}

    @staticmethod
    def selected_hand_index(result, settings):
        if not result or not result.multi_hand_landmarks or not result.multi_handedness:
            return None
        candidates = []
        for index, (_, handedness) in enumerate(zip(result.multi_hand_landmarks, result.multi_handedness)):
            classified = handedness.classification[0]
            if classified.label.lower() == settings['web']['writing_hand'] and classified.score >= .75:
                candidates.append((classified.score, index))
        return max(candidates)[1] if candidates else None

    @staticmethod
    def selected_hand(result, settings):
        index = Dashboard.selected_hand_index(result, settings)
        return result.multi_hand_landmarks[index].landmark if index is not None else None

    def current_pressure(self):
        with self.lock:
            return {kind: r['newtons'] for kind, r in self.pressure_readings.items()
                    if 0 <= time.monotonic() - r['time'] <= .5}

    def extract_hand(self, result, frame, pose, settings):
        from writing_detector import measure_hand
        from pen_detector import detect_pen
        hand = self.selected_hand(result, settings)
        world = None
        if hand is not None:
            worlds = getattr(result, 'multi_hand_world_landmarks', None)
            index = self.selected_hand_index(result, settings)
            if worlds and index is not None and index < len(worlds):
                world = worlds[index].landmark
        pen = detect_pen(frame, hand) if settings['web'].get('writing_pen_markers', True) else None
        return measure_hand(hand, frame.shape[1], frame.shape[0], pose, world=world,
                            pen=pen, pressure=self.current_pressure())

    def writing_worker(self):
        """Optional dedicated desk feed; front-camera mode reuses front inference."""
        import cv2
        from contextlib import ExitStack
        from main import open_side_capture
        from writing_detector import HandMeasurement, WritingMonitor
        capture = None
        identity = None
        monitor = WritingMonitor()
        stack = ExitStack()
        hands = pose = None
        retry_at = 0
        try:
            while not self.stop.is_set():
                with self.lock:
                    settings = {**self.settings, "web": dict(self.settings["web"])}
                    revision, hand_revision = self.revision, self.writing_revision
                    enabled = self.started and not self.paused and settings["web"]["writing_enabled"] and bool(settings["web"]["writing_source"])
                if not enabled:
                    if capture is not None:
                        capture.release()
                        capture = None
                    identity = None
                    self.stop.wait(.1)
                    continue
                source = settings["web"]["writing_source"]
                if identity != (source, revision, hand_revision):
                    if capture is not None:
                        capture.release()
                        capture = None
                    identity = (source, revision, hand_revision)
                    monitor.reset()
                    demo_start = time.monotonic()
                    retry_at = 0
                now = time.monotonic()
                if self.args.demo:
                    import numpy as np
                    frame = np.full((540, 960, 3), (43, 52, 42), dtype=np.uint8)
                    cv2.putText(frame, "DEMO / WRITING HAND", (55, 68), cv2.FONT_HERSHEY_SIMPLEX, .6, (210, 230, 210), 2)
                    measured = HandMeasurement(.25 + (.5 if (now - demo_start) % 25 > 12 else 0), .15, 8.)
                else:
                    if capture is None:
                        if now < retry_at:
                            self.stop.wait(.1)
                            continue
                        capture = open_side_capture(cv2, int(source) if source.isdigit() else source)
                        if not capture.isOpened():
                            capture.release()
                            capture = None
                            self.publish_writing({"phase": "positioning", "confidence": "Unavailable", "status": "Desk camera unavailable · retrying", "metrics": [], "guidance": [], "warning": False}, revision, hand_revision)
                            retry_at = now + 3
                            continue
                    ok, frame = capture.read()
                    if not ok:
                        capture.release()
                        capture = None
                        monitor.reset()
                        with self.lock:
                            self.frames.pop("writing", None)
                        self.publish_writing({"phase": "positioning", "confidence": "Unavailable", "status": "Desk camera disconnected · retrying", "metrics": [], "guidance": [], "warning": False}, revision, hand_revision)
                        retry_at = now + 3
                        continue
                    if hands is None:
                        import mediapipe as mp
                        hands = stack.enter_context(mp.solutions.hands.Hands(max_num_hands=2, min_detection_confidence=.65, min_tracking_confidence=.65))
                        pose = stack.enter_context(mp.solutions.pose.Pose(min_detection_confidence=.6, min_tracking_confidence=.6))
                    frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pose_result = pose.process(rgb)
                    body = pose_result.pose_landmarks.landmark if pose_result.pose_landmarks else None
                    hand_result = hands.process(rgb)
                    measured = self.extract_hand(hand_result, frame, body, settings)
                monitor.calibration_seconds = settings["web"]["calibration_seconds"]
                self.publish_writing(monitor.update(measured, time.monotonic(), settings["alert_seconds"]), revision, hand_revision, measured)
                from tracking_overlay import draw_tracking, demo_landmarks
                if self.args.demo:
                    demo_pose, demo_hand = demo_landmarks(body=False)
                    draw_tracking(frame, hand=demo_hand, simulated=True)
                else:
                    draw_tracking(frame, pose=body, hand=self.selected_hand(hand_result, settings))
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                with self.lock:
                    if ok and revision == self.revision and self.started and not self.paused:
                        self.frames["writing"] = encoded.tobytes()
                self.stop.wait(.08)
        except Exception as exc:
            self.publish_writing({"phase": "positioning", "confidence": "Unavailable", "status": f"Hand tracker stopped ({type(exc).__name__}). Restart the server.", "metrics": [], "guidance": [], "warning": False}, revision, hand_revision)
        finally:
            if capture is not None:
                capture.release()
            stack.close()

    def worker(self, name):
        import cv2
        from main import Monitor, demo_measurement, open_side_capture
        from posture_detector import Thresholds
        from debug_tui import landmark_visibility
        from eye_detector import measure_eyes
        from fatigue_detector import FatigueMonitor
        from contextlib import ExitStack
        capture = None
        identity = None
        monitor = None
        previous = None
        retry_at = 0
        stack = ExitStack()
        pose = face = hands = None
        from writing_detector import WritingMonitor
        writing_monitor = WritingMonitor()
        fatigue_monitor = FatigueMonitor()
        hand_revision = None
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
                    monitor = Monitor(new_identity[1], settings["alert_seconds"], settings["web"]["calibration_seconds"])
                    fatigue_monitor.reset()
                    identity = new_identity
                    demo_start = time.monotonic()
                    previous = None
                    retry_at = 0
                    if pose:
                        pose.reset()
                    if face:
                        face.reset()
                if hand_revision != (revision, self.writing_revision):
                    writing_monitor.reset()
                    hand_revision = (revision, self.writing_revision)
                now = time.monotonic()
                monitor.alert.delay_seconds = settings["alert_seconds"]
                monitor.calibration_seconds = settings["web"]["calibration_seconds"]
                writing_monitor.calibration_seconds = settings["web"]["calibration_seconds"]
                monitor.activity.reminder_seconds = settings["web"]["break_minutes"] * 60
                scale = {"gentle": 1.35, "balanced": 1, "sensitive": .75}[settings["web"]["sensitivity"]]
                monitor.detector.thresholds = Thresholds(**{
                    key: (1 + (value - 1) * scale if key == "face_scale_ratio" else value * scale)
                    for key, value in asdict(Thresholds()).items()})
                hand_points = None
                if self.args.demo:
                    import numpy as np
                    frame = np.full((540, 960, 3), (43, 52, 42), dtype=np.uint8)
                    cv2.putText(frame, "DEMO / SYNTHETIC FEED", (55, 68), cv2.FONT_HERSHEY_SIMPLEX, .6, (210, 230, 210), 2)
                    cv2.putText(frame, "No camera is being used", (55, 92), cv2.FONT_HERSHEY_SIMPLEX, .5, (180, 200, 180), 1)
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
                if name == "front" and settings["web"]["writing_enabled"] and not settings["web"]["writing_source"]:
                    if self.args.demo:
                        from writing_detector import HandMeasurement
                        hand_measurement = HandMeasurement(.25 + (.5 if (now - demo_start) % 25 > 12 else 0), .15, 8.)
                    else:
                        if hands is None:
                            import mediapipe as mp
                            hands = stack.enter_context(mp.solutions.hands.Hands(max_num_hands=2, min_detection_confidence=.65, min_tracking_confidence=.65))
                        hand_result = hands.process(rgb)
                        hand_points = self.selected_hand(hand_result, settings)
                        hand_measurement = self.extract_hand(hand_result, frame, landmarks, settings)
                    self.publish_writing(writing_monitor.update(hand_measurement, now, settings["alert_seconds"]), revision, hand_revision[1], hand_measurement)
                snap = monitor.update(measured, now, fps, visibility, name, eyes)
                data = describe_snapshot(snap, monitor.detector)
                if name == "front":
                    data["fatigue"] = asdict(fatigue_monitor.update(snap.eye, now))
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
                from tracking_overlay import draw_tracking, demo_landmarks
                if self.args.demo:
                    demo_pose, demo_hand = demo_landmarks(body=measured is not None,
                        hand=name == 'front' and settings['web']['writing_enabled'] and not settings['web']['writing_source'])
                    data['overlay'] = draw_tracking(frame, pose=demo_pose, hand=demo_hand, simulated=True)
                else:
                    data['overlay'] = draw_tracking(frame, pose=landmarks, face=face_landmarks, hand=hand_points)
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
            if content_type == 'application/x-ndjson':
                self.send_header('Content-Disposition', 'attachment; filename="writing-recording.jsonl"')
            if content_type.startswith("text/csv"):
                self.send_header("Content-Disposition", 'attachment; filename="still-sessions.csv"')
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
            if path == "/api/analytics":
                identifier = parse_qs(urlparse(self.path).query).get("id", [None])[0]
                if identifier is not None:
                    detail = dashboard.analytics.detail(identifier)
                    return self.reply(200, {"session": detail}) if detail else self.reply(404, {"error": "Session not found."})
                return self.reply(200, {"current": dashboard.analytics.summary(), "history": dashboard.analytics.history(), "error": dashboard.analytics.error})
            if path == '/api/writing-recording.jsonl':
                with dashboard.lock:
                    content = dashboard.writing_recorder.export()
                return self.reply(200, content.encode(), 'application/x-ndjson')
            if path == "/api/export.csv":
                return self.reply(200, dashboard.analytics.export_csv(), "text/csv; charset=utf-8")
            if path == "/api/session":
                return self.reply(200, {"token": dashboard.token})
            if path.startswith("/feed/"):
                name = path.rsplit("/", 1)[-1].removesuffix(".jpg")
                with dashboard.lock:
                    frame = dashboard.frames.get(name)
                return self.reply(200, frame, "image/jpeg") if frame else self.reply(503, {"error": "Waiting for camera"})
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
                      "/sw.js": ("sw.js", "application/javascript"), "/icon.svg": ("icon.svg", "image/svg+xml"),
                      "/app.js": ("app.js", "application/javascript"), "/i18n.js": ("i18n.js", "application/javascript"),
                      "/style.css": ("style.css", "text/css")}
            if path in assets:
                filename, mime = assets[path]
                return self.reply(200, (Path(__file__).parent / "web" / filename).read_bytes(), mime)
            self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if not self.allowed() or self.headers.get("X-Dashboard-Token") != dashboard.token:
                return self.reply(403, {"error": "Reload the dashboard to reconnect."})
            path = urlparse(self.path).path
            if path != '/api/command':
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


def open_app_window(url):
    """Use an installed browser's app window; never installs another runtime."""
    import os
    import shutil
    import subprocess
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"),
    ]
    candidates.extend(filter(None, (shutil.which(name) for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"))))
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                subprocess.Popen([candidate, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                continue
    return False


def run_web(args):
    dashboard = Dashboard(args)
    server = Server(("127.0.0.1", args.port), make_handler(dashboard))
    dashboard.launch()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Posture Monitor: {url}\nOpen Still and choose Start session. Press Ctrl+C here to stop.", flush=True)
    if not args.no_browser:
        if not getattr(args, "app", False) or not open_app_window(url):
            webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        dashboard.stop.set()
        dashboard.analytics.finish()
        server.server_close()
        for thread in dashboard.threads:
            thread.join(timeout=4)
    return 0
