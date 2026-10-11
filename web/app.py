"""FastAPI app. Routes live in routes_public.py and routes_lab.py; shared helpers in common.py.

Route handlers are plain `def` (FastAPI runs them in a thread) so sync DB calls are fine.
"""
import html
import json
import logging
import pathlib
import threading
import time
from contextlib import asynccontextmanager

import segno
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, routes_lab, routes_public, storage, research
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
            research.cleanup()
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
app.include_router(research.router)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/lab", include_in_schema=False)
def lab_page():
    return FileResponse(STATIC / "lab.html")


@app.get("/research", include_in_schema=False)
def research_page():
    return FileResponse(STATIC / "research.html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@app.get("/qr", include_in_schema=False)
def checkout_qr(request: Request):
    return _qr_page(request, tester=False)


@app.get("/qr/tester", include_in_schema=False)
def tester_qr(request: Request):
    return _qr_page(request, tester=True)


def _qr_page(request: Request, *, tester: bool):
    url = f"{config.PUBLIC_URL or str(request.base_url).rstrip('/')}/" + ("?tester=1" if tester else "")
    heading = "Help calibrate Follow It" if tester else "Try Follow It"
    description = ("Share a movement recording with consent to help calibrate our provisional scoring rules."
                   if tester else "Follow the ball for five seconds, then reserve a demo ticket. No payment is collected.")
    note = ("Raw recordings are kept for 72 hours. Choose your device and give consent before recording."
            if tester else "A keyboard-accessible browser check is also available. It adds computational friction, not proof of humanity.")
    svg = segno.make(url, error="m").svg_inline(scale=12, border=2, dark="#000", light="#fff")
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Follow It · {heading}</title>
<style>body{{margin:0;background:#fff;color:#000;font:20px/1.4 system-ui,sans-serif;text-align:center}}
main{{max-width:640px;margin:0 auto;padding:32px 16px}}h1{{font-size:40px;margin:0 0 8px}}
svg{{max-width:100%;height:auto}}code{{font-size:16px;word-break:break-all}}</style></head>
<body><main><h1>{heading}</h1><p>{description}</p>
{svg}<p><code>{html.escape(url)}</code></p>
<p>{note}</p></main></body></html>""")


@app.get("/healthz")
def healthz():
    traces = {r["device"] or "unknown": r["n"] for r in db.all(
        """SELECT device, count(*) AS n FROM attempts WHERE cohort='human_test' AND path_version=%s
           AND presentation_version=%s GROUP BY device""", config.PATH_VERSION, config.PRESENTATION_VERSION)}
    excluded = db.one("""SELECT count(*) AS n FROM attempts WHERE cohort='human_test'
                         AND (path_version<>%s OR presentation_version<>%s)""",
                      config.PATH_VERSION, config.PRESENTATION_VERSION)["n"]
    return {"ok": True, "engine": "stubs" if USING_STUBS else "real", "active_variant": active_variant()["id"],
            "path_version": config.PATH_VERSION, "presentation_version": config.PRESENTATION_VERSION,
            "excluded_legacy_human_traces": excluded,
            "human_traces": {"total": sum(traces.values()), **traces}}
