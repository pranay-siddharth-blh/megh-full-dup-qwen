"""Resumable runner for uat/test_matrix.csv -> uat/results.csv (one row per attempt, appended at once).

    python uat/run_matrix.py [--workers 10] [--only C01,C04] [--ids-file f] [--rerun-failed] [--all]

* A test is DONE when its latest result row is Pass or Fail; Error rows are re-run (3 tries inside a run,
  then the run re-tries all errors once more at the end).
* --rerun-failed: re-run the tests whose latest row is Fail (after a fix); --all: re-run everything
  (final full pass; rows are appended with a new run tag, the latest row per id wins).
* Zero writes: no app lifespan (it creates app.* tables), no session sync, the LangGraph checkpointer in
  memory, and db.execute / execute_script refused. Questions run through the router's own path
  (conversation layer -> pipeline graph -> restyle), as tests/conversation_harness does.
"""
import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
csv.field_size_limit(10 ** 8)

import live_cme_uat as U  # noqa: E402

RESULTS = os.path.join(HERE, "results.csv")
PROGRESS = os.path.join(HERE, "progress.log")
FIELDS = ["id", "category", "tc", "level", "question", "expected", "actual", "route", "sql", "status", "fails",
          "secs", "attempts", "run", "ts"]
ORDER = ["C01", "C16", "C04", "C15", "C10", "C12", "C13", "C09", "C07", "C05", "C03", "C08", "C06", "C11", "C02", "C14"]

TIME_OK = re.compile(r"no date|no time|not record\w* (a |any )?(date|time|year)|time period|no financial year|"
                     r"cannot be placed|can't be placed|not (be )?placed in a financial year|no year|does not hold (a |any )?"
                     r"(date|year)|doesn't hold (a |any )?(date|year)|has no date|without a time filter|no dates?\b", re.I)
BAD_ZERO = ["couldn't find", "could not find", "not found", "doesn't cover", "does not cover", "no data available",
            "not available", "don't have data", "do not have data", "isn't covered", "not covered", "no information",
            "couldn't build", "could not build"]
NAME_OK = re.compile(r"not (hold|record|store|have|include|share|provide|available)|doesn't (hold|record|have|include)|"
                     r"no (names?|personal|individual)|personal|privacy|can(no|')t (share|provide|give)|not able to share|"
                     r"only (counts|aggregate)|aggregate|does not contain|doesn.t contain|isn.t part of|not part of", re.I)  # R9 (decisions 22, D3)


def norm(s):
    return U.norm(s)


def has_num(text, n):
    return U.has_num(text, n)


def check_list(text, checks, total=None, ties_at=None):
    fails, low = [], norm(text)
    for kws, n in checks:
        if n is None:                       # label only (village -> constituency)
            if kws and not any(norm(k) in low for k in kws):
                fails.append(f"label {kws[0]!r} absent")
            continue
        if not has_num(text, n):
            fails.append(f"missing {n}" + (f" ({kws[0]})" if kws else ""))
        elif kws and n and not (ties_at is not None and n <= ties_at) and not any(norm(k) in low for k in kws):
            fails.append(f"label {kws[0]!r} absent")
    if total not in (None, "") and int(total) and not has_num(text, int(total)):
        fails.append(f"missing total {total}")
    return fails


