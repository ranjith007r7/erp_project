"""
Per-user access control for Ask Data ("two ticks on the existing row").

  view     use Ask Data on the modules the role can already open
  approve  ALSO ask about restricted data (salary, payroll); additional, never a
           substitute for module access

The rule: Ask Data never shows a person more than the normal screens would.
Enforced in three independent places (prompt, validator, database), and each is
tested on its own below, including with the first two deliberately disabled.
"""
import uuid

import psycopg2
import pytest
from sqlalchemy import text

import app.main as main_module
from app.api.routes.intelligence import get_llm
from app.services.intelligence import pipeline as pl
from app.services.intelligence.access import AccessProfile, denial_message
from app.services.intelligence.manifest import (
    ACCESS, ALL_MODULES, EXAMPLES, VIEWS, VIEWS_BY_NAME, example_questions,
)
from app.services.intelligence.safety import AccessDeniedError, UnsafeQueryError, validate_sql
from conftest import UIL_TEST_URL, login_headers
from uil_helpers import FakeLLM

RESTRICTED = {"employee_pay", "payroll_runs", "payslips"}


# ------------------------------------------------------------ the access table
def test_exactly_the_pay_views_are_restricted():
    assert {v.name for v in VIEWS if v.restricted} == RESTRICTED


def test_every_restricted_view_also_requires_the_hr_module_so_approve_alone_is_never_enough():
    for name in RESTRICTED:
        assert VIEWS_BY_NAME[name].access == ("hr",)


def test_salary_exists_in_exactly_one_view():
    holders = [v.name for v in VIEWS if any(c.name == "salary" for c in v.columns)]
    assert holders == ["employee_pay"]
    assert not any(c.name == "salary" for c in VIEWS_BY_NAME["employees"].columns)


def test_every_access_rule_names_only_real_modules():
    known = {"crm", "sales", "finance", "inventory", "hr", "procurement", "projects", "core"}
    for name, (modules, _restricted) in ACCESS.items():
        assert modules and set(modules) <= known, name


def _profile(modules, restricted=False):
    return AccessProfile(modules=frozenset(modules), restricted=restricted)


# Written BY HAND from "which screens already show this data", independently of the ACCESS table.
EXPECTED = {
    "nothing": (_profile([]), set()),
    "inventory only": (_profile(["inventory"]),
                       {"products", "product_categories", "warehouses", "stock_levels", "stock_movements"}),
    "hr, not approved": (_profile(["hr"]), {"departments", "employees", "attendance", "leave_requests", "users"}),
    "hr + approved": (_profile(["hr"], True),
                      {"departments", "employees", "attendance", "leave_requests", "users"} | RESTRICTED),
    "approved but NO hr": (_profile(["inventory", "sales"], True),
                           {"products", "product_categories", "warehouses", "stock_levels", "stock_movements",
                            "crm_accounts", "customers", "quotations", "quotation_items", "sales_orders",
                            "sales_order_items", "invoices"}),
    "finance only": (_profile(["finance"]),
                     {"customers", "invoices", "chart_of_accounts", "journal_entries", "journal_lines", "payments"}),
}


@pytest.mark.parametrize("label", list(EXPECTED))
def test_each_profile_may_read_exactly_the_hand_written_set(label):
    profile, expected = EXPECTED[label]
    assert profile.allowed_names() == expected


def test_admin_profile_reads_everything():
    assert AccessProfile.full().allowed_names() == set(VIEWS_BY_NAME)


def test_denial_messages_say_what_is_missing_in_plain_words():
    basic = _profile(["inventory"])
    assert "HR module" in denial_message(["payslips"], basic) and "approve" in denial_message(["payslips"], basic)
    assert "Sales or Finance" in denial_message(["invoices"], basic)
    hr_only = _profile(["hr"])
    msg = denial_message(["employee_pay"], hr_only)
    assert "approve" in msg and "HR module" not in msg      # they already have HR: only say what is actually missing
    assert "administrator" in msg


