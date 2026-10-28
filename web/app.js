'use strict';
const $ = id => document.getElementById(id);
let token, current, settingsLoaded = false, busy = false;
let lastFrame = {front: 0, side: 0};
const numeric = ['camera', 'alert_seconds', 'break_minutes', 'cooldown_seconds'];
const checks = ['notifications', 'posture_alerts', 'eye_alerts', 'break_alerts'];
const fields = [...numeric, ...checks, 'view', 'sensitivity', 'side_source', 'quiet_start', 'quiet_end'];
function message(text, error = false) {
  $('message').textContent = text;
  $('message').hidden = !text;
  $('message').setAttribute('role', error ? 'alert' : 'status');
}
function fillSettings(settings) {
  const values = {...settings, ...settings.web};
  for (const key of fields) {
    if (checks.includes(key)) $(key).checked = values[key];
    else $(key).value = values[key] ?? '';
  }
  settingsLoaded = true;
}
async function command(action, extra = {}) {
  if (busy) return;
  busy = true;
  try {
    if (!token) token = (await (await fetch('/api/session')).json()).token;
    const response = await fetch('/api/command', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Dashboard-Token': token},
      body: JSON.stringify({action, ...extra})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not apply that change.');
    message('');
    if (action === 'settings') {
      fillSettings(data.settings);
      $('save-status').textContent = 'Preferences saved';
    }
    render(data);
  } catch (error) { message(error.message, true); }
  finally { busy = false; }
}
function guidance(id, texts) {
  const node = $(id);
  node.replaceChildren(...texts.map(text => {
    const p = document.createElement('p'); p.textContent = text; return p;
  }));
}
function badge(id, value) {
  $(id).textContent = value;
  $(id).classList.toggle('limited', value === 'Limited' || value === 'Unavailable');
}
function metrics(id, rows, compact = false) {
  const target = $(id);
  const body = compact ? document.createElement('tbody') : target;
  body.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.className = row.issue ? 'issue' : row.available ? '' : 'unavailable';
    const delta = row.available ? `${row.delta > 0 ? '+' : ''}${row.delta}${row.unit === 'ratio' ? ' ratio' : row.unit}` : 'Unavailable';
    const status = row.available ? row.issue ? row.guidance : 'Within your reference range' : 'Not assessed · landmarks or reference missing';
    for (const text of compact ? [row.name, delta, status] : [row.name, delta, `${row.threshold}${row.unit === 'ratio' ? ' ratio' : row.unit}`, status]) {
      const td = document.createElement('td'); td.textContent = text; tr.append(td);
    }
    body.append(tr);
  }
  if (compact) { const table = document.createElement('table'); table.append(body); target.replaceChildren(table); }
}
function formatTime(seconds) {
  return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60).toString().padStart(2, '0')}s`;
}
function resetCamera(name, text) {
  const img = $(`${name}-feed`);
  img.hidden = true;
  img.removeAttribute('src');
  if (img.dataset.objectUrl) { URL.revokeObjectURL(img.dataset.objectUrl); delete img.dataset.objectUrl; }
  $(`${name}-placeholder`).hidden = false;
  badge(`${name}-confidence`, text);
}
function renderCamera(name, camera, state) {
  const live = state.started && !state.paused;
  if (!live || !camera || camera.error) {
    resetCamera(name, !state.started ? 'Camera off' : state.paused ? 'Paused' : 'Unavailable');
    $(`${name}-status`).textContent = camera?.error || (!state.started ? 'Waiting to start' : state.paused ? 'Paused · camera released' : 'Connecting camera…');
    if (name === 'front') {
      $('posture-status').textContent = state.paused ? 'Monitoring paused' : camera?.error ? 'Camera unavailable' : state.started ? 'Connecting…' : 'Find your reference';
      $('posture-help').textContent = camera?.error || 'Follow the setup guide to establish your comfortable reference.';
      $('confidence-detail').textContent = 'No current assessment is available.';
      $('eye-status').textContent = 'Eyes unavailable';
      badge('eye-confidence', 'Unavailable');
      $('blink-rate').textContent = $('eye-closed').textContent = $('still-time').textContent = '—';
      $('fps').textContent = '— FPS';
      $('metrics').replaceChildren();
      const row = document.createElement('tr'); const cell = document.createElement('td');
      cell.colSpan = 4; cell.textContent = 'Complete setup to see current measurements.'; row.append(cell); $('metrics').append(row);
      guidance('posture-guidance', []); guidance('eye-guidance', []);
    } else { guidance('side-guidance', []); $('side-metrics').replaceChildren(); }
    return;
  }
  badge(`${name}-confidence`, camera.confidence);
  $(`${name}-status`).textContent = camera.status;
  const cues = camera.guidance || [];
  guidance(`${name === 'front' ? 'posture' : 'side'}-guidance`, name === 'front' && cues.length > 2 ? [...cues.slice(0, 2), `${cues.length - 2} more changes in the measurements below.`] : cues);
  if (name === 'side') {
    $('side-detail').textContent = camera.calibration_hint || camera.confidence_detail;
    metrics('side-metrics', camera.metrics, true);
    return;
  }
  $('posture-status').textContent = camera.status;
  $('posture-help').textContent = camera.phase === 'monitoring' ? camera.confidence_detail : camera.calibration_hint || 'Hold comfortably upright while your reference is learned.';
  $('confidence-detail').textContent = camera.confidence_detail;
  $('fps').textContent = `${camera.fps.toFixed(1)} FPS`;
  $('feed-label').textContent = `${state.demo ? 'DEMO · ' : ''}${camera.view.toUpperCase()} CAMERA · ${camera.lighting.toUpperCase()}`;
  $('eye-status').textContent = camera.eye.status;
  badge('eye-confidence', camera.eye.confidence);
  $('blink-rate').textContent = camera.eye.blinks_per_minute === null ? '—' : camera.eye.blinks_per_minute.toFixed(1);
  $('eye-closed').textContent = camera.eye.openness === null ? '—' : `${camera.eye.closed_seconds.toFixed(1)}s`;
  guidance('eye-guidance', camera.eye.guidance);
  $('still-time').textContent = camera.activity_tracked ? formatTime(camera.still_seconds) : '—';
  $('movement-help').textContent = `Reminder after ${state.settings.web.break_minutes} min. Movement resets the timer.`;
  metrics('metrics', camera.metrics);
}
function render(state) {
  current = state;
  if (!settingsLoaded) fillSettings(state.settings);
  $('connection').textContent = state.paused ? 'Paused' : state.started ? 'Monitoring locally' : 'Connected locally';
  $('connection-dot').classList.remove('offline');
  $('demo-banner').hidden = !state.demo;
  $('pause').disabled = $('recalibrate').disabled = $('stop').disabled = !state.started;
  $('pause').textContent = state.paused ? 'Resume' : 'Pause';
  $('start').hidden = state.started;
  const front = state.cameras.front;
  const side = state.cameras.side;
  const sideEnabled = Boolean(state.settings.web.side_source);
  const setupComplete = state.started && !state.paused && front?.phase === 'monitoring' && (!sideEnabled || side?.phase === 'monitoring');
  $('setup').hidden = setupComplete;
  $('setup-hint').textContent = state.paused ? 'Camera released. Resume when you’re ready.' : front?.error || front?.calibration_hint || (!state.started ? 'Ready when you are.' : front?.phase === 'calibrating' ? `Hold still · ${front.calibration_remaining.toFixed(1)} seconds left` : sideEnabled && front?.phase === 'monitoring' && side?.phase !== 'monitoring' ? side?.error || side?.calibration_hint || 'Front ready. Complete side camera calibration.' : 'Connecting camera…');
  $('calibration-progress').value = front?.phase === 'monitoring' ? 5 : front?.phase === 'calibrating' ? 5 - front.calibration_remaining : 0;
  $('side-card').hidden = !sideEnabled;
  renderCamera('front', front, state);
  if (sideEnabled) renderCamera('side', side, state);
  $('notification-note').textContent = state.desktop_notifications_supported ? 'Desktop banners use macOS notification permissions. Dashboard alerts always work.' : 'Desktop notifications are only supported on macOS. In-dashboard alerts work here.';
  $('notifications').disabled = !state.desktop_notifications_supported;
  $('alert-panel').classList.toggle('active', state.alerts.length > 0);
  $('alert-title').textContent = state.snooze_seconds ? `Snoozed · ${formatTime(state.snooze_seconds)} left` : state.quiet ? 'Quiet hours are active' : state.alerts.length ? 'A little adjustment might help.' : 'You’re in control.';
  $('alerts').textContent = state.snooze_seconds || state.quiet ? 'Reminders are quiet. Live measurements continue above.' : state.alerts.join(' ') || 'No active reminders. Your preferences determine when alerts appear.';
  $('unsnooze').hidden = !state.snooze_seconds;
}
async function poll() {
  try {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error('Connection failed');
    render(await response.json());
  } catch (_) {
    $('connection').textContent = 'Server disconnected · retrying';
    $('connection-dot').classList.add('offline');
    for (const name of ['front', 'side']) resetCamera(name, 'Disconnected');
    $('posture-status').textContent = 'Live measurements unavailable';
    $('posture-help').textContent = 'The local server is disconnected. Start it again to resume.';
    $('eye-status').textContent = 'Unavailable';
    $('blink-rate').textContent = $('eye-closed').textContent = $('still-time').textContent = '—';
    badge('eye-confidence', 'Unavailable');
    $('metrics').replaceChildren();
    $('confidence-detail').textContent = 'Connection lost. Previous measurements are no longer current.';
    $('alerts').textContent = 'Server disconnected. Reminders are unavailable.';
    $('alert-title').textContent = 'Waiting to reconnect';
    $('alert-panel').classList.remove('active');
    guidance('posture-guidance', []); guidance('eye-guidance', []);
    $('pause').disabled = $('recalibrate').disabled = $('stop').disabled = true;
    current = null; token = null;
  } finally { setTimeout(poll, 500); }
}
async function feed(name) {
  try {
    if (current?.started && !current.paused && current.cameras[name] && !current.cameras[name].error && (name !== 'side' || current.settings.web.side_source)) {
      const response = await fetch(`/feed/${name}.jpg?t=${Date.now()}`);
      if (response.ok) {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const img = $(`${name}-feed`);
        const old = img.dataset.objectUrl;
        // A pause/stop may arrive while a frame is in flight.
        if (current?.started && !current.paused && !current.cameras[name]?.error) {
          img.src = url; img.dataset.objectUrl = url; img.hidden = false;
          $(`${name}-placeholder`).hidden = true;
          lastFrame[name] = Date.now();
        } else URL.revokeObjectURL(url);
        if (old) URL.revokeObjectURL(old);
      }
    }
    if (lastFrame[name] && Date.now() - lastFrame[name] > 4000) resetCamera(name, 'Feed delayed');
  } catch (_) { resetCamera(name, 'Feed unavailable'); }
  finally { setTimeout(() => feed(name), 200); }
}
$('start').onclick = () => command('start');
$('pause').onclick = () => command('pause');
$('stop').onclick = () => command('stop');
$('recalibrate').onclick = () => command('recalibrate');
$('snooze').onclick = () => command('snooze', {minutes: Number($('snooze-minutes').value)});
$('unsnooze').onclick = () => command('unsnooze');
$('clear-quiet').onclick = () => { $('quiet_start').value = ''; $('quiet_end').value = ''; $('save-status').textContent = 'Unsaved changes'; };
$('preferences').oninput = () => { $('save-status').textContent = 'Unsaved changes'; };
$('preferences').onsubmit = event => {
  event.preventDefault();
  const settings = {};
  for (const key of fields) settings[key] = checks.includes(key) ? $(key).checked : numeric.includes(key) ? Number($(key).value) : $(key).value;
  command('settings', {settings});
};
poll(); feed('front'); feed('side');
