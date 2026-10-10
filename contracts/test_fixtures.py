"""Contract tests. Both people run `pytest contracts/` before every push.

These check the fixtures themselves, plus web/static/path.js against path_vectors.json.
Engine-side checks skip until engine/ is importable.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "contracts" / "fixtures"
FEATURES = {"lag_ms", "err_mean_px", "submoves_per_s", "jitter_px", "power_law_beta"}
AGENTS = {"red", "blue", "gate", "system"}
EVENT_TYPES = {"round_started", "tool_call", "tool_result", "attempt_scored", "round_report",
               "gate_result", "approval_needed", "variant_activated", "error"}


def load(name):
    return json.loads((FIX / name).read_text())


def events():
    return [json.loads(line) for line in (FIX / "events_example.jsonl").read_text().splitlines() if line.strip()]


def check_gate_shape(g):
    assert set(g) == {"candidate", "baseline", "verdict", "humans_rejected", "forgeries_passed", "reasons"}
    assert g["verdict"] in {"approve_for_review", "reject"}
    for grp in g["humans_rejected"].values():
        assert set(grp) == {"total", "candidate", "baseline"}
    assert set(g["forgeries_passed"]) == {"candidate", "baseline", "total"}


def gate_rule(g):
    worse = any(v["candidate"] > v["baseline"] for v in g["humans_rejected"].values())
    fewer = g["forgeries_passed"]["candidate"] < g["forgeries_passed"]["baseline"]
    return "approve_for_review" if (not worse and fewer) else "reject"


def test_variant_v1():
    v = load("variant_v1.json")
    assert v["id"] == "v1" and v["parent"] is None
    assert set(v["features"]) == FEATURES
    assert set(v["enabled"]) <= FEATURES
    assert 0 < v["pass_threshold"] <= 1
    for lo, hi in v["features"].values():
        assert lo < hi


def test_score_example():
    s = load("score_example.json")
    assert set(s) >= {"score", "pass", "variant", "features"}
    assert set(s["features"]) == FEATURES
    for f in s["features"].values():
        assert set(f) == {"value", "band", "ok", "enabled"}
        assert f["ok"] == (f["band"][0] <= f["value"] <= f["band"][1])


def test_gate_example_obeys_rule():
    g = load("gate_example.json")
    check_gate_shape(g)
    assert g["verdict"] == gate_rule(g)
    assert (g["verdict"] == "reject") == bool(g["reasons"])


def test_events_example():
    evs = events()
    assert evs, "events_example.jsonl is empty"
    for ev in evs:
        assert set(ev) == {"run_id", "agent", "type", "ts", "data"}
        assert ev["agent"] in AGENTS and ev["type"] in EVENT_TYPES
        d = ev["data"]
        if ev["type"] == "tool_call":
            assert set(d) == {"tool", "args"}
        elif ev["type"] == "tool_result":
            assert set(d) == {"tool", "summary"} and len(d["summary"]) <= 200
        elif ev["type"] == "attempt_scored":
            assert set(d) == {"attempt_id", "score", "pass", "failed"}
            assert set(d["failed"]) <= FEATURES
        elif ev["type"] == "gate_result":
            check_gate_shape(d)
            assert d["verdict"] == gate_rule(d)
        elif ev["type"] == "approval_needed":
            assert set(d) == {"approval_id", "variant_id", "gate"}
        elif ev["type"] == "round_report":
            assert set(d) >= {"round", "agent", "attempts", "passed", "best_params", "what_changed", "evidence"}
    types = {ev["type"] for ev in evs}
    assert {"gate_result", "approval_needed", "variant_activated"} <= types


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_path_js_matches_vectors():
    data = load("path_vectors.json")
    script = (
        "import {makePath} from " + json.dumps((ROOT / "web/static/path.js").as_uri()) + ";"
        "const d = JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(d.vectors.map(v => v.points.map(([t]) => makePath(v.seed)(t)))));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(data)],
                         capture_output=True, text=True, check=True).stdout
    got = json.loads(out)
    for vec, pts in zip(data["vectors"], got):
        for (t, ex, ey), (x, y) in zip(vec["points"], pts):
            assert abs(x - ex) <= data["tolerance_px"] and abs(y - ey) <= data["tolerance_px"], (vec["seed"], t)


def test_engine_path_matches_vectors():
    path = pytest.importorskip("engine.path")
    data = load("path_vectors.json")
    for vec in data["vectors"]:
        pos = path.make_path(vec["seed"])
        for t, ex, ey in vec["points"]:
            x, y = pos(t)
            assert abs(x - ex) <= data["tolerance_px"] and abs(y - ey) <= data["tolerance_px"], (vec["seed"], t)
