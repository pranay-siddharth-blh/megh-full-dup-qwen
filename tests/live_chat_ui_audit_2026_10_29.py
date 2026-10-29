"""Live check of the chat UI audit fixes (2026-10-29): the audit's questions through
the real /api/query handler (routers.query._answer) with the real models and
megh_db, nothing written (persistence, caches, memory and audit are stubbed out).
Needs the VPN. Run:  .venv/Scripts/python.exe tests/live_chat_ui_audit_2026_10_29.py OUT.json

Each case is one or more turns in one fresh conversation; the last turn's result
is kept (route, answer, banner, chart hint, columns, rows, pause chips, timing)."""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.requests import Request  # noqa: E402

from app import auth, entity_resolver  # noqa: E402
from app.routers import query as router  # noqa: E402

CASES = [
    ("A-1", ["Compare MGNREGA and PMAY-G expenditure in 2022-23, 2023-24 and 2024-25"]),
    ("G-1", ["Compare MGNREGA and PMAY-G villages in a chart"]),
    ("I-1", ["bottom 5 districts by beneficiaries in MGNREGA and PMAY-G"]),
    ("J-1", ["MGNREGA person days in East Khasi Hills for last 3 years"]),
    ("C-1", ["Compare MGNREGA expenditure 2023-24 vs 2024-25"]),
    ("X-14", ["PMAY-G amount released by district in 2023-24"]),
    ("D-1", ["PMAY-G completion rate by district"]),
    ("E-1", ["Top 5 blocks by MGNREGA person days in 2024-25"]),
    ("G-8", ["How many villages are covered by MGNREGA or PMAY-G?"]),
    ("A-9", ["Compare MGNREGA and PMAY-G amount released each year"]),
    ("B-8", ["Which is better, MGNREGA or PMAY-G?"]),
    ("B-9", ["Which scheme has the least beneficiaries, MGNREGA or PMAY-G?"]),
    ("I-2", ["top 5 districts in MGNREGA and PMAY-G year wise"]),
    ("I-18", ["sabse jyada person days kis district me MGNREGA aur PMAY-G"]),
    ("A-13", ["Compare MGNREGA and Focus Plus beneficiaries each year"]),
    ("C-13", ["Focus Legacy members each year"]),
    ("J-10", ["MGNREGA person days in Apalgre in 2024-25"]),
    ("B-6", ["What is the difference between MGNREGA and PMAY-G?"]),
    ("A-14", ["Compare MGNREGA and PMAY-G beneficiaries in 2022-23 and 2023-24"]),
    ("F-9", ["MGNREGA person days in East Khasi Hils in 2024-25"]),
    ("I-10", ["lowest 5 villages by MGNREGA beneficiaries in Ri Bhoi in 2024-25"]),
    ("E-9", ["top 5 villages by PMAY-G houses sanctioned in Ri Bhoi"]),
    ("E-3", ["List every village with its MGNREGA person days in 2024-25"]),
    ("I-13", ["top 3 districts by beneficiaries in all schemes"]),
    ("A-16", ["MGNREGA and PMAY-G beneficiaries year wise"]),
    ("J-4", ["MGNREGA person days in 2024-25"]),
    ("J-5", ["how many households for MGNREGA"]),
    ("F-7", ["Compare MGNREGA and PMAY-G beneficiaries in East Khasi Hills"]),
    ("F-8", ["Compare MGNREGA person days in 2027-28 and 2024-25 in Ri Bhoi"]),
    ("H-5", ["MGNREGA person days in East Khasi Hills across all financial years"]),
    ("D-1b", ["PMAY-G completion rate by district in 2023-24"]),
    ("E-9b", ["top 5 villages by PMAY-G houses sanctioned in Ri Bhoi in 2023-24"]),
    ("I-18b", ["sabse jyada person days kis district me MGNREGA aur PMAY-G 2023-24 me"]),
    ("J-5b", ["how many households for MGNREGA", "how many households for MGNREGA for all of Meghalaya for FY 2024-25"]),
    ("K-6", ["MGNREGA person days in Ri Bhoi in 2024-25", "and in 2023-24?"]),
]


def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


async def _noop(*a, **k):
    return None


def _quiet():
    """Nothing is written: no conversation rows, no audit, no cache, no memory."""
    router.conversation_store.persist_turn = lambda **k: None
    router.conversation_memory.index_turn = lambda **k: None
    router._mirror_audit = lambda *a, **k: None
    router.session_sync.sync_out = _noop
    router.response_cache.put = _noop
    router.semantic_cache.put = _noop


def _summary(res: dict, secs: float) -> dict:
    data = res.get("data") or []
    clar = res.get("clarification") or {}
    return {
        "route": res.get("route"), "intent": res.get("intent"), "seconds": round(secs, 1),
        "answer": (res.get("answer") or "")[:900], "scope_banner": res.get("scope_banner"),
        "chart_type": res.get("chart_type"), "row_count": res.get("row_count"),
        "total_row_count": res.get("total_row_count"), "columns": list(data[0]) if data else [],
        "data": data[:60], "data_len": len(data), "schemes": res.get("schemes"),
        "measure_notes": res.get("measure_notes"), "column_totals": res.get("column_totals"),
        "pause_rule": clar.get("rule"), "chips": [o.get("label") for o in (clar.get("options") or [])],
        "follow_ups": [o.get("label") for o in (res.get("follow_up_options") or [])],
        "rewritten_question": res.get("rewritten_question"), "sql": (res.get("sql") or "")[:1500],
    }


async def _startup():
    """app.main's startup, read-only steps only (no app schema seeding, no KB ingest)."""
    from app import main as app_main, metric_catalog, pipeline, schema_introspect
    await app_main.init_pool()
    await app_main.init_client()
    await app_main._try("qdrant", app_main.init_qdrant())
    app_main.load_annotations()
    entity_resolver.load_all()
    await app_main._try("village_names", entity_resolver.load_village_names())
    await app_main._try("schema_catalog", schema_introspect.load())
    await app_main._try("metric_catalog", metric_catalog.load())
    await app_main._try("scheme_years", pipeline.refresh_scheme_years())


async def main(out_path: str, only: "set | None"):
    await _startup()
    _quiet()
    scope = auth.scope_from_user({"role": "admin", "username": "audit-live", "id": None})
    scope.user_id = "audit-live"
    results = {}
    for cid, turns in CASES:
        if only and cid not in only:
            continue
        sid = f"audit-live-{cid}-{uuid.uuid4().hex[:6]}"
        res, secs = {}, 0.0
        try:
            for q in turns:
                t0 = time.monotonic()
                res = await router._answer(router.QueryRequest(question=q, session_id=sid, skip_cache=True),
                                           _request(), scope)
                secs = time.monotonic() - t0
            results[cid] = {"question": turns[-1], **_summary(res, secs)}
        except Exception as e:  # noqa: BLE001
            results[cid] = {"question": turns[-1], "error": f"{type(e).__name__}: {e}"[:500]}
        print(cid, results[cid].get("route") or results[cid].get("error"), results[cid].get("seconds"), flush=True)
        Path(out_path).write_text(json.dumps(results, indent=1, default=str, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None))
