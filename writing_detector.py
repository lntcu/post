"""Personal hand, marked-pen, and optional sensor reference measurements."""
from dataclasses import dataclass, field
import math
import statistics


@dataclass(frozen=True)
class HandMeasurement:
    pinch_ratio: float
    finger_curl: float
    wrist_degrees: float | None = None
    features: dict = field(default_factory=dict)
    geometry_source: str = "image"


# Candidate features; thresholds are initial reference-deviation allowances, not
# validated ergonomic cutoffs. Correlated features share a scoring family.
FEATURES = (
    ('index_pip', 'Index middle joint', 15., '°', 'fingers'),
    ('index_dip', 'Index end joint', 15., '°', 'fingers'),
    ('middle_pip', 'Middle finger middle joint', 15., '°', 'fingers'),
    ('middle_dip', 'Middle finger end joint', 15., '°', 'fingers'),
    ('thumb_mcp', 'Thumb base joint', 15., '°', 'fingers'),
    ('thumb_ip', 'Thumb end joint', 15., '°', 'fingers'),
    ('thumb_opposition', 'Thumb to middle finger', .25, 'palm widths', 'fingers'),
    ('finger_spread', 'Index–middle spacing', .25, 'palm widths', 'fingers'),
    ('pen_angle', 'Pen angle to hand in image', 15., '°', 'pen'),
    ('pen_thumb_distance', 'Thumb to pen shaft in image', .2, 'palm widths', 'pen'),
    ('pen_index_distance', 'Index to pen shaft in image', .2, 'palm widths', 'pen'),
    ('pen_middle_distance', 'Middle finger to pen shaft in image', .2, 'palm widths', 'pen'),
    ('pen_hold_position', 'Hold position from blue marker', .3, 'palm widths', 'pen'),
    ('grip_force', 'Grip sensor force', 1., 'N', 'pressure'),
    ('tip_force', 'Pen tip sensor force', .5, 'N', 'pressure'),
)


def joint_angle(points, a, b, c):
    u = tuple(x-y for x, y in zip(points[a], points[b]))
    v = tuple(x-y for x, y in zip(points[c], points[b]))
    norm = math.sqrt(sum(x*x for x in u) * sum(x*x for x in v))
    return math.degrees(math.acos(max(-1., min(1., sum(x*y for x, y in zip(u, v)) / norm)))) if norm > 1e-12 else None


