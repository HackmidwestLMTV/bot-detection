"""Lab routes: all need X-Lab-Key (router-level dependency).

Sync DB helpers + plain `def` handlers, except handlers that call `events.publish` (must run on the
event loop): those are `async def` and push DB work through `run_in_threadpool`.

Events the SERVER emits (the worker must NOT post these itself, or the dashboard shows them twice):
  - gate_result       on POST /v1/lab/gate              (agent "gate")
  - approval_needed   on POST /v1/lab/approvals         (agent "blue")
  - variant_activated on POST /v1/variants/{id}/activate and on reset (agent "system")
A worker-posted approval_needed whose approval_id is already in `approvals` is dropped as a duplicate.
"""
import hashlib
import json
import math
import pathlib
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from . import config, db, engine_adapter, events
from .common import active_variant, new_id, require_lab

router = APIRouter(dependencies=[Depends(require_lab)])

_V1_FIXTURE = pathlib.Path(__file__).resolve().parent.parent / "contracts" / "fixtures" / "variant_v1.json"
BACKLOG = 50

Agent = Literal["red", "blue", "gate", "system"]
EventType = Literal["round_started", "tool_call", "tool_result", "attempt_scored", "round_report",
                    "gate_result", "approval_needed", "variant_activated", "error"]


# ---------- bodies ----------

class VariantIn(BaseModel):
    """Validate every scoring field, including disabled bands, before storing a rule."""
    model_config = ConfigDict(extra="allow")
    id: str
    features: dict[str, list[float]]
    enabled: list[str]
    pass_threshold: float

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not v.strip():
            raise ValueError("id must not be empty")
        return v

    @model_validator(mode="after")
    def _shape(self):
        if self.model_extra and "path_version" in self.model_extra:
            if self.model_extra["path_version"] not in ("v1", "smooth_v2"):
                raise ValueError("unknown path_version")
        names = {"lag_ms", "err_mean_px", "submoves_per_s", "jitter_px", "power_law_beta"}
        if set(self.features) != names:
            raise ValueError("features must contain exactly the five contract features")
        if not self.enabled or len(set(self.enabled)) != len(self.enabled):
            raise ValueError("enabled must be nonempty and contain no duplicates")
        if not math.isfinite(self.pass_threshold) or not 0 < self.pass_threshold <= 1:
            raise ValueError("pass_threshold must be finite and in (0, 1]")
        for name, band in self.features.items():
            if len(band) != 2 or not all(math.isfinite(v) for v in band) or band[0] >= band[1]:
                raise ValueError(f"features.{name} must be finite [lo, hi] with lo < hi")
        missing = [n for n in self.enabled if n not in self.features]
        if missing:
            raise ValueError(f"enabled features without a band: {missing}")
        return self

    @field_validator("pass_threshold", mode="before")
    @classmethod
    def _threshold_type(cls, value):
        if isinstance(value, bool):
            raise ValueError("pass_threshold must be numeric, not boolean")
        return value


class GateIn(BaseModel):
    candidate_id: str
    run_id: str | None = None


class ApprovalIn(BaseModel):
    interrupt_id: str | None = None
    variant_id: str
    gate: dict[str, Any] | None = None
    run_id: str | None = None


class DecideIn(BaseModel):
    approve: bool


class RunIn(BaseModel):
    kind: Literal["red", "blue"]


class LabEvent(BaseModel):
    run_id: str | None = None
    agent: Agent
    type: EventType
    ts: float | None = None
    data: dict[str, Any] = {}


# ---------- event helpers ----------

def _store_event(ev: dict):
    db.exec("INSERT INTO lab_events(run_id, body) VALUES (%s, %s)", ev.get("run_id"), db.Json(ev))


async def _emit(run_id: str | None, agent: str, type_: str, data: dict):
    ev = {"run_id": run_id or "manual", "agent": agent, "type": type_, "ts": time.time(), "data": data}
    await run_in_threadpool(_store_event, ev)
    await events.publish(ev)


