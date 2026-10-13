"""EVERY Focus Legacy village (village_code, entity_type <> 'Unresolved') through the live
pipeline, one question each; the shape alternates TC-27-style (producer groups mapped to
the village, counted) / TC-18-style (amount disbursed) and the name's case rotates UPPER /
Title / lower. Shared names must draw a which-village pause offering the right village
(twins picked by LGD code). Usage (repo root): fl_all.py -> fl_all_results.json
(FL_ALL_OUT); resumable; FL_ONLY_CODES=<file> re-runs just those villages."""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "Focus Legacy")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from fl_run import checks, FN  # noqa: E402
from harness import fetch  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("FL_ALL_OUT", "fl_all_results.json"))
V = "curated.v_focus_legacy"
T_ = "TC-"


async def main():
    async with app_main.lifespan(app_main.app):
        villages = await fetch(f"""SELECT village_code, MIN(lgd_village_name) name, MIN(lgd_block) block,
                                          MIN(lgd_district) district, COUNT(DISTINCT pg_id)::float8 g,
                                          SUM(amount_disbursed)::float8 a
                                   FROM {V} WHERE entity_type <> 'Unresolved' AND village_code > 0
                                   GROUP BY 1 ORDER BY 1""")
        only = None
        if os.environ.get("FL_ONLY_CODES"):
            only = {int(x) for x in open(os.environ["FL_ONLY_CODES"]).read().split()}
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
                tc, q, chk, ex = (T_ + "27", f"How many {FN[i % 4]} Producer Groups are mapped to {nm} village?",
                                  checks(("groups", v["g"])), v["g"])
            else:
                tc, q, chk, ex = (T_ + "18", f"What is the total {FN[i % 4]} amount disbursed for {nm}?",
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
