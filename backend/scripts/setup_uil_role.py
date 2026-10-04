"""
One-time (and re-runnable) setup of the read-only database login the
Unified Intelligence Layer's queries run as.

Run it:
  - once, after `alembic upgrade head` has created the `uil` schema, and
  - again after any later migration that adds or changes a uil view
    (it is idempotent, and it REMOVES access to anything no longer in the
    manifest).

Why a script and not a migration: a login role is cluster-wide and needs a
password, and secrets do not belong in migrations.

What it does NOT do: it never touches your data. It creates one login and
grants it SELECT on the 33 curated views, nothing else, then CHECKS the
resulting privileges and refuses to report success if any are wrong.

Usage (from the backend folder, venv active):

  PowerShell:
    $env:DATABASE_URL    = "<your PRIVILEGED connection string>"
    $env:UIL_DB_PASSWORD = "<16+ chars>"
    python scripts/setup_uil_role.py

  Generate a URL-safe password with:
    python -c "import secrets; print(secrets.token_hex(16))"

DANGER GUARD: like the seeder, it prints the target database and makes you
type its name, because this project has already been bitten once by a
DATABASE_URL left pointing at production.

Optionally set UIL_DATABASE_URL too and it will log in as the new role and run a
functional check.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine.url import make_url  # noqa: E402


def main():
    database_url = os.environ.get("DATABASE_URL")
    password = os.environ.get("UIL_DB_PASSWORD")
    if not database_url or not password:
        print("ERROR: set DATABASE_URL (privileged) and UIL_DB_PASSWORD (16+ chars) first.", file=sys.stderr)
        sys.exit(1)

    from app.services.intelligence.role_setup import ROLE_NAME, ensure_uil_role, smoke_test_login

    url = make_url(database_url)
    print(f"\nThis will create/update the login '{ROLE_NAME}' in:\n  host: {url.host}\n  database: {url.database}\n")
    if input(f"Type the database name ({url.database}) to confirm, anything else aborts: ").strip() != url.database:
        print("Aborted. Nothing was changed.")
        sys.exit(1)

    engine = create_engine(database_url)
    with engine.connect() as c:
        if not c.execute(text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'uil'")).scalar():
            print("ERROR: the 'uil' schema does not exist. Run `alembic upgrade head` first.", file=sys.stderr)
            sys.exit(1)

    timeout = int(os.environ.get("UIL_STATEMENT_TIMEOUT_MS", "5000"))
    try:
        ensure_uil_role(engine, password, statement_timeout_ms=timeout)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"\nOK: '{ROLE_NAME}' exists and its privileges were verified (SELECT on the curated views only).")

    uil_url = os.environ.get("UIL_DATABASE_URL")
    if uil_url:
        problems = smoke_test_login(uil_url)
        if problems:
            print("\nLogin check FAILED:\n  - " + "\n  - ".join(problems))
            sys.exit(1)
        print("Login check passed: it can log in, sees nothing without a tenant, and cannot read base tables.")
    else:
        print(f"\nNext: set UIL_DATABASE_URL to\n  postgresql://{ROLE_NAME}:<UIL_DB_PASSWORD>@{url.host}:{url.port or 5432}/{url.database}")
        print("(On Supabase's pooler the username may need to be  uil_readonly.<project-ref>.)")
        print("Then re-run this script with UIL_DATABASE_URL set to check the login works.")


if __name__ == "__main__":
    main()
