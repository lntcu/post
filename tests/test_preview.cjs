const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/app.js'), 'utf8');
test('every startup control binding has an element in the page', () => {
  const html = fs.readFileSync(require('node:path').join(__dirname, '../web/index.html'), 'utf8');
  const boundIds = [...source.matchAll(/\$\('([^']+)'\)\.(?:onclick|onchange|addEventListener)/g)].map(match => match[1]);
  const missing = [...new Set(boundIds)].filter(id => !html.includes(`id="${id}"`));
  assert.deepEqual(missing, []);
});
function fixture() {
  const nodes = new Map();
  const resets = [];
  const state = {started: true, paused: false, settings: {web: {writing_enabled: true, writing_hand: 'right', writing_source: '2'}}, writing: {confidence: 'Available', phase: 'monitoring', remaining: 0}};
  const context = vm.createContext({
    document: {body: {dataset: {}}},
    $: id => { if (!nodes.has(id)) nodes.set(id, {dataset: {}, hidden: false, replaceChildren() {}, closest() { return this; }}); return nodes.get(id); },
    resetCamera: (...args) => resets.push(args), badge() {}, metrics() {}, guidance() {}, speakAlerts() {},
    route: 'monitor', analyticsError: '', current: state, lastFrame: {writing: 9500},
    Date: {now: () => 10000}, setTimeout() {},
    URL: {createObjectURL: () => 'blob:new-frame', revokeObjectURL() {}},
    fetch: async () => ({ok: true, blob: async () => ({})}),
  });
  vm.runInContext(source.slice(source.indexOf('function renderApp('), source.indexOf('function selectedRows(')), context);
  vm.runInContext(source.slice(source.indexOf('async function feed('), source.indexOf('\nconst routes =')), context);
  context.state = state;
  return {context, state, nodes, resets};
}
test('hand tracking loss does not hide an incoming camera preview', async () => {
  const {context, state, nodes, resets} = fixture();
  for (const confidence of ['Available', 'Unavailable', 'Available', 'Unavailable']) {
    state.writing.confidence = confidence;
    vm.runInContext('renderApp(state)', context);
    await vm.runInContext("feed('writing')", context);
    assert.equal(nodes.get('writing-feed').hidden, false);
    assert.equal(nodes.get('writing-placeholder').hidden, true);
  }
  assert.equal(resets.length, 0);
});
test('pause, stop, and disabled writing still clear the preview', () => {
  for (const change of ['pause', 'stop', 'disable']) {
    const {context, state, resets} = fixture();
    if (change === 'pause') state.paused = true;
    if (change === 'stop') state.started = false;
    if (change === 'disable') state.settings.web.writing_enabled = false;
    vm.runInContext('renderApp(state)', context);
    assert.equal(resets.length, 1);
    assert.equal(resets[0][0], 'writing');
  }
});
test('one dropped frame preserves the preview, but a stalled feed clears it', async () => {
  const {context, resets} = fixture();
  context.fetch = async () => { throw new Error('Dropped request'); };
  await vm.runInContext("feed('writing')", context);
  assert.equal(resets.length, 0);
  context.lastFrame.writing = 5000;
  await vm.runInContext("feed('writing')", context);
  assert.equal(resets.length, 1);
  assert.equal(resets[0][1], 'Feed unavailable');
});
test('shared-camera monitor uses one feed for posture and hand tracking', async () => {
  const {context, state} = fixture();
  state.settings.web.writing_source = '';
  const requested = [];
  context.fetch = async url => { requested.push(url); return {ok: true, blob: async () => ({})}; };
  state.cameras = {front: {confidence: 'Available'}};
  await vm.runInContext("feed('writing')", context);
  await vm.runInContext("feed('front')", context);
  assert.equal(requested.length, 1);
  assert.match(requested[0], /^\/feed\/front\.jpg/);
});
test('dedicated-camera monitor streams the posture and hand views together', async () => {
  const {context, state} = fixture();
  const requested = [];
  context.fetch = async url => { requested.push(url); return {ok: true, blob: async () => ({})}; };
  state.cameras = {front: {confidence: 'Available'}};
  await vm.runInContext("feed('writing')", context);
  await vm.runInContext("feed('front')", context);
  assert.equal(requested.length, 2);
  assert.match(requested[0], /^\/feed\/writing\.jpg/);
  assert.match(requested[1], /^\/feed\/front\.jpg/);
});
test('old writing links resolve to the unified monitor', () => {
  const {context, nodes} = fixture();
  let replaced;
  context.routes = {dashboard: ['Dashboard'], monitor: ['Live monitor'], settings: ['Settings']};
  context.document.querySelectorAll = () => [];
  context.window = {history: {replaceState: (_state, _title, hash) => { replaced = hash; }}, scrollTo() {}};
  vm.runInContext(source.slice(source.indexOf('function setRoute('), source.indexOf("window.addEventListener('hashchange'")), context);
  vm.runInContext("setRoute('writing')", context);
  assert.equal(context.route, 'monitor');
  assert.equal(replaced, '#monitor');
  assert.equal(nodes.get('view-monitor').hidden, false);
  assert.equal(nodes.get('view-dashboard').hidden, true);
});

test('eyes score waits for tracking and an observation window, then counts detected cues', () => {
  const context = vm.createContext({Number, Set});
  vm.runInContext(source.slice(source.indexOf('function eyeCueAssessment('), source.indexOf('function renderCoaching(')), context);
  const eye = {confidence: 'Available', openness: .3, blinks_per_minute: 12, closed_fraction: .1, reasons: []};
  context.state = {started: true, paused: false, cameras: {front: {eye}}};
  const assess = () => vm.runInContext('eyeCueAssessment(state)', context);
  assert.equal(assess().score, 100);
  eye.reasons = ['Low blink rate', 'Long time without a blink'];
  assert.equal(assess().score, 50);
  eye.closed_fraction = null;
  assert.equal(assess().score, null);
  eye.closed_fraction = .1; eye.confidence = 'Unavailable';
  assert.equal(assess().score, null);
  eye.confidence = 'Available'; context.state.paused = true;
  assert.equal(assess().score, null);
});

function reminderFixture() {
  const context = vm.createContext({Map, Set, JSON});
  vm.runInContext(source.slice(source.indexOf('function steadyReminders('), source.indexOf('function renderFloatingReminders(')), context);
  const buffer = new Map();
  return {buffer, update: (items, now, muted = false) => context.steadyReminders(buffer, items, now, muted)};
}
test('qualified reminders appear immediately and stay readable after a cue clears', () => {
  const {update} = reminderFixture();
  const item = {category: 'Eyes', message: 'Blink and look away', severity: 'warning', score: 75};
  const first = update([item], 0)[0]; assert.ok(first);
  assert.equal(update([], 4000)[0], first);
  assert.equal(update([{...item, score: 70, severity: 'attention'}], 5000)[0], first);
  assert.equal(update([], 10000).length, 1);
  assert.equal(update([], 15000).length, 0);
});
test('dismissed reminders stay quiet through brief cue disappearance', () => {
  const {update} = reminderFixture();
  const item = {category: 'Eyes', message: 'Blink', severity: 'warning'};
  const entry = update([item], 0)[0];
  entry.dismissedUntil = 30000; entry.shownAt = null;
  assert.equal(update([], 1000).length, 0);
  assert.equal(update([item], 2000).length, 0);
  assert.equal(update([item], 30000).length, 1);
});
test('dismissal survives score updates and quieting clears immediately', () => {
  const {update, buffer} = reminderFixture();
  const item = {category: 'Posture', message: 'Relax shoulders', severity: 'warning', score: 60};
  for (let now = 0; now < 3000; now += 500) update([item], now);
  const entry = update([item], 3000)[0];
  entry.dismissedUntil = 33000; entry.shownAt = null;
  for (let now = 3500; now < 33000; now += 500) assert.equal(update([{...item, score: 55}], now).length, 0);
  assert.equal(update([item], 33000).length, 1);
  assert.equal(update([item], 34000, true).length, 0); assert.equal(buffer.size, 0);
});
test('duplicate blink cues become the same concise actionable reminder', () => {
  const context = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('function conciseReminder('), source.indexOf('// Keep reminder identity')), context);
  const first = context.conciseReminder({category: 'Eyes', message: 'Long stare: blink and refocus away from the screen.'});
  const second = context.conciseReminder({category: 'Eyes', message: 'Blinking infrequently: blink fully and look away.'});
  assert.equal(first.message, second.message);
  assert.equal(first.message, 'Blink fully, then look away for a moment.');
});

