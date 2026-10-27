"""
Parser-based guard for model-generated SQL (SQLGlot, Postgres dialect).

The query is parsed into a syntax tree and checked node by node — never by
keyword search — so a word like 'delete' inside a string literal, a comment or
a column name is not mistaken for a statement, and a write hidden inside a CTE
(`WITH x AS (DELETE ... RETURNING *) SELECT ...`) or a `SELECT ... INTO` is
still caught. The megh_readonly role stays the real security boundary; this is
the check in front of it.

The text sent to Postgres is the model's own text (cut at its last token), not
SQLGlot's regenerated SQL, so a dialect detail SQLGlot round-trips differently
can never change what runs.
"""
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError
from sqlglot.tokens import TokenType

DIALECT = "postgres"

# The only schemas generated SQL may read — the same two the megh_readonly role
# is granted (deploy/sql/03_readonly_role.sql) and the read-only pool's search_path.
READONLY_SCHEMAS: tuple[str, ...] = ("curated", "semantic")

# Tables generated SQL must never read, though megh_readonly can: unmasked bank
# account numbers and holder names (Focus Legacy fact, its bank bridge) and
# applicant names (CM Elevate Legacy fact). Their curated.v_* views mask or drop
# those fields. Until 2026-10-16 only the prompt kept them out (KI-004).
PRIVATE_TABLES: frozenset[str] = frozenset({
    "curated.fact_focus_legacy_disbursement", "curated.bridge_pg_bank_history",
    "curated.fact_cm_elevate_disbursement"})


class UnsafeSQLError(ValueError):
    """Raised when generated SQL fails the read-only / single-statement check.
    `rule` names which check: parse_error, empty, multiple_statements,
    not_a_select, write_operation, forbidden_function, schema_not_allowed,
    private_table."""

    def __init__(self, message: str, rule: str = "unsafe"):
        super().__init__(message)
        self.rule = rule


# The statement itself must be a query: SELECT (with or without a WITH),
# UNION / INTERSECT / EXCEPT, or a parenthesised one of those.
_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.SetOperation, exp.Subquery)

# Anywhere in the tree. Looked up by name so a SQLGlot release that renames or
# drops one of these doesn't break the import. exp.Command is what SQLGlot
# falls back to for statements it doesn't model (VACUUM, CALL, EXPLAIN,
# REFRESH ..., SET ROLE); exp.Into is SELECT ... INTO (creates a table);
# exp.Lock is FOR UPDATE / FOR SHARE.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    cls for cls in (getattr(exp, name, None) for name in (
        "DML", "DDL", "Insert", "Update", "Delete", "Merge", "Create", "Drop",
        "Alter", "TruncateTable", "Copy", "Grant", "Revoke", "Command",
        "Transaction", "Commit", "Rollback", "Set", "Lock", "Into", "Analyze",
        "Use", "Pragma", "Refresh", "LoadData", "Cache", "Uncache", "Kill",
        "Execute", "Comment", "Attach", "Detach", "Install",
    )) if isinstance(cls, type)
)

# Functions with side effects, file/network access, or that run SQL passed in
# as a string — none has a place in an answer to a question.
_FORBIDDEN_FUNCTIONS = frozenset({
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile",
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "lo_unlink",
    "dblink", "dblink_exec", "dblink_connect", "dblink_send_query",
    "set_config", "nextval", "setval",
    "pg_advisory_lock", "pg_advisory_xact_lock", "pg_try_advisory_lock",
    "pg_notify", "query_to_xml", "query_to_xml_and_xmlschema", "table_to_xml",
    "cursor_to_xml",
    # Server / session information (DB team review 2026-10-27, "reject
    # system-catalog functions"): read-only, but nothing a scheme question needs.
    # SQLGlot parses version() as CurrentVersion.
    "current_setting", "version", "current_version", "current_database",
})

# Whole families refused by prefix (2026-10-27): every pg_* function (backend
# pids, stats, file access, catalog lookups like pg_get_viewdef), large objects,
# dblink, transaction ids and server / client addresses. Not one of the 657
# distinct generated statements in app.query_audit calls any of them. A full
# allow-list would also refuse ordinary functions the model has not used yet
# (AVG, TO_CHAR, RANK ...), so the list of what IS allowed stays open.
_FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "txid_", "inet_")


def _is_forbidden_function(name: str) -> bool:
    return name in _FORBIDDEN_FUNCTIONS or name.startswith(_FORBIDDEN_FUNCTION_PREFIXES)


