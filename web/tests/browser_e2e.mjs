#!/usr/bin/env node
// Real-browser end-to-end tests for the ticket page.
//
//   node web/tests/browser_e2e.mjs [baseUrl]        (default http://localhost:8801)
//
// Drives a throwaway headless Chrome over the DevTools Protocol and synthesizes REAL
// pointer input (Input.dispatchMouseEvent / Input.dispatchTouchEvent), so the browser's
// own pointer pipeline runs: coalesced events, pointer capture, touch-action.
//
// Checks 1-8 are described in the PASS/FAIL output. Exits nonzero on any failure.
// Needs the app running with POW_BITS low enough to solve quickly (12 is plenty).

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';

const BASE = (process.argv[2] || 'http://localhost:8801').replace(/\/$/, '');
const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9222 + Math.floor(Math.random() * 900);
const DURATION_MS = 5000;
const W = 600, H = 400;

export const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------------------------------------------------------------- reporting

const results = [];
const jsErrors = [];   // every uncaught error / unhandled rejection / console.error

function record(n, title, ok, detail) {
  results.push({ n, title, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  check ${n}  ${title}${detail ? `\n        ${detail}` : ''}`);
}

export class Fail extends Error {}
export function assert(cond, msg) { if (!cond) throw new Fail(msg); }
function near(a, b, tol, what) {
  assert(Math.abs(a - b) <= tol, `${what}: ${a} not within ${tol} of ${b}`);
}

async function check(n, title, fn) {
  try {
    const detail = await fn();
    record(n, title, true, detail);
  } catch (e) {
    record(n, title, false, e instanceof Fail ? e.message : `${e.stack || e}`);
  }
}

// ---------------------------------------------------------------- CDP plumbing

export class Conn {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.handlers = new Map();
    ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data);
      if (m.id !== undefined) {
        const p = this.pending.get(m.id);
        if (!p) return;
        this.pending.delete(m.id);
        m.error ? p.reject(new Error(`${p.method}: ${m.error.message}`)) : p.resolve(m.result);
      } else {
        for (const cb of this.handlers.get(m.method) || []) cb(m.params);
      }
    });
  }
  static async open(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', () => rej(new Error(`cannot connect to ${url}`)), { once: true });
    });
    return new Conn(ws);
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) =>
      this.pending.set(id, { resolve, reject, method }));
  }
  on(event, cb) {
    if (!this.handlers.has(event)) this.handlers.set(event, []);
    this.handlers.get(event).push(cb);
  }
  close() { try { this.ws.close(); } catch { /* ignore */ } }
}

async function httpJson(url) {
  const r = await fetch(url);
  return r.json();
}

export class Browser {
  static async launch() {
    const dir = mkdtempSync(join(tmpdir(), 'followit-e2e-'));
    const proc = spawn(CHROME, [
      '--headless=new',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${dir}`,
      '--no-first-run', '--no-default-browser-check',
      '--disable-background-networking', '--disable-sync',
      '--disable-extensions', '--disable-features=Translate',
      '--window-size=1280,900',
      '--ignore-certificate-errors',
      'about:blank',
    ], { stdio: 'ignore' });
    let version = null;
    for (let i = 0; i < 100 && !version; i++) {
      try { version = await httpJson(`http://127.0.0.1:${PORT}/json/version`); }
      catch { await sleep(100); }
    }
    if (!version) { proc.kill('SIGKILL'); rmSync(dir, { recursive: true, force: true }); throw new Error('Chrome did not start'); }
    const b = new Browser();
    b.proc = proc; b.dir = dir;
    b.conn = await Conn.open(version.webSocketDebuggerUrl);
    return b;
  }
  async newPage(label) {
    const { targetId } = await this.conn.send('Target.createTarget', { url: 'about:blank' });
    const list = await httpJson(`http://127.0.0.1:${PORT}/json/list`);
    const t = list.find(x => x.id === targetId);
    const page = new Page(await Conn.open(t.webSocketDebuggerUrl), label, this, targetId);
    await page.init();
    return page;
  }
  async close() {
    // Let Chrome stop its child processes before deleting its isolated profile.
    // Killing only the parent leaves Windows file handles open briefly.
    try { await this.conn.send('Browser.close'); } catch { /* already closed */ }
    this.conn.close();
    if (this.proc.exitCode === null) {
      await Promise.race([new Promise(r => this.proc.once('exit', r)), sleep(3000)]);
      if (this.proc.exitCode === null) this.proc.kill('SIGKILL');
    }
    const profile = resolve(this.dir);
    assert(profile.startsWith(resolve(tmpdir()) + sep + 'followit-e2e-'), 'refusing cleanup outside test profiles');
    rmSync(profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
  }
}

