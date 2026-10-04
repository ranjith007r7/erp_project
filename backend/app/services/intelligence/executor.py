"""
Runs validated SQL on the dedicated read-only database login, acting for
exactly one organization.

HOW TENANT ISOLATION WORKS (and why it is built this way)

Every uil.* view filters on `uil.current_org()`, which looks up the
organization registered for THIS database connection's backend PID in
uil.session_context. The flow per question:

  1. open a connection as the read-only login and read its backend PID
  2. the PRIVILEGED application login (the request's own db session)
     registers {pid -> org_id, the user's RBAC modules, approved?} and commits
  3. the AI's SQL runs on the read-only connection
  4. the registration is deleted, always, in a finally block

Why not a normal session setting (SET app.org_id = ...) as is common with
row-level security? Because that setting is changeable by any SELECT that can
call set_config(). Here the value lives in a table the read-only login cannot
touch, keyed by a PID it cannot forge, so even a query that got past the SQL
validator could not switch tenant. If anything is missing or goes wrong the
lookup returns NULL, `org_id = NULL` is never true, and the query sees zero
rows: it fails closed, never open.

Uses the raw DBAPI cursor (not SQLAlchemy's text()) on purpose: text() treats
":word" as a bind parameter and the driver treats "%" specially, and AI-written
SQL is full of both (ILIKE '%acme%', 'HH24:MI'). Passing the statement
straight to the driver means the SQL that was validated is the SQL that runs.
"""
import datetime
import decimal
import uuid
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings


class UilNotConfigured(Exception):
    """UIL_DATABASE_URL is not set."""


class UilExecutionError(Exception):
    """The query was valid but failed in the database. `reason` is safe to show."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class QueryResult:
    columns: list
    rows: list
    truncated: bool


_engines: dict = {}


def ensure_configured() -> None:
    """Raise UilNotConfigured if the read-only login has not been set up."""
    _uil_engine()


def _uil_engine():
    url = settings.UIL_DATABASE_URL
    if not url:
        raise UilNotConfigured(
            "The intelligence layer is not configured yet: set UIL_DATABASE_URL "
            "(the read-only database login) and run scripts/setup_uil_role.py."
        )
    engine = _engines.get(url)
    if engine is None:
        engine = create_engine(url, pool_size=2, max_overflow=2, pool_pre_ping=True)
        _engines[url] = engine
    return engine


def _json_safe(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return value.total_seconds() / 86400 if value.total_seconds() % 86400 == 0 else str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<binary>"
    return value


def _register_tenant(db: Session, pid: int, org_id: str, modules=(), restricted: bool = False) -> None:
    # Housekeeping: a crash between register and clear would leave a stale row.
    # It could never be used wrongly (every run overwrites its own PID's row
    # before querying), but it need not live forever either.
    db.execute(text("DELETE FROM uil.session_context WHERE set_at < now() - interval '1 hour'"))
    db.execute(
        text(
            "INSERT INTO uil.session_context (backend_pid, org_id, modules, restricted, set_at) "
            "VALUES (:pid, :org, :modules, :restricted, now()) "
            "ON CONFLICT (backend_pid) DO UPDATE SET org_id = EXCLUDED.org_id, modules = EXCLUDED.modules, "
            "restricted = EXCLUDED.restricted, set_at = now()"
        ),
        {"pid": pid, "org": org_id, "modules": sorted(modules), "restricted": bool(restricted)},
    )
    db.commit()  # must be visible to the OTHER connection before it queries


def _clear_tenant(db: Session, pid: int) -> None:
    try:
        db.execute(text("DELETE FROM uil.session_context WHERE backend_pid = :pid"), {"pid": pid})
        db.commit()
    except Exception:
        db.rollback()  # cleanup is best effort; the row is overwritten on next use anyway


def run_readonly_query(db: Session, org_id: str, sql: str, *, max_rows: int, timeout_ms: int,
                       modules=(), restricted: bool = False) -> QueryResult:
    """
    `modules` / `restricted` describe what the ASKING USER may read and are enforced by the
    database itself (every view calls uil.can_read). Both default to "nothing": a caller that
    forgets to pass them gets zero rows, never full access. Fail closed.
    """
    engine = _uil_engine()
    raw = engine.raw_connection()
    pid = None
    try:
        cur = raw.cursor()
        cur.execute("SELECT pg_backend_pid()")
        pid = cur.fetchone()[0]

        _register_tenant(db, pid, str(org_id), modules, restricted)  # any failure here propagates: never run without it

        # Redundant with the role's own defaults on purpose (belt and braces).
        cur.execute("SET LOCAL transaction_read_only = on")
        cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")

        try:
            cur.execute(sql)
            fetched = cur.fetchmany(max_rows + 1)
        except Exception as exc:
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else "database error"
            if "statement timeout" in first_line.lower():
                raise UilExecutionError("The query took too long and was stopped. Try a narrower question.")
            raise UilExecutionError(first_line[:300])

        columns = [d[0] for d in cur.description] if cur.description else []
        truncated = len(fetched) > max_rows
        rows = [[_json_safe(v) for v in row] for row in fetched[:max_rows]]
        return QueryResult(columns=columns, rows=rows, truncated=truncated)
    finally:
        try:
            raw.rollback()  # never commits anything: this connection only reads
        finally:
            raw.close()
            if pid is not None:
                _clear_tenant(db, pid)
