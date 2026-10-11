"""Five-second target coverage, smoothness, parity and fresh evidence isolation."""
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from engine.calibrate import load_traces
from engine.forger import forge_trail
from engine.path import DEFAULT_PATH_VERSION, make_path
from engine.scorer import features
from contracts.presentation import PRESENTATION_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_roaming_fixture_and_javascript_parity():
    data = json.loads((ROOT / "contracts/fixtures/path_vectors_roaming_v3.json").read_text())
    script = ("import {makePath} from " + json.dumps((ROOT / "web/static/path.js").as_uri())
              + "; const d=JSON.parse(process.argv[1]); console.log(JSON.stringify(d.vectors.map(v => "
              "v.points.map(([t]) => makePath(v.seed, d.path_version)(t)))));")
    result = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(data)],
                            capture_output=True, text=True, check=True)
    javascript = json.loads(result.stdout)
    assert data["path_version"] == DEFAULT_PATH_VERSION == "roaming_v3"
    for vector, js_points in zip(data["vectors"], javascript):
        path = make_path(vector["seed"], data["path_version"])
        for (t, x, y), js in zip(vector["points"], js_points):
            assert path(t) == pytest.approx((x, y), abs=data["tolerance_px"])
            assert path(t) == pytest.approx(js, abs=1e-10)


def test_thousand_roaming_paths_cover_area_with_bounded_motion():
    # Include negatives/high unsigned seeds, endpoint neighborhoods, and dense
    # 5ms samples. Geometry caps are analytic; distance/coverage are regressions.
    seeds = list(range(1000)) + [-1, 2 ** 31, 2 ** 32 - 1]
    starts = []
    for seed in seeds:
        path = make_path(seed, "roaming_v3")
        xy = np.array([path(t) for t in range(-5, 5006, 5)])
        assert np.all(xy >= [84, 84]) and np.all(xy <= [516, 316])
        velocity = np.diff(xy, axis=0) / .005
        acceleration = np.diff(velocity, axis=0) / .005
        assert np.linalg.norm(velocity, axis=1).max() < 256
        assert np.linalg.norm(acceleration, axis=1).max() < 282
        shown = xy[1:-1]
        distance = np.linalg.norm(np.diff(shown, axis=0), axis=1).sum()
        assert 600 < distance < 1000
        assert np.all(np.ptp(shown, axis=0) > [295, 145])
        starts.append(shown[0])
    assert np.all(np.ptp(starts, axis=0) > [400, 210])
    assert len({tuple(p) for p in starts[:1000]}) == 1000


@pytest.mark.parametrize("delay", [0, 100, 250, 500])
def test_roaming_forgery_uses_issued_path(delay):
    trail = forge_trail(42, lag_ms=delay, path_version="roaming_v3")
    assert trail[-1][0] == 5000
    result = features(trail, 42, "roaming_v3")
    assert result["lag_ms"] == pytest.approx(delay)
    if not delay:
        assert result["err_mean_px"] < 1e-9
        assert features(trail, 42, "smooth_v2")["err_mean_px"] > 100


def test_calibration_does_not_mix_old_paths_with_roaming(tmp_path):
    for version in ("v1", "smooth_v2", "roaming_v3"):
        trace = {"seed": 42, "samples": forge_trail(42, path_version=version),
                 "path_version": version, "presentation_version": PRESENTATION_VERSION,
                 "cohort": "human_test", "tester": {"consent": True}, "device": "mouse", "round_id": None}
        (tmp_path / (version + ".json")).write_text(json.dumps(trace))
    rows, rejected = load_traces(tmp_path, "roaming_v3")
    assert not rejected
    assert len(rows) == 1 and rows[0]["file"] == "roaming_v3.json"
