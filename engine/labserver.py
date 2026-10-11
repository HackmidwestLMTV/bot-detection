"""Disposable local lab. Run separately from the human recorder on port 8001."""

import json
import asyncio
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import secrets
import time
import threading
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, StrictBool

from engine.scorer import normalize_samples, score, score_features, validate_variant
from engine.gate import gate
from contracts.presentation import DURATION_MS, LEGACY_PRESENTATION, PRESENTATION_VERSION
from engine.path import DEFAULT_PATH_VERSION


class ChallengeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


class RedAttempt(BaseModel):
    samples: list[tuple[float, float, float]] = Field(min_length=2, max_length=10000)
    device: Literal["mouse", "trackpad", "touch"]
    pointer_type: Literal["mouse", "pen", "touch"]
    cohort: Literal["red"]
    round_id: str = Field(min_length=1, max_length=128)


class LabEvent(BaseModel):
    run_id: str = Field(min_length=1, max_length=128)
    agent: Literal["red", "blue", "gate", "system"]
    type: Literal["round_started", "tool_call", "tool_result", "attempt_scored", "round_report", "error",
                  "gate_result", "approval_needed", "variant_activated"]
    ts: float = Field(allow_inf_nan=False)
    data: dict


class GateRequest(BaseModel):
    candidate_id: str
    run_id: str = "manual"


class ApprovalRequest(BaseModel):
    interrupt_id: str
    variant_id: str
    gate: dict
    run_id: str = "manual"


class DecideRequest(BaseModel):
    approve: StrictBool


class RunRequest(BaseModel):
    kind: Literal["red", "blue"]


