"""
Test infrastructure. Two real decisions worth explaining rather than
just doing:

1. A SEPARATE database, never the dev one. `TEST_DATABASE_URL` (falls
   back to a sensible local default) is a totally different database
   from whatever DATABASE_URL points at in .env — tests should never be
   able to touch real or even manually-tested dev data.

2. Real Alembic migrations, not Base.metadata.create_all(). This
   project's own established rule (see MANUAL.md Part 7/10) is that
   create_all() is untrustworthy for schema management — it can't alter
   existing tables, which caused a real Phase 4 bug. Running the actual
   migration chain here means every test run also re-proves every
   migration still applies cleanly to a fresh database, which create_all
   would silently skip entirely.

3. Isolation via unique orgs, not per-test transaction rollback. Almost
   every route in this app calls db.commit() directly inside the route
   function, not just at the very end of a request — self-healing
   lookups, multi-step actions, and the notification service all commit
   independently. A wrap-in-a-transaction-and-rollback pattern would
   fight that assumption throughout the codebase. Instead, tests share
   one long-lived test database for the whole run, and any test that
   needs an organization creates its own via signup() below with a
   unique subdomain — exactly the same pattern used throughout this
   project's own manual curl-based testing all along, just automated.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config

import app.main as main_module
from app.core.database import Base, get_db
from app.core.config import settings

TEST_DATABASE_URL = "postgresql://erp_test:erp_test@localhost:5432/erp_pytest_db"


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    """
    Runs once for the whole test session: points Alembic at the test
    database and runs the real migration chain against it, proving the
    chain works AND giving every test a real, correctly-shaped schema.
    """
    original_url = settings.DATABASE_URL
    settings.DATABASE_URL = TEST_DATABASE_URL

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import app.core.database as db_module

    test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    db_module.engine = test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(alembic_cfg, "head")

    yield

    settings.DATABASE_URL = original_url


@pytest.fixture
def client():
    """A FastAPI TestClient wired to the real app, real routes, real DB session per request."""
    return TestClient(main_module.app)


@pytest.fixture
def signup(client):
    """
    Returns a function a test calls to create a brand-new, uniquely-named
    org + Admin user, and get back a ready-to-use auth header. Every test
    that needs data gets its own isolated org this way — no test can ever
    see another test's data, without needing DB-level rollback machinery.
    """
    def _signup(org_name="Test Org"):
        unique = uuid.uuid4().hex[:12]
        resp = client.post("/api/auth/signup", json={
            "org_name": f"{org_name} {unique}",
            "subdomain": f"test{unique}",
            "admin_name": "Test Admin",
            "admin_email": f"admin-{unique}@test.com",
            "admin_password": "testpass123",
        })
        assert resp.status_code == 201, resp.text
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return _signup
