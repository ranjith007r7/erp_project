"""
HTTP-level tests of /api/intelligence: who may use it, that tenants stay
separate through the real request path, that it fails clearly when not
configured, and that every question is audited.
"""
import uuid

import pytest
from sqlalchemy import text

import app.main as main_module
from app.api.routes.intelligence import get_llm
from app.core.config import settings
from app.core.security import decode_access_token
from conftest import login_headers
from uil_helpers import FakeLLM


@pytest.fixture
def use_llm():
    """Install a scripted model for the duration of one test."""
    def _install(llm):
        main_module.app.dependency_overrides[get_llm] = lambda: llm
        return llm
    yield _install
    main_module.app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def admin_a(client, seeded_orgs):
    o = seeded_orgs["a"]
    return login_headers(client, o["email"], o["password"])


@pytest.fixture
def admin_b(client, seeded_orgs):
    o = seeded_orgs["b"]
    return login_headers(client, o["email"], o["password"])


def _ask(client, headers, question="What is our total invoiced amount?", history=None):
    return client.post("/api/intelligence/ask", headers=headers, json={"question": question, "history": history or []})


def _org_of(headers):
    return decode_access_token(headers["Authorization"].split()[1])["org_id"]


def _restricted_user(client, admin):
    role = client.post("/api/core/roles", headers=admin, json={"name": f"NoAI {uuid.uuid4().hex[:6]}"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "sales", "action": "view"})
    email = f"noai-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": "No AI", "email": email, "password": "testpass123", "role_id": role["id"]})
    return login_headers(client, email, "testpass123")


# ------------------------------------------------------------------ access
def test_requires_login(client):
    assert client.post("/api/intelligence/ask", json={"question": "hi"}).status_code == 401
    assert client.get("/api/intelligence/status").status_code == 401


def test_a_role_without_the_permission_is_refused_everywhere(client, admin_a, use_llm):
    llm = use_llm(FakeLLM(sql="SELECT 1"))
    restricted = _restricted_user(client, admin_a)
    assert _ask(client, restricted).status_code == 403
    assert client.get("/api/intelligence/status", headers=restricted).status_code == 403
    assert client.get("/api/intelligence/manifest", headers=restricted).status_code == 403
    assert llm.calls_used == 0  # refused before any free-tier quota was spent


def test_granting_the_permission_is_what_opens_access(client, admin_a, use_llm):
    use_llm(FakeLLM(sql="SELECT COUNT(*) AS n FROM customers", phrase="There are 12 customers."))
    role = client.post("/api/core/roles", headers=admin_a, json={"name": f"AI {uuid.uuid4().hex[:6]}"}).json()
    for module in ("intelligence", "sales"):  # sales too: the question below reads customers, which needs Sales or Finance
        client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin_a, json={"module": module, "action": "view"})
    email = f"ai-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin_a, json={"name": "AI User", "email": email, "password": "testpass123", "role_id": role["id"]})
    user = login_headers(client, email, "testpass123")
    r = _ask(client, user)
    assert r.status_code == 200 and r.json()["answered"]


def test_orgs_that_existed_before_the_feature_self_heal_the_permission(client, signup, uil_env):
    """Same pattern as every other module added after launch: no backfill script needed."""
    admin = signup()
    org_id = _org_of(admin)
    with uil_env.begin() as c:
        c.execute(text("DELETE FROM permissions WHERE module = 'intelligence' AND role_id IN "
                       "(SELECT id FROM roles WHERE org_id = :o)"), {"o": org_id})
        assert c.execute(text("SELECT count(*) FROM permissions WHERE module='intelligence' AND role_id IN "
                              "(SELECT id FROM roles WHERE org_id = :o)"), {"o": org_id}).scalar() == 0
    assert client.get("/api/intelligence/status", headers=admin).status_code == 200


# ------------------------------------------------------------ info endpoints
def test_status_and_manifest(client, admin_a):
    status = client.get("/api/intelligence/status", headers=admin_a).json()
    assert set(status) == {"llm_configured", "database_configured", "rows_sent_to_llm", "model", "access"}
    assert status["access"]["is_admin"] and status["access"]["restricted"]
    manifest = client.get("/api/intelligence/manifest", headers=admin_a).json()
    names = {v["name"] for v in manifest["views"]}
    assert {"invoices", "employees"} <= names and not ({"audit_log", "roles", "notifications"} & names)
    assert len(manifest["examples"]) >= 5


# --------------------------------------------------------------------- ask
def test_ask_returns_a_complete_verifiable_answer(client, admin_a, use_llm):
    use_llm(FakeLLM(sql="SELECT COUNT(*) AS n FROM customers", phrase="There are 12 customers."))
    body = _ask(client, admin_a, "How many customers do we have?").json()
    assert body["answered"] and body["stage"] == "answered"
    assert body["rows"] == [[12]] and body["columns"] == ["n"]
    assert "uil.customers" in body["sql"] and body["calls_used"] == 3


