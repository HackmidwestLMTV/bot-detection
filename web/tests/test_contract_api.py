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
    assert "total" in r.json()["human_traces"]


def test_qr_page_points_at_tester_mode(client):
    r = client.get("/qr")
    assert r.status_code == 200 and "<svg" in r.text and "/?tester=1" in r.text


def test_challenge_keys(client):
    r = client.post("/v1/challenges", json={"session_id": "s_test"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"challenge_id", "seed", "variant_id", "duration_ms", "expires_in_s", "path_version"}
    assert body["path_version"] == config.PATH_VERSION
    assert body["duration_ms"] == 3000 and body["expires_in_s"] == 120
    assert 0 <= body["seed"] < 2**32


def test_challenge_needs_session(client):
    assert client.post("/v1/challenges", json={}).status_code == 422


def test_lab_routes_need_key(client):
    assert client.get("/v1/variants/active").status_code == 403
    assert client.get("/v1/variants/active", headers={"X-Lab-Key": "wrong"}).status_code == 403
    r = client.get("/v1/variants/active", headers=LAB)
    assert r.status_code == 200 and r.json()["id"]

