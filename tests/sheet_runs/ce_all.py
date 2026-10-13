"""EVERY CM Elevate village (entity_type <> 'Unresolved') through the live pipeline,
one question each; the shape rotates over the sheet's village cases (OFF-003
applicants, OFF-008 program in village, OFF-030 status per program in village) and
the name's case over UPPER / Title / lower. Shared names must draw a which-village
pause offering the right village. Usage (repo root): ce_all.py -> ce_all_results.json
(CE_ALL_OUT); resumable; CE_ONLY_CODES=<file> re-runs just those villages."""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "CM Elevate")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from ce_run import STATUS, SHORT, checks, names_and, pname  # noqa: E402
from harness import fetch  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("CE_ALL_OUT", "ce_all_results.json"))
V = "curated.v_cm_elevate"
T_ = "CM-ELEVATE-OFF-"


async def main():
    async with app_main.lifespan(app_main.app):
        villages = await fetch(f"""SELECT village_code, MIN(lgd_village_name) name, MIN(lgd_block) block,
                                          MIN(lgd_district) district, COUNT(DISTINCT request_id)::float8 n
                                   FROM {V} WHERE entity_type <> 'Unresolved' AND village_code IS NOT NULL
                                   GROUP BY 1 ORDER BY 1""")
        progs = {}
        for r in await fetch(f"""SELECT village_code, scheme_name p, COUNT(DISTINCT request_id)::float8 n FROM {V}
                                 WHERE entity_type <> 'Unresolved' GROUP BY 1,2 ORDER BY 1, 3 DESC, 2"""):
            progs.setdefault(r["village_code"], []).append((r["p"], r["n"]))
        stat = {}
        for r in await fetch(f"""SELECT village_code, scheme_name p, {STATUS} s, COUNT(DISTINCT request_id)::float8 n FROM {V}
                                 WHERE entity_type <> 'Unresolved' GROUP BY 1,2,3"""):
            stat.setdefault((r["village_code"], r["p"]), []).append((r["s"], r["n"]))
        only = None
        if os.environ.get("CE_ONLY_CODES"):
            only = {int(x) for x in open(os.environ["CE_ONLY_CODES"]).read().split()}
        done = set()
        if os.path.exists(OUT):
            prev = json.load(open(OUT, encoding="utf-8"))
            mg_run.RESULTS.update(prev)
            done = {c["code"] for cs in prev.values() for c in cs if "code" in c}
        mg_run.log(f"{len(villages)} villages ({len(done)} already done)")
        T = []
        for i, v in enumerate(villages):
            code = v["village_code"]
            if code in done or (only is not None and code not in only):
                continue
            nm = [v["name"].upper(), v["name"].title(), v["name"].lower()][i % 3]
            p0, n0 = progs[code][0]
            k = i % 3
            if k == 0:
                tc, q, chk, ex = T_ + "003", f"How many CM ELEVATE applicants are there in {nm}?", checks(("n", v["n"])), v["n"]
            elif k == 1:
                tc, q, chk, ex = (T_ + "008", f"How many applicants are there under {pname(p0, i)} in {nm}?",
                                  checks(("n", n0)), n0)
            else:
                sv = stat[(code, p0)]
                tc, q, chk, ex = (T_ + "030", f"What is the status-wise applicant count for {pname(p0, i)} in {nm}?",
                                  names_and(*sv), dict(sv))
            lab = f"{v['name']} [{code}] {v['block']}/{v['district']} as '{nm}' / {SHORT[p0]}"
            T.append(_case(tc, lab, q, chk, ex, code, dict(year=None, place=[v["name"], v["block"] or ""],
                                                         level="village")))
        mg_run.log(f"running {len(T)} conversations")
        for k in range(0, len(T), 200):
            await asyncio.gather(*T[k:k + 200])
            json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, default=str)
            mg_run.log(f"checkpoint {min(k + 200, len(T))}/{len(T)}")
    mg_run.log("written", OUT)


async def _case(tc, lab, q, chk, ex, code, kw):
    await mg_run.run_case(tc, lab, q, chk, expected=ex, mgnrega_only=False, **kw)
    mg_run.RESULTS[tc][-1]["code"] = code


if __name__ == "__main__":
    asyncio.run(main())
