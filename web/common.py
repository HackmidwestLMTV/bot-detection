"""Helpers shared by the route modules."""
import secrets

from fastapi import Header, HTTPException, Query

from . import config, db


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(9)}"


def require_lab(x_lab_key: str | None = Header(default=None), key: str | None = Query(default=None)):
    """X-Lab-Key header. `?key=` is accepted too, only because EventSource (SSE) can't set headers."""
    supplied = x_lab_key or key
    if not supplied or not secrets.compare_digest(supplied, config.LAB_KEY):
        raise HTTPException(403, "lab key required")


def is_lab(x_lab_key: str | None) -> bool:
    return bool(x_lab_key) and secrets.compare_digest(x_lab_key, config.LAB_KEY)


def active_variant() -> dict:
    row = db.one("SELECT config FROM variants WHERE status='active' ORDER BY created_at DESC LIMIT 1")
    if not row:
        raise HTTPException(500, "no active variant")
    return row["config"]
