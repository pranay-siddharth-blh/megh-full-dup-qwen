"""
Urgent PII redaction (app/pii_guard.py, openspec/changes/urgent-pii-redaction)
— pure-logic + monkeypatched-dependency checks, no DB, no model gateway. Run:
`python tests/test_pii_guard.py`, exit code 0 = all pass.

Covers tasks.md groups 1 and 2's acceptance scenarios:
  Layer 1 (pre-execution SQL-text blocklist, wired into
  app/pipeline.py::execute_with_repair immediately before run_readonly):
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
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import pii_guard, pipeline  # noqa: E402

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
