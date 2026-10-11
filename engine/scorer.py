"""Explicit, provisional movement heuristics; no trained classifier."""

import math
from collections.abc import Mapping

import numpy as np

from engine.path import PATH_VERSIONS, make_path

FEATURES = ("lag_ms", "err_mean_px", "submoves_per_s", "jitter_px", "power_law_beta")
STEP_MS = 1000 / 60


def normalize_samples(samples):
    """Validate and collapse repeated timestamps, preserving the last position."""
    try:
        data = np.asarray(samples, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("samples must be finite [t_ms, x, y] triples") from exc
    if data.size == 0:
        raise ValueError("trail too short")
    if data.ndim != 2 or data.shape[1] != 3 or not np.isfinite(data).all():
        raise ValueError("samples must be finite [t_ms, x, y] triples")
    if (data[:, 0] < 0).any() or (np.diff(data[:, 0]) < 0).any():
        raise ValueError("timestamps must be nonnegative and nondecreasing")
    keep = np.r_[np.diff(data[:, 0]) != 0, True]
    data = data[keep]
    if len(data) < 2 or data[-1, 0] - data[0, 0] < 1000:
        raise ValueError("trail too short")
    return data


def resample(samples):
    data = normalize_samples(samples)
    count = math.floor((data[-1, 0] - data[0, 0]) / STEP_MS + 1e-9) + 1
    times = data[0, 0] + np.arange(count) * STEP_MS
    times = times[times <= data[-1, 0]]
    xy = np.column_stack([np.interp(times, data[:, 0], data[:, axis]) for axis in (1, 2)])
    return times, xy


def smooth(values):
    """Centered seven-sample moving average, with replicated edge values."""
    values = np.asarray(values)
    if values.ndim == 1:
        return np.convolve(np.pad(values, (3, 3), mode="edge"), np.ones(7) / 7, mode="valid")
    return np.column_stack([smooth(values[:, axis]) for axis in range(values.shape[1])])


def count_speed_peaks(speed):
    """Prominent local maxima; equal-height plateaus count once."""
    span = float(np.ptp(speed))
    if span <= 1e-9:
        return 0
    candidates = []
    i = 1
    while i < len(speed) - 1:
        end = i
        while end + 1 < len(speed) and speed[end + 1] == speed[i]:
            end += 1
        if end < len(speed) - 1 and speed[i] > speed[i - 1] and speed[end] > speed[end + 1]:
            peak = (i + end) // 2
            left = i - 1
            while left > 0 and speed[left - 1] <= speed[peak]:
                left -= 1
            right = end + 1
            while right < len(speed) - 1 and speed[right + 1] <= speed[peak]:
                right += 1
            prominence = speed[peak] - max(np.min(speed[left:peak + 1]), np.min(speed[peak:right + 1]))
            if prominence >= 0.1 * span:
                candidates.append(peak)
        i = end + 1
    selected = []
    for peak in sorted(candidates, key=lambda p: (-speed[p], p)):
        if all(abs(peak - previous) >= 6 for previous in selected):
            selected.append(peak)
    return len(selected)


def features(samples, seed: int, path_version="v1"):
    times, xy = resample(samples)
    path = make_path(seed, path_version)
    target = np.asarray([path(t) for t in times])
    # Use identical observations for every lag and never evaluate negative challenge time.
    eligible = times >= 500
    lags = np.arange(31) * STEP_MS
    errors = [np.mean(np.sum((xy[eligible] - np.asarray([path(t - lag) for t in times[eligible]])) ** 2, axis=1))
              for lag in lags]
    lag = float(lags[int(np.argmin(errors))])
    smoothed = smooth(xy)
    velocity = np.gradient(smoothed, STEP_MS / 1000, axis=0)
    acceleration = np.gradient(velocity, STEP_MS / 1000, axis=0)
    speed = np.linalg.norm(velocity, axis=1)
    curvature = np.abs(velocity[:, 0] * acceleration[:, 1] - velocity[:, 1] * acceleration[:, 0]) / np.maximum(speed, 1e-12) ** 3
    usable = (speed > 1e-6) & (curvature > 1e-9) & np.isfinite(curvature)
    usable[:4] = False
    usable[-4:] = False
    beta = 0.0
    if np.count_nonzero(usable) >= 10:
        log_curvature = np.log(curvature[usable])
        if np.std(log_curvature) > 1e-6:
            beta = -float(np.polyfit(log_curvature, np.log(speed[usable]), 1)[0])
    duration = (times[-1] - times[0]) / 1000
    return {
        "lag_ms": lag,
        "err_mean_px": float(np.mean(np.linalg.norm(xy - target, axis=1))),
        "submoves_per_s": count_speed_peaks(smooth(speed)) / duration,
        "jitter_px": float(np.sqrt(np.mean(np.sum((xy - smoothed) ** 2, axis=1)))),
        "power_law_beta": beta,
    }


def validate_variant(variant):
    try:
        enabled = variant["enabled"]
        bands = variant["features"]
        threshold = variant["pass_threshold"]
        valid = (variant.get("path_version", "v1") in PATH_VERSIONS
                 and isinstance(variant["id"], str) and bool(variant["id"])
                 and isinstance(enabled, list) and bool(enabled)
                 and all(isinstance(name, str) for name in enabled)
                 and len(set(enabled)) == len(enabled) and set(enabled) <= set(FEATURES)
                 and isinstance(bands, Mapping) and set(bands) == set(FEATURES)
                 and not isinstance(threshold, bool) and math.isfinite(threshold) and 0 < threshold <= 1)
        for name in FEATURES:
            low, high = bands[name]
            valid = valid and math.isfinite(low) and math.isfinite(high) and low < high
        if not valid:
            raise ValueError("invalid variant")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid variant") from exc


def score_features(values, variant):
    """Accept plain feature values or the ScoreResult feature objects stored by P1."""
    validate_variant(variant)
    result = {}
    for name in FEATURES:
        try:
            value = values[name]
            if isinstance(value, Mapping):
                value = value["value"]
            value = float(value)
            if not math.isfinite(value):
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("missing or invalid feature: " + name) from exc
        low, high = variant["features"][name]
        result[name] = {"value": value, "band": [low, high], "ok": low <= value <= high,
                        "enabled": name in variant["enabled"]}
    fraction = sum(result[name]["ok"] for name in variant["enabled"]) / len(variant["enabled"])
    return {"score": fraction, "pass": fraction >= variant["pass_threshold"], "variant": variant["id"], "features": result}


def score(samples: list, seed: int, variant: dict):
    validate_variant(variant)
    return score_features(features(samples, seed, variant.get("path_version", "v1")), variant)
