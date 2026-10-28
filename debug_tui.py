"""Read-only terminal dashboard for camera measurements."""

from __future__ import annotations

import curses
from dataclasses import dataclass

from alerts import AlertTimer
from activity_monitor import ActivityAssessment
from eye_detector import EyeAssessment
from posture_detector import Assessment, Measurements, PostureDetector


@dataclass
class DebugSnapshot:
    phase: str
    assessment: Assessment
    measured: Measurements | None
    calibration_remaining: float
    poor_seconds: float
    warning: bool
    fps: float
    landmarks: dict[str, float | None]
    source: str
    eye: EyeAssessment = EyeAssessment("Not Detected")
    activity: ActivityAssessment = ActivityAssessment()
    calibration_hint: str = ""


class Dashboard:
    def __init__(self, screen: curses.window) -> None:
        self.screen = screen
        self.colors_enabled = False
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.nodelay(True)
        screen.keypad(True)
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_RED, -1)
            self.colors_enabled = True
        except curses.error:
            pass

    def input(self, detector: PostureDetector, alert: AlertTimer | None = None) -> str | None:
        key = self.screen.getch()
        if key in (ord("q"), ord("Q"), 27):
            return "quit"
        if key in (ord("r"), ord("R")):
            return "recalibrate"
        if key in (ord("v"), ord("V")):
            choices = ("auto", "front", "side")
            detector.view = choices[(choices.index(detector.view) + 1) % len(choices)]
            return "recalibrate"
        return None

    def draw(self, snap: DebugSnapshot, detector: PostureDetector, alert: AlertTimer,
             side_snap: DebugSnapshot | None = None,
             side_detector: PostureDetector | None = None) -> None:
        screen = self.screen
        screen.erase()
        height, width = screen.getmaxyx()
        needed = 39 if side_snap is not None else 31
        if height < needed or width < 80:
            self._line(0, f"Resize terminal to at least 80 x {needed}")
            screen.refresh()
            return

        def shown(value, digits=2):
            return f"{value:.{digits}f}" if value is not None else "--"

        current, base, t = snap.measured, detector.baseline, detector.thresholds
        posture_color = 3 if snap.warning else (1 if snap.assessment.status == "Good" else 2)
        eye_color = 3 if snap.eye.warning else (1 if snap.eye.status == "Tracking" else 2)
        self._line(0, "POSTURE + EYE MONITOR     Q quit | R recalibrate | V view", curses.A_BOLD)
        self._line(1, f"{snap.source}   FPS {snap.fps:.1f}   View {detector.view}   Phase {snap.phase}")
        self._line(2, f"POSTURE  {snap.assessment.status}   Score {snap.assessment.score if snap.assessment.score is not None else '--'}",
                   curses.color_pair(posture_color) if self.colors_enabled else 0)
        self._line(3, f"Indicators: {', '.join(snap.assessment.reasons) or '--'}")
        self._line(4, f"Warning {'ACTIVE' if snap.warning else 'off'}   Poor {snap.poor_seconds:.1f}/{alert.delay_seconds:.1f}s   Calibrate {snap.calibration_remaining:.1f}s")
        if snap.calibration_hint:
            self._line(15, f"Calibration: {snap.calibration_hint}")
        self._line(5, "POSE INDICATOR           Current    Baseline      Delta      Limit", curses.A_BOLD)
        metrics = (
            ("Torso angle (deg)", "torso_angle", t.torso_degrees, 1),
            ("Shoulder tilt (deg)", "shoulder_angle", t.shoulder_degrees, 1),
            ("Forward head (neck)", "head_forward", t.head_forward_ratio, 2),
            ("Head tilt (deg)", "head_tilt", t.head_tilt_degrees, 1),
            ("Head turn (face)", "head_turn", t.head_turn_ratio, 2),
            ("Shoulder gap (torso)", "shoulder_clearance", t.shoulder_elevation_ratio, 2),
            ("Elbow spread (torso)", "elbow_spread", t.elbow_spread_ratio, 2),
        )
        for row, (label, name, limit, digits) in enumerate(metrics, 6):
            value = getattr(current, name) if current else None
            reference = getattr(base, name) if base else None
            if name == "shoulder_angle" and current and current.view != "front":
                value = reference = None
            change = value - reference if value is not None and reference is not None else None
            self._line(row, f"{label:<24} {shown(value, digits):>8}   {shown(reference, digits):>8}   {shown(change, digits):>8}   {limit:.2f}")
        scale = (current.face_width / base.face_width
                 if current and base and current.face_width is not None and base.face_width else None)
        self._line(13, f"Face size / baseline: {shown(scale)}    Closer cue at {t.face_scale_ratio:.2f}x")
        self._line(14, f"Nearly still: {snap.activity.still_seconds / 60:.1f} min    Break reminder: {'ACTIVE' if snap.activity.warning else 'off'}")
        self._line(16, f"EYES  {snap.eye.status}", curses.color_pair(eye_color) if self.colors_enabled else 0)
        self._line(17, f"Indicators: {', '.join(snap.eye.reasons) or '--'}")
        eye = snap.eye
        self._line(18, f"Eye ratio: L {shown(eye.left_ratio, 3)}   R {shown(eye.right_ratio, 3)}   mean {shown(eye.openness, 3)}")
        self._line(19, f"Open reference {shown(eye.open_baseline, 3)}   Closed cutoff {shown(eye.closed_threshold, 3)}")
        self._line(20, f"Blinks (60s) {eye.blink_count}   Estimated rate {shown(eye.blinks_per_minute, 1)}/min")
        fraction = 100 * eye.closed_fraction if eye.closed_fraction is not None else None
        self._line(21, f"Closed now {eye.closed_seconds:.1f}s   Closed fraction {shown(fraction, 0)}%")
        self._line(22, f"Since blink {eye.since_blink:.1f}s   {eye.warning or ''}")
        self._line(24, "POSE LANDMARK VISIBILITY (0-1)", curses.A_BOLD)
        names = ("nose", "left ear", "right ear", "left shoulder", "right shoulder",
                 "left elbow", "right elbow", "left hip", "right hip")
        bits = [f"{name} {shown(snap.landmarks.get(name), 2)}" for name in names]
        self._line(25, "   ".join(bits[:3]))
        self._line(26, "   ".join(bits[3:6]))
        self._line(27, "   ".join(bits[6:]))
        self._line(29, "Face size is relative to calibration; a webcam cannot measure screen distance.")
        if side_snap is not None and side_detector is not None:
            side = side_snap.measured
            base = side_detector.baseline
            self._line(31, "PHONE SIDE VIEW", curses.A_BOLD)
            self._line(32, f"{side_snap.source}   {side_snap.phase}   Posture {side_snap.assessment.status}   Score {side_snap.assessment.score if side_snap.assessment.score is not None else '--'}")
            self._line(33, f"Indicators: {', '.join(side_snap.assessment.reasons) or '--'}")
            self._line(34, f"Warning {'ACTIVE' if side_snap.warning else 'off'}   Poor {side_snap.poor_seconds:.1f}s   Calibration {side_snap.calibration_remaining:.1f}s")
            self._line(35, f"Torso angle: {shown(side.torso_angle if side else None, 1)}   Baseline: {shown(base.torso_angle if base else None, 1)}")
            self._line(36, f"Forward head: {shown(side.head_forward if side else None)}   Baseline: {shown(base.head_forward if base else None)}")
            self._line(37, f"Calibration: {side_snap.calibration_hint or 'Ready'}")
        screen.refresh()

    def _line(self, row: int, value: str, attr: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if row < height:
            try:
                self.screen.addnstr(row, 0, value, max(0, width - 1), attr)
            except curses.error:
                pass


def landmark_visibility(landmarks) -> dict[str, float | None]:
    indices = {"nose": 0, "left ear": 7, "right ear": 8, "left shoulder": 11,
               "right shoulder": 12, "left elbow": 13, "right elbow": 14,
               "left hip": 23, "right hip": 24}
    return {
        name: float(landmarks[index].visibility) if landmarks is not None and len(landmarks) > index else None
        for name, index in indices.items()
    }
