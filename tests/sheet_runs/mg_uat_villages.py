"""EVERY MGNREGA village (6,491) through the live LangGraph pipeline, one question each, on the
mg_uat.py rules (no year -> all years; job cards = latest year; FY 2025-26 women "not recorded").
The question shape rotates over the sheet's 12 village cases (DATA-001, 005-012, 022, 023, 028),
the year option over the four FYs + no year (formats rotating), the name case over UPPER / Title /
lower. A shared name must draw a which-village pause offering this village (block / LGD code on
the chip); the chip is then taken.

Usage (repo root, VPN): .venv/Scripts/python.exe -X utf8 tests/sheet_runs/mg_uat_villages.py <out.json> [start end]
Resumable: villages already in <out.json> are skipped. MGU_ONLY_CODES=<file of codes> re-runs chosen villages."""
import asyncio
import json
import os
import sys

OUTP = sys.argv[1]
START = int(sys.argv[2]) if len(sys.argv) > 3 else 0
END = int(sys.argv[3]) if len(sys.argv) > 3 else None
sys.argv = sys.argv[:1]
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_uat as U  # noqa: E402
from harness import fetch  # noqa: E402


async def main():
    from app import main as app_main
    async with app_main.lifespan(app_main.app):
        for r in await fetch("SELECT village_code k, year_key y, " + ", ".join(
                f"COALESCE(SUM({c}),0)::float8 {c}" for c in U.EMP_COLS) + " FROM curated.v_employment GROUP BY 1, 2"):
            U.EMP[("village", r["k"], r["y"])] = dict(r)
        for r in await fetch("SELECT village_code k, year_key y, " + ", ".join(
                f"COALESCE(SUM({c}),0)::float8 {c}" for c in U.EXP_COLS) + " FROM curated.v_expenditure GROUP BY 1, 2"):
            U.EXP[("village", r["k"], r["y"])] = dict(r)
        villages = await fetch("""
            SELECT village_code, MIN(lgd_village_name) AS name, MIN(lgd_block) AS block, MIN(lgd_district) AS district
            FROM (SELECT village_code, lgd_village_name, lgd_block, lgd_district FROM curated.v_employment
                  UNION ALL SELECT village_code, lgd_village_name, lgd_block, lgd_district FROM curated.v_expenditure) u
            WHERE village_code IS NOT NULL GROUP BY 1 ORDER BY 1""")
        villages = villages[START:END]
        only = None
        if os.environ.get("MGU_ONLY_CODES"):
            only = {int(x) for x in open(os.environ["MGU_ONLY_CODES"]).read().split()}
        done = set()
        if os.path.exists(OUTP) and only is None:
            # a case that ended in a connection error (VPN drop) is not done: it re-runs
            prev = json.load(open(OUTP, encoding="utf-8"))
            rerun_failed = os.environ.get("MGU_RERUN_FAILED") == "1"       # the after-fix pass
            for tc, cs in prev.items():
                U.RESULTS[tc] = [c for c in cs if not (c["turns"] and c["turns"][-1]["kind"] == "error")
                                 and not (rerun_failed and not c["ok"])]
            done = {c["code"] for cs in U.RESULTS.values() for c in cs if c.get("code") is not None}
        U.log(f"{len(villages)} villages ({len(done)} already done)")
        T = []
        for i, v in enumerate(villages):
            code = v["village_code"]
            if code in done or (only is not None and code not in only):
                continue
            n = i + START
            in_emp = any(("village", code, y) in U.EMP for y in U.YEARS)
            in_exp = any(("village", code, y) in U.EXP for y in U.YEARS)
            emp_tcs = {"DATA-005", "DATA-006", "DATA-007", "DATA-008", "DATA-009"}
            both_tcs = {"DATA-028"}
            shapes = [tc for tc in U.VILLAGE_TCS
                      if (tc in emp_tcs and in_emp) or (tc in both_tcs and in_emp and in_exp)
                      or (tc not in emp_tcs | both_tcs and in_exp)]
            tc = shapes[n % len(shapes)]
            y = U.YOPTS[(n // len(shapes)) % 5]
            nm = [v["name"].upper(), v["name"].title(), v["name"].lower()][n % 3]
            T.append(U.case(tc, "village", code, nm, y, n, f"{v['name']} [{code}] {v['block']}/{v['district']}",
                            place=[v["name"], v["block"] or ""], code=code))
        U.log(f"running {len(T)} conversations")
        for k in range(0, len(T), 200):
            await asyncio.gather(*T[k:k + 200])
            json.dump(U.RESULTS, open(OUTP, "w", encoding="utf-8"), ensure_ascii=False, default=str)
            U.log(f"checkpoint {min(k + 200, len(T))}/{len(T)}")
    U.log("written", OUTP)


asyncio.run(main())
