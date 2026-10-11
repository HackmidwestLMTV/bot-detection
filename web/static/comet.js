// "Follow the comet" game: pure canvas + pointer logic. No network, no page state.
// runComet(canvas, seed, {onProgress, onStart, signal}) -> Promise<{samples, pointerType}>
import { makePath, W, H, DURATION_MS } from './path.js';
import { drawTarget, targetGeometry } from './comet-target.js?v=plain_ring_5s_v2';
export { PRESENTATION_VERSION } from './comet-target.js?v=plain_ring_5s_v2';

export const START_RADIUS = 40;   // logical px: pointer must land this close to start
export const GLOW_RADIUS = 80;    // logical px: decorative symmetric glow

// ---- Pure helpers (unit-tested in node) ----

// Client (CSS) px -> logical 600x400 canvas px. rect = canvas.getBoundingClientRect().
// The canvas must have no border/padding so the rect is exactly the drawn area.
export function toLogical(clientX, clientY, rect) {
  return [(clientX - rect.left) * W / rect.width, (clientY - rect.top) * H / rect.height];
}

export const round1 = v => Math.round(v * 10) / 10;

// Pointer capture keeps the stream coming when a finger or mouse slides past the edge of
// the canvas, so raw conversions can land outside it (we measured -141 px on an overshoot).
// The contract says samples are logical canvas px, so hold them inside the canvas.
export const clampToCanvas = (x, y) =>
  [Math.min(Math.max(x, 0), W), Math.min(Math.max(y, 0), H)];

// event.timeStamp shares performance.now()'s origin in modern browsers. Very old engines
// used epoch ms; if the two are wildly apart, fall back to the handler time.
export function eventTime(ts, now) {
  return Number.isFinite(ts) && Math.abs(ts - now) < 60000 ? ts : now;
}

// PointerEvent-likes -> [[t_ms, x, y], ...] with t counted from t0, kept only for 0 <= t <= DURATION_MS.
export function buildSamples(events, t0, rect, now) {
  const out = [];
  for (const ev of events) {
    const t = eventTime(ev.timeStamp, now ?? ev.timeStamp) - t0;
    if (t < 0 || t > DURATION_MS) continue;
    const [rx, ry] = toLogical(ev.clientX, ev.clientY, rect);
    if (!Number.isFinite(rx) || !Number.isFinite(ry)) continue;
    const [x, y] = clampToCanvas(rx, ry);
    out.push([round1(t), round1(x), round1(y)]);
  }
  return out;
}

export function coalesced(e) {
  const list = e.getCoalescedEvents?.() ?? [e];
  return list.length ? list : [e];
}

export const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

// ---- Drawing ----

function setupCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function starfield(seed) {
  let a = (seed ^ 0x9e3779b9) >>> 0;
  const r = () => ((a = (Math.imul(a, 1664525) + 1013904223) >>> 0) / 4294967296);
  return Array.from({ length: 70 }, () => [r() * W, r() * H, 0.4 + r() * 1.1, 0.15 + r() * 0.45]);
}

function drawBackground(ctx, stars) {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, '#141a2e');
  g.addColorStop(1, '#0b0e1a');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  for (const [x, y, s, o] of stars) {
    ctx.globalAlpha = o;
    ctx.fillStyle = '#cfd6ff';
    ctx.fillRect(x, y, s, s);
  }
  ctx.globalAlpha = 1;
}

function drawComet(ctx, [x, y], glowAlpha = 0.45, cssWidth = 600) {
  const glow = ctx.createRadialGradient(x, y, 0, x, y, GLOW_RADIUS);
  glow.addColorStop(0, `rgba(255, 214, 102, ${glowAlpha})`);
  glow.addColorStop(0.35, `rgba(245, 160, 66, ${glowAlpha * 0.45})`);
  glow.addColorStop(1, 'rgba(245, 160, 66, 0)');
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(x, y, GLOW_RADIUS, 0, 2 * Math.PI);
  ctx.fill();
  drawTarget(ctx, [x, y], cssWidth);
}

