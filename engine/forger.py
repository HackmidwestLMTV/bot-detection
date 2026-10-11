"""Reproducible synthetic attacks. These never save human calibration data."""

import math

import numpy as np

from engine.path import DURATION_MS, make_path
from engine.scorer import STEP_MS, normalize_samples


def forge_trail(seed, lag_ms=0, noise_px=0, submove_hz=0, overshoot=0, *, rng_seed=None, path_version="v1", duration_ms=DURATION_MS):
    """Return a challenge-length trace at 60 Hz. Overshoot is dimensionless."""
    if duration_ms not in (3000, DURATION_MS):
        raise ValueError("unsupported challenge duration")
    parameters = (lag_ms, noise_px, submove_hz, overshoot)
    if any(not math.isfinite(p) or p < 0 for p in parameters) or lag_ms > 500:
        raise ValueError("forger parameters must be finite, nonnegative; lag <= 500 ms")
    rng = np.random.default_rng((int(seed) if rng_seed is None else int(rng_seed)) & 0xFFFFFFFF)
    path = make_path(seed, path_version)
    times = np.linspace(0, duration_ms, round(duration_ms / STEP_MS) + 1)
    delayed = np.asarray([path(max(0, t - lag_ms)) for t in times])
    earlier = np.asarray([path(max(0, t - lag_ms - 100)) for t in times])
    xy = delayed + overshoot * (delayed - earlier)
    if submove_hz:
        phase = 2 * math.pi * submove_hz * times / 1000
        xy += 2 * np.column_stack([np.sin(phase), np.cos(phase) - 1])
    if noise_px:
        xy += rng.normal(0, noise_px, xy.shape)
    xy = np.clip(xy, [0, 0], [600, 400])
    return np.column_stack([times, xy]).tolist()


def transplant(trace, seed, path_version="v1"):
    """Transfer a team's recorded error pattern onto a different seeded path."""
    data = normalize_samples(trace["samples"])
    source_path = make_path(trace["seed"], trace.get("path_version", "v1"))
    target_path = make_path(seed, path_version)
    source = np.asarray([source_path(t) for t in data[:, 0]])
    target = np.asarray([target_path(t) for t in data[:, 0]])
    # Preserve residuals exactly; do not clamp away evidence of an implausible forgery.
    return np.column_stack([data[:, 0], target + data[:, 1:] - source]).tolist()
