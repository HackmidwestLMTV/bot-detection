"""In-memory sliding-window rate limits. Valid for a single uvicorn worker (that's the deploy).

Thread-safe: route handlers are sync and run in a threadpool.
"""
import ipaddress
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from . import config

WINDOW_S = 60.0
_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)
_last_sweep = 0.0


# Caddy reaches the app over the compose network, so our proxy is always on one of these.
# Listed explicitly rather than using ip.is_private, which also covers the documentation
# ranges (192.0.2/24, 198.51.100/24, 203.0.113/24) -- we do not want to trust those.
_PROXY_NETS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10",
))


def _trusted_peer(host: str | None) -> bool:
    """Is the socket peer our own reverse proxy? Anything else talked to us directly."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in _PROXY_NETS)


def client_ip(request: Request) -> str:
    """The real client address, resistant to a spoofed X-Forwarded-For.

    Caddy APPENDS the peer it saw to any X-Forwarded-For the client supplied, so a
    client sending `X-Forwarded-For: 1.2.3.4` produces `1.2.3.4, <real client>`. Taking
    the FIRST hop would therefore key the IP ceiling on an attacker-chosen value, and
    rotating it defeats the limit entirely. Take the LAST hop -- the one our own proxy
    appended -- and only when the peer is that proxy. Otherwise use the socket peer.
    """
    peer = request.client.host if request.client else None
    if _trusted_peer(peer):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            hops = [h.strip() for h in xff.split(",") if h.strip()]
            if hops:
                return hops[-1]
    return peer or "unknown"


def _prune(q: deque, now: float):
    while q and q[0] <= now - WINDOW_S:
        q.popleft()


def _sweep(now: float):
    global _last_sweep
    if now - _last_sweep < WINDOW_S:
        return
    _last_sweep = now
    for k in [k for k, q in _hits.items() if not q or q[-1] <= now - WINDOW_S]:
        del _hits[k]


def allow(rules: list[tuple[str, int]]) -> bool:
    """rules = [(key, limit_per_window)]. Records a hit on every key only if ALL are under limit."""
    now = time.monotonic()
    with _lock:
        _sweep(now)
        qs = []
        for key, limit in rules:
            q = _hits[key]
            _prune(q, now)
            if len(q) >= limit:
                return False
            qs.append(q)
        for q in qs:
            q.append(now)
        return True


def check_challenge(session_id: str, request: Request) -> bool:
    return allow([(f"sess:{session_id}", config.CHALLENGES_PER_MIN),
                  (f"ip:{client_ip(request)}", config.IP_PER_MIN)])


def reset():
    """Tests only."""
    with _lock:
        _hits.clear()
