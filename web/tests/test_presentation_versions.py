"""Display cohorts and issued policies stay bound across review and activation."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from web import config

try:
    psycopg.connect(config.DATABASE_URL, connect_timeout=2).close()
except Exception:
    pytest.skip("disposable PostgreSQL required", allow_module_level=True)

from fastapi.testclient import TestClient
from web import db, engine_adapter, storage
from web.app import app

LAB = {"X-Lab-Key": config.LAB_KEY}
V1 = json.loads((Path(__file__).resolve().parents[2] / "contracts/fixtures/variant_v1.json").read_text())
FEATS = {name: (low + high) / 2 for name, (low, high) in V1["features"].items()}


@pytest.fixture
def client():
    with TestClient(app) as client:
        client.post("/v1/lab/reset", headers=LAB).raise_for_status()
        yield client


def insert_evidence(aid, cohort, values, presentation="plain_ring_5s_v2"):
    db.exec("""INSERT INTO attempts(id, cohort, device, features, path_version, presentation_version)
               VALUES (%s, %s, 'mouse', %s, %s, %s)""",
            aid, cohort, db.Json(values), config.PATH_VERSION, presentation)


def test_legacy_display_is_not_current_human_or_attack_evidence(client):
    legacy, legacy_red, current = (uuid4().hex for _ in range(3))
    try:
        # Missing display metadata defaults to legacy, including rows in the same path cohort.
        db.exec("INSERT INTO attempts(id, cohort, device, features, path_version) VALUES (%s, 'human_test', 'mouse', %s, %s)",
                legacy, db.Json(FEATS), config.PATH_VERSION)
        insert_evidence(legacy_red, "red", FEATS, "legacy")
        insert_evidence(current, "human_test", FEATS)
        db.init_schema()  # Repeat startup cannot relabel historical rows.
        assert db.one("SELECT presentation_version FROM attempts WHERE id=%s", legacy)["presentation_version"] == "legacy"
        humans = client.get("/v1/lab/human-features", headers=LAB).json()
        assert current in {row["attempt_id"] for row in humans}
        assert legacy not in {row["attempt_id"] for row in humans}
        assert legacy_red not in {row["attempt_id"] for row in client.get("/v1/lab/forgeries", headers=LAB).json()}
        health = client.get("/healthz").json()
        assert health["presentation_version"] == "plain_ring_5s_v2"
        assert health["human_traces"]["total"] == len(humans)
        assert health["excluded_legacy_human_traces"] >= 1
    finally:
        for aid in (legacy, legacy_red, current):
            db.exec("DELETE FROM attempts WHERE id=%s", aid)


def test_attempt_uses_issued_snapshot_and_server_display_even_after_reset(client, monkeypatch):
    snapshot = {**deepcopy(V1), "id": "issued_policy"}
    snapshot["enabled"] = ["lag_ms"]
    db.exec("UPDATE variants SET status='retired' WHERE status='active'")
    db.exec("INSERT INTO variants(id, config, status) VALUES (%s, %s, 'active')", snapshot["id"], db.Json(snapshot))
    issued = client.post("/v1/challenges", headers=LAB, json={"session_id": uuid4().hex}).json()
    client.post("/v1/lab/reset", headers=LAB).raise_for_status()  # Deletes the issued variant.
    new = client.post("/v1/challenges", headers=LAB, json={"session_id": uuid4().hex}).json()
    assert issued["variant_id"] == "issued_policy" and new["variant_id"] == "v1"
    observed, saved = [], []
    def score(samples, seed, variant):
        observed.append(variant)
        return {"features": FEATS, "score": 1, "pass": True, "variant": variant["id"]}
    monkeypatch.setattr(engine_adapter, "score", score)
    monkeypatch.setattr(storage, "put_trail", lambda aid, trail: saved.append(trail) or "test-only")
    monkeypatch.setattr(config, "PRESENTATION_VERSION", "changed_after_issue")
    result = client.post(f"/v1/challenges/{issued['challenge_id']}/attempt", json={
        "samples": [[0, 1, 2], [3000, 3, 4]], "device": "touch", "cohort": "human_test",
        "tester": {"consent": True}, "presentation_version": issued["presentation_version"]}).json()
    assert observed == [{**snapshot, "path_version": issued["path_version"]}]
    assert saved[0]["presentation_version"] == "plain_ring_5s_v2"
    row = db.one("SELECT presentation_version FROM attempts WHERE id=%s", result["attempt_id"])
    assert row["presentation_version"] == "plain_ring_5s_v2"


@pytest.mark.skipif(engine_adapter.USING_STUBS, reason="real gate required")
def test_display_change_invalidates_approval_and_legacy_cannot_supply_gate_evidence(client, monkeypatch):
    ids = [uuid4().hex for _ in range(2)]
    candidate = {**deepcopy(V1), "id": uuid4().hex, "enabled": ["lag_ms"], "pass_threshold": 1}
    candidate["features"]["lag_ms"] = [200, 450]
    human = {**FEATS, "lag_ms": 250}
    forged = {**FEATS, "lag_ms": 150}
    try:
        insert_evidence(ids[0], "human_test", human)
        insert_evidence(ids[1], "red", forged)
        client.post("/v1/variants", headers=LAB, json=candidate).raise_for_status()
        aid = client.post("/v1/lab/approvals", headers=LAB, json={"variant_id": candidate["id"]}).json()["approval_id"]
        client.post(f"/v1/lab/approvals/{aid}/decide", headers=LAB, json={"approve": True}).raise_for_status()
        # Even identical rule/results/evidence must fingerprint the display identity.
        db.exec("UPDATE attempts SET presentation_version='changed' WHERE id IN (%s, %s)", *ids)
        db.exec("UPDATE variants SET config=jsonb_set(config, '{presentation_version}', '\"changed\"') WHERE id=%s", candidate["id"])
        monkeypatch.setattr(config, "PRESENTATION_VERSION", "changed")
        assert client.post(f"/v1/variants/{candidate['id']}/activate", headers=LAB).status_code == 403
        db.exec("UPDATE attempts SET presentation_version='legacy' WHERE id IN (%s, %s)", *ids)
        gate = client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": candidate["id"]}).json()
        assert gate["verdict"] == "reject" and "no human evidence" in gate["reasons"]
        assert "no forgery evidence" in gate["reasons"]
    finally:
        for aid in ids:
            db.exec("DELETE FROM attempts WHERE id=%s", aid)


def test_candidate_cannot_select_legacy_presentation(client):
    candidate = {**V1, "id": uuid4().hex, "presentation_version": "legacy"}
    assert client.post("/v1/variants", headers=LAB, json=candidate).status_code == 422


@pytest.mark.parametrize("display", [None, "legacy", "spoofed"])
def test_stale_tester_cannot_record_current_evidence(client, display):
    issued = client.post("/v1/challenges", headers=LAB, json={"session_id": uuid4().hex}).json()
    response = client.post(f"/v1/challenges/{issued['challenge_id']}/attempt", json={
        "samples": [[0, 1, 2], [3000, 3, 4]], "device": "mouse", "cohort": "human_test",
        "tester": {"consent": True}, "presentation_version": display})
    assert response.status_code == 409
    assert db.one("SELECT 1 FROM attempts WHERE challenge_id=%s", issued["challenge_id"]) is None


@pytest.mark.parametrize("cohort,consent,expected_uploads", [
    ("organic", True, 0), ("human_test", False, 0), ("human_test", "true", 0), ("human_test", True, 1),
])
def test_raw_storage_requires_tester_cohort_and_literal_consent(client, monkeypatch, cohort, consent, expected_uploads):
    issued = client.post("/v1/challenges", headers=LAB, json={"session_id": uuid4().hex}).json()
    saved = []
    monkeypatch.setattr(storage, "put_trail", lambda aid, trail: saved.append(trail) or "test-only")
    monkeypatch.setattr(engine_adapter, "score", lambda *args: {"features": FEATS, "score": 1, "pass": True})
    response = client.post(f"/v1/challenges/{issued['challenge_id']}/attempt", json={
        "samples": [[0, 1, 2], [3000, 3, 4]], "device": "mouse", "cohort": cohort,
        "tester": {"consent": consent}, "presentation_version": issued["presentation_version"]})
    assert response.status_code == 200
    assert len(saved) == expected_uploads
    stored = db.one("SELECT features, trail_key FROM attempts WHERE id=%s", response.json()["attempt_id"])
    assert stored["features"] == FEATS and "samples" not in stored["features"]
    assert bool(stored["trail_key"]) == bool(expected_uploads)
