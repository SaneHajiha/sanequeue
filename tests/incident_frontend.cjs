/* Dependency-free browser lifecycle regressions against the shipped script. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname,
  '../qpanel/themes/qpanel/static/js/incident-notices.js'), 'utf8');

function setup(view = 'telephony') {
  const requests = [], observers = [], elements = {}, timers = new Map(), storage = new Map(), listeners = new Map();
  let timerSequence = 0;
  const make = () => ({
    disabled: false, value: '', checked: false, hidden: false, files: [], textContent: '',
    replaceChildren() { this.children = []; this.value = ''; },
    removeAttribute() {}, setAttribute() {}, append() {},
    add(option) {
      (this.children ??= []).push(option);
      if (!this.value) this.value = option.value;
    },
  });
  const fields = {};
  for (const name of ['binding', 'title', 'enabled', 'starts_at', 'expires_at', 'audio_file']) {
    fields[name] = make();
  }
  const button = make(), form = make();
  form.elements = fields;
  form.querySelectorAll = () => [...Object.values(fields), button];
  form.querySelector = () => button;
  for (const name of ['incident-form', 'incident-audio', 'incident-integration',
    'incident-feedback', 'incident-current', 'incident-refresh',
    'incident-timezone', 'ops-config']) elements[name] = make();
  elements['incident-form'] = form;
  elements['ops-config'].textContent = '{"csrf":"test-token"}';
  const body = { dataset: { view } };
  const document = {
    body, documentElement: { lang: 'en' },visibilityState:'visible',
    addEventListener: (event,callback)=>listeners.set(event,callback),
    getElementById: id => elements[id], createElement: make,
  };
  const fetch = (url, options) => new Promise((resolve, reject) => {
    requests.push({ url, options, resolve, reject });
  });
  const context = {
    document, fetch, Intl, Date, JSON, Object, Promise,
    sessionStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    setTimeout: (callback, delay) => { const id = ++timerSequence; timers.set(id, { callback, delay }); return id; },
    clearTimeout: id => timers.delete(id),
    FormData: class { set() {} },
    Option: function (text, value) { this.text = text; this.value = value; },
    MutationObserver: class {
      constructor(callback) { observers.push(callback); }
      observe() {}
    },
  };
  vm.runInNewContext(source, context, { filename: 'incident-notices.js' });
  const good = label => ({
    redirected: false, ok: true,
    headers: { get: () => 'application/json' },
    json: async () => ({ bindings: { support: { label, queue: '8001' } }, notices: [] }),
  });
  return {
    requests, fields, elements, form, good, timers,
    tick() { const [id, timer] = timers.entries().next().value; timers.delete(id); timer.callback(); return timer.delay; },
    visibility(value){document.visibilityState=value;listeners.get('visibilitychange')?.();},
    move(next) { body.dataset.view = next; observers.forEach(callback => callback()); },
    observe() { observers.forEach(callback => callback()); },
  };
}

const flush = () => new Promise(resolve => setImmediate(resolve));
const submit = state => state.form.onsubmit({ preventDefault() {} });

async function run() {
  let state = setup();
  assert.equal(state.requests.length, 1, 'restored active view must load immediately');
  assert.equal(state.fields.title.disabled, true, 'form must await current registry');
  state.observe(); state.observe();
  assert.equal(state.requests.length, 1, 'same-view observer notifications must deduplicate');
  state.requests[0].resolve(state.good('Initial')); await flush();
  assert.equal(state.fields.title.disabled, false);

  state.elements['incident-refresh'].onclick();
  state.elements['incident-refresh'].onclick();
  assert.equal(state.requests.length, 3);
  assert.equal(state.fields.title.disabled, true, 'refresh must invalidate the old registry');
  state.requests[2].resolve(state.good('Latest')); await flush();
  state.fields.title.value = 'User draft';
  state.requests[1].reject(new Error('obsolete failure')); await flush();
  assert.equal(state.fields.title.value, 'User draft', 'old failure must preserve current edits');
  assert.equal(state.elements['incident-feedback'].textContent, '', 'old failure must stay hidden');

  state.elements['incident-refresh'].onclick();
  state.requests[3].reject(new Error('offline')); await flush();
  assert.equal(state.fields.title.disabled, true, 'failed registry must disable editing');
  assert.equal(state.fields.binding.children.length, 0, 'failed registry must clear stale bindings');
  const before = state.requests.length;
  await submit(state);
  assert.equal(state.requests.length, before, 'failed registry must prevent form submission');

  state.elements['incident-refresh'].onclick();
  state.move('live');
  state.requests[4].resolve(state.good('Obsolete after leave')); await flush();
  assert.equal(state.fields.title.disabled, true, 'response after leaving must not enable the form');
  state.move('telephony');
  assert.equal(state.requests.length, 6, 're-entry must fetch a fresh registry');
  state.observe();
  assert.equal(state.requests.length, 6, 're-entry must not start duplicate loads');
  state.requests[5].resolve(state.good('Re-entered')); await flush();
  assert.equal(state.fields.title.disabled, false);

  state = setup('live');
  assert.equal(state.requests.length, 0, 'hidden module must make no request');
  state.move('telephony');
  assert.equal(state.requests.length, 1);
  state.observe();
  assert.equal(state.requests.length, 1, 'visibility observation must not poll');
  state.requests[0].resolve(state.good('Ready')); await flush();

  // Leaving during an audio upload may store an unused sound, but must never
  // submit a configuration after the view and its registry have been invalidated.
  state.fields.audio_file.files = [{ size: 10 }];
  const saving = submit(state);
  assert.equal(state.requests.at(-1).url, '/api/pbx/incidents/audio');
  assert.equal(state.elements['incident-refresh'].disabled, true);
  state.move('live');
  state.requests.at(-1).resolve({
    redirected: false, ok: true, headers: { get: () => 'application/json' },
    json: async () => ({ id: 'a'.repeat(32), state: 'queued' }),
  });
  await saving; await flush();
  assert.equal(state.requests.length, 2, 'invalidated upload must not produce a configuration POST');
  assert.equal(state.fields.title.disabled, true);
  assert.equal(state.elements['incident-refresh'].disabled, false);

  state = setup();state.requests[0].resolve(state.good('Ready'));await flush();
  assert.equal(state.timers.size, 0, 'idle form must not poll');
  state.fields.title.value = 'Keep my incident draft';state.fields.audio_file.files = [{ size: 10 }];
  const queued = submit(state);
  state.requests[1].resolve({ redirected: false, ok: true, headers: { get: () => 'application/json' }, json: async () => ({ id: 'b'.repeat(32), state: 'queued' }) });
  await queued;await flush();
  assert.equal(state.requests.length, 2, 'upload queues conversion without publishing configuration');
  assert.equal(state.timers.size, 1);assert.equal(state.fields.title.disabled, false, 'draft remains editable');
  assert.equal(state.fields.binding.disabled, true, 'conversion remains bound to its original scope');
  state.visibility('hidden');assert.equal(state.timers.size,0,'background browser tab must stop polling');
  state.visibility('visible');assert.equal(state.timers.size,1,'visible pending job resumes status checks');
  assert.equal(state.tick(), 2000);await flush();
  state.requests[2].resolve({ redirected: false, ok: true, headers: { get: () => 'application/json' }, json: async () => ({ state: 'running' }) });
  await flush();assert.equal(state.timers.size, 1);
  state.fields.title.value = 'Updated while converting';state.move('live');
  assert.equal(state.timers.size, 0, 'leaving cancels pending poll timer');
  state.move('telephony');state.requests[3].resolve(state.good('Re-enter'));await flush();
  assert.equal(state.fields.title.value, 'Updated while converting', 're-entry preserves conversion draft');
  assert.equal(state.tick(), 4000, 'pending status uses backoff');await flush();
  state.requests[4].resolve({ redirected: false, ok: true, headers: { get: () => 'application/json' }, json: async () => ({ state: 'completed', audio: 'c'.repeat(64) }) });
  await flush();assert.equal(state.timers.size, 0, 'completed job stops polling');
  assert.equal(state.fields.title.value, 'Updated while converting', 'completion must not reset draft');
  assert.equal(state.elements['incident-audio'].src, '/api/pbx/incidents/audio/' + 'c'.repeat(64));
  assert.equal(state.requests.filter(r => r.url === '/api/pbx/incidents' && r.options.method === 'POST').length, 0, 'conversion completion requires explicit Save');

  console.log('PASS incident frontend: restore, deduplication, stale results, registry failure, submit guard, upload invalidation, visible-only conversion polling, backoff and draft preservation');
}

run().catch(error => { console.error(error); process.exitCode = 1; });
