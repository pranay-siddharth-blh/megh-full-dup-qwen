"""Metric catalogue measurement (D-071) — live, needs the VPN.

For every catalogue measure of the six schemes it asks the REAL pipeline a set
of plain questions (one total at the state, a district and a block; a breakdown
by district; the top district; two districts compared), with the catalogue in
shadow mode, so the model path answers as it does today. For each question it
records what the catalogue would have built, runs that query on the read-only
pool, and compares the two figures.

The result decides data/metric_catalog_verified.yaml: a measure is listed for a
query type only when every question of that type agreed.

    .venv/Scripts/python.exe -X utf8 tests/metric_catalog_eval.py [--types total,ranking] \
        [--metrics key1,key2] [--concurrency 3] [--out <file.json>]
"""
import argparse
import asyncio
import contextvars
import json
import sys
import time
import uuid
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, llm  # noqa: E402
from app.config import settings  # noqa: E402
from app.text_match import number_spans, to_number  # noqa: E402

ARGS = None
_PLANS: contextvars.ContextVar = contextvars.ContextVar("metric_catalog_plans")

# One year each scheme holds in full (PMAY-G's latest is a sanction year with
# most houses still open; MGNREGA FY2024-25 is a partial extract).
YEARS = {"MGNREGA": "2023-24", "PMAY-G": "2022-23", "Focus Plus": "2022-23", "Focus Legacy": "2022-23",
         "CM Elevate": None, "CM Elevate Legacy": "2024-25"}
DISTRICT, BLOCK, PAIR = "Ri Bhoi", "Umsning", ("Ri Bhoi", "West Garo Hills")


def _questions(m, raw_synonyms: list[str]) -> list[dict]:
    from app import metric_catalog as mc
    words = [s for s in [*raw_synonyms, m.display_name] if mc.match(s, m.scheme).metric is m][:2]
    if not words:
        return []
    fy = YEARS[m.scheme]
    yr = f" in FY {fy}" if fy else ""
    sch = m.scheme
    out = []
    for w in words:
        out += [
            {"type": "total", "q": f"What is the {w} under {sch} in {DISTRICT} district{yr}?"},
            {"type": "total", "q": f"Total {w} under {sch} in Meghalaya{yr}"},
        ]
    w = words[0]
    out += [
        {"type": "total", "q": f"{w} under {sch} in {BLOCK} block{yr}"},
        {"type": "breakdown", "q": f"{w} under {sch} by district{yr}"},
        {"type": "ranking", "q": f"Which district had the highest {w} under {sch}{yr}?"},
        {"type": "compare", "q": f"Compare {w} under {sch} in {PAIR[0]} and {PAIR[1]}{yr}"},
    ]
    return [dict(x, metric=m.key, scheme=sch) for x in out]


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    return None


_FACTORS = (1, 100, 0.01, 1e7, 1e-7, 1e5, 1e-5)


def _close(a: float, b: float, rel: float = 1e-6) -> bool:
    return abs(a - b) <= max(0.0051, rel * abs(b))


def _same(cell: float, v: float, rel: float = 1e-6) -> bool:
    return any(_close(cell * f, v, rel) for f in _FACTORS)


def _answer_numbers(text: str) -> list[float]:
    return [n for n in (to_number(s) for _, _, s in number_spans(text or "")) if n is not None]


def _groups(rows: list[dict], alias: str) -> dict:
    out = {}
    for r in rows:
        key = next((r[k] for k in r if k != alias and k != "financial_year"), None)
        out[str(key).upper()] = _num(r.get(alias))
    return out


def compare(qtype: str, alias: str, cat_rows: list[dict], model_rows: list[dict], answer: str) -> dict:
    """Do the model's rows (or its answer) hold the catalogue's figures?"""
    if qtype == "total":
        v = _num(cat_rows[0].get(alias)) if cat_rows else None
        if v is None:
            return {"rows": None, "answer": None, "catalogue": None}
        cells = [n for r in model_rows for n in map(_num, r.values()) if n is not None]
        return {"catalogue": v, "rows": any(_same(c, v) for c in cells),
                "answer": any(_same(n, v, 0.006) for n in _answer_numbers(answer))}
    want = _groups(cat_rows, alias)
    hit = 0
    named = {str(x).upper() for r in model_rows for x in r.values()}
    for key, v in want.items():
        if v is None:
            continue
        if v == 0 and key not in named:
            hit += 1                     # a zero row the model's query left out: the same figures
            continue
        for r in model_rows:
            texts = {str(x).upper() for x in r.values() if not isinstance(x, (int, float, Decimal))}
            texts |= {str(int(x)) for x in r.values() if isinstance(x, int)}
            if key in texts and any(_same(n, v) for n in map(_num, r.values()) if n is not None):
                hit += 1
                break
    usable = sum(1 for v in want.values() if v is not None)
    return {"catalogue": want, "rows": usable > 0 and hit == usable, "matched": f"{hit}/{usable}",
            "answer": None}


