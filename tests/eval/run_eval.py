"""Evaluation harness — plays tests/eval/cases.yaml through the real pipeline
and scores it. The score every pipeline change is compared against (see
CLAUDE.md "Project rules").

    python tests/eval/run_eval.py                      # full run, default flags
    python tests/eval/run_eval.py --label baseline     # also writes results/baseline.json
    python tests/eval/run_eval.py --compare tests/eval/results/baseline.json
    python tests/eval/run_eval.py --filter pmay- --concurrency 2
    python tests/eval/run_eval.py --flags-on           # PIPELINE_GRAPH + LANGGRAPH_FOLLOWUP + RLS

LIVE: this calls the real Qwen gateway and the real megh_db (read-only
curated queries), exactly like the running service. Nothing is mocked.

How a case is played. Each case is one conversation. Its scripted turns are
sent in order to POST /api/query in-process (FastAPI app + real startup), so
every turn goes through answer_question() AND the router's clarification
pause/resume, turn recording and context-state handling — the same path a
browser takes. Calling answer_question() bare would skip the router's
pending-question stash, i.e. the very resume behaviour under test.

After the last scripted turn of a workbook / messy case, if the bot asks a
clarification the harness answers like a user would: it taps the one-tap
option that best fits the case (the case's own scheme, else "all of
Meghalaya" / "all years" / "all tranches"), or types "all of Meghalaya, all
years" when no options are offered — up to 3 rounds. Audit-log conversations
replay the real user's own turns and never auto-answer.

Scoring (per case):
  kind=answer   pass if expect.figures[0] (the headline figure) appears in the
                final answer text or result rows (unit-normalised, see
                scoring.py). No figures => unscored.
  kind=clarify  pass if the scored turn asked a clarification, or — when the
                workbook names a default — answered it with rows > 0.
  audit_log     unscored until a human fills in expect (needs_expected_answer).
Totals: accuracy (pass / scored), clarification rate (cases where the bot
asked at least once), zero-row rate (final data answers with 0 rows).

Isolation: the eval identity is a synthetic admin ("eval-harness", tenant 1).
Its turns are NOT written to app.conversations / app.query_audit / the
conversation-memory table, and the JSONL audit mirror goes to
results/<run>_audit.jsonl instead of logs/query_audit.jsonl. Caches are off,
so a rerun after a code change never serves a stale answer. Pass --persist to
keep the normal durable writes.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = Path(__file__).resolve().parent
RESULTS = EVAL / "results"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVAL))

SCHEME_ALIASES = {
    "MGNREGA": ["mgnrega", "nrega"],
    "PMAY-G": ["pmay"],
    "Focus Plus": ["focus"],
    "CM Elevate": ["cm elevate", "elevate"],
}
GENERIC_PREFS = ["all of meghalaya", "statewide", "state-wide", "whole state", "all districts",
                 "all years", "all financial years", "all tranches", "cumulative", "overall",
                 "total"]
FREE_TEXT_REPLY = "all of Meghalaya, all years"
MAX_AUTO_REPLIES = 3


def _args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cases", default=str(EVAL / "cases.yaml"))
    ap.add_argument("--filter", help="only case ids containing this substring")
    ap.add_argument("--source", help="comma list: kpi_workbook,messy_variant,audit_log")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--flags-on", action="store_true",
                    help="PIPELINE_GRAPH_ENABLED + LANGGRAPH_FOLLOWUP_ENABLED + TENANT_SCHEME_RLS_ENABLED")
    ap.add_argument("--label", default="", help="suffix for the result file; 'baseline' also writes results/baseline.json")
    ap.add_argument("--compare", help="a previous results JSON to diff against")
    ap.add_argument("--persist", action="store_true", help="keep durable conversation/audit writes")
    ap.add_argument("--frame-gates", action="store_true",
                    help="FRAME_GATES_ENABLED=true: the QueryFrame drives the clarification gates "
                         "(app/nlu/clarify_rules.py); the frame is recorded on every turn too")
    ap.add_argument("--understand-shadow", action="store_true",
                    help="UNDERSTAND_SHADOW=true: record the shadow QueryFrame on every turn "
                         "(then run tests/eval/frame_agreement.py on the result)")
    ap.add_argument("--rescore", metavar="RESULTS_JSON",
                    help="re-score a saved run against the current cases.yaml (no live calls)")
    return ap.parse_args()


ARGS = _args()
RUN_ID = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S") + (f"_{ARGS.label}" if ARGS.label else "")
RESULTS.mkdir(exist_ok=True)

# Settings are read at import time — set everything before importing app.*.
os.environ["RESPONSE_CACHE_ENABLED"] = "false"
os.environ["SEMANTIC_CACHE_ENABLED"] = "false"
os.environ["REDIS_URL"] = ""
if not ARGS.persist:
    os.environ["AUDIT_FILE"] = str(RESULTS / f"{RUN_ID}_audit.jsonl")
if ARGS.understand_shadow:
    os.environ["UNDERSTAND_SHADOW"] = "true"
if ARGS.frame_gates:
    os.environ["FRAME_GATES_ENABLED"] = "true"
if ARGS.flags_on:
    for k in ("PIPELINE_GRAPH_ENABLED", "LANGGRAPH_FOLLOWUP_ENABLED", "TENANT_SCHEME_RLS_ENABLED"):
        os.environ[k] = "true"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import logging  # noqa: E402

import httpx  # noqa: E402
import yaml  # noqa: E402

from app.api import deps  # noqa: E402
from app.api.middleware import rate_limit  # noqa: E402
from app.core import auth  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.conversation import conversation_memory, conversation_store  # noqa: E402
from app.conversation.session_store import session_store  # noqa: E402
from app.main import app  # noqa: E402
from scoring import figure_found  # noqa: E402

logging.getLogger().setLevel(logging.ERROR)
for name in ("app", "nlp_service", "httpx", "uvicorn"):
    logging.getLogger(name).setLevel(logging.ERROR)

_EVAL_SCOPE = auth.UserScope(
    user_id="eval-harness", role="admin", granularity_cap="village",
    schemes=list(SCHEME_ALIASES), geographies="all", tenant_id=1,
    # _identity requires a db user under AUTH_ENABLED; 0 is never a real row
    # and nothing durable is written with it unless --persist.
    db_user_id=0, username="eval-harness",
)


async def _current_scope_override():
    return _EVAL_SCOPE

app.dependency_overrides[deps.current_scope] = _current_scope_override

# The service's per-IP limiter (30 /api/query per 60 s) would reject the
# harness's own traffic — every in-process request comes from one "IP".
# Lift the /api/query cap for this process only; login limits untouched.
rate_limit._RULES[:] = [(p, 10**9 if p == "/api/query" else cap, w, k)
                        for p, cap, w, k in rate_limit._RULES]
_RATE_LIMITED = 0


def _isolate():
    """Keep eval turns out of the durable conversation/audit/memory stores."""
    async def _no_state(*_a, **_k):
        return {}
    conversation_store.persist_turn = lambda **_k: None
    conversation_store.save_context_state = lambda **_k: None
    conversation_store.load_context_state = _no_state
    conversation_memory.index_turn = lambda **_k: None


def _session_id(case_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._:-]", "-", f"eval-{RUN_ID}-{case_id}")[:128]


def _choice_of(o: dict) -> "dict | None":
    """The {slot, value} a chip sends alongside its text (web/ai_query.html)."""
    return {"slot": o["slot"], "value": o.get("value")} if o.get("slot") else None


def _choose_reply(case: dict, clar: dict) -> tuple[str, str, "dict | None"]:
    """(text to send, what was chosen, chip {slot, value}) — how a user would
    answer the pause."""
    opts = [o for o in (clar.get("options") or []) if isinstance(o, dict) and o.get("question")]
    if not opts:
        return FREE_TEXT_REPLY, "free-text default", None
    aliases = SCHEME_ALIASES.get(case.get("scheme") or "", [])
    best, best_score = opts[0], -1
    for o in opts:
        hay = f"{o.get('label', '')} {o.get('question', '')}".lower()
        score = 10 * any(a in hay for a in aliases) + sum(5 for p in GENERIC_PREFS if p in hay)
        if score > best_score:
            best, best_score = o, score
    return best["question"], f"option: {best.get('label') or best['question'][:60]}", _choice_of(best)


async def _post(client: httpx.AsyncClient, text: str, sid: str,
                choice: "dict | None" = None) -> tuple[int, dict, float]:
    payload = {"question": text, "session_id": sid, **(choice or {})}
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            r = await client.post("/api/query", json=payload)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            status = r.status_code
        except Exception as e:  # noqa: BLE001
            status, body = 599, {"detail": f"{type(e).__name__}: {e}"}
        ms = (time.monotonic() - t0) * 1000
        if status in (503, 429) and attempt == 0:
            await asyncio.sleep(35 if status == 429 else 5)
            continue
        if status == 429:
            global _RATE_LIMITED
            _RATE_LIMITED += 1
            if _RATE_LIMITED >= 5:
                raise SystemExit("aborting: repeated HTTP 429 — a rate limiter is rejecting eval traffic")
        return status, body, ms
    return status, body, ms


def _shadow_frame(sid: str, say: str) -> "dict | None":
    """The shadow QueryFrame the pipeline stored for this exact message."""
    shadow = getattr(session_store.get(sid), "understand_frame", None)
    return {k: v for k, v in shadow.items() if k != "question"}         if shadow and shadow.get("question") == say else None


def _turn_record(say: str, status: int, body: dict, ms: float, auto: str | None,
                 frame: "dict | None" = None) -> dict:
    clar = body.get("clarification") or {}
    rows = body.get("data") or body.get("rows") or []
    return {
        "say": say, "auto_reply": auto, "http": status, "latency_ms": round(ms),
        "route": body.get("route") if status == 200 else "error",
        "schemes": body.get("schemes") or [],
        "rewritten_question": body.get("rewritten_question"),
        "clarification_rule": clar.get("rule") if body.get("route") == "clarification" else None,
        "clarification_question": body.get("question") if body.get("route") == "clarification" else None,
        "clarification_options": [o.get("label") or o.get("question") for o in (clar.get("options") or [])
                                  if isinstance(o, dict)],
        "row_count": body.get("row_count"),
        "answer": (body.get("answer") or body.get("detail") or "")[:1500],
        "sql": body.get("sql"),
        "resolved_entities": body.get("resolved_entities") or {},
        "assumptions": body.get("assumptions"),
        "gate_trace": body.get("gate_trace"),
        "_rows": rows[:200],
        "_options_full": [o for o in (clar.get("options") or []) if isinstance(o, dict)]
        + [o for o in (body.get("correction_options") or []) if isinstance(o, dict)],
        "correction_options": [o.get("label") for o in (body.get("correction_options") or [])],
        **({"understand": frame} if frame is not None else {}),
    }


def _score(case: dict, turns: list[dict]) -> dict:
    exp = case.get("expect") or {}
    final = turns[-1]
    asked = [t for t in turns if t["route"] == "clarification"]
    out = {"clarification_asked": bool(asked),
           "clarification_rules": [t["clarification_rule"] for t in asked]}
    if any(t["http"] != 200 for t in turns):
        bad = next(t for t in turns if t["http"] != 200)
        out.update(status="error", reason=f"HTTP {bad['http']}: {bad['answer'][:120]}")
        return out
    if case.get("needs_expected_answer"):
        out.update(status="unscored", reason="needs expected answer")
        return out
    if exp.get("kind") == "resolved":
        want = {k: v for k, v in exp.items() if k not in ("kind", "schemes")}
        got = final.get("resolved_entities") or {}
        def _same(v, g):
            if isinstance(v, list):
                return sorted(str(x).upper() for x in v) == sorted(str(x).upper() for x in (g or []))
            return str(g if g is not None else "").upper() == str(v).upper()
        bad = {k: (v, got.get(k)) for k, v in want.items() if not _same(v, got.get(k))}
        if exp.get("schemes") and sorted(final.get("schemes") or []) != sorted(exp["schemes"]):
            bad["schemes"] = (exp["schemes"], final.get("schemes"))
        if final["route"] == "data" and final["row_count"] and not bad:
            out.update(status="pass", reason=f"resolved {want} for {exp.get('schemes')}")
        else:
            out.update(status="fail", reason=f"route={final['route']} rows={final['row_count']} mismatch={bad}"[:200])
        return out
    if exp.get("kind") == "clarify":
        idx = exp.get("scored_turn", len(case["turns"]) - 1)
        scored = [t for t in turns if not t["auto_reply"]][idx]
        if scored["route"] == "clarification":
            out.update(status="pass", reason=f"asked ({scored['clarification_rule']})")
        elif exp.get("accept_default") and scored["route"] == "data" and (scored["row_count"] or 0) > 0:
            out.update(status="pass", reason="answered with a default")
        else:
            out.update(status="fail", reason=f"expected a clarification, got route={scored['route']}"
                       f" rows={scored['row_count']}")
        return out
    figs = exp.get("figures") or []
    if not figs:
        out.update(status="unscored", reason=exp.get("unscored_reason") or "no expected figure")
        return out
    for f in figs:
        f.setdefault("base", f["value"] if f["pct"] else f["value"] * {"crore": 1e7, "cr": 1e7, "lakh": 1e5,
                                                                       "l": 1e5, "k": 1e3, "thousand": 1e3}
                     .get(f["unit"], 1.0))
    rows = final.get("_rows", final.get("rows")) or []
    # Ignore the deterministic "Understood as" / "Assumed" preamble (Step 8):
    # its numbers ("12 districts", "FY 2025-26") are not the answer and must
    # not score a figure match.
    answer = "\n".join(ln for ln in (final["answer"] or "").split("\n")
                       if not ln.startswith(("_Understood as:", "_Assumed:")))
    where = figure_found(figs[0], answer, rows)
    found = sum(1 for f in figs if figure_found(f, answer, rows))
    out["figure_recall"] = round(found / len(figs), 3)
    if where:
        out.update(status="pass", reason=f"headline figure {figs[0]['text']!r} found in {where}")
    elif final["route"] == "clarification":
        out.update(status="fail", reason=f"still clarifying after {MAX_AUTO_REPLIES} replies ({final['clarification_rule']})")
    elif final["route"] == "data" and not final["row_count"]:
        out.update(status="fail", reason="zero rows")
    else:
        out.update(status="fail", reason=f"headline figure {figs[0]['text']!r} not found (route={final['route']})")
    return out


async def run_case(client, case, sem) -> dict:
    async with sem:
        sid = _session_id(case["id"])
        turns = []
        for step in case["turns"]:
            choice, why = None, None
            if isinstance(step, dict) and step.get("click"):
                # Tap the option of the previous reply whose label starts with
                # the given text — clarification options first, then the
                # "Change area" correction chips — sending its {slot, value}.
                prev = turns[-1]["_options_full"] if turns else []
                o = next((o for o in prev if str(o.get("label", "")).casefold()
                          .startswith(str(step["click"]).casefold())), None)
                if o is None:
                    turns.append({**_turn_record(f"[click {step['click']}]", 200, {}, 0, "click"),
                                  "route": "error", "http": 200,
                                  "answer": f"no option starting with {step['click']!r} to click"})
                    break
                say, choice, why = o["question"], _choice_of(o), f"click: {o.get('label')}"
            else:
                say = step if isinstance(step, str) else str(step.get("say", ""))
            status, body, ms = await _post(client, say, sid, choice)
            turns.append(_turn_record(say, status, body, ms, why, _shadow_frame(sid, say)))
            if status != 200:
                break
        auto_ok = (case.get("source") != "audit_log" and (case.get("expect") or {}).get("kind") == "answer")
        rounds = 0
        while auto_ok and turns[-1]["http"] == 200 and turns[-1]["route"] == "clarification" \
                and rounds < MAX_AUTO_REPLIES:
            clar = {"options": turns[-1]["_options_full"], "rule": turns[-1]["clarification_rule"]}
            text, why, choice = _choose_reply(case, clar)
            status, body, ms = await _post(client, text, sid, choice)
            turns.append(_turn_record(text, status, body, ms, why, _shadow_frame(sid, text)))
            rounds += 1
        return {"id": case["id"], "source": case.get("source"), "scheme": case.get("scheme"),
                "style": case.get("style"), **_score(case, turns),
                "final_route": turns[-1]["route"], "final_schemes": turns[-1]["schemes"],
                "final_rows": turns[-1]["row_count"], "turns": turns}


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def summarise(results: list[dict]) -> dict:
    def block(rs):
        scored = [r for r in rs if r["status"] in ("pass", "fail", "error")]
        passed = sum(r["status"] == "pass" for r in scored)
        data_final = [r for r in rs if r["final_route"] == "data"]
        answer_kind = [r for r in rs if r["source"] != "audit_log" and r.get("_kind") == "answer"]
        return {
            "cases": len(rs), "scored": len(scored), "pass": passed,
            "accuracy_pct": _pct(passed, len(scored)),
            "clarification_rate_pct": _pct(sum(r["clarification_asked"] for r in rs), len(rs)),
            "clarification_rate_answer_cases_pct": _pct(sum(r["clarification_asked"] for r in answer_kind),
                                                        len(answer_kind)),
            "zero_row_rate_pct": _pct(sum(1 for r in data_final if not r["final_rows"]), len(data_final)),
            "errors": sum(r["status"] == "error" for r in rs),
            # Data-independent understanding signals (don't depend on the
            # workbook's figures matching the live DB):
            #   answered   = ended on a real answer (data with rows>0, or knowledge)
            #   scheme_ok  = the case's scheme is among the schemes the bot used
            "answered_pct": _pct(sum(1 for r in rs if (r["final_route"] == "data" and r["final_rows"])
                                     or r["final_route"] == "knowledge"), len(rs)),
            "scheme_ok_pct": _pct(sum(1 for r in rs if r["scheme"] and r["scheme"] in (r["final_schemes"] or [])),
                                  sum(1 for r in rs if r["scheme"])),
            "routes": dict(sorted({k: sum(r["final_route"] == k for r in rs)
                                   for k in {r["final_route"] for r in rs}}.items())),
        }
    lat = [t["latency_ms"] for r in results for t in r["turns"]]
    return {
        "total": block(results),
        "by_source": {s: block([r for r in results if r["source"] == s])
                      for s in sorted({r["source"] for r in results})},
        "by_scheme": {s: block([r for r in results if r["scheme"] == s])
                      for s in sorted({r["scheme"] for r in results if r["scheme"]})},
        "latency_ms": {"requests": len(lat), "p50": statistics.median(lat) if lat else None,
                       "p90": sorted(lat)[int(0.9 * (len(lat) - 1))] if lat else None},
    }


def print_summary(summary: dict):
    cols = ["cases", "scored", "pass", "accuracy_pct", "clarification_rate_pct",
            "clarification_rate_answer_cases_pct", "zero_row_rate_pct", "answered_pct",
            "scheme_ok_pct", "errors"]
    heads = ["cases", "scored", "pass", "acc %", "clar %", "clar% ans", "0-row %", "answered %",
             "scheme ok %", "err"]
    rows = [("TOTAL", summary["total"])] + \
           [(f"src:{k}", v) for k, v in summary["by_source"].items()] + \
           [(f"scheme:{k}", v) for k, v in summary["by_scheme"].items()]
    w = max(len(r[0]) for r in rows) + 2
    print("\n" + "".ljust(w) + "".join(h.rjust(13) for h in heads))
    for name, b in rows:
        print(name.ljust(w) + "".join(("-" if b.get(c) is None else str(b[c])).rjust(13) for c in cols))
    lat = summary["latency_ms"]
    print(f"\nrequests={lat['requests']}  latency p50={lat['p50']}ms p90={lat['p90']}ms")
    print(f"final routes: {summary['total']['routes']}")


def compare(prev_path: str, results: list[dict], summary: dict):
    prev = json.loads(Path(prev_path).read_text(encoding="utf-8"))
    pt, ct = prev["summary"]["total"], summary["total"]
    print(f"\n=== vs {Path(prev_path).name} ===")
    for k in ("accuracy_pct", "clarification_rate_pct", "clarification_rate_answer_cases_pct",
              "zero_row_rate_pct", "answered_pct", "scheme_ok_pct", "errors"):
        a, b = pt.get(k), ct.get(k)
        d = "" if a is None or b is None else f"  ({b - a:+.1f})"
        print(f"  {k:38s} {a} -> {b}{d}")
    before = {r["id"]: r["status"] for r in prev["results"]}
    fixed = [r["id"] for r in results if before.get(r["id"]) in ("fail", "error") and r["status"] == "pass"]
    broke = [r["id"] for r in results if before.get(r["id"]) == "pass" and r["status"] in ("fail", "error")]
    print(f"  fail->pass ({len(fixed)}): {', '.join(fixed) or '-'}")
    print(f"  pass->fail ({len(broke)}): {', '.join(broke) or '-'}")


def _git():
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                                    text=True).stdout.strip())
        return {"head": head, "dirty": dirty}
    except Exception:  # noqa: BLE001
        return {}


def rescore(path: str):
    """Re-apply the current cases.yaml expectations to a saved run."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in yaml.safe_load(Path(ARGS.cases).read_text(encoding="utf-8"))["cases"]}
    for r in doc["results"]:
        case = cases.get(r["id"])
        if case is None:
            continue
        for t in r["turns"]:
            t.setdefault("auto_reply", None)
        r.update(_score(case, r["turns"]))
        r["_kind"] = (case.get("expect") or {}).get("kind")
    doc["summary"] = summarise(doc["results"])
    for r in doc["results"]:
        r.pop("_kind", None)
    doc["rescored_at"] = dt.datetime.now().isoformat(timespec="seconds")
    out = RESULTS / f"eval_{RUN_ID}_rescored.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print_summary(doc["summary"])
    if ARGS.compare:
        compare(ARGS.compare, doc["results"], doc["summary"])
    print(f"\nsaved {out.relative_to(ROOT)}")