# ------------------------------------------------------------------- validator
def test_validator_denies_a_view_the_user_may_not_read():
    with pytest.raises(AccessDeniedError) as exc:
        validate_sql("SELECT * FROM payslips", max_rows=200, allowed_views=frozenset({"employees"}))
    assert exc.value.views == ["payslips"]


@pytest.mark.parametrize("sql", [
    "SELECT * FROM uil.payslips",                                           # schema-qualified
    "SELECT * FROM payslips p JOIN employees e ON e.id = p.employee_id",    # one allowed, one not
    "WITH t AS (SELECT * FROM payslips) SELECT * FROM t",                   # hidden inside a CTE
    "SELECT name FROM employees UNION SELECT employee_id::text FROM payslips",
    'SELECT * FROM "payslips"',
])
def test_every_way_of_naming_a_denied_view_is_caught(sql):
    with pytest.raises(AccessDeniedError):
        validate_sql(sql, max_rows=200, allowed_views=frozenset({"employees"}))


def test_only_the_denied_views_are_reported():
    with pytest.raises(AccessDeniedError) as exc:
        validate_sql("SELECT * FROM employees e JOIN payslips p ON p.employee_id = e.id", max_rows=200,
                     allowed_views=frozenset({"employees"}))
    assert exc.value.views == ["payslips"]


def test_no_restriction_is_applied_when_allowed_views_is_none():
    validate_sql("SELECT * FROM payslips", max_rows=200, allowed_views=None)


def test_a_denial_is_not_a_safety_error_so_it_can_never_be_retried_away():
    assert not issubclass(AccessDeniedError, UnsafeQueryError)


def test_a_malicious_query_is_reported_as_malicious_not_as_a_permissions_problem():
    with pytest.raises(UnsafeQueryError):
        validate_sql("SELECT pg_sleep(5) FROM payslips", max_rows=200, allowed_views=frozenset({"employees"}))


# ------------------------------------------------------------ prompt filtering
def test_a_basic_users_prompt_never_contains_pay_data_or_definitions():
    prompt = pl._sql_prompt("how much stock?", _profile(["inventory"]))
    for leaked in ("net_pay", "employee_pay", "payslips", "salary", "Payroll cost", "average salary"):
        assert leaked.lower() not in prompt.lower().split("not available to this user (never query these)")[0], leaked
    assert "stock_levels" in prompt and "quantity integer" in prompt


def test_locked_views_appear_by_name_and_description_only_never_with_columns():
    prompt = pl._sql_prompt("q", _profile(["inventory"]))
    section = prompt.split("NOT AVAILABLE TO THIS USER (never query these)")[1].split("EXAMPLES:")[0]
    assert "payslips" in section and "employee_pay" in section
    assert "net_pay" not in section and "salary numeric" not in section


def test_an_admins_prompt_has_everything_and_no_locked_section():
    prompt = pl._sql_prompt("q", AccessProfile.full())
    assert "NOT AVAILABLE" not in prompt and "DENIED" not in prompt   # nothing locked, so nothing mentioned
    assert "net_pay" in prompt and "salary" in prompt


def test_only_examples_the_user_can_run_are_shown_or_suggested():
    assert example_questions(_profile(["inventory"]).allowed_names()) == ["Which products are low on stock?"]
    all_q = example_questions(AccessProfile.full().allowed_names())
    assert len(all_q) == len(EXAMPLES)
    hr_only = example_questions(_profile(["hr"]).allowed_names())
    assert not any("salary" in q or "payroll" in q for q in hr_only)


# ----------------------------------------------- the DATABASE enforces it alone
def _connect():
    return psycopg2.connect(UIL_TEST_URL)


@pytest.fixture(autouse=True)
def _clean_registrations(uil_env):
    with uil_env.begin() as c:
        c.execute(text("TRUNCATE uil.session_context"))
    yield
    with uil_env.begin() as c:
        c.execute(text("TRUNCATE uil.session_context"))


