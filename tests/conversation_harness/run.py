"""
Run conversation scenarios and report pass / fail per turn.

    .venv/Scripts/python.exe -m tests.conversation_harness.run --driver http [--stream] [--account superadmin]
    .venv/Scripts/python.exe -m tests.conversation_harness.run --driver inprocess --only B_out_of_scope,E_hierarchy
    .venv/Scripts/python.exe -m tests.conversation_harness.run --repeat 3 --only CMP_compare_with_scheme
    .venv/Scripts/python.exe -m tests.conversation_harness.run --validate
    .venv/Scripts/python.exe -m tests.conversation_harness.run --list

Scenario files: tests/conversation_harness/scenarios/*.yaml (README.md explains the
format). A scenario's `account` picks the HTTP user (its permissions matter: a
district-level account is denied block questions). `--account` overrides for all.

Report: logs/conversation_harness/<timestamp>_<label>.json (every turn, answer,
banner, chips, failures) and a table on stdout. Exit 0 all passed, 1 a check failed,
2 a scenario file is invalid, 3 nothing could run (server / DB unreachable).
Run from the repo root (the .env is read relative to it); the DB and gateway need the VPN.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.conversation_harness.checks import check_turn, validate_scenario  # noqa: E402
from tests.conversation_harness.drivers import HttpDriver, InProcessDriver  # noqa: E402


def load_scenarios(only: str = "", tags: str = "") -> list[dict]:
    out = []
    want = {s.strip() for s in only.split(",") if s.strip()}
    want_tags = {s.strip().lower() for s in tags.split(",") if s.strip()}
    for f in sorted((HERE / "scenarios").glob("*.yaml")):
        docs = yaml.safe_load(f.read_text(encoding="utf-8")) or []
        if isinstance(docs, dict):
            docs = [docs]
        for sc in docs:
            sc["_file"] = f.name
            if want and sc.get("name") not in want:
                continue
            if want_tags and not (want_tags & {str(t).lower() for t in (sc.get("tags") or [])}):
                continue
            out.append(sc)
    return out


async def _truth_value(sql: str):
    """The first numeric cell of the first row of a read-only query, or None."""
    from app import db
    try:
        rows = await db.run_readonly(sql)
    except Exception as e:  # noqa: BLE001
        print(f"    truth query failed: {type(e).__name__}: {str(e)[:120]}")
        return None
    for r in rows or []:
        for v in dict(r).values():
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


async def run_scenario(driver, sc: dict, account_override: str | None, truth_ok: bool) -> dict:
    conv = driver.new_conversation(account_override or sc.get("account"))
    records = []
    result = {"name": sc["name"], "file": sc["_file"], "account": account_override or sc.get("account"),
              "doc": sc.get("doc"), "turns": [], "passed": True}
    for i, turn in enumerate(sc["turns"], 1):
        rec = await conv.ask(turn["say"])
        expect = turn.get("expect") or {}
        truth = None
        if "truth" in expect and truth_ok:
            truth = await _truth_value(expect["truth"]["sql"])
        fails = check_turn(expect, rec, records, truth_value=truth)
        records.append(rec)
        result["turns"].append({
            "n": i, "say": turn["say"], "route": rec.route, "edge_type": rec.edge_type, "pause_rule": rec.pause_rule,
            "banner": rec.banner, "answer": rec.answer, "chips": rec.chips, "ms": rec.ms, "status": rec.status,
            "truth": truth, "expect": expect, "fails": fails, "note": turn.get("note"),
            # diagnostics: what the pipeline actually ran (data turns)
            "rewritten": rec.raw.get("rewritten_question"), "sql": rec.raw.get("sql") or rec.raw.get("sql_query"),
            "schemes": rec.raw.get("schemes"), "resolved": rec.raw.get("resolved_entities"),
        })
        if fails:
            result["passed"] = False
    return result


def _print(result: dict) -> None:
    mark = "PASS" if result["passed"] else "FAIL"
    print(f"\n[{mark}] {result['name']}  ({result['file']}, account={result['account']})")
    for t in result["turns"]:
        flag = "ok " if not t["fails"] else "XX "
        head = f"  {flag}{t['n']:>2}. U: {t['say']}"
        print(head)
        ans = (t["answer"] or "").replace("\n", " ")
        print(f"        B[{t['route']}{('/' + (t['edge_type'] or t['pause_rule'])) if (t['edge_type'] or t['pause_rule']) else ''}] "
              f"{ans[:160]}  banner={t['banner']}")
        for f in t["fails"]:
            print(f"        !! {f}")


async def main_async(args) -> int:
    scenarios = load_scenarios(args.only, args.tags)
    problems = {sc["name"]: validate_scenario(sc) for sc in scenarios}
    bad = {k: v for k, v in problems.items() if v}
    if bad:
        for k, v in bad.items():
            print(f"invalid scenario {k}: {v}")
        return 2
    if args.list or args.validate:
        for sc in scenarios:
            print(f"{sc['name']:36} {len(sc['turns']):>2} turns  account={sc.get('account')}  tags={sc.get('tags')}  {sc.get('doc') or ''}")
        if args.validate:
            print(f"{len(scenarios)} scenario(s) valid")
        return 0
    if not scenarios:
        print("no scenarios selected")
        return 2
    if args.driver == "http":
        driver = HttpDriver(base_url=args.base_url, stream=args.stream, default_account=args.account or "superadmin",
                            skip_cache=args.skip_cache)
    else:
        driver = InProcessDriver()
    results = []
    started = time.time()
    try:
        async with driver:
            truth_ok = True
            if args.driver == "http":
                # the truth queries need the app DB pool in THIS process
                try:
                    from app import db
                    await db.init_pool()
                except Exception as e:  # noqa: BLE001
                    print(f"DB pool not available for truth checks: {type(e).__name__}: {str(e)[:100]}")
                    truth_ok = False
                # a token up front, so an unreachable server fails fast
                try:
                    await driver.ensure_token(args.account or "superadmin")
                except Exception as e:  # noqa: BLE001
                    print(f"cannot mint a token: {type(e).__name__}: {str(e)[:160]}")
                    return 3
            for sc in scenarios:
                if sc.get("skip"):
                    print(f"\n[SKIP] {sc['name']}: {sc['skip']}")
                    continue
                for rep in range(max(1, args.repeat)):
                    r = await run_scenario(driver, sc, args.account, truth_ok)
                    if args.repeat > 1:
                        r["name"] = f"{sc['name']} #{rep + 1}"
                    results.append(r)
                    _print(r)
    except Exception as e:  # noqa: BLE001
        print(f"harness could not run: {type(e).__name__}: {str(e)[:200]}")
        return 3
    passed = sum(1 for r in results if r["passed"])
    turns = sum(len(r["turns"]) for r in results)
    failed_turns = sum(1 for r in results for t in r["turns"] if t["fails"])
    errors = sum(1 for r in results for t in r["turns"] if t["route"] == "error")
    print(f"\n{passed}/{len(results)} scenarios passed; {turns - failed_turns}/{turns} turns ok; "
          f"{errors} transport/server errors; driver={args.driver}{' stream' if args.stream else ''}; "
          f"{round(time.time() - started)}s")
    out_dir = REPO / "logs" / "conversation_harness"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    out = out_dir / f"{stamp}_{args.label or args.driver}.json"
    out.write_text(json.dumps({"driver": args.driver, "stream": args.stream, "account": args.account,
                               "base_url": args.base_url, "results": results}, indent=1, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(f"saved {out.relative_to(REPO)}")
    return 0 if passed == len(results) and results else (3 if not results else 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--driver", choices=("http", "inprocess"), default="http")
    ap.add_argument("--base-url", default=os.environ.get("HARNESS_BASE_URL", "http://127.0.0.1:8401"))
    ap.add_argument("--stream", action="store_true", help="use POST /api/query/stream (http driver)")
    ap.add_argument("--account", default="", help="seeded username for every scenario (default: the scenario's, else superadmin)")
    ap.add_argument("--skip-cache", action="store_true", help="bypass the answer caches (http driver)")
    ap.add_argument("--only", default="", help="comma-separated scenario names")
    ap.add_argument("--tags", default="", help="comma-separated tags (any match)")
    ap.add_argument("--repeat", type=int, default=1, help="run each scenario N times (flakiness)")
    ap.add_argument("--label", default="", help="report file label")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--validate", action="store_true", help="check the scenario files and exit")
    args = ap.parse_args()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
