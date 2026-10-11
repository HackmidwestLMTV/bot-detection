"""Operator-enrolled sequences, separate from self-labeled calibration evidence."""
import hashlib
import io
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import segno
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from contracts.research import COLLECTOR_VERSION, CONSENT_VERSION, DEVICES, ID, RETENTION_S, SCHEMA, canonical, sign, verify
from . import config, db, storage
from .common import is_lab, new_id

router = APIRouter(prefix="/v1/research")


def configured():
    return len(config.LAB_KEY) >= 16 and bool(config.RESEARCH_RECORDINGS_DIR or storage.configured())


def operator(x_lab_key: str | None = Header(default=None)):
    # Sensitive exports never accept query-string credentials.
    if not is_lab(x_lab_key) or len(config.LAB_KEY) < 16:
        raise HTTPException(403, "research requires a strong operator key in X-Lab-Key")


def code_hash(code):
    if not isinstance(code, str) or not 20 <= len(code) <= 100:
        raise HTTPException(403, "invalid research enrollment")
    return hashlib.sha256(code.encode()).hexdigest()


@router.post("/enrollments", dependencies=[Depends(operator)])
def enroll(body: dict, response: Response, request: Request):
    if not configured():
        raise HTTPException(503, "private research storage is not configured")
    participant = body.get("participant_id")
    if not isinstance(participant, str) or not ID.fullmatch(participant):
        raise HTTPException(422, "use an 8-100 character pseudonymous participant_id")
    device = body.get("device", "")
    if device and device not in DEVICES:
        raise HTTPException(422, "choose mouse, trackpad, or touch")
    code, eid = secrets.token_urlsafe(24), new_id("enroll")
    db.exec("""INSERT INTO research_enrollments(id, code_hash, participant_id, expires_at)
               VALUES (%s,%s,%s,now()+interval '24 hours')""", eid, code_hash(code), participant)
    response.headers["Cache-Control"] = "no-store"
    # Fragments never reach access logs. Opening an invitation does not grant consent.
    origin = config.PUBLIC_URL or str(request.base_url).rstrip("/")
    url = origin + "/?tester=1#" + urlencode({"research": code, "device": device})
    svg = io.BytesIO()
    # Standalone <img> SVG needs its namespace; svg_inline deliberately omits it.
    segno.make(url, error="m").save(svg, kind="svg", scale=6, border=4, xmldecl=False)
    return {"code": code, "enrollment_id": eid, "participant_id": participant,
            "expires_in_s": 86400, "max_challenges": 30, "consent_version": CONSENT_VERSION,
            "tester_url": url, "qr_svg": svg.getvalue().decode("utf-8")}


def bind(body, session_id):
    if not body.get("research_code"):
        return None
    if not configured():
        raise HTTPException(503, "private research storage is not configured")
    if body.get("research_consent") != CONSENT_VERSION:
        raise HTTPException(422, "explicit model-training consent required")
    row = db.one("""UPDATE research_enrollments SET session_id=%s, remaining=remaining-1
        WHERE code_hash=%s AND expires_at>now() AND remaining>0
          AND (session_id IS NULL OR session_id=%s) RETURNING id""",
        session_id, code_hash(body["research_code"]), session_id)
    if not row:
        raise HTTPException(403, "enrollment expired, exhausted, or bound to another session")
    return row["id"]


def validate_attempt(ch, trail):
    eid = ch.get("research_enrollment")
    if not eid:
        if trail.get("research_consent") or trail.get("research_code"):
            raise HTTPException(409, "start an enrolled research challenge first")
        return None
    tester = trail.get("tester") if isinstance(trail.get("tester"), dict) else {}
    if (trail.get("cohort") != "human_test" or trail.get("research_consent") != CONSENT_VERSION
            or tester.get("consent") is not True
            or trail.get("session_id") != ch["session_id"]
            or trail.get("collector_version") != COLLECTOR_VERSION):
        raise HTTPException(422, "research consent, session, and current collector are required")
    row = db.one("""SELECT participant_id FROM research_enrollments WHERE id=%s
        AND code_hash=%s AND session_id=%s AND expires_at>now()""",
        eid, code_hash(trail.get("research_code")), ch["session_id"])
    if not row:
        raise HTTPException(403, "invalid research enrollment")
    return row["participant_id"]