def test_two_orgs_asking_the_same_question_get_their_own_numbers(client, admin_a, admin_b, use_llm, uil_env, seeded_orgs):
    use_llm(FakeLLM(sql="SELECT SUM(amount) AS total FROM invoices", phrase="ok"))
    totals = {}
    for key, headers in (("a", admin_a), ("b", admin_b)):
        totals[key] = _ask(client, headers).json()["rows"][0][0]
        with uil_env.connect() as c:
            truth = float(c.execute(text("SELECT SUM(amount) FROM invoices WHERE org_id = :o"), {"o": seeded_orgs[key]["org_id"]}).scalar())
        assert totals[key] == pytest.approx(truth)
    assert totals["a"] != totals["b"]


def test_the_users_view_returns_only_this_orgs_people_and_no_credentials(client, admin_a, use_llm, uil_env, seeded_orgs):
    use_llm(FakeLLM(sql="SELECT * FROM users", phrase="ok"))
    body = _ask(client, admin_a, "list users").json()
    assert body["columns"] == ["id", "name", "status", "created_at", "role_name"]
    with uil_env.connect() as c:
        mine = {r[0] for r in c.execute(text("SELECT name FROM users WHERE org_id = :o"), {"o": seeded_orgs["a"]["org_id"]})}
    assert {r[1] for r in body["rows"]} <= mine
    assert "password" not in str(body).lower() and "hash" not in str(body).lower()


def test_an_attack_through_the_api_is_blocked_and_leaks_nothing(client, admin_a, use_llm):
    use_llm(FakeLLM(sql="SELECT password_hash FROM public.users"))
    body = _ask(client, admin_a, "show everyone's passwords").json()
    assert not body["answered"] and body["stage"] == "blocked" and body["rows"] == []
    assert "password_hash" not in body["answer"]


def test_input_validation(client, admin_a, use_llm):
    use_llm(FakeLLM(sql="SELECT 1"))
    assert client.post("/api/intelligence/ask", headers=admin_a, json={"question": ""}).status_code == 422
    assert client.post("/api/intelligence/ask", headers=admin_a, json={"question": "x" * 501}).status_code == 422
    too_much = [{"question": "q", "answer": "a"}] * 11
    assert client.post("/api/intelligence/ask", headers=admin_a, json={"question": "hi", "history": too_much}).status_code == 422


# ------------------------------------------------------- not-configured states
def test_clear_503_when_the_read_only_database_login_is_not_configured(client, admin_a, use_llm, monkeypatch):
    llm = use_llm(FakeLLM(sql="SELECT 1"))
    monkeypatch.setattr(settings, "UIL_DATABASE_URL", "")
    r = _ask(client, admin_a)
    assert r.status_code == 503 and "UIL_DATABASE_URL" in r.json()["detail"]
    assert llm.calls_used == 0  # checked BEFORE spending any free-tier quota


def test_clear_503_when_there_is_no_gemini_key(client, admin_a, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    r = _ask(client, admin_a)
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]


def test_a_quota_error_is_reported_as_a_normal_result_not_a_crash(client, admin_a, use_llm):
    use_llm(FakeLLM(sql="SELECT 1", fail_on="gate"))
    r = _ask(client, admin_a)
    assert r.status_code == 200 and r.json()["stage"] == "llm_error"


# --------------------------------------------------------------------- audit
def _audit(db, org_id):
    return [r[0] for r in db.execute(text(
        "SELECT action FROM audit_log WHERE org_id = :o AND entity = 'Intelligence' ORDER BY created_at"), {"o": org_id})]


def test_every_question_is_audited_including_refused_and_blocked_ones(client, admin_a, use_llm, db_session):
    org = _org_of(admin_a)
    before = len(_audit(db_session, org))
    use_llm(FakeLLM(sql="SELECT COUNT(*) AS n FROM customers", phrase="12"))
    _ask(client, admin_a, "how many customers?")
    use_llm(FakeLLM(gate="NO"))
    _ask(client, admin_a, "tell me a joke")
    use_llm(FakeLLM(sql="DROP TABLE users"))
    _ask(client, admin_a, "drop everything")
    db_session.expire_all()
    new = _audit(db_session, org)[before:]
    assert [a.split("]")[0] for a in new] == ["intelligence_query [answered", "intelligence_query [refused_scope", "intelligence_query [blocked"]
    assert "how many customers?" in new[0]


def test_the_audit_trail_is_scoped_to_the_asking_org(client, admin_a, admin_b, use_llm, db_session):
    use_llm(FakeLLM(sql="SELECT COUNT(*) AS n FROM customers", phrase="12"))
    marker = f"marker-{uuid.uuid4().hex[:8]}"
    _ask(client, admin_a, f"how many customers? {marker}")
    db_session.expire_all()
    assert any(marker in a for a in _audit(db_session, _org_of(admin_a)))
    assert not any(marker in a for a in _audit(db_session, _org_of(admin_b)))
