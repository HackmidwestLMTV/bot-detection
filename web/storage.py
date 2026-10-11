"""Raw trail storage in S3-compatible object storage (Linode). Degrades gracefully:
if S3_* env vars are unset or an upload fails, put_trail returns None and logs a warning.
"""
import datetime as dt
import json
import logging
import threading

from . import config

log = logging.getLogger("followit")
PREFIX = "trails/"
_client = None
_client_lock = threading.Lock()


def configured() -> bool:
    return bool(config.S3_ENDPOINT and config.S3_BUCKET and config.S3_KEY and config.S3_SECRET)


def _s3():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import boto3
                from botocore.config import Config
                _client = boto3.client(
                    "s3", endpoint_url=config.S3_ENDPOINT,
                    aws_access_key_id=config.S3_KEY, aws_secret_access_key=config.S3_SECRET,
                    config=Config(request_checksum_calculation="when_required",
                                  response_checksum_validation="when_required",
                                  connect_timeout=3, read_timeout=5, retries={"max_attempts": 2}))
    return _client


def put_trail(attempt_id: str, trail: dict) -> str | None:
    """Upload the raw trail; return its object key, or None if storage is unavailable."""
    if not configured():
        log.warning("S3 not configured; raw trail for %s not stored", attempt_id)
        return None
    key = f"{PREFIX}{attempt_id}.json"
    try:
        _s3().put_object(Bucket=config.S3_BUCKET, Key=key, Body=json.dumps(trail).encode(),
                         ContentType="application/json", ACL="private")
        return key
    except Exception as e:  # noqa: BLE001
        log.warning("trail upload failed for %s: %s", attempt_id, e)
        return None


def delete_old_trails(hours: int = 72) -> int:
    """Delete trail objects older than `hours`. Returns the number deleted (0 if not configured)."""
    if not configured():
        return 0
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    deleted = 0
    try:
        s3 = _s3()
        batch = []
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=config.S3_BUCKET, Prefix=PREFIX):
            for obj in page.get("Contents", []):
                if obj["LastModified"] < cutoff:
                    batch.append({"Key": obj["Key"]})
                if len(batch) == 1000:
                    s3.delete_objects(Bucket=config.S3_BUCKET, Delete={"Objects": batch, "Quiet": True})
                    deleted += len(batch)
                    batch = []
        if batch:
            s3.delete_objects(Bucket=config.S3_BUCKET, Delete={"Objects": batch, "Quiet": True})
            deleted += len(batch)
    except Exception as e:  # noqa: BLE001
        log.warning("trail cleanup failed: %s", e)
    if deleted:
        log.warning("deleted %d trails older than %dh", deleted, hours)
    return deleted
