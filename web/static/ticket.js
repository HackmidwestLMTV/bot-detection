// Ticket page controller: session, API calls, comet -> attempt, PoW fallback, reserve, tester mode.
import { makePath } from './path.js';
import { runComet, drawStill } from './comet.js';

// Console check: makePath(42)(1000) must be [103.824, 209.568]
window.makePath = makePath;

const $ = id => document.getElementById(id);
const el = {
  lede: $('lede'), tester: $('tester'), consent: $('consent'), nondominant: $('nondominant'), thanks: $('thanks'),
  stage: $('stage'), canvas: $('comet'), ring: $('ring'), ringFill: $('ring-fill'), overlay: $('overlay'), stub: $('stub'),
  skip: $('skip'), retry: $('retry'), result: $('result'), status: $('status'), checkTitle: $('check-title'),
  reserve: $('reserve'), reserveMsg: $('reserve-msg'), verifyAgain: $('verify-again'),
  confirm: $('confirm'), rid: $('rid'), reuse: $('reuse'),
};

const TESTER = new URLSearchParams(location.search).get('tester') === '1';
const REDUCED = !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

// ---- session ----
function randomId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(b, x => x.toString(16).padStart(2, '0')).join('');
}
let memSession = null;
function sessionId() {
  try {
    let s = sessionStorage.getItem('followit_session');
    if (!s) { s = 'sess_' + randomId(); sessionStorage.setItem('followit_session', s); }
    return s;
  } catch {
    return (memSession ??= 'sess_' + randomId());
  }
}
const SESSION = sessionId();

// ---- api ----
async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON body */ }
  return { status: res.status, ok: res.ok, data };
}

// ---- state ----
const S = {
  gen: 0,            // bumps on every new flow; stale async results check it and bail
  abort: null,       // AbortController for the running comet
  worker: null,      // running PoW worker
  token: null,       // kept in memory (also after use) for the "reuse token" demo
  ringMax: 0,
  thanks: 0,
};

// ---- small UI helpers ----
const say = msg => { el.status.textContent = msg; };
const overlay = msg => { el.overlay.textContent = msg || ''; el.overlay.hidden = !msg; };
const RING_C = 2 * Math.PI * 20;
el.ringFill.style.strokeDasharray = `${RING_C}`;
function setRing(f) {
  S.ringMax = Math.max(S.ringMax, Math.min(1, f));   // never goes backwards
  el.ringFill.style.strokeDashoffset = `${RING_C * (1 - S.ringMax)}`;
}
function resetRing() { S.ringMax = 0; el.ringFill.style.strokeDashoffset = `${RING_C}`; }
function showResult(html) { el.result.innerHTML = html; el.result.hidden = !html; }
function showRetry(label, fn) {
  el.retry.textContent = label;
  el.retry.onclick = fn;
  el.retry.hidden = false;
}
const hideRetry = () => { el.retry.hidden = true; el.retry.onclick = null; };

function stopEverything() {
  S.gen++;
  S.abort?.abort(); S.abort = null;
  S.worker?.terminate(); S.worker = null;
}

function setPassed(token, msg) {
  S.token = token;
  el.reserve.disabled = false;
  el.reserve.hidden = false;
  el.reserveMsg.hidden = true;
  el.verifyAgain.hidden = true;
  el.skip.hidden = true;
  overlay("You're through");
  say(msg);
}

// ---- tester mode ----
function testerDevice() { return el.tester.querySelector('input[name="device"]:checked')?.value || null; }
function testerReady() { return el.consent.checked && !!testerDevice(); }
function updateThanks() {
  if (!S.thanks) return;
  el.thanks.hidden = false;
  el.thanks.textContent = `Thank you: ${S.thanks} trace${S.thanks === 1 ? '' : 's'} sent`;
}
if (TESTER) {
  el.tester.hidden = false;
  try { S.thanks = +sessionStorage.getItem('followit_thanks') || 0; } catch { /* ignore */ }
  updateThanks();
  el.tester.addEventListener('submit', e => e.preventDefault());
  el.tester.addEventListener('change', () => {
    // Nothing is fetched or sent until consent is ticked and a device is picked.
    if (testerReady() && !S.abort && !S.worker && el.reserve.disabled && el.retry.hidden) startChallenge();
    else if (!testerReady() && S.abort) waitForTester();
  });
}
function waitForTester() {
  stopEverything();
  drawStill(el.canvas, 42);
  overlay(el.consent.checked ? 'Pick your device above to start' : 'Tick the box above to start');
}

