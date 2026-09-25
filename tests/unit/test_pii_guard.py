"""
Urgent PII redaction (app/core/pii_guard.py, openspec/changes/urgent-pii-redaction)
— pure-logic + monkeypatched-dependency checks, no DB, no model gateway. Run:
`python tests/unit/test_pii_guard.py`, exit code 0 = all pass.

Covers tasks.md groups 1 and 2's acceptance scenarios:
  Layer 1 (pre-execution SQL-text blocklist, wired into
  app/orchestration/pipeline.py::execute_with_repair immediately before run_readonly):
    (a) a bare blocklisted column is rejected
    (b) an aliased blocklisted column is still rejected (the alias-evasion
        gap Layer 1 exists to close) — including CM Elevate's
        scheme_specific ->> 'key' JSONB form
    (c) a non-blocklisted column with a similar name is not falsely rejected
        (word-boundary case)
    (d) MGNREGA / PMAY-G (empty blocklist) are never rejected by this check
    (e) the rejection response text never contains the blocklisted column
        name — only the log does (log vs. response separation)
  Layer 2 (post-execution row redaction, app/pii_guard.redact_rows):
    (a) a blocklisted key is fully removed, not nulled
    (b) non-blocklisted keys in the same row are untouched
    (c) a row with no blocklisted keys passes through unchanged
    (d) an integration-style check that execute_with_repair's returned
        `rows` — confirmed in tasks.md 0.2 to be the exact object
        _answer_data returns and conversation_store.persist_turn reads —
        never contains a blocklisted key, even when Layer 1's SQL-text scan
        can't see it (a `SELECT *` that doesn't name the column literally).
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.core import pii_guard  # noqa: E402
from app.orchestration import pipeline

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


class _FakeLogger:
    def __init__(self):
        self.warnings: list[str] = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def info(self, *a, **kw):
        pass


_ENTITY_RESULT = {"resolved": {}, "notes": [], "display": {}}
_FAKE_ROWS = [{"amount_disbursed": 5000, "financial_year": "2023-24"}]


async def _run():
    async def _fake_verify_sql(*_a, **_kw):
        return None  # no semantic-verifier issue — reach the PII check every time

    async def _fake_run_readonly_plain(sql):
        return [dict(r) for r in _FAKE_ROWS]

    orig_verify = pipeline._verify_sql
    orig_run_readonly = pipeline.run_readonly
    orig_logger = pipeline.logger
    pipeline._verify_sql = _fake_verify_sql

    try:
        # ── LAYER 1 ──────────────────────────────────────────────────────────
        print("1. LAYER 1 — BARE BLOCKLISTED COLUMN IS REJECTED")
        pipeline.run_readonly = _fake_run_readonly_plain
        fake_log = _FakeLogger()
        pipeline.logger = fake_log
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show Focus Plus member ids", ["Focus Plus"], _ENTITY_RESULT,
                initial_sql="SELECT member_id FROM curated.v_focus_plus LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("bare `SELECT member_id` raises ClarificationNeeded", raised is not None)
        check("rule tag is pii-column-blocked", raised is not None and raised.rule == "pii-column-blocked")

        print("2. LAYER 1 — ALIASED BLOCKLISTED COLUMN STILL REJECTED")
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show Focus Plus member ids", ["Focus Plus"], _ENTITY_RESULT,
                initial_sql="SELECT member_id AS mid FROM curated.v_focus_plus LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("aliased `SELECT member_id AS mid` still raises ClarificationNeeded", raised is not None)

        print("2b. LAYER 1 — CM ELEVATE scheme_specific JSONB KEY FORM REJECTED")
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show CM Elevate applicant member ids", ["CM Elevate"], _ENTITY_RESULT,
                initial_sql="SELECT scheme_specific ->> 'member_id' AS mid, cm_scheme_key "
                            "FROM curated.v_cm_elevate LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("scheme_specific ->> 'member_id' (quoted JSONB key) raises ClarificationNeeded",
              raised is not None)

        print("3. LAYER 1 — SIMILAR-NAME NON-BLOCKLISTED COLUMN NOT FALSELY REJECTED")
        raised = None
        sql, rows = None, None
        try:
            sql, rows = await pipeline.execute_with_repair(
                "show Focus Plus pincode verification status", ["Focus Plus"], _ENTITY_RESULT,
                initial_sql="SELECT pincode_verified_flag FROM curated.v_focus_plus LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("`pincode_verified_flag` (word-boundary case) is NOT rejected", raised is None)
        check("query actually executed and returned rows", rows == _FAKE_ROWS)

        print("4. LAYER 1 — MGNREGA / PMAY-G (EMPTY BLOCKLIST) NEVER REJECTED")
        for scheme, colname in (("MGNREGA", "member_id"), ("PMAY-G", "pincode")):
            raised = None
            try:
                await pipeline.execute_with_repair(
                    f"show {scheme} data", [scheme], _ENTITY_RESULT,
                    initial_sql=f"SELECT {colname} FROM curated.some_view LIMIT 5")
            except pipeline.ClarificationNeeded as e:
                raised = e
            check(f"{scheme} (empty blocklist) with literal '{colname}' in SQL is never rejected",
                  raised is None)

        print("5. LAYER 1 — REJECTION RESPONSE NEVER LEAKS THE COLUMN NAME (LOG DOES)")
        fake_log.warnings.clear()
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show Focus Plus member ids", ["Focus Plus"], _ENTITY_RESULT,
                initial_sql="SELECT member_id FROM curated.v_focus_plus LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("response text does not contain the blocklisted column name",
              raised is not None and "member_id" not in raised.question)
        check("the log DOES capture which column triggered it",
              any("member_id" in w for w in fake_log.warnings))

        # ── LAYER 2 (pure, on pii_guard.redact_rows) ────────────────────────
        print("6. LAYER 2 — BLOCKLISTED KEY FULLY REMOVED, NOT NULLED")
        row = {"member_id": "12345", "pincode": 793001, "amount_disbursed": 5000}
        out = pii_guard.redact_rows([row], ["Focus Plus"])
        check("member_id key is entirely absent (not present-but-None)",
              "member_id" not in out[0])
        check("pincode key is entirely absent (not present-but-None)",
              "pincode" not in out[0])

        print("7. LAYER 2 — NON-BLOCKLISTED KEYS UNTOUCHED")
        check("amount_disbursed survives with its original value",
              out[0].get("amount_disbursed") == 5000)
        check("original row dict was not mutated in place",
              "member_id" in row)

        print("8. LAYER 2 — ROW WITH NO BLOCKLISTED KEYS PASSES THROUGH UNCHANGED")
        clean_row = {"amount_disbursed": 5000, "financial_year": "2023-24"}
        out2 = pii_guard.redact_rows([clean_row], ["Focus Plus"])
        check("content is identical to the input row", out2[0] == clean_row)

        print("9. LAYER 2 — BACKSTOP: SELECT * ESCAPES LAYER 1 BUT NOT LAYER 2")

        async def _fake_run_readonly_star(sql):
            return [dict(r) for r in [
                {"member_id": "999", "pincode": 793001, "amount_disbursed": 2500}
            ]]

        pipeline.run_readonly = _fake_run_readonly_star
        raised = None
        sql, rows = None, None
        try:
            sql, rows = await pipeline.execute_with_repair(
                "show all Focus Plus disbursement details", ["Focus Plus"], _ENTITY_RESULT,
                initial_sql="SELECT * FROM curated.v_focus_plus LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("`SELECT *` is not rejected by Layer 1 (no literal column name in the SQL text)",
              raised is None)
        check("the rows execute_with_repair returns (the exact object _answer_data "
              "returns, and conversation_store.persist_turn reads via result['data'] — "
              "see tasks.md 0.2) contain no blocklisted key despite Layer 1 missing it",
              rows is not None and "member_id" not in rows[0] and "pincode" not in rows[0])
        check("non-blocklisted data in that same backstopped row survives",
              rows is not None and rows[0].get("amount_disbursed") == 2500)

        # ── FOLLOW-UP FIX #1 — scheme_specific WHOLE-COLUMN BYPASS (CM Elevate) ──
        print("10. LAYER 1b — BARE `SELECT scheme_specific` REJECTED (CM ELEVATE)")
        pipeline.run_readonly = _fake_run_readonly_plain
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show CM Elevate scheme specific data", ["CM Elevate"], _ENTITY_RESULT,
                initial_sql="SELECT scheme_specific FROM curated.v_cm_elevate LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("bare `SELECT scheme_specific` raises ClarificationNeeded", raised is not None)
        check("rule tag is pii-column-blocked", raised is not None and raised.rule == "pii-column-blocked")

        print("11. LAYER 1b — ALIASED `SELECT scheme_specific AS ss` REJECTED")
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show CM Elevate scheme specific data", ["CM Elevate"], _ENTITY_RESULT,
                initial_sql="SELECT scheme_specific AS ss, cm_scheme_key FROM curated.v_cm_elevate LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("aliased `SELECT scheme_specific AS ss` raises ClarificationNeeded", raised is not None)

        print("12. LAYER 1b — `SELECT *` ON CM ELEVATE REJECTED (view includes scheme_specific)")
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show me everything about CM Elevate applications", ["CM Elevate"], _ENTITY_RESULT,
                initial_sql="SELECT * FROM curated.v_cm_elevate LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("`SELECT *` on CM Elevate raises ClarificationNeeded", raised is not None)

        print("13. LAYER 1b — REGRESSION: scoped `->> 'gender_id'` extraction NOT rejected "
              "(the doc's own worked example — a legitimate, non-blocklisted key)")
        raised = None
        sql, rows = None, None
        try:
            sql, rows = await pipeline.execute_with_repair(
                "gender split of CM Elevate applicants", ["CM Elevate"], _ENTITY_RESULT,
                initial_sql="SELECT scheme_specific ->> 'gender_id' AS gender, COUNT(*) AS applications "
                            "FROM curated.v_cm_elevate GROUP BY 1")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("scoped non-blocklisted `->> 'gender_id'` is NOT rejected", raised is None)
        check("query actually executed and returned rows", rows == _FAKE_ROWS)

        print("14. LAYER 1b — scoped `->> 'dob'` (blocklisted key) STILL REJECTED "
              "(find_blocked_columns' existing literal-name scan, unaffected by the new check)")
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show CM Elevate applicant date of birth", ["CM Elevate"], _ENTITY_RESULT,
                initial_sql="SELECT scheme_specific ->> 'dob' AS dob FROM curated.v_cm_elevate LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("scoped `->> 'dob'` (blocklisted key) still raises ClarificationNeeded", raised is not None)

        # ── FOLLOW-UP FIX #1, LAYER 2 — JSON-VALUE REDACTION BACKSTOP ───────────
        print("15. LAYER 2b — JSON-STRING VALUE: BLOCKLISTED KEYS STRIPPED, OTHERS SURVIVE")
        raw_row = {
            "cm_scheme_key": 7,
            "scheme_specific": json.dumps({
                "dob": "1990-01-01", "member_id": "CME-123",
                "gender_id": "Female", "village_name": "Zikzak",
            }),
        }
        out3 = pii_guard.redact_rows([raw_row], ["CM Elevate"])
        parsed_specific = json.loads(out3[0]["scheme_specific"])
        check("dob is absent from the redacted JSON string value", "dob" not in parsed_specific)
        check("member_id is absent from the redacted JSON string value", "member_id" not in parsed_specific)
        check("gender_id (non-blocklisted) survives with its original value",
              parsed_specific.get("gender_id") == "Female")
        check("village_name (non-blocklisted) survives with its original value",
              parsed_specific.get("village_name") == "Zikzak")
        check("original row's scheme_specific string was not mutated in place",
              "dob" in json.loads(raw_row["scheme_specific"]))

        print("16. LAYER 2b — INTEGRATION: `SELECT *` ON CM ELEVATE FALLS THROUGH TO LAYER 2 "
              "(if Layer 1b somehow missed it, the JSON-value backstop still strips it)")

        async def _fake_run_readonly_cm_star(sql):
            return [dict(r) for r in [{
                "cm_scheme_key": 3,
                "scheme_specific": json.dumps({
                    "dob": "1985-05-05", "email_id": "a@example.com",
                    "member_id": "CME-999", "family_id": "F-1",
                    "pds_id": "PDS-1", "account_holder_name": "X",
                    "ifsc_code": "ABCD0123456", "gender_id": "Male",
                    "village_name": "Somewhere",
                }),
            }]]

        # Force this one row through Layer 2 alone (as if Layer 1b's SQL-text
        # scan somehow missed it) by calling redact_rows directly on the fake
        # driver's output — this is the same backstop guarantee section 9
        # established for Focus Plus, now exercised for CM Elevate specifically,
        # per proposal.md's note that the original test only covered Focus Plus.
        star_rows = await _fake_run_readonly_cm_star("SELECT * FROM curated.v_cm_elevate LIMIT 5")
        redacted_star_rows = pii_guard.redact_rows(star_rows, ["CM Elevate"])
        nested = json.loads(redacted_star_rows[0]["scheme_specific"])
        check("no blocklisted key survives at the top level",
              not ({"dob", "email_id", "member_id", "family_id", "pds_id",
                    "account_holder_name", "ifsc_code"} & redacted_star_rows[0].keys()))
        check("no blocklisted key survives inside the nested scheme_specific JSON",
              not ({"dob", "email_id", "member_id", "family_id", "pds_id",
                    "account_holder_name", "ifsc_code"} & nested.keys()))
        check("non-blocklisted nested fields (gender_id, village_name) survive",
              nested.get("gender_id") == "Male" and nested.get("village_name") == "Somewhere")

        print("16b. LAYER 1b + 2b — FULL END-TO-END: `SELECT *` ON CM ELEVATE THROUGH "
              "execute_with_repair IS REJECTED AT LAYER 1b (never reaches Layer 2 at all)")
        pipeline.run_readonly = _fake_run_readonly_cm_star
        raised = None
        try:
            await pipeline.execute_with_repair(
                "show me everything about this CM Elevate application", ["CM Elevate"], _ENTITY_RESULT,
                initial_sql="SELECT * FROM curated.v_cm_elevate LIMIT 5")
        except pipeline.ClarificationNeeded as e:
            raised = e
        check("`SELECT *` on CM Elevate is rejected end-to-end via execute_with_repair",
              raised is not None)
    finally:
        pipeline._verify_sql = orig_verify
        pipeline.run_readonly = orig_run_readonly
        pipeline.logger = orig_logger


asyncio.run(_run())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL PII_GUARD CHECKS PASSED")