def _register(admin, conn, org_id, modules, restricted):
    cur = conn.cursor()
    cur.execute("SELECT pg_backend_pid()")
    pid = cur.fetchone()[0]
    conn.rollback()
    with admin.begin() as c:
        c.execute(text("INSERT INTO uil.session_context (backend_pid, org_id, modules, restricted) VALUES (:p,:o,:m,:r)"),
                  {"p": pid, "o": org_id, "m": sorted(modules), "r": restricted})
    return pid


def _truth(admin, view, org_id):
    with admin.connect() as c:
        if view.via is None:
            sql = f"SELECT count(*) FROM public.{view.base} WHERE org_id = :o"
        else:
            parent, fk = view.via
            sql = f"SELECT count(*) FROM public.{view.base} c JOIN public.{parent} p ON p.id = c.{fk} WHERE p.org_id = :o"
        return c.execute(text(sql), {"o": org_id}).scalar()


@pytest.mark.parametrize("label", list(EXPECTED))
def test_database_alone_returns_rows_only_for_views_the_profile_may_read(uil_env, seeded_orgs, label):
    """No validator, no prompts: straight to the database as the real read-only login."""
    profile, _ = EXPECTED[label]
    org = seeded_orgs["a"]["org_id"]
    conn = _connect()
    try:
        _register(uil_env, conn, org, profile.modules, profile.restricted)
        cur = conn.cursor()
        visible_with_data = 0
        for v in VIEWS:
            cur.execute(f"SELECT count(*) FROM uil.{v.name}")
            seen = cur.fetchone()[0]
            conn.rollback()
            want = _truth(uil_env, v, org) if profile.allows(v) else 0
            assert seen == want, f"{label}: {v.name} returned {seen}, expected {want}"
            visible_with_data += 1 if seen else 0
        assert visible_with_data == (0 if label == "nothing" else visible_with_data)
    finally:
        conn.close()


def _counts(conn, views):
    cur, out = conn.cursor(), {}
    for v in views:
        cur.execute(f"SELECT count(*) FROM uil.{v}")
        out[v] = cur.fetchone()[0]
        conn.rollback()
    return out


@pytest.mark.parametrize("modules,restricted,employees,pay", [
    (["hr"], False, True, False),           # HR but not approved: sees people, not pay
    (["hr"], True, True, True),             # HR and approved: sees both
    (["sales", "inventory"], True, False, False),   # approved but no HR: sees NEITHER (approve is not a substitute)
    ([], True, False, False),
    (["inventory"], False, False, False),
])
def test_salary_and_payroll_are_unreachable_without_both_hr_and_approve(uil_env, seeded_orgs, modules, restricted, employees, pay):
    conn = _connect()
    try:
        _register(uil_env, conn, seeded_orgs["a"]["org_id"], modules, restricted)
        c = _counts(conn, ["employees", "employee_pay", "payslips", "payroll_runs"])
        assert (c["employees"] > 0) == employees
        for pay_view in ("employee_pay", "payslips", "payroll_runs"):
            assert (c[pay_view] > 0) == pay, f"{pay_view} with modules={modules} restricted={restricted}"
    finally:
        conn.close()


def test_a_user_cannot_grant_themselves_access_by_editing_their_context(uil_env, seeded_orgs):
    conn = _connect()
    try:
        _register(uil_env, conn, seeded_orgs["a"]["org_id"], ["inventory"], False)
        cur = conn.cursor()
        for attack in ("UPDATE uil.session_context SET restricted = true",
                       "UPDATE uil.session_context SET modules = ARRAY['hr','finance']",
                       "INSERT INTO uil.session_context (backend_pid, org_id, modules, restricted) "
                       "VALUES (1, gen_random_uuid(), ARRAY['hr'], true)"):
            with pytest.raises(psycopg2.Error):
                cur.execute(attack)
            conn.rollback()
        assert _counts(conn, ["payslips"])["payslips"] == 0
    finally:
        conn.close()


def test_the_access_check_function_only_reports_the_callers_own_context(uil_env, seeded_orgs):
    conn = _connect()
    try:
        _register(uil_env, conn, seeded_orgs["a"]["org_id"], ["hr"], False)
        cur = conn.cursor()
        cur.execute("SELECT uil.can_read(ARRAY['hr'], false), uil.can_read(ARRAY['hr'], true), uil.can_read(ARRAY['finance'], false)")
        assert cur.fetchone() == (True, False, False)
    finally:
        conn.close()


