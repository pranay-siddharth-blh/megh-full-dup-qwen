"""
Query-log FK miner (app/fk_miner.py) — pure-logic + monkeypatched-dependency
checks against the real curated YAML files (no live DB; app.db.fetch_rows
is monkeypatched to return a fixed, in-memory query log). Run:
`python tests/test_fk_miner.py`, exit code 0 = all pass.

Covers openspec/changes/join-discovery-fk-log-mining/tasks.md group 2's
acceptance scenarios: (a) a recurring unknown-edge pair is surfaced with
the right occurrence count; (b) a pair already covered by a declared edge
is never surfaced, however often it's joined; (c) a pair below
min_occurrences is dropped; (d) a CTE-aliased/unqualified join contributes
nothing; (e) a table unknown to join_graph is skipped, not guessed at;
(f) a malformed SQL string is skipped without raising.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import db, fk_miner, join_graph  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


join_graph.build(force=True)

# Real, known-but-unrelated pair (see tests/test_join_graph.py's check 3):
# curated.v_pmay has zero non-prohibited edges to any MGNREGA table.
_UNRELATED_A, _UNRELATED_B = "curated.v_pmay", "curated.fact_mgnrega_employment"
# Real declared FK (tests/test_join_graph.py's check 1) -- already has_edge().
_DECLARED_A, _DECLARED_B = "curated.fact_mgnrega_employment", "curated.dim_geography"
# A second known-but-unrelated pair, used once only (below min_occurrences).
_RARE_A, _RARE_B = "curated.v_cm_elevate", "curated.v_focus_plus"

assert not join_graph.has_edge(_UNRELATED_A, _UNRELATED_B), "test fixture assumption broken"
assert join_graph.has_edge(_DECLARED_A, _DECLARED_B), "test fixture assumption broken"
assert not join_graph.has_edge(_RARE_A, _RARE_B), "test fixture assumption broken"

_QUERY_LOG_ROWS: list[dict] = []


async def _fake_fetch_rows(sql, params=None):
    return _QUERY_LOG_ROWS


async def _run():
    orig_fetch_rows = db.fetch_rows
    db.fetch_rows = _fake_fetch_rows
    try:
        _QUERY_LOG_ROWS[:] = [
            # (a) unrelated pair, joined 3x on the same columns -> surfaced, occurrences == 3
            {"sql": f"SELECT * FROM {_UNRELATED_A} p JOIN {_UNRELATED_B} m "
                     "ON p.village_code = m.village_code"},
            {"sql": f"SELECT * FROM {_UNRELATED_A} p JOIN {_UNRELATED_B} m "
                     "ON p.village_code = m.village_code WHERE m.year_key = 2024"},
            {"sql": f"SELECT count(*) FROM {_UNRELATED_B} m JOIN {_UNRELATED_A} p "
                     "ON m.village_code = p.village_code"},
            # (b) already-declared-edge pair, joined 5x -> never surfaced
            *[{"sql": f"SELECT * FROM {_DECLARED_A} f JOIN {_DECLARED_B} g "
                       "ON f.geography_key = g.geography_key"}] * 5,
            # (c) a second unrelated pair, joined only once -> below min_occurrences
            {"sql": f"SELECT * FROM {_RARE_A} c JOIN {_RARE_B} fp "
                     "ON c.district_code = fp.district_code"},
            # (d) CTE-to-CTE join -- "agg" is a bare alias, never schema-qualified
            {"sql": f"WITH agg AS (SELECT village_code FROM {_UNRELATED_B} GROUP BY village_code) "
                     f"SELECT * FROM agg a JOIN {_UNRELATED_A} p ON a.village_code = p.village_code"},
            # (e) one side is a table join_graph has never catalogued
            {"sql": f"SELECT * FROM {_UNRELATED_A} p JOIN curated.made_up_table_xyz x "
                     "ON p.some_col = x.other_col"},
            # (f) malformed SQL -- must be skipped, not raise
            {"sql": "SELEC FRM invalid ((( sql this is not valid at all"},
        ]

        candidates = await fk_miner.mine_implicit_fks(min_occurrences=2)

        print("1. RECURRING UNKNOWN-EDGE PAIR IS SURFACED WITH THE RIGHT COUNT")
        unrelated_pair = {c for c in candidates
                          if {c.from_table, c.to_table} == {_UNRELATED_A, _UNRELATED_B}}
        check("exactly one candidate for the unrelated pair", len(unrelated_pair) == 1,
              str(candidates))
        if unrelated_pair:
            cand = next(iter(unrelated_pair))
            check("occurrence count is 3 (merged regardless of join-side order)",
                  cand.occurrences == 3, str(cand.occurrences))

        print("2. A PAIR ALREADY COVERED BY A DECLARED EDGE IS NEVER SURFACED")
        declared_pair = [c for c in candidates
                         if {c.from_table, c.to_table} == {_DECLARED_A, _DECLARED_B}]
        check("declared-edge pair not in candidates despite 5 occurrences",
              len(declared_pair) == 0, str(declared_pair))

        print("3. A PAIR BELOW min_occurrences IS DROPPED")
        rare_pair = [c for c in candidates
                    if {c.from_table, c.to_table} == {_RARE_A, _RARE_B}]
        check("single-occurrence pair not in candidates (min_occurrences=2)",
              len(rare_pair) == 0, str(rare_pair))

        print("4. A MALFORMED / UNQUALIFIED / UNKNOWN-TABLE JOIN NEVER CRASHES OR APPEARS")
        check("no candidate names the never-catalogued table",
              all("curated.made_up_table_xyz" not in (c.from_table, c.to_table)
                  for c in candidates), str(candidates))
        check("no candidate names the bare CTE alias",
              all("agg" not in (c.from_table, c.to_table) for c in candidates), str(candidates))
        check("exactly one candidate total (only the recurring unrelated pair qualifies)",
              len(candidates) == 1, str(candidates))

        print("5. min_occurrences=1 SURFACES THE OTHERWISE-DROPPED RARE PAIR TOO")
        candidates_lenient = await fk_miner.mine_implicit_fks(min_occurrences=1)
        rare_lenient = [c for c in candidates_lenient
                       if {c.from_table, c.to_table} == {_RARE_A, _RARE_B}]
        check("rare pair appears once min_occurrences is lowered to 1",
              len(rare_lenient) == 1 and rare_lenient[0].occurrences == 1,
              str(rare_lenient))
    finally:
        db.fetch_rows = orig_fetch_rows


asyncio.run(_run())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL FK-MINER CHECKS PASSED")
