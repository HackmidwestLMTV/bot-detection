"""FastAPI app: every route in contracts/CONTRACT.md.

Build order: /v1/challenges -> /attempt -> tokens -> /demo/tickets/reserve -> /v1/pow -> lab routes.
Route handlers are plain `def` (FastAPI runs them in a thread) so sync DB calls are fine.
"""
import json
import logging
import pathlib
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .engine_adapter import USING_STUBS

log = logging.getLogger("followit")
ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = pathlib.Path(__file__).resolve().parent / "static"


def seed_v1():
    v1 = json.loads((ROOT / "contracts" / "fixtures" / "variant_v1.json").read_text())
    db.exec("""INSERT INTO variants(id, config, status)
               SELECT %s, %s, 'active' WHERE NOT EXISTS (SELECT 1 FROM variants)""",
            v1["id"], db.Json(v1))


@asynccontextmanager
async def lifespan(app):
    db.open_pool()
    db.init_schema()
    seed_v1()
    log.warning("engine mode: %s", "stubs" if USING_STUBS else "real engine")
    yield
    db.close_pool()


app = FastAPI(title="Follow It", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------- helpers ----------

def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(9)}"


def require_lab(x_lab_key: str | None = Header(default=None)):
    if not x_lab_key or not secrets.compare_digest(x_lab_key, config.LAB_KEY):
        raise HTTPException(403, "lab key required")


def active_variant() -> dict:
    row = db.one("SELECT config FROM variants WHERE status='active' ORDER BY created_at DESC LIMIT 1")
    if not row:
        raise HTTPException(500, "no active variant")
    return row["config"]


# ---------- pages ----------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/lab", include_in_schema=False)
def lab_page():
    return FileResponse(STATIC / "lab.html")


@app.get("/healthz")
def healthz():
    db.one("SELECT 1")
    return {"ok": True, "engine": "stubs" if USING_STUBS else "real", "active_variant": active_variant()["id"]}


# ---------- public ----------

@app.post("/v1/challenges")
def create_challenge(body: dict):
    session_id = body.get("session_id")
    if not session_id or not isinstance(session_id, str):
        raise HTTPException(422, "session_id required")
    # TODO limits.check_challenge(session_id): 10/min per session, IP ceiling 300/min
    cid, seed, variant = new_id("ch"), secrets.randbits(32), active_variant()
    db.exec("""INSERT INTO challenges(id, session_id, seed, variant_id, expires_at)
               VALUES (%s, %s, %s, %s, now() + make_interval(secs => %s))""",
            cid, session_id, seed, variant["id"], config.CHALLENGE_TTL_S)
    return {"challenge_id": cid, "seed": seed, "variant_id": variant["id"],
            "duration_ms": config.DURATION_MS, "expires_in_s": config.CHALLENGE_TTL_S}


# TODO POST /v1/challenges/{cid}/attempt
# TODO POST /v1/pow, POST /v1/pow/{id}/solve
# TODO POST /demo/tickets/reserve  (atomic UPDATE ... RETURNING on tokens)


# ---------- lab (all Depends(require_lab)) ----------

@app.get("/v1/variants", dependencies=[Depends(require_lab)])
def list_variants():
    return [r["config"] for r in db.all("SELECT config FROM variants ORDER BY created_at")]


@app.get("/v1/variants/active", dependencies=[Depends(require_lab)])
def get_active_variant():
    return active_variant()


# TODO remaining lab routes: human-features, forgeries, POST variants, gate, approvals,
#      activate (403 unless approved), runs, commands/next, events, stream, reset
