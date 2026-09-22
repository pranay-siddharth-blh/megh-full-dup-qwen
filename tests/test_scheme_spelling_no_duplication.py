"""
tests/test_scheme_spelling_no_duplication.py — `_correct_scheme_spelling` must
never duplicate a scheme name that the question already spells correctly.

The bug this file locks down: the lone word "Elevate" fuzzy-matches the
"cmelevate" alias on its own (fuzz.ratio("elevate", "cmelevate") ~= 87.5, over
the 80 accept threshold), so a correctly-spelled "CM Elevate" question had its
already-present "CM" duplicated — EVERY CM Elevate question, on every route,
became "total CM CM Elevate expenditure". A second pass (a resumed
clarification chip re-entering _run_pipeline) compounded it to "CM CM CM
Elevate".

The pre-LangGraph codebase guarded against exactly this by skipping word-level
correction for any scheme the question already names outright
(`_already_named`). The LangGraph rewrite kept only the trailing-duplicate
collapse ("Focus Plus plus" -> "Focus Plus"), which cannot cover this case:
the duplication here is LEADING, not trailing. Both are needed.

`python tests/test_scheme_spelling_no_duplication.py`, exit code 0 = all pass.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.update(
    ENV="prod",
    AUTH_ENABLED="true",
    JWT_SECRET="test-secret-at-least-32-characters-long",
    DATABASE_URL="postgresql://u:p@127.0.0.1:5/none",
)

from app.pipeline import _correct_scheme_spelling as correct  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


print("1. A CORRECTLY SPELLED scheme name is left exactly alone")
for q in (
    "total CM Elevate expenditure",
    "CM Elevate beneficiaries in Ri Bhoi",
    "how many CM Elevate units were sanctioned",
    "total Focus Plus expenditure",
    "total MGNREGA expenditure",
    "PMAY-G houses completed in West Garo Hills",
    "compare MGNREGA and CM Elevate spending",
):
    out = correct(q)
    check(f"unchanged: {q!r}", out == q, f"got {out!r}")

print("2. Case / separator variants of an already-named scheme are not duplicated")
for q in ("cm elevate total", "CM ELEVATE spending", "total CM-Elevate expenditure",
          "cmelevate beneficiaries"):
    out = correct(q)
    check(f"no 'CM CM' duplication: {q!r}", "cm cm" not in out.lower(), f"got {out!r}")

print("3. IDEMPOTENT — a second pass (resumed clarification chip re-entering "
      "_run_pipeline) must not compound the text")
for q in ("total CM Elevate expenditure", "total Focus Plus expenditure",
          "cm elevate in South Garo Hills"):
    once = correct(q)
    twice = correct(once)
    check(f"stable under a second pass: {q!r}", once == twice, f"{once!r} -> {twice!r}")

print("4. STILL CORRECTS a genuine misspelling (the function's actual purpose)")
for typo, must_contain in (
    ("total manrega expenditure", "MGNREGA"),
    ("total facus plus expenditure", "Focus Plus"),
):
    out = correct(typo)
    check(f"{typo!r} -> contains {must_contain!r}", must_contain in out, f"got {out!r}")

# "mnrega"/"nrega" are EXACT entries in _SCHEME_FUZZY_ALIASES["MGNREGA"], so
# the `wl in aliases` short-circuit returns them untouched — by design ("a word
# only gets corrected when it does NOT already exactly match a scheme alias").
# _SCHEME_NAME_PATTERN also matches them outright, so routing sees MGNREGA
# either way; only the literal text is left as the user typed it.
check("a recognised short alias is deliberately left as typed",
      correct("mnrega person days") == "mnrega person days",
      correct("mnrega person days"))

print("5. The trailing-duplicate collapse still works (regression guard for the "
      "fix this codebase already had)")
out = correct("total facus plus expenditure")
check("'facus plus' does not become 'Focus Plus plus'",
      "plus plus" not in out.lower(), f"got {out!r}")

print("6. Unrelated words are not mangled")
for q in ("total expenditure last year", "which blocks have the highest wages",
          "sanctioned houses in Ri Bhoi"):
    out = correct(q)
    check(f"unchanged: {q!r}", out == q, f"got {out!r}")

# KNOWN PRE-EXISTING FALSE POSITIVE, deliberately NOT asserted as fixed here:
# fuzz.ratio("elevated", "cmelevate") == 82.35, over the 80 accept threshold, so
# a scheme-free sentence containing "elevated" ("elevated road construction")
# is rewritten to "CM Elevate road construction". The `_already_named` guard
# restored above cannot help — no scheme is named in that sentence at all.
# This behaves identically in the pre-LangGraph codebase, so it is NOT a
# regression from the rewrite and is out of scope for this change; raising
# _FUZZY_SCHEME_ACCEPT or requiring a scheme-ish neighbour word would be a
# separate, independently-reviewed change. Asserted as-is so the behavior is
# recorded rather than silently discovered again later.
check("KNOWN ISSUE recorded (not a regression): 'elevated' still trips the "
      "fuzzy scheme matcher in a scheme-free sentence",
      correct("elevated road construction") == "CM Elevate road construction",
      correct("elevated road construction"))

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + "; ".join(_fails))
    sys.exit(1)
print("ALL SCHEME-SPELLING CHECKS PASSED")
