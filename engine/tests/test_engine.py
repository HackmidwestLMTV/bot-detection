import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from engine.forger import forge_trail, transplant
from engine.gate import gate
from engine.path import make_path
from engine.scorer import FEATURES, count_speed_peaks, features, normalize_samples, resample, score, score_features

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def variant():
    return json.loads((ROOT / "contracts/fixtures/variant_v1.json").read_text())


def feature_values(lag=200):
    return dict(lag_ms=lag, err_mean_px=30, submoves_per_s=3, jitter_px=2, power_law_beta=.3)


@pytest.mark.parametrize("seed", [1, 7, 42, 4294967295])
def test_path_fixtures_and_bounds(seed):
    data = json.loads((ROOT / "contracts/fixtures/path_vectors.json").read_text())
    vector = next(v for v in data["vectors"] if v["seed"] == seed)
    path = make_path(seed)
    for t, x, y in vector["points"]:
        assert path(t) == pytest.approx((x, y), abs=data["tolerance_px"])
    for t in np.linspace(0, 3000, 601):
        x, y = path(t)
        assert 30 <= x <= 570 and 30 <= y <= 370


@pytest.mark.parametrize("seed", [1, 7, 42, 4294967295])
def test_naive_attack_fails(variant, seed):
    result = score(forge_trail(seed), seed, variant)
    assert not result["pass"]
    assert result["features"]["lag_ms"]["value"] == 0
    assert result["features"]["err_mean_px"]["value"] == pytest.approx(0, abs=1e-9)
    assert set(result["features"]) == set(FEATURES)


@pytest.mark.parametrize("delay", [0, 100, 250, 500])
def test_recovers_known_delay(delay):
    path = make_path(42)
    trail = [[t, *path(max(0, t - delay))] for t in np.linspace(0, 3000, 181)]
    assert features(trail, 42)["lag_ms"] == pytest.approx(delay, abs=1e-6)


def test_linear_motion_resampling_and_stationary_features():
    times, xy = resample([[25, 10, 20], [525, 60, 120], [1050, 112.5, 225]])
    assert times[0] == 25 and times[-1] <= 1050
    np.testing.assert_allclose(xy[:, 0], 10 + (times - 25) * .1)
    np.testing.assert_allclose(xy[:, 1], 20 + (times - 25) * .2)
    stationary = features([[0, 200, 200], [3000, 200, 200]], 42)
    assert stationary["power_law_beta"] == 0
    assert stationary["submoves_per_s"] == 0
    assert stationary["jitter_px"] == pytest.approx(0, abs=1e-10)
    assert all(math.isfinite(value) for value in stationary.values())


def test_duplicates_use_last_position():
    data = normalize_samples([[0, 0, 0], [0, 10, 20], [1000, 40, 50], [1000, 60, 70]])
    assert data.tolist() == [[0, 10, 20], [1000, 60, 70]]


@pytest.mark.parametrize("samples, message", [
    ([], "trail too short"), ([[0, 1, 2], [999, 2, 3]], "trail too short"),
    ([[0, 1, 2], [1500, 2, 3], [1000, 4, 5]], "nondecreasing"),
    ([[-1, 1, 2], [1000, 4, 5]], "nonnegative"),
    ([[0, float("nan"), 2], [1000, 4, 5]], "finite"),
    ([[0, 1, 2], [float("inf"), 4, 5]], "finite"),
    ([[0, 1], [1000, 4]], "triples"),
])
def test_invalid_trails(samples, message):
    with pytest.raises(ValueError, match=message):
        features(samples, 42)


def test_peak_prominence_spacing_and_plateau():
    assert count_speed_peaks(np.ones(61)) == 0
    # Two prominent peaks 100 ms apart; tiny fluctuations do not count.
    speed = np.zeros(30)
    speed[6], speed[12], speed[20] = 10, 9, .5
    assert count_speed_peaks(speed) == 2
    speed[9] = 8
    assert count_speed_peaks(speed) == 2
    speed[:] = 0
    speed[8:11] = 10
    assert count_speed_peaks(speed) == 1


def test_jitter_increases_with_high_frequency_noise():
    clean = [[i * 1000 / 60, 100 + i, 200] for i in range(181)]
    noisy = [[t, x, y + (5 if i % 2 else -5)] for i, (t, x, y) in enumerate(clean)]
    assert features(noisy, 42)["jitter_px"] > features(clean, 42)["jitter_px"] + 3


def test_speed_curvature_coefficient_on_analytic_ellipse():
    # Constant angular motion on an ellipse satisfies speed = C * curvature^(-1/3).
    times = np.linspace(0, 3000, 181)
    theta = 2 * np.pi * times / 3000
    trail = np.column_stack([times, 300 + 100 * np.cos(theta), 200 + 50 * np.sin(theta)])
    assert features(trail.tolist(), 42)["power_law_beta"] == pytest.approx(1 / 3, abs=.01)


