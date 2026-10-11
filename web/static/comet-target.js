// Shared visual target. Coordinates and scoring stay at the centre of the ring.
// CSS-sized geometry stays visible around a fingertip on a narrow phone canvas.
export function targetGeometry(cssWidth = 600) {
  const scale = 600 / Math.max(1, cssWidth);
  return { radius: 32 * scale, core: 9 * scale, line: 2 * scale, arrow: 40 * scale };
}

export function drawTarget(ctx, point, previous, cssWidth = 600) {
  const [x, y] = point;
  const { radius, core, line, arrow } = targetGeometry(cssWidth);
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
  if (previous && Math.hypot(x - previous[0], y - previous[1]) > 0.001) {
    // Show current motion, not a preview of future target positions.
    const angle = Math.atan2(y - previous[1], x - previous[0]);
    ctx.translate(x, y); ctx.rotate(angle);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(arrow - line * 3, -line * 3);
    ctx.lineTo(arrow, 0);
    ctx.lineTo(arrow - line * 3, line * 3);
    ctx.stroke();
  }
  ctx.restore();
}
