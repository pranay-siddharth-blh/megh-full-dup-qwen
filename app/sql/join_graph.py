"""
FK graph + join-path discovery (proposal §5.9 / capability `join-discovery`).

Builds an in-memory adjacency-list graph from two sources:
  1. schema_introspect.live_fks() — real FK constraints, already loaded
     read-only from megh_db's pg_constraint at startup. This module does NOT
     query megh_db itself; it consumes whatever schema_introspect already
     cached (best-effort — empty if that startup read didn't land).
  2. Each scheme's curated foreign_key_augmentation.yaml `edges` section —
     every edge NOT marked is_prohibited, carrying its exact on_clause. This
     loader never inspects `declared` (true/false/inferred) — only
     `is_prohibited` gates whether an edge is added. That matters because
     Focus Plus's file has a genuine curated-only case already: its four
     joins off fact_focus_plus_disbursement are all `declared: inferred`
     ("NOT ONE FOREIGN KEY IN THIS FILE IS A VERIFIED CONSTRAINT" per that
     file's own header) — read off column naming, not information_schema.
     Three of those (-> dim_geography, dim_year, dim_scheme) are not
     prohibited, so they ARE loaded here, and they are NOT redundant with
     live_fks(): Focus Plus has no real pg_constraint FKs for live_fks() to
     find, so without this YAML source those three joins would not be in
     the graph at all. MGNREGA, PMAY-G, and CM Elevate have no
     declared:inferred edges today — every one of their edges is either a
     real FK (declared: true) or a deliberate prohibition — so for those
     three schemes this source and live_fks() do cover overlapping ground.
     The YAML source stays wired in for every scheme regardless, both for
     Focus Plus's existing case and the day another scheme needs one (see
     docs/scheme-onboarding.md).

A node tagged `readable_by_read_role: false` in a YAML `nodes` section (the
`raw` schema) is excluded from the graph entirely, regardless of whether the
specific edge into it also carries `is_prohibited: true` — one PMAY-G edge
into raw.source_rows was found missing that flag, so node-level exclusion is
the safety net, not just the edge-level flag.

Plain BFS shortest path — no NetworkX (see design.md: every scheme's graph
today has under 20 nodes, and there is no curated data volume that would
justify it).

Enforcement tier (see design.md's "Join discovery gates SQL generation only
where it has a genuine pre-generation signal" decision): find_join_path()
is a pure graph function with no opinion on how its result is used. It is
NOT a runtime SQL parser — app/orchestration/pipeline.py decides, based on whether
schema_retrieval already supplied 2+ required tables, whether a bad result
here gates generation (ClarificationNeeded) or is merely an additive prompt
hint, the same tier as the existing PROHIBITED JOINS mechanism.
"""
import logging
from collections import deque
from pathlib import Path
from typing import NamedTuple

import yaml

from app.sql import schema_introspect

logger = logging.getLogger(__name__)

_DATA_PART = Path(__file__).resolve().parents[2] / "data"
_FK_FILES = {
    "MGNREGA": _DATA_PART / "mgnrega" / "foreign_key_augmentation.yaml",
    "PMAY-G": _DATA_PART / "pmay" / "pmay_foreign_key_augmentation.yaml",
    "Focus Plus": _DATA_PART / "focus_plus" / "focusplus_foreign_key_augmentation.yaml",
    "CM Elevate": _DATA_PART / "cm_elevate" / "cmelevate_foreign_key_augmentation.yaml",
}

_FACT_ROLES = {"fact", "fact_view"}
_DIMENSION_ROLES = {"dimension"}

