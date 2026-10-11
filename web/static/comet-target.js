// Shared visual target. Coordinates and scoring stay at the centre of the ring.
// CSS-sized geometry stays visible around a fingertip on a narrow phone canvas.
export const PRESENTATION_VERSION = 'plain_ring_v1';

export function targetGeometry(cssWidth = 600) {
  const scale = 600 / Math.max(1, cssWidth);
  return { radius: 32 * scale, core: 9 * scale, line: 2 * scale };
}

export function drawTarget(ctx, point, cssWidth = 600) {
  const [x, y] = point;
  const { radius, core, line } = targetGeometry(cssWidth);
  ctx.save();
  const glow = ctx.createRadialGradient(x, y, core, x, y, radius * 1.25);
  glow.addColorStop(0, '#ffc47766');
  glow.addColorStop(1, '#ffc47700');
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(x, y, radius * 1.25, 0, Math.PI * 2); ctx.fill();
  ctx.lineWidth = line;
  ctx.strokeStyle = '#ffd397';
  ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = '#fff4dc';
  ctx.beginPath(); ctx.arc(x, y, core, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}
