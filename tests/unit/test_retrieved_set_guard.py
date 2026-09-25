"""
Pipeline architecture doc §5.9/§5.11 ("tables must belong to the retrieved
set") — baseline-audit.md cross-cutting finding 11 flagged this as having
zero implementation, distinct from the join-graph relationship rule
sql_join_validator.py already enforces (that one asks "are these two tables
related"; this one asks "was this fact table actually retrieved for this
question at all"). Implemented as
app/schema_retrieval.find_tables_outside_retrieved_set(), scoped to fact
tables only (a dimension table can be legitimately joined in via the FK
graph without schema-retrieval ever naming it — see the function's
docstring for the concrete Focus Plus/dim_geography case that motivated the
scoping) and a true no-op whenever retrieval named no fact-table candidate
(the common case today for MGNREGA/PMAY-G, which have no schema-metadata
indexed yet). No DB, no model gateway — join_graph.build() only reads local
curated YAML.
Run: `python tests/unit/test_retrieved_set_guard.py`, exit code 0 = pass.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.sql import join_graph  # noqa: E402
from app.sql.schema_retrieval import find_tables_outside_retrieved_set  # noqa: E402

join_graph.build()

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_CM_ELEVATE_RETRIEVED = [
    {"granularity": "table", "ref": "curated.v_cm_elevate", "scheme_id": "CM Elevate"},
    {"granularity": "table", "ref": "curated.dim_cm_elevate_scheme", "scheme_id": "CM Elevate"},
    {"granularity": "column", "ref": "curated.v_cm_elevate.status", "scheme_id": "CM Elevate"},
]

_FOCUS_PLUS_RETRIEVED = [
    {"granularity": "table", "ref": "curated.v_focus_plus", "scheme_id": "Focus Plus"},
]


# ── 1. A no-op when retrieval named no fact-table candidate at all ─────────
print("1. NO-OP WHEN NOTHING TO CHECK AGAINST")

check("empty retrieved list is a true no-op",
      find_tables_outside_retrieved_set(
          "SELECT * FROM curated.fact_mgnrega_employment LIMIT 10", []) == [])

check("retrieved list with only column-granularity rows (no table candidate) is a no-op",
      find_tables_outside_retrieved_set(
          "SELECT * FROM curated.fact_mgnrega_employment LIMIT 10",
          [{"granularity": "column", "ref": "curated.v_cm_elevate.status"}]) == [])


# ── 2. The retrieved fact table itself is never flagged ────────────────────
print("2. THE RETRIEVED TABLE ITSELF PASSES")

check("a query using exactly the retrieved fact table has no violations",
      find_tables_outside_retrieved_set(
          "SELECT status, COUNT(*) FROM curated.v_cm_elevate GROUP BY status LIMIT 10",
          _CM_ELEVATE_RETRIEVED) == [])

check("case-insensitive match — differently-cased table name still matches the retrieved ref",
      find_tables_outside_retrieved_set(
          "SELECT status FROM CURATED.V_Cm_Elevate LIMIT 10", _CM_ELEVATE_RETRIEVED) == [])


# ── 3. A fact table NOT in the retrieved set is flagged ────────────────────
print("3. AN UNRETRIEVED FACT TABLE IS FLAGGED")

violations = find_tables_outside_retrieved_set(
    "SELECT village_code, SUM(person_days) FROM curated.fact_mgnrega_employment "
    "GROUP BY village_code LIMIT 10",
    _CM_ELEVATE_RETRIEVED)
check("a MGNREGA fact table referenced while only CM Elevate was retrieved is flagged",
      violations == ["curated.fact_mgnrega_employment"], detail=str(violations))


# ── 4. Dimension tables are exempt, even when not in the retrieved set ─────
print("4. DIMENSION TABLES ARE EXEMPT (THE FOCUS PLUS / DIM_GEOGRAPHY CASE)")

# Focus Plus's schema_metadata.yaml indexes only v_focus_plus and
# fact_focus_plus_disbursement — dim_geography is a legitimate join target
# per join_graph.py's FK data but was never indexed as a Focus Plus "table"
# candidate. A literal, unscoped membership check would wrongly flag this.
sql = ("SELECT g.lgd_district, SUM(f.amount) FROM curated.v_focus_plus f "
      "JOIN curated.dim_geography g ON f.village_code = g.village_code "
      "GROUP BY g.lgd_district LIMIT 10")
violations = find_tables_outside_retrieved_set(sql, _FOCUS_PLUS_RETRIEVED)
check("a dimension table (dim_geography) joined alongside the retrieved fact table is not flagged",
      violations == [], detail=str(violations))


# ── 5. Multiple stray fact tables are all reported, sorted ─────────────────
print("5. MULTIPLE VIOLATIONS")

sql = ("SELECT * FROM curated.fact_mgnrega_employment m "
      "JOIN curated.fact_pmay_house p ON m.village_code = p.village_code LIMIT 10")
violations = find_tables_outside_retrieved_set(sql, _CM_ELEVATE_RETRIEVED)
check("every unretrieved fact table referenced is reported, sorted",
      violations == ["curated.fact_mgnrega_employment", "curated.fact_pmay_house"],
      detail=str(violations))


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL RETRIEVED-SET GUARD (5.9/5.11) CHECKS PASSED")
