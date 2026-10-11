"""Versioned, signed research envelopes. An invite attests enrollment, not biology."""
import hashlib
import hmac
import json
import math
import re
import time

SCHEMA = "research_sequence_v1"
CONSENT_VERSION = "movement_training_v1"
COLLECTOR_VERSION = "pointer_v2"
FEATURE_VERSION = "target_response_v1"
RETENTION_S = 72 * 3600
DEVICES = ("mouse", "trackpad", "touch")
ID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sign(record, key):
    if not isinstance(key, str) or len(key) < 16:
        raise ValueError("research signing requires an operator key of at least 16 characters")
    derived = hmac.new(key.encode(), b"followit/research/v1", hashlib.sha256).digest()
    return {"record": record, "signature": hmac.new(derived, canonical(record), hashlib.sha256).hexdigest()}


def verify(envelope, key, *, now=None, allow_test=False):
    now = time.time() if now is None else now
    if not isinstance(envelope, dict) or set(envelope) != {"record", "signature"}:
        raise ValueError("unsigned or malformed research envelope")
    r = envelope["record"]
    expected = sign(r, key)["signature"]
    if not isinstance(envelope["signature"], str) or not hmac.compare_digest(expected, envelope["signature"]):
        raise ValueError("recording signature mismatch")
    if not isinstance(r, dict) or r.get("schema") != SCHEMA:
        raise ValueError("unsupported recording schema")
    for name in ("record_id", "group_id", "session_group"):
        if not isinstance(r.get(name), str) or not ID.fullmatch(r[name]):
            raise ValueError("invalid recording identity")
    for name in ("collected_at", "expires_at"):
        if type(r.get(name)) not in (int, float) or not math.isfinite(r[name]):
            raise ValueError("invalid recording timestamp")
    if not 0 < r["expires_at"] - r["collected_at"] <= RETENTION_S or r["collected_at"] > now + 60:
        raise ValueError("invalid retention window")
    if r["expires_at"] <= now:
        raise ValueError("recording expired")
    if r.get("device") not in DEVICES or r.get("collector_version") != COLLECTOR_VERSION:
        raise ValueError("unsupported device or collector")
    if type(r.get("seed")) is not int or not 0 <= r["seed"] <= 0xffffffff:
        raise ValueError("invalid seed")
    if r.get("label") not in ("human", "bot"):
        raise ValueError("unknown training label")
    if r.get("provenance") == "test_fixture":
        if not allow_test:
            raise ValueError("test fixtures cannot become research evidence")
    elif r["label"] == "human":
        if (r.get("provenance") != "operator_invite_v1" or r.get("consent") != CONSENT_VERSION
                or not isinstance(r.get("participant_id"), str) or r["participant_id"] != r["group_id"]):
            raise ValueError("human evidence requires enrolled training consent")
    elif r.get("provenance") != "synthetic_generator_v1":
        raise ValueError("unknown attack provenance")
    if r["label"] == "bot" and not ID.fullmatch(str(r.get("attack_family", ""))):
        raise ValueError("attack family is required")
    return r