def measure_hand(landmarks, width, height, pose=None, world=None, pen=None, pressure=None):
    if landmarks is None or len(landmarks) != 21 or width <= 0 or height <= 0:
        return None
    points = [(float(p.x) * width, float(p.y) * height) for p in landmarks]
    if any(not math.isfinite(v) for point in points for v in point):
        return None
    if any(not (-.05 * width <= x <= 1.05 * width and -.05 * height <= y <= 1.05 * height) for x, y in points):
        return None
    palm = math.dist(points[5], points[17])
    if palm < 25:
        return None
    pinch = math.dist(points[4], points[8]) / palm
    # Index fingertip to knuckle relative to all three finger segments.
    span = sum(math.dist(points[a], points[b]) for a, b in ((5, 6), (6, 7), (7, 8)))
    curl = 1 - min(1., math.dist(points[5], points[8]) / max(span, 1))
    wrist = None
    if pose and len(pose) > 16:
        candidates = []
        for elbow, wrist_index in ((13, 15), (14, 16)):
            e, w = pose[elbow], pose[wrist_index]
            if min(getattr(e, 'visibility', 0), getattr(w, 'visibility', 0)) < .65:
                continue
            wp = (w.x * width, w.y * height)
            ep = (e.x * width, e.y * height)
            if not all(math.isfinite(v) for v in (*wp, *ep)):
                continue
            if math.dist(wp, points[0]) < palm * .7 and math.dist(ep, wp) > palm:
                candidates.append((math.dist(wp, points[0]), ep, wp))
        if candidates:
            _, ep, wp = min(candidates)
            forearm = (wp[0] - ep[0], wp[1] - ep[1])
            hand = (points[9][0] - points[0][0], points[9][1] - points[0][1])
            norm = math.hypot(*forearm) * math.hypot(*hand)
            if norm > 1:
                wrist = math.degrees(math.acos(max(-1., min(1., (forearm[0] * hand[0] + forearm[1] * hand[1]) / norm))))
    geometry = points
    source = 'image'
    if world is not None and len(world) == 21:
        candidate = [(float(p.x), float(p.y), float(p.z)) for p in world]
        if all(math.isfinite(v) for point in candidate for v in point) and math.dist(candidate[5], candidate[17]) > 1e-6:
            geometry, source = candidate, 'world'
    scale = math.dist(geometry[5], geometry[17])
    pinch = math.dist(geometry[4], geometry[8]) / scale
    span = sum(math.dist(geometry[a], geometry[b]) for a, b in ((5, 6), (6, 7), (7, 8)))
    curl = 1 - min(1., math.dist(geometry[5], geometry[8]) / max(span, 1e-12))
    features = {}
    for name, indices in (('index_pip', (5, 6, 7)), ('index_dip', (6, 7, 8)),
                          ('middle_pip', (9, 10, 11)), ('middle_dip', (10, 11, 12)),
                          ('thumb_mcp', (1, 2, 3)), ('thumb_ip', (2, 3, 4))):
        value = joint_angle(geometry, *indices)
        if value is not None:
            features[name] = value
    features['thumb_opposition'] = math.dist(geometry[4], geometry[12]) / scale
    features['finger_spread'] = math.dist(geometry[8], geometry[12]) / scale
    from pen_detector import pen_features
    features.update(pen_features(pen, points, palm))
    if pressure:
        features.update(pressure)
    return HandMeasurement(pinch, curl, wrist, features, source)


