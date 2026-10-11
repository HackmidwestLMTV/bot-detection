# Roaming target path (`roaming_v3`)

New challenges use a five-second display (`plain_ring_5s_v2`) and a seeded,
smooth target loop (`roaming_v3`). Each issued challenge has a fresh random
seed. The seed chooses the starting phase, clockwise/counterclockwise travel,
axis lengths, phase offset, center, gentle harmonic shape and pace. The visible
ball, symmetric glow and start ring do not show its direction or future path.

On the 600 by 400 logical canvas, the center stays within x=84..516, y=84..316.
The 84px margin leaves the 32 CSS-pixel start ring and stroke visible when the
canvas is at least 236 CSS pixels wide, including the narrow phone layout.
A 6.2–6.6 second period traverses more than three quarters of the broad
loop during the five-second challenge; it does not need to close the loop.
Sinusoidal components remain continuously differentiable without clipping,
teleportation, sharp corners or direction-change impulses. The analytic speed
bound is under 256 logical px/s and acceleration under 282 logical px/s².

Regression tests cover 1,003 seeds, both endpoints and 5ms sampling, requiring
600–1,000px of travel, over 295px horizontal span and over 145px vertical span.
The first 1,000 seeds measured 638–842px total distance, 322–408px horizontal
span, 162–213px vertical span, and no more than 220px/s peak speed. These are
geometry checks, not evidence of human success or accessibility. Wider coverage
requires more hand movement than `smooth_v2`; collect new mouse, trackpad and
real-touch results before tuning scoring or claiming a usability improvement.

Python `engine/path.py` and JavaScript `web/static/path.js` share the versioned
implementation. `fixtures/path_vectors_roaming_v3.json` is the parity contract.
Legacy `v1` and `smooth_v2` functions remain unchanged. Missing path metadata
still means `v1`; historical evidence must never be relabeled as `roaming_v3`.
Gates, research datasets and shadow artifacts require matching path and
presentation versions. Issued challenges retain their assigned path.

The path is deterministic and sent to the browser. Randomized display variety
does **not** hide the future trajectory or prevent forged client telemetry.