def create_lab_app(*, lab_key="dev", variant=None, humans=(), forgeries=(), clock=time.monotonic):
    if not lab_key:
        raise ValueError("lab key cannot be empty")
    if variant is None:
        variant = json.loads((Path(__file__).resolve().parents[1] / "contracts/fixtures/variant_v1.json").read_text())
    validate_variant(variant)
    variant = deepcopy(variant)
    path_version = variant.get("path_version", "v1")
    presentation_version = variant.get("presentation_version", PRESENTATION_VERSION)
    if presentation_version != PRESENTATION_VERSION:
        raise ValueError("unsupported lab presentation_version")
    variant["presentation_version"] = presentation_version
    initial = deepcopy(variant)
    app = FastAPI(title="Follow It disposable lab")
    def matches(row):
        return (row.get("path_version", "v1") == path_version
                and row.get("presentation_version", LEGACY_PRESENTATION) == presentation_version)

    challenges, attempts, events = {}, deepcopy([r for r in forgeries if matches(r)]), []
    for row in attempts:
        score_features(row["features"], variant)
    variants, approvals, commands = {variant["id"]: variant}, {}, []
    all_humans = list(humans)
    human_rows = deepcopy([r for r in all_humans if matches(r)])
    for row in human_rows:
        if row.get("device") not in ("mouse", "trackpad", "touch"):
            raise ValueError("invalid human device")
        score_features(row["features"], variant)
    lock = threading.RLock()
    app.state.events = events
    app.state.attempts = attempts
    app.state.humans = human_rows
    app.state.approvals = approvals

    def emit(run_id, agent, kind, data):
        if len(events) >= 5000:
            raise HTTPException(429, "restart the disposable lab to clear capacity")
        events.append({"run_id": run_id, "agent": agent, "type": kind, "ts": time.time(), "data": deepcopy(data)})

    def evaluate(candidate_id):
        if candidate_id not in variants:
            raise HTTPException(404, "unknown candidate")
        return gate(variants[candidate_id], variant, human_rows, attempts)

    def fingerprint(candidate_id):
        body = [path_version, presentation_version, variants[candidate_id], variant, human_rows, attempts]
        return hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def auth(x_lab_key: str = Header(default="")):
        if not secrets.compare_digest(x_lab_key, lab_key):
            raise HTTPException(403, "invalid lab key")

    @app.get("/healthz")
    def health():
        counts = {device: sum(row["device"] == device for row in human_rows) for device in ("mouse", "trackpad", "touch")}
        return {"status": "ok", "mode": "disposable_lab", "human_records": len(human_rows),
                "human_traces": {"total": len(human_rows), **counts},
                "path_version": path_version, "presentation_version": presentation_version,
                "excluded_legacy_human_traces": len(all_humans) - len(human_rows)}

    @app.get("/lab")
    def lab_page():
        return FileResponse(Path(__file__).parent / "static/lab.html")

    @app.get("/v1/variants/active", dependencies=[Depends(auth)])
    def active():
        return variant

    @app.post("/v1/challenges", dependencies=[Depends(auth)])
    def challenge(body: ChallengeRequest):
        for key in list(challenges):
            if challenges[key]["expires"] <= clock():
                del challenges[key]
        if len(challenges) >= 1000:
            raise HTTPException(429, "restart the disposable lab to clear capacity")
        challenge_id = uuid4().hex
        seed = secrets.randbits(32)
        challenges[challenge_id] = {"seed": seed, "expires": clock() + 120, "path_version": path_version,
                                    "presentation_version": presentation_version, "scoring_config": deepcopy(variant)}
        return {"challenge_id": challenge_id, "seed": seed, "variant_id": variant["id"],
                "duration_ms": DURATION_MS, "expires_in_s": 120, "path_version": path_version,
                "presentation_version": presentation_version}

    @app.post("/v1/challenges/{challenge_id}/attempt", dependencies=[Depends(auth)])
    def attempt(challenge_id: str, body: RedAttempt):
        item = challenges.get(challenge_id)
        if item is None or item["expires"] <= clock():
            raise HTTPException(404, "challenge missing, expired, or used")
        if len(attempts) >= 1000:
            raise HTTPException(429, "restart the disposable lab to clear capacity")
        try:
            samples = normalize_samples(body.samples)
            if samples[-1, 0] > DURATION_MS:
                raise ValueError("samples exceed challenge duration")
            result = score(samples, item["seed"], {**item["scoring_config"], "path_version": item["path_version"]})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        del challenges[challenge_id]
        with lock:
            attempts.append({"attempt_id": "att_" + uuid4().hex, "round_id": body.round_id,
                             "features": result["features"], "score": result["score"], "pass": result["pass"],
                             "path_version": item["path_version"], "presentation_version": item["presentation_version"]})
        # Match the contract: attempt IDs are obtained from the forgery listing.
        return {"result": result, "token": None, "fallback": None if result["pass"] else "pow"}

    @app.get("/v1/lab/forgeries", dependencies=[Depends(auth)])
    def forgeries(round_id: str | None = None):
        return [row for row in attempts if round_id is None or row["round_id"] == round_id]

    @app.post("/v1/lab/events", dependencies=[Depends(auth)], status_code=204)
    def post_event(event: LabEvent):
        if len(events) >= 5000:
            raise HTTPException(429, "restart the disposable lab to clear capacity")
        events.append(event.model_dump())
        return Response(status_code=204)

    @app.get("/dev/events", dependencies=[Depends(auth)])
    def get_events():
        return events

    @app.get("/v1/variants", dependencies=[Depends(auth)])
    def list_variants():
        return list(variants.values())

    @app.post("/v1/variants", dependencies=[Depends(auth)])
    def propose(body: dict):
        try:
            validate_variant(body)
            if body.get("path_version", path_version) != path_version:
                raise ValueError("scoring proposals cannot change the lab path_version")
            if body.get("presentation_version", presentation_version) != presentation_version:
                raise ValueError("scoring proposals cannot change the lab presentation_version")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with lock:
            if body["id"] in variants:
                raise HTTPException(409, "variant already exists")
            if len(variants) >= 100:
                raise HTTPException(429, "candidate capacity reached")
            variants[body["id"]] = {**deepcopy(body), "presentation_version": presentation_version}
        return {"id": body["id"]}

    @app.get("/v1/lab/human-features", dependencies=[Depends(auth)])
    def human_features():
        return [{key: row[key] for key in ("attempt_id", "device", "features", "nondominant_hand", "path_version", "presentation_version") if key in row}
                for row in human_rows]

    @app.post("/v1/lab/gate", dependencies=[Depends(auth)])
    def run_gate(body: GateRequest):
        with lock:
            result = evaluate(body.candidate_id)
            emit(body.run_id, "gate", "gate_result", result)
            return result

    @app.post("/v1/lab/approvals", dependencies=[Depends(auth)])
    def create_approval(body: ApprovalRequest):
        with lock:
            current = evaluate(body.variant_id)
            if current["verdict"] != "approve_for_review" or body.gate != current:
                raise HTTPException(403, "fresh approving gate required")
            if len(approvals) >= 100:
                raise HTTPException(429, "approval capacity reached")
            aid = "apr_" + uuid4().hex
            approvals[aid] = {"variant_id": body.variant_id, "status": "pending", "gate": current,
                              "fingerprint": fingerprint(body.variant_id), "consumed": False}
            emit(body.run_id, "blue", "approval_needed", {"approval_id": aid, "variant_id": body.variant_id, "gate": current})
            return {"approval_id": aid}

    @app.get("/v1/lab/approvals/{approval_id}", dependencies=[Depends(auth)])
    def get_approval(approval_id: str):
        if approval_id not in approvals:
            raise HTTPException(404, "unknown approval")
        return {"status": approvals[approval_id]["status"]}

    @app.post("/v1/lab/approvals/{approval_id}/decide", dependencies=[Depends(auth)])
    def decide(approval_id: str, body: DecideRequest):
        with lock:
            row = approvals.get(approval_id)
            if row is None:
                raise HTTPException(404, "unknown approval")
            if row["status"] != "pending":
                raise HTTPException(409, "approval already decided")
            if body.approve and row["fingerprint"] != fingerprint(row["variant_id"]):
                row["status"] = "denied"
                raise HTTPException(409, "evidence changed; request a fresh approval")
            row["status"] = "approved" if body.approve else "denied"
            return {"status": row["status"]}

    @app.post("/v1/variants/{variant_id}/activate", dependencies=[Depends(auth)])
    def activate(variant_id: str, run_id: str = "manual"):
        nonlocal variant
        with lock:
            current = evaluate(variant_id)
            approved = [(aid, row) for aid, row in approvals.items() if row["variant_id"] == variant_id
                        and row["status"] == "approved" and not row["consumed"]
                        and row["fingerprint"] == fingerprint(variant_id)]
            if current["verdict"] != "approve_for_review" or not approved:
                raise HTTPException(403, "fresh gate and unconsumed human approval required")
            aid, row = approved[-1]
            row["consumed"] = True
            previous = variant["id"]
            variant = variants[variant_id]
            result = {"variant_id": variant_id, "previous": previous, "approval_id": aid}
            emit(run_id, "system", "variant_activated", result)
            return result

    @app.post("/v1/lab/runs", dependencies=[Depends(auth)])
    def queue_run(body: RunRequest):
        with lock:
            if len(commands) >= 100:
                raise HTTPException(429, "queue full")
            run_id = "run_" + uuid4().hex
            commands.append({"run_id": run_id, "kind": body.kind})
            return {"run_id": run_id}

    @app.get("/v1/lab/commands/next", dependencies=[Depends(auth)])
    def next_command():
        with lock:
            return commands.pop(0) if commands else Response(status_code=204)

    @app.get("/v1/lab/stream", dependencies=[Depends(auth)])
    def stream():
        async def frames():
            index = max(0, len(events) - 50)
            while True:
                if index > len(events):
                    index = 0
                batch = events[index:]
                index += len(batch)
                for event in batch:
                    yield "data: " + json.dumps(event) + "\n\n"
                if not batch:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(frames(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/v1/lab/reset", dependencies=[Depends(auth)])
    def reset():
        nonlocal variant
        with lock:
            previous = variant["id"]
            variant = deepcopy(initial)
            variants.clear()
            variants[variant["id"]] = variant
            approvals.clear()
            challenges.clear()
            attempts.clear()
            commands.clear()
            events.clear()
            emit("reset", "system", "variant_activated", {"variant_id": variant["id"], "previous": previous, "approval_id": None})
            return {"ok": True, "active": variant["id"]}

    return app


def local_humans():
    from engine.calibrate import ROOT, load_traces
    rows, rejected = load_traces(os.environ.get("HUMAN_TRACES_DIR", ROOT / "contracts/fixtures/human_traces"), None)
    if rejected:
        raise ValueError("invalid local human evidence; run python -m engine.calibrate")
    return [{"attempt_id": row["file"], "device": row["trace"]["device"], "features": row["features"],
             "path_version": row["trace"].get("path_version", "v1"),
             "presentation_version": row["trace"].get("presentation_version", LEGACY_PRESENTATION),
             "nondominant_hand": row["trace"]["tester"].get("nondominant_hand", False)} for row in rows]


def local_forgeries():
    path = os.environ.get("LAB_FORGERIES_FILE")
    return json.loads(Path(path).read_text(encoding="utf-8"))["forgeries"] if path else []


_local_variant = json.loads((Path(__file__).resolve().parents[1] / "contracts/fixtures/variant_v1.json").read_text())
_local_variant["path_version"] = os.environ.get("PATH_VERSION", DEFAULT_PATH_VERSION)
app = create_lab_app(lab_key=os.environ.get("LAB_KEY", "dev"), variant=_local_variant,
                     humans=local_humans(), forgeries=local_forgeries())
