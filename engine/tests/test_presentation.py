"""Synthetic presentation tests never write to genuine human fixtures."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from engine.calibrate import load_traces, calibration_report
from engine.forger import forge_trail
from engine.labserver import create_lab_app

ROOT = Path(__file__).resolve().parents[2]


def variant():
    return json.loads((ROOT / "contracts/fixtures/variant_v1.json").read_text())


def test_calibration_never_counts_legacy_display_as_current(tmp_path):
    legacy = {"seed": 42, "samples": forge_trail(42), "device": "mouse", "cohort": "human_test",
              "round_id": None, "tester": {"consent": True}}
    (tmp_path / "legacy.json").write_text(json.dumps(legacy))
    (tmp_path / "current.json").write_text(json.dumps({**legacy, "presentation_version": "plain_ring_v1"}))
    rows, rejected = load_traces(tmp_path)
    assert not rejected and [row["file"] for row in rows] == ["current.json"]
    assert len(load_traces(tmp_path, None, None)[0]) == 2  # Explicit transplant input.
    report = calibration_report(tmp_path, variant())
    assert report["recordings"] == 1 and report["presentation_version"] == "plain_ring_v1"
    assert report["candidate"]["presentation_version"] == "plain_ring_v1"


def test_disposable_lab_filters_both_human_and_attack_display_cohorts():
    values = {name: sum(band) / 2 for name, band in variant()["features"].items()}
    legacy = {"attempt_id": "legacy", "device": "mouse", "features": values}
    current = {**legacy, "attempt_id": "current", "presentation_version": "plain_ring_v1"}
    app = create_lab_app(humans=[legacy, current], forgeries=[{**legacy, "round_id": "r"}])
    with TestClient(app) as client:
        health = client.get("/healthz").json()
        assert health["human_records"] == 1 and health["excluded_legacy_human_traces"] == 1
        assert health["human_traces"]["touch"] == 0
        auth = {"X-Lab-Key": "dev"}
        assert client.get("/v1/lab/forgeries", headers=auth).json() == []
        candidate = {**variant(), "id": "test-proposal"}
        client.post("/v1/variants", headers=auth, json=candidate).raise_for_status()
        gate = client.post("/v1/lab/gate", headers=auth, json={"candidate_id": candidate["id"]}).json()
        assert gate["verdict"] == "reject" and "no forgery evidence" in gate["reasons"]
        assert client.post("/v1/variants", headers=auth, json={**candidate, "id": "legacy-rule",
                           "presentation_version": "legacy"}).status_code == 422


def test_disposable_lab_scores_open_challenge_with_issued_rule():
    baseline = variant()
    values = {name: sum(band) / 2 for name, band in baseline["features"].items()}
    app = create_lab_app(variant=baseline, humans=[{"attempt_id": "synthetic-human-fixture", "device": "mouse",
                        "features": {**values, "lag_ms": 250}, "presentation_version": "plain_ring_v1"}],
                        forgeries=[{"attempt_id": "synthetic-attack-fixture", "round_id": "r",
                                    "features": {**values, "lag_ms": 150}, "presentation_version": "plain_ring_v1"}])
    auth = {"X-Lab-Key": "dev"}
    with TestClient(app) as client:
        issued = client.post("/v1/challenges", headers=auth, json={"session_id": "test"}).json()
        candidate = {**variant(), "id": "updated", "enabled": ["lag_ms"], "pass_threshold": 1}
        candidate["features"]["lag_ms"] = [200, 450]
        client.post("/v1/variants", headers=auth, json=candidate).raise_for_status()
        gate = client.post("/v1/lab/gate", headers=auth, json={"candidate_id": "updated"}).json()
        aid = client.post("/v1/lab/approvals", headers=auth, json={"variant_id": "updated",
                           "interrupt_id": "test", "gate": gate}).json()["approval_id"]
        client.post(f"/v1/lab/approvals/{aid}/decide", headers=auth, json={"approve": True}).raise_for_status()
        client.post("/v1/variants/updated/activate", headers=auth).raise_for_status()
        new = client.post("/v1/challenges", headers=auth, json={"session_id": "next"}).json()
        assert new["variant_id"] == "updated"
        response = client.post(f"/v1/challenges/{issued['challenge_id']}/attempt", headers=auth,
                               json={"samples": [[0, 1, 2], [3000, 3, 4]], "device": "mouse",
                                     "pointer_type": "mouse", "cohort": "red", "round_id": "test"})
        assert response.status_code == 200
        assert response.json()["result"]["variant"] == baseline["id"]
        assert issued["presentation_version"] == app.state.attempts[0]["presentation_version"] == "plain_ring_v1"
