"""Challenge path versions survive configuration changes without relabelling evidence."""
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


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


@pytest.mark.skipif(engine_adapter.USING_STUBS, reason="real versioned scorer required")
@pytest.mark.parametrize("issued_version,next_version", [("v1", "smooth_v2"), ("smooth_v2", "v1")])
def test_challenge_pins_path_for_scoring_evidence_and_storage(client, monkeypatch, issued_version, next_version):
    monkeypatch.setattr(config, "PATH_VERSION", issued_version)
    challenge = client.post("/v1/challenges", headers=LAB, json={"session_id": uuid4().hex}).json()
    assert challenge["path_version"] == issued_version
    assert db.one("SELECT path_version FROM challenges WHERE id=%s", challenge["challenge_id"])["path_version"] == issued_version
    monkeypatch.setattr(config, "PATH_VERSION", next_version)
    path = engine_adapter.make_path(challenge["seed"], issued_version)
    samples = [[t, *path(t)] for t in (i * 1000 / 60 for i in range(181))]
    stored = []
    monkeypatch.setattr(storage, "put_trail", lambda aid, trail: stored.append(trail) or "test-only")
    response = client.post(f"/v1/challenges/{challenge['challenge_id']}/attempt", json={
        "samples": samples, "device": "mouse", "cohort": "human_test", "tester": {"consent": True},
        "path_version": next_version, "seed": 0})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["result"]["features"]["err_mean_px"]["value"] < 0.01
    assert db.one("SELECT path_version FROM attempts WHERE id=%s", result["attempt_id"])["path_version"] == issued_version
    assert stored[0]["path_version"] == issued_version and stored[0]["seed"] == challenge["seed"]
    assert stored[0]["challenge_id"] == challenge["challenge_id"]


def test_legacy_rows_keep_v1_and_are_excluded_from_smooth_evidence(client, monkeypatch):
    monkeypatch.setattr(config, "PATH_VERSION", "smooth_v2")
    legacy_human, legacy_red, current_human = (uuid4().hex for _ in range(3))
    try:
        for aid, cohort in [(legacy_human, "human_test"), (legacy_red, "red")]:
            # Column defaults model pre-versioning records; no backfill to smooth_v2.
            db.exec("INSERT INTO attempts(id, cohort, device, features) VALUES (%s, %s, 'mouse', %s)", aid, cohort, db.Json(FEATS))
        db.exec("INSERT INTO attempts(id, cohort, device, features, path_version) VALUES (%s, 'human_test', 'touch', %s, 'smooth_v2')",
                current_human, db.Json(FEATS))
        assert db.one("SELECT path_version FROM attempts WHERE id=%s", legacy_human)["path_version"] == "v1"
        humans = client.get("/v1/lab/human-features", headers=LAB).json()
        assert legacy_human not in [row["attempt_id"] for row in humans]
        assert current_human in [row["attempt_id"] for row in humans]
        assert legacy_red not in [row["attempt_id"] for row in client.get("/v1/lab/forgeries", headers=LAB).json()]
        health = client.get("/healthz").json()
        assert health["path_version"] == "smooth_v2"
        assert health["human_traces"]["total"] == len(humans)
        assert health["excluded_legacy_human_traces"] >= 1
        if not engine_adapter.USING_STUBS:
            candidate = {**V1, "id": uuid4().hex}
            assert client.post("/v1/variants", headers=LAB, json=candidate).status_code == 200
            gate = client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": candidate["id"]})
            assert gate.status_code == 200, gate.text
            assert sum(group["total"] for group in gate.json()["humans_rejected"].values()) == len(humans)
    finally:
        for aid in (legacy_human, legacy_red, current_human):
            db.exec("DELETE FROM attempts WHERE id=%s", aid)


def test_candidate_cannot_select_another_path(client, monkeypatch):
    monkeypatch.setattr(config, "PATH_VERSION", "smooth_v2")
    candidate = {**V1, "id": uuid4().hex, "path_version": "v1"}
    assert client.post("/v1/variants", headers=LAB, json=candidate).status_code == 422
    assert db.one("SELECT 1 FROM variants WHERE id=%s", candidate["id"]) is None
    assert client.get("/v1/variants/active", headers=LAB).json()["path_version"] == "smooth_v2"
