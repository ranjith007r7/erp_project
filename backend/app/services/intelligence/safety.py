"""
LAYER ONE of the safety design: validate AI-written SQL before it runs.

Unlike a keyword blocklist ("reject anything containing DROP"), this PARSES
the query into a syntax tree and applies deny-by-default rules, so there is
no list of "bad words" to forget an entry from:

  - exactly ONE statement, and it must be a SELECT (a WITH ... SELECT or a
    UNION of SELECTs is fine). INSERT/UPDATE/DELETE/DDL/COPY/SET and
    "SELECT ... INTO" / "FOR UPDATE" are structurally impossible, not
    merely filtered.
  - every table must be one of the manifest's views. Anything else (base
    tables, pg_catalog, information_schema, table-valued functions like
    generate_series) is rejected.
  - every function must be on an explicit allow-list. So set_config,
    pg_sleep, lo_import, pg_read_file and anything we have not thought of
    are rejected by default.
  - the SQL that actually RUNS is regenerated from the validated tree (not
    the original text), with every table schema-qualified and a hard row
    cap applied. This removes the classic gap where a validator and the
    database parse the same string differently.

This layer is a seatbelt, not the wall. The wall is the database role
(role_setup.py) and the tenant-scoped views, which hold even if this file
had a bug. Both layers are tested independently.
"""
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.services.intelligence.manifest import ALLOWED_VIEW_NAMES

SCHEMA = "uil"

# Evidence-based: derived by parsing realistic analytics queries and listing
# which function classes they produce (see MANUAL.md Part 56). sqlglot names
# functions by its own class, not the Postgres spelling (date_trunc becomes
# TimestampTrunc), so this is keyed on class name.
ALLOWED_FUNC_CLASSES = frozenset({
    # aggregates
    "Sum", "Count", "Avg", "Min", "Max", "Stddev", "Variance", "GroupConcat", "PercentileCont",
    # conditionals / null handling
    "Case", "If", "Coalesce", "Nullif", "Greatest", "Least", "Exists",
    # boolean connectives (sqlglot models AND/OR as functions)
    "And", "Or", "Not",
    # math
    "Abs", "Ceil", "Floor", "Round", "Sqrt", "Ln", "Pow",
    # text
    "Upper", "Lower", "Length", "Substring", "Trim", "Concat", "ConcatWs",
    # dates and casting
    "Cast", "Extract", "TimestampTrunc", "DateTrunc", "StrToDate", "TimeToStr", "TsOrDsToDate",
    "CurrentDate", "CurrentTimestamp", "DateDiff", "DateAdd", "DateSub", "Year", "Month", "Day",
    # window functions
    "RowNumber", "Rank", "DenseRank", "Lag", "Lead", "NTile", "FirstValue", "LastValue",
})
# Functions sqlglot does not model and therefore parses as "Anonymous".
ALLOWED_ANONYMOUS_FUNCS = frozenset({"age", "make_date", "date_part"})

# Statement-level constructs that must never appear anywhere in the tree.
FORBIDDEN_NODES = frozenset({
    "Into", "Lock", "Command", "Set", "SetItem", "Copy", "Insert", "Update", "Delete", "Drop", "Create",
    "Alter", "AlterTable", "Merge", "TruncateTable", "Transaction", "Commit", "Rollback", "Use",
    "Grant", "Revoke", "Pragma", "Placeholder", "Parameter", "Kill", "Analyze", "Describe", "Show",
})

_SET_OPERATION = getattr(exp, "SetOperation", exp.Union)


