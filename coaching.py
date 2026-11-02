"""Reference-based writing and posture coaching, independent of reminder delivery."""
from __future__ import annotations
import math

ONE_SIDED = {'Raised shoulders', 'Elbows away from body', 'Forward head', 'Closer to camera'}
SEVERITIES = {'neutral': 0, 'success': 1, 'suggestion': 2, 'warning': 3, 'attention': 4}


def instantaneous_alignment(state):
    """Equal-weight live subscores, including the same eye cues as the UI."""
    scores = [p['score'] for p in state.get('coaching', {}).get('parts', [])
              if isinstance(p.get('score'), (int, float)) and math.isfinite(p['score']) and not p.get('exclude_from_overall')]
    front = state.get('cameras', {}).get('front', {})
    eye = front.get('eye', {})
    if (not front.get('error') and eye.get('confidence') != 'Unavailable'
            and all(isinstance(eye.get(key), (int, float)) and math.isfinite(eye[key])
                    for key in ('openness', 'blinks_per_minute', 'closed_fraction'))):
        cues = {'Prolonged closure', 'Eyes closed often', 'Low blink rate', 'Long time without a blink'}
        scores.append(100 - 25 * len(cues.intersection(eye.get('reasons', []))))
    return sum(scores) / len(scores) if scores else None


def assessment(source, label, live=True, hand=False):
    rows = source.get('metrics', [])
    available = [r for r in rows if r.get('available') and r.get('delta') is not None and r.get('threshold', 0) > 0]
    tracked = live and not source.get('error') and source.get('phase') == 'monitoring' and bool(available)
    if not tracked:
        return {'label': label, 'score': None, 'severity': 'neutral', 'coverage': 'Unavailable',
                'status': source.get('error') or source.get('status') or 'Set up tracking',
                'guidance': [source.get('hint') or source.get('calibration_hint') or 'Start a session and keep the required landmarks visible.']}
    ratios = [(max(0, r['delta']) if not hand and r['name'] in ONE_SIDED else abs(r['delta'])) / r['threshold'] for r in available]
    changed = any(r.get('issue') for r in available)
    severity = ('attention' if max(ratios) >= 2 else 'warning') if changed and source.get('warning') else 'suggestion' if changed else 'success'
    cues = [r['guidance'] for r in available if r.get('issue') and r.get('guidance')]
    score = round(100 * sum(1 - min(r, 2) / 2 for r in ratios) / len(ratios))
    if hand and source.get('family_scores'):
        # Additional correlated finger features must not drown out wrist or pen.
        families = [v for v in source['family_scores'].values() if v is not None]
        score = round(sum(families) / len(families)) if families else None
    return {'label': label, 'score': score,
            'severity': severity, 'coverage': 'Available' if len(available) == len(rows) else 'Limited',
            'status': 'Review your position' if severity == 'attention' else 'Adjustment needed' if severity == 'warning' else 'Adjustment suggested' if changed else 'Near your reference',
            'guidance': cues or ['Keep your movement relaxed. Pause and change position when you need to.']}


def writing_posture_guidance(cameras):
    """Adapt body corrections to paper work instead of directing eyes at a screen."""
    from main import POSTURE_GUIDANCE
    cues = {
        'Torso lean': 'Torso position changed. Bring the paper within reach and check that your back and forearm feel supported.',
        'Head turn': 'Head position changed. Turn the paper to a comfortable angle rather than twisting your neck to follow the line.',
        'Head tilt': 'Head tilt changed. Adjust the paper position so you can see your writing without holding your neck at an awkward angle.',
        'Forward head': 'Your head is further forward. Bring the page into a comfortable view and check your forearm support.',
        'Raised shoulders': 'Shoulders raised. Pause, let them relax, and check that the writing surface and forearm support feel comfortable.',
        'Elbows away from body': 'Arm position changed. Move the paper within easy reach and support your forearm without holding your shoulder tense.',
        'Closer to camera': 'You moved closer to the camera. Check the page position and lighting, then return to a comfortable writing distance.',
    }
    replacements = {POSTURE_GUIDANCE[name]: cue for name, cue in cues.items()}
    for camera in cameras.values():
        camera['guidance'] = [replacements.get(cue, cue) for cue in camera.get('guidance', [])]
        for row in camera.get('metrics', []):
            if row['name'] in cues:
                row['guidance'] = cues[row['name']]


def build_coaching(cameras, writing, writing_enabled, live, side_enabled=False):
    parts = [assessment(cameras.get('front', {}), 'Posture', live)]
    if side_enabled:
        parts.append(assessment(cameras.get('side', {}), 'Side posture', live))
    if writing_enabled:
        parts.append(assessment(writing, 'Grip & wrist', live, hand=True))
    scored_parts = [p for p in parts if not p.get('exclude_from_overall')]
    complete = bool(scored_parts) and all(p['score'] is not None for p in scored_parts)
    score = round(sum(p['score'] for p in scored_parts) / len(scored_parts)) if complete else None
    severity = max((p['severity'] for p in parts), key=SEVERITIES.get) if complete else 'neutral'
    return {'score': score, 'severity': severity, 'parts': parts,
            'coverage': 'Unavailable' if not complete else 'Limited' if any(p['coverage'] == 'Limited' for p in parts) else 'Available',
            'description': 'Reference alignment, 0–100. Each camera has equal weight; visible measurements are averaged within each body camera; writing averages available finger, wrist, pen and sensor families. 100 means no measured deviation; a change at the alert threshold scores 50. Hidden measurements are excluded. This is not a health, grip correctness, or handwriting quality score.'}
