"""Live test harness: drives conversations through pipeline.answer_question (the
LangGraph orchestrator) with the real models and megh_db, the way routers.query
does (build_turn after an answer, remember_pause after a pause)."""
import asyncio
import json
import logging
import os
import sys
import time
import uuid

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # repo root, for tests._text_checks
logging.basicConfig(level=logging.ERROR)

from app import db, pipeline  # noqa: E402
from tests._text_checks import number_runs  # noqa: E402
from app.routers.query import build_turn, pause_question, remember_pause  # noqa: E402
from app.session_store import SessionStore  # noqa: E402

STORE = SessionStore(ttl=3600, max_sessions=5000, max_turns=8)


class _RepairLog(logging.Handler):
    """Keeps the pipeline's repair / fallback warnings ("SQL failed (attempt 1/4), repairing: …",
    "data path failed (…) — trying KB fallback") so a "couldn't build a working query" case
    carries its diagnosis in the results file (MGNREGA UAT 2026-10-30: a Jirang list failed
    once in the run and never again in three traces)."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record):
        msg = record.getMessage()
        if "SQL failed" in msg or "data path failed" in msg or "verifier" in msg.lower():
            self.lines.append(msg[:600])


for _n in ("app.pipeline", "app.pipeline_graph"):
    logging.getLogger(_n).setLevel(logging.WARNING)
_REPAIRS = _RepairLog()
logging.getLogger("app.pipeline").addHandler(_REPAIRS)
logging.getLogger("app.pipeline_graph").addHandler(_REPAIRS)


def _rows(r):
    # `data` is the full table; `rows` is the first 20 the router shows (a six-scheme
    # per-district answer has 72 rows, cross-scheme run 2026-10-30)
    rows = r.get("data") or r.get("rows") or []
    return [dict(x) for x in rows][:300]


class Conv:
    def __init__(self):
        self.sid = "gen-" + uuid.uuid4().hex[:10]
        self.session = STORE.ensure(self.sid, "tester")
        self.turns = []

    async def ask(self, q):
        self.session.turn_context = {}
        t0 = time.perf_counter()
        rec = {"q": q}
        try:
            r = await pipeline.answer_question(q, session=self.session, scope=None)
            self.session.turns.append(build_turn(q, r))
            rec.update(kind="answer", n_rows=r.get("row_count") or len(r.get("data") or r.get("rows") or []), answer=r.get("answer"), route=r.get("route"), intent=r.get("intent"),
                       schemes=r.get("schemes"), sql=r.get("sql") or r.get("sql_query"), rows=_rows(r),
                       entities=r.get("resolved_entities"), rewritten=r.get("rewritten_question"),
                       suggestions=r.get("suggestions"), options=r.get("follow_up_options"))
        except pipeline.ClarificationNeeded as e:
            remember_pause(self.session, pause_question(self.session, q), e)
            rec.update(kind="pause", answer=e.question, rule=e.rule,
                       options=[o.get("label") if isinstance(o, dict) else str(o) for o in (e.options or [])],
                       option_qs=[o.get("question") if isinstance(o, dict) else str(o) for o in (e.options or [])])
        except Exception as e:  # noqa: BLE001
            rec.update(kind="error", answer=f"{type(e).__name__}: {e}")
        rec["ms"] = round((time.perf_counter() - t0) * 1000)
        if _REPAIRS.lines:
            # concurrent conversations share the handler: the lines are a best-effort trail
            rec["repairs"] = list(_REPAIRS.lines[-8:])
            _REPAIRS.lines.clear()
        self.turns.append(rec)
        return rec


async def fetch(sql, params=None):
    return [dict(x) for x in await db.fetch_rows(sql, params or [])]


def numbers_in(rows):
    out = []
    for r in rows or []:
        for v in r.values():
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                pass
    return out


def text_numbers(text):
    vals = []
    for _s, _e, num in number_runs(text):
        try:
            vals.append(float(num.replace(",", "")))
        except ValueError:
            pass
    return vals


def close(a, b, rel=0.005):
    return b is not None and a is not None and abs(a - b) <= max(0.011, abs(b) * rel)


def has_value(rec, expected, rel=0.005):
    """True when the bot's rows or answer text carry the expected figure (exact
    or as lakh/crore conversions of a lakh-rupee value)."""
    cands = numbers_in(rec.get("rows")) + text_numbers(rec.get("answer"))
    forms = [expected, expected / 100.0, expected * 100000.0]   # lakh, crore, rupees
    return any(close(c, f, rel) for c in cands for f in forms)
