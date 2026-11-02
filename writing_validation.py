"""Opt-in landmark recording and participant-held-out change-model validation.

No video is recorded. A learned prediction describes the supplied labels; it is
not a validated assessment of grip correctness, comfort, or pressure.
"""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import secrets

LABELS = ('normal', 'grip_change', 'camera_rotation', 'tracking_failure')
SCHEMA = 'writing-observations-v1'


class WritingRecorder:
    def __init__(self):
        self.active = False
        self.frames = []
        self.metadata = {}
        self.last_time = None
        self.started_at = None
        self.label = 'normal'

    def start(self, participant, style, now):
        if self.active:
            raise ValueError('Finish the current recording first.')
        if not isinstance(participant, str) or not participant.strip() or len(participant) > 80:
            raise ValueError('Enter a participant alias of 1–80 characters.')
        if not isinstance(style, str) or len(style) > 80:
            raise ValueError('Writing style must be at most 80 characters.')
        self.metadata = {'schema': SCHEMA, 'participant': participant.strip(), 'style': style,
                         'session': secrets.token_hex(8)}
        self.frames = []
        self.label = 'normal'
        self.started_at = now
        self.last_time = None
        self.active = True

    def set_label(self, label):
        if label not in LABELS:
            raise ValueError('Choose normal, grip_change, camera_rotation, or tracking_failure.')
        if not self.active:
            raise ValueError('Start a recording before labeling it.')
        self.label = label

    def record(self, measured, result, now):
        if not self.active or (self.last_time is not None and now - self.last_time < .1):
            return
        if now - self.started_at > 600 or len(self.frames) >= 6000:
            self.active = False
            return
        self.last_time = now
        self.frames.append({'t': round(now - self.started_at, 4), 'label': self.label,
                            'measurement': asdict(measured) if measured else None,
                            'phase': result.get('phase'), 'metrics': result.get('metrics', []),
                            'warning': result.get('warning', False)})

    def status(self):
        return {'active': self.active, 'samples': len(self.frames), 'label': self.label,
                'participant': self.metadata.get('participant', '')}

    def export(self):
        return '\n'.join(json.dumps(item, allow_nan=False) for item in [self.metadata, *self.frames]) + '\n'


def feature_vector(rows, names):
    by_name = {r['name']: r for r in rows}
    values = []
    for name in names:
        row = by_name.get(name, {})
        valid = (row.get('available') and type(row.get('delta')) in (int, float)
                 and type(row.get('threshold')) in (int, float) and row['threshold'] > 0
                 and math.isfinite(row['delta']) and math.isfinite(row['threshold']))
        values.extend((min(4., abs(row['delta']) / row['threshold']) if valid else 0., float(bool(valid))))
    return values


class ChangeModel:
    def __init__(self, model):
        if not isinstance(model, dict) or model.get('schema') != 'writing-change-model-v1':
            raise ValueError('Unsupported writing model.')
        self.names = model['names']
        self.weights = model['weights']
        self.bias = model['bias']
        if (not isinstance(self.names, list) or not isinstance(self.weights, list)
                or not self.names or len(self.names) > 64 or any(not isinstance(n, str) for n in self.names)
                or len(set(self.names)) != len(self.names) or len(self.weights) != len(self.names) * 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in [self.bias, *self.weights])):
            raise ValueError('Invalid writing model coefficients.')
        self.report = model.get('validation', {})
        self.geometry_source = model.get('geometry_source')

    def predict(self, rows, geometry_source=None):
        if self.geometry_source and geometry_source and self.geometry_source != geometry_source:
            return None
        if not any(r.get('available') and r.get('name') in self.names for r in rows):
            return None
        vector = feature_vector(rows, self.names)
        z = self.bias + sum(a*b for a, b in zip(vector, self.weights))
        return round(1 / (1 + math.exp(-max(-30, min(30, z)))), 4)