test('calibration opens for posture and hand, shows countdowns, and hides after both finish', () => {
  function node() { return {dataset: {}, children: [], hidden: false, open: false, append(...items) { this.children.push(...items); items.forEach(item => { item.remove = () => { const index = this.children.indexOf(item); if (index >= 0) this.children.splice(index, 1); }; }); }, querySelector() { return this.children[1]; }}; }
  const nodes = new Map();
  const context = vm.createContext({document: {createElement: node}, $: id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); }, route: 'monitor'});
  vm.runInContext(source.slice(source.indexOf('function renderCalibration('), source.indexOf('function render(state)')), context);
  const front = {phase: 'calibrating', calibration_remaining: 3.2};
  const hand = {phase: 'calibrating', remaining: 4.1};
  const state = {started: true, paused: false, cameras: {front}, writing: hand, settings: {web: {writing_enabled: true}}};
  context.renderCalibration(state);
  assert.equal(nodes.get('setup').open, true);
  const rows = nodes.get('calibration-countdowns').children;
  assert.equal(rows[0].children[1].textContent, '3.2s');
  assert.equal(rows[1].children[1].textContent, '4.1s');
  assert.equal(nodes.get('calibration-progress').max, 17);
  assert.ok(Math.abs(nodes.get('calibration-progress').value - 9.7) < 1e-9);
  // Allow removal of completed countdowns from the small DOM fixture.
  rows.forEach(row => { row.remove = () => { const list = nodes.get('calibration-countdowns').children; list.splice(list.indexOf(row), 1); }; });
  front.phase = 'monitoring';
  context.renderCalibration(state);
  assert.equal(nodes.get('setup').hidden, false);
  assert.equal(nodes.get('calibration-countdowns').children.length, 1);
  hand.phase = 'monitoring'; hand.calibrated = true;
  context.renderCalibration(state);
  assert.equal(nodes.get('setup').hidden, true);
  assert.equal(nodes.get('setup').open, false);
  hand.phase = 'positioning';
  context.renderCalibration(state);
  assert.equal(nodes.get('setup').hidden, true); // Losing the hand does not reopen completed setup.
  hand.phase = 'calibrating'; hand.calibrated = false; hand.remaining = 5;
  context.renderCalibration(state);
  assert.equal(nodes.get('setup').hidden, false);
  assert.equal(nodes.get('setup').open, true);
  nodes.get('calibration-countdowns').children.forEach(row => { row.remove = () => { const list = nodes.get('calibration-countdowns').children; list.splice(list.indexOf(row), 1); }; });
  state.started = false; context.renderCalibration(state); nodes.get('setup').open = true;
  context.renderCalibration(state);
  assert.equal(nodes.get('setup').open, true); // Idle setup remains manually usable.
});

