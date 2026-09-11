"""
Structured findings (app/findings.py, node 5.13) — pure-logic checks, no DB,
no model gateway. Same stance as test_security.py / test_defaults_engine.py:
`python tests/test_findings.py`, exit code 0 = all pass.

Covers tasks.md group 2's acceptance scenarios: (a) an empty result produces
the empty-result finding and nothing else; (b) a result with a clear max/min
produces an extremes finding matching pipeline.py's `_result_digest` text
exactly, both built from the one shared `compute_result_stats` call —
cross-checked, not re-derived; (c) a tie at the max produces a ties finding;
(d) a result over the large-result-set threshold produces that finding;
(e) a threshold-breach fires against a scheme with an authored thresholds
file; (f) a scheme with no thresholds file produces no threshold findings
and does not raise; (g) `findings` is always a list, never `None`.

Note on (e): no real `*_findings_thresholds.yaml` has been authored for CM
Elevate (or any scheme) yet — that needs SME-reviewed values this session
has no access to (see findings.py's module docstring and proposal.md's
Explicitly Out of Scope). This test exercises the mechanism against a
temporary, clearly-fictional thresholds file, not a claim of real business
thresholds.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import findings  # noqa: E402
from app.pipeline import _result_digest  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── (a) empty result -> empty-result finding, nothing else ─────────────────
print("1. EMPTY RESULT -> EMPTY-RESULT FINDING ONLY")

out_a = findings.evaluate("total expenditure", ["MGNREGA"], [], {})
check("exactly one finding", len(out_a) == 1, str(out_a))
check("it is type empty_result", bool(out_a) and out_a[0]["type"] == "empty_result", str(out_a))

# ── (b) extremes finding matches _result_digest's own numbers exactly ─────
print("2. EXTREMES FINDING MATCHES THE SHARED DIGEST EXACTLY")

rows_b = [
    {"district": "EAST KHASI HILLS", "expenditure": 500},
    {"district": "WEST GARO HILLS", "expenditure": 900},
    {"district": "RI BHOI", "expenditure": 100},
]
out_b = findings.evaluate("expenditure by district", ["MGNREGA"], rows_b, {})
extremes = [f for f in out_b if f["type"] == "extreme"]
check("an extremes finding is produced", len(extremes) == 1, str(out_b))
if extremes:
    check("max matches the known input (900)", extremes[0]["row_ref"].get("expenditure") == 900,
          str(extremes[0]))

digest_text, digest_nums = _result_digest(rows_b)
check("pipeline._result_digest reports the same max (900)", "max=900" in digest_text, digest_text)
check("pipeline._result_digest reports the same min (100)", "min=100" in digest_text, digest_text)
check("900 is in the numeric-faithfulness whitelist the digest derived", "900" in digest_nums, str(digest_nums))

stats_b = findings.compute_result_stats(rows_b)
check("compute_result_stats' own max equals the extremes finding's max",
      stats_b.numeric["expenditure"].max == extremes[0]["row_ref"]["expenditure"] if extremes else False)

# ── (c) a tie at the max produces a ties finding ────────────────────────────
print("3. A TIE AT THE MAX PRODUCES A TIES FINDING")

rows_c = [
    {"district": "EAST KHASI HILLS", "expenditure": 900},
    {"district": "WEST GARO HILLS", "expenditure": 900},
    {"district": "RI BHOI", "expenditure": 100},
]
out_c = findings.evaluate("expenditure by district", ["MGNREGA"], rows_c, {})
ties = [f for f in out_c if f["type"] == "tie"]
check("a tie finding is produced for the tied max", len(ties) == 1, str(out_c))
if ties:
    check("the tie message names both tied districts",
          "EAST KHASI HILLS" in ties[0]["message"] and "WEST GARO HILLS" in ties[0]["message"],
          ties[0]["message"])

rows_c_no_tie = [
    {"district": "EAST KHASI HILLS", "expenditure": 900},
    {"district": "WEST GARO HILLS", "expenditure": 500},
    {"district": "RI BHOI", "expenditure": 100},
]
out_c_no_tie = findings.evaluate("expenditure by district", ["MGNREGA"], rows_c_no_tie, {})
check("no tie finding when nothing is actually tied",
      not any(f["type"] == "tie" for f in out_c_no_tie), str(out_c_no_tie))

# ── (d) a result over the large-result-set threshold produces that finding ─
print("4. LARGE RESULT SET -> THAT FINDING (AND ONLY OVER THE THRESHOLD)")

from app.config import settings as _settings  # noqa: E402

big_rows = [{"village": f"V{i}", "count": i} for i in range(_settings.FINDINGS_LARGE_RESULT_ROWS + 1)]
out_d = findings.evaluate("villages", ["MGNREGA"], big_rows, {})
check("large_result_set finding present over the threshold",
      any(f["type"] == "large_result_set" for f in out_d), str([f["type"] for f in out_d]))

small_rows = [{"village": f"V{i}", "count": i} for i in range(5)]
out_d_small = findings.evaluate("villages", ["MGNREGA"], small_rows, {})
check("no large_result_set finding under the threshold",
      not any(f["type"] == "large_result_set" for f in out_d_small), str(out_d_small))

# ── (e) threshold breach fires against an authored (here: test-fixture) file ─
print("5. THRESHOLD BREACH FIRES AGAINST AN AUTHORED THRESHOLDS FILE")

_FAKE_SCHEME = "_TEST_SCHEME_WITH_THRESHOLDS"
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
    tf.write(
        "findings_thresholds:\n"
        "  - column: amount\n"
        "    operator: gt\n"
        "    value: 1000\n"
        "    severity: warning\n"
        "    message: \"amount {value} exceeds the test threshold of {threshold}\"\n"
    )
    thresholds_path = Path(tf.name)
findings._THRESHOLDS_FILE[_FAKE_SCHEME] = thresholds_path
try:
    rows_e = [{"district": "RI BHOI", "amount": 1500}]
    out_e = findings.evaluate("amount", [_FAKE_SCHEME], rows_e, {})
    breaches = [f for f in out_e if f["type"] == "threshold_breach"]
    check("a threshold_breach finding fires when the row crosses it",
          len(breaches) == 1, str(out_e))
    if breaches:
        check("the message is formatted with the actual value and threshold",
              breaches[0]["message"] == "amount 1500 exceeds the test threshold of 1000",
              breaches[0]["message"])

    rows_e_under = [{"district": "RI BHOI", "amount": 500}]
    out_e_under = findings.evaluate("amount", [_FAKE_SCHEME], rows_e_under, {})
    check("no threshold_breach finding when the row doesn't cross it",
          not any(f["type"] == "threshold_breach" for f in out_e_under), str(out_e_under))
finally:
    thresholds_path.unlink(missing_ok=True)

# ── (f) a scheme with no thresholds file -> no threshold findings, no raise ─
print("6. UN-PILOTED SCHEME (NO THRESHOLDS FILE) -> NO THRESHOLD FINDINGS, NO RAISE")

for scheme in ("MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"):
    try:
        out_f = findings.evaluate("amount", [scheme], [{"district": "RI BHOI", "amount": 999999}], {})
        check(f"{scheme}: no threshold_breach finding (no real thresholds file authored yet)",
              not any(f["type"] == "threshold_breach" for f in out_f), str(out_f))
    except Exception as e:  # noqa: BLE001
        check(f"{scheme}: evaluate() does not raise", False, f"raised {type(e).__name__}: {e}")

_FAKE_MALFORMED_THRESHOLDS = "_TEST_SCHEME_MALFORMED_THRESHOLDS"
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
    tf.write("findings_thresholds: [not: valid: yaml:")
    malformed_path = Path(tf.name)
findings._THRESHOLDS_FILE[_FAKE_MALFORMED_THRESHOLDS] = malformed_path
try:
    out_malformed = findings.evaluate("amount", [_FAKE_MALFORMED_THRESHOLDS],
                                      [{"district": "RI BHOI", "amount": 999999}], {})
    check("a malformed thresholds file degrades to no threshold findings, no raise",
          not any(f["type"] == "threshold_breach" for f in out_malformed), str(out_malformed))
except Exception as e:  # noqa: BLE001
    check("a malformed thresholds file degrades to no threshold findings, no raise",
          False, f"raised {type(e).__name__}: {e}")
finally:
    malformed_path.unlink(missing_ok=True)

# ── (g) findings is always a list, never None ───────────────────────────────
print("7. FINDINGS IS ALWAYS A LIST, NEVER NONE")

for rows_g, label in ((None, "None rows"), ([], "empty rows"),
                      ([{"a": 1}], "single row"), (rows_b, "multi row")):
    out_g = findings.evaluate("q", ["MGNREGA"], rows_g or [], {})
    check(f"evaluate() returns a list for {label}", isinstance(out_g, list), repr(out_g))

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL FINDINGS CHECKS PASSED")
