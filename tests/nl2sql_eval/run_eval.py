"""
NL->SQL accuracy: runs every question in questions.yaml through the real chat
pipeline (the LangGraph graph, the real model gateway, the read-only DB pool)
and scores the result against the item's gold SQL, run fresh on the same
read-only pool. Run it on every change to the pipeline, prompts, few-shots or
model assignment; keep a change only when accuracy holds or improves.

The questions are HELD OUT from the fix loop (holdout.py): never add one of
them, or a paraphrase, to a few-shot bank, rule file, test or sheet. The run
refuses to score while any question is leaked.

Each item's outcome:
  correct        the pipeline's rows hold the gold answer (compare.py) — or, for a
                 single-number gold, the answer text states that number
  wrong          it answered with data, but not the gold answer
  clarification  it stopped to ask a question (the items are written to be
                 unambiguous, so this counts against accuracy)
  no_sql         it answered without running SQL (knowledge / edge route, refusal)
  error          an exception (gateway, DB, timeout)
  gold_error     the gold SQL itself failed — a broken item, left out of the score

    python tests/nl2sql_eval/run_eval.py --label baseline
    python tests/nl2sql_eval/run_eval.py --label verifier-30b --fail-on-regression
    python tests/nl2sql_eval/run_eval.py --scheme MGNREGA --ids MG-03,MG-07
    python tests/nl2sql_eval/run_eval.py --check-gold     # gold SQL + hold-out only, no models

Accuracy = correct / (items - gold_error). Every run is saved to results/ with
its git commit and model assignment, and compared with the previous run:
items that were correct and no longer are ("regressions") are listed first.
"""
import argparse
import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="run", help="name for this run (e.g. baseline, verifier-30b)")
    ap.add_argument("--scheme", help="only this scheme")
    ap.add_argument("--ids", help="only these ids, comma-separated")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=180, help="seconds per question")
    ap.add_argument("--baseline", help="results/*.json to compare with (default: the latest earlier run)")
    ap.add_argument("--check-gold", action="store_true", help="run gold SQL and the hold-out check only")
    ap.add_argument("--skip-holdout", action="store_true", help="skip the hold-out check (a run is then marked unscored)")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="exit 1 when an item correct in the baseline is no longer correct")
    ap.add_argument("--allow-superuser", action="store_true",
                    help="let the read-only pool log in as a superuser (until megh_readonly is set up); "
                         "still guarded and in READ ONLY transactions; recorded in the results")
    return ap.parse_args()


ARGS = parse_args()
# Before app.config is imported, so settings picks them up.
os.environ["PIPELINE_GRAPH_CHECKPOINTER_DSN"] = "memory"     # no checkpoint rows in app.*
# Small pools: megh_db (max_connections 100) is shared with the app, pgAdmin and
# other services, and the service-sized pools (.env: 10-30 per pool) once left
# the eval unable to connect at all. An environment variable beats .env.
os.environ["DB_POOL_MIN_SIZE"] = "1"
os.environ["DB_POOL_MAX_SIZE"] = "4"
os.environ["READONLY_DB_POOL_MIN_SIZE"] = "1"
os.environ["READONLY_DB_POOL_MAX_SIZE"] = "3"
if ARGS.allow_superuser:
    os.environ["READONLY_DB_ALLOW_SUPERUSER"] = "true"
sys.path.insert(0, str(ROOT))

from app import db, llm  # noqa: E402
from app.config import settings  # noqa: E402
from tests.nl2sql_eval import holdout  # noqa: E402
from tests.nl2sql_eval.compare import compare, long_as_wide, stated_in_answer  # noqa: E402


