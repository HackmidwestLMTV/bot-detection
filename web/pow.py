"""Proof-of-work fallback: find counter with leading_zero_bits(sha256(f"{nonce}:{counter}")) >= bits."""
import hashlib
import secrets

from . import config, db
from .common import new_id


def leading_zero_bits(h: bytes) -> int:
    n = int.from_bytes(h, "big")
    return 256 - n.bit_length() if n else 256


def digest(nonce: str, counter) -> bytes:
    return hashlib.sha256(f"{nonce}:{counter}".encode()).digest()


def create(session_id: str) -> dict:
    pid, nonce, bits = new_id("pow"), secrets.token_hex(16), config.POW_BITS
    db.exec("""INSERT INTO pow(id, session_id, nonce, bits, expires_at)
               VALUES (%s, %s, %s, %s, now() + make_interval(secs => %s))""",
            pid, session_id, nonce, bits, config.POW_TTL_S)
    return {"pow_id": pid, "nonce": nonce, "bits": bits, "expires_in_s": config.POW_TTL_S}


def solve(pow_id: str, counter) -> str | None:
    """Return the session_id the pow belongs to if `counter` is valid and the pow is fresh
    and unsolved (marked solved atomically), else None."""
    row = db.one("SELECT nonce, bits FROM pow WHERE id=%s", pow_id)
    if not row or leading_zero_bits(digest(row["nonce"], counter)) < row["bits"]:
        return None
    won = db.one("""UPDATE pow SET solved_at=now()
                    WHERE id=%s AND solved_at IS NULL AND expires_at > now()
                    RETURNING session_id""", pow_id)
    return won["session_id"] if won else None


def brute_force(nonce: str, bits: int) -> int:
    """Client-side helper (tests / scripts)."""
    c = 0
    while leading_zero_bits(digest(nonce, c)) < bits:
        c += 1
    return c