export class Page {
  constructor(conn, label, browser, targetId) {
    this.c = conn; this.label = label; this.browser = browser; this.targetId = targetId;
    this.requests = [];   // {url, method, postData, status}
  }
  async init() {
    const c = this.c;
    c.on('Runtime.exceptionThrown', p => jsErrors.push(
      `[${this.label}] uncaught: ${p.exceptionDetails?.exception?.description
        || p.exceptionDetails?.text || JSON.stringify(p.exceptionDetails)}`));
    c.on('Runtime.consoleAPICalled', p => {
      if (p.type === 'error' || p.type === 'assert') {
        jsErrors.push(`[${this.label}] console.${p.type}: ${p.args.map(a => a.description || a.value).join(' ')}`);
      }
    });
    c.on('Log.entryAdded', p => {
      const e = p.entry;
      // Favicon 404s on about:blank-ish navigations are noise, not app errors.
      // Browser-level HTTP status noise for API calls the app handles on purpose
      // (a 422 on a short trail, a 409 on a reused pass) is not a JS error.
      const handledApi = e.source === 'network' && /\/v1\/|\/demo\//.test(e.url || '');
      if (e.level === 'error' && !handledApi && !/favicon/.test(e.url || '')) {
        jsErrors.push(`[${this.label}] log(${e.source}): ${e.text} ${e.url || ''}`);
      }
    });
    c.on('Network.requestWillBeSent', p => {
      this.requests.push({ id: p.requestId, url: p.request.url, method: p.request.method, postData: p.request.postData });
    });
    c.on('Network.responseReceived', p => {
      const r = this.requests.find(x => x.id === p.requestId);
      if (r) r.status = p.response.status;
    });
    await c.send('Page.enable');
    await c.send('Runtime.enable');
    await c.send('Log.enable');
    await c.send('Network.enable', { maxPostDataSize: 10_000_000 });
    await c.send('Network.setCacheDisabled', { cacheDisabled: true });
  }
  req(match) { return this.requests.filter(r => r.url.includes(match)); }
  lastReq(match) { return this.req(match).at(-1); }

  async phone({ mobile = false, dsf = 3, width = 390, height = 844 } = {}) {
    await this.c.send('Emulation.setDeviceMetricsOverride',
      { width, height, deviceScaleFactor: dsf, mobile });
    if (mobile) await this.c.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  }
  async reduceMotion() {
    await this.c.send('Emulation.setEmulatedMedia',
      { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  }
  async goto(path = '/') {
    const done = new Promise(r => {
      const h = () => r();
      this.c.on('Page.loadEventFired', h);
    });
    await this.c.send('Page.navigate', { url: BASE + path });
    await Promise.race([done, sleep(20000)]);
  }
  async eval(expression) {
    const r = await this.c.send('Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) {
      throw new Error(`eval failed: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    }
    return r.result.value;
  }
  async waitFor(expression, timeout = 10000, what = expression) {
    const t = Date.now();
    for (;;) {
      if (await this.eval(`!!(${expression})`)) return;
      if (Date.now() - t > timeout) throw new Fail(`timed out waiting for ${what}`);
      await sleep(60);
    }
  }
  async text(id) { return this.eval(`document.getElementById(${JSON.stringify(id)}).textContent.trim()`); }
  async hidden(id) { return this.eval(`document.getElementById(${JSON.stringify(id)}).hidden`); }
  // Scrolls the element into view first: CDP input coordinates are viewport-relative,
  // so anything below the fold would otherwise be clicked in empty space.
  async rect(sel) {
    const r = await this.eval(
      `(()=>{const e=document.querySelector(${JSON.stringify(sel)});
        e.scrollIntoView({block:'center',behavior:'instant'});
        const r=e.getBoundingClientRect();
        return {x:r.left,y:r.top,w:r.width,h:r.height}})()`);
    assert(r && r.w > 0, `${sel} has no layout`);
    return r;
  }
  async responseBody(id) {
    const r = await this.c.send('Network.getResponseBody', { requestId: id });
    return r.base64Encoded ? Buffer.from(r.body, 'base64').toString('utf8') : r.body;
  }
  async postBody(r) {
    if (r.postData) return r.postData;
    const got = await this.c.send('Network.getRequestPostData', { requestId: r.id });
    return got.postData;
  }
  async clickId(id) {
    const r = await this.rect(`#${id}`);
    const x = r.x + r.w / 2, y = r.y + r.h / 2;
    await this.c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none', buttons: 0, pointerType: 'mouse' });
    await this.c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1, pointerType: 'mouse' });
    await this.c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1, pointerType: 'mouse' });
  }
  async close() {
    this.c.close();
    try { await this.browser.conn.send('Target.closeTarget', { targetId: this.targetId }); } catch { /* ignore */ }
  }
}