def test_the_database_still_enforces_a_users_access_even_if_the_validator_has_a_bug(uil_env, seeded_orgs, db_session, monkeypatch):
    """
    Defense in depth, proven rather than assumed: disable the application's per-user check
    (as if validate_sql had a bug that let a denied view through) and ask for salaries as a
    user with no pay access. The database returns nothing, so nothing can leak.
    """
    real = pl.validate_sql
    monkeypatch.setattr(pl, "validate_sql", lambda sql, **kw: real(sql, max_rows=kw["max_rows"], allowed_views=None))
    basic = _profile(["inventory"])
    llm = FakeLLM(sql="SELECT salary FROM employee_pay", phrase="ok")
    r = pl.answer_question(db_session, seeded_orgs["a"]["org_id"], "what do people earn?", None, llm, basic)
    assert not r.answered and r.stage == pl.NO_DATA and r.rows == []
    assert "phrase" not in llm.kinds


# ------------------------------------------------------------------ HTTP level
@pytest.fixture
def use_llm():
    def _install(llm):
        main_module.app.dependency_overrides[get_llm] = lambda: llm
        return llm
    yield _install
    main_module.app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def admin_a(client, seeded_orgs):
    o = seeded_orgs["a"]
    return login_headers(client, o["email"], o["password"])


def _user_with(client, admin, perms):
    """A brand-new role holding exactly `perms` [(module, action)...], and a logged-in user in it."""
    role = client.post("/api/core/roles", headers=admin, json={"name": f"R{uuid.uuid4().hex[:8]}"}).json()
    ids = {}
    for module, action in perms:
        r = client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": module, "action": action})
        ids[(module, action)] = r.json()["id"]
    email = f"u-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": "T User", "email": email, "password": "testpass123", "role_id": role["id"]})
    return login_headers(client, email, "testpass123"), role["id"], ids


def _ask(client, headers, question="q"):
    return client.post("/api/intelligence/ask", headers=headers, json={"question": question}).json()


Q_STOCK = "SELECT COUNT(*) AS n FROM stock_levels"
Q_PAYSLIPS = "SELECT COUNT(*) AS n FROM payslips"
Q_PAY = "SELECT COUNT(*) AS n FROM employee_pay"
Q_PEOPLE = "SELECT COUNT(*) AS n FROM employees"
Q_INVOICES = "SELECT COUNT(*) AS n FROM invoices"


def test_a_basic_inventory_user_can_ask_about_stock_but_not_hr_or_invoices_or_pay(client, admin_a, use_llm):
    user, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("inventory", "view")])
    use_llm(FakeLLM(sql=Q_STOCK, phrase="ok"))
    ok = _ask(client, user, "how much stock do we have?")
    assert ok["answered"] and ok["rows"][0][0] > 0

    for sql, must_mention in ((Q_PAYSLIPS, ("HR module", "approve")), (Q_PAY, ("HR module", "approve")),
                              (Q_PEOPLE, ("HR module",)), (Q_INVOICES, ("Sales or Finance",))):
        llm = use_llm(FakeLLM(sql=sql, phrase="ok"))
        r = _ask(client, user, "tell me")
        assert not r["answered"] and r["stage"] == "denied", sql
        assert r["rows"] == [] and r["sql"] is None, "a denial must not reveal rows or the SQL"
        for phrase in must_mention:
            assert phrase in r["answer"], (sql, phrase)
        assert llm.kinds == ["gate", "sql"], "a denial is final: no retry, no phrasing"


def test_hr_without_approve_sees_people_but_not_pay(client, admin_a, use_llm):
    user, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("hr", "view")])
    use_llm(FakeLLM(sql=Q_PEOPLE, phrase="ok"))
    assert _ask(client, user)["answered"]
    for sql in (Q_PAY, Q_PAYSLIPS, "SELECT COUNT(*) AS n FROM payroll_runs"):
        use_llm(FakeLLM(sql=sql))
        r = _ask(client, user)
        assert r["stage"] == "denied" and "approve" in r["answer"] and "HR module" not in r["answer"], sql


