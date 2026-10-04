"""
LAYER TWO tests: the database itself, attacked directly as the real read-only
login with NO application validator in the way. If these hold, tenant
isolation and read-only-ness do not depend on application code being right.
"""
import psycopg2
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.intelligence.executor import UilExecutionError, run_readonly_query
from app.services.intelligence.manifest import ALL_MODULES, VIEWS
from app.services.intelligence.role_setup import smoke_test_login, verify_uil_role
from conftest import UIL_TEST_URL


@pytest.fixture(autouse=True)
def _clean_tenant_registrations(uil_env):
    """
    Tests here register tenants for their own connections and must not leave
    rows behind: leftovers made two executor tests fail, and worse, the
    "no context => zero rows" test could become flaky when the database reuses
    a backend PID that an earlier test registered.
    """
    with uil_env.begin() as c:
        c.execute(text("TRUNCATE uil.session_context"))
    yield
    with uil_env.begin() as c:
        c.execute(text("TRUNCATE uil.session_context"))


def _connect():
    return psycopg2.connect(UIL_TEST_URL)


def _set_tenant(admin, pid, org_id, modules=None, restricted=True):
    """Registers a tenant AND what the user may read. Defaults to FULL access so the isolation tests
    exercise the hardest case; the access-control tests pass narrower profiles explicitly."""
    modules = sorted(ALL_MODULES) if modules is None else sorted(modules)
    with admin.begin() as c:
        c.execute(text(
            "INSERT INTO uil.session_context (backend_pid, org_id, modules, restricted) VALUES (:p, :o, :m, :r) "
            "ON CONFLICT (backend_pid) DO UPDATE SET org_id = EXCLUDED.org_id, modules = EXCLUDED.modules, "
            "restricted = EXCLUDED.restricted"), {"p": pid, "o": org_id, "m": modules, "r": restricted})


def _pid(conn):
    cur = conn.cursor()
    cur.execute("SELECT pg_backend_pid()")
    pid = cur.fetchone()[0]
    conn.rollback()
    return pid


def _expected_count(admin, view, org_id):
    """Ground truth computed as the PRIVILEGED user straight from the base tables."""
    with admin.connect() as c:
        if view.custom_sql:
            sql = f"SELECT count(*) FROM public.{view.base} WHERE org_id = :o"
        elif view.via is None:
            sql = f"SELECT count(*) FROM public.{view.base} WHERE org_id = :o"
        else:
            parent, fk = view.via
            sql = (f"SELECT count(*) FROM public.{view.base} c JOIN public.{parent} p ON p.id = c.{fk} "
                   "WHERE p.org_id = :o")
        return c.execute(text(sql), {"o": org_id}).scalar()


def test_role_has_exactly_the_intended_privileges(uil_env):
    assert verify_uil_role(uil_env) == []


def test_functional_login_works_and_fails_closed(uil_env):
    assert smoke_test_login(UIL_TEST_URL) == []


def test_no_context_means_zero_rows_in_every_single_view(uil_env, seeded_orgs):
    conn = _connect()
    try:
        cur = conn.cursor()
        for v in VIEWS:
            cur.execute(f"SELECT count(*) FROM uil.{v.name}")
            assert cur.fetchone()[0] == 0, f"{v.name} returned rows with no tenant context"
            conn.rollback()
    finally:
        conn.close()


@pytest.mark.parametrize("key", ["a", "b"])
def test_every_view_returns_exactly_this_orgs_rows_and_no_others(uil_env, seeded_orgs, key):
    """All 33 views, including the 10 child tables that have no org_id of their own."""
    org_id = seeded_orgs[key]["org_id"]
    conn = _connect()
    try:
        pid = _pid(conn)
        _set_tenant(uil_env, pid, org_id)
        cur = conn.cursor()
        for v in VIEWS:
            cur.execute(f"SELECT count(*) FROM uil.{v.name}")
            seen = cur.fetchone()[0]
            conn.rollback()
            assert seen == _expected_count(uil_env, v, org_id), f"{v.name}: wrong row count for org {key}"
    finally:
        conn.close()


def test_the_two_seeded_orgs_really_differ_so_the_isolation_test_means_something(uil_env, seeded_orgs):
    a = _expected_count(uil_env, next(v for v in VIEWS if v.name == "invoices"), seeded_orgs["a"]["org_id"])
    b = _expected_count(uil_env, next(v for v in VIEWS if v.name == "invoices"), seeded_orgs["b"]["org_id"])
    assert a > 0 and b > 0 and a != b


def test_switching_the_registered_org_switches_what_is_visible(uil_env, seeded_orgs):
    conn = _connect()
    try:
        pid = _pid(conn)
        cur = conn.cursor()
        sums = {}
        for key in ("a", "b"):
            _set_tenant(uil_env, pid, seeded_orgs[key]["org_id"])
            cur.execute("SELECT sum(amount) FROM uil.invoices")
            sums[key] = cur.fetchone()[0]
            conn.rollback()
        assert sums["a"] != sums["b"]
    finally:
        conn.close()


ATTACKS = [
    "SELECT password_hash FROM public.users",
    "SELECT * FROM public.invoices",
    "SELECT * FROM uil.session_context",
    "INSERT INTO uil.invoices (id) VALUES (gen_random_uuid())",
    "UPDATE public.invoices SET amount = 0",
    "DELETE FROM public.invoices",
    "DROP TABLE public.invoices",
    "TRUNCATE public.invoices",
    "CREATE TABLE uil.hack (x int)",
    "UPDATE uil.session_context SET org_id = gen_random_uuid()",
    "DELETE FROM uil.session_context",
    "SET ROLE postgres",
    "SET ROLE erp_test",
    "SELECT set_config('role', 'erp_test', false)",
    "SET SESSION AUTHORIZATION erp_test",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT lo_import('/etc/passwd')",
    "COPY (SELECT 1) TO PROGRAM 'id'",
    "SELECT * FROM pg_authid",
]


