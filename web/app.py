"""FastAPI app. Routes live in routes_public.py and routes_lab.py; shared helpers in common.py.

Route handlers are plain `def` (FastAPI runs them in a thread) so sync DB calls are fine.
"""
import json
import logging
import pathlib
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, routes_lab, routes_public, storage
from .common import active_variant
from .engine_adapter import USING_STUBS

log = logging.getLogger("followit")
ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = pathlib.Path(__file__).resolve().parent / "static"


def seed_v1():
    v1 = json.loads((ROOT / "contracts" / "fixtures" / "variant_v1.json").read_text())
    db.exec("""INSERT INTO variants(id, config, status)
               SELECT %s, %s, 'active' WHERE NOT EXISTS (SELECT 1 FROM variants)""",
            v1["id"], db.Json(v1))


def _trail_janitor():
    """Raw tester trails are kept 72 h (the consent text promises it)."""
    while True:
        try:
            storage.delete_old_trails(72)
        except Exception:  # noqa: BLE001
            log.exception("trail cleanup failed")
        time.sleep(3600)


@asynccontextmanager
async def lifespan(app):
    db.open_pool()
    db.init_schema()
    seed_v1()
    threading.Thread(target=_trail_janitor, daemon=True).start()
    log.warning("engine mode: %s", "stubs" if USING_STUBS else "real engine")
    yield
    db.close_pool()


app = FastAPI(title="Follow It", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(routes_public.router)
app.include_router(routes_lab.router)


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