test('uncalibrated hand keeps setup visible while waiting for tracking', () => {
  function node() { return {dataset: {}, children: [], hidden: false, open: false}; }
  const nodes = new Map();
  const context = vm.createContext({document: {createElement: node}, $: id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); }, route: 'monitor'});
  vm.runInContext(source.slice(source.indexOf('function renderCalibration('), source.indexOf('function render(state)')), context);
  const state = {started: true, paused: false, cameras: {front: {phase: 'monitoring'}},
    writing: {phase: 'positioning', calibrated: false, hint: 'Show your writing hand'},
    settings: {web: {writing_enabled: true, writing_assessment: 'geometry'}}};
  context.renderCalibration(state);
  assert.equal(nodes.get('setup').hidden, false);
  assert.equal(nodes.get('setup').open, true);
  assert.equal(nodes.get('setup-hint').textContent, 'Show your writing hand');
  state.settings.web.writing_enabled = false;
  context.renderCalibration(state);
  assert.equal(nodes.get('setup').hidden, true);
});

test('grip and wrist calibration enables the live hand feed and starts the session', async () => {
  const nodes = new Map();
  const calls = [];
  const current = {started: false, paused: false, settings: {web: {writing_enabled: false}}};
  const context = vm.createContext({current, $: id => { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); },
    command: async (action, extra) => { calls.push([action, extra]); if (action === 'settings') Object.assign(current.settings.web, extra.settings); return current; },
    startSession: async () => { calls.push(['start']); current.started = true; }});
  vm.runInContext(source.slice(source.indexOf("$('writing-calibrate').onclick ="), source.indexOf("$('clear-history').onclick =")), context);
  await nodes.get('writing-calibrate').onclick();
  assert.deepEqual(calls.map(([action]) => action), ['settings', 'start']);
  assert.equal(current.settings.web.writing_enabled, true);
  calls.length = 0;
  await nodes.get('writing-calibrate').onclick();
  assert.deepEqual(calls.map(([action]) => action), ['writing_calibrate']);
});

