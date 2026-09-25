"""
app/core/pii_guard.py — two-layer, code-enforced §11.4 PII protection.

Before this module, PII protection was prompt-text only: app/sql/schema_context.py
tells the SQL-generating LLM which columns are sensitive, but nothing in the
code path enforced it — see openspec/changes/urgent-pii-redaction/proposal.md
for the fact-finding this is built from.

Layer 1 (`find_blocked_columns`) — pre-execution: scan generated SQL text for
a blocklisted column identifier before it runs. A full-text, word-boundary
scan (not a parsed SELECT-list) so it can't be dodged by aliasing
(`SELECT member_id AS mid` still contains the literal identifier) and also
catches a JSONB key reference like `scheme_specific ->> 'member_id'`
(CM Elevate's blocklisted fields live inside `scheme_specific`, not as
top-level columns — apostrophes are non-word characters, so the word-boundary
match still fires inside the quotes).

Layer 2 (`redact_rows`) — post-execution: strip any blocklisted key from
every result row, unconditionally. This is the actual guarantee — it doesn't
depend on parsing SQL at all, so it also covers a column Layer 1's text scan
somehow missed.

The blocklist below is a hardcoded per-scheme dict, not parsed from the
`data/*/​*_schema_partitions.yaml` docs — those are prose-first SME references
with inconsistent per-file structure (CM Elevate has a `pii_rule.
retained_in_scheme_specific` list; Focus Plus has per-column `pii: true`
flags scattered through a `columns:` list), not a stable machine contract.
A live `semantic.column_catalog`-driven blocklist is a flagged fast-follow
(proposal.md's Explicitly Out of Scope) once that table's existence/shape is
confirmed against a reachable database.
"""
import json
import re

# scheme -> a JSONB container column that is NOT PII-only (holds legitimate,
# actively-queried non-PII data alongside PII keys), so it can't be
# blocklisted outright like a column in PII_BLOCKLIST — only *whole-column*
# exposure is unsafe. CM Elevate's scheme_specific holds ~125 fields, of
# which only the 8 PII_BLOCKLIST["CM Elevate"] keys are sensitive; the rest
# includes gender_id, called out in cmelevate_schema_partitions.yaml as "the
# one genuinely useful demographic on this partition and reachable only
# through JSONB" — re-confirmed before this check was added (see
# openspec/changes/urgent-pii-redaction-followup/proposal.md).
_CONTAINER_COLUMNS: dict[str, str] = {
    "CM Elevate": "scheme_specific",
}

_JSON_EXTRACT_OP = re.compile(r"\s*(->>|->|#>>|#>)")
_SELECT_LIST = re.compile(r"\bselect\b(.*?)\bfrom\b", re.IGNORECASE | re.DOTALL)
_LEADING_DISTINCT = re.compile(r"(?i)^\s*distinct\s+")
_BARE_STAR_TOKEN = re.compile(r"^\s*(?:\w+\.)?\*\s*$")

# scheme -> blocklisted column / scheme_specific JSONB key identifiers.
# Source citations (re-confirm here before editing, per proposal.md's
# "Per-scheme blocklist" section):
#   MGNREGA   - no person-level column exists on any fact (mgnrega_schema_partitions.yaml).
#   PMAY-G    - beneficiary_name / father_mother_name dropped at ingest, never
#               reach curated (pmay_schema_partitions.yaml:539-545).
#   Focus Plus - member_id, pincode: both `pii: true`
#               (focusplus_schema_partitions.yaml:472-505).
#   CM Elevate - pii_rule.retained_in_scheme_specific
#               (cmelevate_schema_partitions.yaml:795-798) — the separately
#               listed stripped_at_ingest set never reaches the DB at all,
#               so blocklisting it would be moot.
PII_BLOCKLIST: dict[str, tuple[str, ...]] = {
    "MGNREGA": (),
    "PMAY-G": (),
    # account_no_masked / ifsc_code / bank_details_current come with
    # curated.v_focus_legacy (producer-group payments, added to Focus Plus
    # 2026-09-23) — bank account details are never answerable, masked or not.
    "Focus Plus": ("member_id", "pincode", "account_no_masked", "account_no",
                   "ifsc_code", "bank_details_current"),
    "CM Elevate": (
        "dob", "email_id", "address", "member_id", "family_id",
        "pds_id", "account_holder_name", "ifsc_code",
    ),
}

_pattern_cache: dict[str, re.Pattern] = {}


def _pattern_for(column: str) -> re.Pattern:
    pat = _pattern_cache.get(column)
    if pat is None:
        pat = re.compile(r"\b" + re.escape(column) + r"\b", re.IGNORECASE)
        _pattern_cache[column] = pat
    return pat


def blocklisted_columns(schemes: list[str]) -> tuple[str, ...]:
    """Union of blocklisted columns across every active scheme, de-duplicated,
    order-preserving."""
    seen: dict[str, None] = {}
    for scheme in schemes or ():
        for col in PII_BLOCKLIST.get(scheme, ()):
            seen.setdefault(col, None)
    return tuple(seen)


