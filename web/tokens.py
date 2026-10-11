"""Single-use reservation tokens: 120 s, bound to session_id and action="reserve_ticket".

Redeem semantics (documented choices):
- Unknown token (or a token for another action) -> reason "used". We don't reveal whether a
  token id ever existed; to the client it's just "not redeemable any more".
- Precedence when the atomic consume fails: wrong_session > used > expired.
- Cap (2 reservations per session): checked AFTER the token is consumed, in the same
  transaction, and the transaction commits either way. So a token that hits the cap is
  CONSUMED (it's spent; asking again returns "used"). Consistent and simple.
- Race safety: the whole thing (consume + cap count + reservation insert) runs in one
  transaction that first takes pg_advisory_xact_lock(hashtext(session_id)). Two tokens of the
  same session redeemed concurrently serialize on that lock, so the count can't be stale.
  The same token redeemed concurrently is serialized by the row lock taken by the UPDATE:
  exactly one UPDATE ... RETURNING sees consumed_at IS NULL.
"""
from . import config, db
from .common import new_id

ACTION = "reserve_ticket"


def issue(session_id: str) -> str:
    tid = new_id("tok")
    db.exec("""INSERT INTO tokens(id, session_id, action, expires_at)
               VALUES (%s, %s, %s, now() + make_interval(secs => %s))""",
            tid, session_id, ACTION, config.TOKEN_TTL_S)
    return tid


def _why_not(conn, token: str, session_id: str) -> str:
    row = conn.execute("""SELECT session_id, action, consumed_at, expires_at <= now() AS expired
                          FROM tokens WHERE id=%s""", (token,)).fetchone()
    if not row or row["action"] != ACTION:
        return "used"
    if row["session_id"] != session_id:
        return "wrong_session"
    if row["consumed_at"] is not None:
        return "used"
    if row["expired"]:
        return "expired"
    return "used"  # unreachable in practice (lost a race between UPDATE and SELECT)


def redeem(token: str, session_id: str) -> tuple[bool, str]:
    """Consume `token` and create a reservation.

    Returns (True, reservation_id) on success, else (False, reason) with reason in
    "used" | "expired" | "wrong_session" | "cap".
    """
    with db.tx() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (session_id,))
        row = conn.execute("""UPDATE tokens SET consumed_at=now()
                              WHERE id=%s AND session_id=%s AND action=%s
                                AND consumed_at IS NULL AND expires_at > now()
                              RETURNING id""", (token, session_id, ACTION)).fetchone()
        if not row:
            return False, _why_not(conn, token, session_id)
        n = conn.execute("SELECT count(*) AS n FROM reservations WHERE session_id=%s",
                         (session_id,)).fetchone()["n"]
        if n >= config.RESERVATIONS_PER_SESSION:
            return False, "cap"  # commits: the token stays consumed
        rid = new_id("res")
        conn.execute("INSERT INTO reservations(id, session_id, token_id) VALUES (%s, %s, %s)",
                     (rid, session_id, token))
        return True, rid
