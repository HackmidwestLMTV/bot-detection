"""Post contracts/fixtures/events_example.jsonl to /v1/lab/events, one line every 0.7 s.

Lets the /lab dashboard be built before Person 2's worker exists.
    python -m web.dev.replay_events [API_BASE]
"""
import json
import os
import pathlib
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[2]
base = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("API_BASE", "http://localhost:8000")
key = os.environ.get("LAB_KEY", "dev-lab-key")

for line in (ROOT / "contracts" / "fixtures" / "events_example.jsonl").read_text().splitlines():
    ev = json.loads(line)
    ev["ts"] = time.time()
    r = httpx.post(f"{base}/v1/lab/events", json=ev, headers={"X-Lab-Key": key})
    print(r.status_code, ev["agent"], ev["type"])
    time.sleep(0.7)