def train(paths, holdout, output):
    import numpy as np
    records = []
    sessions = set()
    for path in paths:
        lines = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        metadata, *frames = lines
        if metadata.get('schema') != SCHEMA or not metadata.get('participant') or not metadata.get('session'):
            raise ValueError(f'{path}: unsupported or incomplete recording metadata.')
        if metadata.get('demo'):
            raise ValueError('Demo recordings contain synthetic data; use real writing sessions for training.')
        if metadata['session'] in sessions:
            raise ValueError('The same session was supplied more than once.')
        sessions.add(metadata['session'])
        for frame in frames:
            if frame.get('label') not in LABELS:
                raise ValueError(f'{path}: invalid label.')
            if frame.get('phase') != 'calibrating':
                records.append((metadata['participant'], metadata['session'], frame))
    training = [r for r in records if r[0] != holdout and r[2]['label'] != 'tracking_failure' and r[2].get('phase') == 'monitoring']
    testing = [r for r in records if r[0] == holdout]
    if not training or not testing:
        raise ValueError('Provide separate training participants and a held-out participant.')
    sources = {(f.get('measurement') or {}).get('geometry_source', 'image') for _, _, f in training}
    if len(sources) != 1:
        raise ValueError('Train image and world geometry models separately; do not mix coordinate sources.')
    geometry_source = sources.pop()
    # Feature selection uses training recordings only.
    names = sorted({row['name'] for _, _, f in training for row in f['metrics'] if row.get('available')})
    if not names:
        raise ValueError('Training recordings have no calibrated measurements.')
    x = np.array([feature_vector(f['metrics'], names) for _, _, f in training])
    y = np.array([float(f['label'] == 'grip_change') for _, _, f in training])
    if len(set(y)) != 2:
        raise ValueError('Training data needs both normal writing and labeled grip changes.')
    # Balance classes and sessions, so a long clip does not dominate learning.
    counts = {}
    for _, session, f in training:
        key = (session, f['label'] == 'grip_change')
        counts[key] = counts.get(key, 0) + 1
    sample_weights = np.array([1 / counts[(s, f['label'] == 'grip_change')] for _, s, f in training])
    for cls in (0, 1):
        sample_weights[y == cls] /= sample_weights[y == cls].sum()
    sample_weights /= sample_weights.sum()
    w = np.zeros(x.shape[1]); b = 0.
    for _ in range(1500):
        prediction = 1 / (1 + np.exp(-np.clip(x @ w + b, -30, 30)))
        error = (prediction - y) * sample_weights
        w -= .1 * (x.T @ error + .02 * w)
        b -= .1 * error.sum()
    model = {'schema': 'writing-change-model-v1', 'names': names, 'weights': w.tolist(), 'bias': float(b), 'geometry_source': geometry_source}
    predictor = ChangeModel(model)
    report = {'heldout_participant': holdout, 'training_participants': len({r[0] for r in training}),
              'training_sessions': len({r[1] for r in training}), 'threshold': .5, 'by_label': {}}
    for label in LABELS:
        frames = [f for _, _, f in testing if f['label'] == label]
        predictions = [predictor.predict(f['metrics'], (f.get('measurement') or {}).get('geometry_source', geometry_source)) for f in frames]
        assessed = [p for p in predictions if p is not None]
        positives = sum(p >= .5 for p in assessed)
        report['by_label'][label] = {'samples': len(frames), 'assessed': len(assessed),
                                     'predicted_changes': positives,
                                     'change_rate': positives / len(assessed) if assessed else None}
    if not report['by_label']['normal']['assessed'] or not report['by_label']['grip_change']['assessed']:
        raise ValueError('Held-out data needs assessable normal writing and grip changes.')
    # Count reference-warning onsets and observed normal-writing duration.
    # Do not bridge missing observations, pauses, label changes or sessions.
    seconds = 0.; false_alerts = 0
    previous = None
    for _, session, frame in testing:
        normal = frame['label'] == 'normal' and frame.get('phase') == 'monitoring'
        continuous = previous is not None and previous[0] == session and 0 < frame['t'] - previous[1]['t'] <= .75
        prior_normal = continuous and previous[1]['label'] == 'normal' and previous[1].get('phase') == 'monitoring'
        if normal and prior_normal:
            seconds += frame['t'] - previous[1]['t']
        if normal and frame.get('warning') and not (prior_normal and previous[1].get('warning')):
            false_alerts += 1
        previous = (session, frame)
    report['reference_normal_observed_seconds'] = round(seconds, 3)
    report['reference_false_alerts_per_minute'] = false_alerts * 60 / seconds if seconds else None
    report['normal_false_positive_rate'] = report['by_label']['normal']['change_rate']
    report['grip_change_recall'] = report['by_label']['grip_change']['change_rate']
    report['note'] = 'Frame-level held-out results; not clinical validation or proof of general accuracy.'
    model['validation'] = report
    Path(output).write_text(json.dumps(model, indent=2, allow_nan=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recordings', nargs='+', help='Exported JSONL recordings')
    parser.add_argument('--holdout-participant', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(train(args.recordings, args.holdout_participant, args.output), indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
