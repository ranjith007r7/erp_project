"""
The manifest (what the AI is told exists) must always match the database's
actual views, and must never expose anything sensitive. These tests are what
make the migration's frozen copy of the view list safe to rely on.
"""
import re

import pytest
from sqlalchemy import text

from app.services.intelligence.executor import run_readonly_query
from app.services.intelligence.access import AccessProfile
from app.services.intelligence.manifest import (
    ALL_MODULES, ALLOWED_VIEW_NAMES, EXAMPLES, VIEWS, render_schema_description,
)
from app.services.intelligence.pipeline import _gate_prompt, _sql_prompt

PG_TYPE = {"uuid": "uuid", "character varying": "text", "numeric": "numeric", "integer": "integer",
           "date": "date", "timestamp without time zone": "timestamp", "time without time zone": "time"}


def test_manifest_and_database_views_are_identical(uil_env):
    with uil_env.connect() as c:
        db_views = {r[0] for r in c.execute(text(
            "SELECT table_name FROM information_schema.views WHERE table_schema = 'uil'"))}
    assert db_views == set(ALLOWED_VIEW_NAMES)


@pytest.mark.parametrize("view", VIEWS, ids=lambda v: v.name)
def test_every_column_name_order_and_type_matches_the_database(uil_env, view):
    with uil_env.connect() as c:
        rows = c.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'uil' AND table_name = :t ORDER BY ordinal_position"), {"t": view.name}).fetchall()
    assert [(r[0], PG_TYPE[r[1]]) for r in rows] == [(c.name, c.type) for c in view.columns]


FORBIDDEN_EXACT = {"password_hash", "email", "phone", "org_id", "storage_key", "contact", "branding_storage_key"}
FORBIDDEN_PATTERN = re.compile(r"token|hash|secret|password|credential|api_key", re.I)


def test_no_sensitive_column_is_exposed_anywhere():
    for view in VIEWS:
        for col in view.columns:
            assert col.name not in FORBIDDEN_EXACT, f"{view.name}.{col.name} must not be exposed"
            assert not FORBIDDEN_PATTERN.search(col.name), f"{view.name}.{col.name} looks sensitive"


def test_internal_tables_are_not_in_the_manifest():
    for name in ("audit_log", "roles", "permissions", "notifications", "organizations", "documents",
                 "approval_workflows", "approval_requests", "saved_reports", "report_subscriptions",
                 "custom_fields", "custom_field_values", "session_context"):
        assert name not in ALLOWED_VIEW_NAMES


def test_the_prompt_the_model_sees_contains_no_secrets_vocabulary():
    prompt = _sql_prompt("what is our revenue?", AccessProfile.full()).lower()
    for word in ("password", "token", "hash", "secret", "storage_key", "org_id'"):
        assert word not in prompt.replace("never mention org_id", "")
    assert not FORBIDDEN_PATTERN.search(render_schema_description())


def test_the_model_is_told_never_to_filter_by_organization():
    assert "NEVER filter by organization" in _sql_prompt("q", AccessProfile.full())


def test_gate_prompt_lists_what_exists_but_never_column_definitions():
    prompt = _gate_prompt("q")
    assert "invoices: " in prompt            # it knows which areas exist...
    assert "    id uuid" not in prompt      # ...but is never shown the column listing
    assert "unit_price numeric" not in prompt


@pytest.mark.parametrize("question,sql,views", EXAMPLES, ids=[e[0][:40] for e in EXAMPLES])
def test_every_example_query_really_runs_against_realistic_data(uil_env, seeded_orgs, db_session, question, sql, views):
    """The few-shot examples are shown to the model as truth, so they must actually execute."""
    from app.services.intelligence.safety import validate_sql
    validated = validate_sql(sql, max_rows=200)
    result = run_readonly_query(db_session, seeded_orgs["a"]["org_id"], validated.sql, max_rows=200, timeout_ms=5000,
                                modules=ALL_MODULES, restricted=True)
    assert result.columns
    assert validated.tables == views, "the example's declared views must match what its SQL really reads"


def test_the_headline_revenue_example_agrees_with_the_erps_own_finance_report(uil_env, seeded_orgs, db_session):
    """The AI's definition of revenue must equal what the Finance screen computes."""
    from app.services.reports import finance_summary
    from app.services.intelligence.safety import validate_sql
    org_id = seeded_orgs["a"]["org_id"]
    sql = validate_sql(EXAMPLES[0][1], max_rows=200).sql
    ai_revenue = run_readonly_query(db_session, org_id, sql, max_rows=200, timeout_ms=5000,
                                    modules=ALL_MODULES, restricted=True).rows[0][0]
    assert ai_revenue == pytest.approx(finance_summary(db_session, org_id, months=24)["total_revenue"])
