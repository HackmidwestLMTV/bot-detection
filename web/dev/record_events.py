"""Record the live /v1/lab/stream to a .jsonl file for the REPLAY backup run.

Start this, then run Red, Blue and Approve on /lab. It stops after `variant_activated` (or Ctrl-C).
Events replayed from the backlog on connect are skipped, so only the new run is recorded.
    python -m web.dev.record_events https://<domain> backup_run.jsonl
Play it back with: python -m web.dev.replay_events https://<domain> --file backup_run.jsonl --reset
"""
import json
import os
import sys
import time

import httpx

base = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("API_BASE", "http://localhost:8000")
out = sys.argv[2] if len(sys.argv) > 2 else "backup_run.jsonl"
key = os.environ.get("LAB_KEY", "dev-lab-key")
started = time.time()
n = 0

with open(out, "w") as f, httpx.stream("GET", f"{base}/v1/lab/stream", params={"key": key},
                                       timeout=httpx.Timeout(10, read=None)) as r:
    r.raise_for_status()
    print(f"recording to {out}; run the demo on /lab now (Ctrl-C to stop)")
    try:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            if (ev.get("ts") or 0) < started:   # backlog replay, not part of this run
                continue
            f.write(json.dumps(ev) + "\n")
            f.flush()
            n += 1
            print(n, ev["agent"], ev["type"])
            if ev["type"] == "variant_activated":
                break
    except KeyboardInterrupt:
        pass
print(f"saved {n} events to {out}")
