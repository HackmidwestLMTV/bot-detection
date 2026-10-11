"""The adapter must produce contract-shaped results, stubs or real engine."""
import json
import pathlib

import pytest

from web import engine_adapter as ea

FIX = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
V1 = json.loads((FIX / "variant_v1.json").read_text())
SCORE_EX = json.loads((FIX / "score_example.json").read_text())
GATE_EX = json.loads((FIX / "gate_example.json").read_text())


def test_score_shape_matches_fixture():
    pos = ea.make_path(42)
    samples = [[t, *pos(t)] for t in range(0, 3001, 16)]
    r = ea.score(samples, 42, V1)
    assert set(SCORE_EX) <= set(r)
    assert set(r["features"]) == set(SCORE_EX["features"])
    for f in r["features"].values():
        assert set(f) == {"value", "band", "ok", "enabled"}


def test_short_trail_raises():
    with pytest.raises(ValueError):
        ea.score([[0, 300, 200], [500, 301, 201]], 42, V1)


def test_gate_shape_matches_fixture():
    g = ea.gate(V1, V1, [], [])
    assert set(g) == set(GATE_EX)