def git_info() -> dict:
    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    return {"commit": git("rev-parse", "--short", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def models() -> dict:
    return {"classifier": settings.CLASSIFIER_MODEL, "rewrite": settings.REWRITE_MODEL,
            "sql": settings.SQL_GENERATION_MODEL, "verifier": settings.SQL_VERIFY_MODEL,
            "verifier_enabled": settings.SQL_VERIFY_ENABLED, "composer": settings.RESPONSE_MODEL,
            # where the SQL prompt's worked examples came from (D-074)
            "sql_examples": settings.SQL_EXAMPLES_SOURCE}


def select(items: list[dict]) -> list[dict]:
    if ARGS.scheme:
        items = [i for i in items if i["scheme"].lower() == ARGS.scheme.lower()]
    if ARGS.ids:
        want = {x.strip() for x in ARGS.ids.split(",")}
        items = [i for i in items if i["id"] in want]
    return items


async def startup() -> str:
    """What app.main's lifespan does, minus the HTTP app, the app.* schema and
    KB ingest. Returns the read-only pool's login role."""
    from app import pipeline, schema_introspect
    from app.annotations import load_all as load_annotations
    from app.entity_resolver import load_all as load_entity_resolver
    from app.vectorstore import init_qdrant
    await db.init_pool()
    # The VPN link to megh_db flaps: retry a dropped connection a few times
    # before giving up (a refused superuser login is not retried).
    for attempt in range(1, 6):
        try:
            pool = await db.ensure_readonly_pool()     # ReadonlyRoleError on a superuser login without the flag
            break
        except db.ReadonlyRoleError:
            raise
        except Exception as e:  # noqa: BLE001
            if attempt == 5 or not db.is_connection_error(e):
                raise
            print(f"  megh_db unreachable ({type(e).__name__}) — retry {attempt}/4 in 20 s")
            await asyncio.sleep(20)
    async with pool.acquire() as conn:
        role = await conn.fetchval("SELECT current_user")
    await llm.init_client()
    for label, step in (("qdrant", init_qdrant()), ("schema_catalog", schema_introspect.load()),
                        ("scheme_years", pipeline.refresh_scheme_years())):
        try:
            await step
        except Exception as e:  # noqa: BLE001
            print(f"  startup step {label} failed — continuing: {e}")
    load_annotations()
    load_entity_resolver()
    return role


async def shutdown():
    from app import pipeline_graph
    from app.vectorstore import close_qdrant
    for step in (pipeline_graph.close(), llm.close_client(), close_qdrant(), db.close_pool()):
        try:
            await step
        except Exception:  # noqa: BLE001
            pass


async def run_gold(item: dict) -> "tuple[list[dict] | None, str | None]":
    try:
        return await db.run_readonly(item["gold_sql"]), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


async def run_pipeline(item: dict) -> dict:
    from app import pipeline, turn_trace
    from app.session_store import Session
    # The per-turn trace the router keeps (repairs, verifier rejections, the
    # few-shot ids the prompt carried) — read back into the record below.
    trace = turn_trace.start(f"nl2sql-eval-{item['id']}")
    now = time.time()
    session = Session(session_id=f"nl2sql-eval-{uuid.uuid4().hex[:12]}", user_id="nl2sql-eval",
                      created=now, last_seen=now)
    t0 = time.perf_counter()
    try:
        res = await asyncio.wait_for(pipeline.answer_question(item["question"], session=session),
                                     timeout=ARGS.timeout)
    except pipeline.ClarificationNeeded as e:
        return {"outcome": "clarification", "detail": f"{getattr(e, 'rule', '')}: {e}"[:300],
                "seconds": round(time.perf_counter() - t0, 1), **_trace_fields(trace)}
    except Exception as e:  # noqa: BLE001
        return {"outcome": "error", "detail": f"{type(e).__name__}: {e}"[:300],
                "seconds": round(time.perf_counter() - t0, 1), **_trace_fields(trace)}
    rows = res.get("data") if res.get("data") is not None else res.get("rows")
    return {"outcome": "answered", "route": res.get("route"), "schemes": res.get("schemes"),
            # for diagnosing a miss: what the question became, and the places / years pinned
            "rewritten": res.get("rewritten_question"),
            "resolved": json.loads(json.dumps(res.get("resolved_entities") or {}, default=str)),
            "sql": res.get("sql"), "rows": rows if res.get("sql") else None,
            "answer": res.get("answer") or "", "seconds": round(time.perf_counter() - t0, 1),
            **_trace_fields(trace)}


def _trace_fields(trace: dict) -> dict:
    return {"repairs": int(trace.get("repairs") or 0),
            "verifier_rejections": int(trace.get("verifier_rejections") or 0),
            "few_shot_ids": list(trace.get("few_shot_ids") or [])}


async def evaluate(item: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        gold, gold_err = await run_gold(item)
        rec = {"id": item["id"], "scheme": item["scheme"], "difficulty": item.get("difficulty"),
               "question": item["question"], "gold_rows": None if gold is None else len(gold)}
        if gold_err:
            rec.update(outcome="gold_error", detail=gold_err)
            print(f"  {item['id']:6} GOLD ERROR {gold_err[:120]}")
            return rec
        if ARGS.check_gold:
            rec.update(outcome="gold_ok")
            print(f"  {item['id']:6} gold ok ({len(gold)} rows)")
            return rec
        got = await run_pipeline(item)
        rec.update({k: v for k, v in got.items() if k not in ("rows", "answer")})
        rec["answer"] = (got.get("answer") or "")[:400]
        if got["outcome"] == "answered":
            if not got.get("sql") or got.get("rows") is None:
                rec["outcome"] = "no_sql"
                rec["detail"] = f"route={got.get('route')}"
            else:
                cmp = compare(gold, got["rows"], ordered=bool(item.get("ordered")))
                if not cmp["match"] and long_as_wide(gold, got["rows"]):
                    cmp = {"match": True, "mapping": {},
                           "reason": f"same numbers, one column per category ({cmp['reason']})"}
                if not cmp["match"] and stated_in_answer(gold, got.get("answer") or ""):
                    cmp = {"match": True, "mapping": {},
                           "reason": f"gold value stated in the answer text ({cmp['reason']})"}
                rec["outcome"] = "correct" if cmp["match"] else "wrong"
                rec["detail"], rec["mapping"] = cmp["reason"], cmp["mapping"]
                rec["pred_rows"] = len(got["rows"])
                if not cmp["match"]:
                    rec["gold_sample"] = json.loads(json.dumps(gold[:3], default=str))
                    rec["pred_sample"] = json.loads(json.dumps(got["rows"][:3], default=str))
        print(f"  {item['id']:6} {rec['outcome']:13} {rec.get('seconds', 0):5}s  {rec.get('detail', '')[:90]}")
        return rec


def summarise(records: list[dict]) -> dict:
    scored = [r for r in records if r["outcome"] != "gold_error"]
    by = defaultdict(Counter)
    for r in scored:
        by[r["scheme"]][r["outcome"]] += 1
        by[f"difficulty:{r.get('difficulty')}"][r["outcome"]] += 1
    acc = lambda c: round(100 * c["correct"] / sum(c.values()), 1) if sum(c.values()) else None  # noqa: E731
    total = Counter(r["outcome"] for r in records)
    return {"items": len(records), "scored": len(scored), "outcomes": dict(total),
            "accuracy": acc(Counter(r["outcome"] for r in scored)),
            "by": {k: {"accuracy": acc(c), **dict(c)} for k, c in sorted(by.items())}}


def previous_run(current: Path) -> "Path | None":
    if ARGS.baseline:
        return Path(ARGS.baseline)
    runs = sorted(p for p in RESULTS.glob("*.json") if p != current)
    return runs[-1] if runs else None


def diff(prev: dict, records: list[dict]) -> dict:
    before = {r["id"]: r["outcome"] for r in prev.get("records", [])}
    reg = [r for r in records if before.get(r["id"]) == "correct" and r["outcome"] != "correct"]
    fix = [r for r in records if r["id"] in before and before[r["id"]] != "correct" and r["outcome"] == "correct"]
    return {"regressions": [(r["id"], r["outcome"]) for r in reg], "fixed": [r["id"] for r in fix]}


async def main() -> int:
    items = select(holdout.load_questions())
    if not items:
        print("no questions selected")
        return 2
    holdout_ok = None
    if not ARGS.skip_holdout:
        print("hold-out check ...")
        leaked = holdout.check(items)
        for x in leaked:
            print(f"  LEAKED {x['id']} ({x['score']}): {x['question']!r} ~ {x['matches']!r} [{x['source']}]")
        if leaked:
            print(f"{len(leaked)} question(s) are in the fix loop — replace them before scoring.")
            return 2
        holdout_ok = True
    role = await startup()
    print(f"{len(items)} questions | read-only pool login: {role} | models: {models()}")
    sem = asyncio.Semaphore(ARGS.concurrency)
    t0 = time.perf_counter()
    try:
        records = await asyncio.gather(*(evaluate(i, sem) for i in items))
    finally:
        await shutdown()
    summary = summarise(records)
    if ARGS.check_gold:
        bad = [r for r in records if r["outcome"] == "gold_error"]
        print(f"gold SQL: {len(records) - len(bad)} ok, {len(bad)} failed")
        return 1 if bad else 0

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{dt.datetime.now():%Y-%m-%d_%H%M}_{ARGS.label}.json"
    prev_path = previous_run(out)
    run = {"label": ARGS.label, "when": dt.datetime.now().isoformat(timespec="seconds"),
           "git": git_info(), "models": models(), "readonly_login": role,
           "superuser_allowed": ARGS.allow_superuser, "holdout_checked": holdout_ok,
           "selection": {"scheme": ARGS.scheme, "ids": ARGS.ids},
           "minutes": round((time.perf_counter() - t0) / 60, 1), "summary": summary, "records": records}
    delta = None
    if prev_path and prev_path.exists():
        delta = diff(json.loads(prev_path.read_text(encoding="utf-8")), records)
        run["compared_with"] = prev_path.name
        run["delta"] = delta
    out.write_text(json.dumps(run, indent=1, default=str), encoding="utf-8")

    print(f"\nACCURACY {summary['accuracy']}%  ({summary['outcomes'].get('correct', 0)}/{summary['scored']})"
          f"  outcomes: {summary['outcomes']}")
    for k, v in summary["by"].items():
        print(f"  {k:26} {v['accuracy']}%  " + ", ".join(f"{o}={n}" for o, n in v.items() if o != "accuracy"))
    if delta is not None:
        print(f"vs {prev_path.name}: {len(delta['regressions'])} regression(s) {delta['regressions']}, "
              f"{len(delta['fixed'])} fixed {delta['fixed']}")
    if ARGS.allow_superuser:
        print("NOTE: read-only pool ran as a superuser (--allow-superuser) — still READ ONLY transactions.")
    print(f"saved {out.relative_to(ROOT)}")
    return 1 if (ARGS.fail_on_regression and delta and delta["regressions"]) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