def _local_path(record_id):
    if not ID.fullmatch(record_id):
        raise ValueError("invalid recording id")
    root = Path(config.RESEARCH_RECORDINGS_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root / (record_id + ".json")


def save(aid, cid, ch, trail, participant):
    now = time.time()
    record = {"schema": SCHEMA, "record_id": aid, "label": "human", "provenance": "operator_invite_v1",
              "participant_id": participant, "group_id": participant,
              "session_group": hashlib.sha256(ch["session_id"].encode()).hexdigest(),
              "consent": CONSENT_VERSION, "collected_at": now, "expires_at": now + RETENTION_S,
              "device": trail["device"], "collector_version": COLLECTOR_VERSION,
              "seed": ch["seed"], "path_version": ch["path_version"],
              "presentation_version": ch["presentation_version"], "challenge_id": cid,
              "samples": trail["samples"], "nondominant_hand": trail["tester"].get("nondominant_hand") is True}
    body = canonical(sign(record, config.LAB_KEY))
    if config.RESEARCH_RECORDINGS_DIR:
        path = _local_path(aid)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            f.write(body)
        key = "local:" + aid
    elif storage.configured():
        key = "research/v1/" + aid + ".json"
        storage._s3().put_object(Bucket=config.S3_BUCKET, Key=key, Body=body,
                                ContentType="application/json", ACL="private")
    else:
        raise ValueError("research storage unavailable")
    try:
        db.exec("""INSERT INTO research_recordings
            (id,enrollment_id,device,path_version,presentation_version,expires_at,storage_key)
            VALUES (%s,%s,%s,%s,%s,to_timestamp(%s),%s)""",
            aid, ch["research_enrollment"], trail["device"], ch["path_version"],
            ch["presentation_version"], now + RETENTION_S, key)
    except Exception:
        remove(aid, key)
        raise


def remove(aid, key):
    if key == "local:" + aid:
        _local_path(aid).unlink(missing_ok=True)
    elif key == "research/v1/" + aid + ".json":
        storage._s3().delete_object(Bucket=config.S3_BUCKET, Key=key)
    else:
        raise ValueError("invalid recording storage key")


def cleanup():
    for row in db.all("SELECT id,storage_key FROM research_recordings WHERE expires_at<=now()"):
        remove(row["id"], row["storage_key"])
        db.exec("DELETE FROM research_recordings WHERE id=%s", row["id"])
    db.exec("DELETE FROM research_enrollments WHERE expires_at<now()-interval '72 hours'")
    # Also remove orphaned writes if a process stopped before inserting metadata.
    cutoff = time.time() - RETENTION_S
    if config.RESEARCH_RECORDINGS_DIR:
        for path in Path(config.RESEARCH_RECORDINGS_DIR).glob("*.json"):
            if path.stat().st_mtime <= cutoff:
                path.unlink()
    if storage.configured():
        s3 = storage._s3()
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=config.S3_BUCKET, Prefix="research/v1/"):
            for obj in page.get("Contents", []):
                if obj["LastModified"].timestamp() <= cutoff:
                    s3.delete_object(Bucket=config.S3_BUCKET, Key=obj["Key"])


@router.get("/export", dependencies=[Depends(operator)])
def export(response: Response, after: str = ""):
    response.headers["Cache-Control"] = "no-store"
    rows = db.all("""SELECT id,storage_key FROM research_recordings WHERE expires_at>now() AND id>%s
        AND path_version=%s AND presentation_version=%s ORDER BY id LIMIT 25""",
        after, config.PATH_VERSION, config.PRESENTATION_VERSION)
    envelopes = []
    for row in rows:
        aid, key = row["id"], row["storage_key"]
        try:
            if key == "local:" + aid:
                envelope = json.loads(_local_path(aid).read_bytes())
            elif key == "research/v1/" + aid + ".json":
                envelope = json.loads(storage._s3().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read())
            else:
                raise ValueError("invalid storage key")
            verify(envelope, config.LAB_KEY)
            envelopes.append(envelope)
        except Exception as exc:
            # Never silently produce an incomplete benchmark dataset.
            raise HTTPException(409, "research evidence missing, expired, or changed") from exc
    return {"recordings": envelopes, "next": rows[-1]["id"] if len(rows) == 25 else None}


@router.get("/status", dependencies=[Depends(operator)])
def status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    counts = {r["device"]: r["n"] for r in db.all("""SELECT device,count(*) AS n FROM research_recordings
        WHERE expires_at>now() AND path_version=%s AND presentation_version=%s GROUP BY device""",
        config.PATH_VERSION, config.PRESENTATION_VERSION)}
    return {"storage_configured": configured(), "coverage": {d: {"recordings": counts.get(d, 0),
            "status": "collected; quality not yet evaluated" if counts.get(d) else "untested"} for d in DEVICES},
            "shadow_configured": bool(config.SHADOW_MODEL_DIR), "mode": "shadow_only",
            "model_status": "configured; inspect shadow results" if config.SHADOW_MODEL_DIR else "awaiting_real_training_data",
            "retention_hours": 72, "activation_available": False}