def _parse_single(sql: str) -> exp.Expression:
    try:
        # A comment after the final ';' comes back as a bare Semicolon node.
        statements = [s for s in sqlglot.parse(sql, read=DIALECT)
                      if s is not None and not isinstance(s, exp.Semicolon)]
    except ParseError as e:
        first = e.errors[0] if e.errors else {}
        where = f" (line {first['line']}, col {first['col']})" if "line" in first else ""
        raise UnsafeSQLError(f"could not parse the query{where}: {first.get('description', e)}",
                             "parse_error") from e
    except SqlglotError as e:
        raise UnsafeSQLError(f"could not parse the query: {e}", "parse_error") from e
    if not statements:
        raise UnsafeSQLError("empty query", "empty")
    if len(statements) > 1:
        raise UnsafeSQLError("multiple statements are not allowed", "multiple_statements")
    return statements[0]


def _function_name(fn: exp.Func) -> str:
    return (fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()).lower()


def _assert_schemas(tree: exp.Expression, schemas: tuple[str, ...]) -> None:
    """Every table the query reads must be in `schemas`. A schema-qualified name
    is checked as written; an unqualified one resolves through the read-only
    pool's search_path (curated, semantic) — except pg_catalog, which Postgres
    always searches first, so an unqualified pg_* name is refused. A CTE name is
    not a table; a set-returning function (generate_series, unnest) has no schema."""
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if table.catalog:
            raise UnsafeSQLError(f"query names another database ({table.catalog}.{table.db}.{name})",
                                 "schema_not_allowed")
        if table.db:
            if table.db.lower() not in schemas:
                raise UnsafeSQLError(f"query reads {table.db}.{name} — only the {' / '.join(schemas)} "
                                     "schemas are allowed", "schema_not_allowed")
        elif isinstance(table.this, exp.Identifier) and name not in cte_names and name.startswith("pg_"):
            raise UnsafeSQLError(f"query reads the system catalog ({name}) — only the "
                                 f"{' / '.join(schemas)} schemas are allowed", "schema_not_allowed")
        # An unqualified name resolves through search_path curated, semantic.
        qualified = f"{(table.db or 'curated').lower()}.{name}"
        if qualified in PRIVATE_TABLES and (table.db or name not in cte_names):
            view = {"curated.fact_cm_elevate_disbursement": "curated.v_cm_elevate_disbursement"}.get(
                qualified, "curated.v_focus_legacy")
            raise UnsafeSQLError(f"query reads {qualified}, which holds unmasked personal data and is "
                                 f"never queried — read {view} instead", "private_table")


def assert_readonly(sql: str, schemas: tuple[str, ...] | None = READONLY_SCHEMAS) -> exp.Expression:
    """Parse `sql` and return its tree if it is one read-only query reading only
    `schemas` (None skips the schema check); raise UnsafeSQLError (with a reason
    the repair prompt can act on) otherwise."""
    tree = _parse_single(sql)
    if not isinstance(tree, _ALLOWED_ROOTS):
        raise UnsafeSQLError(f"query must be a SELECT (optionally with WITH), got {tree.key.upper()}",
                             "not_a_select")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeSQLError(f"query contains a write/DDL operation ({node.key.upper()})",
                                 "write_operation")
        if isinstance(node, exp.Func) and _is_forbidden_function(_function_name(node)):
            raise UnsafeSQLError(f"query calls a forbidden function ({_function_name(node)})",
                                 "forbidden_function")
    if schemas is not None:
        _assert_schemas(tree, schemas)
    return tree


def _statement_text(sql: str) -> str:
    """The query text up to its last real token — drops trailing semicolons and
    trailing comments, so a LIMIT can be appended safely."""
    tokens = sqlglot.tokenize(sql, read=DIALECT)
    last = next((t for t in reversed(tokens) if t.token_type != TokenType.SEMICOLON), None)
    return sql[: last.end + 1] if last is not None else ""


def _outer_row_cap(tree: exp.Expression) -> int | None:
    """The outermost LIMIT / FETCH FIRST as an int; None when there is none;
    -1 when there is one that isn't a plain number (LIMIT ALL, $1, an expression)."""
    node = tree
    while node is not None:
        clause = node.args.get("limit")
        if clause is not None:
            value = clause.args.get("count") if isinstance(clause, exp.Fetch) else clause.expression
            if isinstance(value, exp.Literal) and not value.is_string:
                try:
                    return int(value.this)
                except ValueError:
                    return -1
            return -1
        node = node.this if isinstance(node, exp.Subquery) else None
    return None


def prepare_readonly(sql: str, max_rows: int) -> str:
    """Validate `sql` and return the text to execute, bounded at `max_rows`:
    no outer LIMIT → one is appended; an outer LIMIT above the cap (or not a
    plain number) → the query is wrapped and capped; otherwise unchanged. A
    LIMIT inside a subquery or CTE doesn't bound the result, so it doesn't count."""
    tree = assert_readonly(sql)
    body = _statement_text(sql)
    cap = _outer_row_cap(tree)
    if cap is None:
        return f"{body}\nLIMIT {max_rows}"
    if 0 <= cap <= max_rows:
        return body
    return f"SELECT * FROM (\n{body}\n) AS _capped LIMIT {max_rows}"
