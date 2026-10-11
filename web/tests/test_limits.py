"""Rate limits rely on the ASGI peer, with forwarding handled by trusted middleware."""
import asyncio

import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from web.limits import client_ip


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
