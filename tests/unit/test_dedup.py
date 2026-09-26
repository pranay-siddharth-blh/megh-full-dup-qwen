"""
Duplicate-record guard (app/sql/dedup.py) — pure SQL-text checks, no DB:
`python tests/unit/test_dedup.py`, exit code 0 = all pass.

Live figures behind it (2026-09-23 audit): curated.v_cm_elevate 8,627 rows /
8,600 distinct request_id (Jirang 760 / 752); curated.v_pmay 170,981 house rows
/ 170,613 distinct reg_no. The rewrite itself was also run against megh_db and
returned those distinct figures.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")

from app.sql.dedup import dedupe_sql, note_for  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


print("1. CM ELEVATE")
sql, applied = dedupe_sql("SELECT COUNT(*) AS applications\nFROM curated.v_cm_elevate\nWHERE lgd_block = 'JIRANG'\nLIMIT 1")
check("bare view rewritten to one row per request_id",
      "FROM (SELECT DISTINCT ON (request_id) * FROM curated.v_cm_elevate ORDER BY request_id, cm_elevate_fact_id DESC) AS v_cm_elevate" in sql, sql)
check("WHERE clause kept after the rewritten FROM", "AS v_cm_elevate\nWHERE lgd_block = 'JIRANG'" in sql, sql)
check("reports what it de-duplicated on", applied == ["application number"], str(applied))
sql, _ = dedupe_sql("SELECT c.scheme_name, COUNT(*) FROM curated.v_cm_elevate c GROUP BY c.scheme_name")
check("existing alias preserved", ") AS c GROUP BY" in sql, sql)
sql, _ = dedupe_sql("SELECT COUNT(*) FROM curated.v_cm_elevate WHERE x = 1")
check("a keyword after the view is not taken as an alias", ") AS v_cm_elevate WHERE x = 1" in sql, sql)

print("2. PMAY-G")
sql, applied = dedupe_sql("SELECT COUNT(*), SUM(sanctioned_amount) FROM curated.v_pmay AS p WHERE NOT p.is_placeholder")
check("v_pmay rewritten to one row per reg_no (NULL-safe)",
      "DISTINCT ON (COALESCE(reg_no, 'fact:' || pmay_fact_id::text))" in sql and ") AS p WHERE" in sql, sql)
check("PMAY label", applied == ["registration number"], str(applied))

print("3. SHAPES")
sql, _ = dedupe_sql("WITH x AS (SELECT village_code FROM curated.v_cm_elevate) SELECT COUNT(*) FROM x")
check("inside a CTE", "FROM (SELECT DISTINCT ON (request_id)" in sql, sql)
sql, applied = dedupe_sql("SELECT 1 FROM curated.v_pmay p JOIN curated.v_cm_elevate c ON p.village_code = c.village_code")
check("JOIN target rewritten too", sql.count("DISTINCT ON") == 2 and len(applied) == 2, sql)
first, _ = dedupe_sql("SELECT COUNT(*) FROM curated.v_cm_elevate")
again, applied2 = dedupe_sql(first)
check("idempotent — a rewritten statement is not rewritten twice", again == first and applied2 == [], again)

print("4. UNTOUCHED VIEWS")
for v in ("curated.v_focus_plus", "curated.v_focus_legacy", "curated.v_employment",
          "curated.v_expenditure", "curated.dim_cm_elevate_scheme"):
    s = f"SELECT COUNT(*) FROM {v}"
    check(f"{v} unchanged", dedupe_sql(s) == (s, []))

print("5. NOTE")
check("note names the key", note_for(["application number"]) ==
      "_Duplicate records (same application number) are counted once._")
check("no note when nothing applied", note_for([]) == "")

if _fails:
    print(f"\nFAILED ({len(_fails)}): {', '.join(_fails)}")
    sys.exit(1)
print("\nALL DEDUP CHECKS PASSED")