def _without_count_only_uses(sql: str, column: str) -> str:
    """`sql` with the uses of `column` that can only ever produce a NUMBER
    removed: `COUNT(col)`, `COUNT(DISTINCT col)` and a `col IS [NOT] NULL`
    test. None of these can put an identifier in the result, and
    COUNT(DISTINCT member_id) is the one use of member_id the Focus Plus rules
    explicitly permit (schema_context FOCUS PLUS RULES rule 5) — scanning the
    bare word blocked it too, so "members with an id" could never be answered
    (2026-09-23). Selecting, grouping, ordering or comparing the value is
    untouched and still caught by the scan."""
    col = r"(?:\w+\.)?" + re.escape(column)
    sql = re.sub(rf"\bcount\s*\(\s*(?:distinct\s+)?{col}\s*\)", " ", sql, flags=re.IGNORECASE)
    return re.sub(rf"{col}\s+is\s+(?:not\s+)?null\b", " ", sql, flags=re.IGNORECASE)


def find_blocked_columns(sql: str, schemes: list[str]) -> tuple[str, ...]:
    """Layer 1. Returns the blocklisted column name(s) found anywhere in
    `sql` for the active scheme(s) — empty tuple if none. Case-insensitive,
    word-boundary matched over the full SQL text, ignoring count-only uses
    (see _without_count_only_uses)."""
    return tuple(col for col in blocklisted_columns(schemes)
                 if _pattern_for(col).search(_without_count_only_uses(sql, col)))


def _has_star_select(sql: str) -> bool:
    """True if any SELECT list in `sql` (there may be more than one, e.g.
    inside a CTE) selects a bare or qualified wildcard (`*` / `alias.*`) as
    its own list item — not `a * b` (multiplication), which never appears as
    a standalone comma-separated token."""
    for select_list in _SELECT_LIST.findall(sql):
        for token in select_list.split(","):
            if _BARE_STAR_TOKEN.match(_LEADING_DISTINCT.sub("", token)):
                return True
    return False


def find_container_exposure(sql: str, schemes: list[str]) -> str | None:
    """Layer 1b. `scheme_specific` (CM Elevate) and any future entry in
    _CONTAINER_COLUMNS is NOT PII-only — see module docstring / proposal.md —
    so it can't be blocklisted outright the way a PII_BLOCKLIST column is.
    Only *whole-column* exposure is unsafe: a bare/aliased select of the
    column, or a `SELECT *` that would include it. A scoped `scheme_specific
    ->> 'key'` extraction is left alone here; if `key` is itself one of the
    8 blocklisted names, find_blocked_columns already catches it via the
    literal-name scan. Returns the exposed container column name, or None."""
    for scheme in schemes or ():
        col = _CONTAINER_COLUMNS.get(scheme)
        if not col:
            continue
        if _has_star_select(sql):
            return col
        for m in re.finditer(r"\b" + re.escape(col) + r"\b", sql, re.IGNORECASE):
            if not _JSON_EXTRACT_OP.match(sql[m.end():]):
                return col
    return None


def _redact_json_value(value, blocked: set[str]):
    """Layer 2 backstop for a single row value: if `value` is a JSON object
    — as text (an un-decoded JSONB column, the normal asyncpg shape since
    app/database/db.py registers no json/jsonb type codec) or already a dict — strip
    any blocklisted key found inside it and return the same type back.
    Non-object / non-JSON values, and objects with nothing to strip, pass
    through unchanged (including the identical string, to avoid needless
    re-serialization). This is what catches a whole-container exposure
    (`SELECT *` on CM Elevate, or any future JSONB container column)
    regardless of whether Layer 1's SQL-text scan saw it coming."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.startswith("{"):
            return value
        try:
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            return value
        if not isinstance(parsed, dict) or not (blocked & parsed.keys()):
            return value
        return json.dumps({k: v for k, v in parsed.items() if k not in blocked})
    if isinstance(value, dict):
        if not (blocked & value.keys()):
            return value
        return {k: v for k, v in value.items() if k not in blocked}
    return value


def redact_rows(rows: list[dict], schemes: list[str]) -> list[dict]:
    """Layer 2. Returns new row dicts with every blocklisted key fully
    removed (not nulled) for the active scheme(s), at the top level and
    (per _redact_json_value) inside any JSON-object value such as CM
    Elevate's scheme_specific. Rows are always copied, never mutated in
    place. When no scheme in `schemes` has a blocklist, `rows` is returned
    unchanged (same objects) — nothing to redact."""
    blocked = set(blocklisted_columns(schemes))
    if not blocked:
        return rows
    return [
        {k: _redact_json_value(v, blocked) for k, v in row.items() if k not in blocked}
        for row in rows
    ]
