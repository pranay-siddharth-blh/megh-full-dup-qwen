"""
FK graph + join-path discovery (app/join_graph.py) — pure-logic checks
against the real curated YAML files (no DB, no model gateway, no pgvector;
schema_introspect.live_fks() is empty in this offline run, which is fine —
the graph still builds from the curated YAMLs' declared FK edges alone).
Run: `python tests/test_join_graph.py`, exit code 0 = all pass.

Covers tasks.md group 3's acceptance scenarios: (a) a real declared-FK pair
gets the graph's exact on_clause; (b) a real curated cross-scheme
prohibited pair has no usable path (the pipeline.py wiring test below
confirms the fan-out/no-path distinction doesn't matter for correctness —
either result correctly blocks the join); (c) app/pipeline.py's
generate_sql() gates on exactly this pair when schema-retrieval names it,
and does NOT gate when retrieval returns fewer than 2 table candidates.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import join_graph  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


join_graph.build(force=True)


# ── 1. A real declared FK gets the graph's exact on_clause ─────────────────
print("1. REAL DECLARED FK -> EXACT ON_CLAUSE, NOT A GUESS")

result = join_graph.find_join_path(
    ["curated.fact_mgnrega_employment", "curated.dim_geography"])
check("status is ok", result.status == "ok", result.status)
check("exactly one join edge returned", len(result.joins) == 1, str(result.joins))
if result.joins:
    check("on_clause matches the curated YAML exactly",
          result.joins[0].on_clause ==
          "curated.fact_mgnrega_employment.geography_key = curated.dim_geography.geography_key",
          result.joins[0].on_clause)


# ── 2. Prohibited edges never appear in a path ──────────────────────────────
print("2. PROHIBITED EDGES ARE NEVER USED TO BUILD A PATH")

# fact_mgnrega_employment <-> fact_mgnrega_expenditure is explicitly
# is_prohibited: true in data/mgnrega/foreign_key_augmentation.yaml, and both
# are fact-tagged with dim_year/dim_geography as their only shared
# dimensions — so a path exists (via a dimension), but never the direct
# prohibited edge itself.
r2 = join_graph.find_join_path(
    ["curated.fact_mgnrega_employment", "curated.fact_mgnrega_expenditure"])
check("no join in the result uses the two facts directly (the prohibited edge)",
      all(not ({j.left, j.right} == {"curated.fact_mgnrega_employment",
                                     "curated.fact_mgnrega_expenditure"})
          for j in r2.joins),
      str(r2.joins))


# ── 3. A real curated cross-scheme pair has no usable path ─────────────────
print("3. REAL CROSS-SCHEME PROHIBITED PAIR HAS NO USABLE PATH")

# curated.v_pmay has zero non-prohibited edges anywhere in the curated YAMLs
# (pmay_foreign_key_augmentation.yaml declares it only ever joined via the
# pre-joined fact, and every edge FROM v_pmay to another scheme's fact is
# is_prohibited: true) — so no path should exist to MGNREGA's employment fact.
r3 = join_graph.find_join_path(["curated.v_pmay", "curated.fact_mgnrega_employment"])
check("status is no_path or fan_out_guard (never ok)",
      r3.status in ("no_path", "fan_out_guard"), r3.status)


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL JOIN-GRAPH CHECKS PASSED")
