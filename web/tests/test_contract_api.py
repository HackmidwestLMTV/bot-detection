"""API returns contract-shaped JSON. Needs Postgres at DATABASE_URL; skips if unreachable.

Local: docker compose --profile local up -d db
"""
import psycopg
import pytest

from web import config

try:
    psycopg.connect(config.DATABASE_URL, connect_timeout=2).close()
except Exception:  # noqa: BLE001
    pytest.skip(f"Postgres not reachable at {config.DATABASE_URL}", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from web.app import app  # noqa: E402

LAB = {"X-Lab-Key": config.LAB_KEY}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"]


def test_challenge_keys(client):
    r = client.post("/v1/challenges", json={"session_id": "s_test"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"challenge_id", "seed", "variant_id", "duration_ms", "expires_in_s"}
    assert body["duration_ms"] == 3000 and body["expires_in_s"] == 120
    assert 0 <= body["seed"] < 2**32


def test_challenge_needs_session(client):
    assert client.post("/v1/challenges", json={}).status_code == 422


def test_lab_routes_need_key(client):
    assert client.get("/v1/variants/active").status_code == 403
    assert client.get("/v1/variants/active", headers={"X-Lab-Key": "wrong"}).status_code == 403
    r = client.get("/v1/variants/active", headers=LAB)
    assert r.status_code == 200 and r.json()["id"]


# TODO as routes land: /attempt returns {result, token, fallback}; red attempt w/o key -> 403;
#      /activate w/o approval -> 403; /v1/lab/human-features items have device + features.
