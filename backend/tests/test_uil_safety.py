"""
Layer-one tests: the SQL validator, the number-grounding check, and the LLM
client's retry/error handling. No database needed for most of these.

The rejection list below is the same set of attacks probed by hand during
development, kept so none of them can ever silently start passing.
"""
import pytest
from google.genai import errors as genai_errors

from app.services.intelligence.llm import GeminiClient, LLMError, call_with_retry
from app.services.intelligence.manifest import EXAMPLES
from app.services.intelligence.pipeline import ungrounded_numbers
from app.services.intelligence.safety import (
    ALLOWED_ANONYMOUS_FUNCS,
    ALLOWED_FUNC_CLASSES,
    UnsafeQueryError,
    validate_sql,
)

REJECTED = [
    # multiple statements / non-SELECT
    ("SELECT 1; DROP TABLE users", "Exactly one"),
    ("DROP TABLE users", "Only SELECT"),
    ("DELETE FROM invoices", "Only SELECT"),
    ("UPDATE invoices SET amount = 0", "Only SELECT"),
    ("INSERT INTO invoices VALUES (1)", "Only SELECT"),
    ("COPY (SELECT 1) TO '/tmp/x'", "Only SELECT"),
    ("SET ROLE postgres", "Only SELECT"),
    ("TRUNCATE invoices", "Only SELECT"),
    # SELECT-shaped but still writing/locking
    ("SELECT * INTO newtable FROM uil.invoices", "not allowed"),
    ("SELECT * FROM uil.invoices FOR UPDATE", "not allowed"),
    # tables that are not in the manifest
    ("SELECT * FROM public.users", "not available"),
    ("SELECT * FROM public.invoices", "not available"),
    ("SELECT * FROM pg_catalog.pg_user", "not available"),
    ("SELECT * FROM information_schema.tables", "not available"),
    ("SELECT * FROM uil.audit_log", "not available"),
    ("SELECT * FROM uil.session_context", "not available"),
    ("SELECT * FROM audit_log", "not an available view"),
    ("SELECT * FROM roles", "not an available view"),
    ("SELECT * FROM notifications", "not an available view"),
    ("WITH audit_log AS (SELECT * FROM audit_log) SELECT * FROM audit_log", "not an available view"),
    ("SELECT * FROM generate_series(1, 100000000)", "Table-valued"),
    # dangerous functions
    ("SELECT set_config('role', 'postgres', true)", "not allowed"),
    ("SELECT pg_sleep(30)", "not allowed"),
    ("SELECT lo_import('/etc/passwd')", "not allowed"),
    ("SELECT pg_read_file('/etc/passwd')", "not allowed"),
    ("SELECT pg_terminate_backend(1)", "not allowed"),
    ("SELECT uil.current_org()", "not allowed"),
    ("SELECT current_setting('uil.org_id')", "not allowed"),
    ("SELECT version()", "not allowed"),
    # no data source at all / empty / parameters
    ("SELECT now()", "must read from"),
    ("", "empty"),
    ("   \n  ", "empty"),
    ("SELECT * FROM uil.invoices WHERE amount > $1", "not allowed"),
]


@pytest.mark.parametrize("query,reason_fragment", REJECTED)
def test_attack_is_rejected(query, reason_fragment):
    with pytest.raises(UnsafeQueryError) as exc:
        validate_sql(query, max_rows=200)
    assert reason_fragment.lower() in exc.value.reason.lower()


ACCEPTED = [
    "SELECT name FROM crm_leads;",
    "```sql\nSELECT name FROM crm_leads;\n```",
    "SELECT name FROM crm_leads -- every lead",
    "SELECT name FROM customers WHERE name ILIKE '%acme%'",
    "SELECT to_char(created_at, 'HH24:MI') FROM invoices",
    "SELECT ROUND(AVG(amount)::numeric, 2) FROM invoices",
    "SELECT name FROM customers UNION SELECT name FROM vendors",
    "SELECT x.s FROM (SELECT SUM(amount) AS s FROM invoices) x",
    "SELECT amount, SUM(amount) OVER (ORDER BY created_at) FROM invoices",
    "WITH t AS (SELECT customer_id, SUM(amount) a FROM invoices GROUP BY 1) SELECT * FROM t ORDER BY a DESC",
    "SELECT COUNT(*) FILTER (WHERE status = 'paid') FROM invoices",
    "SELECT name FROM customers WHERE name = 'a;b'",
    "SELECT EXTRACT(YEAR FROM created_at) FROM invoices",
    "SELECT AGE(CURRENT_DATE, joining_date) FROM employees",
    "SELECT * FROM invoices WHERE created_at > NOW() - INTERVAL '30 days'",
    'SELECT * FROM "invoices"',
    "SELECT * FROM uil.invoices",
]


@pytest.mark.parametrize("query", ACCEPTED)
def test_ordinary_queries_are_not_falsely_rejected(query):
    validated = validate_sql(query, max_rows=200)
    assert "uil." in validated.sql


def test_every_manifest_example_passes_the_validator():
    for question, sql, _views in EXAMPLES:
        validate_sql(sql, max_rows=200)


def test_unqualified_users_resolves_to_the_safe_view_never_the_real_table():
    """The model asking for 'users' must get uil.users (names/roles only), not public.users (password hashes)."""
    sql = validate_sql("SELECT * FROM users", max_rows=200).sql
    assert "uil.users" in sql
    assert "public" not in sql.lower()


def test_unqualified_names_are_always_schema_qualified():
    sql = validate_sql("SELECT i.id FROM invoices i JOIN customers c ON c.id = i.customer_id", max_rows=200).sql
    assert "uil.invoices" in sql and "uil.customers" in sql