test('tiredness prompt shows evidence and break action, then clears on lost tracking', () => {
  const nodes = new Map();
  const context = vm.createContext({
    $: id => { if (!nodes.has(id)) nodes.set(id, {hidden: false, classList: {toggle() {}}}); return nodes.get(id); },
    formatTime: seconds => `${seconds}s`,
  });
  vm.runInContext(source.slice(source.indexOf('function renderFatigue('), source.indexOf('function render(state)')), context);
  const state = {started: true, paused: false, settings: {web: {fatigue_alerts: true}}, cameras: {front: {fatigue: {
    warning: true, guidance: 'Take a break.', reasons: ['Prolonged eye closure']
  }}}};
  context.renderFatigue(state);
  assert.equal(nodes.get('fatigue-break').hidden, false);
  assert.equal(nodes.get('fatigue-status').textContent, 'You may be tired.');
  state.snooze_seconds = 60;
  context.renderFatigue(state);
  assert.match(nodes.get('fatigue-break-detail').textContent, /snoozed/);
  state.paused = true; state.break_seconds = 120;
  context.renderFatigue(state);
  assert.equal(nodes.get('fatigue-break').hidden, true);
  assert.match(nodes.get('fatigue-status').textContent, /120s/);
  assert.match(nodes.get('fatigue-break-detail').textContent, /Resume when ready/);
  state.paused = false; state.cameras = {};
  context.renderFatigue(state);
  assert.equal(nodes.get('fatigue-break').hidden, true);
  assert.match(nodes.get('fatigue-status').textContent, /unavailable/);
});

test('overall alignment averages only available scores, including eyes and zero values', () => {
  const context = vm.createContext({Number, Math});
  vm.runInContext(source.slice(source.indexOf('function availableAlignment('), source.indexOf('function renderCoaching(')), context);
  const parts = [{score: 65, severity: 'attention'}, {score: 75, severity: 'suggestion'}, {score: null, severity: 'neutral'}];
  let result = context.availableAlignment(parts);
  assert.equal(result.score, 70); assert.equal(result.count, 2); assert.equal(result.partial, true); assert.equal(result.severity, 'attention');
  parts[0].score = 0;
  assert.equal(context.availableAlignment(parts).score, 38);
  assert.equal(context.availableAlignment([{score: 90, severity: 'success'}]).score, 90);
  assert.equal(context.availableAlignment([{score: null}]).score, null);
  assert.equal(context.availableAlignment(parts, false).score, null);
});

