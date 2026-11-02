"""Time-weighted local session summaries. Never stores frames or landmarks."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import csv
import copy
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid


class Analytics:
    def __init__(self, path: Path, *, demo=False):
        self.path = Path(path)
        self.demo = demo
        self.lock = threading.RLock()
        self.session = None
        self.last_tick = None
        self.error = None
        self.last_save = 0

    def start(self, persist=True, now=None):
        with self.lock:
            self.finish()
            self.session = {"id": uuid.uuid4().hex, "started": datetime.now().astimezone().isoformat(timespec='milliseconds'),
                            "ended": None, "demo": self.demo, "active_seconds": 0., "tracked_seconds": 0.,
                            "near_seconds": 0., "changed_seconds": 0., "eye_seconds": 0., "eye_rate_sum": 0.,
                            "writing_seconds": 0., "writing_changed_seconds": 0., "movement_resets": 0,
                            "alignment_seconds": 0., "alignment_score_sum": 0.,
                            "issues": {}, "timeline": [], "persist": persist and not self.demo}
            self.last_tick = now
            self.last_still = None
            self.last_bin = None
            self.last_save = float("-inf")

    def record(self, state, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if not self.session or not state['started'] or state['paused']:
                self.last_tick = None
                self.last_still = None
                return
            if self.last_tick is None:
                self.last_tick = now
                return
            elapsed = now - self.last_tick
            self.last_tick = now
            if elapsed <= 0 or elapsed > 2.5:
                return  # Never interpolate an unobserved sleep or blocked process.
            session = self.session
            session['active_seconds'] += elapsed
            from coaching import instantaneous_alignment
            score = instantaneous_alignment(state)
            if score is not None:
                session['alignment_seconds'] += elapsed
                session['alignment_score_sum'] += score * elapsed
            front = state['cameras'].get('front', {})
            def tracked(camera):
                return (not camera.get('error') and camera.get('phase') == 'monitoring'
                        and camera.get('confidence') in ('Available', 'Limited')
                        and any(row['available'] for row in camera.get('metrics', [])))
            front_valid = tracked(front)
            sources = ['front']
            if state.get('settings', {}).get('web', {}).get('side_source') or 'side' in state['cameras']:
                sources.append('side')
            views = [(name, state['cameras'].get(name, {})) for name in sources]
            valid = all(tracked(camera) for _, camera in views)
            changed = valid and any(row['issue'] and row['available'] for _, camera in views for row in camera.get('metrics', []))
            if valid:
                session['tracked_seconds'] += elapsed
                session['changed_seconds' if changed else 'near_seconds'] += elapsed
                for name, camera in views:
                    for row in camera['metrics']:
                        if row['available'] and row['issue']:
                            label = f"{name.title()} · {row['name']}" if len(views) > 1 else row['name']
                            session['issues'][label] = session['issues'].get(label, 0) + elapsed
            eye = front.get('eye', {})
            rate = eye.get('blinks_per_minute')
            if not front.get('error') and rate is not None and eye.get('confidence') != 'Unavailable':
                session['eye_seconds'] += elapsed
                session['eye_rate_sum'] += rate * elapsed
            still = front.get('still_seconds') if front_valid and front.get('activity_tracked') else None
            if still is not None and self.last_still is not None and self.last_still > 5 and still < self.last_still - 3:
                session['movement_resets'] += 1
            self.last_still = still
            writing = state.get('writing', {})
            if writing.get('phase') == 'monitoring' and writing.get('confidence') in ('Available', 'Limited'):
                session['writing_seconds'] += elapsed
                if writing.get('changed'):
                    session['writing_changed_seconds'] += elapsed
            minute = int(session['active_seconds'] // 60)
            if not session['timeline'] or session['timeline'][-1]['minute'] != minute:
                session['timeline'].append({'minute': minute, 'tracked': 0., 'near': 0., 'active': 0.})
            bucket = session['timeline'][-1]
            bucket['active'] += elapsed
            bucket['tracked'] += elapsed if valid else 0
            bucket['near'] += elapsed if valid and not changed else 0
            # Bounded in memory and on disk: keep the latest 24 hours of bins.
            session['timeline'] = session['timeline'][-1440:]
            if now - self.last_save >= 15:
                self._save()
                self.last_save = now

    def suspend(self):
        with self.lock:
            self.last_tick = None
            self.last_still = None

    def set_persistence(self, enabled):
        with self.lock:
            persist = enabled and not self.demo
            if self.session and self.session['ended'] is None and self.session['persist'] != persist:
                # Start a new segment so re-enabling history never saves an earlier private interval.
                self.finish()
                self.start(persist=enabled)

    def finish(self):
        with self.lock:
            if self.session and self.session['ended'] is None:
                self.session['ended'] = datetime.now().astimezone().isoformat(timespec='milliseconds')
                self._save()
            self.last_tick = None

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=3)
        connection.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, started TEXT, data TEXT)')
        return connection

    def _save(self):
        if not self.session or not self.session['persist']:
            return
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)',
                                   (self.session['id'], self.session['started'], json.dumps(self.session)))
                connection.execute('DELETE FROM sessions WHERE id NOT IN (SELECT id FROM sessions ORDER BY started DESC LIMIT 200)')
            self.error = None
        except (OSError, sqlite3.Error):
            self.error = 'History could not be saved. Live analytics remain available.'

    @staticmethod
    def describe(session):
        data = copy.deepcopy(session)
        scored = data.get('alignment_seconds', 0)
        data['average_alignment'] = round(data.get('alignment_score_sum', 0) / scored) if scored else None
        tracked = data['tracked_seconds']
        data['near_percent'] = round(100 * data['near_seconds'] / tracked, 1) if tracked else None
        active = data['active_seconds']
        data['coverage_percent'] = round(100 * tracked / active, 1) if active else None
        data['average_blink_rate'] = round(data['eye_rate_sum'] / data['eye_seconds'], 1) if data['eye_seconds'] else None
        data['top_issues'] = [{'name': name, 'seconds': round(seconds, 1)}
                              for name, seconds in Counter(data['issues']).most_common(5)]
        data.pop('persist', None)
        return data

    def summary(self):
        with self.lock:
            return self.describe(self.session) if self.session else None

    def history(self):
        with self.lock:
            if self.demo or not self.path.exists():
                return []
            try:
                with closing(self._connect()) as connection, connection:
                    rows = connection.execute('SELECT data FROM sessions ORDER BY started DESC LIMIT 200').fetchall()
                summaries = [self.describe(json.loads(row[0])) for row in rows]
                for summary in summaries:
                    summary.pop('timeline', None)
                return summaries
            except (OSError, ValueError, sqlite3.Error):
                self.error = 'Saved history could not be read.'
                return []

    def detail(self, identifier):
        with self.lock:
            if self.session and self.session['id'] == identifier:
                return self.describe(self.session)
            if self.demo or not self.path.exists():
                return None
            try:
                with closing(self._connect()) as connection:
                    row = connection.execute('SELECT data FROM sessions WHERE id = ?', (identifier,)).fetchone()
                return self.describe(json.loads(row[0])) if row else None
            except (OSError, ValueError, sqlite3.Error):
                self.error = 'Session details could not be read.'
                return None

    def clear(self):
        with self.lock:
            if self.path.exists() and not self.demo:
                with closing(self._connect()) as connection, connection:
                    connection.execute('DELETE FROM sessions')
            self.session = None
            self.last_tick = None

    def export_csv(self):
        records = self.history()
        current = self.summary()
        if current:
            records = [current] + [row for row in records if row['id'] != current['id']]
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['started', 'ended', 'demo', 'active_seconds', 'tracked_seconds', 'near_reference_percent',
                         'coverage_percent', 'average_blink_rate', 'movement_resets', 'writing_seconds'])
        for row in records:
            writer.writerow([row['started'], row['ended'], row['demo'], round(row['active_seconds'], 1),
                             round(row['tracked_seconds'], 1), row['near_percent'], row['coverage_percent'],
                             row['average_blink_rate'], row['movement_resets'], round(row['writing_seconds'], 1)])
        return out.getvalue().encode('utf-8')