// ---------------------------------------------------------------- the comet

// Dense table of comet positions from the page's own makePath, so the test follows
// exactly the path the page drew.
export async function pathTable(page, seed, pathVersion = 'v1') {
  return page.eval(`(()=>{const p=window.makePath(${seed}>>>0,${JSON.stringify(pathVersion)});const a=[];
    for(let t=0;t<=${DURATION_MS + 400};t+=4)a.push(p(t));return a})()`);
}
function posAt(tbl, t) {
  const i = Math.max(0, Math.min(tbl.length - 1, Math.round(t / 4)));
  return tbl[i];
}

// The server pins the path version per challenge (config.PATH_VERSION, currently roaming_v3)
// and scores against it, so the test must follow THAT curve. Reading it from the challenge
// response rather than hardcoding keeps this suite correct across future path versions --
// following the wrong curve inflates err_mean_px and fails the attempt for the wrong reason.
async function challengeOf(page) {
  const r = page.lastReq('/v1/challenges');
  assert(r, 'no POST /v1/challenges was made');
  const body = JSON.parse(await page.responseBody(r.id));
  assert(Number.isFinite(body.seed), `challenge response had no seed: ${JSON.stringify(body)}`);
  return { seed: body.seed, pathVersion: body.path_version || 'v1' };
}

// Open the page and wait until runComet is listening for input.
export async function openGame(page, { touch = false, viewport = null } = {}) {
  if (viewport) await page.phone(viewport);
  await page.goto('/');
  await page.waitFor(`document.getElementById('overlay').textContent.includes('inside the ring')`,
    15000, 'the comet to be ready for input');
  const { seed, pathVersion } = await challengeOf(page);
  const tbl = await pathTable(page, seed, pathVersion);
  const rect = await page.rect('#comet');
  // logical canvas px -> viewport CSS px
  const toCss = ([lx, ly]) => [rect.x + lx * rect.w / W, rect.y + ly * rect.h / H];
  return { seed, pathVersion, tbl, rect, toCss, touch };
}

// Synthetic input for checking browser/scorer integration, never human evidence.
// The heuristic rejects zero lag and zero jitter, so this fixture adds:
// ~200 ms behind, with a small tremor and corrective sub-movements. These numbers were
// calibrated against engine/scorer.py and variant v1's bands (lag 120-450 ms,
// err 8-90 px, submoves 1.5-6 /s, jitter 0.8-6 px) and pass on every seed tried.
const HAND = { lagMs: 200, wobbleAmp: 7, wobbleHz: 2.8, tremorPx: 2.0 };

function gauss(rand) {
  const u = Math.max(rand(), 1e-12);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
}

// Where a human hand would be at challenge time t, in logical canvas px.
function handAt(tbl, t, rand, human) {
  const [px, py] = posAt(tbl, human ? Math.max(0, t - HAND.lagMs) : t);
  if (!human) return [px, py];
  const ph = 2 * Math.PI * HAND.wobbleHz * t / 1000;
  return [
    px + HAND.wobbleAmp * Math.sin(ph) + HAND.tremorPx * gauss(rand),
    py + HAND.wobbleAmp * Math.sin(ph + 1.3) + HAND.tremorPx * gauss(rand),
  ];
}