def judge(t, rec, raw):
    kind, text = t["kind"], rec["answer"] or ""
    checks, extra = json.loads(t["checks"]), json.loads(t["extra"] or "{}")
    route = rec["route"]
    if route == "error":
        return ["error: " + text[:200]]
    if kind == "no_time":
        if TIME_OK.search(text):
            return []
        # decisions.md #13: a financial-year word pins CM Elevate Legacy (the dataset choice, user
        # decision 2026-10-22); a Legacy answer that says it is Legacy is the designed outcome
        if list((raw or {}).get("schemes") or []) == ["CM Elevate Legacy"] and "legacy" in text.lower():
            return []
        return [f"no 'no time dimension' reply ({route}): {text[:160]}"]
    if kind == "not_found":
        if route == "pause" or any(w in text.lower() for w in U.NOT_FOUND):
            if not re.search(r"\b(are|were|has|have)\s+[1-9][\d,]*\s+(cm elevate\s+)?applica", text.lower()):
                return []
        return ["a figure or no 'not found' for a place that does not exist"]
    if kind == "no_names":
        if re.search(r"\b\d{10}\b|\b\d{4}\s?\d{4}\s?\d{4}\b", text):
            return ["looks like personal data"]
        return [] if (NAME_OK.search(text) or route in ("edge", "pause")) else [f"no refusal: {text[:160]}"]
    if kind == "zero":
        if route != "data":
            return [f"no data answer: route={route}: {text[:160]}"]
        bad = [w for w in BAD_ZERO if w in text.lower()]
        if bad:
            return [f"zero worded as missing data ({bad[0]}): {text[:160]}"]
        return [] if has_num(text, 0) else [f"no zero stated: {text[:160]}"]
    if kind == "pause_or_each":
        if route == "pause":
            return []
        each = extra.get("each") or []
        return check_list(text, [[[b], n] for b, n in each])
    if kind == "bottom_villages":
        if route != "data":
            return [f"no data answer: route={route}"]
        f = [] if has_num(text, extra["min"]) else [f"missing min {extra['min']}"]
        if not any(n in norm(text) for n in extra["names_at_min"]):
            f.append("no village at the minimum named")
        return f
    if kind == "scheme":
        want = extra.get("schemes") or []
        got = list((raw or {}).get("schemes") or [])
        if route == "pause":
            return [] if not checks else [f"paused: {text[:160]}"]
        if route not in ("data", "knowledge"):
            return [f"route={route}: {text[:160]}"]
        f = [] if got == want else [f"schemes {got} != {want}"]
        return f + check_list(text, checks)
    if route != "data":
        return [f"no data answer: route={route}: {text[:200]}"]
    return check_list(text, checks, t["total"], extra.get("ties_at"))


# ── driver: the router path, no persistence ─────────────────────────────────
class Driver:
    async def start(self):
        from app.config import settings
        settings.PIPELINE_GRAPH_CHECKPOINTER_DSN = "memory"
        from app import db
        self._writes = 0

        async def refuse(sql, *a, **k):
            self._writes += 1
            raise RuntimeError("UAT runner: DB writes are disabled (read-only run)")
        for mod in [m for name, m in list(sys.modules.items()) if name.startswith("app") and m is not None]:
            for attr in ("execute", "execute_script"):
                if getattr(mod, attr, None) in (db.execute, db.execute_script):
                    setattr(mod, attr, refuse)
        db.execute, db.execute_script = refuse, refuse
        from app.db import init_pool
        from app.llm import init_client
        from app.vectorstore import init_qdrant
        from app.annotations import load_all as load_annotations
        from app.entity_resolver import load_all as load_entity_resolver, load_village_names
        from app import spelling, schema_introspect, metric_catalog, pipeline, data_facts
        await init_pool()
        await init_client()
        try:
            await init_qdrant()
        except Exception:  # noqa: BLE001
            pass
        load_annotations()
        load_entity_resolver()
        await load_village_names()
        spelling.warm()
        for fn in (schema_introspect.load, metric_catalog.load, pipeline.refresh_scheme_years, data_facts.refresh):
            try:
                await fn()
            except Exception as e:  # noqa: BLE001
                print("startup step failed:", fn.__name__, e, flush=True)
        from app.session_store import SessionStore
        self.store = SessionStore(ttl=3600, max_sessions=5000, max_turns=50)

    async def ask(self, session, say):
        from app import conversation_layer, conversation_replies, pipeline
        from app.routers import query as router
        session.turn_context = {}
        try:
            layer = await conversation_layer.prepare_turn(session, say)
            if layer.response is not None:
                result = layer.response
            elif layer.multi:
                result = await conversation_layer.answer_many(
                    layer.multi, lambda x: pipeline.answer_question(x, session=session, scope=None))
            else:
                result = await pipeline.answer_question(layer.question, session=session, scope=None)
            styled = conversation_replies.restyle(session, say, result)
            if styled is not None:
                result = styled
            session.turns.append(router.build_turn(say, result))
            if result.get("route") == "clarification" or result.get("needs_clarification"):
                clar = result.get("clarification") or {}
                opts = [o for o in clar.get("options") or [] if isinstance(o, dict)]
                return {"route": "pause", "answer": result.get("answer") or result.get("question") or "", "opts": opts}, result
            return {"route": result.get("route") or "error", "answer": result.get("answer") or "", "opts": []}, result
        except pipeline.ClarificationNeeded as e:
            router.remember_pause(session, router.pause_question(session, say), e)
            return {"route": "pause", "answer": e.question, "opts": [o for o in (e.options or []) if isinstance(o, dict)]}, None
        except Exception as e:  # noqa: BLE001
            return {"route": "error", "answer": f"{type(e).__name__}: {e}", "opts": []}, None

    def new_session(self):
        sid = "uat-" + uuid.uuid4().hex[:10]
        return self.store.ensure(sid, "uat")


