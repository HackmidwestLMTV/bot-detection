"""Use only disposable DATABASE_URL, as with the rest of the web integration suite."""
import json
import io
import uuid
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient

from contracts.research import COLLECTOR_VERSION, CONSENT_VERSION, verify
from engine.ml.attacks import samples
from web import config, db, engine_adapter, limits, research
from web.app import app

try:
    psycopg.connect(config.DATABASE_URL, connect_timeout=2).close()
except Exception:
    pytest.skip("disposable PostgreSQL unavailable", allow_module_level=True)

KEY = "research-api-test-key-not-real"
HEADERS = {"X-Lab-Key": KEY}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LAB_KEY", KEY)
    monkeypatch.setattr(config, "RESEARCH_RECORDINGS_DIR", str(tmp_path))
    limits.reset()
    with TestClient(app) as c:
        db.exec("DELETE FROM research_recordings")
        db.exec("DELETE FROM research_enrollments")
        yield c
        db.exec("DELETE FROM research_recordings")
        db.exec("DELETE FROM research_enrollments")
        # Calibration rows survive the lab's reset by design; remove only this
        # fixture's session namespaces so they cannot contaminate other gates.
        db.exec("""DELETE FROM attempts WHERE challenge_id IN (SELECT id FROM challenges
            WHERE session_id LIKE 'research\\_%%' OR session_id LIKE 'public\\_%%' OR session_id LIKE 'shadow\\_%%')""")
        db.exec("""DELETE FROM challenges WHERE session_id LIKE 'research\\_%%'
            OR session_id LIKE 'public\\_%%' OR session_id LIKE 'shadow\\_%%'""")


def enrolled(client):
    response = client.post("/v1/research/enrollments", json={"participant_id": "participant_test1"}, headers=HEADERS)
    assert response.status_code == 200
    code = response.json()["code"]
    session = "research_" + uuid.uuid4().hex
    ch = client.post("/v1/challenges", json={"session_id": session, "research_code": code,
                                           "research_consent": CONSENT_VERSION})
    assert ch.status_code == 200, ch.text
    return code, session, ch.json()


def submit(client, code, session, ch, **overrides):
    return client.post(f"/v1/challenges/{ch['challenge_id']}/attempt", json={
        "samples": samples(ch["seed"], "lagged_noise"), "cohort": "human_test", "device": "trackpad",
        "presentation_version": ch["presentation_version"], "tester": {"consent": True},
        "session_id": session, "research_code": code, "research_consent": CONSENT_VERSION,
        "collector_version": COLLECTOR_VERSION, **overrides})


def test_enrollment_auth_session_binding_consent_and_export(client):
    assert client.post("/v1/research/enrollments", json={"participant_id": "person_123"}).status_code == 403
    code, session, ch = enrolled(client)
    assert client.post("/v1/challenges", json={"session_id": session + "other", "research_code": code,
                       "research_consent": CONSENT_VERSION}).status_code == 403
    assert submit(client, code, session, ch, research_consent=None).status_code == 422
    assert submit(client, code, session + "other", ch).status_code == 422
    response = submit(client, code, session, ch)
    assert response.status_code == 200 and response.json()["research_recording"] == "saved"
    exported = client.get("/v1/research/export", headers=HEADERS)
    assert exported.headers["cache-control"] == "no-store"
    records = exported.json()["recordings"]
    assert len(records) == 1
    r = verify(records[0], KEY)
    assert r["group_id"] == "participant_test1" and r["device"] == "trackpad"
    assert r["seed"] == ch["seed"] and r["provenance"] == "operator_invite_v1"
    assert "research_code" not in r and "session_id" not in r
    assert client.get("/v1/research/export", params={"key": KEY}).status_code == 403
    status = client.get("/v1/research/status", headers=HEADERS).json()
    assert status["coverage"]["touch"]["status"] == "untested"
    assert status["activation_available"] is False