// Follow the comet with real pointer input for `ms`, then (optionally) lift.
// `off: [from, to]` drags the pointer well outside the canvas for that window, the way a
// real hand overshoots; pointer capture keeps the events coming.
// Returns the exact positions commanded, so a caller can check what the page recorded
// against what the pointer actually did, independent of the hand model.
export async function follow(page, g, { ms = DURATION_MS + 120, lift = true, step = 16, off = null, human = true } = {}) {
  const { tbl, toCss, touch, rect } = g;
  let seedState = 0x2f6e2b1 ^ (g.seed | 0);
  const rand = () => (((seedState = (Math.imul(seedState, 1103515245) + 12345) >>> 0)) / 4294967296);
  const commanded = [];
  const down = async ([x, y]) => touch
    ? page.c.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 1 }] })
    : page.c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1, pointerType: 'mouse' });
  // Fire-and-forget so the 16 ms cadence is not eaten by the CDP round trip; writes on
  // one socket stay ordered, so the browser still sees a monotonic pointer stream.
  const move = ([x, y]) => (touch
    ? page.c.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y, id: 1 }] })
    : page.c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'left', buttons: 1, pointerType: 'mouse' })
  ).catch(() => {});
  const up = async ([x, y]) => touch
    ? page.c.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    : page.c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1, pointerType: 'mouse' });

  // Land on the comet's start point to arm the challenge; t0 is set the moment it lands.
  const start = toCss(posAt(tbl, 0));
  const before = Date.now();
  await down(start);
  const t0 = (before + Date.now()) / 2;
  await page.waitFor(`document.getElementById('overlay').textContent === ''`, 3000,
    'the challenge to start (overlay clears)');

  commanded.push([0, ...posAt(tbl, 0)]);
  let i = 0, last = start;
  for (;;) {
    const t = Date.now() - t0;
    if (t > ms) break;
    const outside = off && t >= off[0] && t <= off[1];
    if (outside) {
      last = [Math.max(1, rect.x - 140), Math.max(1, rect.y - 70)];
      // what the page should record for an off-canvas point, after clamping
      commanded.push([t, Math.min(Math.max((last[0] - rect.x) * W / rect.w, 0), W),
        Math.min(Math.max((last[1] - rect.y) * H / rect.h, 0), H)]);
    } else {
      const p = handAt(tbl, t, rand, human);
      commanded.push([t, ...p]);
      last = toCss(p);
    }
    move(last);
    const d = t0 + ++i * step - Date.now();
    if (d > 1) await sleep(d);
  }
  if (lift) await up(last);
  return { t0, steps: i, last, commanded };
}

// Linear interpolation of the commanded path at challenge time t.
function cmdAt(cmd, t) {
  if (t <= cmd[0][0]) return [cmd[0][1], cmd[0][2]];
  for (let i = 1; i < cmd.length; i++) {
    if (cmd[i][0] >= t) {
      const [t0, x0, y0] = cmd[i - 1], [t1, x1, y1] = cmd[i];
      const k = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
      return [x0 + (x1 - x0) * k, y0 + (y1 - y0) * k];
    }
  }
  return [cmd.at(-1)[1], cmd.at(-1)[2]];
}

// After following, wait for the attempt POST to come back and return it.
export async function attemptResult(page) {
  const t = Date.now();
  for (;;) {
    const r = page.lastReq('/attempt');
    if (r && r.status) {
      return { status: r.status, trail: JSON.parse(await page.postBody(r)), body: r.status === 200 ? JSON.parse(await page.responseBody(r.id)) : null };
    }
    if (Date.now() - t > 15000) throw new Fail('attempt POST never completed');
    await sleep(80);
  }
}

