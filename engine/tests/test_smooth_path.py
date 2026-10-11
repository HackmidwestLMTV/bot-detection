"""Versioned target motion: geometry, cross-language agreement, and evidence isolation."""
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from engine.calibrate import calibration_report, load_traces
from engine.forger import forge_trail, transplant
from engine.path import make_path
from engine.scorer import features, score

ROOT = Path(__file__).resolve().parents[2]


def baseline():
    return json.loads((ROOT / "contracts/fixtures/variant_v1.json").read_text())


def test_smooth_fixture_and_javascript_parity():
    data = json.loads((ROOT / "contracts/fixtures/path_vectors_smooth_v2.json").read_text())
    script = ("import {makePath} from " + json.dumps((ROOT / "web/static/path.js").as_uri())
              + "; const d=JSON.parse(process.argv[1]); console.log(JSON.stringify(d.vectors.map(v => "
              "v.points.map(([t]) => makePath(v.seed, d.path_version)(t)))));")
    result = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(data)],
                            capture_output=True, text=True, check=True)
    javascript = json.loads(result.stdout)
    for vector, js_points in zip(data["vectors"], javascript):
        path = make_path(vector["seed"], "smooth_v2")
        for (t, x, y), js in zip(vector["points"], js_points):
            assert path(t) == pytest.approx((x, y), abs=data["tolerance_px"])
            assert path(t) == pytest.approx(js, abs=1e-10)


def test_smooth_trajectory_bounds_speed_and_derivative_continuity():
    # Dense 2ms sampling includes former kick times and both challenge endpoints.
    # Speed/acceleration caps derive from max frequency and summed amplitudes.
    times = np.arange(-2, 3003, 2)
    for seed in range(100):
        path = make_path(seed, "smooth_v2")
        xy = np.array([path(t) for t in times])
        assert np.all(xy >= [145, 110]) and np.all(xy <= [455, 290])
        velocity = np.diff(xy, axis=0) / .002
        acceleration = np.diff(velocity, axis=0) / .002
        assert np.linalg.norm(velocity, axis=1).max() < 158
        assert np.linalg.norm(acceleration, axis=1).max() < 139


def test_legacy_default_is_unchanged_and_unknown_versions_fail():
    assert make_path(42)(1000) == make_path(42, "v1")(1000)
    assert make_path(42)(1000) == pytest.approx((103.824, 209.568), abs=.01)
    with pytest.raises(ValueError, match="path_version"):
        make_path(42, "unknown")
    with pytest.raises(ValueError, match="variant"):
        score(forge_trail(42), 42, {**baseline(), "path_version": "unknown"})


@pytest.mark.parametrize("delay", [0, 100, 250, 500])
def test_smooth_forgery_scoring_uses_selected_target(delay):
    trail = forge_trail(42, lag_ms=delay, path_version="smooth_v2")
    assert trail == forge_trail(42, lag_ms=delay, path_version="smooth_v2")
    values = features(trail, 42, "smooth_v2")
    assert values["lag_ms"] == pytest.approx(delay)
    result = score(trail, 42, {**baseline(), "path_version": "smooth_v2"})
    assert result["features"]["err_mean_px"]["value"] == pytest.approx(values["err_mean_px"])
    if not delay:
        assert values["err_mean_px"] < 1e-9
        assert features(trail, 42)["err_mean_px"] > 10


@pytest.mark.parametrize("source_version", ["v1", "smooth_v2"])
def test_transplant_preserves_source_residual_onto_smooth_target(source_version):
    samples = forge_trail(7, noise_px=2, lag_ms=100, path_version=source_version)
    trace = {"seed": 7, "samples": samples}
    if source_version != "v1":
        trace["path_version"] = source_version
    transplanted = transplant(trace, 42, path_version="smooth_v2")
    source, target = make_path(7, source_version), make_path(42, "smooth_v2")
    for original, changed in zip(samples, transplanted):
        t = original[0]
        np.testing.assert_allclose(np.array(changed[1:]) - target(t), np.array(original[1:]) - source(t), atol=1e-10)


def test_calibration_keeps_versions_separate(tmp_path):
    for version in ("v1", "smooth_v2"):
        trace = {"seed": 42, "samples": forge_trail(42, lag_ms=100, noise_px=2, path_version=version),
                 "cohort": "human_test", "tester": {"consent": True}, "device": "mouse", "round_id": None,
                 "presentation_version": "plain_ring_v1"}
        if version != "v1":
            trace["path_version"] = version
        (tmp_path / f"{version}.json").write_text(json.dumps(trace))
    rows, rejected = load_traces(tmp_path)
    assert len(rows) == 1 and rows[0]["file"] == "v1.json" and not rejected
    smooth, rejected = load_traces(tmp_path, "smooth_v2")
    assert len(smooth) == 1 and smooth[0]["file"] == "smooth_v2.json" and not rejected
    assert len(load_traces(tmp_path, None)[0]) == 2
    default = calibration_report(tmp_path, baseline())
    selected = calibration_report(tmp_path, baseline(), path_version="smooth_v2")
    assert default["recordings"] == selected["recordings"] == 1
    assert default["path_version"] == "v1"
    assert selected["path_version"] == selected["candidate"]["path_version"] == "smooth_v2"
