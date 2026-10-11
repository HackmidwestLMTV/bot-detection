"""Private enrollment/export and retention cleanup. Never sends recordings to a model API."""
import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from contracts.research import canonical, verify


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(canonical(value))


def cleanup(directory, *, now=None):
    now = time.time() if now is None else now
    removed = 0
    for path in Path(directory).glob("*.json"):
        envelope = json.loads(path.read_bytes())
        record = envelope.get("record", {})
        if record.get("expires_at", float("inf")) <= now:
            path.unlink()
            removed += 1
    return removed


def export(base, directory, key):
    import httpx
    cleanup(directory)
    after, count = "", 0
    with httpx.Client(base_url=base, headers={"X-Lab-Key": key}, timeout=30, follow_redirects=False) as client:
        while True:
            response = client.get("/v1/research/export", params={"after": after})
            response.raise_for_status()
            page = response.json()
            for envelope in page["recordings"]:
                record = verify(envelope, key)
                target = Path(directory) / (record["record_id"] + ".json")
                if target.exists():
                    if json.loads(target.read_bytes()) != envelope:
                        raise ValueError("existing export changed")
                else:
                    write_private(target, envelope)
                count += 1
            cursor = page["next"]
            if cursor is None:
                break
            if cursor <= after:
                raise ValueError("invalid export cursor")
            after = cursor
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("enroll", "export", "cleanup"))
    parser.add_argument("directory")
    parser.add_argument("--url")
    parser.add_argument("--key-file")
    parser.add_argument("--participant")
    args = parser.parse_args()
    if args.action == "cleanup":
        print(json.dumps({"removed": cleanup(args.directory)}))
        return
    url = urlparse(args.url or "")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost")):
        parser.error("use HTTPS or disposable localhost; redirects are disabled")
    if not args.key_file:
        parser.error("--key-file is required")
    key = Path(args.key_file).read_text().strip()
    if args.action == "export":
        print(json.dumps({"exported": export(args.url, args.directory, key)}))
    else:
        import httpx
        response = httpx.post(args.url.rstrip("/") + "/v1/research/enrollments",
                              json={"participant_id": args.participant}, headers={"X-Lab-Key": key}, timeout=30)
        response.raise_for_status()
        data = response.json()
        target = Path(args.directory) / (data["enrollment_id"] + ".invite")
        write_private(target, data)
        print(json.dumps({"invite_file": str(target)}))


if __name__ == "__main__":
    main()
