"""EVERY Focus Plus village (village_code) through the live pipeline, one question each;
the shape alternates FOCUS-001 (beneficiaries) / FOCUS-003 (amount disbursed) and the
name's case rotates UPPER / Title / lower. Shared names must draw a which-village pause
offering the right village. Usage (repo root): fp_all.py -> fp_all_results.json
(FP_ALL_OUT); resumable; FP_ONLY_CODES=<file> re-runs just those villages."""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "Focus Plus")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from fp_run import checks, FPN  # noqa: E402
from harness import fetch  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("FP_ALL_OUT", "fp_all_results.json"))
V = "curated.v_focus_plus"
T_ = "FOCUS-"


async def main():
    async with app_main.lifespan(app_main.app):
        villages = await fetch(f"""SELECT village_code, MIN(lgd_village_name) name, COALESCE(MIN(lgd_block), MIN(block_name_raw)) block,
                                          MIN(lgd_district) district, COUNT(DISTINCT beneficiary_key)::float8 b,
                                          SUM(amount_disbursed)::float8 a
                                   FROM {V} WHERE village_code > 0 GROUP BY 1 ORDER BY 1""")
        only = None
        if os.environ.get("FP_ONLY_CODES"):
            only = {int(x) for x in open(os.environ["FP_ONLY_CODES"]).read().split()}
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
            if i % 2 == 0:
                tc, q, chk, ex = (T_ + "001", f"How many {FPN[i % 4]} beneficiaries are there in {nm}?",
                                  checks(("b", v["b"])), v["b"])
            else:
                tc, q, chk, ex = (T_ + "003", f"How much {FPN[i % 4]} amount has been disbursed in {nm}?",
                                  checks(money=[("amt", v["a"])]), v["a"])
            lab = f"{v['name']} [{code}] {v['block']}/{v['district']} as '{nm}'"
            T.append(_case(tc, lab, q, chk, ex, code, dict(year="all", place=[v["name"], v["block"] or ""],
                                                         level="village")))
        mg_run.log(f"running {len(T)} conversations")
        for k in range(0, len(T), 200):
            await asyncio.gather(*T[k:k + 200])
            json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, default=str)
            mg_run.log(f"checkpoint {min(k + 200, len(T))}/{len(T)}")
    mg_run.log("written", OUT)


async def _case(tc, lab, q, chk, ex, code, kw):
    await mg_run.run_case(tc, lab, q, chk, expected=ex, mgnrega_only=False, code=code, **kw)
    mg_run.RESULTS[tc][-1]["code"] = code


if __name__ == "__main__":
    asyncio.run(main())
