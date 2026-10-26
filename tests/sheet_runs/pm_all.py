"""EVERY PMAY-G village through the live LangGraph pipeline, one question each.
The shape rotates over the sheet's 12 village cases (PMAY-OFF-001..010, 026, 028);
the name's case rotates UPPER / Title / lower; shared names must draw a
which-village pause offering the right village. A year pause is answered "All
financial years combined". Expected values: one grouped query on curated.v_pmay.
A village whose only records are zero-sanction registrations counts them as
beneficiaries (D-060), never as a missing place.

Usage (repo root): pm_all.py  -> pm_all_results.json (PM_ALL_OUT); resumable;
PM_ONLY_CODES=<file of codes> re-runs just those villages."""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "PMAY-G")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from pm_run import AGG, Q, VILLAGE_TCS, checks, shape  # noqa: E402
from harness import fetch  # noqa: E402
from tests._text_checks import has_phrase  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("PM_ALL_OUT", "pm_all_results.json"))


def zero_said(answer):
    """The answer states zero / no record (case-insensitive)."""
    return (has_phrase(answer, "0", "no pmay-g houses", "no sanctioned house", "zero", bounded=True)
            or has_phrase(answer, "not recorded", "no record", "no data",
                          "couldn?t find any matching records", "could not find any matching records"))


def casing(name, i):
    return [name.upper(), name.title(), name.lower()][i % 3]


async def main():
    async with app_main.lifespan(app_main.app):
        rows = await fetch(f"""SELECT village_code, {AGG} FROM curated.v_pmay
                               WHERE village_code IS NOT NULL GROUP BY 1""")
        agg = {r["village_code"]: dict(r) for r in rows}
        villages = await fetch("""SELECT village_code, MIN(lgd_village_name) AS name, MIN(lgd_block) AS block,
                                         MIN(lgd_district) AS district, BOOL_AND(is_placeholder) AS only_ph
                                  FROM curated.v_pmay WHERE village_code IS NOT NULL GROUP BY 1 ORDER BY 1""")
        only = None
        if os.environ.get("PM_ONLY_CODES"):
            only = {int(x) for x in open(os.environ["PM_ONLY_CODES"]).read().split()}
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
            tc = VILLAGE_TCS[i % len(VILLAGE_TCS)]
            nm = casing(v["name"], i)
            a = agg.get(code)
            lab = f"{v['name']} [{code}] {v['block']}/{v['district']} as '{nm}'"
            if a is None:   # placeholder-only village: must be a plain zero, not 'unknown place'
                def chk(rec):
                    return zero_said(rec.get("answer") or ""), "placeholder-only village: zero expected"
                ex = 0
            else:
                chk = checks(*shape(tc, a))
                ex = {k: a[k] for k in ("houses", "sanctioned", "released", "completed")}
            T.append(_case(tc, lab, Q[tc].format(p=nm), chk, ex, code,
                           dict(year="all", place=[v["name"], v["block"] or ""], level="village")))
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
