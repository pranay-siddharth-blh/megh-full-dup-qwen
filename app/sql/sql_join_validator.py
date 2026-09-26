"""
Post-generation join validation (PRD §5.11 / follow-up to app/sql/join_graph.py
— see openspec/changes/join-graph-post-generation-validation/proposal.md).

app/sql/join_graph.py's find_join_path() only ever gates SQL *before* it is
generated, and only in the narrow case where schema_retrieval already named
2+ required tables (see that module's docstring and the archived design.md's
"Join discovery gates SQL generation only where it has a genuine
pre-generation signal" decision) — everywhere else, a model that ignores the
prompt's join hint and invents a relationship between two unrelated tables
is never caught. This module closes that gap by checking the SQL that was
actually generated, using sqlglot's AST — not a regex — because table
identity in a JOIN has to survive aliasing, full qualification, and chained
(snowflake) joins to be checked correctly at all.

Two things this is deliberately narrow about, both found while prototyping
against this codebase's real SQL (see proposal.md's Why):

1. A join is only ever validated when BOTH sides are schema-qualified
   (`curated.foo`, not a bare `foo`) in that SELECT scope's own FROM/JOIN
   list — a CTE reference parses as a bare, unqualified name, so this alone
   skips every CTE-to-CTE join with no separate CTE-name tracking needed.
   That matters because this codebase has a sanctioned pattern for
   cross-scheme comparisons — aggregate each side into a CTE, then join the
   CTEs on a shared non-key column (schema_context.py: "aggregate
   v_focus_plus to village_code in a CTE and FULL JOIN the aggregate") —
   which the FK graph fundamentally doesn't (and shouldn't) model: it's not
   a declared relationship, it's two independently-aggregated result sets
   sharing a grouping column. Flagging it would be exactly the false
   positive the archived design.md predicted for a naive checker.

2. A pair is flagged as invented only when join_graph.is_known() is True for
   BOTH sides. A table absent from every curated YAML and from live_fks()
   is left unvalidated, not treated as unrelated — otherwise a live_fks()
   outage (this module's own db.py notes the DB host "flaps") could make a
   real, previously-working live-only-FK join newly fail, since an
   uncatalogued table and a reviewed-and-prohibited one would look
   identical under a naive "not in the graph" check.
"""
import logging

import sqlglot
from sqlglot import exp

from app.sql import join_graph

logger = logging.getLogger(__name__)


def _table_key(table: exp.Table) -> str | None:
    """The join_graph node key ("schema.table") for a real, schema-qualified
    table reference — None for a bare name (always a CTE alias in this
    codebase's convention of always qualifying real tables with `curated.`/
    `raw.`/`meta.`/`semantic.`)."""
    if not table.db:
        return None
    return f"{table.db}.{table.name}"


def _alias_map(select: exp.Select) -> dict[str, str]:
    """alias-or-bare-name (lowercased) -> "schema.table", for every
    schema-qualified table referenced directly in this SELECT scope. A CTE
    reference contributes nothing here (no schema), which is exactly how
    CTE-to-CTE joins end up unresolved and skipped below."""
    mapping: dict[str, str] = {}
    for table in select.find_all(exp.Table):
        key = _table_key(table)
        if key is None:
            continue
        mapping[(table.alias_or_name or table.name).lower()] = key
    return mapping


def referenced_tables(sql: str) -> set[str]:
    """Every schema-qualified table ("schema.table", lowercased) referenced
    anywhere in `sql` — every SELECT scope, not just JOIN ON clauses, unlike
    _alias_map which is find_invented_joins' narrower per-scope helper.
    Lowercased because Postgres folds unquoted identifiers to lowercase and
    the curated YAMLs' `ref`/node keys are always written lowercase — an
    exact-case comparison against them would false-positive on a
    differently-cased but identical table the model wrote. Empty when sql
    fails to parse (a different check's concern, same stance as
    find_invented_joins) or names no schema-qualified table at all (e.g.
    every reference is a bare CTE alias)."""
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:  # noqa: BLE001 — parse failures are not this check's job
        return set()
    return {
        key.lower()
        for table in tree.find_all(exp.Table)
        for key in [_table_key(table)]
        if key is not None
    }


def find_invented_joins(sql: str) -> list[tuple[str, str]]:
    """Returns [(table_a, table_b), ...] — every JOIN in `sql` whose own ON
    clause connects two tables that join_graph knows about (is_known) but
    has no declared relationship between (not has_edge). Empty when sql
    fails to parse (a different check's concern), when a JOIN's ON clause
    doesn't resolve cleanly to exactly two known, schema-qualified tables
    (a CTE-involved join, a USING/CROSS join, a composite condition
    spanning 3+ tables, an unqualified reference) — conservative by design,
    same "additive signal only where it has genuine confidence" tier
    join_graph.py already commits to."""
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:  # noqa: BLE001 — parse failures are not this check's job
        return []

    invented: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for select in tree.find_all(exp.Select):
        alias_map = _alias_map(select)
        for join in select.find_all(exp.Join):
            on = join.args.get("on")
            if on is None:
                continue  # USING/CROSS/natural join — not this check's case
            resolved: set[str] = set()
            unresolved = False
            for col in on.find_all(exp.Column):
                prefix = (col.table or "").lower()
                if not prefix or prefix not in alias_map:
                    unresolved = True
                    continue
                resolved.add(alias_map[prefix])
            if unresolved or len(resolved) != 2:
                continue
            a, b = sorted(resolved)
            if not (join_graph.is_known(a) and join_graph.is_known(b)):
                continue
            if join_graph.has_edge(a, b):
                continue
            pair = (a, b)
            if pair not in seen:
                seen.add(pair)
                invented.append(pair)

    return invented
