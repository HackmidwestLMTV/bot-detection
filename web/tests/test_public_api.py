"""Public API end to end: challenge -> attempt -> token -> reserve, PoW, limits.

Needs Postgres at DATABASE_URL; skips if unreachable. Uses the stub scorer behaviour
(passes any trail >= 1 s); with the real engine the scorer-dependent tests are skipped.
"""
import uuid

import psycopg
import pytest

from web import config

try:
    psycopg.connect(config.DATABASE_URL, connect_timeout=2).close()
except Exception:  # noqa: BLE001
    pytest.skip(f"Postgres not reachable at {config.DATABASE_URL}", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from web import db, limits  # noqa: E402
from web.app import app  # noqa: E402
from web.engine_adapter import USING_STUBS  # noqa: E402
from web.pow import brute_force, digest, leading_zero_bits  # noqa: E402

LAB = {"X-Lab-Key": config.LAB_KEY}
stub_only = pytest.mark.skipif(not USING_STUBS, reason="relies on the stub scorer passing any >=1 s trail")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_limits():
    limits.reset()
    yield
    limits.reset()


@pytest.fixture(autouse=True)
def _low_pow(monkeypatch):
    monkeypatch.setattr(config, "POW_BITS", 8)


def sid():
    return f"s_{uuid.uuid4().hex[:12]}"


def trail(ms=1500, cohort="organic", **extra):
    samples = [[t, 300.0 + t / 10, 200.0] for t in range(0, ms + 1, 16)]
    return {"samples": samples, "device": "mouse", "pointer_type": "mouse",
            "cohort": cohort, "round_id": None, **extra}


def challenge(client, s, headers=None):
    r = client.post("/v1/challenges", json={"session_id": s}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["challenge_id"]


def pow_token(client, s):
    r = client.post("/v1/pow", json={"session_id": s})
    assert r.status_code == 200
    p = r.json()
    assert set(p) == {"pow_id", "nonce", "bits", "expires_in_s"} and p["bits"] == 8 and p["expires_in_s"] == 120
    r = client.post(f"/v1/pow/{p['pow_id']}/solve", json={"counter": brute_force(p["nonce"], p["bits"])})
    assert r.status_code == 200, r.text
    assert r.json()["token"].startswith("tok_")
    return p, r.json()["token"]


def reserve(client, token, s):
    return client.post("/demo/tickets/reserve", json={"token": token, "session_id": s})


@stub_only
def test_happy_path_then_reuse(client):
    s = sid()
    cid = challenge(client, s)
    r = client.post(f"/v1/challenges/{cid}/attempt", json=trail())
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"result", "token", "fallback", "attempt_id"}
    assert body["result"]["pass"] is True and body["fallback"] is None
    assert body["token"].startswith("tok_")
    feats = db.one("SELECT features FROM attempts WHERE id=%s", body["attempt_id"])["features"]
    assert all(not isinstance(v, dict) for v in feats.values()) and "lag_ms" in feats

    r = reserve(client, body["token"], s)
    assert r.status_code == 200 and r.json()["reservation_id"].startswith("res_")
    r = reserve(client, body["token"], s)
    assert r.status_code == 409 and r.json() == {"reason": "used"}


def test_wrong_session(client):
    s = sid()
    _, tok = pow_token(client, s)
    r = reserve(client, tok, sid())
    assert r.status_code == 409 and r.json() == {"reason": "wrong_session"}
    assert reserve(client, tok, s).status_code == 200  # still usable by its owner


def test_unknown_token_is_used(client):
    r = reserve(client, "tok_nope", sid())
    assert r.status_code == 409 and r.json() == {"reason": "used"}


def test_expired(client):
    s = sid()
    _, tok = pow_token(client, s)
    db.exec("UPDATE tokens SET expires_at = now() - interval '1 second' WHERE id=%s", tok)
    r = reserve(client, tok, s)
    assert r.status_code == 409 and r.json() == {"reason": "expired"}


def test_red_needs_key_and_never_gets_token(client):
    s = sid()
    cid = challenge(client, s)
    r = client.post(f"/v1/challenges/{cid}/attempt", json=trail(cohort="red", round_id="r1"))
    assert r.status_code == 403
    r = client.post(f"/v1/challenges/{cid}/attempt", json=trail(cohort="red", round_id="r1"),
                    headers={"X-Lab-Key": "wrong"})
    assert r.status_code == 403
    r = client.post(f"/v1/challenges/{cid}/attempt", json=trail(cohort="red", round_id="r1"), headers=LAB)
    assert r.status_code == 200, r.text
    assert r.json()["token"] is None
    row = db.one("SELECT cohort, round_id FROM attempts WHERE id=%s", r.json()["attempt_id"])
    assert row == {"cohort": "red", "round_id": "r1"}


def test_human_test_without_s3_stores_no_trail(client):
    s = sid()
    cid = challenge(client, s)
    r = client.post(f"/v1/challenges/{cid}/attempt",
                    json=trail(cohort="human_test", tester={"consent": True, "nondominant_hand": True}))
    assert r.status_code == 200, r.text
    row = db.one("SELECT trail_key, nondominant_hand FROM attempts WHERE id=%s", r.json()["attempt_id"])
    assert row["nondominant_hand"] is True
    if not config.S3_ENDPOINT:
        assert row["trail_key"] is None


def test_human_test_requires_a_real_device(client):
    """engine.gate() raises on a human_test row with a bad device, and /v1/lab/reset
    keeps human traces, so such a row would break the gate permanently."""
    for bad in (None, "phone", "", "Mouse"):
        cid = challenge(client, sid())
        t = trail(cohort="human_test", tester={"consent": True})
        t["device"] = bad
        r = client.post(f"/v1/challenges/{cid}/attempt", json=t)
        assert r.status_code == 422, f"device={bad!r} gave {r.status_code}"
    cid = challenge(client, sid())
    t = trail(cohort="human_test", tester={"consent": True})
    del t["device"]
    assert client.post(f"/v1/challenges/{cid}/attempt", json=t).status_code == 422
    assert db.one("SELECT 1 FROM attempts WHERE cohort='human_test' AND device IS NULL") is None


def test_short_trail_422(client):
    cid = challenge(client, sid())
    r = client.post(f"/v1/challenges/{cid}/attempt", json=trail(ms=500))
    assert r.status_code == 422


def test_bad_samples_422(client):
    cid = challenge(client, sid())
    r = client.post(f"/v1/challenges/{cid}/attempt", json={"samples": [[0, "x", 1]], "cohort": "organic"})
    assert r.status_code == 422


def test_missing_or_expired_challenge_404(client):
    assert client.post("/v1/challenges/ch_nope/attempt", json=trail()).status_code == 404
    cid = challenge(client, sid())
    db.exec("UPDATE challenges SET expires_at = now() - interval '1 second' WHERE id=%s", cid)
    assert client.post(f"/v1/challenges/{cid}/attempt", json=trail()).status_code == 404


def test_sixth_attempt_429(client):
    cid = challenge(client, sid())
    for _ in range(5):
        assert client.post(f"/v1/challenges/{cid}/attempt", json=trail()).status_code == 200
    assert client.post(f"/v1/challenges/{cid}/attempt", json=trail()).status_code == 429


def test_pow_flow(client):
    s = sid()
    p, tok = pow_token(client, s)
    assert reserve(client, tok, s).status_code == 200
    # reusing a solved pow
    r = client.post(f"/v1/pow/{p['pow_id']}/solve", json={"counter": brute_force(p["nonce"], p["bits"])})
    assert r.status_code == 400


def test_pow_bad_counter(client):
    r = client.post("/v1/pow", json={"session_id": sid()})
    p = r.json()
    good = brute_force(p["nonce"], p["bits"])
    bad = next(c for c in range(good + 1, good + 10_000)
               if leading_zero_bits(digest(p["nonce"], c)) < p["bits"])
    assert client.post(f"/v1/pow/{p['pow_id']}/solve", json={"counter": bad}).status_code == 400
    assert client.post(f"/v1/pow/{p['pow_id']}/solve", json={}).status_code == 400
    assert client.post("/v1/pow/pow_nope/solve", json={"counter": 1}).status_code == 400
    # the pow is still solvable after a bad guess
    assert client.post(f"/v1/pow/{p['pow_id']}/solve", json={"counter": good}).status_code == 200


def test_expired_pow_400(client):
    p = client.post("/v1/pow", json={"session_id": sid()}).json()
    db.exec("UPDATE pow SET expires_at = now() - interval '1 second' WHERE id=%s", p["pow_id"])
    r = client.post(f"/v1/pow/{p['pow_id']}/solve", json={"counter": brute_force(p["nonce"], p["bits"])})
    assert r.status_code == 400


def test_reservation_cap(client):
    s = sid()
    toks = [pow_token(client, s)[1] for _ in range(3)]
    assert reserve(client, toks[0], s).status_code == 200
    assert reserve(client, toks[1], s).status_code == 200
    r = reserve(client, toks[2], s)
    assert r.status_code == 409 and r.json() == {"reason": "cap"}
    # cap consumes the token
    assert reserve(client, toks[2], s).json() == {"reason": "used"}


def test_challenge_rate_limit(client):
    s = sid()
    for _ in range(10):
        challenge(client, s)
    assert client.post("/v1/challenges", json={"session_id": s}).status_code == 429
    # other sessions on the same IP are unaffected; lab key bypasses
    challenge(client, sid())
    challenge(client, s, headers=LAB)


def test_ip_ceiling_and_forwarded_for(client, monkeypatch):
    monkeypatch.setattr(config, "IP_PER_MIN", 3)
    h = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
    for _ in range(3):
        assert client.post("/v1/challenges", json={"session_id": sid()}, headers=h).status_code == 200
    assert client.post("/v1/challenges", json={"session_id": sid()}, headers=h).status_code == 429
    h2 = {"X-Forwarded-For": "203.0.113.8"}
    assert client.post("/v1/challenges", json={"session_id": sid()}, headers=h2).status_code == 200