class WritingMonitor:
    def __init__(self, calibration_seconds=4):
        self.calibration_seconds = calibration_seconds
        self.reset()

    def reset(self):
        self.baseline = None
        self.samples = []
        self.since = None
        self.last_seen = None
        self.sample_time = None
        self.calibration_elapsed = 0.
        self.changed_since = None
        self.issue_since = {}
        self.recent = []
        self.thresholds = (.35, .2, 15.)
        self.feature_baselines = {}
        self.feature_thresholds = {}

    def clear_tracking(self):
        self.recent.clear()
        self.issue_since.clear()
        self.changed_since = None

    def update(self, measured, now, delay=5):
        limit = 'Compares measured hand, marked-pen, and optional sensor geometry with your reference. Camera features do not measure force or pen contact. Comfort and grip correctness cannot be determined.'
        if measured is not None and (not all(math.isfinite(v) for v in (measured.pinch_ratio, measured.finger_curl))
                                     or measured.pinch_ratio < 0 or not 0 <= measured.finger_curl <= 1):
            measured = None
        if measured is not None and measured.wrist_degrees is not None and not 0 <= measured.wrist_degrees <= 180:
            measured = HandMeasurement(measured.pinch_ratio, measured.finger_curl, features=measured.features, geometry_source=measured.geometry_source)
        if measured is not None and measured.geometry_source not in ('image', 'world'):
            measured = None
        if measured is not None:
            # Only known, finite features can enter calibration or recordings.
            clean = {key: value for key, value in measured.features.items()
                     if key in {f[0] for f in FEATURES} and type(value) in (int, float) and math.isfinite(value)}
            measured = HandMeasurement(measured.pinch_ratio, measured.finger_curl, measured.wrist_degrees, clean, measured.geometry_source)
        if measured is None:
            # Brief landmark misses pause calibration instead of erasing it.
            if self.last_seen is None or now - self.last_seen > .75:
                self.samples.clear()
                self.since = None
                self.calibration_elapsed = 0.
                self.last_seen = None
            self.sample_time = None
            self.clear_tracking()
            return {'phase': 'positioning', 'confidence': 'Unavailable', 'status': 'Show your writing hand',
                    'hint': 'Keep the wrist, thumb, and index finger visible. A close desk view works best.',
                    'calibrated': self.baseline is not None,
                    'remaining': max(0, self.calibration_seconds - self.calibration_elapsed), 'metrics': [], 'guidance': [], 'warning': False, 'changed': False, 'limitation': limit}
        if self.baseline is None and self.samples and measured.geometry_source != self.samples[-1].geometry_source:
            self.samples.clear()
            self.calibration_elapsed = 0.
            self.sample_time = None
        if self.last_seen is not None and now - self.last_seen > .75:
            self.samples.clear()
            self.since = None
            self.calibration_elapsed = 0.
            self.sample_time = None
            self.clear_tracking()
        self.last_seen = now
        if self.baseline is None:
            # Allow writing strokes, but restart after a large grip/view change.
            if self.samples and (abs(measured.pinch_ratio - statistics.median(s.pinch_ratio for s in self.samples)) > .6
                                 or abs(measured.finger_curl - statistics.median(s.finger_curl for s in self.samples)) > .35):
                self.samples.clear()
                self.since = None
                self.calibration_elapsed = 0.
                self.sample_time = None
            if self.since is None:
                self.since = now
            if self.sample_time is not None:
                self.calibration_elapsed += max(0, now - self.sample_time)
            self.sample_time = now
            self.samples.append(measured)
            if self.calibration_elapsed >= self.calibration_seconds - 1e-9 and len(self.samples) >= 15:
                wrist_values = [s.wrist_degrees for s in self.samples if s.wrist_degrees is not None]
                self.baseline = HandMeasurement(statistics.median(s.pinch_ratio for s in self.samples),
                                                statistics.median(s.finger_curl for s in self.samples),
                                                statistics.median(wrist_values) if len(wrist_values) >= max(15, .7 * len(self.samples)) else None,
                                                geometry_source=measured.geometry_source)
                for key, _, floor, _, _ in FEATURES:
                    values = [s.features[key] for s in self.samples if key in s.features]
                    if len(values) >= max(15, .7 * len(self.samples)):
                        center = statistics.median(values)
                        spread = statistics.median(abs(v - center) for v in values)
                        self.feature_baselines[key] = center
                        self.feature_thresholds[key] = min(floor * 1.75, max(floor, spread * 3))
                # A robust personal movement allowance, bounded so noisy setup
                # cannot silently disable future cues. Never adapt during monitoring.
                thresholds = []
                for attr, floor in zip(('pinch_ratio', 'finger_curl', 'wrist_degrees'), self.thresholds):
                    values = [getattr(s, attr) for s in self.samples if getattr(s, attr) is not None]
                    center = getattr(self.baseline, attr)
                    spread = statistics.median(abs(v - center) for v in values) if center is not None else 0
                    thresholds.append(min(floor * 1.75, max(floor, spread * 3)))
                self.thresholds = tuple(thresholds)
                self.samples.clear()
            else:
                return {'phase': 'calibrating', 'confidence': 'Setting up', 'status': 'Learning your hand reference',
                        'calibrated': False,
                        'hint': 'Write normally across the page for twelve seconds. Keep the camera and hand angle steady.',
                        'remaining': max(0, self.calibration_seconds - self.calibration_elapsed), 'metrics': [], 'guidance': [],
                        'warning': False, 'changed': False, 'limitation': limit}
        base = self.baseline
        if measured.geometry_source != base.geometry_source:
            self.clear_tracking()
            return {'phase': 'positioning', 'confidence': 'Unavailable', 'status': 'Hand coordinate source changed',
                    'calibrated': True,
                    'hint': 'Restore the previous tracking view or reset the hand reference.',
                    'metrics': [], 'guidance': [], 'warning': False, 'changed': False, 'limitation': limit}

        self.recent = [(t, sample) for t, sample in self.recent if 0 <= now - t <= .3][-4:]
        self.recent.append((now, measured))
        # Smooth finger landmark jumps; a missing elbow stays unavailable.
        measured = HandMeasurement(
            statistics.median(s.pinch_ratio for _, s in self.recent),
            statistics.median(s.finger_curl for _, s in self.recent),
            statistics.median(s.wrist_degrees for _, s in self.recent if s.wrist_degrees is not None)
            if measured.wrist_degrees is not None else None,
            {key: statistics.median(s.features[key] for _, s in self.recent if key in s.features)
             for key in measured.features}, measured.geometry_source)
        rows = []
        guidance = []
        for index, (name, value, reference, threshold, unit, cue) in enumerate((
            ('Thumb–index spacing', measured.pinch_ratio, base.pinch_ratio, .35, 'palm widths', 'Thumb–index spacing changed. Set the pen down, then pick it up with a light, comfortable grip. Check that you can move it without squeezing.'),
            ('Index curl', measured.finger_curl, base.finger_curl, .2, 'ratio', 'Index curl changed. Pause and release finger tension, then try a few light strokes with a grip that feels controlled.'),
            ('Wrist alignment in image', measured.wrist_degrees, base.wrist_degrees, 15, '°', 'Wrist alignment changed in the image. Try turning the paper and supporting your forearm so your wrist feels relaxed. Keep the camera steady.'),
        )):
            threshold = self.thresholds[index]
            available = value is not None and reference is not None
            delta = value - reference if available else None
            issue = available and abs(delta) >= threshold
            rows.append({'name': name, 'delta': delta if available else None, 'available': available,
                         'threshold': threshold, 'unit': unit, 'issue': issue, 'guidance': cue,
                         'family': 'wrist' if index == 2 else 'fingers'})
            if issue:
                guidance.append(cue)
                self.issue_since.setdefault(name, now)
            else:
                self.issue_since.pop(name, None)
        for key, name, _, unit, family in FEATURES:
            value, reference = measured.features.get(key), self.feature_baselines.get(key)
            available = value is not None and reference is not None
            threshold = self.feature_thresholds.get(key, next(f[2] for f in FEATURES if f[0] == key))
            delta = value - reference if available else None
            issue = available and abs(delta) >= threshold
            cue = f'{name} changed from your writing reference. Check your pen position and control.'
            if family == 'pressure':
                cue = f'{name} changed from your reference. Check the sensor reading and how writing feels.'
            rows.append({'name': name, 'key': key, 'value': value, 'reference': reference,
                         'delta': delta if available else None, 'available': available,
                         'threshold': threshold, 'unit': unit, 'issue': issue, 'guidance': cue, 'family': family})
            if issue:
                guidance.append(cue)
                self.issue_since.setdefault(name, now)
            else:
                self.issue_since.pop(name, None)
        changed = bool(guidance)
        self.changed_since = (self.changed_since if self.changed_since is not None else now) if changed else None
        warning = any(row['issue'] and abs(row['delta']) >= row['threshold'] * 1.35
                      and now - self.issue_since.get(row['name'], now) >= delay * 2
                      for row in rows)
        expected = [r for r in rows if r.get('family') != 'pressure' or r.get('reference') is not None]
        full = all(row['available'] for row in expected)
        family_scores = {}
        for family in ('fingers', 'wrist', 'pen', 'pressure'):
            group = [r for r in rows if r.get('family') == family and r['available']]
            family_scores[family] = round(100 * statistics.mean(1 - min(abs(r['delta']) / r['threshold'], 2) / 2 for r in group)) if group else None
        return {'phase': 'monitoring', 'confidence': 'Available' if full else 'Limited',
                'calibrated': True,
                'status': 'Hand position changed' if changed else 'Visible grip cues near reference',
                'hint': 'Your writing movement range is learned. Relearn after switching grip, writing style, or camera angle. Wrist alignment needs the elbow in view.',
                'geometry_source': measured.geometry_source, 'family_scores': family_scores,
                'pen_observed': 'pen_angle' in measured.features,
                'remaining': 0, 'metrics': rows, 'guidance': guidance, 'changed': changed,
                'warning': warning, 'limitation': limit}
