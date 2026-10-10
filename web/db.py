"""psycopg pool + tiny query helpers. Every helper takes SQL with %s placeholders and positional args."""
import pathlib
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg.types.json import Json  # noqa: F401  (re-exported: db.Json(...) for jsonb params)
from psycopg_pool import ConnectionPool

from . import config

pool: ConnectionPool | None = None


def open_pool():
    global pool
    pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=10, open=True,
                          kwargs={"autocommit": True, "row_factory": dict_row})
    pool.wait(timeout=15)


def close_pool():
    if pool:
        pool.close()


def init_schema():
    sql = (pathlib.Path(__file__).parent / "schema.sql").read_text()
    with pool.connection() as conn:
        conn.execute(sql)


def one(sql, *args):
    with pool.connection() as conn:
        return conn.execute(sql, args).fetchone()


def all(sql, *args):  # noqa: A001
    with pool.connection() as conn:
        return conn.execute(sql, args).fetchall()


def exec(sql, *args):  # noqa: A001
    """Run a statement; returns the number of rows affected."""
    with pool.connection() as conn:
        return conn.execute(sql, args).rowcount


@contextmanager
def tx():
    """Several statements in one transaction: `with db.tx() as conn: conn.execute(...)`."""
    with pool.connection() as conn:
        with conn.transaction():
            yield conn
