"""
Mines implicit FK candidates from executed query history (proposal §5.9:
"SQLGlot to optionally mine implicit FKs from existing query logs" — see
openspec/changes/join-discovery-fk-log-mining/proposal.md).

This is the query-log-mining leg the original proposal named alongside
NetworkX/graph-build and SQLAlchemy/information_schema introspection for
join discovery (app/join_graph.py covers the other two, deliberately via
plain BFS and the existing asyncpg pool instead — see that module's
docstring and the archived phase-3 design.md).

Deliberately read-only and advisory only: this module NEVER writes into
join_graph's live graph or any foreign_key_augmentation.yaml. Every
candidate is a report for a human SME to review and, if they agree, add
to the relevant scheme's curated YAML by hand — the same "reviewed by a
SME" step join_graph.py's own docstring requires for any implicit
(non-FK-constraint) edge. Auto-merging a query-log pattern straight into
the graph would reintroduce the "something other than a declared/curated
edge invents a join" risk join-discovery's spec exists to prevent.

Column-level sibling of app/sql_join_validator.py's find_invented_joins():
that function already resolves per-SELECT-scope, schema-qualified table
aliases and flags JOIN-ON pairs that are is_known() on both sides but have
no has_edge() between them — exactly this module's "known tables, joined
in real SQL, no declared relationship" signal — but it only needs table
identity to flag a single query, so it discards the join columns and never
aggregates across queries. This module keeps the columns and counts
occurrences across many historical app.query_audit rows instead.
"""
import logging
from collections import Counter
from typing import NamedTuple

import sqlglot
from sqlglot import exp

from app import db, join_graph

logger = logging.getLogger(__name__)

_DEFAULT_LOG_LIMIT = 5000
_DEFAULT_MIN_OCCURRENCES = 2


class MinedFKCandidate(NamedTuple):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    occurrences: int
    sample_sql: str


def _table_key(table: exp.Table) -> str | None:
    """The join_graph node key ("schema.table") for a real, schema-qualified
    table reference — None for a bare name (a CTE alias in this codebase's
    convention of always schema-qualifying real tables), matching
    sql_join_validator._table_key exactly."""
    if not table.db:
        return None
    return f"{table.db}.{table.name}".lower()


def _alias_map(select: exp.Select) -> dict[str, str]:
    """alias-or-bare-name (lowercased) -> "schema.table", for every
    schema-qualified table referenced directly in this SELECT scope. A CTE
    reference contributes nothing (no schema), so a CTE-to-CTE join's
    columns never resolve below — same skip sql_join_validator relies on."""
    mapping: dict[str, str] = {}
    for table in select.find_all(exp.Table):
        key = _table_key(table)
        if key is None:
            continue
        mapping[(table.alias_or_name or table.name).lower()] = key
    return mapping


def _resolve_column(col: exp.Column, alias_map: dict[str, str]) -> tuple[str, str] | None:
    prefix = (col.table or "").lower()
    if not prefix or prefix not in alias_map:
        return None
    return alias_map[prefix], col.name.lower()


def _extract_equalities(sql: str):
    """Yields (table_a, col_a, table_b, col_b) for every JOIN-ON equality in
    `sql` that resolves both sides to a distinct, schema-qualified table.
    Conservative by design, same skips as sql_join_validator.find_invented_joins:
    CTE-to-CTE joins, USING/CROSS/natural joins (no `on`), unresolved
    prefixes, and any non-column-to-column condition (a literal, a function
    call) all yield nothing rather than a guessed pair. Malformed SQL yields
    nothing instead of raising — mining historical text is best-effort."""
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:  # noqa: BLE001 — malformed/historical SQL isn't this job's concern
        return

    for select in tree.find_all(exp.Select):
        alias_map = _alias_map(select)
        for join in select.find_all(exp.Join):
            on = join.args.get("on")
            if on is None:
                continue
            for eq in on.find_all(exp.EQ):
                left, right = eq.this, eq.expression
                if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                    continue
                l_res = _resolve_column(left, alias_map)
                r_res = _resolve_column(right, alias_map)
                if l_res is None or r_res is None:
                    continue
                (lt, lc), (rt, rc) = l_res, r_res
                if lt == rt:
                    continue
                yield lt, lc, rt, rc


async def _fetch_query_log(log_limit: int, schemes: list[str] | None) -> list[str]:
    if schemes:
        rows = await db.fetch_rows(
            "SELECT sql FROM app.query_audit "
            "WHERE sql IS NOT NULL AND allowed = TRUE AND schemes && $2 "
            "ORDER BY id DESC LIMIT $1",
            [log_limit, schemes],
        )
    else:
        rows = await db.fetch_rows(
            "SELECT sql FROM app.query_audit "
            "WHERE sql IS NOT NULL AND allowed = TRUE "
            "ORDER BY id DESC LIMIT $1",
            [log_limit],
        )
    return [r["sql"] for r in rows if r.get("sql")]


async def mine_implicit_fks(*, log_limit: int = _DEFAULT_LOG_LIMIT,
                            min_occurrences: int = _DEFAULT_MIN_OCCURRENCES,
                            schemes: list[str] | None = None) -> list[MinedFKCandidate]:
    """Scans up to `log_limit` most recent allowed queries from
    app.query_audit, extracts every JOIN-ON equality between two tables
    join_graph already knows about (curated YAML or live_fks()) but has no
    declared edge between, and returns those seen at least
    `min_occurrences` times, most frequent first. Purely advisory — see
    module docstring; callers never merge this into the live graph."""
    try:
        sql_rows = await _fetch_query_log(log_limit, schemes)
    except Exception:  # noqa: BLE001 — best-effort, same posture as join_graph.build()
        logger.warning("fk_miner: could not read app.query_audit", exc_info=True)
        return []

    join_graph.build()
    counts: Counter[tuple[str, str, str, str]] = Counter()
    samples: dict[tuple[str, str, str, str], str] = {}
    contributing = 0

    for sql in sql_rows:
        found_any = False
        for lt, lc, rt, rc in _extract_equalities(sql):
            if not (join_graph.is_known(lt) and join_graph.is_known(rt)):
                continue  # never catalogued at all -- not this tool's job to guess
            if join_graph.has_edge(lt, rt):
                continue  # already declared or curated -- nothing new to surface
            key = (lt, lc, rt, rc) if lt < rt else (rt, rc, lt, lc)
            counts[key] += 1
            samples.setdefault(key, sql)
            found_any = True
        if found_any:
            contributing += 1

    candidates = [
        MinedFKCandidate(lt, lc, rt, rc, n, samples[(lt, lc, rt, rc)])
        for (lt, lc, rt, rc), n in counts.items()
        if n >= min_occurrences
    ]
    candidates.sort(key=lambda c: c.occurrences, reverse=True)
    logger.info(
        "fk_miner: scanned %d logged queries (%d contributed a candidate edge), "
        "%d novel implicit-FK candidate(s) at >= %d occurrences",
        len(sql_rows), contributing, len(candidates), min_occurrences,
    )
    return candidates
