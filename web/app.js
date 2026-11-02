'use strict';
const $ = id => document.getElementById(id);
let token, current, settingsLoaded = false, busy = false, disconnected = false;
let lastFrame = {front: 0, side: 0};
const numeric = ['camera', 'alert_seconds', 'break_minutes', 'cooldown_seconds', 'speech_rate', 'speech_volume', 'calibration_seconds'];
const checks = ['notifications', 'posture_alerts', 'eye_alerts', 'break_alerts', 'fatigue_alerts', 'spoken_alerts', 'history_enabled', 'writing_enabled', 'writing_alerts', 'writing_pen_markers'];
const fields = [...numeric, ...checks, 'view', 'sensitivity', 'side_source', 'quiet_start', 'quiet_end', 'speech_voice', 'writing_source', 'writing_hand'];
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
  preferredVoice = values.speech_voice;
  loadVoices();
  settingsLoaded = true;
}
async function command(action, extra = {}, options = {}) {
  if (busy) return;
  busy = true;
  try {
    if (!token) token = (await (await fetch('/api/session')).json()).token;
    const send = action => fetch('/api/command', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Dashboard-Token': token},
      body: JSON.stringify({action, ...extra})
    });
    let response = await send(action);
    let data = await response.json();
    // Older running servers support pause/resume but do not know end_break yet.
    if (action === 'end_break' && !response.ok && data.error === 'Unknown action.') {
      response = await fetch('/api/state');
      data = await response.json();
      if (response.ok && data.started && data.paused) {
        const breakSnooze = data.break_seconds > 0 && Math.abs(data.snooze_seconds - data.break_seconds) <= 1;
        response = await send('pause');
        data = await response.json();
        if (response.ok && !data.paused && breakSnooze) {
          response = await send('unsnooze');
          data = await response.json();
        }
      }
    }
    if (!response.ok) throw new Error(data.error || 'Could not apply that change.');
    message('');
    if (['pause', 'stop', 'snooze', 'take_break'].includes(action) && 'speechSynthesis' in window) { speechSequence++; testingSpeech = false; speechSynthesis.cancel(); }
    if (action === 'settings' && !options.preserveDraft) {
      if (Object.keys(extra.settings || {}).length >= fields.length) {
        fillSettings(data.settings);
        $('save-status').textContent = 'Preferences saved';
      } else {
        // Quick actions update their own fields without overwriting a settings draft.
        for (const [key, value] of Object.entries(extra.settings || {})) {
          if (checks.includes(key)) $(key).checked = value; else if ($(key)) $(key).value = value;
        }
        if ($('save-status').textContent !== 'Unsaved changes') $('save-status').textContent = 'Preferences saved';
      }
    }
    render(data);
    if (['stop', 'clear_history'].includes(action)) fetchAnalytics(false);
    return data;
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
    const unit = ['°', '%', 'N'].includes(row.unit) ? row.unit : '';
    const delta = row.available ? `${row.delta > 0 ? '+' : ''}${Number(row.delta.toFixed(2))}${unit}` : '—';
    const status = row.available ? row.issue ? conciseReminder({message: row.guidance || 'Adjust your position.'}).message : 'Near reference' : 'Not tracked';
    const names = {'Elbows away from body': 'Elbow spread', 'Raised shoulders': 'Shoulder raise', 'Closer to camera': 'Camera proximity', 'Wrist alignment in image': 'Wrist alignment', 'Thumb–index spacing': 'Thumb–index gap'};
    for (const text of compact ? [names[row.name] || row.name, delta, status] : [names[row.name] || row.name, delta, `${Number(row.threshold.toFixed(2))}${unit}`, status]) {
      const td = document.createElement('td'); td.textContent = text; td.title = row.available ? `${row.name} · ${row.unit}${row.issue ? ` · ${row.guidance}` : ''}` : 'Landmarks or reference unavailable; excluded from the score.'; tr.append(td);
    }
    body.append(tr);
  }
  if (compact) { const table = document.createElement('table'); table.append(body); target.replaceChildren(table); }
}
const severityLabels = {neutral: 'Not assessed', success: 'Near reference', suggestion: 'Suggestion', warning: 'Correction', attention: 'Review now'};
function eyeCueAssessment(state) {
  const eye = state.cameras?.front?.eye;
  const reasons = [...new Set(eye?.reasons || [])].filter(reason => ['Prolonged closure', 'Eyes closed often', 'Low blink rate', 'Long time without a blink'].includes(reason));
  const tracked = state.started && !state.paused && eye?.confidence !== 'Unavailable' && Number.isFinite(eye?.openness);
  // Wait for a blink and closure observation window before showing a numeric score.
  const ready = tracked && Number.isFinite(eye.blinks_per_minute) && Number.isFinite(eye.closed_fraction);
  return {label: 'Eyes', score: ready ? 100 - reasons.length * 25 : null,
    severity: !tracked ? 'neutral' : reasons.length ? 'suggestion' : ready ? 'success' : 'neutral',
    coverage: tracked ? eye.confidence : 'Unavailable',
    status: !tracked ? 'Eye tracking unavailable' : !ready ? 'Observing blink pattern' : reasons.length ? 'Blink or closure cues detected' : 'No active eye cues',
    guidance: tracked && eye.guidance?.length ? eye.guidance : [!tracked ? 'Keep both eyes visible to the front camera.' : !ready ? 'Keep your eyes visible while the observation window fills.' : 'No blink or closure reminders are active.'],
    eyeCue: true};
}
function updateScoreRing(node, score, severity, label) {
  const available = Number.isFinite(score);
  node.dataset.severity = severity || 'neutral'; node.dataset.available = String(available);
  const value = available ? Math.max(0, Math.min(100, score)) : null;
  node.querySelector('.ring-progress').style.strokeDashoffset = String(value === null ? 100 : 100 - value);
  node.querySelector('.score-value').textContent = value ?? '—';
  node.setAttribute('aria-label', `${label}: ${value === null ? 'Not assessed' : `${value} out of 100`}`);
}
function availableAlignment(parts, live = true) {
  const available = live ? parts.filter(part => Number.isFinite(part.score) && !part.exclude_from_overall) : [];
  const rank = {neutral: 0, success: 1, suggestion: 2, warning: 3, attention: 4};
  return {
    score: available.length ? Math.round(available.reduce((sum, part) => sum + part.score, 0) / available.length) : null,
    severity: available.reduce((worst, part) => rank[part.severity] > rank[worst] ? part.severity : worst, 'neutral'),
    count: available.length,
    partial: available.length < parts.length || available.some(part => part.coverage === 'Limited')
  };
}
// Compatibility with an already running server: retain observed averages across
// refreshes until server-side session aggregates become available.
let observedAlignment;
function sessionAlignment(state, liveScore) {
  const session = state.session;
  if (!session?.id) return {score: null, seconds: 0, local: false};
  if (Object.hasOwn(session, 'average_alignment')) {
    return {score: session.average_alignment, seconds: session.alignment_seconds || 0, local: false};
  }
  if (observedAlignment?.id !== session.id) {
    try { observedAlignment = JSON.parse(sessionStorage.getItem('still-session-alignment') || 'null'); } catch (_) { observedAlignment = null; }
    if (observedAlignment?.id !== session.id || !Number.isFinite(observedAlignment.sum) || !Number.isFinite(observedAlignment.seconds)) {
      observedAlignment = {id: session.id, sum: 0, seconds: 0, last: null};
    }
  }
  const average = observedAlignment;
  const active = session.active_seconds;
  const elapsed = average.last === null ? 0 : active - average.last;
  average.last = state.started && !state.paused && Number.isFinite(active) ? active : null;
  if (state.started && !state.paused && Number.isFinite(liveScore) && elapsed > 0 && elapsed <= 2.5) {
    average.sum += liveScore * elapsed; average.seconds += elapsed;
  }
  try { sessionStorage.setItem('still-session-alignment', JSON.stringify(average)); } catch (_) { /* In-memory averaging still works. */ }
  return {score: average.seconds ? Math.round(average.sum / average.seconds) : null, seconds: average.seconds, local: true};
}
function renderCoaching(state) {
  const coach = state.coaching;
  const parts = [...(coach?.parts || [])];
  parts.splice(1, 0, eyeCueAssessment(state));
  const overall = availableAlignment(parts, state.started && !state.paused);
  const average = sessionAlignment(state, overall.score);
  const averageSeverity = average.score === null ? 'neutral' : average.score >= 85 ? 'success' : 'suggestion';
  updateScoreRing($('alignment-ring'), average.score, averageSeverity, 'Session average alignment');
  $('alignment-score').dataset.severity = averageSeverity;
  $('coaching-title').textContent = 'Session average';
  $('coaching-summary').textContent = average.score === null ? 'Waiting for tracked time' : `${state.paused ? 'Paused · ' : !state.started ? 'Ended · ' : ''}${shortTime(average.seconds)} scored${average.local ? ' · since view opened' : ''}`;
  $('score-description').textContent = 'The large score is the time-weighted session average of the available live subscores below, including Eyes. Each observed interval has equal-weight subscores; longer intervals contribute proportionally more time. Pauses, missing scores, and observation gaps are excluded. The average stays visible during pauses or tracking loss and resets for a new session. Individual scores show the current position. Posture and grip scores compare live camera measurements with your reference. Eyes subtracts 25 for each active blink or closure cue after observation. These scores do not measure health or verify grip correctness.';
  const ranks = {attention: 4, warning: 3, suggestion: 2, neutral: 1, success: 0};
  const candidates = [...parts, ...(state.notifications || []).map(item => ({severity: item.severity, guidance: [item.message]}))];
  const priority = candidates.sort((a, b) => ranks[b.severity] - ranks[a.severity])[0];
  $('next-step').textContent = !state.started ? 'Start a session to set your reference.' : state.paused ? 'Resume when you’re ready.' : priority?.guidance[0] || 'Keep your movement relaxed.';
  $('next-step').dataset.severity = priority?.severity || 'neutral';
  $('next-action').hidden = !state.started || state.paused || !priority || priority.severity === 'success';
  const target = $('coaching-parts');
  const cards = parts.map(part => {
    let card = [...target.children].find(node => node.dataset.label === part.label);
    if (!card) {
      card = document.createElement('details'); card.className = 'coaching-card'; card.dataset.label = part.label;
      const heading = document.createElement('summary'); heading.className = 'card-heading';
      const title = document.createElement('span'); title.className = 'coaching-name'; title.textContent = part.label;
      const caption = document.createElement('span'); caption.className = 'score-caption'; title.append(caption);
      const badge = document.createElement('span'); badge.className = 'score-ring'; badge.setAttribute('role', 'img');
      badge.innerHTML = '<svg viewBox="0 0 48 48" aria-hidden="true"><circle class="ring-track" cx="24" cy="24" r="20"></circle><circle class="ring-progress" cx="24" cy="24" r="20" pathLength="100"></circle></svg><span class="score-value">—</span>';
      heading.append(title, badge);
      const status = document.createElement('p'); status.className = 'coaching-status';
      const cues = document.createElement('div'); cues.className = 'coaching-cues';
      card.append(heading, status, cues);
    }
    const ring = card.querySelector('.score-ring');
    updateScoreRing(ring, part.score, part.severity, part.label);
    card.querySelector('.score-caption').textContent = part.score === null ? (part.label === 'Grip & wrist' ? part.status : 'Not assessed') : part.eyeCue && part.severity === 'success' ? 'No active cues' : severityLabels[part.severity];
    card.querySelector('.coaching-status').textContent = `${part.status}${part.coverage === 'Limited' ? ' · Partial tracking' : ''}`;
    const cues = card.querySelector('.coaching-cues');
    if (cues.dataset.content !== JSON.stringify(part.guidance)) {
      cues.dataset.content = JSON.stringify(part.guidance);
      cues.replaceChildren(...part.guidance.map(text => { const p = document.createElement('p'); p.textContent = text; return p; }));
    }
    return card;
  });
  if (cards.length !== target.children.length || cards.some((card, i) => card !== target.children[i])) target.replaceChildren(...cards);
}
function conciseReminder(item) {
  const rules = [
    [/blink|long stare/i, 'Blink fully, then look away for a moment.'],
    [/eyes closed|eye closure/i, 'Pause and rest your eyes if you feel tired.'],
    [/uneven shoulders|shoulder tilt/i, 'Level your shoulders and support your arms.'],
    [/raised shoulders|shoulders raised/i, 'Relax your shoulders and support your forearm.'],
    [/torso|trunk/i, 'Sit comfortably upright and bring your work within reach.'],
    [/head.*forward|head is further forward/i, 'Bring your work closer and relax your neck.'],
    [/head tilt|head tilted/i, 'Level your head and adjust the page angle.'],
    [/head turn|head turned|head position changed/i, 'Turn your work toward you to ease neck twisting.'],
    [/elbows|arm position changed/i, 'Bring your elbows closer and support your forearms.'],
    [/closer to.*camera|leaning closer|moved closer/i, 'Return to your reference distance and adjust your work.'],
    [/thumb.index spacing/i, 'Reset your pen grip; keep it light and comfortable.'],
    [/index curl/i, 'Relax your fingers and try a few light strokes.'],
    [/wrist alignment/i, 'Turn the paper and support your forearm.'],
    [/change position|short break|stillness/i, 'Change position or take a short break.']
  ];
  const match = rules.find(([pattern]) => pattern.test(item.message));
  return {...item, message: match ? match[1] : item.message.replace(/^(Front|Side):\s*/i, '')};
}
// Keep reminder identity independent of changing scores and severity.
const monitorReminders = new Map();
function steadyReminders(buffer, items, now, muted = false) {
  if (muted) { buffer.clear(); return []; }
  const active = new Set();
  for (const item of items) {
    const key = JSON.stringify([item.category, item.message]); active.add(key);
    let entry = buffer.get(key);
    if (!entry) { entry = {key, item, lastSeen: now, shownAt: null, dismissedUntil: 0}; buffer.set(key, entry); }
    // Detection already applies its configured delay; display qualified cues now.
    entry.lastSeen = now; entry.item = item;
    if (entry.shownAt === null && now >= entry.dismissedUntil) entry.shownAt = now;
  }
  for (const [key, entry] of buffer) {
    if (!active.has(key) && now >= entry.dismissedUntil && (entry.shownAt === null || (now - entry.lastSeen >= 5000 && now - entry.shownAt >= 12000))) buffer.delete(key);
  }
  return [...buffer.values()].filter(entry => entry.shownAt !== null && now >= entry.dismissedUntil);
}
function removeFloatingReminder(row, target) {
  if (row.dataset.leaving) return;
  row.dataset.leaving = 'true';
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    row.remove(); target.hidden = !target.children.length; return;
  }
  const height = row.getBoundingClientRect().height;
  const motion = row.animate([
    {opacity: 1, transform: 'translateX(0) scale(1)', height: `${height}px`, paddingTop: '14px', paddingBottom: '14px', marginBottom: '0px'},
    {opacity: 0, transform: 'translateX(12px) scale(.98)', height: '0px', paddingTop: '0px', paddingBottom: '0px', borderWidth: '0px', marginBottom: '-10px'}
  ], {duration: 420, easing: 'cubic-bezier(.4, 0, .2, 1)', fill: 'forwards'});
  motion.finished.catch(() => {}).then(() => { row.remove(); target.hidden = !target.children.length; });
}
function renderFloatingReminders(state) {
  const target = $('monitor-notifications');
  const muted = !state.started || state.paused || Boolean(state.quiet || state.snooze_seconds);
  const entries = steadyReminders(monitorReminders, (state.notifications || []).map(conciseReminder), Date.now(), muted);
  if (muted) { target.replaceChildren(); target.hidden = true; return []; }
  const visible = new Set(entries.map(entry => entry.key));
  for (const row of [...target.children]) if (!visible.has(row.dataset.key)) removeFloatingReminder(row, target);
  for (const entry of entries) {
    let row = [...target.children].find(node => node.dataset.key === entry.key);
    if (!row) {
      row = document.createElement('div'); row.className = 'notification-row'; row.dataset.key = entry.key;
      const label = document.createElement('span'); label.className = 'notification-title';
      const text = document.createElement('p'); text.textContent = entry.item.message;
      const close = document.createElement('button'); close.className = 'dismiss-notification'; close.textContent = '×'; close.setAttribute('aria-label', `Dismiss ${entry.item.category} reminder`);
      close.onclick = () => { entry.dismissedUntil = Date.now() + Math.max(30, state.settings.web.cooldown_seconds || 30) * 1000; entry.shownAt = null; removeFloatingReminder(row, target); };
      row.append(label, text, close); target.append(row);
    }
    row.dataset.severity = entry.item.severity;
    const label = row.querySelector('.notification-title');
    if (label.textContent !== entry.item.category) label.textContent = entry.item.category;
    row.setAttribute('aria-label', `${entry.item.category} · ${severityLabels[entry.item.severity]}`);
  }
  target.hidden = !target.children.length;
  return entries.map(entry => entry.item);
}
function renderNotifications(state) {
  const target = $('alerts');
  const notifications = renderFloatingReminders(state);
  const rank = {suggestion: 1, warning: 2, attention: 3};
  $('alert-panel').dataset.severity = [...(notifications || [])].sort((a, b) => rank[b.severity] - rank[a.severity])[0]?.severity || 'neutral';
  // Stable content avoids repeatedly announcing unchanged reminders during polling.
  const signature = JSON.stringify([state.quiet, Boolean(state.snooze_seconds), notifications]);
  if (target.dataset.signature === signature) return;
  target.dataset.signature = signature;
  target.replaceChildren();
  if (state.snooze_seconds || state.quiet || !notifications?.length) {
    target.textContent = state.snooze_seconds || state.quiet ? 'Reminders are quiet. Live guidance continues above.' : 'No active reminders. Suggestions appear in your live guidance.';
    return;
  }
  for (const item of notifications) {
    const row = document.createElement('div'); row.className = 'notification-row'; row.dataset.severity = item.severity;
    const label = document.createElement('span'); label.className = 'severity-badge'; label.dataset.severity = item.severity; label.textContent = `${severityLabels[item.severity]} · ${item.category}${item.score !== null && item.score !== undefined ? ` · ${item.score}/100` : ''}`;
    const text = document.createElement('p'); text.textContent = item.message; row.append(label, text); target.append(row);

  }
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
  $('eye-status').textContent = camera.eye.status;
  badge('eye-confidence', camera.eye.confidence);
  $('blink-rate').textContent = camera.eye.blinks_per_minute === null ? '—' : camera.eye.blinks_per_minute.toFixed(1);
  $('eye-closed').textContent = camera.eye.openness === null ? '—' : `${camera.eye.closed_seconds.toFixed(1)}s`;
  guidance('eye-guidance', camera.eye.guidance);
  $('still-time').textContent = camera.activity_tracked ? formatTime(camera.still_seconds) : '—';
  $('movement-help').textContent = `Reminder after ${state.settings.web.break_minutes} min. Movement resets the timer.`;
  metrics('metrics', camera.metrics);
}
function renderCalibration(state) {
  const setup = $('setup');
  const live = state.started && !state.paused;
  const front = state.cameras.front;
  const sideEnabled = Boolean(state.settings.web.side_source);
  const handEnabled = state.settings.web.writing_enabled;
  const sources = [
    {name: 'Posture', data: front, remaining: front?.calibration_remaining, duration: state.settings.web.calibration_seconds},
    ...(sideEnabled ? [{name: 'Side posture', data: state.cameras.side, remaining: state.cameras.side?.calibration_remaining, duration: state.settings.web.calibration_seconds}] : []),
    ...(handEnabled ? [{name: 'Hand', data: state.writing, remaining: state.writing?.remaining, duration: state.settings.web.calibration_seconds}] : [])
  ];
  const active = live ? sources.filter(source => source.data?.phase === 'calibrating') : [];
  const postureReady = live && sources.filter(source => source.name !== 'Hand').every(source => source.data?.phase === 'monitoring');
  if (!live) delete setup.dataset.ready;
  else if (postureReady) setup.dataset.ready = 'true';
  const handReady = !handEnabled || state.writing?.calibrated || state.writing?.phase === 'monitoring';
  const complete = live && !active.length && setup.dataset.ready === 'true' && handReady;
  setup.hidden = complete;
  const previous = setup.dataset.calibrating;
  const signature = active.map(source => source.name).join(',');
  if (signature && signature !== setup.dataset.calibrating && route === 'monitor') setup.open = true;
  if (live && handEnabled && !handReady && route === 'monitor') setup.open = true;
  if (route === 'monitor' || !signature) setup.dataset.calibrating = signature;
  if (complete || (!live && previous)) setup.open = false;
  $('setup-title').textContent = active.length ? 'Calibrating' : 'Camera setup';
  $('setup-steps').hidden = Boolean(active.length);
  $('setup-side-hint').hidden = !sideEnabled || Boolean(active.length);
  const countdowns = $('calibration-countdowns'); countdowns.hidden = !active.length;
  const names = new Set(active.map(source => source.name));
  for (const row of [...countdowns.children]) if (!names.has(row.dataset.source)) row.remove();
  for (const source of active) {
    let row = [...countdowns.children].find(node => node.dataset.source === source.name);
    if (!row) {
      row = document.createElement('div'); row.className = 'calibration-countdown'; row.dataset.source = source.name;
      const label = document.createElement('span'); label.textContent = source.name;
      const value = document.createElement('strong'); row.append(label, value); countdowns.append(row);
    }
    row.querySelector('strong').textContent = `${Math.max(0, Number.isFinite(source.remaining) ? source.remaining : source.duration).toFixed(1)}s`;
  }
  const pending = sources.find(source => source.data?.phase !== 'monitoring');
  $('setup-hint').textContent = !state.started ? 'Ready' : state.paused ? 'Paused · resume to set up' : active.length ? (active.some(source => source.name === 'Hand') ? 'Keep your body steady; write a few relaxed strokes for the hand reference' : 'Hold comfortably still') : pending?.data?.error || pending?.data?.hint || pending?.data?.calibration_hint || 'Waiting for tracking…';
  $('calibration-progress').hidden = !active.length;
  $('calibration-progress').max = active.length ? active.reduce((sum, source) => sum + source.duration, 0) : 5;
  $('calibration-progress').value = active.reduce((sum, source) => sum + source.duration - Math.max(0, Math.min(source.duration, source.remaining ?? source.duration)), 0);
}
function renderFatigue(state) {
  const fatigue = state.started && !state.paused ? state.cameras?.front?.fatigue : null;
  const recommend = Boolean(fatigue?.warning);
  const reminders = state.settings?.web?.fatigue_alerts !== false;
  const onBreak = Boolean(state.started && state.paused && state.break_seconds > 0);
  $('fatigue-card').classList.toggle('tired', recommend);
  $('fatigue-status').textContent = !state.started ? 'Waiting for camera'
    : state.paused ? onBreak ? `Break · ${formatTime(state.break_seconds)} left` : 'Paused'
    : recommend ? 'You may be tired.' : !fatigue || fatigue.status === 'Unavailable' ? 'Eye tracking unavailable' : 'No tiredness cues';
  $('fatigue-break').hidden = !state.started || state.paused || !recommend;
  $('fatigue-break-detail').hidden = !state.started || (!recommend && !state.paused);
  $('fatigue-break-detail').textContent = state.paused
    ? 'Camera paused · Resume when ready.'
    : !reminders ? 'Reminders off' : state.quiet ? 'Quiet hours' : state.snooze_seconds ? 'Reminders snoozed' : 'Pauses camera & reminders';
}
let breakResumePending = false;
let breakScreenActive = false;
function renderBreak(state) {
  const active = Boolean(state.started && state.paused && (state.break_active ?? (state.break_seconds > 0 || breakScreenActive)));
  breakScreenActive = active;
  const remaining = Math.max(0, Math.min(120, Math.ceil(state.break_seconds || 0)));
  $('break-screen').hidden = !active;
  document.body.classList.toggle('on-break', active);
  if (!active) return;
  const complete = remaining === 0;
  const title = complete ? 'Break complete' : 'Break';
  if ($('break-title').textContent !== title) $('break-title').textContent = title;
  $('break-time').textContent = `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`;
  $('break-time-caption').textContent = complete ? 'break complete' : 'remaining';
  $('break-ring').style.strokeDashoffset = String(100 * (1 - remaining / 120));
  $('break-progress').setAttribute('aria-valuenow', String(remaining));
  $('break-progress').setAttribute('aria-valuetext', complete ? 'Break complete' : `${remaining} seconds remaining`);
  $('end-break').textContent = complete ? 'Resume session' : 'End break early';
  $('end-break').disabled = breakResumePending;
}
function render(state) {
  current = state;
  if (!settingsLoaded) fillSettings(state.settings);
  $('demo-banner').hidden = !state.demo;
  $('pause').disabled = $('recalibrate').disabled = $('stop').disabled = !state.started;
  $('pause').textContent = state.paused ? 'Resume' : 'Pause';
  $('start').hidden = state.started;
  const front = state.cameras.front;
  const side = state.cameras.side;
  const sideEnabled = Boolean(state.settings.web.side_source);
  renderCalibration(state);
  $('side-card').hidden = !sideEnabled;
  renderCamera('front', front, state);
  if (sideEnabled) renderCamera('side', side, state);
  $('notification-note').textContent = state.desktop_notifications_supported ? 'Off by default. In-app reminders stay on.' : 'Requires macOS. In-app reminders stay on.';
  $('notifications').disabled = !state.desktop_notifications_supported;
  $('alert-panel').classList.toggle('active', state.alerts.length > 0);
  $('alert-title').textContent = state.snooze_seconds ? `Snoozed · ${formatTime(state.snooze_seconds)} left` : state.quiet ? 'Quiet hours are active' : state.alerts.length ? `${state.alerts.length} active reminder${state.alerts.length === 1 ? '' : 's'}` : 'All clear';
  renderNotifications(state);
  renderCoaching(state);
  renderFatigue(state);
  renderBreak(state);
  $('unsnooze').hidden = !state.snooze_seconds;
  renderApp(state);
}
async function poll() {
  try {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error('Connection failed');
    render(await response.json());
    if (disconnected) { disconnected = false; message(''); }
  } catch (_) {
    if (!disconnected) message('Local server disconnected. Summaries shown are last received; live cameras and controls are unavailable.', true);
    disconnected = true;
    for (const name of ['front', 'side']) resetCamera(name, 'Disconnected');
    $('posture-status').textContent = 'Live measurements unavailable';
    $('posture-help').textContent = 'The local server is disconnected. Start it again to resume.';
    renderFatigue({started: true, paused: false});
    renderBreak({started: false});
    $('fatigue-status').textContent = 'Detection unavailable · disconnected';
    $('eye-status').textContent = 'Unavailable';
    $('blink-rate').textContent = $('eye-closed').textContent = $('still-time').textContent = '—';
    badge('eye-confidence', 'Unavailable');
    $('metrics').replaceChildren();
    $('confidence-detail').textContent = 'Connection lost. Previous measurements are no longer current.';
    monitorReminders.clear(); $('monitor-notifications').replaceChildren(); $('monitor-notifications').hidden = true;
    $('alerts').textContent = 'Server disconnected. Reminders are unavailable.';
    $('alert-title').textContent = 'Waiting to reconnect';
    $('alert-panel').classList.remove('active');
    guidance('posture-guidance', []); guidance('eye-guidance', []);
    $('pause').disabled = $('recalibrate').disabled = $('stop').disabled = true;
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    $('writing-status').textContent = 'Server disconnected';
    $('writing-metrics').replaceChildren(); guidance('writing-guidance', []);
    $('writing-progress').value = 0; $('writing-hint').textContent = 'Waiting for fresh hand measurements from the server.';
    $('side-metrics').replaceChildren(); guidance('side-guidance', []);
    $('side-status').textContent = 'Server disconnected';
    ['session-start', 'enable-writing', 'writing-calibrate'].forEach(id => { $(id).disabled = true; });
    resetCamera('writing', 'Unavailable');
    renderCoaching({started: false, paused: false});
    $('coaching-summary').textContent = 'Connection lost. Waiting for fresh measurements.';
    $('alerts').dataset.signature = '';
    current = null; token = null;
  } finally { setTimeout(poll, 500); }
}
async function feed(name) {
  try {
    const writing = name === 'writing';
    const source = writing ? (current?.settings.web.writing_source ? 'writing' : 'front') : name;
    const camera = writing ? current?.writing : current?.cameras[name];
    const enabled = writing ? current?.settings.web.writing_enabled : name !== 'side' || current?.settings.web.side_source;
    // Only fetch images for a visible screen. Tracking continues on the server.
    const visible = route === 'monitor' && (!writing || Boolean(current?.settings.web.writing_source));
    if (visible && enabled && current?.started && !current.paused && camera && !camera.error) {
      const response = await fetch(`/feed/${source}.jpg?t=${Date.now()}`);
      if (response.ok) {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const img = $(`${name}-feed`);
        const old = img.dataset.objectUrl;
        if (current?.started && !current.paused && (writing ? current.settings.web.writing_enabled : !current.cameras[name]?.error)) {
          img.src = url; img.dataset.objectUrl = url; img.hidden = false;
          $(`${name}-placeholder`).hidden = true;
          lastFrame[name] = Date.now();
        } else URL.revokeObjectURL(url);
        if (old) URL.revokeObjectURL(old);
      }
    }
    if (lastFrame[name] && Date.now() - lastFrame[name] > 4000) resetCamera(name, 'Feed delayed');
  } catch (_) {
    // A single dropped request should not replace an otherwise live preview.
    if (!lastFrame[name] || Date.now() - lastFrame[name] > 4000) resetCamera(name, 'Feed unavailable');
  }
  finally { setTimeout(() => feed(name), 200); }
}

