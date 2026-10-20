"""
LIVE context-memory matrix: every flow of documents/MAIN_Contex.pdf (forward,
measure follow-up, out of scope, knowledge digression, backward by content,
backward by order, topic switch and back) for EVERY scheme, on the real model
gateway and megh_db (needs the VPN). Built 2026-10-18 for the user's "it has to
work 100%" request (D-050 / D-051).

Each conversation runs through tests/live_context_validation.py's
Conversation: the router's own conversation layer, refusal restyle, caches
check and pause handling, rotated across THREE simulated workers that share
state only through the real Postgres snapshot. A turn's expectation says
which scheme it must answer for, which place and year must be in the SQL,
which must not, or that it must be an out-of-scope reply with no query.

    .venv/Scripts/python.exe tests/live_context_matrix.py
    .venv/Scripts/python.exe tests/live_context_matrix.py --only MGNREGA,PMAY-G --flows F1,F5
    .venv/Scripts/python.exe tests/live_context_matrix.py --out logs/live_ctx_matrix.json

Exit code: 0 all passed, 1 a check failed, 3 not run (gateway or DB unreachable).
"""
import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402
from live_context_validation import Conversation, _PromptCapture, _reachable, _write  # noqa: E402

# Per scheme: the opening question, two places and two years it holds, a second
# measure, and the words its data turns use. Years are financial-year starts
# (2023 = FY 2023-24). CM Elevate applications carry no year (v_data_coverage).
SCHEMES = {
    "MGNREGA": dict(
        q1="How many person-days were generated under MGNREGA in East Khasi Hills in FY 2023-24?",
        d1="EAST KHASI HILLS", d2="WEST GARO HILLS", y1=2023, y2=2024, m2="job cards"),
    "PMAY-G": dict(
        q1="How many PMAY-G houses were sanctioned in Ri Bhoi in FY 2022-23?",
        d1="RI BHOI", d2="SOUTH GARO HILLS", y1=2022, y2=2021, m2="houses completed"),
    "Focus Plus": dict(
        q1="How much was disbursed under Focus Plus in West Garo Hills in FY 2025-26?",
        d1="WEST GARO HILLS", d2="EAST KHASI HILLS", y1=2025, y2=2022, m2="beneficiaries"),
    "Focus Legacy": dict(
        q1="How much was paid under Focus Legacy in East Garo Hills in FY 2024-25?",
        d1="EAST GARO HILLS", d2="WEST KHASI HILLS", y1=2024, y2=2022, m2="producer groups"),
    # User decision 2026-10-12: a bare "CM Elevate" data question goes to CM
    # Elevate Legacy unless it uses applications-ONLY words (applicants,
    # pending, status, on hold …) — so this scheme's questions use them.
    "CM Elevate": dict(
        q1="How many CM Elevate applicants are there in Ri Bhoi?",
        d1="RI BHOI", d2="WEST GARO HILLS", y1=None, y2=None, m2="pending applicants"),
    "CM Elevate Legacy": dict(
        q1="How much was disbursed under CM Elevate Legacy in West Khasi Hills in FY 2024-25?",
        d1="WEST KHASI HILLS", d2="RI BHOI", y1=2024, y2=2025, m2="beneficiaries"),
}
# A question about another scheme, for the backward / switch flows.
OTHER = {"MGNREGA": "How many PMAY-G houses were completed in FY 2023-24?",
         "PMAY-G": "How many person-days were generated under MGNREGA in FY 2024-25?",
         "Focus Plus": "How many PMAY-G houses were completed in FY 2023-24?",
         "Focus Legacy": "How many person-days were generated under MGNREGA in FY 2024-25?",
         "CM Elevate": "How many PMAY-G houses were completed in FY 2023-24?",
         "CM Elevate Legacy": "How many person-days were generated under MGNREGA in FY 2024-25?"}


def fy(y):
    return f"FY {y}-{str(y + 1)[-2:]}"


def title(place):
    return place.title()


