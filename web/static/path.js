// Comet path. Must match engine/path.py exactly (see contracts/fixtures/path_vectors.json).
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t = (((t + Math.imul(t ^ (t >>> 7), t | 61)) >>> 0) ^ t) >>> 0;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export const W = 600, H = 400, DURATION_MS = 3000;
const AMP_X = [130, 50, 20], AMP_Y = [80, 35, 15];
export function makePath(seed, pathVersion = 'v1') {
  if (!['v1', 'smooth_v2'].includes(pathVersion)) throw new Error('unsupported path_version');
  if (pathVersion === 'smooth_v2') return makeSmoothPath(seed);
  const r = mulberry32(seed);
  const comps = [AMP_X, AMP_Y].map(amps => amps.map(base => {
    const f = 0.10 + r() * 0.25, ph = r() * 2 * Math.PI, amp = base * (0.6 + 0.4 * r());
    return [f, ph, amp];
  }));
  const kicks = [900, 1900].map(t0 => {
    const tk = t0 + r() * 500, ang = r() * 2 * Math.PI, mag = 60 + r() * 30;
    return [tk, mag * Math.cos(ang), mag * Math.sin(ang)];
  });
  return function pos(tMs) {
    const t = tMs / 1000;
    let x = W / 2, y = H / 2;
    for (const [f, p, a] of comps[0]) x += a * Math.sin(2 * Math.PI * f * t + p);
    for (const [f, p, a] of comps[1]) y += a * Math.sin(2 * Math.PI * f * t + p);
    for (const [tk, dx, dy] of kicks) {
      const u = Math.min(Math.max((tMs - tk) / 120, 0), 1), s = u * u * (3 - 2 * u);
      x += dx * s; y += dy * s;
    }
    return [Math.min(Math.max(x, 30), W - 30), Math.min(Math.max(y, 30), H - 30)];
  };
}

function makeSmoothPath(seed) {
  const r = mulberry32(seed);
  const comps = [[120, 35], [70, 20]].map(amps => amps.map(base => {
    const f = .08 + .06 * r(), ph = r() * 2 * Math.PI, amp = base * (.8 + .2 * r());
    return [f, ph, amp];
  }));
  // Amplitude sums bound x to145..455/y to110..290; speed stays below158 px/s.
  return tMs => comps.map((axis, i) => (i === 0 ? W : H) / 2 + axis.reduce(
    (sum, [f, ph, amp]) => sum + amp * Math.sin(2 * Math.PI * f * tMs / 1000 + ph), 0));
}