// ---- comet flow ----
async function startChallenge() {
  stopEverything();
  const gen = S.gen;
  hideRetry();
  showResult('');
  resetRing();
  el.skip.hidden = false;
  if (REDUCED) return startPow('reduced');
  if (TESTER && !testerReady()) return waitForTester();

  say('');
  overlay('Loading…');
  let ch;
  try {
    const r = await post('/v1/challenges', { session_id: SESSION });
    if (gen !== S.gen) return;
    if (!r.ok || !r.data?.challenge_id) return startPow('challenge_failed');
    ch = r.data;
  } catch {
    if (gen === S.gen) startPow('network');
    return;
  }

  // Keep the prompt pill away from the comet so it never hides it.
  el.overlay.classList.toggle('top', makePath(ch.seed >>> 0)(0)[1] > 200);
  overlay('Put your finger on the comet');
  const ac = new AbortController();
  S.abort = ac;
  let run;
  try {
    run = await runComet(el.canvas, ch.seed >>> 0, {
      onProgress: setRing,
      onStart: () => overlay(''),
      signal: ac.signal,
    });
  } catch {
    return; // aborted (Skip / reset)
  }
  if (gen !== S.gen) return;
  S.abort = null;
  await submitAttempt(ch, run, gen);
}

function normPointer(t) { return t === 'touch' || t === 'pen' ? t : 'mouse'; }

async function submitAttempt(ch, { samples, pointerType }, gen) {
  overlay('');
  say('One moment…');
  const pointer_type = normPointer(pointerType);
  const trail = {
    samples,
    device: TESTER ? testerDevice() : (pointer_type === 'touch' ? 'touch' : 'mouse'),
    pointer_type,
    cohort: TESTER ? 'human_test' : 'organic',
    round_id: null,
  };
  if (TESTER) trail.tester = { consent: el.consent.checked, nondominant_hand: el.nondominant.checked };

  let r;
  try {
    r = await post(`/v1/challenges/${encodeURIComponent(ch.challenge_id)}/attempt`, trail);
  } catch {
    if (gen === S.gen) failToPow();
    return;
  }
  if (gen !== S.gen) return;

  if (r.status === 422) {
    // Usually: finger lifted early, trail too short. Quietly offer another go.
    overlay('');
    say('That one was cut a little short. Want another go? Or skip it.');
    showRetry(TESTER ? 'Play again' : 'Try again', startChallenge);
    return;
  }
  if (r.status === 429 || !r.ok) return startPow('limited');

  const result = r.data?.result || {};
  el.stub.hidden = !result.stub;
  const token = r.data?.token || null;

  if (TESTER) {
    S.thanks++;
    try { sessionStorage.setItem('followit_thanks', String(S.thanks)); } catch { /* ignore */ }
    updateThanks();
    const score = typeof result.score === 'number' ? result.score.toFixed(2) : '–';
    showResult(`<p><strong>${token ? 'Passed' : 'Not a pass this time'}</strong> · score ${score}</p>
      <p class="muted">Thank you. Every trace helps us make the check fairer.</p>`);
    showRetry('Play again', startChallenge);
    if (token) setPassed(token, "You're through. You can reserve now, or play again.");
    else { overlay(''); say('Thanks, that trace was saved. Play again, or skip to reserve.'); el.skip.hidden = false; }
    return;
  }

  if (token) setPassed(token, "You're through. You can reserve now.");
  else failToPow();
}

function failToPow() {
  showResult("<p>That didn't work, so we'll check your browser instead.</p>");
  startPow('failed', true);
}

// ---- proof of work ----
function solveInWorker(nonce, bits) {
  return new Promise((resolve, reject) => {
    const w = new Worker('/static/pow-worker.js');
    S.worker = w;
    w.onmessage = ({ data }) => { w.terminate(); if (S.worker === w) S.worker = null; resolve(data.counter); };
    w.onerror = e => { w.terminate(); if (S.worker === w) S.worker = null; reject(e); };
  });
}