const routes = {
  dashboard: ['Dashboard', 'OVERVIEW', 'Your workspace. In balance.', 'A simple view of your session and where to focus.'],
  monitor: ['Live monitor', 'LIVE VIEW', 'A clearer view.', 'Posture, eye cues, and small adjustments as you work.'],
  settings: ['Settings', 'PREFERENCES', 'Make yourself comfortable.', 'Set up your cameras, reminders, and privacy.']
};
let route = 'dashboard', analyticsRange = 'session', history = [], selectedSession = null;
let chartData = [], chartLabels = [], analyticsError = '';
let preferredVoice = '', localVoices = [], speechArmed = false, speechActive = new Set(), speechLast = {};
let testingSpeech = false, speechSequence = 0;
const speechOwner = Math.random().toString(36).slice(2);
let installPrompt;
let settingsMotion;
function openSettings() {
  const modal = $('settings-modal');
  if (modal.open) return;
  modal.classList.remove('closing');
  modal.showModal();
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    settingsMotion = modal.animate([
      {opacity: 0, transform: 'translateY(12px) scale(.97)'},
      {opacity: 1, transform: 'translateY(0) scale(1)'}
    ], {duration: 260, easing: 'cubic-bezier(.16, 1, .3, 1)'});
  }
}
async function closeSettings() {
  savePreferences();
  const modal = $('settings-modal');
  if (!modal.open || modal.classList.contains('closing')) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { modal.close(); return; }
  const style = getComputedStyle(modal);
  const start = {opacity: style.opacity, transform: style.transform};
  settingsMotion?.cancel();
  modal.classList.add('closing');
  settingsMotion = modal.animate([start, {opacity: 0, transform: 'translateY(8px) scale(.98)'}],
    {duration: 180, easing: 'cubic-bezier(.4, 0, 1, 1)', fill: 'forwards'});
  try { await settingsMotion.finished; } catch (_) { /* A canceled animation can still close cleanly. */ }
  modal.close(); settingsMotion.cancel(); modal.classList.remove('closing');
}
$('close-settings').onclick = closeSettings;
$('settings-modal').addEventListener('cancel', event => { event.preventDefault(); closeSettings(); });
$('settings-modal').addEventListener('click', event => {
  if (event.target === $('settings-modal')) closeSettings();
});
document.querySelector('.settings-link').addEventListener('click', event => {
  event.preventDefault(); openSettings();
});
function setRoute(value) {
  if (value === 'writing') { value = 'monitor'; window.history.replaceState(null, '', '#monitor'); }
  if (value === 'settings' || value === 'preferences') {
    if (!document.body.dataset.view) setRoute(route);
    window.history.replaceState(null, '', `#${route}`);
    openSettings();
    return;
  }
  route = routes[value] ? value : 'dashboard';
  document.body.dataset.view = route;
  document.querySelectorAll('.app-popover, #alert-panel').forEach(panel => { panel.open = false; });
  for (const name of ['dashboard', 'monitor']) $(`view-${name}`).hidden = name !== route;
  document.querySelectorAll('[data-view]').forEach(link => {
    const active = link.dataset.view === route;
    link.classList.toggle('active', active);
    link.setAttribute('aria-label', routes[link.dataset.view][0]);
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });
  const [title, eyebrow, heading, description] = routes[route];
  $('route-title').textContent = title; $('route-eyebrow').textContent = eyebrow;
  $('route-heading').textContent = title; $('route-description').textContent = description;
  document.title = `Still · ${title}`;
  $('coaching-panel').hidden = route !== 'monitor';
  if (route === 'dashboard') { renderAnalytics(); selectRangeButtons(); requestAnimationFrame(drawChart); }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', () => setRoute(location.hash.slice(1)));
function percent(value) { return value === null || value === undefined ? '—' : `${value.toFixed(1)}%`; }
function shortTime(seconds) {
  if (!seconds) return '0m';
  return seconds < 60 ? `${Math.round(seconds)}s` : seconds < 3600 ? `${Math.floor(seconds / 60)}m` : `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
}
function renderApp(state) {
  ['session-start'].forEach(id => { $(id).disabled = false; });
  $('session-start').hidden = state.started;
  $('clear-history').disabled = state.started;
  const writing = state.writing;
  renderWritingEvidence(state);
  document.body.dataset.tracking = state.started && !state.paused ? 'live' : 'off';
  $('writing-hint').hidden = writing?.phase === 'monitoring';
  $('writing-progress').hidden = writing?.phase !== 'calibrating';
  $('enable-writing').hidden = state.settings.web.writing_enabled && state.started && !state.paused;
  const enabled = state.settings.web.writing_enabled;
  $('enable-writing').textContent = enabled ? (state.started ? 'Hand tracking enabled' : 'Start posture & hand tracking') : 'Enable hand tracking';
  $('writing-camera-card').hidden = !enabled || !state.settings.web.writing_source;
  $('workspace-camera-title').textContent = enabled && !state.settings.web.writing_source ? 'Posture & hand camera' : 'Posture camera';
  document.body.dataset.handCamera = enabled && state.settings.web.writing_source ? 'dedicated' : 'shared';
  $('writing-calibrate').hidden = false;
  $('writing-calibrate').textContent = enabled && state.started && !state.paused ? 'Reset grip & wrist reference' : 'Start grip & wrist calibration';
  $('enable-writing').disabled = enabled && state.started && !state.paused;
  $('writing-calibrate').disabled = false;
  if (!enabled || !state.started || state.paused) {
    resetCamera('writing', enabled ? state.paused ? 'Paused' : 'Camera off' : 'Disabled');
    $('writing-status').textContent = state.paused ? 'Paused · resume when ready' : enabled ? 'Start a session to track your hand' : 'Enable writing mode to begin';
    $('writing-progress').value = 0;
    $('writing-metrics').replaceChildren(); guidance('writing-guidance', []);
  } else {
    badge('writing-confidence', writing.confidence || 'Connecting');
    $('writing-status').textContent = writing.status || 'Connecting hand tracker…';
    $('writing-hint').textContent = writing.hint || 'Show the wrist, thumb, and index finger. Check the chosen writing hand in Settings.';
    $('writing-progress').max = state.settings.web.calibration_seconds;
    $('writing-progress').value = writing.phase === 'monitoring' ? $('writing-progress').max : writing.phase === 'calibrating' ? $('writing-progress').max - writing.remaining : 0;
    metrics('writing-metrics', writing.metrics || []);
    guidance('writing-guidance', writing.guidance || []);
    $('writing-limitation').textContent = writing.limitation || 'Hand geometry is a limited visual cue, not a grip correctness assessment.';
    $('writing-feed-label').textContent = `${state.demo ? 'DEMO · ' : ''}${state.settings.web.writing_hand.toUpperCase()} HAND · ${state.settings.web.writing_source ? 'DESK CAMERA' : 'FRONT CAMERA'}`;
    // Hand landmark availability is independent of camera video availability.
    // Keep showing incoming frames when the hand briefly leaves view.
  }
  $('history-error').textContent = state.history_error || analyticsError;
  if (route === 'dashboard') renderAnalytics();
  speakAlerts(state);
}
function renderWritingEvidence(state) {
  const writing = state.writing || {}, active = state.started && !state.paused && state.settings.web.writing_enabled;
  const scores = active ? writing.family_scores || {} : {};
  $('writing-observation').textContent = !active ? 'Start hand tracking to measure writing.' : writing.phase !== 'monitoring' ? 'Learning the writing reference…' :
    `${writing.geometry_source === 'world' ? 'Estimated 3D hand geometry' : '2D hand geometry'} · ${writing.pen_observed ? scores.pen == null ? 'Pen markers visible · reset hand reference to score pen position' : 'Pen markers visible' : state.settings.web.writing_pen_markers ? 'Pen markers not observed' : 'Pen marker tracking off'}`;
  $('writing-family-scores').textContent = Object.entries({fingers: 'Fingers', wrist: 'Wrist', pen: 'Pen', pressure: 'Sensor force'})
    .map(([key, label]) => `${label}: ${scores[key] == null ? 'Not assessed' : `${scores[key]}/100`}`).join(' · ');
  const probability = active ? writing.learned_change?.probability : null;
  $('writing-learned').textContent = state.writing_model_error || (probability == null ? 'Learned change detector: no prediction. Train and load a model using labeled recordings.' :
    `Learned change likelihood: ${Math.round(probability * 100)}%. This experimental prediction is separate from reference alignment.`);
  const sensors = Object.entries(state.pressure || {}).map(([kind, sensor]) =>
    `${kind === 'grip_force' ? 'Grip' : 'Pen tip'}: ${sensor.fresh ? `${sensor.newtons.toFixed(2)} N` : 'Reading expired'} (${sensor.device})`);
  $('writing-pressure').textContent = sensors.join(' · ') || 'Force: connect a calibrated sensor to measure grip or tip force.';

}

function selectedRows() {
  const currentRow = current?.session;
  if (selectedSession && analyticsRange === 'session') return [selectedSession];
  if (analyticsRange === 'session') return currentRow ? [currentRow] : [];
  const rows = currentRow ? [currentRow, ...history.filter(row => row.id !== currentRow.id)] : history;
  const cutoff = Date.now() - Number(analyticsRange) * 86400000;
  return rows.filter(row => new Date(row.started).getTime() >= cutoff && row.demo === Boolean(current?.demo));
}
function renderIssueChart(entries, tracked) {
  const target = $('top-issues'); target.replaceChildren();
  const values = entries.filter(([, seconds]) => Number.isFinite(seconds) && seconds > 0);
  if (!values.length) {
    const empty = document.createElement('p'); empty.className = 'subtle';
    empty.textContent = tracked ? 'No changes' : 'No data'; target.append(empty); return;
  }
  const max = Math.max(...values.map(([, seconds]) => seconds));
  const magnitude = 10 ** Math.floor(Math.log10(max / 4));
  const step = [1, 2, 5, 10].map(n => n * magnitude).find(n => n >= max / 4);
  const ceiling = Math.ceil(max / step) * step;
  const width = 440, rowHeight = 40, axisY = values.length * rowHeight + 6;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${axisY + 38}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `Recurring changes by duration in seconds. ${values.map(([name, seconds]) => `${name}: ${Math.round(seconds)} seconds`).join('; ')}. Durations may overlap.`);
  function element(tag, attrs, content) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (content !== undefined) node.textContent = content;
    svg.append(node); return node;
  }
  for (let i = 0; i <= Math.round(ceiling / step); i++) {
    const seconds = i * step, x = 1 + seconds / ceiling * (width - 2);
    element('line', {x1: x, x2: x, y1: 0, y2: axisY, class: 'issue-chart-grid'});
    element('text', {x, y: axisY + 15, 'text-anchor': i === 0 ? 'start' : seconds >= ceiling ? 'end' : 'middle', class: 'issue-chart-tick'}, String(Number(seconds.toPrecision(6))));
  }
  values.forEach(([name, seconds], index) => {
    const y = index * rowHeight;
    element('text', {x: 1, y: y + 12, class: 'issue-chart-label'}, name);
    element('text', {x: width - 1, y: y + 12, 'text-anchor': 'end', class: 'issue-chart-value'}, `${Math.round(seconds)}s`);
    element('rect', {x: 1, y: y + 20, width: seconds / ceiling * (width - 2), height: 13, rx: 2, class: 'issue-chart-bar'});
  });
  element('text', {x: width / 2, y: axisY + 33, 'text-anchor': 'middle', class: 'issue-chart-tick'}, 'Duration (seconds)');
  target.append(svg);
}
function renderAnalytics() {
  const rows = selectedRows();
  const total = key => rows.reduce((sum, row) => sum + row[key], 0);
  const active = total('active_seconds'), tracked = total('tracked_seconds'), near = total('near_seconds');
  $('analytics-active').textContent = rows.length ? shortTime(active) : '—';
  $('analytics-near').textContent = percent(tracked ? 100 * near / tracked : null);
  $('analytics-coverage').textContent = percent(active ? 100 * tracked / active : null);
  $('analytics-movement').textContent = rows.length ? String(total('movement_resets')) : '—';
  const eyeSeconds = total('eye_seconds');
  $('analytics-blinks').textContent = eyeSeconds ? `${(total('eye_rate_sum') / eyeSeconds).toFixed(1)} / min` : '—';
  $('analytics-writing').textContent = rows.length ? shortTime(total('writing_seconds')) : '—';
  $('analytics-writing-change').textContent = rows.length ? shortTime(total('writing_changed_seconds')) : '—';
  const issues = {};
  rows.forEach(row => Object.entries(row.issues).forEach(([name, seconds]) => { issues[name] = (issues[name] || 0) + seconds; }));
  const top = Object.entries(issues).sort((a, b) => b[1] - a[1]).slice(0, 5);
  renderIssueChart(top, tracked);
  if (analyticsRange === 'session') {
    chartData = rows[0]?.timeline || [];
    chartLabels = chartData.map(bin => `${bin.minute}m`);
    $('chart-detail').textContent = selectedSession ? `Session started ${new Date(selectedSession.started).toLocaleString()}. Select “This session” to return to the current session.` : 'One bar per active minute. All configured posture views must be tracked; missing tracking is never counted as near reference. Sampled once per second.';
  } else {
    const days = new Map();
    rows.forEach(row => {
      const key = new Date(row.started).toLocaleDateString();
      const bucket = days.get(key) || {active: 0, tracked: 0, near: 0};
      bucket.active += row.active_seconds; bucket.tracked += row.tracked_seconds; bucket.near += row.near_seconds;
      days.set(key, bucket);
    });
    const entries = Array.from(days.entries()).reverse();
    chartData = entries.map(entry => entry[1]); chartLabels = entries.map(entry => entry[0]);
    $('chart-detail').textContent = 'One bar per day with saved sessions, grouped by session start date. Each bar shows the share of active time.';
  }
  $('chart-empty').hidden = !(!chartData.length || !active);
  $('chart-values').replaceChildren();
  chartData.forEach((bin, index) => {
    const tr = document.createElement('tr');
    [chartLabels[index], shortTime(bin.near), shortTime(Math.max(0, bin.tracked - bin.near)), shortTime(Math.max(0, bin.active - bin.tracked))].forEach(text => { const td = document.createElement('td'); td.textContent = text; tr.append(td); });
    $('chart-values').append(tr);
  });
  drawChart();
}
function drawChart() {
  const canvas = $('trend-chart'); const box = canvas.getBoundingClientRect();
  if (!box.width) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(box.width * dpr); canvas.height = Math.round(box.height * dpr);
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  const w = box.width, h = box.height, left = 32, top = 14, bottom = 29, area = h - top - bottom;
  ctx.font = '9px -apple-system, sans-serif';
  for (const percent of [0, .5, 1]) {
    const y = top + area * (1 - percent);
    ctx.strokeStyle = '#e5e5e7'; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(w - 8, y); ctx.stroke();
    ctx.fillStyle = '#6e6e73'; ctx.fillText(`${Math.round(percent * 100)}%`, 0, y + 3);
  }
  if (!chartData.length) return;
  const step = (w - left - 16) / chartData.length;
  chartData.forEach((bin, index) => {
    const bw = Math.min(56, Math.max(1, step * .76));
    const x = left + index * step + (step - bw) / 2;
    const near = bin.active ? bin.near / bin.active : 0;
    const changed = bin.active ? Math.max(0, bin.tracked - bin.near) / bin.active : 0;
    const untracked = bin.active ? Math.max(0, bin.active - bin.tracked) / bin.active : 0;
    let y = top + area;
    [[near, '#727278'], [changed, '#b5802b'], [untracked, '#e8e8ed']].forEach(([fraction, color]) => { const height = area * fraction; ctx.fillStyle = color; ctx.fillRect(x, y - height, bw, height); y -= height; });
    const stride = Math.max(1, Math.ceil(chartData.length / 7));
    if (index % stride === 0) { ctx.fillStyle = '#6e6e73'; ctx.fillText(chartLabels[index], x, h - 8, Math.max(step * stride - 5, 25)); }
  });
}
async function fetchAnalytics(repeat = true) {
  try {
    const response = await fetch('/api/analytics');
    if (!response.ok) throw new Error();
    const data = await response.json(); history = data.history; analyticsError = data.error || '';
    $('history-note').textContent = current?.demo ? 'Demo · sessions are not saved' : current?.settings.web.history_enabled ? '' : 'Session saving is off';
    $('history-note').hidden = !$('history-note').textContent;
    const body = $('session-history'); body.replaceChildren();
    const list = history.filter(row => row.id !== current?.session?.id || row.ended);
    if (!list.length) { const tr = document.createElement('tr'); const td = document.createElement('td'); td.colSpan = 6; td.textContent = 'No saved sessions'; tr.append(td); body.append(tr); }
    list.forEach(row => {
      const tr = document.createElement('tr');
      [`${new Date(row.started).toLocaleString()}${row.ended ? '' : ' · recovered checkpoint'}`, shortTime(row.active_seconds), percent(row.near_percent), percent(row.coverage_percent), String(row.movement_resets)].forEach(text => { const td = document.createElement('td'); td.textContent = text; tr.append(td); });
      const td = document.createElement('td'), button = document.createElement('button'); button.className = 'session-detail'; button.textContent = 'View'; button.setAttribute('aria-label', `View session from ${new Date(row.started).toLocaleString()}`);
      button.onclick = async () => {
        try {
          const response = await fetch(`/api/analytics?id=${encodeURIComponent(row.id)}`);
          const detail = await response.json();
          if (!response.ok) throw new Error(detail.error || 'Session details unavailable.');
          selectedSession = detail.session; analyticsRange = 'session'; selectRangeButtons();
          location.hash = '#dashboard'; renderAnalytics(); window.scrollTo(0, 0);
        } catch (error) { message(error.message, true); }
      };
      td.append(button); tr.append(td); body.append(tr);
    });
    if (route === 'dashboard') renderAnalytics();
  } catch (_) { analyticsError = 'Analytics history is unavailable while the server is disconnected.'; }
  finally { if (repeat) setTimeout(fetchAnalytics, 5000); }
}
function selectRangeButtons() {
  let selected;
  [['range-session', 'session'], ['range-week', '7'], ['range-month', '30']].forEach(([id, value]) => {
    const button = $(id), active = analyticsRange === value;
    button.classList.toggle('selected', active);
    button.setAttribute('aria-pressed', String(active));
    if (active) selected = button;
  });
  if (selected?.offsetWidth) {
    const indicator = $('range-indicator');
    indicator.style.width = `${selected.offsetWidth}px`;
    indicator.style.transform = `translateX(${selected.offsetLeft}px)`;
  }
}
let rangeAnimations = [];
function switchAnalyticsRange(value) {
  if (analyticsRange === value && !selectedSession) return;
  rangeAnimations.forEach(animation => animation.cancel());
  rangeAnimations = [];
  selectedSession = null;
  analyticsRange = value;
  selectRangeButtons();
  renderAnalytics();
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const panels = document.querySelectorAll('#view-dashboard .analytic-card, #view-dashboard .analytics-grid > .panel, #view-dashboard .eyes-writing');
  panels.forEach((panel, index) => {
    if (!panel.animate) return;
    rangeAnimations.push(panel.animate([
      {opacity: .45, transform: 'translateY(5px)'},
      {opacity: 1, transform: 'translateY(0)'}
    ], {duration: 340, delay: Math.min(index * 22, 110), easing: 'cubic-bezier(.22, 1, .36, 1)', fill: 'backwards'}));
  });
}
function loadVoices() {
  if (!('speechSynthesis' in window)) { $('voice-status').textContent = 'This browser does not support spoken reminders.'; $('test-voice').disabled = true; return; }
  localVoices = speechSynthesis.getVoices().filter(voice => voice.localService);
  const select = $('speech_voice'), old = select.value || preferredVoice;
  select.replaceChildren(); const option = document.createElement('option'); option.value = ''; option.textContent = 'System default · local'; select.append(option);
  localVoices.forEach(voice => { const option = document.createElement('option'); option.value = voice.name; option.textContent = `${voice.name} · ${voice.lang}`; select.append(option); });
  select.value = localVoices.some(voice => voice.name === old) ? old : '';
}
function say(text, test = false) {
  if (!('speechSynthesis' in window) || !localVoices.length) { $('voice-status').textContent = 'No local speech voice is available. Install an OS voice or try another browser.'; return; }
  const name = test ? $('speech_voice').value : current?.settings.web.speech_voice;
  const voice = localVoices.find(voice => voice.name === name) || localVoices.find(voice => voice.default) || localVoices.find(voice => voice.lang.startsWith(navigator.language.split('-')[0])) || localVoices[0];
  const sequence = ++speechSequence;
  speechSynthesis.cancel();
  testingSpeech = test;
  const utterance = new SpeechSynthesisUtterance(text); utterance.voice = voice;
  utterance.rate = test ? Number($('speech_rate').value) || 1 : current.settings.web.speech_rate;
  utterance.volume = test ? Number($('speech_volume').value) : current.settings.web.speech_volume;
  utterance.onend = () => { if (sequence !== speechSequence) return; testingSpeech = false; $('voice-status').textContent = 'Voice ready. Automatic warnings follow your saved reminder settings.'; };
  utterance.onerror = () => { if (sequence !== speechSequence) return; testingSpeech = false; $('voice-status').textContent = 'Speech was interrupted or blocked. Use Enable & test voice to retry.'; };
  speechSynthesis.speak(utterance);
}
function ownSpeechLease() {
  try {
    const raw = localStorage.getItem('still-voice-owner'); const lease = raw ? JSON.parse(raw) : null;
    if (lease && lease.id !== speechOwner && Date.now() - lease.time < 6000) return false;
    localStorage.setItem('still-voice-owner', JSON.stringify({id: speechOwner, time: Date.now()})); return true;
  } catch (_) { return document.hasFocus(); }
}
function speakAlerts(state) {
  if (!('speechSynthesis' in window) || testingSpeech) return;
  if (!state.settings.web.spoken_alerts || !speechArmed || state.paused || state.quiet || state.snooze_seconds || !state.started) {
    speechSynthesis.cancel(); speechActive.clear(); return;
  }
  if (!ownSpeechLease()) return;
  const now = Date.now(), events = new Set(state.alerts);
  const fresh = [...events].filter(text => !speechActive.has(text) && now - (speechLast[text] || 0) >= state.settings.web.cooldown_seconds * 1000);
  if (fresh.length) { say(fresh.slice(0, 2).join(' ')); fresh.forEach(text => { speechLast[text] = now; }); }
  speechActive = events;
}
async function startSession(target = 'monitor') {
  speechArmed = true;
  const data = await command('start');
  if (data) location.hash = `#${target}`;
}
$('start').onclick = () => startSession();
$('session-start').onclick = () => startSession();
$('pause').onclick = () => { speechArmed = true; command('pause'); };
$('stop').onclick = () => command('stop');
$('recalibrate').onclick = () => command('recalibrate');
$('snooze').onclick = () => command('snooze', {minutes: Number($('snooze-minutes').value)});
$('unsnooze').onclick = () => command('unsnooze');
let preferenceTimer;
let preferenceSaving = false;
const pendingPreferences = new Map();
const invalidPreferences = new Set();
function queuePreference(field) {
  if (!fields.includes(field.id)) return;
  const key = field.id;
  if (!field.checkValidity() || (numeric.includes(key) && field.value === '')) {
    pendingPreferences.delete(key); invalidPreferences.add(key);
    $('save-status').textContent = 'Check the highlighted value';
    field.setAttribute('aria-invalid', 'true');
    clearTimeout(preferenceTimer); return;
  }
  invalidPreferences.delete(key); field.removeAttribute('aria-invalid');
  pendingPreferences.set(key, checks.includes(key) ? field.checked : numeric.includes(key) ? Number(field.value) : field.value);
  if (key === 'spoken_alerts' && field.checked) speechArmed = true;
  $('save-status').textContent = 'Saving…';
  clearTimeout(preferenceTimer);
  preferenceTimer = setTimeout(savePreferences, 600);
}
async function savePreferences() {
  clearTimeout(preferenceTimer);
  if (!pendingPreferences.size || preferenceSaving) return;
  if (busy) { preferenceTimer = setTimeout(savePreferences, 200); return; }
  preferenceSaving = true;
  const settings = Object.fromEntries(pendingPreferences);
  $('save-status').textContent = 'Saving…';
  const result = await command('settings', {settings}, {preserveDraft: true});
  preferenceSaving = false;
  if (result) {
    for (const [key, value] of Object.entries(settings)) {
      if (pendingPreferences.get(key) === value) pendingPreferences.delete(key);
    }
    $('save-status').textContent = invalidPreferences.size ? 'Check the highlighted value' : pendingPreferences.size ? 'Saving…' : 'All changes saved';
    if (pendingPreferences.size) preferenceTimer = setTimeout(savePreferences, 0);
  } else {
    $('save-status').textContent = 'Not saved. ' + ($('message').textContent || 'Change a value to retry.');
  }
}
$('clear-quiet').onclick = () => {
  for (const key of ['quiet_start', 'quiet_end']) { $(key).value = ''; queuePreference($(key)); }
};
$('preferences').oninput = event => queuePreference(event.target);
$('preferences').onchange = event => queuePreference(event.target);
$('preferences').onsubmit = event => { event.preventDefault(); savePreferences(); };
const settingsTabs = [...document.querySelectorAll('.settings-nav [role="tab"]')];
function selectSettingsTab(tab) {
  for (const item of settingsTabs) {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1;
    $(item.getAttribute('aria-controls')).hidden = !selected;
  }
  const content = document.querySelector('.settings-content');
  if (content) content.scrollTop = 0;
}
settingsTabs.forEach((tab, index) => {
  tab.onclick = () => selectSettingsTab(tab);
  tab.onkeydown = event => {
    const direction = {ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1}[event.key];
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? settingsTabs.length - 1 : direction ? (index + direction + settingsTabs.length) % settingsTabs.length : null;
    if (next !== null) { event.preventDefault(); selectSettingsTab(settingsTabs[next]); settingsTabs[next].focus(); }
  };
});
$('test-voice').onclick = () => { speechArmed = true; loadVoices(); say('Still is ready. I will gently remind you when a visible change persists.', true); };
$('enable-writing').onclick = async () => {
  if (!current) return;
  if (!current.settings.web.writing_enabled) {
    const data = await command('settings', {settings: {writing_enabled: true}});
    if (!data) return;
  }
  if (!current.started) await startSession();
  else if (current.paused) await command('pause');
};
$('writing-calibrate').onclick = async () => {
  if (!current) return;
  const changed = !current.settings.web.writing_enabled;
  if (changed && !await command('settings', {settings: {writing_enabled: true}})) return;
  if (!current.started) await startSession();
  else if (current.paused) await command('pause');
  else if (!changed) await command('writing_calibrate');
};
$('clear-history').onclick = async () => {
  if (!confirm('Permanently clear all saved session summaries on this computer? This cannot be undone.')) return;
  const data = await command('clear_history');
  if (data) { selectedSession = null; history = []; renderAnalytics(); message('Local history cleared.'); }
};
[['range-session', 'session'], ['range-week', '7'], ['range-month', '30']].forEach(([id, value]) => { $(id).onclick = () => switchAnalyticsRange(value); });
if ('speechSynthesis' in window) speechSynthesis.addEventListener('voiceschanged', loadVoices);
window.addEventListener('resize', () => { drawChart(); selectRangeButtons(); });
window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); installPrompt = event; $('install-app').hidden = false; });
$('install-app').onclick = async () => { if (installPrompt) { await installPrompt.prompt(); installPrompt = null; $('install-app').hidden = true; } };
window.addEventListener('pagehide', () => { if ('speechSynthesis' in window) speechSynthesis.cancel(); try { const lease = JSON.parse(localStorage.getItem('still-voice-owner') || '{}'); if (lease.id === speechOwner) localStorage.removeItem('still-voice-owner'); } catch (_) {} });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
setRoute(location.hash.slice(1)); selectRangeButtons(); loadVoices();
poll(); fetchAnalytics(); feed('front'); feed('side'); feed('writing');

