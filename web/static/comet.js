// "Follow the comet" game: pure canvas + pointer logic. No network, no page state.
// runComet(canvas, seed, {onProgress, onStart, signal}) -> Promise<{samples, pointerType}>
import { makePath, W, H, DURATION_MS } from './path.js';

export const START_RADIUS = 40;   // logical px: pointer must land this close to start
export const GLOW_RADIUS = 80;    // logical px: visible catch zone

// ---- Pure helpers (unit-tested in node) ----

// Client (CSS) px -> logical 600x400 canvas px. rect = canvas.getBoundingClientRect().
// The canvas must have no border/padding so the rect is exactly the drawn area.
export function toLogical(clientX, clientY, rect) {
  return [(clientX - rect.left) * W / rect.width, (clientY - rect.top) * H / rect.height];
}

export const round1 = v => Math.round(v * 10) / 10;

// event.timeStamp shares performance.now()'s origin in modern browsers. Very old engines
// used epoch ms; if the two are wildly apart, fall back to the handler time.
export function eventTime(ts, now) {
  return Number.isFinite(ts) && Math.abs(ts - now) < 60000 ? ts : now;
}

// PointerEvent-likes -> [[t_ms, x, y], ...] with t counted from t0, kept only for 0 <= t <= 3000.
export function buildSamples(events, t0, rect, now) {
  const out = [];
  for (const ev of events) {
    const t = eventTime(ev.timeStamp, now ?? ev.timeStamp) - t0;
    if (t < 0 || t > DURATION_MS) continue;
    const [x, y] = toLogical(ev.clientX, ev.clientY, rect);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
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

function drawComet(ctx, [x, y], tail, glowAlpha = 0.45) {
  for (let i = 0; i < tail.length; i++) {
    const [tx, ty] = tail[i], k = (i + 1) / tail.length;
    ctx.beginPath();
    ctx.arc(tx, ty, 3 + 7 * k, 0, 2 * Math.PI);
    ctx.fillStyle = `rgba(255, 170, 80, ${0.05 + 0.25 * k})`;
    ctx.fill();
  }
  const glow = ctx.createRadialGradient(x, y, 0, x, y, GLOW_RADIUS);
  glow.addColorStop(0, `rgba(255, 214, 102, ${glowAlpha})`);
  glow.addColorStop(0.35, `rgba(245, 160, 66, ${glowAlpha * 0.45})`);
  glow.addColorStop(1, 'rgba(245, 160, 66, 0)');
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(x, y, GLOW_RADIUS, 0, 2 * Math.PI);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(x, y, 13, 0, 2 * Math.PI);
  ctx.fillStyle = '#fff4cc';
  ctx.fill();
}

// Draw the comet resting at its start point, no animation (used for reduced-motion / idle).
export function drawStill(canvas, seed) {
  const ctx = setupCanvas(canvas);
  drawBackground(ctx, starfield(seed));
  drawComet(ctx, makePath(seed)(0), []);
}

// ---- The game ----

export function runComet(canvas, seed, { onProgress, onStart, signal } = {}) {
  return new Promise((resolve, reject) => {
    const ctx = setupCanvas(canvas);
    const stars = starfield(seed);
    const pos = makePath(seed);
    const start = pos(0);
    let state = 'waiting', t0 = 0, raf = 0, progress = 0, pointerType = '';
    const samples = [], tail = [];

    const rect = () => canvas.getBoundingClientRect();

    function maybeStart(e) {
      if (state !== 'waiting') return;
      const p = toLogical(e.clientX, e.clientY, rect());
      if (dist(p, start) > START_RADIUS) return;
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
        ctx.arc(start[0], start[1], START_RADIUS + 6 * pulse, 0, 2 * Math.PI);
        ctx.strokeStyle = `rgba(255, 214, 102, ${0.35 + 0.35 * pulse})`;
        ctx.lineWidth = 2;
        ctx.stroke();
        drawComet(ctx, start, [], 0.35 + 0.2 * pulse);
      } else {
        const el = Math.max(0, now - t0), t = Math.min(el, DURATION_MS);
        const p = pos(t);
        tail.push(p);
        if (tail.length > 12) tail.shift();
        drawComet(ctx, p, tail.slice(0, -1));
        progress = Math.max(progress, t / DURATION_MS);   // never goes backwards
        onProgress?.(progress);
        if (el >= DURATION_MS) {
          cleanup();
          samples.sort((a, b) => a[0] - b[0]);
          resolve({ samples, pointerType: pointerType || 'mouse' });
          return;
        }
      }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
  });
}
