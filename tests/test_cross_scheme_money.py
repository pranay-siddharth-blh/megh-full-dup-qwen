"""
"Which scheme paid out the most?" — a superlative asked ACROSS schemes must be
ANSWERED (the scheme is the answer), never turned into a "which scheme does
your question concern?" pause.

Regression for the 2026-09-17 report: "what about the scheme with highest money
paid?" raised the four-way scheme-clarification chips. That pause exists for a
question that forgot to name a scheme it needs as a FILTER — but here the
scheme is the thing being asked for, so asking the user to supply it hands back
the very answer they came for.

_EXPLICIT_BOTH already exempts the phrasings that ask for every scheme ("both
schemes", "by scheme", "scheme-wise"); this shape carries its cross-scheme
intent through "which scheme" + a ranking word instead, which nothing matched.

Pure-Python assertions (SQL read through SQLGlot) — no model or DB. Plain script (no pytest
in the venv): `python tests/test_cross_scheme_money.py`, exit code 0 = all pass.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402
from app import sql_ast  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── 1. The reported question ───────────────────────────────────────────────
print("1. REPORTED QUESTION")
REPORTED = "what about the scheme with highest money paid?"
check("it is recognised as a cross-scheme money ranking",
      p._wants_cross_scheme_money_ranking(REPORTED))
check("  and no longer raises the 'which scheme?' pause",
      not p._needs_scheme_clarification(REPORTED))

# ── 2. Other phrasings of the same question ────────────────────────────────
print("2. OTHER PHRASINGS")
for q in ("which scheme has the highest expenditure?",
          "which scheme spent the most?",
          "what scheme paid out the most money",
          "which scheme has the lowest spend",
          "rank the schemes by amount spent",
          "the scheme with the largest disbursement"):
    check(f"{q[:46]!r} -> ranking", p._wants_cross_scheme_money_ranking(q))
    check("  and no scheme pause", not p._needs_scheme_clarification(q))

# ── 3. Superlatives that are NOT about money stay on the normal path ───────
# "which scheme has the most applications" is a different figure (CM Elevate
# application counts), answered by ordinary SQL generation — the deterministic
# money ranking must not intercept it.
print("3. NON-MONEY SUPERLATIVES ARE LEFT ALONE")
for q in ("which scheme has the most applications?",
          "which scheme has the most beneficiaries?",
          "which scheme covers the most villages?"):
    check(f"{q[:46]!r} -> not the money ranking",
          not p._wants_cross_scheme_money_ranking(q))

# ── 4. Ordinary questions are untouched ────────────────────────────────────
print("4. ORDINARY QUESTIONS UNTOUCHED")
for q in ("total MGNREGA expenditure in West Garo Hills",
          "how many houses completed by district",
          "PMAY-G houses sanctioned in 2023-24",
          "compare MGNREGA and PMAY-G spending",
          "which district spent the most?"):
    check(f"{q[:46]!r} -> not the money ranking",
          not p._wants_cross_scheme_money_ranking(q))

# A question that names its own scheme never needed the pause anyway.
check("a scheme-named question still skips the pause",
      not p._needs_scheme_clarification("total MGNREGA expenditure in West Garo Hills"))

# ── 5. Answered as a cross-scheme question over every scheme with money ────
# Since D-062 (2026-10-22) the ranking is one model-written query per scheme and
# a composed answer, no longer the fixed _CROSS_SCHEME_MONEY_SQL. CM Elevate
# records no money (v_cm_elevate: applications only): it is never queried for an
# amount and the answer says so, rather than a misleading zero.
print("5. EVERY SCHEME WITH MONEY, CM ELEVATE SAID PLAINLY")
from app import cross_scheme  # noqa: E402
for q in ("which scheme spent the most money?", "rank the schemes by amount spent"):
    gaps = p._cross_scheme_gaps(cross_scheme.ORDER, {}, {}, q)
    check(f"{q[:46]!r} -> CM Elevate not queried for money", "CM Elevate" in gaps, gaps)
    # 2026-11-14: every scheme that records no money (CM Elevate, and Homestay since it was onboarded), not
    # a hard-coded one; the same set the cross-scheme answer derives (cross_figures.NO_MONEY)
    from app import cross_figures  # noqa: E402
    check("  and every other scheme is", set(gaps) == set(cross_figures.NO_MONEY), gaps)
check("a money AND count question still asks CM Elevate for its applications",
      "CM Elevate" not in p._cross_scheme_gaps(
          cross_scheme.ORDER, {}, {}, "compare MGNREGA spending and CM Elevate applications"))
check("the template SQL is gone", not hasattr(p, "_CROSS_SCHEME_MONEY_SQL"))

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL CROSS-SCHEME MONEY CHECKS PASSED")