def flows(name, s):
    """(flow id, label, [(question, expectation)]) for one scheme."""
    d1, d2, y1, y2, m2 = s["d1"], s["d2"], s["y1"], s["y2"], s["m2"]
    keep = dict(scheme=name)
    out = [
        ("F1", "forward: place, then year, then measure",
         [(s["q1"], dict(keep, has=[d1], year=y1)),
          (f"What about {title(d2)}?", dict(keep, has=[d2], not_has=[d1], year=y1))]
         + ([(f"And in {fy(y2)}?", dict(keep, has=[d2], year=y2, not_year=y1))] if y2 else [])
         + [(f"How many {m2}?", dict(keep, has=[d2], year=y2 or None))]),
        ("F2", "forward: 'what is the total …' keeps the scope",
         [(s["q1"], dict(keep, has=[d1], year=y1)),
          (f"What is the total {m2}?", dict(keep, has=[d1], year=y1))]),
        ("F3", "out of scope in the middle",
         [(s["q1"], dict(keep, has=[d1], year=y1)),
          ("Who won the cricket match yesterday?", dict(edge=True)),
          (f"What about {title(d2)}?", dict(keep, has=[d2], year=y1))]),
        ("F4", "knowledge digression, then back to the figure",
         [(s["q1"], dict(keep, has=[d1], year=y1)),
          (f"Who is eligible for {name}?", dict(knowledge=True)),
          (f"And in {title(d2)}?", dict(keep, has=[d2], year=y1))]),
        ("F5", "backward by content",
         [(s["q1"], dict(keep, has=[d1], year=y1)),
          (OTHER[name], dict(other=True)),
          (f"Go back to the {title(d1)} one", dict(keep, has=[d1], year=y1))]),
        ("F6", "backward by order, with a new place",
         [(s["q1"], dict(keep, has=[d1], year=y1)),
          (OTHER[name], dict(other=True)),
          (f"Go back to the first question, what about {title(d2)}?", dict(keep, has=[d2], year=y1))]),
        ("F7", "topic switch by name and back",
         [(s["q1"], dict(keep, has=[d1], year=y1)),
          (OTHER[name], dict(other=True)),
          (f"Go back to {name}", dict(ack=True)),
          (f"What about {title(d2)}?", dict(keep, has=[d2], year=y1))]),
    ]
    return out


def _sql(t):
    return (t.get("sql") or "").upper()


def judge(t, exp):
    """[(check, ok, detail)] for one turn."""
    res, ans = [], (t.get("answer") or "")
    sql = _sql(t)
    first = t["chain"][0]
    if exp.get("edge"):
        res.append(("out-of-scope reply, no query", t.get("route") == "edge" and not t.get("sql"),
                    [t.get("route"), ans[:100]]))
        return res
    if exp.get("knowledge"):
        res.append(("answered from the scheme documents", t.get("route") in ("knowledge", "edge"),
                    [t.get("route"), ans[:100]]))
        return res
    if exp.get("ack"):
        res.append(("topic restored (acknowledged or answered)", t.get("route") in ("edge", "data"),
                    [t.get("route"), ans[:100]]))
        return res
    if exp.get("other"):
        res.append(("the other scheme's question answered", t.get("route") == "data" and bool(t.get("schemes")),
                    [t.get("route"), t.get("schemes"), first.get("rule")]))
        return res
    scheme = exp["scheme"]
    res.append((f"answers for {scheme} only", t.get("schemes") == [scheme],
                [t.get("final_kind"), t.get("schemes"), first.get("rule"), ans[:120]]))
    for needle in exp.get("has", []):
        res.append((f"filters {needle}", needle in sql, sql[:240]))
    for needle in exp.get("not_has", []):
        res.append((f"does not filter {needle}", needle not in sql, sql[:240]))
    if exp.get("year"):
        y = exp["year"]
        res.append((f"keeps {fy(y)}", str(y) in sql or fy(y) in ans, [sql[:200], ans[:100]]))
    if exp.get("not_year"):
        y = exp["not_year"]
        res.append((f"not {fy(y)}", f"= {y}" not in sql and f"YEAR_KEY = {y}" not in sql, sql[:200]))
    return res


