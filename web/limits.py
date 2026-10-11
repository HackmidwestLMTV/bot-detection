"""In-memory sliding-window rate limits. Valid for a single uvicorn worker (that's the deploy).

Thread-safe: route handlers are sync and run in a threadpool.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from . import config

WINDOW_S = 60.0
_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)
_last_sweep = 0.0


def client_ip(request: Request) -> str:
    """Use the ASGI peer resolved by Uvicorn's configured trusted proxy middleware.

    Reading raw forwarding headers here lets an untrusted client change its rate
    limit bucket. Only the server's explicit proxy trust policy may replace peer IP.
    """
    return request.client.host if request.client else "unknown"


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
