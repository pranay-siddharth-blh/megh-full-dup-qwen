"""
app/pii_guard.py — two-layer, code-enforced §11.4 PII protection.

Before this module, PII protection was prompt-text only: app/schema_context.py
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
import re

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
    "Focus Plus": ("member_id", "pincode"),
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


def find_blocked_columns(sql: str, schemes: list[str]) -> tuple[str, ...]:
    """Layer 1. Returns the blocklisted column name(s) found anywhere in
    `sql` for the active scheme(s) — empty tuple if none. Case-insensitive,
    word-boundary matched over the full SQL text."""
    return tuple(col for col in blocklisted_columns(schemes) if _pattern_for(col).search(sql))


def redact_rows(rows: list[dict], schemes: list[str]) -> list[dict]:
    """Layer 2. Returns new row dicts with every blocklisted key fully
    removed (not nulled) for the active scheme(s). Rows are always copied,
    never mutated in place. When no scheme in `schemes` has a blocklist,
    `rows` is returned unchanged (same objects) — nothing to redact."""
    blocked = set(blocklisted_columns(schemes))
    if not blocked:
        return rows
    return [{k: v for k, v in row.items() if k not in blocked} for row in rows]