// `meanErr` is the page's recorded trail against the positions the pointer was actually
// driven to: it should be ~0 whatever the hand model does, so it is a tight test of the
// CSS px -> logical px conversion. `cometErr` is the human-like tracking error, which the
// scorer wants between 8 and 90 px.
export function trailStats(trail, tbl, run) {
  const s = trail.samples;
  assert(Array.isArray(s) && s.length > 30, `expected a dense trail, got ${s?.length} samples`);
  let maxX = -Infinity, minX = Infinity, maxY = -Infinity, minY = Infinity, errSum = 0, cometSum = 0;
  for (const [t, x, y] of s) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    const [cx, cy] = run ? cmdAt(run.commanded, t) : posAt(tbl, t);
    errSum += Math.hypot(x - cx, y - cy);
    const [px, py] = posAt(tbl, t);
    cometSum += Math.hypot(x - px, y - py);
  }
  return {
    n: s.length, minX, maxX, minY, maxY, first: s[0][0], last: s.at(-1)[0],
    meanErr: errSum / s.length, cometErr: cometSum / s.length,
  };
}

function spanOf(points) {
  const xs = points.map(p => p[1]), ys = points.map(p => p[2]);
  return [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
}

function assertLogicalPx(st, run) {
  assert(st.minX >= 0 && st.maxX <= W, `x out of logical range [0,${W}]: [${st.minX.toFixed(1)}, ${st.maxX.toFixed(1)}]`);
  assert(st.minY >= 0 && st.maxY <= H, `y out of logical range [0,${H}]: [${st.minY.toFixed(1)}, ${st.maxY.toFixed(1)}]`);
  // A CSS-px leak squashes the trail by rect.width/600 (0.52x on a phone). Two guards,
  // and the first is the real one:
  //
  //  1. st.meanErr -- per-sample distance from where the pointer was actually driven,
  //     matched on timestamp. A scale leak makes this hundreds of px; it reads ~0.1 px.
  //     Asserted by the caller.
  //  2. The span ratio below. This one only bounds a GROSS squash, because synthesized
  //     pointer events are coalesced and occasionally dropped when the main thread is
  //     busy drawing, which clips the extremes of the sweep. A 0.9 floor made the check
  //     flake at 79-84% on main and on PR #5 alike -- a harness artifact, not a app
  //     regression. Keep it loose; guard #1 is what actually detects a leak.
  const [sx, sy] = spanOf(run.commanded);
  const gx = (st.maxX - st.minX) / sx, gy = (st.maxY - st.minY) / sy;
  assert(gx > 0.6 && gx < 1.1, `x span is ${(gx * 100).toFixed(0)}% of what the pointer covered - samples look scaled, not logical`);
  assert(gy > 0.6 && gy < 1.1, `y span is ${(gy * 100).toFixed(0)}% of what the pointer covered - samples look scaled, not logical`);
}

// ---------------------------------------------------------------- the checks

async function main() {
const browser = await Browser.launch();
let c1 = null, c1trail = null;

try {
  // 1 ---------------------------------------------------------------------
  await check(1, 'mouse, desktop: follow the comet -> 200, pass, token, Reserve enabled', async () => {
    const page = await browser.newPage('c1-desktop-mouse');
    c1 = page;
    const g = await openGame(page);
    const run = await follow(page, g);
    const a = await attemptResult(page);
    assert(a.status === 200, `attempt POST returned ${a.status}`);
    assert(a.body.result?.pass === true, `result.pass was ${JSON.stringify(a.body.result?.pass)}`);
    assert(typeof a.body.token === 'string' && a.body.token.startsWith('tok_'),
      `no token: ${JSON.stringify(a.body.token)}`);
    await page.waitFor(`!document.getElementById('reserve').disabled`, 5000, 'Reserve to become enabled');
    c1trail = { trail: a.trail, tbl: g.tbl, run };
    const st = trailStats(a.trail, g.tbl, run);
    const f = a.body.result.features || {};
    const band = k => f[k] ? `${k} ${f[k].value.toFixed(1)}${f[k].ok ? '' : ' OUT OF BAND'}` : k;
    return `seed ${g.seed}, ${st.n} samples, score ${a.body.result.score}, token ok, status: "${await page.text('status')}"`
      + `\n        ${['lag_ms', 'err_mean_px', 'submoves_per_s', 'jitter_px'].map(band).join(', ')}`;
  });

  // 2 ---------------------------------------------------------------------
  await check(2, 'samples are logical 600x400 px - desktop AND on a CSS-scaled phone canvas', async () => {
    assert(c1trail, 'check 1 did not produce a trail to inspect');
    const d = trailStats(c1trail.trail, c1trail.tbl, c1trail.run);
    assertLogicalPx(d, c1trail.run);
    near(d.first, 0, 60, 'desktop first t_ms');
    near(d.last, DURATION_MS, 120, 'desktop last t_ms');
    assert(d.meanErr < 10, `desktop samples differ from the commanded path by ${d.meanErr.toFixed(1)}px`);
    assert(d.cometErr < 90, `desktop tracking error ${d.cometErr.toFixed(1)}px is not human-like`);

    // Now the one that actually matters: the canvas is ~314 CSS px wide here, so any
    // missing CSS->logical conversion shows up immediately.
    const page = await browser.newPage('c2-phone-mouse');
    try {
      const g = await openGame(page, { viewport: { width: 390, height: 844, dsf: 3, mobile: false } });
      assert(g.rect.w < 420 && g.rect.w > 100, `expected a scaled canvas, CSS width was ${g.rect.w}`);
      const run = await follow(page, g);
      const a = await attemptResult(page);
      assert(a.status === 200, `phone attempt POST returned ${a.status}`);
      const p = trailStats(a.trail, g.tbl, run);
      assertLogicalPx(p, run);
      near(p.first, 0, 60, 'phone first t_ms');
      near(p.last, DURATION_MS, 120, 'phone last t_ms');
      assert(p.meanErr < 10, `phone samples differ from the commanded path by ${p.meanErr.toFixed(1)}px`);
      assert(p.cometErr < 90, `phone tracking error ${p.cometErr.toFixed(1)}px is not human-like`);

      // Adversarial: pointer capture keeps the stream alive when a finger slides past the
      // edge of the canvas, so the conversion must still yield in-canvas logical px.
      const over = await browser.newPage('c2-overshoot');
      let ov;
      try {
        const g2 = await openGame(over, { viewport: { width: 390, height: 844, dsf: 3, mobile: false } });
        const run2 = await follow(over, g2, { off: [1000, 1600] });
        const a2 = await attemptResult(over);
        assert(a2.status === 200, `overshoot attempt returned ${a2.status}`);
        ov = trailStats(a2.trail, g2.tbl, run2);
        assert(ov.minX >= 0 && ov.maxX <= W && ov.minY >= 0 && ov.maxY <= H,
          `overshooting the canvas edge leaked out-of-range samples: x[${ov.minX.toFixed(1)},${ov.maxX.toFixed(1)}] y[${ov.minY.toFixed(1)},${ov.maxY.toFixed(1)}]`);
      } finally { await over.close(); }

      return `desktop: canvas ${c1trail.trail.samples.length} samples, x[${d.minX.toFixed(0)},${d.maxX.toFixed(0)}] y[${d.minY.toFixed(0)},${d.maxY.toFixed(0)}] t[${d.first},${d.last}] off commanded path by ${d.meanErr.toFixed(2)}px (comet err ${d.cometErr.toFixed(1)}px)`
        + `\n        phone (canvas ${g.rect.w.toFixed(0)} CSS px, dpr 3): x[${p.minX.toFixed(0)},${p.maxX.toFixed(0)}] y[${p.minY.toFixed(0)},${p.maxY.toFixed(0)}] t[${p.first},${p.last}] off commanded path by ${p.meanErr.toFixed(2)}px (comet err ${p.cometErr.toFixed(1)}px)`
        + `\n        phone + overshoot past the canvas edge: x[${ov.minX.toFixed(1)},${ov.maxX.toFixed(1)}] y[${ov.minY.toFixed(1)},${ov.maxY.toFixed(1)}] still inside 600x400`;
    } finally { await page.close(); }
  });

  // 3 ---------------------------------------------------------------------
  await check(3, 'touch, 390x844: follow with real touch events, no page scroll, capture held', async () => {
    const page = await browser.newPage('c3-phone-touch');
    try {
      const g = await openGame(page, { touch: true, viewport: { width: 390, height: 844, dsf: 3, mobile: true } });
      // Watch pointer capture and any scrolling for real.
      await page.eval(`(()=>{const c=document.getElementById('comet');window.__pc=[];
        c.addEventListener('gotpointercapture',e=>window.__pc.push(['got',e.pointerId]));
        c.addEventListener('lostpointercapture',e=>window.__pc.push(['lost',e.pointerId]));
        window.__y0=window.scrollY;window.__drift=0;
        addEventListener('scroll',()=>{window.__drift=Math.max(window.__drift,Math.abs(scrollY-window.__y0))},{passive:true});
        return true})()`);
      const scrollable = await page.eval('document.documentElement.scrollHeight - innerHeight');
      const y0 = await page.eval('window.scrollY');
      const run = await follow(page, g);
      const a = await attemptResult(page);
      const y1 = await page.eval('window.scrollY');
      const maxScroll = await page.eval('window.__drift');
      const pc = await page.eval('JSON.stringify(window.__pc)');
      assert(a.status === 200, `touch attempt POST returned ${a.status}`);
      assert(a.trail.pointer_type === 'touch', `pointer_type was "${a.trail.pointer_type}", expected "touch"`);
      assert(a.trail.device === 'touch', `device was "${a.trail.device}", expected "touch"`);
      const st = trailStats(a.trail, g.tbl, run);
      assertLogicalPx(st, run);
      assert(st.meanErr < 10, `touch samples differ from the commanded path by ${st.meanErr.toFixed(1)}px`);
      assert(scrollable > 100, `page was not scrollable (${scrollable}px), the no-scroll check is meaningless`);
      assert(y1 === y0 && maxScroll === 0, `page scrolled during tracking: ${y0} -> ${y1} (drift ${maxScroll})`);
      assert(/"got"/.test(pc), `canvas never got pointer capture: ${pc}`);
      assert(a.body.result?.pass === true, 'touch attempt did not pass');
      return `${st.n} samples, off commanded path by ${st.meanErr.toFixed(2)}px (comet err ${st.cometErr.toFixed(1)}px), scrollY ${y0}->${y1} of ${scrollable}px scrollable, capture ${pc}`;
    } finally { await page.close(); }
  });

  // 4 ---------------------------------------------------------------------
  await check(4, 'reserve -> 200 with a reservation id; same pass again -> 409 + friendly message', async () => {
    assert(c1, 'check 1 left no page to reserve from');
    const page = c1;
    await page.clickId('reserve');
    await page.waitFor(`!document.getElementById('confirm').hidden`, 10000, 'the confirmation card');
    const rid = await page.text('rid');
    const res1 = page.lastReq('/demo/tickets/reserve');
    assert(res1.status === 200, `first reserve returned ${res1.status}`);
    assert(/^res_|\w{6,}/.test(rid), `reservation id not shown (got "${rid}")`);
    assert(!(await page.hidden('reuse')), 'the "try the same pass again" link was not offered');

    await page.clickId('reuse');
    await page.waitFor(`!document.getElementById('reserve-msg').hidden`, 10000, 'the reuse error message');
    const reqs = page.req('/demo/tickets/reserve');
    assert(reqs.length === 2, `expected 2 reserve calls, saw ${reqs.length}`);
    assert(reqs[1].status === 409, `reuse returned ${reqs[1].status}, expected 409`);
    const msg = await page.text('reserve-msg');
    assert(/already been used/i.test(msg), `unfriendly reuse message: "${msg}"`);
    assert(!(await page.hidden('verify-again')), 'no "Verify again" offered after the reuse 409');
    return `reservation ${rid} (200), reuse -> 409 "${msg}"`;
  });

  // 5 ---------------------------------------------------------------------
  await check(5, 'Skip -> proof of work -> Reserve (POW_BITS low), status line updates', async () => {
    const page = await browser.newPage('c5-pow');
    try {
      await page.goto('/');
      await page.waitFor(`document.getElementById('overlay').textContent.includes('inside the ring')`,
        15000, 'the game to load');
      await page.clickId('skip');
      await page.waitFor(`document.getElementById('status').textContent.includes('Checking your browser')`,
        5000, 'the "checking your browser" status');
      const checking = await page.text('status');
      await page.waitFor(`!document.getElementById('reserve').disabled`, 40000, 'PoW to finish and enable Reserve');
      const done = await page.text('status');
      const solve = page.lastReq('/v1/pow/');
      assert(solve && solve.status === 200, `PoW solve returned ${solve?.status}`);
      const tok = JSON.parse(await page.responseBody(solve.id));
      assert(typeof tok.token === 'string' && tok.token.length > 4, 'PoW issued no token');
      assert(done !== checking, 'the status line never updated after the PoW finished');
      await page.clickId('reserve');
      await page.waitFor(`!document.getElementById('confirm').hidden`, 10000, 'the confirmation card');
      const res = page.lastReq('/demo/tickets/reserve');
      assert(res.status === 200, `reserve after PoW returned ${res.status}`);
      return `"${checking}" -> "${done}" -> reservation ${await page.text('rid')}`;
    } finally { await page.close(); }
  });

  // 6 ---------------------------------------------------------------------
  await check(6, 'prefers-reduced-motion: straight to proof of work, no comet', async () => {
    const page = await browser.newPage('c6-reduced');
    try {
      await page.reduceMotion();
      await page.goto('/');
      await page.waitFor(`document.getElementById('status').textContent.includes('Checking your browser')`,
        10000, 'the browser check to start by itself');
      assert(await page.hidden('stage'), 'the comet stage was still visible under reduced motion');
      assert(await page.hidden('skip'), 'the Skip button was still shown under reduced motion');
      const lede = await page.text('lede');
      assert(/reduced motion/i.test(lede), `lede not updated for reduced motion: "${lede}"`);
      assert(page.req('/v1/challenges').length === 0,
        'a comet challenge was fetched despite reduced motion');
      await page.waitFor(`!document.getElementById('reserve').disabled`, 40000, 'PoW to enable Reserve');
      const anim = await page.eval('document.getAnimations ? document.getAnimations().length : 0');
      assert(anim === 0, `${anim} running animations under reduced motion`);
      return `no /v1/challenges, stage hidden, lede "${lede.slice(0, 60)}…", token issued`;
    } finally { await page.close(); }
  });

  // 7 ---------------------------------------------------------------------
  await check(7, 'short trail (pointer lifted after ~500ms) -> 422 and a quiet retry offer', async () => {
    const page = await browser.newPage('c7-short');
    try {
      const g = await openGame(page);
      await follow(page, g, { ms: 500 });
      // Move the pointer off the canvas so nothing more is recorded, and let the
      // comet run out its 5 seconds.
      await page.c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 4, y: 4, button: 'none', buttons: 0, pointerType: 'mouse' });
      const a = await attemptResult(page);
      assert(a.status === 422, `short trail returned ${a.status}, expected 422`);
      const span = a.trail.samples.at(-1)[0] - a.trail.samples[0][0];
      assert(span < 1200, `trail was not actually short (${span}ms)`);
      await page.waitFor(`!document.getElementById('retry').hidden`, 8000, 'the retry button');
      const status = await page.text('status');
      assert(/another go|try again|short/i.test(status), `no quiet retry wording: "${status}"`);
      assert(await page.eval(`document.getElementById('reserve').disabled`), 'Reserve was enabled after a 422');
      assert(!(await page.hidden('skip')), 'Skip was not offered after the 422');
      // the page must still work: retry starts a fresh challenge rather than wedging
      await page.clickId('retry');
      await page.waitFor(`document.getElementById('overlay').textContent.includes('inside the ring')`,
        10000, 'a fresh comet after retry');
      return `422 after ${span.toFixed(0)}ms of samples, status "${status}", retry restarts the game`;
    } finally { await page.close(); }
  });

  // 8 ---------------------------------------------------------------------
  await check(8, 'no uncaught JS errors, unhandled rejections or console errors in the whole run', async () => {
    assert(jsErrors.length === 0, `${jsErrors.length} JS problem(s):\n        ${jsErrors.join('\n        ')}`);
    return 'console and error log clean across every page';
  });
} finally {
  if (c1) await c1.close();
  await browser.close();
}

const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed  (${BASE})`);
process.exit(failed.length ? 1 : 0);
}

if (import.meta.main) await main();