_fact_nodes: set[str] = set()
_dimension_nodes: set[str] = set()
_unreadable_nodes: set[str] = set()
_graph: dict[str, dict[str, str]] = {}
# Every table named anywhere in the curated YAMLs or live_fks() — a `nodes:`
# entry, either end of an `edges:` entry (INCLUDING a prohibited one, unlike
# _graph's keys, which only ever hold tables with at least one non-prohibited
# edge), or a live_fks() participant. Deliberately broader than _graph: a
# table can be "known" (an SME looked at it and either declared or explicitly
# prohibited every relationship it has) while still having zero live edges —
# curated.v_focus_plus is exactly this today, every one of its 6 declared
# edges is_prohibited. app/sql/sql_join_validator.py needs this distinction to
# tell "these two tables were reviewed and found unrelated" (flag it) apart
# from "this table was never catalogued at all" (skip — don't guess), which
# matters most when live_fks() is empty (a DB hiccup at startup) and would
# otherwise make a never-catalogued live-only-FK table look identical to a
# reviewed-and-prohibited one.
_known_nodes: set[str] = set()
_loaded = False


def _add_edge(a: str, b: str, on_clause: str | None) -> None:
    _graph.setdefault(a, {})
    _graph.setdefault(b, {})
    clause = on_clause or ""
    # Don't let a later, clause-less duplicate (e.g. from live_fks() re-adding
    # an edge the YAML already gave a richer on_clause for) blank out a
    # clause we already have.
    if clause or a not in _graph or b not in _graph[a]:
        _graph[a][b] = clause or _graph[a].get(b, "")
        _graph[b][a] = clause or _graph[b].get(a, "")


def build(force: bool = False) -> None:
    """Build the graph from every scheme's curated YAML plus
    schema_introspect.live_fks() (best-effort, already loaded read-only from
    megh_db). Safe to call again — replaces state, never merges stale
    entries, so a reload actually drops anything removed upstream."""
    global _loaded
    if _loaded and not force:
        return

    _fact_nodes.clear()
    _dimension_nodes.clear()
    _unreadable_nodes.clear()
    _graph.clear()
    _known_nodes.clear()

    for scheme, path in _FK_FILES.items():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning("join_graph: no FK file for %s at %s", scheme, path)
            continue
        fk = (data or {}).get("foreign_key_augmentation", {})

        for name, node in (fk.get("nodes") or {}).items():
            _known_nodes.add(name)
            role = (node or {}).get("role")
            if role in _FACT_ROLES:
                _fact_nodes.add(name)
            elif role in _DIMENSION_ROLES:
                _dimension_nodes.add(name)
            if (node or {}).get("readable_by_read_role") is False:
                _unreadable_nodes.add(name)

        for edge in fk.get("edges") or []:
            from_table, to_table = edge.get("from_table"), edge.get("to_table")
            if from_table:
                _known_nodes.add(from_table)
            if to_table:
                _known_nodes.add(to_table)
            if edge.get("is_prohibited"):
                continue
            if not from_table or not to_table:
                continue
            if from_table in _unreadable_nodes or to_table in _unreadable_nodes:
                continue
            # Composite-key edges (from_column/to_column as lists) carry no
            # single-column on_clause to synthesize from live_fks() anyway —
            # the YAML's own on_clause (possibly None for a prohibited edge,
            # already skipped above) is the only source of truth here.
            _add_edge(from_table, to_table, edge.get("on_clause"))

    for fk_row in schema_introspect.live_fks():
        a, b = fk_row["from"], fk_row["to"]
        _known_nodes.add(a)
        _known_nodes.add(b)
        if a in _unreadable_nodes or b in _unreadable_nodes:
            continue
        on_clause = f"{a}.{fk_row['from_column']} = {b}.{fk_row['to_column']}"
        _add_edge(a, b, on_clause)

    _loaded = True
    logger.info("join_graph: built graph — %d nodes, %d fact-tagged, %d dimension-tagged",
               len(_graph), len(_fact_nodes), len(_dimension_nodes))


def _bfs_path(start: str, goal: str) -> list[str] | None:
    if start == goal:
        return [start]
    if start not in _graph or goal not in _graph:
        return None
    visited = {start}
    queue: deque[list[str]] = deque([[start]])
    while queue:
        path = queue.popleft()
        for neighbor in _graph.get(path[-1], {}):
            if neighbor in visited:
                continue
            new_path = path + [neighbor]
            if neighbor == goal:
                return new_path
            visited.add(neighbor)
            queue.append(new_path)
    return None


