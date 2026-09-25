"""
Post-generation join validation (app/sql/sql_join_validator.py,
openspec/changes/join-graph-post-generation-validation) — pure-logic +
monkeypatched-dependency checks, no DB, no model gateway. Run:
`python tests/unit/test_sql_join_validator.py`, exit code 0 = all pass.

Covers tasks.md group 2's acceptance scenarios (find_invented_joins, unit)
and group 3's (wired into execute_with_repair as a repairable ValueError,
integration) — plus group 1.3's is_known/has_edge distinction, since that's
the mechanism this whole module depends on.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.sql import join_graph  # noqa: E402
from app.clients import llm
from app.orchestration import pipeline
from app.sql import sql_join_validator

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


join_graph.build(force=True)
_ENTITY_RESULT = {"resolved": {}, "notes": [], "display": {}}


# ── 1. is_known / has_edge distinction (task 1.3) ───────────────────────────
print("1. is_known VS has_edge — THE DISTINCTION THIS MODULE DEPENDS ON")
check("v_focus_plus is known (named in its YAML's edges)",
      join_graph.is_known("curated.v_focus_plus"))
check("v_focus_plus has no edge to fact_pmay_house (every declared edge is prohibited)",
      not join_graph.has_edge("curated.v_focus_plus", "curated.fact_pmay_house"))
check("a wholly made-up table is not known",
      not join_graph.is_known("curated.totally_made_up_table_xyz"))
check("a real declared FK pair has an edge",
      join_graph.has_edge("curated.fact_mgnrega_employment", "curated.dim_geography"))


# ── 2. find_invented_joins — unit tests on the 7 verified shapes ───────────
print("2. find_invented_joins — REAL QUERY SHAPES")

sql_valid_chained = """
SELECT g.lgd_district, SUM(f.wage_amount) AS total
FROM curated.fact_mgnrega_employment f
JOIN curated.dim_geography g ON f.geography_key = g.geography_key
JOIN curated.dim_geography_alias a ON a.geography_key = g.geography_key
WHERE f.year_key = 2024
GROUP BY 1
LIMIT 10;
"""
check("valid star + chained dimension join: no false positive",
      sql_join_validator.find_invented_joins(sql_valid_chained) == [])

sql_sanctioned_cte = """
WITH fp AS (
  SELECT village_code, SUM(amount_disbursed) AS amt FROM curated.v_focus_plus GROUP BY village_code
), pm AS (
  SELECT village_code, COUNT(*) AS cnt FROM curated.fact_pmay_house GROUP BY village_code
)
SELECT fp.village_code, fp.amt, pm.cnt FROM fp FULL JOIN pm ON fp.village_code = pm.village_code LIMIT 10;
"""
check("sanctioned CTE-to-CTE cross-scheme pattern (schema_context.py's own worked "
      "example) is NOT flagged — the false positive design.md predicted, avoided",
      sql_join_validator.find_invented_joins(sql_sanctioned_cte) == [])

sql_invented_direct = """
SELECT fp.village_code, fp.amount_disbursed, ph.house_status
FROM curated.v_focus_plus fp
JOIN curated.fact_pmay_house ph ON fp.village_code = ph.village_code
LIMIT 10;
"""
invented = sql_join_validator.find_invented_joins(sql_invented_direct)
check("real currently-prohibited direct join (v_focus_plus/fact_pmay_house, no CTE) IS flagged",
      invented == [("curated.fact_pmay_house", "curated.v_focus_plus")], str(invented))

sql_unaliased = """
SELECT curated.dim_geography.lgd_district, SUM(curated.fact_mgnrega_expenditure.total_expenditure)
FROM curated.fact_mgnrega_expenditure
JOIN curated.dim_geography ON curated.fact_mgnrega_expenditure.geography_key = curated.dim_geography.geography_key
GROUP BY 1 LIMIT 10;
"""
check("fully-qualified, unaliased real join: no false positive",
      sql_join_validator.find_invented_joins(sql_unaliased) == [])

sql_unknown_table = """
SELECT * FROM curated.totally_uncatalogued_table u
JOIN curated.dim_geography g ON u.geography_key = g.geography_key
LIMIT 10;
"""
check("a join to a table absent from every YAML/live_fks() is left unvalidated (not flagged)",
      sql_join_validator.find_invented_joins(sql_unknown_table) == [])

sql_cross_join = """
SELECT a.wage_amount FROM curated.fact_mgnrega_employment a
CROSS JOIN curated.dim_geography g
LIMIT 10;
"""
check("a CROSS JOIN (no ON clause) is skipped, not flagged",
      sql_join_validator.find_invented_joins(sql_cross_join) == [])

check("unparseable SQL returns [] rather than raising",
      sql_join_validator.find_invented_joins("not even valid sql (((") == [])


# ── 3. Wired into execute_with_repair as a repairable ValueError ───────────
print("3. WIRED INTO execute_with_repair — REPAIRABLE, NOT A HARD DENIAL")


async def _run():
    async def _fake_verify_sql(*_a, **_kw):
        return None

    async def _fake_run_readonly(_sql):
        return [{"cnt": 5}]

    repair_calls: list[str] = []

    async def _fake_sql_generator(prompt, **_kw):
        repair_calls.append(prompt)
        return "SELECT COUNT(*) AS cnt FROM curated.fact_pmay_house LIMIT 5;"

    orig_verify = pipeline._verify_sql
    orig_run_readonly = pipeline.run_readonly
    orig_sql_generator = llm.call_sql_generator
    pipeline._verify_sql = _fake_verify_sql
    pipeline.run_readonly = _fake_run_readonly
    llm.call_sql_generator = _fake_sql_generator

    try:
        sql, rows = await pipeline.execute_with_repair(
            "compare focus plus and pmay by village", ["Focus Plus", "PMAY-G"], _ENTITY_RESULT,
            initial_sql="SELECT fp.village_code, ph.house_status FROM curated.v_focus_plus fp "
                        "JOIN curated.fact_pmay_house ph ON fp.village_code = ph.village_code LIMIT 5;")
        check("an invented-join initial_sql triggers exactly one repair call",
              len(repair_calls) == 1, str(len(repair_calls)))
        check("the repaired SQL (no invented join) is what executes and returns",
              sql == "SELECT COUNT(*) AS cnt FROM curated.fact_pmay_house LIMIT 5" and rows == [{"cnt": 5}],
              f"sql={sql!r} rows={rows!r}")

        # A clean query with a real declared-FK join is never touched by this check.
        repair_calls.clear()
        sql2, rows2 = await pipeline.execute_with_repair(
            "employment by district", ["MGNREGA"], _ENTITY_RESULT,
            initial_sql="SELECT g.lgd_district, SUM(f.wage_amount) AS total "
                        "FROM curated.fact_mgnrega_employment f "
                        "JOIN curated.dim_geography g ON f.geography_key = g.geography_key "
                        "GROUP BY 1 LIMIT 10;")
        check("a real declared-FK join executes on the first attempt, no repair needed",
              len(repair_calls) == 0 and rows2 == [{"cnt": 5}], f"repairs={len(repair_calls)} rows={rows2!r}")
    finally:
        pipeline._verify_sql = orig_verify
        pipeline.run_readonly = orig_run_readonly
        llm.call_sql_generator = orig_sql_generator


asyncio.run(_run())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL SQL JOIN VALIDATOR CHECKS PASSED")
