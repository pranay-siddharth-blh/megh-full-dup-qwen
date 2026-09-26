"""
app/conversation/failures.py — what counts as a failed turn, in ONE place.

Used by the admin "today's failures" view (SQL over app.query_audit) and by
tests/eval/export_failures.py (the same rules over logs/query_audit.jsonl
records, so the export also works without the database). Every failure found
in production is meant to become an eval case — see the export script.

  zero_rows       a data answer that returned no rows
  repair_used     the first SQL failed a check and had to be repaired
  fallback_reply  the answer came from a fallback (deterministic text after
                  the number check, or the KB after a failed data path)
  clarify_loop    the bot asked for clarification more than twice in one
                  conversation that day
"""
from __future__ import annotations

import collections
import json

REASONS = ("zero_rows", "repair_used", "fallback_reply", "clarify_loop")
CLARIFY_LOOP_THRESHOLD = 2          # "more than twice"


def _trace(rec: dict) -> dict:
    t = rec.get("trace")
    if isinstance(t, str):
        try:
            t = json.loads(t)
        except ValueError:
            t = None
    return t if isinstance(t, dict) else {}


def reasons_for(rec: dict, clarifications_in_session: int = 0) -> list[str]:
    """The failure reasons that apply to one audit record."""
    out = []
    t = _trace(rec)
    rows = rec.get("row_count")
    if rec.get("route") == "data" and (rows in (0, "0")):
        out.append("zero_rows")
    if int(t.get("repairs") or 0) > 0:
        out.append("repair_used")
    if t.get("fallback"):
        out.append("fallback_reply")
    if rec.get("route") == "clarification" and clarifications_in_session > CLARIFY_LOOP_THRESHOLD:
        out.append("clarify_loop")
    return out


def classify(records: list[dict]) -> list[dict]:
    """Records (one day) -> the failed ones, each with a `reasons` list."""
    clar = collections.Counter(r.get("session_id") for r in records if r.get("route") == "clarification")
    failed = []
    for r in records:
        why = reasons_for(r, clar.get(r.get("session_id"), 0))
        if why:
            failed.append({**r, "reasons": why})
    return failed


# The same rules in SQL, for app.query_audit (tenant filter + day bound by the caller).
FAILURES_SQL = """
WITH day AS (
    SELECT * FROM app.query_audit
    WHERE created_at >= $1::date AND created_at < ($1::date + 1) {tenant_clause}
), loops AS (
    SELECT session_id FROM day WHERE route = 'clarification'
    GROUP BY session_id HAVING count(*) > {threshold}
)
SELECT d.id, d.created_at, d.tenant_id, d.username, d.session_id, d.question, d.rewritten_question,
       d.route, d.row_count, d.sql, d.answer, d.denied_by, d.trace,
       ARRAY_REMOVE(ARRAY[
           CASE WHEN d.route = 'data' AND d.row_count = 0 THEN 'zero_rows' END,
           CASE WHEN COALESCE((d.trace->>'repairs')::int, 0) > 0 THEN 'repair_used' END,
           CASE WHEN d.trace->>'fallback' IS NOT NULL THEN 'fallback_reply' END,
           CASE WHEN d.route = 'clarification' AND d.session_id IN (SELECT session_id FROM loops)
                THEN 'clarify_loop' END
       ], NULL) AS reasons
FROM day d
WHERE (d.route = 'data' AND d.row_count = 0)
   OR COALESCE((d.trace->>'repairs')::int, 0) > 0
   OR d.trace->>'fallback' IS NOT NULL
   OR (d.route = 'clarification' AND d.session_id IN (SELECT session_id FROM loops))
ORDER BY d.created_at DESC
LIMIT {limit}
"""