class UnsafeQueryError(Exception):
    """Raised with a reason safe to show to the user (and to feed back to the LLM)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AccessDeniedError(Exception):
    """
    The query is well-formed and names real views, but at least one of them is a
    view this particular user may not read. Deliberately NOT a subclass of
    UnsafeQueryError: a permission problem is not a query-writing mistake, so it
    must never be "corrected" by retrying, and it needs its own plain message.
    """

    def __init__(self, views):
        super().__init__("access denied: " + ", ".join(views))
        self.views = list(views)


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str            # what to execute: regenerated, schema-qualified, row-capped
    tables: frozenset   # which manifest views it reads


def _enclosing_cte_aliases(node: exp.Expression) -> set:
    names = set()
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.CTE) and parent.alias:
            names.add(parent.alias.lower())
        parent = parent.parent
    return names


def _function_name(node: exp.Func) -> str:
    return node.name.lower() if isinstance(node, exp.Anonymous) else type(node).__name__


def validate_sql(raw_sql: str, *, max_rows: int, allowed_views=None) -> ValidatedQuery:
    """
    allowed_views: the views THIS USER may read (None = no per-user restriction, used by
    tooling and tests). A query naming any other manifest view raises AccessDeniedError,
    after all the structural safety checks, so a malicious query is still reported as
    malicious rather than as a permissions problem.
    """
    if not raw_sql or not raw_sql.strip():
        raise UnsafeQueryError("The query was empty.")

    cleaned = raw_sql.strip()
    # Models often wrap SQL in markdown fences; tolerate that, nothing else.
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("sql"):
            cleaned = cleaned[3:]
        cleaned = cleaned.strip()

    try:
        statements = sqlglot.parse(cleaned, read="postgres")
    except SqlglotError as exc:
        raise UnsafeQueryError(f"The query could not be parsed as PostgreSQL: {str(exc).splitlines()[0][:160]}")

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise UnsafeQueryError("Exactly one SQL statement is allowed.")
    root = statements[0]

    if not isinstance(root, (exp.Select, _SET_OPERATION)):
        raise UnsafeQueryError("Only SELECT queries are allowed.")

    cte_names = {c.alias.lower() for c in root.find_all(exp.CTE) if c.alias}
    tables_used = set()
    denied = set()

    for node in root.walk():
        node_type = type(node).__name__
        if node_type in FORBIDDEN_NODES:
            raise UnsafeQueryError(f"'{node_type}' is not allowed; only plain read-only SELECT queries are permitted.")

        if isinstance(node, exp.Func):
            name = _function_name(node)
            allowed = ALLOWED_ANONYMOUS_FUNCS if isinstance(node, exp.Anonymous) else ALLOWED_FUNC_CLASSES
            if name not in allowed:
                shown = name if isinstance(node, exp.Anonymous) else node.sql_name().lower()
                raise UnsafeQueryError(f"The function '{shown}' is not allowed.")

        if isinstance(node, exp.Table):
            if not isinstance(node.this, exp.Identifier):
                raise UnsafeQueryError("Table-valued functions are not allowed.")
            if node.catalog:
                raise UnsafeQueryError("Cross-database references are not allowed.")
            name = node.name.lower()
            schema = node.db.lower() if node.db else ""

            if schema:
                if schema != SCHEMA or name not in ALLOWED_VIEW_NAMES:
                    raise UnsafeQueryError(f"'{node.db}.{node.name}' is not available. Use only the listed views.")
                tables_used.add(name)
                if allowed_views is not None and name not in allowed_views:
                    denied.add(name)
                continue

            # Unqualified: either a CTE defined in this query, or one of our views.
            visible_ctes = cte_names - _enclosing_cte_aliases(node)
            if name in visible_ctes:
                continue
            if name in ALLOWED_VIEW_NAMES:
                node.set("db", exp.to_identifier(SCHEMA))  # qualify, so search_path never matters
                tables_used.add(name)
                if allowed_views is not None and name not in allowed_views:
                    denied.add(name)
                continue
            raise UnsafeQueryError(f"'{node.name}' is not an available view.")

    if denied:
        raise AccessDeniedError(sorted(denied))

    if not tables_used and not cte_names:
        # e.g. "SELECT 1" or "SELECT now()": harmless, but never an answer from data.
        raise UnsafeQueryError("The query must read from one of the listed views.")

    capped = _apply_row_cap(root, max_rows)
    return ValidatedQuery(sql=capped.sql(dialect="postgres"), tables=frozenset(tables_used))


def _apply_row_cap(root: exp.Expression, max_rows: int) -> exp.Expression:
    """
    Always fetch at most max_rows + 1 rows (the extra row lets the caller tell
    the user "showing the first N"). Wrapping/overwriting unconditionally is
    simpler and safer than reasoning about every spelling of LIMIT/FETCH.
    """
    cap = max_rows + 1
    if isinstance(root, exp.Select):
        existing = root.args.get("limit")
        if existing is not None:
            try:
                if int(existing.expression.this) <= cap:
                    return root
            except (AttributeError, ValueError, TypeError):
                pass
        return root.limit(cap)
    return sqlglot.select("*").from_(root.subquery("q")).limit(cap)
