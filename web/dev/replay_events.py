"""Post a LabEvent .jsonl file to /v1/lab/events, one line every --gap seconds.

Builds the dashboard before the worker exists (default file: the contract fixture), and plays the
recorded backup run on stage (open /lab?replay=1 so the REPLAY banner shows):
    python -m web.dev.replay_events [API_BASE] [--file backup_run.jsonl] [--gap 0.7] [--reset]
LAB_KEY comes from the environment.
"""
import argparse
import json
import os
import pathlib
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[2]

ap = argparse.ArgumentParser()
ap.add_argument("base", nargs="?", default=os.environ.get("API_BASE", "http://localhost:8000"))
ap.add_argument("--file", default=str(ROOT / "contracts" / "fixtures" / "events_example.jsonl"))
ap.add_argument("--gap", type=float, default=0.7, help="seconds between events")
ap.add_argument("--reset", action="store_true", help="POST /v1/lab/reset first so the dashboard starts empty")
args = ap.parse_args()
headers = {"X-Lab-Key": os.environ.get("LAB_KEY", "dev-lab-key")}

with httpx.Client(base_url=args.base, headers=headers, timeout=10) as client:
    if args.reset:
        client.post("/v1/lab/reset").raise_for_status()
    for line in pathlib.Path(args.file).read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        ev["ts"] = time.time()
        r = client.post("/v1/lab/events", json=ev)
        print(r.status_code, ev["agent"], ev["type"])
        time.sleep(args.gap)
