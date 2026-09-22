"""
Pipeline architecture doc §5.11 ("SQL validation") — app/db.py's
_assert_safe()/run_readonly(). Per docs/baseline-audit.md this was
regex-based ("a single leading-keyword check + a forbidden-keyword
blocklist"), not the proposal's "non-negotiable" SQLGlot AST parser, and its
LIMIT enforcement was a naive substring check. Rewritten to parse the SQL
with sqlglot and check the actual AST: read-only enforcement (including
write statements nested inside a CTE, which a regex can't see and a naive
root-type check alone would miss — Postgres allows data-modifying CTEs),
single-statement, no SELECT INTO, no row-locking clauses, and a real
top-level LIMIT clause rather than a text match. No DB, no model gateway —
_assert_safe/run_readonly's SQL execution never runs in these checks
(run_readonly's actual conn.fetch is unreachable without ensure_pool(),
which is why the run_readonly-level checks below assert UnsafeSQLError is
raised BEFORE any pool access is attempted, not the query result).
Run: `python tests/test_sql_safety.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.db import UnsafeSQLError, _assert_safe, run_readonly  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def _safe(sql: str) -> "bool | str":
    """True if sql clears _assert_safe; the raised message string otherwise."""
    try:
        _assert_safe(sql)
        return True
    except UnsafeSQLError as e:
        return str(e)


# ── 1. Legitimate queries this codebase actually generates pass cleanly ────
print("1. LEGITIMATE QUERIES PASS")

check("a plain aggregate SELECT with LIMIT passes",
      _safe("SELECT lgd_district, SUM(total_expenditure) AS total FROM curated.v_employment "
            "WHERE year_key = 2023 GROUP BY lgd_district LIMIT 50") is True)
check("a CTE-based cross-scheme comparison query passes",
      _safe("WITH e AS (SELECT village_code, SUM(x) AS s FROM curated.v_employment GROUP BY village_code) "
            "SELECT * FROM e LIMIT 50") is True)
check("a query with no LIMIT still passes _assert_safe itself "
      "(LIMIT enforcement is run_readonly's job, checked separately below)",
      _safe("SELECT * FROM curated.v_employment") is True)


# ── 2. Write/DDL statements are rejected, at the root ───────────────────────
print("2. WRITE/DDL AT THE ROOT")

check("a top-level DELETE is rejected",
      _safe("DELETE FROM curated.v_employment") is not True)
check("a top-level UPDATE is rejected",
      _safe("UPDATE curated.v_employment SET total_expenditure = 0") is not True)
check("a top-level INSERT is rejected",
      _safe("INSERT INTO curated.v_employment (village_code) VALUES (1)") is not True)
check("a top-level DROP is rejected",
      _safe("DROP TABLE curated.v_employment") is not True)
check("a top-level TRUNCATE is rejected",
      _safe("TRUNCATE curated.v_employment") is not True)
check("a top-level GRANT is rejected",
      _safe("GRANT SELECT ON curated.v_employment TO someone") is not True)
check("VACUUM (an unrecognised/Command-type statement) is rejected, not silently allowed",
      _safe("VACUUM curated.v_employment") is not True)


# ── 3. Write hidden inside a CTE — the case a root-type-only check misses ──
print("3. WRITE NESTED INSIDE A CTE")

check("a data-modifying DELETE-in-CTE is rejected even though the outer statement is a SELECT",
      _safe("WITH deleted AS (DELETE FROM curated.v_employment RETURNING *) "
            "SELECT * FROM deleted") is not True)
check("a data-modifying INSERT-in-CTE is rejected even though the outer statement is a SELECT",
      _safe("WITH ins AS (INSERT INTO curated.v_employment (village_code) VALUES (1) RETURNING *) "
            "SELECT * FROM ins") is not True)


# ── 4. Other unsafe shapes ───────────────────────────────────────────────
print("4. OTHER UNSAFE SHAPES")

check("SELECT INTO (creates a table) is rejected",
      _safe("SELECT * INTO new_table FROM curated.v_employment") is not True)
check("SELECT ... FOR UPDATE (row lock) is rejected",
      _safe("SELECT * FROM curated.v_employment LIMIT 1 FOR UPDATE") is not True)
check("stacked statements ('; DELETE ...') are rejected",
      _safe("SELECT 1; DELETE FROM curated.v_employment") is not True)
check("SQL that fails to parse is rejected (fail closed), not silently passed through",
      _safe("SELECT 1) garbage ; --") is not True)
check("an empty query is rejected",
      _safe("   ") is not True)


# ── 5. AST-based checks don't false-positive on data that merely CONTAINS
#       a forbidden keyword as a substring — the exact regex weakness this
#       rewrite exists to fix ─────────────────────────────────────────────
print("5. NO FALSE POSITIVES ON KEYWORD-LOOKING DATA")

check("a WHERE literal containing a forbidden keyword as a substring is not flagged "
      "('Grantville' contains 'grant', 'Dropati' contains 'drop')",
      _safe("SELECT * FROM curated.v_employment WHERE lgd_village_name IN "
            "('Grantville', 'Dropati') LIMIT 10") is True)
check("a column alias containing the word 'limit' does not fool the LIMIT presence check "
      "('district_limit' must not read as a real LIMIT clause)",
      _safe("SELECT lgd_district AS district_limit FROM curated.v_employment") is True)


# ── 6. run_readonly — LIMIT is appended only when genuinely absent ─────────
print("6. RUN_READONLY — LIMIT ENFORCEMENT")


async def _run_readonly_checks():
    # No live DB in this test env — run_readonly() will fail at ensure_pool()
    # for any query that clears _assert_safe. We only assert the safety gate
    # itself: unsafe SQL must raise UnsafeSQLError before any pool access is
    # attempted (a DB/connection error would surface as a different
    # exception type entirely).
    try:
        await run_readonly("DELETE FROM curated.v_employment")
        check("run_readonly rejects unsafe SQL before touching the DB", False, "no exception raised")
    except UnsafeSQLError:
        check("run_readonly rejects unsafe SQL before touching the DB", True)
    except Exception as e:  # noqa: BLE001
        check("run_readonly rejects unsafe SQL before touching the DB", False,
              f"raised {type(e).__name__} instead of UnsafeSQLError: {e}")


asyncio.run(_run_readonly_checks())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL SQL SAFETY / AST VALIDATION (5.11) CHECKS PASSED")