@pytest.mark.parametrize("attack", ATTACKS)
def test_database_refuses_the_attack_on_its_own(uil_env, seeded_orgs, attack):
    conn = _connect()
    try:
        _set_tenant(uil_env, _pid(conn), seeded_orgs["a"]["org_id"])
        cur = conn.cursor()
        with pytest.raises(psycopg2.Error):
            cur.execute(attack)
    finally:
        conn.rollback()
        conn.close()


def test_tampering_with_a_session_setting_cannot_change_tenant(uil_env, seeded_orgs):
    """
    The classic row-level-security weakness: isolation driven by a session
    setting that the querying user can overwrite. Here isolation does NOT
    depend on any setting, so trying to overwrite one changes nothing.
    """
    conn = _connect()
    try:
        _set_tenant(uil_env, _pid(conn), seeded_orgs["a"]["org_id"])
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM uil.invoices")
        before = cur.fetchone()[0]
        for setting in ("uil.org_id", "app.org_id", "app.current_org", "request.jwt.claim.org_id"):
            cur.execute("SELECT set_config(%s, %s, false)", (setting, seeded_orgs["b"]["org_id"]))
        cur.execute("SELECT count(*) FROM uil.invoices")
        assert cur.fetchone()[0] == before == _expected_count(
            uil_env, next(v for v in VIEWS if v.name == "invoices"), seeded_orgs["a"]["org_id"])
    finally:
        conn.rollback()
        conn.close()


def test_role_defaults_are_in_force(uil_env):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SHOW default_transaction_read_only")
        assert cur.fetchone()[0] == "on"
        cur.execute("SHOW statement_timeout")
        assert cur.fetchone()[0] == "5s"
        cur.execute("SHOW search_path")
        assert cur.fetchone()[0] == "uil"
    finally:
        conn.close()


# ------------------------------------------------------------- the executor
def _run(db, org_id, sql, **kw):
    return run_readonly_query(db, org_id, sql, max_rows=kw.get("max_rows", 200), timeout_ms=kw.get("timeout_ms", 5000),
                              modules=ALL_MODULES, restricted=True)


def test_executor_returns_only_the_callers_data(uil_env, seeded_orgs, db_session):
    inv = next(v for v in VIEWS if v.name == "invoices")
    for key in ("a", "b"):
        org_id = seeded_orgs[key]["org_id"]
        result = _run(db_session, org_id, "SELECT count(*) AS n FROM uil.invoices")
        assert result.rows[0][0] == _expected_count(uil_env, inv, org_id)


def test_executor_clears_the_tenant_registration_afterwards(uil_env, seeded_orgs, db_session):
    _run(db_session, seeded_orgs["a"]["org_id"], "SELECT count(*) FROM uil.invoices")
    with uil_env.connect() as c:
        left = c.execute(text("SELECT count(*) FROM uil.session_context WHERE org_id = :o"),
                         {"o": seeded_orgs["a"]["org_id"]}).scalar()
    assert left == 0


def test_executor_clears_the_registration_even_when_the_query_fails(uil_env, seeded_orgs, db_session):
    with pytest.raises(UilExecutionError):
        _run(db_session, seeded_orgs["a"]["org_id"], "SELECT nonexistent_column FROM uil.invoices")
    with uil_env.connect() as c:
        assert c.execute(text("SELECT count(*) FROM uil.session_context WHERE org_id = :o"),
                         {"o": seeded_orgs["a"]["org_id"]}).scalar() == 0


def test_executor_survives_percent_and_colon_characters(uil_env, seeded_orgs, db_session):
    """AI-written SQL is full of both; they must reach the database untouched."""
    result = _run(db_session, seeded_orgs["a"]["org_id"],
                  "SELECT to_char(created_at, 'HH24:MI') AS t FROM uil.invoices WHERE status ILIKE '%paid%' LIMIT 3")
    assert len(result.rows) == 3


def test_executor_enforces_the_row_cap_and_reports_truncation(uil_env, seeded_orgs, db_session):
    result = _run(db_session, seeded_orgs["a"]["org_id"], "SELECT id FROM uil.invoices", max_rows=10)
    assert len(result.rows) == 10 and result.truncated is True


def test_executor_stops_runaway_queries(uil_env, seeded_orgs, db_session):
    with pytest.raises(UilExecutionError) as exc:
        _run(db_session, seeded_orgs["a"]["org_id"],
             "SELECT count(*) FROM uil.invoices a, uil.invoices b, uil.invoices c, uil.journal_lines d", timeout_ms=200)
    assert "too long" in exc.value.reason


def test_executor_never_runs_without_a_tenant(uil_env, seeded_orgs, db_session, monkeypatch):
    """If registering the tenant fails, the query must not run at all (fail closed)."""
    import app.services.intelligence.executor as ex

    def boom(*a, **k):
        raise RuntimeError("could not register tenant")

    monkeypatch.setattr(ex, "_register_tenant", boom)
    with pytest.raises(RuntimeError):
        _run(db_session, seeded_orgs["a"]["org_id"], "SELECT count(*) FROM uil.invoices")
