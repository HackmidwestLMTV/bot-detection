"""Rate limits rely on the ASGI peer, with forwarding handled by trusted middleware."""
import asyncio
from pathlib import Path
import shlex

import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from web.limits import client_ip


def deployed_trusted_hosts():
    """Exercise the actual Compose proxy policy, not a separate test-only policy."""
    compose = (Path(__file__).resolve().parents[2] / "compose.yaml").read_text()
    command = next(line.partition("command:")[2] for line in compose.splitlines()
                   if "command: uvicorn " in line)
    arguments = shlex.split(command)
    return arguments[arguments.index("--forwarded-allow-ips") + 1].split(",")


@pytest.mark.parametrize("peer,expected", [("127.0.0.1", "203.0.113.7"), ("198.51.100.1", "198.51.100.1")])
def test_forwarded_ip_requires_trusted_socket_peer(peer, expected):
    observed = []

    async def app(scope, receive, send):
        observed.append(client_ip(Request(scope)))

    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=["127.0.0.1"])
    scope = {"type": "http", "scheme": "http", "client": (peer, 54321),
             "headers": [(b"x-forwarded-for", b"203.0.113.7")]}
    asyncio.run(wrapped(scope, None, None))
    assert observed == [expected]


def test_raw_forwarding_headers_do_not_override_peer():
    scope = {"type": "http", "client": ("198.51.100.1", 54321),
             "headers": [(b"x-forwarded-for", b"203.0.113.7"), (b"forwarded", b"for=203.0.113.8")]}
    assert client_ip(Request(scope)) == "198.51.100.1"


@pytest.mark.parametrize("peer,forwarded_client,expected", [
    ("172.20.0.2", "203.0.113.9", "203.0.113.9"),
    ("127.0.0.1", "203.0.113.9", "203.0.113.9"),
    ("fd00::2", "2001:db8::9", "2001:db8::9"),
    ("198.51.100.50", "203.0.113.9", "198.51.100.50"),
])
def test_rotating_spoofed_leftmost_hop_cannot_evade_ip_ceiling(
        monkeypatch, peer, forwarded_client, expected):
    """Actual Uvicorn middleware + limiter keep 50 spoofed headers in one bucket.

    Caddy already overwrites XFF at our edge. This additionally checks resilience
    to appended chains and that a direct untrusted socket cannot supply its IP.
    """
    from web import config, limits

    monkeypatch.setattr(config, "IP_PER_MIN", 3)
    observations = []

    async def app(scope, receive, send):
        request = Request(scope)
        observations.append((limits.client_ip(request),
                             limits.check_challenge(scope["session_id"], request)))

    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=deployed_trusted_hosts())

    async def run_requests():
        for i in range(50):
            await wrapped({
                "type": "http", "scheme": "http", "client": (peer, 54321),
                "session_id": f"distinct-session-{i}",
                "headers": [(b"x-forwarded-for",
                             f"198.51.100.{i + 1}, {forwarded_client}".encode())],
            }, None, None)

    limits.reset()
    try:
        asyncio.run(run_requests())
        assert {ip for ip, _ in observations} == {expected}
        assert [allowed for _, allowed in observations] == [True] * 3 + [False] * 47
    finally:
        limits.reset()