def test_threshold_inclusive_bands_and_disabled_feature(variant):
    values = feature_values()
    values["lag_ms"] = variant["features"]["lag_ms"][0]
    values["err_mean_px"] = variant["features"]["err_mean_px"][1]
    values["jitter_px"] = 100
    values["power_law_beta"] = 100
    result = score_features(values, variant)
    assert result["score"] == .75 and result["pass"] is True
    assert result["features"]["power_law_beta"] == {"value": 100, "band": [.2, .45], "ok": False, "enabled": False}
    stricter = copy.deepcopy(variant)
    stricter["pass_threshold"] = 1
    assert not score_features(values, stricter)["pass"]
    assert score_features(result["features"], variant) == result


@pytest.mark.parametrize("change", [
    {"enabled": []}, {"enabled": ["unknown"]}, {"enabled": ["lag_ms", "lag_ms"]},
    {"pass_threshold": 0}, {"pass_threshold": float("nan")}, {"pass_threshold": 1.1},
    {"features": {}}, {"id": ""},
])
def test_invalid_variant(variant, change):
    variant.update(change)
    with pytest.raises(ValueError, match="invalid variant"):
        score_features(feature_values(), variant)


def test_invalid_bands_and_stored_features(variant):
    invalid = copy.deepcopy(variant)
    invalid["features"]["lag_ms"] = [200, 100]
    with pytest.raises(ValueError, match="invalid variant"):
        score_features(feature_values(), invalid)
    with pytest.raises(ValueError, match="invalid feature"):
        score_features({**feature_values(), "jitter_px": float("inf")}, variant)


def test_forgery_repeatable_and_transplant_preserves_error():
    kwargs = dict(lag_ms=200, noise_px=1.5, submove_hz=3, overshoot=.1)
    first = forge_trail(42, **kwargs)
    assert first == forge_trail(42, **kwargs)
    assert first != forge_trail(42, **kwargs, rng_seed=3)
    source_path, target_path = make_path(42), make_path(7)
    source = [[t, source_path(t)[0] + 4, source_path(t)[1] - 3] for t in np.linspace(0, 3000, 181)]
    output = transplant({"seed": 42, "samples": source}, 7)
    for t, x, y in output:
        tx, ty = target_path(t)
        assert (x - tx, y - ty) == pytest.approx((4, -3), abs=1e-9)


def test_gate_approval_and_device_regression(variant):
    baseline = copy.deepcopy(variant)
    baseline["enabled"] = ["lag_ms"]
    candidate = copy.deepcopy(baseline)
    candidate["id"] = "v2"
    candidate["features"]["lag_ms"] = [180, 300]
    humans = [{"device": device, "features": feature_values(200)} for device in ("mouse", "trackpad", "touch")]
    forgeries = [{"round_id": 1, "features": score_features(feature_values(400), baseline)["features"]}]
    approved = gate(candidate, baseline, humans, forgeries)
    assert approved["verdict"] == "approve_for_review" and approved["reasons"] == []
    assert approved["forgeries_passed"] == {"candidate": 0, "baseline": 1, "total": 1}
    humans[1]["features"]["lag_ms"] = 350
    rejected = gate(candidate, baseline, humans, forgeries)
    assert rejected["verdict"] == "reject"
    assert rejected["humans_rejected"]["trackpad"] == {"total": 1, "candidate": 1, "baseline": 0}
    assert "trackpad" in rejected["reasons"][0]


def test_gate_no_improvement_missing_evidence_and_immutability(variant):
    humans = [{"device": "mouse", "features": feature_values()}]
    forgeries = [{"features": feature_values()}]
    original = copy.deepcopy((variant, humans, forgeries))
    assert gate(variant, variant, humans, forgeries)["verdict"] == "reject"
    assert "no human evidence" in gate(variant, variant, [], forgeries)["reasons"]
    assert "no forgery evidence" in gate(variant, variant, humans, [])["reasons"]
    assert (variant, humans, forgeries) == original


def test_platform_adapter_imports_real_engine(variant):
    # Validate this checkout, including shallow CI clones without remote branches.
    source = (ROOT / "web/engine_adapter.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(ROOT / "web/engine_adapter.py"), "__name__": "adapter_integration_test"}
    exec(compile(source, namespace["__file__"], "exec"), namespace)
    assert namespace["USING_STUBS"] is False
    assert namespace["make_path"] is make_path
    assert namespace["score"] is score
    assert namespace["gate"] is gate
    assert "stub" not in namespace["score"](forge_trail(42), 42, variant)


def test_gate_keeps_baseline_when_all_stored_forgeries_are_blocked(variant):
    baseline = copy.deepcopy(variant)
    baseline["enabled"] = ["lag_ms"]
    baseline["features"]["lag_ms"] = [100, 300]
    candidate = copy.deepcopy(baseline)
    candidate["id"] = "no_improvement"
    humans = [{"device": "mouse", "features": feature_values(200)}]
    forgeries = [{"features": feature_values(0)}]
    result = gate(candidate, baseline, humans, forgeries)
    assert result["verdict"] == "reject"
    assert result["forgeries_passed"] == {"candidate": 0, "baseline": 0, "total": 1}
    assert "baseline already blocks all stored forgeries" in result["reasons"][0]
    assert "keep the active variant" in result["reasons"][0]
