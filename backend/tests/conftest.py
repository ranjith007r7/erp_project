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
import os
import uuid

# These must be set BEFORE `import app.main` below, because that import
# chain instantiates app.core.config.settings at module level - and
# Settings.JWT_SECRET_KEY now has no default (see config.py's docstring
# on why), so importing the app at all would crash immediately without
# this. setdefault() means a real CI-provided value always wins if one's
# already set (see .github/workflows/ci.yml).
os.environ.setdefault("JWT_SECRET_KEY", "pytest_test_secret_key_not_for_production")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")
# Security features are switched ON by default in the app; the shared test fixtures create hundreds of
# organizations from one address with no inbox, so these are relaxed here and the dedicated tests
# (test_signup_protection.py, test_admin_portal_2fa.py) turn them on one at a time.
os.environ.setdefault("ADMIN_2FA_REQUIRED", "false")
os.environ.setdefault("REQUIRE_VERIFIED_EMAIL_FOR_API", "false")
os.environ.setdefault("SIGNUP_MAX_PER_IP_PER_HOUR", "100000")
os.environ.setdefault("SIGNUP_MAX_PER_DAY", "100000")

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


def login_any(client, email, password):
    """Sign in without caring which portal the account belongs to (tests only). Retries the other portal when told to."""
    for portal in ("employee", "admin"):
        resp = client.post("/api/auth/login", json={"email": email, "password": password, "portal": portal})
        if resp.status_code == 403 and "sign-in page" in resp.json().get("detail", ""):
            continue
        return resp
    return resp


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


# ---------------------------------------------------------------------------
# Unified Intelligence Layer fixtures (only requested by test_uil_*.py)
# ---------------------------------------------------------------------------
UIL_TEST_PASSWORD = "uil_test_password_123"
UIL_TEST_URL = f"postgresql://uil_readonly:{UIL_TEST_PASSWORD}@localhost:5432/erp_pytest_db"


@pytest.fixture(scope="session")
def uil_env(apply_migrations):
    """
    Creates the real uil_readonly login in the test database (idempotent),
    points the app at it, and yields a PRIVILEGED engine for tests that need to
    inspect or arrange data directly. Nothing here is mocked: the same role
    setup code that production uses.
    """
    from sqlalchemy import create_engine
    from app.services.intelligence.role_setup import ensure_uil_role

    admin_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    ensure_uil_role(admin_engine, UIL_TEST_PASSWORD)
    original = settings.UIL_DATABASE_URL
    settings.UIL_DATABASE_URL = UIL_TEST_URL
    yield admin_engine
    settings.UIL_DATABASE_URL = original
    admin_engine.dispose()


@pytest.fixture(scope="session")
def seeded_orgs(uil_env):
    """
    Two fully populated synthetic organizations (a year of history across every
    module), seeded with DIFFERENT random seeds so their numbers differ. Used to
    prove tenant isolation against realistic data, not 5-row toy orgs.
    """
    import importlib.util
    import app.core.database as db_module

    spec = importlib.util.spec_from_file_location("seed_uil_demo_data", "scripts/seed_uil_demo_data.py")
    seeder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seeder)

    orgs = {}
    for key, seed in (("a", 11), ("b", 22)):
        db = db_module.SessionLocal()
        try:
            subdomain = f"uilseed{key}{uuid.uuid4().hex[:8]}"
            email = f"admin@{subdomain}.example.com"
            org_id = seeder.seed_demo_org(
                db, org_name=f"Seed Org {key.upper()}", subdomain=subdomain,
                admin_email=email, admin_password="DemoPass123!", seed=seed,
            )
            orgs[key] = {"org_id": org_id, "email": email, "password": "DemoPass123!"}
        finally:
            db.close()
    return orgs


@pytest.fixture
def db_session():
    """A plain privileged session on the test database."""
    import app.core.database as db_module

    db = db_module.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def login_headers(client, email, password):
    resp = login_any(client, email, password)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# Smallest valid-enough proof files for the receiving flow.
def _make_png() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


PNG_BYTES = _make_png()
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def receive_po(client, headers, po_id):
    """Approve (if still pending) and receive a PO in good condition - the legacy one-click receive."""
    r = client.post(f"/api/procurement/purchase-orders/{po_id}/approve", headers=headers)
    assert r.status_code in (200, 400), r.text
    r = client.post(
        f"/api/procurement/purchase-orders/{po_id}/receive-good", headers=headers,
        files={"invoice": ("inv.pdf", PDF_BYTES, "application/pdf"), "pod": ("pod.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r
