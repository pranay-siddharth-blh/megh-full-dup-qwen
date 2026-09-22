"""
Pipeline architecture doc §5.3 ("Generic clarification gate") — per
docs/baseline-audit.md this is NOT a YAML rule engine as originally proposed;
it's a set of bespoke, hardcoded predicate functions in app/pipeline.py, each
with baked-in question text. This file covers the pure-logic predicates:
_needs_scheme_clarification, _needs_topn_clarification,
_needs_scope_clarification, _admin_expenditure_clarification, and
_women_share_clarification. No DB, no model gateway — every one of these
runs on question text (+ a resolved-entities dict) alone.
Run: `python tests/test_clarification_gate.py`, exit code 0 = pass.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import pipeline  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── 1. _needs_scheme_clarification ──────────────────────────────────────────
print("1. NEEDS_SCHEME_CLARIFICATION")

check("a question naming no scheme and no scheme-pinning vocabulary needs clarification",
      pipeline._needs_scheme_clarification("how many beneficiaries were there last year?"))
check("a question naming a scheme outright needs no clarification",
      not pipeline._needs_scheme_clarification("how many person-days under MGNREGA?"))
check("an explicit cross-scheme phrase needs no clarification",
      not pipeline._needs_scheme_clarification("give me numbers across both schemes"))
check("vocabulary that pins exactly one scheme needs no clarification",
      not pipeline._needs_scheme_clarification("what is the total sanctioned amount for houses?"))


# ── 2. _needs_topn_clarification ────────────────────────────────────────────
print("2. NEEDS_TOPN_CLARIFICATION")

check("a ranking question over a dimension with no count needs clarification",
      pipeline._needs_topn_clarification("top districts by expenditure"))
check("an explicit count in the ranking question needs no clarification",
      not pipeline._needs_topn_clarification("top 5 districts by expenditure"))
check("'all districts' explicitly wants the whole list, needs no clarification",
      not pipeline._needs_topn_clarification("list all districts by expenditure"))
check("a singular-dimension ranking ('which district...') already means one row",
      not pipeline._needs_topn_clarification("which district spent the most?"))
check("no ranking cue at all needs no clarification",
      not pipeline._needs_topn_clarification("how many houses were completed?"))


# ── 3. _needs_scope_clarification ───────────────────────────────────────────
print("3. NEEDS_SCOPE_CLARIFICATION")

_EMPTY = {}
check("an aggregate question with no place/year named and none resolved needs clarification",
      pipeline._needs_scope_clarification("how many person-days were generated?", _EMPTY))
check("a resolved district satisfies the scope, no clarification needed",
      not pipeline._needs_scope_clarification("how many person-days were generated?",
                                              {"district": "EAST GARO HILLS"}))
check("a resolved year alone also satisfies the scope",
      not pipeline._needs_scope_clarification("how many person-days were generated?",
                                              {"year_key": 2023}))
check("an explicit statewide phrase needs no clarification",
      not pipeline._needs_scope_clarification("total person-days across all of Meghalaya", _EMPTY))
check("a breakdown request ('by district') is already scoped, needs no clarification",
      not pipeline._needs_scope_clarification("person-days by district", _EMPTY))
check("a cross-scheme geography-overlap question is inherently statewide",
      not pipeline._needs_scope_clarification("how many districts are common to both schemes?", _EMPTY))
check("a bare metric noun with no quantity word still needs a scope",
      pipeline._needs_scope_clarification("show MGNREGA expenditure", _EMPTY))


# ── 4. _admin_expenditure_clarification — scheme-specific vs. generic text ──
print("4. ADMIN_EXPENDITURE_CLARIFICATION")

c = pipeline._admin_expenditure_clarification("what was the admin expenditure for MGNREGA?")
check("a single named scheme with 'not held' text gets the scheme-specific message",
      "MGNREGA" in c.question, detail=c.question)

c = pipeline._admin_expenditure_clarification("what was the admin expenditure overall?")
check("no single pinned scheme gets the generic message",
      c.question == pipeline._ADMIN_EXPENDITURE_GENERIC_TEXT, detail=c.question)


# ── 5. _women_share_clarification / _WOMEN_SHARE_REQUESTED gating ──────────
print("5. WOMEN_SHARE_CLARIFICATION")

check("'% women employment' trips the not-computable share regex",
      bool(pipeline._WOMEN_SHARE_REQUESTED.search("what percentage of workers employed were women?")))
check("a plain women-employment count question does not trip the share regex",
      not bool(pipeline._WOMEN_SHARE_REQUESTED.search("how many women were provided employment?")))
c = pipeline._women_share_clarification("what % of MGNREGA workers were women?")
check("the clarification text explains why a ratio can't be published",
      c.question == pipeline._WOMEN_SHARE_NOT_COMPUTABLE_TEXT, detail=c.question)


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL CLARIFICATION GATE (5.3) CHECKS PASSED")