function preferenceFixture(command) {
  const nodes = new Map(); const timers = new Map(); let timerId = 0;
  const context = vm.createContext({
    $: id => { if (!nodes.has(id)) nodes.set(id, {id, value: '', textContent: '', valid: true, checkValidity() { return this.valid; }, setAttribute() {}, removeAttribute() {}}); return nodes.get(id); },
    fields: ['camera', 'speech_volume', 'writing_enabled'], numeric: ['camera', 'speech_volume'], checks: ['writing_enabled'],
    busy: false, speechArmed: false, command,
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: id => timers.delete(id),
  });
  const start = source.indexOf('let preferenceTimer;');
  vm.runInContext(source.slice(start, source.indexOf('const settingsTabs', start)), context);
  return {context, nodes, timers, queue(id, value) {
    const field = context.$(id); field.value = value;
    context.queuePreference(field); return field;
  }};
}
test('automatic preferences save only changed values and preserve drafts', async () => {
  const calls = [];
  const f = preferenceFixture(async (...args) => { calls.push(args); return {}; });
  f.queue('speech_volume', '.4');
  await f.context.savePreferences();
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0])), ['settings', {settings: {speech_volume: .4}}, {preserveDraft: true}]);
  assert.equal(f.nodes.get('save-status').textContent, 'All changes saved');
});
test('edits during an automatic save are queued for the next save', async () => {
  let finish; const calls = [];
  const f = preferenceFixture((action, payload) => { calls.push(payload); return new Promise(resolve => { finish = resolve; }); });
  f.queue('speech_volume', '.4');
  const saving = f.context.savePreferences();
  f.queue('speech_volume', '.7');
  finish({}); await saving;
  const next = f.context.savePreferences();
  assert.equal(calls[1].settings.speech_volume, .7);
  finish({}); await next;
  assert.equal(f.nodes.get('save-status').textContent, 'All changes saved');
});
test('invalid numeric preferences are not sent and failed saves can be retried', async () => {
  let succeed = false; const calls = [];
  const f = preferenceFixture(async (action, payload) => { calls.push(payload); return succeed ? {} : undefined; });
  f.queue('camera', ''); await f.context.savePreferences();
  assert.equal(calls.length, 0);
  f.queue('camera', '2'); await f.context.savePreferences();
  assert.match(f.nodes.get('save-status').textContent, /Not saved/);
  succeed = true; await f.context.savePreferences();
  assert.equal(calls[1].settings.camera, 2);
  assert.equal(f.nodes.get('save-status').textContent, 'All changes saved');
});
test('automatic preference saves wait for other commands instead of dropping changes', async () => {
  const calls = [];
  const f = preferenceFixture(async (action, payload) => { calls.push(payload); return {}; });
  f.context.busy = true; f.queue('camera', '2');
  await f.context.savePreferences(); assert.equal(calls.length, 0);
  f.context.busy = false; await f.context.savePreferences();
  assert.equal(calls[0].settings.camera, 2);
});

test('range transitions cancel previous motion and respect reduced motion', () => {
  let reduced = false, renders = 0, canceled = 0, animations = 0;
  const buttons = new Map(['range-session', 'range-week', 'range-month', 'range-indicator'].map((id, index) => [id, {
    offsetWidth: 100, offsetLeft: index * 103 + 3, style: {}, classList: {toggle() {}}, setAttribute() {}
  }]));
  const context = vm.createContext({
    analyticsRange: 'session', selectedSession: null,
    $: id => buttons.get(id),
    renderAnalytics: () => renders++,
    window: {matchMedia: () => ({matches: reduced})},
    document: {querySelectorAll: () => [{animate: () => { animations++; return {cancel: () => canceled++}; }}]},
  });
  vm.runInContext(source.slice(source.indexOf('function selectRangeButtons('), source.indexOf('function loadVoices(')), context);
  context.switchAnalyticsRange('7');
  assert.equal(context.analyticsRange, '7');
  assert.equal(animations, 1);
  assert.equal(buttons.get('range-indicator').style.transform, 'translateX(106px)');
  context.switchAnalyticsRange('30');
  assert.equal(canceled, 1);
  context.switchAnalyticsRange('30');
  assert.equal(renders, 2); // Selecting the same range does not replay motion.
  reduced = true;
  context.switchAnalyticsRange('session');
  assert.equal(canceled, 2);
  assert.equal(animations, 2); // Reduced motion still updates data immediately.
  assert.equal(renders, 3);
});

test('centered break countdown supports early end, completion, and normal pause', () => {
  const nodes = new Map();
  const context = vm.createContext({
    document: {body: {classList: {toggle() {}}}},
    $: id => { if (!nodes.has(id)) nodes.set(id, {style: {}, setAttribute(name, value) {this[name] = value;}}); return nodes.get(id); }
  });
  vm.runInContext(source.slice(source.indexOf('let breakResumePending ='), source.indexOf('function render(state)')), context);
  const state = {started: true, paused: true, break_active: true, break_seconds: 83};
  context.renderBreak(state);
  assert.equal(nodes.get('break-screen').hidden, false);
  assert.equal(nodes.get('break-time').textContent, '1:23');
  assert.equal(nodes.get('break-progress')['aria-valuenow'], '83');
  assert.equal(nodes.get('end-break').textContent, 'End break early');
  assert.ok(Number(nodes.get('break-ring').style.strokeDashoffset) > 30);
  delete state.break_active; // Older servers omit this field.
  state.break_seconds = 0;
  context.renderBreak(state);
  assert.equal(nodes.get('break-screen').hidden, false);
  assert.equal(nodes.get('end-break').textContent, 'Resume session');
  assert.equal(nodes.get('break-time').textContent, '0:00');
  state.break_active = false;
  context.renderBreak(state);
  assert.equal(nodes.get('break-screen').hidden, true);
  state.paused = false;
  context.renderBreak(state);
  assert.equal(nodes.get('break-screen').hidden, true);
});