// Secondary tools open over the workspace, keeping the camera and controls in place.
const workspaceDrawers = [...document.querySelectorAll('.app-popover, #alert-panel')];
workspaceDrawers.forEach(drawer => drawer.addEventListener('toggle', () => {
  if (drawer.open) workspaceDrawers.forEach(other => { if (other !== drawer && !other.contains(drawer) && !drawer.contains(other)) other.open = false; });
}));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') workspaceDrawers.forEach(drawer => { drawer.open = false; });
});

$('preferences').addEventListener('invalid', event => {
  const group = event.target.closest('.settings-group');
  if (group) { const tab = settingsTabs.find(item => item.getAttribute('aria-controls') === group.id); if (tab) selectSettingsTab(tab); }
}, true);

$('fatigue-break').onclick = () => command('take_break');

async function endBreak() {
  if (breakResumePending || disconnected || !current?.started || !current.paused) return;
  breakResumePending = true;
  $('end-break').disabled = true;
  try {
    // A settings save must finish before sending the resume action.
    while (busy) await new Promise(resolve => setTimeout(resolve, 50));
    if (!disconnected && current?.started && current.paused) await command('end_break');
  } finally {
    breakResumePending = false;
    $('end-break').disabled = disconnected;
  }
}
$('end-break').onclick = endBreak;
