// Run with: node --test web/tests/ticket_controller.test.cjs
// Execute the real controller and worker; replace only browser/platform boundaries.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const vm = require('node:vm');
const { webcrypto, createHash } = require('node:crypto');

const controller = readFileSync(resolve(__dirname, '../static/ticket.js'), 'utf8')
  .replace(/^import .*;\r?\n/gm, '');
const workerSource = readFileSync(resolve(__dirname, '../static/pow-worker.js'), 'utf8');
const reply = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const flush = () => new Promise(resolve => setImmediate(resolve));
async function until(predicate) {
  for (let i = 0; i < 200; i++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  assert.fail('Controller did not reach the expected state');
}

function harness({ reduced = false, tester = false, manualWorker = false, route } = {}) {
  const nodes = new Map(), requests = [], workers = [], comets = [];
  const document = {
    activeElement: null,
    getElementById(id) {
      if (!nodes.has(id)) {
        const listeners = {};
        nodes.set(id, {
          hidden: ['retry', 'tester', 'confirm', 'reuse'].includes(id),
          disabled: id === 'reserve', checked: false, style: {}, textContent: '',
          classList: { toggle() {} }, setAttribute() {},
          addEventListener(type, handler) { listeners[type] = handler; },
          fire(type) { return (listeners[type] || this[`on${type}`])?.({ preventDefault() {} }); },
          focus() { document.activeElement = this; },
          querySelector() { return this.device ? { value: this.device } : null; },
        });
      }
      return nodes.get(id);
    },
  };
  class Worker {
    constructor(url) {
      assert.equal(url, '/static/pow-worker.js');
      workers.push(this);
      this.messages = [];
      this.stopped = false;
      const self = { postMessage: data => { if (!this.stopped) this.onmessage?.({ data }); } };
      vm.runInNewContext(workerSource, { self, TextEncoder, Uint8Array, crypto: webcrypto });
      this.run = self.onmessage;
    }
    postMessage(data) {
      this.messages.push(data);
      if (!manualWorker) this.run({ data }).catch(error => this.onerror?.(error));
    }
    terminate() { this.stopped = true; }
  }
  vm.runInNewContext(controller, {
    window: { matchMedia: () => ({ matches: reduced }) }, document, Worker,
    location: { search: tester ? '?tester=1' : '' }, URLSearchParams,
    crypto: webcrypto, Uint8Array, AbortController, DOMException,
    sessionStorage: { getItem: () => null, setItem() {} },
    makePath: () => () => [100, 100], drawStill() {},
    runComet: (_canvas, _seed, { signal, pathVersion }) => new Promise((resolve, reject) => {
      comets.push({ resolve, signal, pathVersion });
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }),
    fetch: async (path, options) => {
      const body = JSON.parse(options.body);
      requests.push({ path, body });
      const custom = await route?.(path, body, requests);
      if (custom) return custom;
      if (path === '/v1/challenges') return reply({ challenge_id: 'challenge-1', seed: 42 });
      if (path.endsWith('/attempt')) return reply({ result: { score: 0 }, token: null });
      if (path === '/v1/pow') return reply({ pow_id: 'puzzle', nonce: 'test-nonce', bits: 8 });
      if (path.endsWith('/solve')) return reply({ token: 'valid-token' });
      throw new Error(`Unexpected request: ${path}`);
    },
  });
  return { el: id => document.getElementById(id), requests, workers, comets, document };
}

for (const entry of ['skip', 'reduced motion', 'scoring failure']) {
  test(`${entry} dispatches and completes real PoW before enabling reserve`, async () => {
    const h = harness({ reduced: entry === 'reduced motion' });
    if (entry !== 'reduced motion') {
      await until(() => h.comets.length === 1);
      if (entry === 'skip') h.el('skip').fire('click');
      else h.comets[0].resolve({ samples: [[0, 1, 2], [1500, 3, 4]], pointerType: 'mouse' });
    }
    await until(() => !h.el('reserve').disabled);
    const worker = h.workers[0];
    assert.equal(worker.messages.length, 1);
    assert.equal(worker.messages[0].nonce, 'test-nonce');
    assert.equal(worker.messages[0].bits, 8);
    assert.equal(worker.stopped, true);
    const solve = h.requests.find(r => r.path.endsWith('/solve'));
    assert.equal(createHash('sha256').update(`test-nonce:${solve.body.counter}`).digest()[0], 0);
    if (entry === 'skip') assert.equal(h.comets[0].signal.aborted, true);
    if (entry === 'reduced motion') assert.equal(h.comets.length, 0);
  });
}

test('restarting a solve terminates old worker and ignores its late result', async () => {
  const h = harness({ reduced: true, manualWorker: true });
  await until(() => h.workers.length === 1);
  const staleHandler = h.workers[0].onmessage;
  h.el('skip').fire('click');
  await until(() => h.workers.length === 2);
  assert.equal(h.workers[0].stopped, true);
  staleHandler({ data: { counter: 10 } });
  await flush();
  assert.equal(h.requests.filter(r => r.path.endsWith('/solve')).length, 0);
  h.workers[1].onmessage({ data: { counter: 20 } });
  await until(() => !h.el('reserve').disabled);
  assert.equal(h.requests.filter(r => r.path.endsWith('/solve')).length, 1);
});

test('worker failure exposes a retry that starts a fresh worker', async () => {
  const h = harness({ reduced: true, manualWorker: true });
  await until(() => h.workers.length === 1);
  h.workers[0].onerror(new Error('worker failed'));
  await until(() => !h.el('retry').hidden);
  assert.equal(h.workers[0].stopped, true);
  assert.equal(h.el('reserve').disabled, true);
  h.el('retry').fire('click');
  await until(() => h.workers.length === 2);
  h.workers[1].onmessage({ data: { counter: 1 } });
  await until(() => !h.el('reserve').disabled);
});

test('expired puzzle retries once with a fresh puzzle and worker', async () => {
  let puzzles = 0;
  const h = harness({ reduced: true, route: path => {
    if (path === '/v1/pow') return reply({ pow_id: `puzzle-${++puzzles}`, nonce: 'retry', bits: 0 });
    if (path === '/v1/pow/puzzle-1/solve') return reply({}, 400);
  } });
  await until(() => !h.el('reserve').disabled);
  assert.equal(puzzles, 2);
  assert.equal(h.workers.length, 2);
  assert.ok(h.workers.every(w => w.stopped));
});

test('consent withdrawal during challenge fetch prevents recording; repeated changes do not double-fetch', async () => {
  let finishFetch;
  const h = harness({ tester: true, route: path => {
    if (path === '/v1/challenges') return new Promise(resolve => { finishFetch = resolve; });
  } });
  assert.equal(h.requests.length, 0);
  h.el('consent').checked = true;
  h.el('tester').device = 'mouse';
  h.el('tester').fire('change');
  h.el('nondominant').checked = true;
  h.el('tester').fire('change');
  assert.equal(h.requests.length, 1);
  h.el('consent').checked = false;
  h.el('tester').fire('change');
  finishFetch(reply({ challenge_id: 'stale', seed: 42 }));
  await flush();
  assert.equal(h.comets.length, 0);
  assert.equal(h.requests.some(r => r.path.endsWith('/attempt')), false);
});

test('consent withdrawal during movement aborts collection and never submits it', async () => {
  const h = harness({ tester: true });
  h.el('consent').checked = true;
  h.el('tester').device = 'mouse';
  h.el('tester').fire('change');
  await until(() => h.comets.length === 1);
  h.el('consent').checked = false;
  h.el('tester').fire('change');
  await flush();
  assert.equal(h.comets[0].signal.aborted, true);
  assert.equal(h.requests.some(r => r.path.endsWith('/attempt')), false);
});

test('playing again clears the earlier pass until the new challenge succeeds', async () => {
  const h = harness({ tester: true, route: path => {
    if (path.endsWith('/attempt')) return reply({ result: { score: 1 }, token: 'old-pass' });
  } });
  h.el('consent').checked = true;
  h.el('tester').device = 'mouse';
  h.el('tester').fire('change');
  await until(() => h.comets.length === 1);
  h.comets[0].resolve({ samples: [[0, 1, 2], [1500, 3, 4]], pointerType: 'mouse' });
  await until(() => !h.el('reserve').disabled);
  h.el('retry').fire('click');
  assert.equal(h.el('reserve').disabled, true);
  h.el('reserve').fire('click');
  await until(() => h.comets.length === 2);
  assert.equal(h.requests.some(r => r.path === '/demo/tickets/reserve'), false);
  h.el('consent').checked = false;
  h.el('tester').fire('change');
  await flush();
});

test('tester follows the issued path version and sees real feature measurements', async () => {
  const h = harness({ tester: true, route: path => {
    if (path === '/v1/challenges') return reply({ challenge_id: 'smooth-challenge', seed: 42, path_version: 'smooth_v2' });
    if (path.endsWith('/attempt')) return reply({ result: { score: .75, features: {
      lag_ms: { value: 200, enabled: true, ok: true },
      power_law_beta: { value: .33, enabled: false, ok: true },
    } }, token: 'pass' });
  } });
  h.el('consent').checked = true;
  h.el('tester').device = 'touch';
  h.el('tester').fire('change');
  await until(() => h.comets.length === 1);
  assert.equal(h.comets[0].pathVersion, 'smooth_v2');
  h.comets[0].resolve({ samples: [[0, 1, 2], [1500, 3, 4]], pointerType: 'touch' });
  await until(() => !h.el('reserve').disabled);
  assert.match(h.el('result').innerHTML, /Reaction delay/);
  assert.match(h.el('result').innerHTML, /200.00 ms/);
  assert.match(h.el('result').innerHTML, /Measured only/);
  assert.match(h.el('result').innerHTML, /provisional/);
});
