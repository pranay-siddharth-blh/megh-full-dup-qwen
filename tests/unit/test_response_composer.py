"""
Pipeline architecture doc §5.15 ("Response composer") — the numeric-
faithfulness guard, a strength beyond what the proposal specifies (see
docs/baseline-audit.md row 5.15): app/orchestration/pipeline.py's _data_numbers() (collect
every numeric value the query actually returned) and
_answer_numbers_faithful() (every number the composed answer states must
trace back to one of those values, a small tolerance, or be a year/small
prose integer). Pure logic, no DB, no model gateway.
Run: `python tests/unit/test_response_composer.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.orchestration import pipeline  # noqa: E402
from app.clients import llm  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── 1. _data_numbers — every numeric leaf, normalised ───────────────────────
print("1. _DATA_NUMBERS")

nums = pipeline._data_numbers([{"district": "East Garo Hills", "total_expenditure": 15234, "year_key": 2023}])
check("an integer cell is collected as a plain digit string",
      "15234" in nums, detail=str(nums))
check("a non-numeric cell (district name) is not collected",
      "East Garo Hills" not in nums, detail=str(nums))

nums = pipeline._data_numbers([{"avg_wage": 254.5}])
check("a float cell is collected in general-format form",
      "254.5" in nums, detail=str(nums))


# ── 2. _answer_numbers_faithful — every reported number must trace to data ──
print("2. _ANSWER_NUMBERS_FAITHFUL")

data_nums = {"15234"}
check("a number that exactly matches a data value is faithful",
      pipeline._answer_numbers_faithful(
          "East Garo Hills reported a total expenditure of 15234 lakh rupees.", data_nums))

check("a fabricated number with no match in the data is caught",
      not pipeline._answer_numbers_faithful(
          "East Garo Hills reported a total expenditure of 99999 lakh rupees.", data_nums))

check("a year mentioned in prose is not treated as a data claim",
      pipeline._answer_numbers_faithful("In FY 2023-24, the total was 15234.", data_nums))

check("a small integer used as ordinary prose (not data) is not flagged",
      pipeline._answer_numbers_faithful("There are 2 schemes covering this district.", data_nums))

check("a comma-formatted version of the same data number is still recognised",
      pipeline._answer_numbers_faithful("The total expenditure was 15,234 lakh rupees.", data_nums))

check("a number within the small rounding tolerance of a data value is accepted",
      pipeline._answer_numbers_faithful("The total expenditure was approximately 15234.4 lakh rupees.",
                                        data_nums))


# ── 3. findings woven into compose_response's own prose (2026-09-18) ────────
# openspec/changes/multi-tenant-rls-scheme-scaleout — node 5.13 findings now
# feed compose_response as an actual input (GT proposal §5.15), not just a
# sibling response field. Real end-to-end checks: mock only the LLM call
# itself (llm.call_response_composer), so the real prompt-building and the
# real numeric-faithfulness guard both run for real.
print("3. FINDINGS WOVEN INTO compose_response's OWN PROSE")

_orig_composer = llm.call_response_composer
_captured_prompt: list[str] = []


async def _echo_composer(prompt: str) -> str:
    _captured_prompt.clear()
    _captured_prompt.append(prompt)
    return "placeholder"


async def _run_compose(rows, result_findings, answer_fn):
    llm.call_response_composer = answer_fn
    try:
        return await pipeline.compose_response(
            "how many workers", "SELECT 1", rows, schemes=["MGNREGA"],
            result_findings=result_findings)
    finally:
        llm.call_response_composer = _orig_composer


_rows = [{"district": "East Garo Hills", "amount": 15234}]
_large_result_finding = [{"type": "large_result_set", "severity": "info", "message":
                          "This result has 847 rows, above the 100-row threshold for a single answer."}]

# 3a. no findings -> no findings_block in the prompt at all.
asyncio.run(_run_compose(_rows, [], _echo_composer))
check("no findings -> prompt carries no findings block",
      "Additional observations" not in _captured_prompt[0])

# 3b. findings present -> block appears, with the "at most one" cap instruction.
asyncio.run(_run_compose(_rows, _large_result_finding, _echo_composer))
check("a finding's message appears in the prompt",
      "This result has 847 rows" in _captured_prompt[0], _captured_prompt[0])
check("the composer is instructed to use at most one finding, not force one in",
      "AT MOST ONE" in _captured_prompt[0] and "never force one in" in _captured_prompt[0])
check("findings sit in their own block, not folded into the premise-correction notes block",
      "Additional observations about this result" in _captured_prompt[0])

# 3c. the actual fix: a finding-only number (847, a row COUNT — not a data
# cell value in _rows) must pass the faithfulness guard when the composer
# echoes it, not trigger the deterministic fallback.
async def _answer_with_finding_number(prompt: str) -> str:
    return "This includes 847 records for East Garo Hills."


result = asyncio.run(_run_compose(_rows, _large_result_finding, _answer_with_finding_number))
check("a finding-derived number (847, not a data cell) survives the faithfulness "
      "check instead of triggering the deterministic fallback",
      result == "This includes 847 records for East Garo Hills.", result)

# 3d. control: a genuinely fabricated number (not in data, not in any
# finding) must still correctly fail and fall back — the fix above must not
# have quietly widened the guard to accept anything.
async def _answer_with_fabricated_number(prompt: str) -> str:
    return "This includes 999999 records for East Garo Hills."


result = asyncio.run(_run_compose(_rows, _large_result_finding, _answer_with_fabricated_number))
check("a genuinely fabricated number (not data, not a finding) still triggers "
      "the deterministic fallback, not silently accepted",
      result != "This includes 999999 records for East Garo Hills.", result)


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL RESPONSE COMPOSER NUMERIC-FAITHFULNESS (5.15) CHECKS PASSED")
