"""
Creates (or repairs) the dedicated read-only database login the AI's
queries run as, and gives it exactly SELECT on the curated views.

This is LAYER TWO of the safety design, and it is independent of the
application-level SQL validator (safety.py): even if the validator had
a bug and let something nasty through, this login physically cannot:

  - write anything        (no INSERT/UPDATE/DELETE/DDL grant, and
                           default_transaction_read_only = on)
  - read base tables      (no grant on schema public at all, so
                           users.password_hash is unreachable, not merely
                           "hidden by the prompt")
  - change its tenant     (no access to uil.session_context, which only the
                           privileged application login can write)
  - hang the database     (statement_timeout, idle timeout, small
                           connection limit)

Idempotent on purpose: run it again after any migration that adds or
changes a view, and it re-asserts the same grants.

Why a script/function and not an Alembic migration: a login role is
cluster-wide and needs a password, and secrets do not belong in
migrations. Same reasoning as scripts/grandfather_existing_users.py.
"""
from psycopg2 import sql

from app.services.intelligence.manifest import VIEWS

ROLE_NAME = "uil_readonly"


def ensure_uil_role(engine, password: str, *, statement_timeout_ms: int = 5000) -> None:
    """
    `engine` must connect as a role allowed to create roles and grant on the
    uil schema (the same login the app and Alembic already use).
    """
    if not password or len(password) < 12:
        raise ValueError("Choose a UIL database password of at least 12 characters.")

    raw = engine.raw_connection()
    try:
        # One transaction, committed explicitly at the end: either the whole
        # role setup applies or none of it does. (An earlier draft set
        # `raw.autocommit = True` on the pooled wrapper, which does NOT reach
        # the real connection - the DDL ran in a transaction that was rolled
        # back on return to the pool, and the script reported success while
        # creating nothing. verify_uil_role() below exists so a silent no-op
        # can never happen again.)
        cur = raw.cursor()

        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE_NAME,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(
            sql.SQL(
                "{verb} ROLE {role} WITH LOGIN PASSWORD {pw} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 10"
            ).format(verb=sql.SQL(verb), role=sql.Identifier(ROLE_NAME), pw=sql.Literal(password))
        )

        role = sql.Identifier(ROLE_NAME)
        # Start from nothing, then grant back only what is needed. Revoking
        # first means re-running this after a manifest change also REMOVES
        # access to anything no longer listed.
        for stmt in (
            "REVOKE ALL ON SCHEMA public FROM {role}",
            "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}",
            "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}",
            "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {role}",
            "REVOKE ALL ON SCHEMA uil FROM {role}",
            "REVOKE ALL ON ALL TABLES IN SCHEMA uil FROM {role}",
            "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA uil FROM {role}",
            "GRANT USAGE ON SCHEMA uil TO {role}",
            # Views check EXECUTE on functions they call against the person
            # QUERYING the view (unlike tables, which are checked as the view
            # owner). So the login needs this one function. It is safe: it
            # takes no arguments, runs as its owner only to read one row keyed
            # by the caller's own backend PID, and can only ever return the
            # caller's own tenant.
            "GRANT EXECUTE ON FUNCTION uil.current_org() TO {role}",
            # Same reasoning for the per-user access check every view now calls. It takes
            # arguments, but it only ever reports facts about the CALLER'S OWN registered
            # context, so calling it directly reveals nothing and changes nothing.
            "GRANT EXECUTE ON FUNCTION uil.can_read(text[], boolean) TO {role}",
        ):
            cur.execute(sql.SQL(stmt).format(role=role))

        for view in VIEWS:
            cur.execute(
                sql.SQL("GRANT SELECT ON {schema}.{view} TO {role}").format(
                    schema=sql.Identifier("uil"), view=sql.Identifier(view.name), role=role
                )
            )

        # Role-level defaults apply to every NEW session of this login.
        for stmt, value in (
            ("default_transaction_read_only", "on"),
            ("statement_timeout", f"{int(statement_timeout_ms)}ms"),
            ("idle_in_transaction_session_timeout", "15s"),
            ("search_path", "uil"),
        ):
            cur.execute(
                sql.SQL("ALTER ROLE {role} SET {param} = {val}").format(
                    role=role, param=sql.Identifier(stmt), val=sql.Literal(value)
                )
            )
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()

    problems = verify_uil_role(engine)
    if problems:
        raise RuntimeError("UIL role setup did not produce the intended privileges:\n  - " + "\n  - ".join(problems))


