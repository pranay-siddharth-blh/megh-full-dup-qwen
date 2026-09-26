"""
Answer presentation layer (app/response/answer_format.py) — pure-logic checks, no DB,
no model gateway: `python tests/unit/test_answer_format.py`, exit code 0 = all pass.

Covers: Indian digit grouping; rupee / crore / lakh / percent formatting keyed
on the column name; identifiers left exactly as stored; Title-Casing of
UPPERCASE place literals (in cells and in prose); the multi-row table and the
single-row bullet list; and that formatting never drops a row value.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")

from app.response import answer_format as af  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


print("1. CELL FORMATTING")
check("count uses Indian grouping", af.cell("beneficiaries", 105702) == "1,05,702", af.cell("beneficiaries", 105702))
check("rupee column >= 1 crore shown in Cr", af.cell("amount_raw", Decimal("1197392500.00")) == "₹119.74 Cr",
      af.cell("amount_raw", Decimal("1197392500.00")))
check("rupee column >= 1 lakh shown in L", af.cell("amount_disbursed", 278000) == "₹2.78 L",
      af.cell("amount_disbursed", 278000))
check("crore-named column keeps its value, adds ₹ Cr",
      af.cell("total_expenditure_crore", Decimal("3628.67")) == "₹3,628.67 Cr")
check("percent column gets %", af.cell("female_pct", 61.43) == "61.4%", af.cell("female_pct", 61.43))
check("year_key left raw", af.cell("year_key", 2025) == "2025")
check("id left exactly as stored", af.cell("pg_id", "PG-FOCUS-EKH-2245") == "PG-FOCUS-EKH-2245")
check("MGNREGA *_exp (lakh, unit not in name) only digit-grouped",
      af.cell("total_exp", Decimal("88.92")) == "88.92")
check("UPPERCASE place literal Title-Cased", af.cell("lgd_district", "WEST GARO HILLS") == "West Garo Hills")
check("mixed-case name untouched",
      af.cell("scheme_name", "PRIME Small Enterprise Empowerment and Development (SEED)")
      == "PRIME Small Enterprise Empowerment and Development (SEED)")
check("NULL shown as a dash", af.cell("lgd_block", None) == "—")
check("numeric text formatted like a number", af.cell("amount_raw", "71277500.00") == "₹7.13 Cr")

print("2. HEADERS")
check("lgd_ prefix dropped", af.header("lgd_district") == "District", af.header("lgd_district"))
check("storage suffixes dropped", af.header("financial_year_short") == "Financial year",
      af.header("financial_year_short"))
check("amount_raw -> Amount", af.header("amount_raw") == "Amount", af.header("amount_raw"))

print("3. LAYOUT")
# The pipeline registers every district/block name before formatting.
af.register_places(["West Garo Hills", "Ri Bhoi", "East Khasi Hills"])
rows = [{"lgd_district": "WEST GARO HILLS", "applications": 1708},
        {"lgd_district": "RI BHOI", "applications": 2592}]
out = af.present("There are **4,300** applications.", rows)
check("multi-row result gets a readable bulleted breakdown, not a table",
      "- **West Garo Hills** — 1,708 applications" in out and "|" not in out, out)
check("every row value survives formatting", "1,708" in out and "2,592" in out and "Ri Bhoi" in out, out)
_with_own_table = af.present("Top: **5**.\n\n| a | b |\n| --- | --- |\n| x | 1 |", rows)
check("composer's own table is dropped so the breakdown is not shown twice",
      _with_own_table.count("- **Ri Bhoi**") == 1 and "| a | b |" not in _with_own_table,
      _with_own_table)
many = [{"block": f"B{i}", "n": i} for i in range(20)]
check("long result capped with a row count note",
      "_…and 8 more._" in af.present("x", many))
money = af.present("x", [{"tranche_label": "Tranch 1", "amount_raw": 466430000, "payments": 93286},
                         {"tranche_label": "Tranch 2", "amount_raw": 233215000, "payments": 93286}])
check("money and counts read naturally in a row", "- **Tranch 1** — ₹46.64 Cr · 93,286 payments" in money, money)
one = af.present("Sakania PG has **12** members.",
                 [{"pg_name": "Sakania Pg", "lgd_district": "EAST KHASI HILLS", "members": 12}])
check("single multi-field row becomes labelled bullets",
      "- **District:** East Khasi Hills" in one and "- **Members:** 12" in one, one)
check("single-value row stays a sentence",
      af.present("**8,627** applications.", [{"applications": 8627}]) == "**8,627** applications.")

print("4. PROSE")
af.register_places(["West Garo Hills", "Tikrikilla"])
check("UPPERCASE places in prose Title-Cased",
      af.polish_prose("TIKRIKILLA leads WEST GARO HILLS") == "Tikrikilla leads West Garo Hills",
      af.polish_prose("TIKRIKILLA leads WEST GARO HILLS"))
check("table cell pipes cannot break the table", "|" not in af.cell("scheme_name", "A|B"))

if _fails:
    print(f"\nFAILED ({len(_fails)}): {', '.join(_fails)}")
    sys.exit(1)
print("\nALL ANSWER-FORMAT CHECKS PASSED")
