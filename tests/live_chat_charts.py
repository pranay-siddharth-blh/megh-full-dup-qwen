"""Live chart suite (2026-10-30, user: "whatever chart the user asks, give it; a
compare question gets a graph by default; when there is no chart for that question,
generate one"). Needs the office VPN (megh_db + model gateway).

Each case is a chat (one or more turns) run like the chat endpoint does it
(conversation layer -> pipeline.answer_question through the LangGraph graph). The
responses are written to tests/nl2sql_eval/results/<stamp>_charts-<label>.json;
`node frontend/tests/chart_live_grade.mjs <that file>` then draws each one with the
real frontend/src/chat/analytics.js and grades what the officer would see.

    .venv/Scripts/python.exe tests/live_chat_charts.py [--only C01,N] [--label run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import conversation_layer, conversation_replies, pipeline  # noqa: E402
from app.pipeline import ClarificationNeeded  # noqa: E402
from app.routers import query as router  # noqa: E402
from app.session_store import SessionStore  # noqa: E402

RESULTS = ROOT / "tests" / "nl2sql_eval" / "results"


def T(q, want, view=None, says=None):
    """One turn. want: 'chart' (any chart must be drawn), 'bar' / 'pie' / 'doughnut' /
    'line' / 'stacked' (that type, and only that type), 'any' (not graded); says: a
    phrase the answer text must contain."""
    return {"q": q, "want": want, "view": view, "says": says}


def case(cid, group, *turns):
    return {"id": cid, "group": group, "turns": list(turns)}


CASES = [
    # ── nothing asked: a comparison is drawn by default ──
    case("D01", "default", T("Compare beneficiaries in MGNREGA and PMAY-G", "chart")),
    case("D02", "default", T("Compare MGNREGA person days in East Khasi Hills and West Garo Hills", "chart")),
    case("D03", "default", T("MGNREGA households provided employment by district", "chart")),
    case("D04", "default", T("PMAY-G houses completed by financial year", "chart")),
    case("D05", "default", T("Compare PMAY-G houses completed in 2022-23 and 2023-24", "chart")),
    # PMAY-G holds no FY 2024-25: one year is answered, and the answer says the other is missing
    case("D08", "default", T("Compare PMAY-G houses completed in 2023-24 and 2024-25", "any",
                             says="2024-25 holds no data")),
    case("D06", "default", T("Compare Focus Plus beneficiaries in East Garo Hills and Ri Bhoi", "chart")),
    case("D07", "default", T("Compare MGNREGA expenditure and PMAY-G expenditure", "chart")),
    # ── a chart asked, no type ──
    case("C01", "chart", T("Show MGNREGA person days by district in a graph", "chart")),
    case("C02", "chart", T("give me chart of PMAY-G houses sanctioned by district", "chart")),
    case("C03", "chart", T("Compare beneficiaries in MGNREGA and PMAY-G in a graph", "chart")),
    case("C04", "chart", T("Visualise CM Elevate applications by district", "chart")),
    # ── one named type: that type only ──
    case("N01", "named", T("bar chart of MGNREGA households provided employment by district", "bar")),
    case("N02", "named", T("pie chart of PMAY-G houses completed by district", "pie")),
    case("N03", "named", T("line graph of MGNREGA expenditure by financial year", "line")),
    case("N04", "named", T("donut chart of Focus Plus beneficiaries by district", "doughnut")),
    case("N05", "named", T("Compare beneficiaries in MGNREGA and PMAY-G as a pie chart", "pie")),
    case("N06", "named", T("Compare beneficiaries in MGNREGA and PMAY-G, I want only bar graph", "bar")),
    case("N07", "named", T("Show MGNREGA person days by district as a line chart", "line")),
    case("N08", "named", T("pie chart of top 5 districts by MGNREGA expenditure", "pie")),
    case("N09", "named", T("PMAY-G houses completed by year in a bar graph", "bar")),
    case("N10", "named", T("Compare PMAY-G houses completed in 2022-23 and 2023-24 as a line graph", "line")),
    case("N11", "named", T("stacked bar chart of PMAY-G houses sanctioned and completed by district", "stacked")),
    # ── a single figure asked as a chart: a chart is still drawn ──
    case("S01", "single", T("Total MGNREGA expenditure as a bar chart", "bar")),
    case("S02", "single", T("How many PMAY-G houses were completed? show in pie chart", "pie")),
    case("S03", "single", T("Show me the total Focus Plus beneficiaries in a graph", "chart")),
    # ── follow-ups that change the view ──
    case("F01", "followup",
         T("MGNREGA households provided employment by district", "chart"),
         T("pie chart", "pie"), T("now give me line graph", "line"), T("I want only bar", "bar")),
    case("F02", "followup",
         T("Compare beneficiaries in MGNREGA and PMAY-G", "chart"),
         T("show this in a pie chart", "pie")),
    case("F03", "followup",
         T("Total PMAY-G houses completed", "any"),
         T("show it in graph", "chart")),
]


def _snap(result: dict) -> dict:
    keep = ("route", "answer", "data", "chart_type", "rewritten_question", "schemes", "row_count",
            "chart_wide", "measure_notes", "column_totals")
    return {k: result.get(k) for k in keep}


async def run_turn(session, q: str) -> dict:
    try:
        layer = await conversation_layer.prepare_turn(session, q)
        if layer.response is not None:
            result = layer.response
        elif layer.multi:
            result = await conversation_layer.answer_many(
                layer.multi, lambda x: pipeline.answer_question(x, session=session, scope=None))
        else:
            result = await pipeline.answer_question(layer.question, session=session, scope=None)
        styled = conversation_replies.restyle(session, q, result)
        if styled is not None:
            result = styled
        session.turns.append(router.build_turn(q, result))
        return _snap(result)
    except ClarificationNeeded as e:
        router.remember_pause(session, q, e)
        return {"route": f"clarify:{e.rule}", "answer": e.question,
                "options": [o.get("label") for o in (e.options or [])]}


async def run_case(c: dict, store: SessionStore, sem: asyncio.Semaphore) -> dict:
    async with sem:
        session = store.ensure(f"live-ch-{c['id']}-{uuid.uuid4().hex[:6]}", "live-charts")
        out = []
        for turn in c["turns"]:
            t0 = time.perf_counter()
            try:
                got = await run_turn(session, turn["q"])
            except Exception as e:  # noqa: BLE001 — a crash is a failure, not the end of the run
                got = {"route": f"error:{type(e).__name__}", "answer": str(e)[:300]}
            got["seconds"] = round(time.perf_counter() - t0, 2)
            out.append({**turn, "response": got})
        return {"id": c["id"], "group": c["group"], "turns": out}


async def main(args) -> int:
    from app import main as app_main
    logging.basicConfig(level=logging.WARNING)
    cases = CASES
    if args.only:
        keys = [k.strip() for k in args.only.split(",") if k.strip()]
        cases = [c for c in CASES if any(c["id"] == k or c["id"].startswith(k) or c["group"] == k for k in keys)]
    store = SessionStore(ttl=3600, max_sessions=1000, max_turns=20)
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    async with app_main.lifespan(app_main.app):
        results = await asyncio.gather(*(run_case(c, store, sem) for c in cases))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{time.strftime('%Y-%m-%d_%H%M')}_charts-{args.label}.json"
    out.write_text(json.dumps({"label": args.label, "results": results}, ensure_ascii=False, indent=1,
                              default=str), encoding="utf-8")
    print(f"{len(results)} chats in {time.perf_counter() - t0:.0f}s; written {out.relative_to(ROOT)}")
    # the grading is the frontend's own code
    return subprocess.call(["node", str(ROOT / "frontend" / "tests" / "chart_live_grade.mjs"), str(out)])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--label", default="run")
    ap.add_argument("--concurrency", type=int, default=4)
    sys.exit(asyncio.run(main(ap.parse_args())))
