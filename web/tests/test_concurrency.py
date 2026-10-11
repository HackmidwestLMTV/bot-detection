"""One token, 20 parallel redeems -> exactly one 200. Prints "1 success, 19 rejected".

- Live:   FOLLOWIT_LIVE_URL=https://site pytest web/tests/test_concurrency.py
          or   python -m web.tests.test_concurrency https://site
- Local:  runs the real app under uvicorn in a background thread (real sockets, real threadpool,
          real Postgres pool), so the 20 redeems are genuinely concurrent DB transactions.
          Skips if Postgres at DATABASE_URL is unreachable.

The token comes from the PoW route (brute-forced here), so it works with stubs or the real scorer.
"""
import asyncio
import os
import socket
import sys
import threading
import time
import uuid

import httpx
import pytest

N = 20


def get_token(base: str, session_id: str) -> str:
    from web.pow import brute_force
    with httpx.Client(base_url=base, timeout=30) as c:
        p = c.post("/v1/pow", json={"session_id": session_id}).raise_for_status().json()
        counter = brute_force(p["nonce"], p["bits"])
        return c.post(f"/v1/pow/{p['pow_id']}/solve", json={"counter": counter}).raise_for_status().json()["token"]


async def _fire(base: str, token: str, session_id: str) -> list[httpx.Response]:
    limits = httpx.Limits(max_connections=N, max_keepalive_connections=N)
    async with httpx.AsyncClient(base_url=base, timeout=30, limits=limits) as c:
        body = {"token": token, "session_id": session_id}
        return await asyncio.gather(*[c.post("/demo/tickets/reserve", json=body) for _ in range(N)])


def run(base: str) -> tuple[int, int]:
    base = base.rstrip("/")
    session_id = f"s_conc_{uuid.uuid4().hex[:10]}"
    token = get_token(base, session_id)
    responses = asyncio.run(_fire(base, token, session_id))
    ok = sum(r.status_code == 200 for r in responses)
    rejected = [r for r in responses if r.status_code == 409]
    assert all(r.json() == {"reason": "used"} for r in rejected), [r.text for r in rejected]
    assert ok + len(rejected) == N, [r.status_code for r in responses]
    print(f"{ok} success, {len(rejected)} rejected")
    return ok, len(rejected)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(not os.environ.get("FOLLOWIT_LIVE_URL"), reason="set FOLLOWIT_LIVE_URL to run against a live site")
def test_concurrent_redeem_live():
    assert run(os.environ["FOLLOWIT_LIVE_URL"]) == (1, N - 1)


def test_concurrent_redeem_local(monkeypatch):
    import psycopg

    from web import config
    try:
        psycopg.connect(config.DATABASE_URL, connect_timeout=2).close()
    except Exception:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable at {config.DATABASE_URL}")
    import uvicorn

    from web.app import app

    monkeypatch.setattr(config, "POW_BITS", 8)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        deadline = time.time() + 15
        while not server.started:
            assert time.time() < deadline and t.is_alive(), "uvicorn did not start"
            time.sleep(0.05)
        assert run(f"http://127.0.0.1:{port}") == (1, N - 1)
    finally:
        server.should_exit = True
        t.join(10)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m web.tests.test_concurrency https://live-url")
    ok, rej = run(sys.argv[1])
    sys.exit(0 if (ok, rej) == (1, N - 1) else 1)