# ---------- variants ----------

@router.get("/v1/variants")
def list_variants():
    return [r["config"] for r in db.all("SELECT config FROM variants ORDER BY created_at")]


@router.get("/v1/variants/active")
def get_active_variant():
    return {**active_variant(), "path_version": config.PATH_VERSION}


@router.post("/v1/variants")
def create_variant(body: VariantIn):
    cfg = body.model_dump()
    if cfg.get("path_version", config.PATH_VERSION) != config.PATH_VERSION:
        raise HTTPException(422, "scoring proposals cannot change the configured challenge path_version")
    cfg["path_version"] = config.PATH_VERSION
    n = db.exec("INSERT INTO variants(id, config, status) VALUES (%s, %s, 'candidate') ON CONFLICT (id) DO NOTHING",
                cfg["id"], db.Json(cfg))
    if not n:
        raise HTTPException(409, f"variant {cfg['id']} already exists")
    return {"id": cfg["id"]}


def _activate(variant_id: str) -> dict:
    with db.tx() as conn:
        _lock_evidence(conn)
        if not conn.execute("SELECT 1 FROM variants WHERE id=%s", (variant_id,)).fetchone():
            raise HTTPException(404, "unknown variant")
        appr = conn.execute("""SELECT * FROM approvals WHERE variant_id=%s AND status='approved'
                               AND consumed_at IS NULL
                               ORDER BY decided_at DESC NULLS LAST LIMIT 1""", (variant_id,)).fetchone()
        if not appr:
            raise HTTPException(403, "variant has no approved approval")
        result, fingerprint = _evaluate(conn, variant_id)
        if (result["verdict"] != "approve_for_review" or fingerprint != appr["evidence_fingerprint"]
                or result != appr["gate"]):
            raise HTTPException(403, "approval evidence or baseline changed; request a new review")
        # Locks cover recomputation, single-use consumption, and the active-rule switch.
        conn.execute("UPDATE approvals SET consumed_at=now() WHERE id=%s", (appr["id"],))
        conn.execute("UPDATE variants SET status='retired' WHERE status='active' AND id<>%s", (variant_id,))
        conn.execute("UPDATE variants SET status='active' WHERE id=%s", (variant_id,))
    return {"variant_id": variant_id, "previous": result["baseline"], "approval_id": appr["id"]}


@router.post("/v1/variants/{variant_id}/activate")
async def activate_variant(variant_id: str, run_id: str | None = Query(default=None)):
    result = await run_in_threadpool(_activate, variant_id)
    if result["previous"] != variant_id:
        await _emit(run_id, "system", "variant_activated", result)
    return result


# ---------- data for the agents ----------

@router.get("/v1/lab/human-features")
def human_features():
    return db.all("""SELECT id AS attempt_id, device, COALESCE(nondominant_hand, false) AS nondominant_hand, features, path_version
                     FROM attempts WHERE cohort='human_test' AND path_version=%s ORDER BY created_at""", config.PATH_VERSION)


@router.get("/v1/lab/forgeries")
def forgeries(round_id: str | None = Query(default=None)):
    sql = """SELECT id AS attempt_id, round_id, features, score, pass, path_version
             FROM attempts WHERE cohort='red' AND path_version=%s
             AND (%s::text IS NULL OR round_id=%s::text) ORDER BY created_at"""
    return db.all(sql, config.PATH_VERSION, round_id, round_id)


# ---------- gate + approvals ----------

def _lock_evidence(conn):
    """Freeze the lab snapshot, including inserts that row locks cannot protect.

    SHARE ROW EXCLUSIVE conflicts with PostgreSQL's ordinary write locks, so
    public attempt inserts cannot slip between evaluation and activation. Lock
    ordering is shared with reset; no cooperation from evidence writers needed.
    These brief lab transactions intentionally favor correctness over throughput.
    """
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('followit.activate'))")
    conn.execute("LOCK TABLE variants, attempts, approvals IN SHARE ROW EXCLUSIVE MODE")


