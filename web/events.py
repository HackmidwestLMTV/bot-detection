"""In-memory SSE broadcaster. Needs uvicorn --workers 1."""
import asyncio
import json

subscribers: set[asyncio.Queue] = set()


async def publish(ev: dict):
    for q in list(subscribers):
        q.put_nowait(ev)


async def stream(backlog: list[dict] = ()):
    """Yields SSE frames. `backlog` (last N lab_events) is replayed first so a refresh doesn't empty the screen."""
    q = asyncio.Queue()
    subscribers.add(q)
    try:
        yield "retry: 2000\n\n"
        for ev in backlog:
            yield f"data: {json.dumps(ev)}\n\n"
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), 15)
                yield f"data: {json.dumps(ev)}\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"
    finally:
        subscribers.discard(q)