async def main(args) -> int:
    gw_ok = _reachable(settings.SQL_GENERATION_BASE_URL)
    _db = urlparse(settings.DATABASE_URL) if settings.DATABASE_URL else None
    db_ok = bool(_db and _db.hostname) and _reachable(_db.hostname, _db.port or 5432)
    if not (gw_ok and db_ok):
        print(f"SKIPPED - unreachable: gateway={gw_ok} db={db_ok} (VPN off?)")
        return 3
    capture = _PromptCapture()
    logging.getLogger("app.context_budget").addHandler(capture)
    logging.getLogger("app.context_budget").setLevel(logging.INFO)
    only = [x.strip() for x in args.only.split(",")] if args.only else list(SCHEMES)
    only_flows = {x.strip().upper() for x in args.flows.split(",")} if args.flows else None
    from app import db, main as app_main
    sids, report, total, passed = [], {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": []}, 0, 0
    async with app_main.lifespan(app_main.app):
        try:
            for name in only:
                for fid, label, turns in flows(name, SCHEMES[name]):
                    if only_flows and fid not in only_flows:
                        continue
                    sid = f"live-ctx-mx-{uuid.uuid4().hex[:10]}"
                    sids.append(sid)
                    conv = Conversation(sid, 3, True, args.tenant_id)
                    run = {"scheme": name, "flow": fid, "label": label, "turns": []}
                    ok_all = True
                    for i, (q, exp) in enumerate(turns, 1):
                        # A dropped DB / gateway connection (the VPN flaps; CLAUDE.md §9)
                        # fails this conversation, not the whole run: retried once after
                        # a pause, then recorded and the next conversation goes on.
                        try:
                            t = await conv.ask(q, capture, auto_click=True)
                        except Exception as e:  # noqa: BLE001
                            print(f"      (retrying T{i} after: {type(e).__name__}: {str(e)[:80]})")
                            await asyncio.sleep(5)
                            try:
                                t = await conv.ask(q, capture, auto_click=True)
                            except Exception as e2:  # noqa: BLE001
                                t = {"answer": f"ERROR {type(e2).__name__}: {e2}", "chain": [{}], "route": None,
                                     "sql": None, "schemes": None, "scope_banner": None, "rewritten": None,
                                     "final_kind": "error"}
                        checks = judge(t, exp)
                        ok = all(c[1] for c in checks)
                        ok_all &= ok
                        total += len(checks)
                        passed += sum(c[1] for c in checks)
                        run["turns"].append({"q": q, "answer": (t.get("answer") or "")[:300], "sql": t.get("sql"),
                                             "schemes": t.get("schemes"), "route": t.get("route"),
                                             "banner": t.get("scope_banner"), "rewritten": t.get("rewritten"),
                                             "chain": [{k: s.get(k) for k in ("kind", "rule", "auto_clicked", "asked")}
                                                       for s in t["chain"]],
                                             "checks": [{"check": c[0], "ok": c[1], "detail": str(c[2])[:300]}
                                                        for c in checks]})
                    run["ok"] = ok_all
                    report["runs"].append(run)
                    print(f"{'PASS' if ok_all else 'FAIL'}  {name:18} {fid} {label}")
                    if not ok_all:
                        for i, tr in enumerate(run["turns"], 1):
                            for c in tr["checks"]:
                                if not c["ok"]:
                                    print(f"        T{i} {tr['q'][:60]!r}: {c['check']} :: {c['detail'][:200]}")
                    _write(args.out, report)
        finally:
            if sids:
                try:
                    await db.execute("DELETE FROM app.conversations WHERE session_id = ANY($1::text[])", [sids])
                except Exception as e:  # noqa: BLE001
                    print(f"cleanup failed: {e}")
    runs_ok = sum(r["ok"] for r in report["runs"])
    report.update(conversations_passed=runs_ok, conversations=len(report["runs"]),
                  checks_passed=passed, checks_total=total)
    _write(args.out, report)
    print(f"\nCONVERSATIONS {runs_ok}/{len(report['runs'])}   CHECKS {passed}/{total}")
    return 0 if runs_ok == len(report["runs"]) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated scheme names")
    ap.add_argument("--flows", help="comma-separated flow ids (F1..F7)")
    ap.add_argument("--out", default="logs/live_context_matrix.json")
    ap.add_argument("--tenant-id", type=int, default=1)
    sys.exit(asyncio.run(main(ap.parse_args())))