async def ask(item: dict, sem: asyncio.Semaphore) -> dict:
    from app import pipeline
    from app.session_store import Session
    async with sem:
        plans: list = []
        _PLANS.set(plans)
        now = time.time()
        session = Session(session_id=f"mc-eval-{uuid.uuid4().hex[:12]}", user_id="mc-eval",
                          created=now, last_seen=now)
        rec = dict(item)
        t0 = time.perf_counter()
        try:
            res = await asyncio.wait_for(pipeline.answer_question(item["q"], session=session), timeout=240)
        except pipeline.ClarificationNeeded as e:
            res = None
            rec.update(outcome="asked", detail=str(e)[:200])
        except Exception as e:  # noqa: BLE001
            res = None
            rec.update(outcome="error", detail=f"{type(e).__name__}: {e}"[:200])
        rec["seconds"] = round(time.perf_counter() - t0, 1)
        plan = plans[-1] if plans else None
        rec["plan"] = None if plan is None else {k: plan[k] for k in ("status", "metric", "qtype", "reason",
                                                                      "question", "verified")}
        if res is not None:
            rows = res.get("data") if res.get("data") is not None else (res.get("rows") or [])
            rec.update(outcome="answered", sql=res.get("sql"), answer=(res.get("answer") or "")[:500],
                       model_rows=json.loads(json.dumps(rows[:40], default=str)))
            if res.get("clarification") or res.get("needs_clarification"):
                rec["outcome"] = "asked"
        if plan and plan.get("query") and rec.get("outcome") == "answered":
            from app import metric_catalog as mc
            m = mc.metrics()[plan["metric"]]
            cat = await db.fetch_rows_readonly(plan["query"][0], plan["query"][1])
            rec["catalogue_sql"] = plan["query"][2]
            rec["catalogue_rows"] = json.loads(json.dumps(cat[:40], default=str))
            raw_rows = rows if res is not None else []
            rec["agree"] = compare(plan["qtype"], m.alias, cat, raw_rows, res.get("answer") or "")
            rec["agree"] = json.loads(json.dumps(rec["agree"], default=str))
        a = rec.get("agree") or {}
        print(f"  {item['metric'][:34]:34} {item['type']:9} {rec.get('outcome', '?'):9} "
              f"plan={(rec['plan'] or {}).get('status')}/{(rec['plan'] or {}).get('qtype')} "
              f"rows={a.get('rows')} ans={a.get('answer')} {rec['seconds']}s | {item['q'][:70]}"
              f" | {(rec['plan'] or {}).get('reason', '')[:60]}", flush=True)
        return rec


async def startup() -> None:
    """What app.main's lifespan does, minus the HTTP app, the app.* schema and KB ingest."""
    from app import pipeline, schema_introspect
    from app.annotations import load_all as load_annotations
    from app.entity_resolver import load_all as load_entity_resolver, load_village_names
    from app.vectorstore import init_qdrant
    await db.init_pool()
    await db.ensure_readonly_pool()
    await llm.init_client()
    for step in (init_qdrant(), schema_introspect.load(), pipeline.refresh_scheme_years(), load_village_names()):
        try:
            await step
        except Exception as e:  # noqa: BLE001
            print(f"  startup step failed — continuing: {e}")
    load_annotations()
    load_entity_resolver()


async def shutdown() -> None:
    from app import pipeline_graph
    from app.vectorstore import close_qdrant
    for step in (pipeline_graph.close(), llm.close_client(), close_qdrant(), db.close_pool()):
        try:
            await step
        except Exception:  # noqa: BLE001
            pass


async def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default="total,breakdown,ranking,compare")
    ap.add_argument("--metrics", default="")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="shadow", choices=("shadow", "on"),
                    help="shadow: the model answers (builds the evidence); on: verified measures answer")
    ARGS = ap.parse_args()
    settings.METRIC_CATALOG_MODE = ARGS.mode
    await startup()
    from app import metric_catalog as mc
    from app import pipeline
    await mc.load()
    real = pipeline._metric_catalog_plan

    def recorded(question, schemes, entity_result):
        plan = real(question, schemes, entity_result)
        try:
            _PLANS.get().append(dict(plan, question=question))
        except LookupError:
            pass
        return plan

    pipeline._metric_catalog_plan = recorded
    syn = {r["metric_key"]: list(r["synonyms"] or []) for r in await db.fetch_rows_readonly(
        "SELECT metric_key, synonyms FROM semantic.metric_definitions WHERE is_active")}
    want_types = set(ARGS.types.split(","))
    want_metrics = {x for x in ARGS.metrics.split(",") if x}
    items = []
    for key, m in sorted(mc.metrics().items()):
        if want_metrics and key not in want_metrics:
            continue
        items += [q for q in _questions(m, syn.get(key, [])) if q["type"] in want_types]
    print(f"{len(items)} questions, {len(mc.metrics())} measures, concurrency {ARGS.concurrency}")
    sem = asyncio.Semaphore(ARGS.concurrency)
    records = await asyncio.gather(*(ask(i, sem) for i in items))
    await shutdown()
    verdict = defaultdict(Counter)
    for r in records:
        a = r.get("agree") or {}
        state = ("agree" if a.get("rows") or a.get("answer") else "differ") if a else \
            f"not compared ({r.get('outcome')}, {(r.get('plan') or {}).get('status')})"
        verdict[(r["metric"], r["type"])][state] += 1
    summary = {f"{k[0]} {k[1]}": dict(v) for k, v in sorted(verdict.items())}
    out = Path(ARGS.out)
    out.write_text(json.dumps({"summary": summary, "records": records}, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