def _evaluate(conn, candidate_id: str) -> tuple[dict, str]:
    row = conn.execute("SELECT config FROM variants WHERE id=%s", (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(404, "unknown candidate variant")
    if engine_adapter.USING_STUBS:
        raise HTTPException(503, "real engine required for gate evaluation and activation")
    active = conn.execute("SELECT config FROM variants WHERE status='active' ORDER BY created_at DESC LIMIT 1").fetchone()
    if not active:
        raise HTTPException(409, "no active baseline")
    if row["config"].get("path_version", config.PATH_VERSION) != config.PATH_VERSION:
        raise HTTPException(422, "candidate path_version differs from configured challenge path")
    baseline = {**active["config"], "path_version": config.PATH_VERSION}
    candidate = {**row["config"], "path_version": config.PATH_VERSION}
    humans = conn.execute("SELECT id, device, features, path_version FROM attempts WHERE cohort='human_test' AND path_version=%s ORDER BY id",
                          (config.PATH_VERSION,)).fetchall()
    forged = conn.execute("SELECT id, round_id, features, path_version FROM attempts WHERE cohort='red' AND path_version=%s ORDER BY id",
                          (config.PATH_VERSION,)).fetchall()
    invalid_devices = [r["id"] for r in humans
                       if not isinstance(r["device"], str) or r["device"] not in {"mouse", "trackpad", "touch"}]
    if invalid_devices:
        # Preserve historical evidence; never silently omit a represented human.
        shown = ", ".join(invalid_devices[:20])
        raise HTTPException(422, f"{len(invalid_devices)} retained human attempt(s) have invalid devices: {shown}. "
                                 "Review and correct their device metadata before gate evaluation.")
    try:
        VariantIn.model_validate(candidate)
        VariantIn.model_validate(baseline)
        result = engine_adapter.gate(candidate, baseline, humans, forged)
        snapshot = {"candidate": candidate, "baseline": baseline, "humans": humans, "forgeries": forged}
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, "invalid variant or evidence; gate cannot be evaluated") from exc
    return result, fingerprint


def _run_gate(candidate_id: str) -> dict:
    with db.tx() as conn:
        _lock_evidence(conn)
        result, _ = _evaluate(conn, candidate_id)
        conn.execute("INSERT INTO gate_decisions(id, candidate, baseline, result) VALUES (%s, %s, %s, %s)",
                     (new_id("gd"), candidate_id, result["baseline"], db.Json(result)))
    return result


@router.post("/v1/lab/gate")
async def run_gate(body: GateIn):
    result = await run_in_threadpool(_run_gate, body.candidate_id)
    await _emit(body.run_id, "gate", "gate_result", result)
    return result


def _create_approval(body: ApprovalIn) -> tuple[str, dict]:
    aid = new_id("apr")
    with db.tx() as conn:
        _lock_evidence(conn)
        result, fingerprint = _evaluate(conn, body.variant_id)
        if result["verdict"] != "approve_for_review":
            raise HTTPException(409, "candidate does not pass the server gate")
        if body.gate is not None and body.gate != result:
            raise HTTPException(409, "submitted gate does not match the current server gate")
        conn.execute("""INSERT INTO approvals(id, interrupt_id, variant_id, gate, evidence_fingerprint, status)
                        VALUES (%s, %s, %s, %s, %s, 'pending')""",
                     (aid, body.interrupt_id, body.variant_id, db.Json(result), fingerprint))
    return aid, result


@router.post("/v1/lab/approvals")
async def create_approval(body: ApprovalIn):
    aid, gate = await run_in_threadpool(_create_approval, body)
    # The server is the single source of approval_needed (see module docstring).
    await _emit(body.run_id, "blue", "approval_needed",
                {"approval_id": aid, "variant_id": body.variant_id, "gate": gate})
    return {"approval_id": aid}


@router.get("/v1/lab/approvals/{approval_id}")
def get_approval(approval_id: str):
    row = db.one("SELECT status FROM approvals WHERE id=%s", approval_id)
    if not row:
        raise HTTPException(404, "unknown approval")
    return {"status": row["status"]}


@router.post("/v1/lab/approvals/{approval_id}/decide")
def decide_approval(approval_id: str, body: DecideIn):
    status = "approved" if body.approve else "denied"
    with db.tx() as conn:
        _lock_evidence(conn)
        row = conn.execute("SELECT * FROM approvals WHERE id=%s", (approval_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown approval")
        if row["status"] != "pending":
            raise HTTPException(409, "approval already decided")
        if body.approve:
            result, fingerprint = _evaluate(conn, row["variant_id"])
            if (result["verdict"] != "approve_for_review" or fingerprint != row["evidence_fingerprint"]
                    or result != row["gate"]):
                raise HTTPException(409, "approval evidence or baseline changed; request a new review")
        conn.execute("UPDATE approvals SET status=%s, decided_at=now() WHERE id=%s", (status, approval_id))
    return {"status": status}


# ---------- worker command queue ----------

@router.post("/v1/lab/runs")
def queue_run(body: RunIn):
    run_id = new_id("run")
    db.exec("INSERT INTO lab_commands(id, kind, status) VALUES (%s, %s, 'queued')", run_id, body.kind)
    return {"run_id": run_id}


@router.get("/v1/lab/commands/next")
def next_command():
    row = db.one("""UPDATE lab_commands SET status='running'
                    WHERE id = (SELECT id FROM lab_commands WHERE status='queued'
                                ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED)
                    RETURNING id AS run_id, kind""")
    if not row:
        return Response(status_code=204)
    return row


# ---------- events + SSE ----------

def _ingest(ev: dict) -> bool:
    if ev["type"] == "approval_needed":
        aid = (ev.get("data") or {}).get("approval_id")
        if aid and db.one("SELECT 1 FROM approvals WHERE id=%s", aid):
            return False  # the server already emitted this card on POST /v1/lab/approvals
    _store_event(ev)
    return True


@router.post("/v1/lab/events", status_code=204)
async def post_event(body: LabEvent):
    ev = body.model_dump()
    if ev["ts"] is None:
        ev["ts"] = time.time()
    if await run_in_threadpool(_ingest, ev):
        await events.publish(ev)
    return Response(status_code=204)


def _backlog() -> list[dict]:
    rows = db.all("""SELECT body FROM (SELECT id, body FROM lab_events ORDER BY id DESC LIMIT %s) t
                     ORDER BY id""", BACKLOG)
    return [r["body"] for r in rows]


@router.get("/v1/lab/stream")
async def stream():
    backlog = await run_in_threadpool(_backlog)
    return StreamingResponse(events.stream(backlog), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- reset ----------

def _reset() -> str | None:
    v1 = json.loads(_V1_FIXTURE.read_text())
    with db.tx() as conn:
        _lock_evidence(conn)
        prev = conn.execute("SELECT id FROM variants WHERE status='active' ORDER BY created_at DESC LIMIT 1").fetchone()
        conn.execute("DELETE FROM attempts WHERE cohort='red'")
        for table in ("approvals", "gate_decisions", "lab_commands", "lab_events"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM variants WHERE id<>'v1'")
        conn.execute("""INSERT INTO variants(id, config, status) VALUES ('v1', %s, 'active')
                        ON CONFLICT (id) DO UPDATE SET config=EXCLUDED.config, status='active'""", (db.Json(v1),))
    return prev["id"] if prev else None


@router.post("/v1/lab/reset")
async def reset():
    prev = await run_in_threadpool(_reset)
    # One event so open dashboards learn v1 is live again; it also becomes the whole backlog.
    await _emit("reset", "system", "variant_activated", {"variant_id": "v1", "previous": prev, "approval_id": None})
    return {"ok": True, "active": "v1"}