def verify_uil_role(engine) -> list[str]:
    """
    Checks the role's ACTUAL effective privileges (including anything it
    inherits from PUBLIC, which a plain grant list would miss) and returns a
    list of problems; an empty list means the isolation guarantees hold.
    """
    from sqlalchemy import text

    problems: list[str] = []
    with engine.connect() as c:
        role = c.execute(
            text("SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = :r"),
            {"r": ROLE_NAME},
        ).fetchone()
        if role is None:
            return [f"role {ROLE_NAME} does not exist"]
        if not role.rolcanlogin:
            problems.append("role cannot log in")
        if role.rolsuper or role.rolcreaterole or role.rolcreatedb:
            problems.append("role has elevated attributes (superuser/createrole/createdb)")

        def priv(sql_text, **params):
            return c.execute(text(sql_text), params).scalar()

        if not priv("SELECT has_schema_privilege(:r, 'uil', 'USAGE')", r=ROLE_NAME):
            problems.append("no USAGE on schema uil")
        if priv("SELECT has_schema_privilege(:r, 'uil', 'CREATE')", r=ROLE_NAME):
            problems.append("role can CREATE objects in schema uil")

        for view in VIEWS:
            qualified = f"uil.{view.name}"
            if not priv("SELECT has_table_privilege(:r, :t, 'SELECT')", r=ROLE_NAME, t=qualified):
                problems.append(f"cannot SELECT {qualified}")
            for write in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                if priv("SELECT has_table_privilege(:r, :t, :p)", r=ROLE_NAME, t=qualified, p=write):
                    problems.append(f"can {write} {qualified}")

        leaked = priv(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r','v','m','p') "
            "AND has_table_privilege(:r, c.oid, 'SELECT')",
            r=ROLE_NAME,
        )
        if leaked:
            problems.append(f"can SELECT {leaked} table(s)/view(s) in schema public (base tables must be unreachable)")

        for write in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            if priv("SELECT has_table_privilege(:r, 'uil.session_context', :p)", r=ROLE_NAME, p=write):
                problems.append(f"can {write} uil.session_context (tenant context must be writable only by the app)")
        if not priv("SELECT has_function_privilege(:r, 'uil.current_org()', 'EXECUTE')", r=ROLE_NAME):
            problems.append("cannot EXECUTE uil.current_org() (every view calls it, so every query would fail)")
        if not priv("SELECT has_function_privilege(:r, 'uil.can_read(text[], boolean)', 'EXECUTE')", r=ROLE_NAME):
            problems.append("cannot EXECUTE uil.can_read() (every view calls it, so every query would fail)")
    return problems


def smoke_test_login(database_url: str) -> list[str]:
    """
    FUNCTIONAL check, complementing the privilege check above: actually log in
    as the read-only role and run real queries. Privilege lists alone once
    missed a role that was too locked down to work at all, so this proves it
    works AND that it fails closed. Returns a list of problems (empty = good).
    """
    from sqlalchemy import create_engine, text

    problems: list[str] = []
    eng = create_engine(database_url, pool_pre_ping=True)
    try:
        with eng.connect() as c:
            # No tenant context is set for a fresh connection, so a working,
            # correctly isolated setup returns ZERO rows (not an error, and
            # certainly not every tenant's rows).
            n = c.execute(text("SELECT count(*) FROM uil.invoices")).scalar()
            if n != 0:
                problems.append(f"a connection with no tenant context saw {n} invoice row(s); expected 0 (must fail closed)")
            if c.execute(text("SHOW default_transaction_read_only")).scalar() != "on":
                problems.append("default_transaction_read_only is not on for this login")
            try:
                c.execute(text("SELECT count(*) FROM public.users")).scalar()
                problems.append("this login CAN read public.users")
            except Exception:
                pass
    except Exception as exc:
        problems.append(f"could not log in and query as the read-only role: {str(exc).splitlines()[0]}")
    finally:
        eng.dispose()
    return problems
