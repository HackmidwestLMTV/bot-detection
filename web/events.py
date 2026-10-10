"""In-memory SSE broadcaster. Needs uvicorn --workers 1.

`publish` must run on the event loop (call it from `async def` handlers); asyncio.Queue is not
thread-safe. Each subscriber queue is bounded: a tab that stops reading gets disconnected
(its queue is cleared and closed) instead of growing memory forever. EventSource reconnects on
its own after `retry`, and the backlog replay fills the screen back in.
"""
import asyncio
import json

QUEUE_MAX = 256          # events buffered per subscriber before we drop it
PING_S = 15              # keep-alive comment interval (proxies kill idle connections)

_CLOSE = object()        # sentinel: tells a stream to end
subscribers: set[asyncio.Queue] = set()


def _drop(q: asyncio.Queue):
    subscribers.discard(q)
    while True:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break
    q.put_nowait(_CLOSE)


async def publish(ev: dict):
    for q in list(subscribers):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            _drop(q)


def frame(ev: dict) -> str:
    return f"data: {json.dumps(ev, separators=(',', ':'))}\n\n"


async def stream(backlog: list[dict] = ()):
    """Yields SSE frames. `backlog` (last N lab_events) is replayed first so a refresh doesn't empty the screen."""
    q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
    subscribers.add(q)  # subscribe before replaying so nothing published meanwhile is lost
    try:
        yield "retry: 2000\n\n"
        for ev in backlog:
            yield frame(ev)
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), PING_S)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if ev is _CLOSE:
                return
            yield frame(ev)
    finally:
        subscribers.discard(q)