async function startPow(reason, keepResult = false) {
  const hadFocus = [el.skip, el.retry, el.verifyAgain].includes(document.activeElement);
  stopEverything();
  const gen = S.gen;
  hideRetry();
  if (!keepResult) showResult('');
  el.skip.hidden = true;
  if (hadFocus) el.checkTitle.focus();     // keep keyboard users anchored
  if (REDUCED) {
    el.stage.hidden = true;
    el.lede.textContent = "Your device asks for reduced motion, so there's no game. We'll check your browser instead.";
  } else {
    drawStill(el.canvas, 7);
    overlay('Checking your browser…');
  }
  say('Checking your browser. Nothing to do.');

  try {
    for (let tryNo = 0; tryNo < 2; tryNo++) {
      const p = await post('/v1/pow', { session_id: SESSION });
      if (gen !== S.gen) return;
      if (!p.ok || !p.data?.pow_id) throw new Error('pow ' + p.status);
      const counter = await solveInWorker(p.data.nonce, p.data.bits);
      if (gen !== S.gen) return;
      const s = await post(`/v1/pow/${encodeURIComponent(p.data.pow_id)}/solve`, { counter });
      if (gen !== S.gen) return;
      if (s.ok && s.data?.token) {
        setPassed(s.data.token, 'Done. You can reserve now.');
        if (hadFocus || document.activeElement === el.checkTitle) el.reserve.focus();
        return;
      }
      if (s.status !== 400) throw new Error('solve ' + s.status);
      // 400 (e.g. expired): silently fetch a fresh puzzle and go again
    }
    throw new Error('pow retries exhausted');
  } catch {
    if (gen !== S.gen) return;
    overlay('');
    say("We couldn't finish the check. Please try again.");
    showRetry('Check again', () => startPow('retry'));
  }
}

// ---- reserve ----
const REASONS = {
  used: ['That pass has already been used. Each pass works for one reservation.', true],
  expired: ['That pass expired. Passes last 2 minutes.', true],
  wrong_session: ['That pass belongs to a different browser session.', true],
  cap: ["You've reserved the most tickets allowed for this visit (2). Thanks for the enthusiasm!", false],
};

async function reserve({ reuse = false } = {}) {
  if (!S.token) return;
  el.reserve.disabled = true;
  el.reuse.disabled = true;
  el.reserveMsg.hidden = true;
  el.verifyAgain.hidden = true;
  say(reuse ? 'Trying the same pass again…' : 'Reserving…');
  let r;
  try {
    r = await post('/demo/tickets/reserve', { token: S.token, session_id: SESSION });
  } catch {
    say("Couldn't reach the box office. Please try again.");
    el.reserve.disabled = reuse;
    el.reuse.disabled = false;
    return;
  }
  el.reuse.disabled = false;
  if (r.ok && r.data?.reservation_id) {
    el.rid.textContent = r.data.reservation_id;
    el.confirm.hidden = false;
    el.reserve.hidden = true;
    el.reuse.hidden = false;
    overlay('');
    say(`Reserved. Your reservation number is ${r.data.reservation_id}.`);
    el.confirm.setAttribute('tabindex', '-1');
    el.confirm.focus();
    return;
  }
  const reason = r.data?.reason ?? r.data?.detail?.reason;
  const [msg, offerVerify] = REASONS[reason] || ['Something went wrong reserving. Please verify again.', true];
  el.reserveMsg.textContent = msg;
  el.reserveMsg.hidden = false;
  say(msg);
  el.reserve.disabled = true;
  if (offerVerify) { el.verifyAgain.hidden = false; }
}

el.reserve.addEventListener('click', () => reserve());
el.reuse.addEventListener('click', () => reserve({ reuse: true }));
el.verifyAgain.addEventListener('click', () => {
  S.token = null;
  el.reserve.disabled = true;
  el.reserve.hidden = false;
  el.reserveMsg.hidden = true;
  el.verifyAgain.hidden = true;
  el.reuse.hidden = true;
  el.stage.hidden = REDUCED;
  if (!REDUCED) el.checkTitle.focus();
  startChallenge();
});
el.skip.addEventListener('click', () => startPow('skip'));

// ---- go ----
startChallenge();
