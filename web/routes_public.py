"""Public routes: challenges, attempts, PoW, ticket reservation."""
import logging
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from . import config, db, engine_adapter, limits, pow, storage, tokens, research
from .common import active_variant, is_lab, new_id

log = logging.getLogger("followit")
router = APIRouter()

MAX_SAMPLES = 5000
COHORTS = {"organic", "human_test", "red"}
# engine.gate() raises on any human_test row whose device isn't one of these, and
# /v1/lab/reset keeps human traces, so one bad row would break the gate for good.
DEVICES = {"mouse", "trackpad", "touch"}


def _session(body: dict) -> str:
    sid = body.get("session_id") if isinstance(body, dict) else None
    if not sid or not isinstance(sid, str) or len(sid) > 200:
        raise HTTPException(422, "session_id required")
    return sid


@router.post("/v1/challenges")
def create_challenge(body: dict, request: Request, x_lab_key: str | None = Header(default=None)):
    session_id = _session(body)
    # The lab worker (Red) carries X-Lab-Key and is exempt from the public limits.
    if not is_lab(x_lab_key) and not limits.check_challenge(session_id, request):
        raise HTTPException(429, "too many challenges")
    cid, seed, variant = new_id("ch"), secrets.randbits(32), active_variant()
    enrollment = research.bind(body, session_id)
    db.exec("""INSERT INTO challenges(id, session_id, seed, variant_id, path_version, presentation_version, scoring_config, expires_at, research_enrollment)
               VALUES (%s, %s, %s, %s, %s, %s, %s, now() + make_interval(secs => %s), %s)""",
            cid, session_id, seed, variant["id"], config.PATH_VERSION, config.PRESENTATION_VERSION,
            db.Json(variant), config.CHALLENGE_TTL_S, enrollment)
    return {"challenge_id": cid, "seed": seed, "variant_id": variant["id"],
            "duration_ms": config.DURATION_MS, "expires_in_s": config.CHALLENGE_TTL_S,
            "path_version": config.PATH_VERSION, "presentation_version": config.PRESENTATION_VERSION}


def _samples(trail: dict) -> list:
    s = trail.get("samples")
    if not isinstance(s, list) or len(s) > MAX_SAMPLES:
        raise HTTPException(422, "samples must be a list of [t_ms, x, y]")
    out = []
    for p in s:
        if (not isinstance(p, (list, tuple)) or len(p) != 3
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)):
            raise HTTPException(422, "samples must be a list of [t_ms, x, y]")
        out.append([float(p[0]), float(p[1]), float(p[2])])
    return out


@router.post("/v1/challenges/{cid}/attempt")
def attempt(cid: str, trail: dict, x_lab_key: str | None = Header(default=None)):
    cohort = trail.get("cohort", "organic")
    if cohort is None:
        cohort = "organic"
    if not isinstance(cohort, str) or cohort not in COHORTS:
        raise HTTPException(422, "bad cohort")
    red = cohort == "red"
    if red and not is_lab(x_lab_key):
        raise HTTPException(403, "lab key required for red attempts")
    device = trail.get("device")
    valid_device = isinstance(device, str) and device in DEVICES
    if cohort == "human_test" and not valid_device:
        raise HTTPException(422, "human_test requires device mouse, trackpad or touch")
    if device is not None and not valid_device:
        raise HTTPException(422, "device must be mouse, trackpad or touch")
    samples = _samples(trail)
    tester = trail.get("tester") if isinstance(trail.get("tester"), dict) else {}

    ch = db.one("""UPDATE challenges SET attempts = attempts + 1
                   WHERE id=%s AND expires_at > now() AND attempts < %s
                   RETURNING session_id, seed, path_version, presentation_version, scoring_config, research_enrollment""", cid, config.ATTEMPTS_PER_CHALLENGE)
    if not ch:
        live = db.one("SELECT 1 FROM challenges WHERE id=%s AND expires_at > now()", cid)
        if not live:
            raise HTTPException(404, "challenge not found or expired")
        raise HTTPException(429, "too many attempts for this challenge")

    if cohort == "human_test" and trail.get("presentation_version") != ch["presentation_version"]:
        raise HTTPException(409, "tester display changed or unavailable; reload before recording")
    participant = research.validate_attempt(ch, trail)

    try:
        if ch["scoring_config"] is None:
            raise HTTPException(409, "issued scoring rule unavailable; start a new challenge")
        result = engine_adapter.score(samples, ch["seed"], {**ch["scoring_config"], "path_version": ch["path_version"]})
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    passed = bool(result.get("pass"))
    features = {k: (v.get("value") if isinstance(v, dict) else v)
                for k, v in (result.get("features") or {}).items()}
    aid = new_id("att")
    trail_key = None
    if cohort == "human_test" and tester.get("consent") is True and not participant:
        trail_key = storage.put_trail(aid, {**trail, "seed": ch["seed"], "path_version": ch["path_version"],
                                           "presentation_version": ch["presentation_version"],
                                           "challenge_id": cid})
    db.exec("""INSERT INTO attempts(id, challenge_id, cohort, device, nondominant_hand, round_id,
                                    features, score, pass, trail_key, path_version, presentation_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            aid, cid, cohort, trail.get("device"), bool(tester.get("nondominant_hand", False)),
            trail.get("round_id") if red else None, db.Json(features),
            result.get("score"), passed, trail_key, ch["path_version"], ch["presentation_version"])

    research_status = None
    if participant:
        try:
            research.save(aid, cid, ch, trail, participant)
            research_status = "saved"
        except Exception:
            log.warning("research recording unavailable for %s", aid)
            research_status = "storage_unavailable"
    if config.SHADOW_MODEL_DIR:
        try:
            shadow = engine_adapter.shadow(samples, ch["seed"], ch["path_version"], ch["presentation_version"], config.SHADOW_MODEL_DIR)
            db.exec("UPDATE attempts SET shadow_result=%s WHERE id=%s", db.Json(shadow), aid)
        except Exception:
            log.warning("shadow telemetry unavailable for %s; active decision preserved", aid)

    token = tokens.issue(ch["session_id"]) if passed and not red else None
    response = {"result": result, "token": token, "fallback": None if passed else "pow", "attempt_id": aid}
    if participant:
        response["research_recording"] = research_status
    return response


@router.post("/v1/pow")
def create_pow(body: dict):
    return pow.create(_session(body))


@router.post("/v1/pow/{pid}/solve")
def solve_pow(pid: str, body: dict):
    counter = body.get("counter") if isinstance(body, dict) else None
    if isinstance(counter, bool) or not isinstance(counter, (int, str)) or len(str(counter)) > 64:
        raise HTTPException(400, "counter required")
    session_id = pow.solve(pid, counter)
    if not session_id:
        raise HTTPException(400, "invalid, expired or already solved")
    return {"token": tokens.issue(session_id)}


@router.post("/demo/tickets/reserve")
def reserve(body: dict):
    token = body.get("token") if isinstance(body, dict) else None
    session_id = _session(body)
    if not token or not isinstance(token, str):
        return JSONResponse({"reason": "used"}, status_code=409)
    ok, value = tokens.redeem(token, session_id)
    if not ok:
        return JSONResponse({"reason": value}, status_code=409)
    return {"reservation_id": value}