def test_hr_plus_approve_can_ask_about_pay(client, admin_a, use_llm):
    user, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("intelligence", "approve"), ("hr", "view")])
    for sql in (Q_PAY, Q_PAYSLIPS, EXAMPLES[-1][1]):
        use_llm(FakeLLM(sql=sql, phrase="ok"))
        r = _ask(client, user)
        assert r["answered"], (sql, r["answer"])


def test_approve_without_the_hr_module_opens_nothing(client, admin_a, use_llm):
    user, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("intelligence", "approve"), ("sales", "view")])
    for sql in (Q_PAY, Q_PAYSLIPS):
        use_llm(FakeLLM(sql=sql))
        r = _ask(client, user)
        assert r["stage"] == "denied" and "HR module" in r["answer"]
    use_llm(FakeLLM(sql=Q_INVOICES, phrase="ok"))
    assert _ask(client, user)["answered"]            # ...but Sales data still works


def test_approve_alone_without_the_view_tick_cannot_even_reach_the_feature(client, admin_a, use_llm):
    user, _, _ = _user_with(client, admin_a, [("intelligence", "approve"), ("hr", "view")])
    use_llm(FakeLLM(sql=Q_PAY))
    assert client.post("/api/intelligence/ask", headers=user, json={"question": "q"}).status_code == 403


def test_admin_can_ask_about_everything_including_pay(client, admin_a, use_llm):
    for sql in (Q_STOCK, Q_PAYSLIPS, Q_PAY, Q_PEOPLE, Q_INVOICES):
        use_llm(FakeLLM(sql=sql, phrase="ok"))
        assert _ask(client, admin_a)["answered"], sql


def test_pay_answers_are_this_orgs_data_even_for_an_approved_user(client, admin_a, use_llm, uil_env, seeded_orgs):
    user, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("intelligence", "approve"), ("hr", "view")])
    use_llm(FakeLLM(sql="SELECT SUM(net_pay) AS total FROM payslips", phrase="ok"))
    got = _ask(client, user)["rows"][0][0]
    sums = {}
    with uil_env.connect() as c:
        for key in ("a", "b"):
            sums[key] = float(c.execute(text(
                "SELECT SUM(ps.net_pay) FROM payslips ps JOIN payroll_runs pr ON pr.id = ps.payroll_run_id "
                "WHERE pr.org_id = :o"), {"o": seeded_orgs[key]["org_id"]}).scalar())
    assert got == pytest.approx(sums["a"]) and got != pytest.approx(sums["b"])


def test_a_denial_message_from_the_model_is_honoured_only_when_it_is_true(client, admin_a, use_llm):
    basic, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("inventory", "view")])
    llm = use_llm(FakeLLM(sql="DENIED: payslips"))
    r = _ask(client, basic)
    assert r["stage"] == "denied" and llm.kinds == ["gate", "sql"]

    # An admin CAN read payslips, so a model claiming DENIED is simply wrong: it must not refuse them.
    llm = use_llm(FakeLLM(sql=["DENIED: payslips", Q_PAYSLIPS], phrase="ok"))
    r = _ask(client, admin_a)
    assert r["answered"] and llm.kinds == ["gate", "sql", "sql", "phrase"]


def test_a_model_denying_a_view_that_does_not_exist_cannot_refuse_anyone(client, admin_a, use_llm):
    basic, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("inventory", "view")])
    use_llm(FakeLLM(sql="DENIED: not_a_real_view"))
    r = _ask(client, basic)
    assert r["stage"] == "blocked"       # treated as a bad query, never as a permissions refusal


def test_the_model_is_only_shown_what_this_user_may_read(client, admin_a, use_llm):
    basic, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("inventory", "view")])
    llm = use_llm(FakeLLM(sql=Q_STOCK, phrase="ok"))
    _ask(client, basic)
    sql_prompt = llm.prompts[llm.kinds.index("sql")]
    assert "net_pay" not in sql_prompt and "salary numeric" not in sql_prompt and "quantity integer" in sql_prompt