def test_row_cap_is_always_applied():
    assert validate_sql("SELECT name FROM customers", max_rows=200).sql.endswith("LIMIT 201")


def test_oversized_limit_is_clamped_and_small_limit_is_kept():
    assert validate_sql("SELECT name FROM customers LIMIT 99999", max_rows=200).sql.endswith("LIMIT 201")
    assert validate_sql("SELECT name FROM customers LIMIT 5", max_rows=200).sql.endswith("LIMIT 5")


def test_set_operations_are_wrapped_so_the_cap_covers_the_whole_result():
    sql = validate_sql("SELECT name FROM customers UNION SELECT name FROM vendors", max_rows=200).sql
    assert sql.startswith("SELECT * FROM (") and sql.endswith("LIMIT 201")


def test_allowlist_contains_nothing_dangerous():
    dangerous = {"set_config", "pg_sleep", "lo_import", "pg_read_file", "current_setting", "pg_terminate_backend",
                 "dblink", "version", "current_org", "pg_ls_dir", "generate_series"}
    assert not (dangerous & set(ALLOWED_ANONYMOUS_FUNCS))
    assert not ({c.lower() for c in ALLOWED_FUNC_CLASSES} & {d.replace("_", "") for d in dangerous})


# ------------------------------------------------------------ number grounding
ROWS = [["Acme Traders", 125000.5, "2026-03-15"], ["Zenith Auto", 98000.0, "2026-04-02"]]


def test_numbers_present_in_the_data_are_grounded():
    assert ungrounded_numbers("Acme Traders billed 125,000.50 on 2026-03-15.", "top customers", ROWS) == []


def test_a_fabricated_figure_is_caught():
    assert 130000.0 in ungrounded_numbers("Acme Traders billed 130,000.", "top customers", ROWS)


def test_rounding_to_a_whole_number_is_allowed_but_not_further_drift():
    assert ungrounded_numbers("Acme billed about 125,001.", "q", ROWS) == []
    assert ungrounded_numbers("Acme billed about 125,200.", "q", ROWS) == [125200.0]


def test_counts_and_ranks_up_to_the_row_count_are_allowed():
    assert ungrounded_numbers("There are 2 customers; the top 1 is Acme.", "q", ROWS) == []


def test_numbers_from_the_question_itself_are_allowed():
    assert ungrounded_numbers("In 2026 revenue was 125,000.50.", "revenue in 2026?", ROWS) == []


def test_an_invented_percentage_is_caught():
    assert 56.0 in ungrounded_numbers("Acme is 56% of revenue.", "q", ROWS)


# ------------------------------------------------------------ retry behaviour
class _Err(Exception):
    def __init__(self, code):
        super().__init__(f"http {code}")
        self.code = code


def test_retry_succeeds_after_transient_errors_with_exponential_backoff():
    attempts, sleeps = [], []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise _Err(429)
        return "ok"

    assert call_with_retry(flaky, sleep=sleeps.append) == "ok"
    assert len(attempts) == 3
    assert sleeps == [1.5, 3.0]


def test_non_retryable_errors_fail_immediately_without_burning_quota():
    attempts = []

    def bad_key():
        attempts.append(1)
        raise _Err(403)

    with pytest.raises(_Err):
        call_with_retry(bad_key, sleep=lambda s: None)
    assert len(attempts) == 1


def test_retry_gives_up_after_max_attempts():
    attempts = []

    def always_busy():
        attempts.append(1)
        raise _Err(503)

    with pytest.raises(_Err):
        call_with_retry(always_busy, attempts=4, sleep=lambda s: None)
    assert len(attempts) == 4


# ------------------------------------------------- Gemini client (fake SDK)
class _FakeModels:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    def generate_content(self, *, model, contents, config):
        self.calls += 1
        return self.behaviour(self.calls)


class _FakeSDK:
    def __init__(self, behaviour):
        self.models = _FakeModels(behaviour)


class _Resp:
    def __init__(self, text):
        self.text = text


def _api_error(code):
    return genai_errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


def test_gemini_client_returns_text_and_counts_calls():
    sdk = _FakeSDK(lambda n: _Resp("  SELECT 1  "))
    client = GeminiClient("k", "m", client=sdk, sleep=lambda s: None)
    assert client.generate("hi") == "SELECT 1"
    assert client.calls_used == 1


def test_gemini_client_retries_a_rate_limit_then_succeeds():
    def behaviour(n):
        if n < 3:
            raise _api_error(429)
        return _Resp("done")

    client = GeminiClient("k", "m", client=_FakeSDK(behaviour), sleep=lambda s: None)
    assert client.generate("hi") == "done"
    assert client.calls_used == 3  # every real attempt counts against the free quota


def test_gemini_client_explains_an_exhausted_quota_plainly():
    client = GeminiClient("k", "m", client=_FakeSDK(lambda n: (_ for _ in ()).throw(_api_error(429))), sleep=lambda s: None)
    with pytest.raises(LLMError) as exc:
        client.generate("hi")
    assert "quota" in exc.value.reason.lower()


def test_gemini_client_reports_a_rejected_key_without_retrying():
    sdk = _FakeSDK(lambda n: (_ for _ in ()).throw(_api_error(403)))
    client = GeminiClient("k", "m", client=sdk, sleep=lambda s: None)
    with pytest.raises(LLMError) as exc:
        client.generate("hi")
    assert "GEMINI_API_KEY" in exc.value.reason
    assert sdk.models.calls == 1


def test_gemini_client_handles_an_empty_or_blocked_response():
    client = GeminiClient("k", "m", client=_FakeSDK(lambda n: _Resp(None)), sleep=lambda s: None)
    with pytest.raises(LLMError) as exc:
        client.generate("hi")
    assert "no answer" in exc.value.reason.lower()
