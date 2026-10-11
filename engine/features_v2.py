"""Target-conditioned measurements for research/shadow use; never a human verdict."""
import numpy as np

from contracts.research import FEATURE_VERSION
from engine.path import make_path
from engine.scorer import features as legacy_features, normalize_samples, smooth

TIMES = np.linspace(0, 3000, 181)
CHANNELS = ("cursor_vx", "cursor_vy", "error_x", "error_y", "target_vx", "target_vy", "speed", "valid")
FEATURE_NAMES = (
    "lag_ms", "err_mean_px", "submoves_per_s", "jitter_px", "power_law_beta",
    "coverage", "event_count", "span_ms", "gap_max_ms", "interval_median_ms", "interval_cv",
    "error_mean_norm", "error_p95_norm", "lag_alignment_gain", "velocity_alignment",
    "alignment_window_std", "speed_median", "speed_p95", "acceleration_p95", "jerk_p95",
    "turn_mean", "turn_std", "path_length_norm", "residual_autocorr", "stationary_fraction",
)


def _mean(x):
    return float(np.mean(x)) if len(x) else 0.0


def _q(x, percentile):
    return float(np.percentile(x, percentile)) if len(x) else 0.0


def representation(samples, seed, path_version="smooth_v2"):
    native = normalize_samples(samples)
    if len(native) > 5000 or native[-1, 0] > 3000 or (native[:, 1:] < 0).any() or (native[:, 1:] > [600, 400]).any():
        raise ValueError("research samples must lie inside the bounded challenge")
    t, points = native[:, 0], native[:, 1:] / [600, 400]
    delta = np.diff(t)
    right = np.searchsorted(t, TIMES, side="left").clip(0, len(t) - 1)
    left = (right - 1).clip(0)
    exact = np.isclose(t[right], TIMES, atol=0.11)
    valid = (TIMES >= t[0]) & (TIMES <= t[-1]) & (exact | ((t[right] - t[left]) <= 100))
    xy = np.column_stack([np.interp(TIMES, t, points[:, a]) for a in (0, 1)])
    path = make_path(seed, path_version)
    target = np.asarray([path(float(x)) for x in TIMES]) / [600, 400]
    velocity = np.gradient(smooth(xy), 1 / 60, axis=0)
    target_velocity = np.gradient(target, 1 / 60, axis=0)
    error = xy - target
    speed = np.linalg.norm(velocity, axis=1)
    # Derivatives only use windows whose neighbors are supported by real events.
    supported = np.convolve(valid.astype(int), np.ones(9, dtype=int), mode="same") == 9
    sequence = np.column_stack([velocity, error, target_velocity, speed, supported.astype(float)])
    sequence[~supported] = 0
    acceleration = np.gradient(velocity, 1 / 60, axis=0)
    jerk = np.gradient(acceleration, 1 / 60, axis=0)
    observed = valid & (TIMES >= 500)
    errors = []
    shifted = []
    for lag in np.arange(31) * (1000 / 60):
        delayed = np.asarray([path(float(max(0, x - lag))) for x in TIMES]) / [600, 400]
        shifted.append(delayed)
        errors.append(_mean(np.sum((xy[observed] - delayed[observed]) ** 2, axis=1)))
    best = int(np.argmin(errors))
    null = []
    for salt in (0x9e3779b9, 0x85ebca6b, 0xc2b2ae35):
        other = make_path(seed ^ salt, path_version)
        alternative = np.asarray([other(float(x)) for x in TIMES]) / [600, 400]
        null.append(_mean(np.sum((xy[observed] - alternative[observed]) ** 2, axis=1)))
    null_error = float(np.median(null))
    gain = (null_error - errors[best]) / max(null_error, 1e-8)
    delayed_velocity = np.gradient(shifted[best], 1 / 60, axis=0)
    denominator = np.linalg.norm(velocity, axis=1) * np.linalg.norm(delayed_velocity, axis=1)
    moving = supported & observed & (denominator > 1e-7)
    alignment = np.sum(velocity * delayed_velocity, axis=1) / np.maximum(denominator, 1e-7)
    windows = [_mean(alignment[moving & (TIMES >= lo) & (TIMES < lo + 750)]) for lo in (0, 750, 1500, 2250)]
    turns = np.diff(np.unwrap(np.arctan2(velocity[:, 1], velocity[:, 0])))
    turn_mask = supported[1:] & supported[:-1] & (speed[1:] > 1e-4) & (speed[:-1] > 1e-4)
    residual = error[valid]
    corr = 0.0
    if len(residual) > 3:
        centered = residual - residual.mean(axis=0)
        corr = float(np.sum(centered[1:] * centered[:-1]) / max(np.sum(centered[:-1] ** 2), 1e-8))
    base = legacy_features(samples, seed, path_version)
    values = [base[n] for n in FEATURE_NAMES[:5]] + [
        float(valid.mean()), len(t), float(t[-1] - t[0]), float(delta.max()), float(np.median(delta)),
        float(delta.std() / max(delta.mean(), 1e-8)),
        _mean(np.linalg.norm(error[valid], axis=1)), _q(np.linalg.norm(error[valid], axis=1), 95),
        gain, _mean(alignment[moving]), float(np.std(windows)), _q(speed[supported], 50), _q(speed[supported], 95),
        _q(np.linalg.norm(acceleration[supported], axis=1), 95), _q(np.linalg.norm(jerk[supported], axis=1), 95),
        _mean(np.abs(turns[turn_mask])), float(np.std(turns[turn_mask])) if turn_mask.any() else 0,
        float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum()), corr,
        _mean((speed[supported] < 0.005).astype(float)),
    ]
    vector = np.asarray(values, dtype=np.float32)
    if not np.isfinite(vector).all() or not np.isfinite(sequence).all():
        raise ValueError("nonfinite research representation")
    quality = {"eligible": bool(len(t) >= 40 and t[-1] - t[0] >= 2500 and valid.mean() >= 0.85),
               "coverage": float(valid.mean()), "event_count": len(t), "max_gap_ms": float(delta.max())}
    return {"features": dict(zip(FEATURE_NAMES, vector.tolist())), "vector": vector,
            "sequence": sequence.astype(np.float32), "quality": quality, "feature_version": FEATURE_VERSION}
