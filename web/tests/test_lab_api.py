"""Lab API. Needs Postgres at DATABASE_URL; skips if unreachable. Seeds rows directly with web.db.

WARNING: calls POST /v1/lab/reset, which wipes red attempts / approvals / lab tables in that DB.
"""
import asyncio
import json
import pathlib
import socket
import threading
import time

import psycopg
import pytest

from web import config

try:
    psycopg.connect(config.DATABASE_URL, connect_timeout=2).close()
except Exception:  # noqa: BLE001
    pytest.skip(f"Postgres not reachable at {config.DATABASE_URL}", allow_module_level=True)

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from web import db, events  # noqa: E402
from web.app import app  # noqa: E402
from web.common import new_id  # noqa: E402

LAB = {"X-Lab-Key": config.LAB_KEY}
ROOT = pathlib.Path(__file__).resolve().parents[2]
GATE_KEYS = {"candidate", "baseline", "verdict", "humans_rejected", "forgeries_passed", "reasons"}
FEATS = json.loads((ROOT / "contracts" / "fixtures" / "score_example.json").read_text())["features"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        assert c.post("/v1/lab/reset", headers=LAB).status_code == 200
        yield c


@pytest.fixture
def real_gate():
    from web import engine_adapter
    if engine_adapter.USING_STUBS:
        pytest.skip("real engine required for gate/approval integration; include p2 on PYTHONPATH")


def add_attempt(cohort, device="mouse", round_id=None, nondominant=False, features=None):
    aid = new_id("att")
    db.exec("""INSERT INTO attempts(id, challenge_id, cohort, device, nondominant_hand, round_id, features, score, pass, path_version)
               VALUES (%s, NULL, %s, %s, %s, %s, %s, 0.75, true, %s)""",
            aid, cohort, device, nondominant, round_id, db.Json(FEATS if features is None else features), config.PATH_VERSION)
    return aid


def variant(vid):
    v = json.loads((ROOT / "contracts" / "fixtures" / "variant_v1.json").read_text())
    return {**v, "id": vid, "parent": "v1", "author": "blue", "reason": "test"}


def reviewable_variant(client, vid):
    """Actual engine evidence: human lag 216.7 passes; forged lag 150 stops passing."""
    cfg = variant(vid)
    cfg["enabled"] = ["lag_ms"]
    cfg["pass_threshold"] = 1
    cfg["features"]["lag_ms"] = [200, 450]
    add_attempt("human_test")
    forged = {name: value["value"] for name, value in FEATS.items()}
    forged["lag_ms"] = 150
    add_attempt("red", features=forged)
    assert client.post("/v1/variants", headers=LAB, json=cfg).status_code == 200
    return cfg


def approve(client, vid):
    gate = client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": vid}).json()
    response = client.post("/v1/lab/approvals", headers=LAB,
                           json={"interrupt_id": "int_1", "variant_id": vid, "gate": gate})
    assert response.status_code == 200, response.text
    aid = response.json()["approval_id"]
    assert client.post(f"/v1/lab/approvals/{aid}/decide", headers=LAB, json={"approve": True}).status_code == 200
    return aid


# ---------- auth ----------

ROUTES = [
    ("get", "/v1/lab/human-features"), ("get", "/v1/lab/forgeries"), ("get", "/v1/variants"),
    ("get", "/v1/variants/active"), ("post", "/v1/variants"), ("post", "/v1/lab/gate"),
    ("post", "/v1/lab/approvals"), ("get", "/v1/lab/approvals/x"), ("post", "/v1/lab/approvals/x/decide"),
    ("post", "/v1/variants/v1/activate"), ("post", "/v1/lab/runs"), ("get", "/v1/lab/commands/next"),
    ("post", "/v1/lab/events"), ("get", "/v1/lab/stream"), ("post", "/v1/lab/reset"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_lab_route_needs_key(client, method, path):
    assert client.request(method, path, json={}).status_code == 403
    assert client.request(method, path, json={}, headers={"X-Lab-Key": "wrong"}).status_code == 403


def test_query_key_accepted(client):
    assert client.get(f"/v1/lab/human-features?key={config.LAB_KEY}").status_code == 200


# ---------- data ----------

def test_human_features_shape(client):
    aid = add_attempt("human_test", device="trackpad", nondominant=True)
    add_attempt("organic")
    rows = client.get("/v1/lab/human-features", headers=LAB).json()
    assert rows and all(set(r) == {"attempt_id", "device", "nondominant_hand", "features", "path_version"} for r in rows)
    mine = next(r for r in rows if r["attempt_id"] == aid)
    assert mine["device"] == "trackpad" and mine["nondominant_hand"] is True and mine["features"] == FEATS


def test_forgeries_filter(client):
    a = add_attempt("red", round_id="run_fa")
    b = add_attempt("red", round_id="run_fb")
    rows = client.get("/v1/lab/forgeries", headers=LAB, params={"round_id": "run_fa"}).json()
    assert [r["attempt_id"] for r in rows] == [a]
    assert set(rows[0]) == {"attempt_id", "round_id", "features", "score", "pass", "path_version"}
    every = {r["attempt_id"] for r in client.get("/v1/lab/forgeries", headers=LAB).json()}
    assert {a, b} <= every


# ---------- variants + gate ----------

def test_post_variant_and_conflict(client):
    assert client.post("/v1/variants", headers=LAB, json=variant("vt_post")).json() == {"id": "vt_post"}
    assert db.one("SELECT status FROM variants WHERE id='vt_post'")["status"] == "candidate"
    assert db.one("SELECT config FROM variants WHERE id='vt_post'")["config"]["reason"] == "test"
    assert client.post("/v1/variants", headers=LAB, json=variant("vt_post")).status_code == 409
    bad = variant("vt_bad")
    del bad["pass_threshold"]
    assert client.post("/v1/variants", headers=LAB, json=bad).status_code == 422
    bad = {**variant("vt_bad"), "enabled": ["nope"]}
    assert client.post("/v1/variants", headers=LAB, json=bad).status_code == 422


def test_gate_bad_evidence_is_422_not_500(client, real_gate):
    """The real engine.gate() raises on a human row with a bad device. The dashboard must
    see a 422, never a 500 -- and /v1/lab/reset keeps human traces, so a bad row would
    otherwise break the gate permanently. routes_public.py now refuses to create one."""
    add_attempt("human_test", device=None)
    add_attempt("red", round_id="run_bad")
    client.post("/v1/variants", headers=LAB, json=variant("vt_bad"))
    r = client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": "vt_bad"})
    assert r.status_code in (200, 422), r.status_code
    db.exec("DELETE FROM attempts WHERE cohort='human_test' AND device IS NULL")


def test_gate(client, real_gate):
    add_attempt("human_test")
    add_attempt("red", round_id="run_g")
    client.post("/v1/variants", headers=LAB, json=variant("vt_gate"))
    r = client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": "vt_gate", "run_id": "run_g"})
    assert r.status_code == 200
    g = r.json()
    assert GATE_KEYS <= set(g) and g["verdict"] in ("approve_for_review", "reject")
    assert db.one("SELECT 1 FROM gate_decisions WHERE candidate='vt_gate' AND baseline='v1'")
    ev = db.one("SELECT run_id, body FROM lab_events WHERE body->>'type'='gate_result' ORDER BY id DESC LIMIT 1")
    assert ev["run_id"] == "run_g" and ev["body"]["agent"] == "gate"
    assert client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": "nope"}).status_code == 404


# ---------- approvals + activate ----------

def test_activate_without_approval_403(client, real_gate):
    reviewable_variant(client, "vt_noappr")
    assert client.post("/v1/variants/vt_noappr/activate", headers=LAB).status_code == 403
    assert client.post("/v1/variants/missing/activate", headers=LAB).status_code == 404
    # a pending or denied approval is not enough
    aid = client.post("/v1/lab/approvals", headers=LAB, json={"interrupt_id": "i", "variant_id": "vt_noappr",
                                                              }).json()["approval_id"]
    assert client.post("/v1/variants/vt_noappr/activate", headers=LAB).status_code == 403
    client.post(f"/v1/lab/approvals/{aid}/decide", headers=LAB, json={"approve": False})
    assert client.get(f"/v1/lab/approvals/{aid}", headers=LAB).json() == {"status": "denied"}
    assert client.post("/v1/variants/vt_noappr/activate", headers=LAB).status_code == 403


def test_approval_flow_and_activate(client, real_gate):
    reviewable_variant(client, "vt_act")
    gate = client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": "vt_act"}).json()
    r = client.post("/v1/lab/approvals", headers=LAB,
                    json={"interrupt_id": "int_9", "variant_id": "vt_act", "gate": gate,
                          "run_id": "run_b"})
    aid = r.json()["approval_id"]
    assert client.get(f"/v1/lab/approvals/{aid}", headers=LAB).json() == {"status": "pending"}
    ev = db.one("SELECT run_id, body FROM lab_events WHERE body->>'type'='approval_needed' ORDER BY id DESC LIMIT 1")
    assert ev["body"]["data"] == {"approval_id": aid, "variant_id": "vt_act", "gate": gate}

    # a worker re-posting the same approval_needed is dropped (no double card)
    n = db.one("SELECT count(*) AS n FROM lab_events")["n"]
    assert client.post("/v1/lab/events", headers=LAB, json=ev["body"]).status_code == 204
    assert db.one("SELECT count(*) AS n FROM lab_events")["n"] == n

    assert client.post(f"/v1/lab/approvals/{aid}/decide", headers=LAB, json={"approve": True}).json() == \
        {"status": "approved"}
    assert client.post(f"/v1/lab/approvals/{aid}/decide", headers=LAB, json={"approve": False}).status_code == 409
    assert client.get(f"/v1/lab/approvals/{aid}", headers=LAB).json() == {"status": "approved"}

    prev = client.get("/v1/variants/active", headers=LAB).json()["id"]
    r = client.post("/v1/variants/vt_act/activate", headers=LAB)
    assert r.status_code == 200 and r.json() == {"variant_id": "vt_act", "previous": prev, "approval_id": aid}
    assert client.get("/v1/variants/active", headers=LAB).json()["id"] == "vt_act"
    assert db.one("SELECT count(*) AS n FROM variants WHERE status='active'")["n"] == 1
    assert db.one("SELECT status FROM variants WHERE id=%s", prev)["status"] == "retired"
    ev = db.one("SELECT body FROM lab_events WHERE body->>'type'='variant_activated' ORDER BY id DESC LIMIT 1")
    assert ev["body"]["agent"] == "system" and ev["body"]["data"]["variant_id"] == "vt_act"


def test_approval_errors(client):
    assert client.get("/v1/lab/approvals/apr_missing", headers=LAB).status_code == 404
    assert client.post("/v1/lab/approvals/apr_missing/decide", headers=LAB, json={"approve": True}).status_code == 404
    assert client.post("/v1/lab/approvals", headers=LAB, json={"variant_id": "nope", "gate": {}}).status_code == 404


# ---------- command queue ----------

def test_runs_and_commands(client):
    while client.get("/v1/lab/commands/next", headers=LAB).status_code == 200:
        pass  # drain anything left over
    run = client.post("/v1/lab/runs", headers=LAB, json={"kind": "red"}).json()["run_id"]
    r = client.get("/v1/lab/commands/next", headers=LAB)
    assert r.status_code == 200 and r.json() == {"run_id": run, "kind": "red"}
    r = client.get("/v1/lab/commands/next", headers=LAB)
    assert r.status_code == 204 and r.content == b""
    assert client.post("/v1/lab/runs", headers=LAB, json={"kind": "green"}).status_code == 422


def test_commands_fifo(client):
    a = client.post("/v1/lab/runs", headers=LAB, json={"kind": "red"}).json()["run_id"]
    b = client.post("/v1/lab/runs", headers=LAB, json={"kind": "blue"}).json()["run_id"]
    got = [client.get("/v1/lab/commands/next", headers=LAB).json()["run_id"] for _ in range(2)]
    assert got == [a, b]


# ---------- events ----------

def test_post_events(client):
    for line in (ROOT / "contracts" / "fixtures" / "events_example.jsonl").read_text().splitlines()[:3]:
        assert client.post("/v1/lab/events", headers=LAB, json=json.loads(line)).status_code == 204
    ok = {"run_id": "run_e", "agent": "red", "type": "round_started", "ts": 1.0, "data": {"round": 1}}
    assert client.post("/v1/lab/events", headers=LAB, json={**ok, "type": "made_up"}).status_code == 422
    assert client.post("/v1/lab/events", headers=LAB, json={**ok, "agent": "purple"}).status_code == 422
    assert db.one("SELECT body FROM lab_events WHERE run_id='run_e'") is None


# ---------- SSE ----------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(client):
    """Real uvicorn (TestClient buffers whole responses, so it can't read an infinite stream).
    lifespan off: the DB pool is already open from the `client` fixture."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off",
                                           log_level="warning", timeout_graceful_shutdown=2))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "uvicorn didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def _read_data_frames(resp, want, max_lines=400):
    frames = []
    for i, line in enumerate(resp.iter_lines()):
        if line.startswith("data: "):
            frames.append(json.loads(line[6:]))
            if len(frames) >= want:
                break
        assert i < max_lines, "too many lines without enough data frames"
    return frames


def test_sse_backlog_and_live(client, live_server):
    marker = {"run_id": "run_sse", "agent": "system", "type": "error", "ts": 2.0, "data": {"msg": "backlog"}}
    assert client.post("/v1/lab/events", headers=LAB, json=marker).status_code == 204

    timeout = httpx.Timeout(5.0)
    assert httpx.get(f"{live_server}/v1/lab/stream", timeout=timeout).status_code == 403
    with httpx.Client(timeout=timeout) as h:
        with h.stream("GET", f"{live_server}/v1/lab/stream", params={"key": config.LAB_KEY}) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert resp.headers["cache-control"] == "no-cache"
            assert resp.headers["x-accel-buffering"] == "no"
            lines = resp.iter_lines()
            # backlog: read until our marker (it is the newest stored event)
            for i, line in enumerate(lines):
                assert i < 400, "marker never arrived"
                if line.startswith("data: ") and json.loads(line[6:]) == marker:
                    break
            # live: an event posted now arrives on the open stream
            live = {**marker, "data": {"msg": "live"}}
            assert h.post(f"{live_server}/v1/lab/events", headers=LAB, json=live).status_code == 204
            for i, line in enumerate(lines):
                assert i < 50, "live event never arrived"
                if line.startswith("data: "):
                    assert json.loads(line[6:]) == live
                    break


def test_slow_subscriber_is_dropped():
    async def run():
        gen = events.stream([])
        assert await gen.__anext__() == "retry: 2000\n\n"
        nxt = asyncio.ensure_future(gen.__anext__())  # parks the subscriber on q.get()
        await asyncio.sleep(0)
        q = next(iter(events.subscribers))
        await events.publish({"n": 0})
        assert json.loads((await nxt)[6:]) == {"n": 0}
        for n in range(events.QUEUE_MAX + 5):  # nobody reading: overflow
            await events.publish({"n": n})
        assert q not in events.subscribers
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
    events.subscribers.clear()
    asyncio.run(run())


# ---------- reset (last: wipes lab state) ----------

def test_forged_gate_and_missing_evidence_cannot_create_approval(client, real_gate):
    client.post("/v1/lab/reset", headers=LAB)
    client.post("/v1/variants", headers=LAB, json=variant("vt_unchanged"))
    assert client.post("/v1/lab/approvals", headers=LAB, json={
        "variant_id": "vt_unchanged", "gate": {"verdict": "approve_for_review"}}).status_code == 409
    reviewable_variant(client, "vt_valid")
    assert client.post("/v1/lab/approvals", headers=LAB, json={
        "variant_id": "vt_valid", "gate": {"verdict": "approve_for_review"}}).status_code == 409
    assert db.one("SELECT count(*) AS n FROM approvals")["n"] == 0


@pytest.mark.parametrize("change", ["insert", "update", "delete", "baseline", "candidate", "active_baseline"])
@pytest.mark.parametrize("already_decided", [False, True])
def test_approval_binds_exact_evidence_and_rules(client, real_gate, change, already_decided):
    client.post("/v1/lab/reset", headers=LAB)
    reviewable_variant(client, "vt_stale")
    aid = client.post("/v1/lab/approvals", headers=LAB, json={"variant_id": "vt_stale"}).json()["approval_id"]
    if already_decided:
        assert client.post(f"/v1/lab/approvals/{aid}/decide", headers=LAB, json={"approve": True}).status_code == 200
    if change == "insert":
        add_attempt("human_test")  # Even unchanged counts of failures require a fresh review.
    elif change == "update":
        db.exec("UPDATE attempts SET features=jsonb_set(features, '{lag_ms}', '151') WHERE cohort='red'")
    elif change == "delete":
        db.exec("DELETE FROM attempts WHERE cohort='red'")
    elif change == "active_baseline":
        other = variant("other_baseline")
        db.exec("UPDATE variants SET status='retired' WHERE status='active'")
        db.exec("INSERT INTO variants(id, config, status) VALUES (%s, %s, 'active')", other["id"], db.Json(other))
    else:
        vid = "v1" if change == "baseline" else "vt_stale"
        db.exec("UPDATE variants SET config=jsonb_set(config, '{reason}', '\"changed\"') WHERE id=%s", vid)
    if already_decided:
        assert client.post("/v1/variants/vt_stale/activate", headers=LAB).status_code == 403
    else:
        assert client.post(f"/v1/lab/approvals/{aid}/decide", headers=LAB, json={"approve": True}).status_code == 409
    expected = "other_baseline" if change == "active_baseline" else "v1"
    assert client.get("/v1/variants/active", headers=LAB).json()["id"] == expected
    assert db.one("SELECT consumed_at FROM approvals WHERE id=%s", aid)["consumed_at"] is None


def test_legacy_approval_cannot_activate(client, real_gate):
    client.post("/v1/lab/reset", headers=LAB)
    reviewable_variant(client, "vt_legacy")
    db.exec("INSERT INTO approvals(id, variant_id, status) VALUES ('legacy', 'vt_legacy', 'approved')")
    assert client.post("/v1/variants/vt_legacy/activate", headers=LAB).status_code == 403


def test_concurrent_activation_consumes_approval_once(client, real_gate):
    from concurrent.futures import ThreadPoolExecutor

    client.post("/v1/lab/reset", headers=LAB)
    reviewable_variant(client, "vt_once")
    aid = approve(client, "vt_once")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: client.post("/v1/variants/vt_once/activate", headers=LAB), range(2)))
    assert sorted(r.status_code for r in results) == [200, 403]
    assert db.one("SELECT consumed_at FROM approvals WHERE id=%s", aid)["consumed_at"] is not None
    assert client.post("/v1/variants/vt_once/activate", headers=LAB).status_code == 403


def test_evidence_insert_cannot_race_activation(client, real_gate, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from web import routes_lab

    client.post("/v1/lab/reset", headers=LAB)
    reviewable_variant(client, "vt_race")
    approve(client, "vt_race")
    evaluated = threading.Event()
    release = threading.Event()
    original = routes_lab._evaluate

    def paused(conn, vid):
        result = original(conn, vid)
        evaluated.set()
        assert release.wait(10), "test did not release activation"
        return result

    def write_evidence():
        with psycopg.connect(config.DATABASE_URL, application_name="followit_test_evidence_writer") as conn:
            conn.execute("INSERT INTO attempts(id, cohort, device, features) VALUES (%s, 'human_test', 'mouse', %s)",
                         (new_id("att"), db.Json(FEATS)))

    monkeypatch.setattr(routes_lab, "_evaluate", paused)
    with ThreadPoolExecutor(max_workers=2) as executor:
        activation = executor.submit(client.post, "/v1/variants/vt_race/activate", headers=LAB)
        assert evaluated.wait(10)
        writer = executor.submit(write_evidence)
        try:
            deadline = time.monotonic() + 5
            while not db.one("SELECT 1 FROM pg_stat_activity WHERE application_name='followit_test_evidence_writer' AND wait_event_type='Lock'"):
                assert time.monotonic() < deadline, "evidence writer was not protected by the snapshot lock"
                time.sleep(0.02)
            assert not writer.done()
        finally:
            release.set()
        assert activation.result(timeout=10).status_code == 200
        writer.result(timeout=10)


def test_stub_gate_fails_closed(client, monkeypatch):
    from web import engine_adapter

    client.post("/v1/lab/reset", headers=LAB)
    client.post("/v1/variants", headers=LAB, json=variant("vt_stub"))
    monkeypatch.setattr(engine_adapter, "USING_STUBS", True)
    assert client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": "vt_stub"}).status_code == 503
    assert client.post("/v1/lab/approvals", headers=LAB, json={"variant_id": "vt_stub"}).status_code == 503


def test_retained_invalid_human_device_is_diagnosed_without_discarding_evidence(client, real_gate):
    client.post("/v1/lab/reset", headers=LAB)
    reviewable_variant(client, "vt_legacy_device")
    invalid = add_attempt("human_test", device=None)
    try:
        response = client.post("/v1/lab/gate", headers=LAB, json={"candidate_id": "vt_legacy_device"})
        assert response.status_code == 422
        assert invalid in response.json()["detail"]
        assert "device" in response.json()["detail"]
        assert client.post("/v1/lab/approvals", headers=LAB, json={"variant_id": "vt_legacy_device"}).status_code == 422
        client.post("/v1/lab/reset", headers=LAB)
        assert db.one("SELECT device FROM attempts WHERE id=%s", invalid) == {"device": None}
    finally:
        # Remove only this deliberately invalid test fixture, never real evidence.
        db.exec("DELETE FROM attempts WHERE id=%s", invalid)

def test_reset(client, real_gate):
    client.post("/v1/lab/reset", headers=LAB)
    human = add_attempt("human_test")
    red = add_attempt("red", round_id="run_r")
    reviewable_variant(client, "vt_reset")
    approve(client, "vt_reset")
    assert client.post("/v1/variants/vt_reset/activate", headers=LAB).status_code == 200
    client.post("/v1/lab/runs", headers=LAB, json={"kind": "blue"})

    r = client.post("/v1/lab/reset", headers=LAB)
    assert r.status_code == 200
    assert client.get("/v1/variants/active", headers=LAB).json()["id"] == "v1"
    assert [v["id"] for v in client.get("/v1/variants", headers=LAB).json()] == ["v1"]
    assert db.one("SELECT 1 FROM attempts WHERE id=%s", human)
    assert db.one("SELECT 1 FROM attempts WHERE id=%s", red) is None
    assert client.get("/v1/lab/forgeries", headers=LAB).json() == []
    for t in ("approvals", "gate_decisions", "lab_commands"):
        assert db.one(f"SELECT count(*) AS n FROM {t}")["n"] == 0
    evs = db.all("SELECT body FROM lab_events")
    assert [e["body"]["type"] for e in evs] == ["variant_activated"]
    assert evs[0]["body"]["data"]["previous"] == "vt_reset"
    assert client.get("/v1/lab/commands/next", headers=LAB).status_code == 204