// Draw the comet resting at its start point, no animation (used for reduced-motion / idle).
export function drawStill(canvas, seed, pathVersion = 'v1') {
  const ctx = setupCanvas(canvas);
  drawBackground(ctx, starfield(seed));
  drawComet(ctx, makePath(seed, pathVersion)(0), 0.45, canvas.getBoundingClientRect().width);
}

// ---- The game ----

export function runComet(canvas, seed, { onProgress, onStart, signal, pathVersion = 'v1' } = {}) {
  return new Promise((resolve, reject) => {
    const ctx = setupCanvas(canvas);
    const stars = starfield(seed);
    const pos = makePath(seed, pathVersion);
    const start = pos(0);
    let state = 'waiting', t0 = 0, raf = 0, progress = 0, pointerType = '';
    const samples = [];

    const rect = () => canvas.getBoundingClientRect();

    // The drawn target holds a constant CSS size, so on a narrow phone canvas its ring is
    // wider in logical px than the fixed START_RADIUS -- measured 61.5 vs 40 on a 312 CSS px
    // canvas, and real touch probes at 45/55/60 logical px landed inside the visible ring
    // without arming anything. Never let the catch zone be smaller than what the user sees.
    const startRadius = () => Math.max(START_RADIUS, targetGeometry(rect().width).radius);

    function maybeStart(e) {
      if (state !== 'waiting') return;
      const p = toLogical(e.clientX, e.clientY, rect());
      if (dist(p, start) > startRadius()) return;
      state = 'tracking';
      t0 = performance.now();
      pointerType = e.pointerType || pointerType;
      onStart?.();
    }
    function onDown(e) {
      // Capture keeps the stream coming even if the finger slides off the canvas,
      // and (with touch-action: none) stops the page scrolling under the finger.
      try { canvas.setPointerCapture(e.pointerId); } catch { /* ignore */ }
      if (e.pointerType === 'touch') e.preventDefault();
      maybeStart(e);
    }
    function onMove(e) {
      if (state === 'waiting') { maybeStart(e); return; }
      if (state !== 'tracking') return;
      if (e.pointerType) pointerType = e.pointerType;
      const s = buildSamples(coalesced(e), t0, rect(), performance.now());
      for (const x of s) samples.push(x);
    }
    const noScroll = e => { if (state !== 'done') e.preventDefault(); };

    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('touchmove', noScroll, { passive: false });

    function cleanup() {
      state = 'done';
      cancelAnimationFrame(raf);
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('touchmove', noScroll);
    }
    signal?.addEventListener('abort', () => {
      if (state === 'done') return;
      cleanup();
      reject(new DOMException('aborted', 'AbortError'));
    }, { once: true });

    function frame(now) {
      if (state === 'done') return;
      drawBackground(ctx, stars);
      if (state === 'waiting') {
        const pulse = 0.5 + 0.5 * Math.sin(now / 300);
        ctx.beginPath();
        ctx.arc(start[0], start[1], startRadius() + 6 * pulse, 0, 2 * Math.PI);
        ctx.strokeStyle = `rgba(255, 214, 102, ${0.35 + 0.35 * pulse})`;
        ctx.lineWidth = 2;
        ctx.stroke();
        drawComet(ctx, start, 0.35 + 0.2 * pulse, rect().width);
      } else {
        const el = Math.max(0, now - t0), t = Math.min(el, DURATION_MS);
        const p = pos(t);
        drawComet(ctx, p, 0.45, rect().width);
        progress = Math.max(progress, t / DURATION_MS);   // never goes backwards
        onProgress?.(progress);
        if (el >= DURATION_MS) {
          cleanup();
          samples.sort((a, b) => a[0] - b[0]);
          resolve({ samples, pointerType: pointerType || 'mouse', collectorVersion: 'pointer_v2' });
          return;
        }
      }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
  });
}