def test_invitation_keeps_code_in_fragment_and_requires_consent(client):
    response = client.post("/v1/research/enrollments", headers=HEADERS,
                           json={"participant_id": "person_test_phone", "device": "touch"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()
    url = urlsplit(data["tester_url"])
    assert url.query == "tester=1" and data["code"] not in url.query
    assert parse_qs(url.fragment) == {"research": [data["code"]], "device": ["touch"]}
    assert "<svg" in data["qr_svg"] and KEY not in data["tester_url"]
    assert 'xmlns="http://www.w3.org/2000/svg"' in data["qr_svg"]
    assert client.post("/v1/challenges", json={"session_id": "research_invite_no_consent",
                       "research_code": data["code"]}).status_code == 422
    assert client.post("/v1/research/enrollments", headers=HEADERS,
                       json={"participant_id": "person_test_phone", "device": "emulated"}).status_code == 422
    status = client.get("/v1/research/status", headers=HEADERS)
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["mode"] == "shadow_only"
    assert status.json()["retention_hours"] == 72
    page = client.get("/research")
    assert page.status_code == 200 and page.headers["referrer-policy"] == "no-referrer"
    assert KEY not in page.text


def test_unsigned_public_calibration_cannot_enter_research_export(client, monkeypatch):
    monkeypatch.setattr("web.storage.put_trail", lambda *args: None)
    ch = client.post("/v1/challenges", json={"session_id": "public_" + uuid.uuid4().hex}).json()
    response = client.post(f"/v1/challenges/{ch['challenge_id']}/attempt", json={
        "samples": samples(ch["seed"], "lagged_noise"), "cohort": "human_test", "device": "mouse",
        "presentation_version": ch["presentation_version"], "tester": {"consent": True}})
    assert response.status_code == 200
    assert client.get("/v1/research/export", headers=HEADERS).json()["recordings"] == []


def test_missing_changed_and_expired_evidence_and_retention(client):
    code, session, ch = enrolled(client)
    aid = submit(client, code, session, ch).json()["attempt_id"]
    path = research._local_path(aid)
    original = path.read_bytes()
    path.unlink()
    assert client.get("/v1/research/export", headers=HEADERS).status_code == 409
    tampered = json.loads(original)
    tampered["record"]["seed"] += 1
    path.write_text(json.dumps(tampered))
    assert client.get("/v1/research/export", headers=HEADERS).status_code == 409
    path.write_bytes(original)
    db.exec("UPDATE research_recordings SET expires_at=now()-interval '1 second' WHERE id=%s", aid)
    assert client.get("/v1/research/export", headers=HEADERS).json()["recordings"] == []
    research.cleanup()
    assert not path.exists() and not db.one("SELECT 1 FROM research_recordings WHERE id=%s", aid)


def test_expired_exhausted_enrollment_and_storage_failures(client, monkeypatch):
    code, session, ch = enrolled(client)
    db.exec("UPDATE research_enrollments SET remaining=0")
    assert client.post("/v1/challenges", json={"session_id": session, "research_code": code,
                       "research_consent": CONSENT_VERSION}).status_code == 403
    monkeypatch.setattr(research, "save", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
    response = submit(client, code, session, ch)
    assert response.status_code == 200 and response.json()["research_recording"] == "storage_unavailable"
    db.exec("UPDATE research_enrollments SET expires_at=now()-interval '1 second'")
    assert submit(client, code, session, ch).status_code == 403


def test_private_s3_path_uses_same_signed_export_and_cleanup(client, monkeypatch):
    objects = {}
    class S3:
        def put_object(self, **args):
            assert args["ACL"] == "private" and args["Key"].startswith("research/v1/")
            objects[args["Key"]] = args["Body"]
        def get_object(self, **args):
            return {"Body": io.BytesIO(objects[args["Key"]])}
        def delete_object(self, **args):
            objects.pop(args["Key"], None)
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return self
        def paginate(self, **args):
            assert args["Prefix"] == "research/v1/"
            return [{"Contents": []}]
    monkeypatch.setattr(config, "RESEARCH_RECORDINGS_DIR", "")
    monkeypatch.setattr("web.storage.configured", lambda: True)
    monkeypatch.setattr("web.storage._s3", lambda: S3())
    code, session, ch = enrolled(client)
    aid = submit(client, code, session, ch).json()["attempt_id"]
    exported = client.get("/v1/research/export", headers=HEADERS).json()["recordings"]
    assert verify(exported[0], KEY)["record_id"] == aid
    db.exec("UPDATE research_recordings SET expires_at=now()-interval '1 second'")
    research.cleanup()
    assert objects == {}


@pytest.mark.parametrize("mode", ["would_fail", "would_pass", "broken_artifact", "exception"])
def test_shadow_never_changes_active_decision_or_stores_ordinary_raw(client, monkeypatch, mode):
    monkeypatch.setattr(config, "SHADOW_MODEL_DIR", "missing-artifact")
    if mode == "exception":
        monkeypatch.setattr(engine_adapter, "shadow", lambda *args: (_ for _ in ()).throw(RuntimeError("shadow failed")))
    elif mode != "broken_artifact":
        monkeypatch.setattr(engine_adapter, "shadow", lambda *args: {"status": "scored", "would_pass": mode == "would_pass"})
    for passed in (True, False):
        monkeypatch.setattr(engine_adapter, "score", lambda *args: {"pass": passed, "score": float(passed), "features": {}})
        ch = client.post("/v1/challenges", json={"session_id": "shadow_" + uuid.uuid4().hex}).json()
        r = client.post(f"/v1/challenges/{ch['challenge_id']}/attempt", json={"samples": [[0, 1, 2], [1500, 2, 3]]}).json()
        assert bool(r["token"]) == passed and r["result"]["pass"] == passed
        row = db.one("SELECT trail_key,shadow_result FROM attempts WHERE id=%s", r["attempt_id"])
        assert row["trail_key"] is None
        assert (row["shadow_result"] is None) == (mode == "exception")
    assert client.get("/v1/research/export", headers=HEADERS).json()["recordings"] == []