async def main():
    raw = Path(ARGS.cases).read_bytes()
    cases = yaml.safe_load(raw.decode("utf-8"))["cases"]
    if ARGS.filter:
        cases = [c for c in cases if ARGS.filter in c["id"]]
    if ARGS.source:
        keep = set(ARGS.source.split(","))
        cases = [c for c in cases if c.get("source") in keep]
    if ARGS.limit:
        cases = cases[:ARGS.limit]
    if not ARGS.persist:
        _isolate()

    print(f"eval {RUN_ID}: {len(cases)} cases, concurrency={ARGS.concurrency}, "
          f"flags_on={ARGS.flags_on}, isolated={not ARGS.persist}")
    started = time.monotonic()
    sem = asyncio.Semaphore(ARGS.concurrency)
    results = []
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://eval",
                                     timeout=httpx.Timeout(settings.REQUEST_TIMEOUT_SECONDS + 60)) as client:
            tasks = [asyncio.create_task(run_case(client, c, sem)) for c in cases]
            for i, t in enumerate(asyncio.as_completed(tasks), 1):
                r = await t
                results.append(r)
                print(f"[{i:3d}/{len(cases)}] {r['status']:8s} {r['id']:34s} "
                      f"route={r['final_route']:13s} clar={'Y' if r['clarification_asked'] else '-'} "
                      f"rows={r['final_rows']}  {r.get('reason', '')[:70]}", flush=True)

    kinds = {c["id"]: (c.get("expect") or {}).get("kind") for c in cases}
    for r in results:
        r["_kind"] = kinds.get(r["id"])
    order = {c["id"]: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order[r["id"]])
    summary = summarise(results)
    for r in results:
        r.pop("_kind", None)
        for i, t in enumerate(r["turns"]):
            rows = t.pop("_rows", [])
            t.pop("_options_full", None)
            # Final turn keeps every returned row (<=200) so a later
            # --rescore can re-check figures without re-running live.
            t["rows" if i == len(r["turns"]) - 1 else "rows_preview"] = rows if i == len(r["turns"]) - 1 else rows[:5]

    doc = {
        "run_id": RUN_ID, "finished": dt.datetime.now().isoformat(timespec="seconds"),
        "wall_seconds": round(time.monotonic() - started),
        "git": _git(), "cases_sha256": hashlib.sha256(raw).hexdigest()[:16],
        "flags": {k: getattr(settings, k) for k in ("PIPELINE_GRAPH_ENABLED", "LANGGRAPH_FOLLOWUP_ENABLED",
                                                    "TENANT_SCHEME_RLS_ENABLED", "PIPELINE_GRAPH_CANARY_PERCENT",
                                                    "UNDERSTAND_SHADOW", "ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED",
                                                    "FRAME_GATES_ENABLED")},
        "models": {k: getattr(settings, k) for k in ("CLASSIFIER_MODEL", "SQL_GENERATION_MODEL",
                                                     "RESPONSE_MODEL", "SQL_VERIFY_MODEL", "UNDERSTAND_MODEL")},
        "filters": {"filter": ARGS.filter, "source": ARGS.source, "limit": ARGS.limit},
        "summary": summary, "results": results,
    }
    out = RESULTS / f"eval_{RUN_ID}.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    if ARGS.label == "baseline":
        (RESULTS / "baseline.json").write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    print_summary(summary)
    if ARGS.compare:
        compare(ARGS.compare, results, summary)
    print(f"\nsaved {out.relative_to(ROOT)}" + ("  (+ results/baseline.json)" if ARGS.label == "baseline" else ""))


if __name__ == "__main__":
    if ARGS.rescore:
        rescore(ARGS.rescore)
    else:
        asyncio.run(main())
