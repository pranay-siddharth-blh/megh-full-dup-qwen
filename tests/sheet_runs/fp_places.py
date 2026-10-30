"""Focus Plus: EVERY block and EVERY assembly constituency through the live pipeline, beneficiaries
(FOCUS-001 shape) and amount disbursed (FOCUS-003 shape) for each (2026-10-30; fp_run.py asks the
amount for the 50 raw blocks only and no constituency at all).
Truth from curated.v_focus_plus with the project's rules: beneficiaries = COUNT(DISTINCT
beneficiary_key), amount = SUM(amount_disbursed); a block is block_name_raw (case-insensitive) —
an LGD block with no raw rows (ADOKGRE, MAWLAI, …) is lgd_block, as _focusplus_lgd_only_block
filters it; a constituency is the view's ac_name.
Usage (repo root): fp_places.py [FOCUS-001 FOCUS-003] -> fp_places.json (FP_OUT)"""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "Focus Plus")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from mg_run import run_case  # noqa: E402
from fp_run import checks, FPN, t  # noqa: E402
from harness import fetch  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set(sys.argv[1:])
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("FP_OUT", os.path.join(HERE, "fp_places.json"))
V = "curated.v_focus_plus"
BEN, AMT = "COUNT(DISTINCT beneficiary_key)::float8", "SUM(amount_disbursed)::float8"


async def main():
    async with app_main.lifespan(app_main.app):
        T = []
        add = T.append
        kw = dict(mgnrega_only=False, year="all")
        raw = await fetch(f"SELECT MIN(block_name_raw) b, MIN(lgd_district) d, {BEN} n, {AMT} a FROM {V} "
                          "WHERE block_name_raw IS NOT NULL AND UPPER(block_name_raw) <> 'NAN' "
                          "GROUP BY UPPER(block_name_raw) ORDER BY 1")
        # "WILLIAM NAGAR-MUNICIPAL BOARD" (LGD) is the raw "Williamnagar-Municipal Board": a name
        # with the same letters is the same block, asked once under its raw (counted) name
        from app.entity_resolver import _squash
        raw_names = {_squash(r["b"].upper()) for r in raw}
        lgd_only = [r for r in await fetch(f"SELECT lgd_block b, MIN(lgd_district) d, {BEN} n, {AMT} a FROM {V} "
                                           "WHERE lgd_block IS NOT NULL GROUP BY 1 ORDER BY 1")
                    if _squash(r["b"].upper()) not in raw_names]
        acs = await fetch(f"SELECT ac_name ac, MIN(lgd_district) d, {BEN} n, {AMT} a FROM {V} "
                          "WHERE ac_name IS NOT NULL GROUP BY 1 ORDER BY 1")
        mg_run.log(f"{len(raw)} raw blocks, {len(lgd_only)} LGD-only blocks, {len(acs)} constituencies")
        for i, b in enumerate(list(raw) + lgd_only):
            nm = [b["b"].upper(), t(b["b"]), b["b"].lower()][i % 3] + " block"
            lab = f"block {b['b']} ({b['d']})"
            add(run_case("FOCUS-001", lab, f"How many {FPN[i % 4]} beneficiaries are there in {nm}?",
                         checks(("b", b["n"])), place=[b["b"].split("-")[0].split(" ")[0]], level="block",
                         expected=b["n"], **kw))
            add(run_case("FOCUS-003", lab, f"How much {FPN[(i + 1) % 4]} amount has been disbursed in {nm}?",
                         checks(money=[("amt", b["a"])]), place=[b["b"].split("-")[0].split(" ")[0]],
                         level="block", expected=b["a"], **kw))
        for i, a in enumerate(acs):
            nm = [a["ac"], t(a["ac"]), a["ac"].upper()][i % 3] + " constituency"
            lab = f"constituency {a['ac']} ({a['d']})"
            add(run_case("FOCUS-001", lab, f"How many {FPN[i % 4]} beneficiaries are there in {nm}?",
                         checks(("b", a["n"])), place=[a["ac"]], level="constituency", expected=a["n"], **kw))
            add(run_case("FOCUS-003", lab, f"How much {FPN[(i + 1) % 4]} amount has been disbursed in {nm}?",
                         checks(money=[("amt", a["a"])]), place=[a["ac"]], level="constituency",
                         expected=a["a"], **kw))
        mg_run.log(f"running {len(T)} conversations")
        await asyncio.gather(*T)
    json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    mg_run.log("written", OUT)


if __name__ == "__main__":
    asyncio.run(main())