def test_revoking_a_tick_takes_effect_on_the_very_next_question(client, admin_a, use_llm):
    user, role_id, perm_ids = _user_with(client, admin_a, [("intelligence", "view"), ("intelligence", "approve"), ("hr", "view")])
    use_llm(FakeLLM(sql=Q_PAYSLIPS, phrase="ok"))
    assert _ask(client, user)["answered"]
    assert client.delete(f"/api/core/roles/{role_id}/permissions/{perm_ids[('intelligence', 'approve')]}", headers=admin_a).status_code == 204
    r = _ask(client, user)
    assert r["stage"] == "denied" and "approve" in r["answer"]
    assert client.delete(f"/api/core/roles/{role_id}/permissions/{perm_ids[('hr', 'view')]}", headers=admin_a).status_code == 204
    use_llm(FakeLLM(sql=Q_PEOPLE))
    assert _ask(client, user)["stage"] == "denied"


def test_status_and_manifest_describe_exactly_what_this_user_can_do(client, admin_a):
    user, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("inventory", "view")])
    st = client.get("/api/intelligence/status", headers=user).json()["access"]
    assert st == {"is_admin": False, "restricted": False, "modules": ["Inventory"]}
    m = client.get("/api/intelligence/manifest", headers=user).json()
    shown = {v["name"] for v in m["views"]}
    assert shown == EXPECTED["inventory only"][1]
    locked = {v["name"]: v["needs"] for v in m["locked"]}
    assert "payslips" in locked and any("approve" in n for n in locked["payslips"])
    assert "employees" in locked and not any("approve" in n for n in locked["employees"])
    assert m["examples"] == ["Which products are low on stock?"]

    admin_status = client.get("/api/intelligence/status", headers=admin_a).json()["access"]
    assert admin_status["is_admin"] and admin_status["restricted"]
    assert client.get("/api/intelligence/manifest", headers=admin_a).json()["locked"] == []


def test_denied_questions_are_audited_too(client, admin_a, use_llm, db_session):
    user, _, _ = _user_with(client, admin_a, [("intelligence", "view"), ("inventory", "view")])
    marker = f"marker-{uuid.uuid4().hex[:8]}"
    use_llm(FakeLLM(sql=Q_PAYSLIPS))
    _ask(client, user, f"what does everyone earn? {marker}")
    db_session.expire_all()
    actions = [r[0] for r in db_session.execute(text("SELECT action FROM audit_log WHERE action LIKE :m"), {"m": f"%{marker}%"})]
    assert len(actions) == 1 and actions[0].startswith("intelligence_query [denied]")


# ------------------------------- the app -> database hand-off (executor) is the integration point
from app.services.intelligence.executor import run_readonly_query  # noqa: E402


@pytest.mark.parametrize("modules,restricted,expect_rows", [
    ((), False, False),                        # forgot to pass access: FAIL CLOSED, zero rows
    (("inventory",), False, False),
    (("hr",), False, False),
    (("sales", "inventory"), True, False),     # approved but no HR
    (("hr",), True, True),
])
def test_executor_hands_the_users_access_to_the_database_correctly(uil_env, seeded_orgs, db_session, modules, restricted, expect_rows):
    result = run_readonly_query(db_session, seeded_orgs["a"]["org_id"], "SELECT count(*) AS n FROM uil.payslips",
                                max_rows=10, timeout_ms=5000, modules=modules, restricted=restricted)
    assert (result.rows[0][0] > 0) == expect_rows


def test_a_caller_that_forgets_to_pass_access_gets_nothing_not_everything(uil_env, seeded_orgs, db_session):
    """The defaults are 'no modules, not approved'. Forgetting the arguments must fail CLOSED."""
    result = run_readonly_query(db_session, seeded_orgs["a"]["org_id"], "SELECT count(*) AS n FROM uil.invoices",
                                max_rows=10, timeout_ms=5000)
    assert result.rows[0][0] == 0