test('ending a break works with current and older running servers without toggling a resumed session', async () => {
  for (const scenario of ['current', 'legacy', 'manual-snooze', 'already-resumed']) {
    const actions = [];
    const legacy = scenario !== 'current';
    const snapshot = {started: true, paused: scenario !== 'already-resumed', break_seconds: 50,
      snooze_seconds: scenario === 'manual-snooze' ? 600 : 50};
    const context = vm.createContext({
      token: 'test-token', busy: false, current: snapshot, window: {},
      message() {}, render() {},
      fetch: async (url, options) => {
        if (url === '/api/state') return {ok: true, json: async () => snapshot};
        const action = JSON.parse(options.body).action;
        actions.push(action);
        const unsupported = legacy && action === 'end_break';
        return {ok: !unsupported, json: async () => unsupported ? {error: 'Unknown action.'} : {...snapshot, paused: false}};
      },
    });
    vm.runInContext(source.slice(source.indexOf('async function command('), source.indexOf('function guidance(')), context);
    await context.command('end_break');
    assert.deepEqual(actions, scenario === 'current' || scenario === 'already-resumed' ? ['end_break']
      : scenario === 'manual-snooze' ? ['end_break', 'pause'] : ['end_break', 'pause', 'unsnooze']);
  }
});

test('repeated early-resume clicks send only one action', async () => {
  let release, sent = 0;
  const button = {};
  const context = vm.createContext({
    breakResumePending: false, disconnected: false, busy: false,
    current: {started: true, paused: true}, $: () => button,
    command: () => { sent++; return new Promise(resolve => { release = resolve; }); },
  });
  vm.runInContext(source.slice(source.indexOf('async function endBreak('), source.indexOf("$('end-break').onclick")), context);
  const first = context.endBreak();
  await context.endBreak();
  assert.equal(sent, 1);
  assert.equal(button.disabled, true);
  release(); await first;
  assert.equal(button.disabled, false);
});

function alignmentFixture(storage = new Map()) {
  const context = vm.createContext({
    sessionStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
  });
  vm.runInContext(source.slice(source.indexOf('let observedAlignment;'), source.indexOf('function renderCoaching(')), context);
  return context;
}
test('observed session average weights time, survives reload, and resets for a new session', () => {
  const storage = new Map(), context = alignmentFixture(storage);
  const state = {started: true, paused: false, session: {id: 'a', active_seconds: 0}};
  assert.equal(context.sessionAlignment(state, 100).score, null);
  state.session.active_seconds = 2;
  assert.equal(context.sessionAlignment(state, 100).score, 100);
  state.session.active_seconds = 3;
  assert.equal(context.sessionAlignment(state, 0).score, 67);
  state.session.active_seconds = 4;
  assert.equal(context.sessionAlignment(state, null).score, 67);
  state.paused = true;
  assert.equal(context.sessionAlignment(state, null).score, 67);
  state.paused = false; state.session.active_seconds = 10;
  assert.equal(context.sessionAlignment(state, 0).score, 67);
  const reloaded = alignmentFixture(storage);
  assert.equal(reloaded.sessionAlignment(state, 0).score, 67);
  state.session.id = 'b'; state.session.active_seconds = 0;
  assert.equal(reloaded.sessionAlignment(state, 100).score, null);
});
test('server session averages override the compatibility accumulator', () => {
  const context = alignmentFixture();
  const average = context.sessionAlignment({session: {id: 'a', average_alignment: 62, alignment_seconds: 120}}, 100);
  assert.equal(average.score, 62); assert.equal(average.seconds, 120); assert.equal(average.local, false);
});