class JoinEdge(NamedTuple):
    left: str
    right: str
    on_clause: str


class JoinPathResult(NamedTuple):
    status: str  # "ok" | "no_path" | "fan_out_guard"
    joins: list[JoinEdge]
    tables: list[str]
    path: list[str] | None = None  # populated on fan_out_guard, for diagnostics


def find_join_path(tables: list[str]) -> JoinPathResult:
    """Given required tables (2+), returns a JoinPathResult built ONLY from
    edges already in the graph (real FK or curated non-prohibited) — never
    an invented ON clause. Status:
      "ok"             — every consecutive pair has a path; .joins holds the
                          explicit edges to emit.
      "no_path"        — some consecutive pair has no path at all.
      "fan_out_guard"   — a path exists between two fact-tagged tables but
                          does not route through a shared dimension; .path
                          holds the unsafe path for diagnostics.
    Callers decide how to use a non-"ok" result (hard-gate vs. hint) — this
    function has no opinion on enforcement tier (see module docstring)."""
    build()
    uniq = list(dict.fromkeys(tables))
    if len(uniq) <= 1:
        return JoinPathResult(status="ok", joins=[], tables=uniq)

    joins: list[JoinEdge] = []
    seen_pairs: set[tuple[str, str]] = set()
    for a, b in zip(uniq, uniq[1:]):
        path = _bfs_path(a, b)
        if path is None:
            return JoinPathResult(status="no_path", joins=[], tables=[a, b])

        if a in _fact_nodes and b in _fact_nodes:
            interior = path[1:-1]
            if not any(n in _dimension_nodes for n in interior):
                return JoinPathResult(status="fan_out_guard", joins=[], tables=[a, b], path=path)

        for x, y in zip(path, path[1:]):
            pair = (x, y) if x < y else (y, x)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            on_clause = _graph[x].get(y) or _graph[y].get(x) or f"{x} = {y}"
            joins.append(JoinEdge(left=x, right=y, on_clause=on_clause))

    return JoinPathResult(status="ok", joins=joins, tables=uniq)


def has_edge(a: str, b: str) -> bool:
    """True if `a` and `b` have a direct, non-prohibited edge between them —
    used by app/sql/sql_join_validator.py to flag a JOIN whose own ON clause
    connects two tables with no declared relationship at all. Not the same
    question as is_known(): a known-but-unrelated pair (e.g.
    curated.v_focus_plus and any other scheme's fact — every one of
    v_focus_plus's edges is is_prohibited) answers False here too."""
    build()
    return b in _graph.get(a, {}) or a in _graph.get(b, {})


def is_fact(table: str) -> bool:
    """True if `table` is tagged role: fact / fact_view in its scheme's curated
    YAML `nodes:` section. Used by the §5.11 "tables must belong to the
    retrieved set" check to scope itself to fact tables only — a dimension
    table (e.g. curated.dim_geography) is legitimately joined in via the FK
    graph without schema-retrieval ever having to name it as a top-K
    candidate, so checking dimensions here would flag known-good queries."""
    build()
    return table in _fact_nodes


def is_known(table: str) -> bool:
    """True if `table` was named anywhere in the curated YAMLs (a `nodes:`
    entry, or either end of an `edges:` entry — prohibited or not) or by
    live_fks(). Broader than being a _graph key: a table can be known and
    still have zero live edges (see has_edge's docstring). A table this
    returns False for was never reviewed at all — sql_join_validator.py
    deliberately does not judge those, to avoid a live_fks() outage making
    an uncatalogued table indistinguishable from a reviewed-and-prohibited
    one."""
    build()
    return table in _known_nodes


def snapshot() -> dict:
    return {
        "nodes": len(_graph),
        "known_nodes": len(_known_nodes),
        "fact_nodes": sorted(_fact_nodes),
        "dimension_nodes": sorted(_dimension_nodes),
        "unreadable_nodes": sorted(_unreadable_nodes),
    }
