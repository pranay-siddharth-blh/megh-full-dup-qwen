"""
What one turn did on the DATA path, for the audit trail and /metrics.

The router starts a trace per request (`start()`); the pipeline stages record
into it — the few-shot examples the SQL prompt carried, every SQL error that
sent a query to repair, verifier rejections, and the error a turn finally gave
up on. LangGraph runs each node in its own task with a COPY of the request's
context, so the trace is one shared mutable dict: a copy of the context still
points at the same dict, and what a node records reaches the router.

Process-wide counters (`COUNTERS`, per worker, like app.cache.metrics) are
updated once per turn by `finish()` and exposed on /metrics.
"""
from __future__ import annotations

import contextvars
import time
import glob
import json
import os
import threading
from pathlib import Path

_trace_var: "contextvars.ContextVar[dict | None]" = contextvars.ContextVar("turn_trace", default=None)
_lock = threading.Lock()
_MAX_ERRORS = 5          # per turn, in the audit row
_MAX_ERROR_CHARS = 500

COUNTERS: dict[str, int] = {
    "data_turns": 0,                 # turns that ran SQL (route data, with a query)
    "sql_ok_first_try": 0,           # ... answered by the first query
    "sql_ok_after_repair": 0,        # ... answered after one or more repairs
    "sql_failed": 0,                 # DATA path gave up (honest message or KB fallback)
    "repairs_total": 0,              # repair calls made
    "verifier_rejections": 0,        # queries the semantic verifier sent back
    "clarifications": 0,             # turns that paused with a question
    "knowledge_turns": 0,            # turns answered from the knowledge base
}


def start(request_id: str = "-") -> dict:
    """A fresh trace for this request (call before the pipeline runs)."""
    t = {"request_id": request_id, "few_shot_ids": [], "sql_errors": [], "repairs": 0,
         "verifier_rejections": 0, "final_error": None,
         "started": time.monotonic()}   # KI-013: the repair loop's time budget reads it
    _trace_var.set(t)
    return t


def current() -> "dict | None":
    return _trace_var.get()


def elapsed() -> "float | None":
    """Seconds since this request's trace started, or None outside a request."""
    t = _trace_var.get()
    return (time.monotonic() - t["started"]) if t and t.get("started") else None


def _cut(text) -> str:
    s = str(text or "")
    return s if len(s) <= _MAX_ERROR_CHARS else s[:_MAX_ERROR_CHARS] + "…"


def note_few_shots(ids) -> None:
    t = _trace_var.get()
    if t is not None:
        for i in ids or []:
            if i and i not in t["few_shot_ids"]:
                t["few_shot_ids"].append(i)


def note_repair(error) -> None:
    """A query failed with `error` and is being repaired."""
    t = _trace_var.get()
    if t is not None:
        t["repairs"] += 1
        if len(t["sql_errors"]) < _MAX_ERRORS:
            t["sql_errors"].append(_cut(error))


def note_verifier_rejection() -> None:
    t = _trace_var.get()
    if t is not None:
        t["verifier_rejections"] += 1


def note_final_error(error) -> None:
    """The DATA path gave up on this error (repair budget spent, no query)."""
    t = _trace_var.get()
    if t is not None:
        t["final_error"] = _cut(error)


def audit_fields(trace: "dict | None", result: dict) -> dict:
    """The audit columns for this turn: the SQL that ran, the error, few-shot ids,
    repairs, verifier rejections and the request id."""
    t = trace or {}
    error = t.get("final_error") or ("; ".join(t.get("sql_errors") or []) or None)
    return {
        "request_id": t.get("request_id"),
        "sql": result.get("sql") or result.get("sql_query"),
        "error": error,
        "few_shot_ids": list(t.get("few_shot_ids") or []),
        "repairs": int(t.get("repairs") or 0),
        "verifier_rejections": int(t.get("verifier_rejections") or 0),
        "outcome": outcome(trace, result),
    }


def outcome(trace: "dict | None", result: dict) -> str:
    """ok_first_try | ok_after_repair | failed | clarification | knowledge | other.
    A data turn that fell back to the knowledge base is 'failed', not
    'knowledge' — the audit can tell the two apart."""
    t = trace or {}
    route = result.get("route")
    if route == "clarification" or result.get("needs_clarification"):
        return "clarification"
    if t.get("final_error"):
        return "failed"
    if route == "data" and (result.get("sql") or result.get("sql_query")):
        return "ok_after_repair" if t.get("repairs") else "ok_first_try"
    if route == "data" and result.get("confidence") == "low":
        return "failed"
    if route == "knowledge":
        return "knowledge"
    return "other"


def finish(trace: "dict | None", result: dict) -> None:
    """Update the per-worker counters once for this turn."""
    o = outcome(trace, result)
    t = trace or {}
    with _lock:
        COUNTERS["repairs_total"] += int(t.get("repairs") or 0)
        COUNTERS["verifier_rejections"] += int(t.get("verifier_rejections") or 0)
        if o in ("ok_first_try", "ok_after_repair", "failed"):
            COUNTERS["data_turns"] += 1
        key = {"ok_first_try": "sql_ok_first_try", "ok_after_repair": "sql_ok_after_repair",
               "failed": "sql_failed", "clarification": "clarifications",
               "knowledge": "knowledge_turns"}.get(o)
        if key:
            COUNTERS[key] += 1


_EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "nl2sql_eval" / "results"


def latest_eval() -> "dict | None":
    """The most recent FULL held-out NL->SQL accuracy run (tests/nl2sql_eval) —
    a re-check of a few ids or one scheme (`selection`) is not the accuracy."""
    files = sorted(glob.glob(str(_EVAL_DIR / "*.json")), key=os.path.getmtime)
    for f in reversed(files):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sel = d.get("selection") or {}
        if sel.get("ids") or sel.get("scheme"):
            continue
        s = d.get("summary") or {}
        if "accuracy" in s:
            return {"label": d.get("label"), "when": d.get("when"), "accuracy_pct": s.get("accuracy"),
                    "questions": sum((s.get("outcomes") or {}).values()) or None,
                    "outcomes": s.get("outcomes")}
    return None


def metrics() -> dict:
    """The /metrics block: live repair / outcome counters for this worker, the
    derived rates, and the latest offline accuracy run."""
    with _lock:
        c = dict(COUNTERS)
    data = c["data_turns"]
    ok = c["sql_ok_first_try"] + c["sql_ok_after_repair"]
    return {
        **c,
        "sql_success_rate_pct": round(100.0 * ok / data, 1) if data else None,
        "sql_first_try_rate_pct": round(100.0 * c["sql_ok_first_try"] / data, 1) if data else None,
        "repairs_per_data_turn": round(c["repairs_total"] / data, 2) if data else None,
        "nl2sql_eval_latest": latest_eval(),
    }