def choose(opts, pick):
    for p in pick:
        parts = [x for x in p.split("&") if x]          # "village&batabari": every part in the label
        c = next((o for o in opts if parts and all(x in norm(o.get("label", "")) for x in parts)), None)
        if c:
            return c
    for want in ("cm elevate applications", "cm elevate", "complete list", "all of them"):
        c = next((o for o in opts if norm(o.get("label", "")).startswith(want) and "legacy" not in norm(o.get("label", ""))), None)
        if c:
            return c
    return None


async def one_turn(drv, session, say, pick):
    rec, raw = await drv.ask(session, say)
    turns = [f"[{rec['route']}] {rec['answer']}"]
    for _ in range(2):
        if rec["route"] != "pause":
            break
        c = choose(rec["opts"], pick)
        if not c:
            break
        rec, raw = await drv.ask(session, c.get("question") or c.get("label"))
        turns.append(f"tap '{c.get('label')}' -> [{rec['route']}] {rec['answer']}")
    return rec, raw, turns


TRANSIENT = re.compile(r"DatabaseUnavailable|connection|timeout|timed out|Gateway|502|503|504|ReadError|"
                       r"RemoteProtocol|too many connections|ConnectError|APIConnection|RateLimit", re.I)


async def run_test(drv, t):
    pick = json.loads(t["pick"])
    t0 = time.perf_counter()
    for attempt in range(1, 4):
        if t["kind"] == "sql":
            ok = json.loads(t["extra"])["ok"]
            return {"status": "Pass" if ok else "Fail", "fails": "" if ok else t["truth_sql"], "actual": "n/a (SQL check)",
                    "route": "sql", "sql": "", "attempts": 1, "secs": 0}
        if t["kind"] == "chain":
            session = drv.new_session()
            out, fails, route, sql = [], [], "data", ""
            for k, turn in enumerate(json.loads(t["question"])):
                rec, raw, turns = await one_turn(drv, session, turn["say"], pick)
                out.append(f"T{k+1}: " + " | ".join(turns))
                route = rec["route"] if rec["route"] != "data" else route
                sql = (raw or {}).get("sql_query") or sql
                if rec["route"] != "data":
                    fails.append(f"T{k+1} no data answer ({rec['route']})")
                else:
                    fails += [f"T{k+1} {f}" for f in check_list(rec["answer"], turn["checks"])]
                if rec["route"] == "error":
                    break
            status = "Pass" if not fails else ("Error" if any("error" in f for f in fails) else "Fail")
            res = {"status": status, "fails": "; ".join(fails), "actual": "\n".join(out), "route": route, "sql": sql}
        else:
            rec, raw, turns = await one_turn(drv, drv.new_session(), t["question"], pick)
            fails = judge(t, rec, raw)
            status = "Pass" if not fails else "Fail"
            if rec["route"] == "error" or (fails and TRANSIENT.search(rec["answer"] or "")
                                           and rec["route"] in ("error", "data") and "couldn't build" not in (rec["answer"] or "")):
                status = "Error"
            res = {"status": status, "fails": "; ".join(fails), "actual": " => ".join(turns)[:4000],
                   "route": rec["route"], "sql": ((raw or {}).get("sql_query") or "")[:2000]}
        if res["status"] != "Error":
            break
        await asyncio.sleep(3 * attempt)
    res["attempts"] = attempt
    res["secs"] = round(time.perf_counter() - t0, 1)
    return res


