"""
Pipeline architecture doc §5.3 ("Generic clarification gate"). The old
hardcoded _needs_{scheme,topn,scope}_clarification regex predicates were
replaced by the QueryFrame rules (app/nlu/clarify_rules.py, covered in
depth by tests/unit/test_clarify_rules.py). This file covers the same
questions those predicates were tested on, through the no-model path: the
deterministic understand.fallback_frame + the frame rules — plus the
column-not-held texts _admin_expenditure_clarification and
_women_share_clarification. No DB, no model gateway.
Run: `python tests/unit/test_clarification_gate.py`, exit code 0 = pass.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.nlu import clarify_rules, understand  # noqa: E402
from app.orchestration import pipeline  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def _asks(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except pipeline.ClarificationNeeded as e:
        return e.rule
    return None


def _after(question, resolved):
    frame = understand.fallback_frame(question)
    return _asks(clarify_rules.after_resolution, frame, question,
                 frame.resolved_schemes or ["MGNREGA"], resolved)


# ── 1. scheme (rule 1) ──────────────────────────────────────────────────────
print("1. SCHEME")

fb = understand.fallback_frame
check("a question naming no scheme and no scheme-pinning vocabulary pins none -> rule 1 asks",
      fb("how many beneficiaries were there last year?").resolved_schemes == []
      and _asks(clarify_rules.before_resolution, fb("how many beneficiaries were there last year?"),
                "how many beneficiaries were there last year?") == "scheme-not-specified")
check("a question naming a scheme outright pins it",
      fb("how many person-days under MGNREGA?").resolved_schemes == ["MGNREGA"])
check("an explicit cross-scheme phrase pins every scheme",
      len(fb("give me numbers across both schemes").resolved_schemes) >= 2)
check("vocabulary that pins exactly one scheme pins it",
      fb("what is the total sanctioned amount for houses?").resolved_schemes == ["PMAY-G"],
      str(fb("what is the total sanctioned amount for houses?").resolved_schemes))


# ── 2. top-N (rule 2) — only what the frame states ─────────────────────────
print("2. TOP-N")

F = understand.QueryFrame
rank = F(schemes=["MGNREGA"], resolved_schemes=["MGNREGA"], metric="expenditure",
         query_type="ranking", group_by="district")
out = None
rule = None
try:
    out = clarify_rules.before_resolution(rank, "top districts by expenditure")
except pipeline.ClarificationNeeded as e:
    rule = e.rule
check("a ranking over a dimension with no count is handled by the top-N rule (asked or defaulted)",
      rule == "ranking-count-not-specified" or any(t.startswith("top_n:default") for t in out.fired),
      str(rule or out.fired))
out = clarify_rules.before_resolution(rank.model_copy(update={"top_n": 5}), "top 5 districts by expenditure")
check("an explicit count needs nothing", not any(t.startswith("top_n") for t in out.fired), str(out.fired))
out = clarify_rules.before_resolution(rank.model_copy(update={"query_type": "list", "metric": "expenditure"}),
                                      "list all districts by expenditure")
check("'all districts' (a list) needs nothing", not any(t.startswith("top_n") for t in out.fired))
out = clarify_rules.before_resolution(fb("which district spent the most under MGNREGA?"),
                                      "which district spent the most under MGNREGA?")
check("a fallback frame never guesses a ranking count", not any(t.startswith("top_n") for t in out.fired))


# ── 3. area (rule 3) ────────────────────────────────────────────────────────
print("3. AREA")

check("a resolved district satisfies the area, nothing asked",
      _after("how many person-days were generated in 2023-24?",
             {"district": "EAST GARO HILLS", "year_key": 2023}) is None)
try:
    _fired = clarify_rules.after_resolution(fb("total person-days in 2023-24"), "total person-days in 2023-24",
                                            ["MGNREGA"], {"year_key": 2023}).fired
except pipeline.ClarificationNeeded as e:
    _fired = [e.rule]
check("no area named -> the disclosed statewide default, or the area question when there is none",
      "area:default:statewide" in _fired or "scope-not-specified" in _fired, str(_fired))
check("a breakdown request ('by district') is already scoped",
      fb("person-days by district").group_by == "breakdown"
      and _after("person-days by district in 2023-24", {"year_key": 2023}) is None)
check("an all-years ask is read as stated",
      bool(fb("total MGNREGA expenditure across all years").year_text))


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