def latest_results():
    last = {}
    if os.path.exists(RESULTS):
        with open(RESULTS, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                last[r["id"]] = r
    return last


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--only", default="")
    ap.add_argument("--ids-file", default="")
    ap.add_argument("--rerun-failed", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--run", default=time.strftime("run-%H%M"))
    args = ap.parse_args()
    with open(os.path.join(HERE, "test_matrix.csv"), newline="", encoding="utf-8") as fh:
        matrix = list(csv.DictReader(fh))
    last = latest_results()
    todo = []
    for t in matrix:
        prev = last.get(t["id"])
        if args.all:
            todo.append(t)
        elif prev is None or prev["status"] == "Error" or (args.rerun_failed and prev["status"] == "Fail"):
            todo.append(t)
    if args.only:
        keys = args.only.split(",")
        todo = [t for t in todo if any(t["id"].startswith(k) or t["category"].startswith(k) for k in keys)]
    if args.ids_file:
        want = set(open(args.ids_file, encoding="utf-8").read().split())
        todo = [t for t in todo if t["id"] in want]
    todo.sort(key=lambda t: ORDER.index(t["category"][:3]) if t["category"][:3] in ORDER else 99)
    print(f"{len(todo)} to run of {len(matrix)} ({args.run})", flush=True)
    drv = Driver()
    await drv.start()
    new = not os.path.exists(RESULTS)
    fh = open(RESULTS, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new:
        w.writeheader()
    lock = asyncio.Lock()
    stats = {"done": 0, "Pass": 0, "Fail": 0, "Error": 0}
    sem = asyncio.Semaphore(args.workers)
    errors = []

    async def go(t):
        async with sem:
            try:
                res = await run_test(drv, t)
            except Exception as e:  # noqa: BLE001
                res = {"status": "Error", "fails": f"{type(e).__name__}: {e}", "actual": "", "route": "error", "sql": "",
                       "attempts": 1, "secs": 0}
        async with lock:
            w.writerow({"id": t["id"], "category": t["category"], "tc": t["tc"], "level": t["level"],
                        "question": t["question"], "expected": t["checks"] + " | " + t["truth_sql"] + (f" | total {t['total']}" if t["total"] else ""),
                        "actual": res["actual"], "route": res["route"], "sql": res["sql"], "status": res["status"],
                        "fails": res["fails"], "secs": res["secs"], "attempts": res["attempts"], "run": args.run,
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            fh.flush()
            stats["done"] += 1
            stats[res["status"]] += 1
            if res["status"] == "Error":
                errors.append(t)
            if res["status"] != "Pass":
                print(f"{res['status']} {t['id']} {res['fails'][:200]}", flush=True)
            if stats["done"] % 100 == 0 or stats["done"] == len(todo):
                line = (f"{time.strftime('%H:%M:%S')} {args.run} done {stats['done']}/{len(todo)} pass {stats['Pass']} "
                        f"fail {stats['Fail']} error {stats['Error']} db_write_attempts {drv._writes}")
                with open(PROGRESS, "a", encoding="utf-8") as p:
                    p.write(line + "\n")
                print(line, flush=True)

    await asyncio.gather(*(go(t) for t in todo))
    if errors:                                   # errors once more, at the end
        print(f"re-running {len(errors)} errors", flush=True)
        retry, errors[:] = list(errors), []
        await asyncio.gather(*(go(t) for t in retry))
    fh.close()
    print("finished", stats, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
