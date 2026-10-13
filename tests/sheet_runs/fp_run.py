"""Focus + sheet (FOCUS-001..030) through the live LangGraph pipeline.
Truth from curated.v_focus_plus with the project's rules (schema_context _FOCUSPLUS_RULES):
beneficiaries = COUNT(DISTINCT beneficiary_key) (both cohorts); amount = SUM(amount_disbursed)
in rupees (accepted as rupees, lakh or crore); person columns (gender, occupation,
focus_status, verification_status) exist on the 12.5K cohort only; blocks on block_name_raw.
Hierarchy: every district, every block, every FY (4 formats), every batch and tranche.
Usage (repo root): fp_run.py [TC ...] -> fp_results.json (FP_OUT)"""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "Focus Plus")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from mg_run import run_case, has_name, vals, close  # noqa: E402
from harness import fetch  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set(sys.argv[1:])
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("FP_OUT", "fp_results.json"))
T_ = "FOCUS-"
V = "curated.v_focus_plus"
FYS = {"2022-2023": 2022, "2025-2026": 2025}
FPN = ["Focus+", "Focus Plus", "FOCUS+", "focus plus"]


def num_ok(rec, n):
    return any(close(c, n, 0.0001) for c in vals(rec))


def money_ok(rec, r):
    """A rupee total stated as rupees, lakh or crore (2-decimal rounding allowed)."""
    return any(abs(c - f) <= max(0.006, f * 0.0006) for c in vals(rec) for f in (r, r / 1e5, r / 1e7))


def checks(*pairs, money=()):
    def chk(rec):
        miss = [f"{l}={e}" for l, e in pairs if not num_ok(rec, e)]
        miss += [f"{l}=Rs{e:,.0f}" for l, e in money if not money_ok(rec, e)]
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


def named(*items):
    """[(name, count)] — every count present and every name mentioned."""
    def chk(rec):
        miss = [f"{n}={c}" for n, c in items if not num_ok(rec, c) or not has_name(rec, str(n))]
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


async def one(sql, params=()):
    r = await fetch(sql, list(params))
    return float(list(dict(r[0]).values())[0] or 0)


def t(name):
    return " ".join(w.capitalize() if w.isupper() and len(w) > 2 else w for w in name.split())


async def main():
    async with app_main.lifespan(app_main.app):
        T = []
        add = T.append
        kw = dict(mgnrega_only=False, year="all")
        districts = [r["d"] for r in await fetch(f"SELECT DISTINCT lgd_district d FROM {V} "
                                                 "WHERE lgd_district IS NOT NULL ORDER BY 1")]
        blocks = await fetch(f"SELECT MIN(block_name_raw) b, MIN(lgd_district) d FROM {V} WHERE UPPER(block_name_raw) <> 'NAN' GROUP BY UPPER(block_name_raw) ORDER BY 1")
        tranches = [r["t"] for r in await fetch(f"SELECT DISTINCT tranche_label t FROM {V} ORDER BY 1")]
        mg_run.log(f"{len(districts)} districts, {len(blocks)} blocks, tranches {tranches}")
        BEN, AMT = "COUNT(DISTINCT beneficiary_key)", "SUM(amount_disbursed)"
        K = "batch_label = '12.5K'"

        # ── districts ───────────────────────────────────────────────────────
        per_d = []
        for i, d in enumerate(districts):
            nm = [d, t(d), d.lower()][i % 3]
            b = await one(f"SELECT {BEN} FROM {V} WHERE lgd_district=$1", [d])
            a = await one(f"SELECT {AMT} FROM {V} WHERE lgd_district=$1", [d])
            per_d.append((d, b, a))
            add(run_case(T_ + "001", d, f"How many {FPN[i % 4]} beneficiaries are there in {nm}?", checks(("b", b)),
                         place=[d.split()[0]], level="district", expected=b, **kw))
            add(run_case(T_ + "003", d, f"How much has been disbursed in {nm}?" if i % 2 else
                         f"How much {FPN[i % 4]} amount has been disbursed in {nm}?", checks(money=[("amt", a)]),
                         place=[d.split()[0]], level="district", expected=a, **kw))
            add(run_case(T_ + "025", d, f"What is the average {FPN[i % 4]} disbursement per beneficiary in {nm}?",
                         (lambda r, v=a / b: (any(abs(c - v) <= 0.6 for c in vals(r)), f"avg={v:.2f}")),
                         place=[d.split()[0]], level="district", expected=a / b, **kw))
        add(run_case(T_ + "002", "every district", "How many Focus+ beneficiaries are there in each district?",
                     named(*[(t(d), b) for d, b, _ in per_d]), expected={d: b for d, b, _ in per_d}, **kw))
        top = max(per_d, key=lambda x: x[2])
        add(run_case(T_ + "023", "ranking", "Which district received the highest total Focus+ disbursement?",
                     lambda r, x=top: (has_name(r, x[0]) and money_ok(r, x[2]), f"{x[0]}={x[2]:,.0f}"),
                     expected={top[0]: top[2]}, **kw))
        pairs = [(per_d[i], per_d[(i + 5) % len(per_d)]) for i in range(0, len(per_d), 2)]
        for k, (x, y) in enumerate(pairs):
            add(run_case(T_ + "026", f"{x[0]} vs {y[0]}",
                         f"Compare the number of {FPN[k % 4]} beneficiaries in {t(x[0])} and {t(y[0])}.",
                         checks(("x", x[1]), ("y", y[1]), ("diff", abs(x[1] - y[1]))),
                         expected={x[0]: x[1], y[0]: y[1]}, **kw))
            add(run_case(T_ + "027", f"{x[0]} vs {y[0]}",
                         f"Compare the total {FPN[k % 4]} disbursement in {t(x[0])} and {t(y[0])}.",
                         lambda r, x=x, y=y: ((money_ok(r, x[2]) and money_ok(r, y[2])
                                               and has_name(r, (x if x[2] > y[2] else y)[0])),
                                              f"{x[0]}={x[2]:,.0f} {y[0]}={y[2]:,.0f}"),
                         expected={x[0]: x[2], y[0]: y[2]}, **kw))

        # ── blocks (every block; bare name on odd, "X block" on even) ───────
        for i, b in enumerate(blocks):
            a = await one(f"SELECT {AMT} FROM {V} WHERE UPPER(block_name_raw)=UPPER($1)", [b["b"]])
            nm = (b["b"].upper() if i % 3 == 0 else b["b"]) + (" block" if i % 2 == 0 else "")
            add(run_case(T_ + "004", f"{b['b']} ({b['d']})", f"How much Focus+ amount has been disbursed in {nm}?",
                         checks(money=[("amt", a)]), place=[b["b"]], level="block", expected=a, **kw))

        # ── financial years ─────────────────────────────────────────────────
        for fy_raw, y in FYS.items():
            a = await one(f"SELECT {AMT} FROM {V} WHERE financial_year=$1", [fy_raw])
            ap = await one(f"SELECT COUNT(*) FROM {V} WHERE financial_year=$1 AND focus_status='Approved'", [fy_raw])
            fe = await one(f"SELECT {BEN} FROM {V} WHERE financial_year=$1 AND gender='Female'", [fy_raw])
            fa = await one(f"SELECT {BEN} FROM {V} WHERE financial_year=$1 AND occupation='Farmer'", [fy_raw])
            for s in range(4):
                f = mg_run.fy(y, s)
                add(run_case(T_ + "005", f, f"What was the total {FPN[s]} amount disbursed during {f}?",
                             checks(money=[("amt", a)]), expected=a, **kw))
                add(run_case(T_ + "020", f, f"How many {FPN[s]} beneficiaries were approved during {f}?",
                             checks(("approved", ap)), expected=ap, **kw))
                add(run_case(T_ + "021", f, f"How many women received {FPN[s]} assistance during {f}?",
                             checks(("female", fe)), expected=fe, **kw))
                add(run_case(T_ + "022", f, f"How many farmers received {FPN[s]} assistance during {f}?",
                             checks(("farmers", fa)), expected=fa, **kw))

        # ── batches and tranches ────────────────────────────────────────────
        for bt in ("93K", "12.5K"):
            a = await one(f"SELECT {AMT} FROM {V} WHERE batch_label=$1", [bt])
            add(run_case(T_ + "006", bt, f"How much was disbursed under the {bt} batch of Focus+?",
                         checks(money=[("amt", a)]), expected=a, **kw))
            st = await fetch(f"SELECT COALESCE(focus_status,'(not recorded)') s, {BEN}::float8 n FROM {V} "
                             "WHERE batch_label=$1 GROUP BY 1", [bt])
            add(run_case(T_ + "019", bt, f"Give me the Focus+ status breakdown for the {bt} batch.",
                         checks(*[(r["s"], r["n"]) for r in st]), expected={r["s"]: r["n"] for r in st}, **kw))
        tr_amt = {}
        for i, tr in enumerate(tranches):
            short = tr.split(" - ")[0]
            q_tr = [short, short.replace("Tranch", "Tranche"), tr][i % 3]
            a = await one(f"SELECT {AMT} FROM {V} WHERE tranche_label=$1", [tr])
            tr_amt[short] = a
            add(run_case(T_ + "007", tr, f"How much Focus+ amount was disbursed under {q_tr}?",
                         checks(money=[("amt", a)]), expected=a, **kw))
            st = await fetch(f"SELECT COALESCE(focus_status,'(not recorded)') s, {BEN}::float8 n FROM {V} "
                             "WHERE tranche_label=$1 GROUP BY 1", [tr])
            add(run_case(T_ + "018", tr, f"Give me the Focus+ status breakdown for {q_tr}.",
                         checks(*[(r["s"], r["n"]) for r in st]), expected={r["s"]: r["n"] for r in st}, **kw))
        ts = list(tr_amt)
        for x, y in [(ts[0], ts[1]), (ts[1], ts[2]), (ts[2], ts[3]), (ts[0], ts[3])]:
            add(run_case(T_ + "028", f"{x} vs {y}", f"Compare Focus+ disbursements between {x} and {y}.",
                         checks(money=[(x, tr_amt[x]), (y, tr_amt[y])]), expected={x: tr_amt[x], y: tr_amt[y]}, **kw))

        # ── person-level breakdowns (12.5K cohort) ──────────────────────────
        g = await fetch(f"SELECT gender s, {BEN}::float8 n, {AMT}::float8 a FROM {V} WHERE {K} GROUP BY 1")
        add(run_case(T_ + "008", "statewide", "Give me the gender-wise breakdown of Focus+ beneficiaries.",
                     named(*[(r["s"], r["n"]) for r in g]), expected={r["s"]: r["n"] for r in g}, **kw))
        add(run_case(T_ + "009", "statewide", "How much Focus+ amount was disbursed to female and male beneficiaries?",
                     checks(money=[(r["s"], r["a"]) for r in g]), expected={r["s"]: r["a"] for r in g}, **kw))
        o = await fetch(f"SELECT occupation s, {BEN}::float8 n FROM {V} WHERE {K} GROUP BY 1")
        add(run_case(T_ + "010", "statewide", "Give me the occupation-wise breakdown of Focus+ beneficiaries.",
                     named(*[(r["s"], r["n"]) for r in o]), expected={r["s"]: r["n"] for r in o}, **kw))
        s = await fetch(f"SELECT focus_status s, {BEN}::float8 n, {AMT}::float8 a FROM {V} WHERE {K} GROUP BY 1")
        add(run_case(T_ + "011", "statewide", "Give me the status-wise breakdown of Focus+ beneficiaries.",
                     named(*[(r["s"], r["n"]) for r in s]), expected={r["s"]: r["n"] for r in s}, **kw))
        vs = await fetch(f"SELECT verification_status s, {BEN}::float8 n FROM {V} WHERE {K} GROUP BY 1")
        add(run_case(T_ + "012", "statewide", "Give me the Focus+ verification status breakdown.",
                     named(*[(r["s"], r["n"]) for r in vs]), expected={r["s"]: r["n"] for r in vs}, **kw))
        sd = {r["s"]: r for r in s}
        add(run_case(T_ + "013", "statewide", "How many Focus+ beneficiaries currently have Pending status?",
                     checks(("pending", sd["Pending"]["n"])), expected=sd["Pending"]["n"], **kw))
        add(run_case(T_ + "014", "statewide", "How many Focus+ beneficiaries have been approved?",
                     checks(("approved", sd["Approved"]["n"])), expected=sd["Approved"]["n"], **kw))
        add(run_case(T_ + "015", "statewide", "How many beneficiaries have Pending Focus status?",
                     checks(("pending", sd["Pending"]["n"])), expected=sd["Pending"]["n"], **kw))
        va = sum(r["n"] for r in vs if r["s"] == "Approved")
        add(run_case(T_ + "016", "statewide", "How many Focus+ beneficiaries have approved verification?",
                     checks(("verified", va)), expected=va, **kw))
        for st in ("Pending", "Approved", "Rejected"):
            add(run_case(T_ + "017", st, f"How much Focus+ amount has been disbursed to beneficiaries with {st} status?",
                         checks(money=[(st, sd[st]["a"])]), expected=sd[st]["a"], **kw))

        # ── statewide figures ───────────────────────────────────────────────
        tot_b = await one(f"SELECT {BEN} FROM {V}")
        tot_a = await one(f"SELECT {AMT} FROM {V}")
        add(run_case(T_ + "024", "statewide", "What is the average Focus+ amount disbursed per beneficiary?",
                     lambda r, v=tot_a / tot_b: (any(abs(c - v) <= 0.6 for c in vals(r)), f"avg={v:.2f}"),
                     expected=tot_a / tot_b, **kw))
        bank = (await fetch(f"SELECT bank_name_raw s, {AMT}::float8 a FROM {V} WHERE bank_name_raw !~ '^[0-9]+$' "
                            "GROUP BY 1 ORDER BY 2 DESC LIMIT 1"))[0]
        add(run_case(T_ + "029", "statewide", "Which bank processed the highest total Focus+ disbursement?",
                     lambda r, x=bank: (has_name(r, x["s"]) and money_ok(r, x["a"]), f"{x['s']}={x['a']:,.0f}"),
                     expected=dict(bank), **kw))
        add(run_case(T_ + "030", "statewide", "Give me an overall Focus+ data summary.",
                     checks(("beneficiaries", tot_b), money=[("amount", tot_a)]),
                     expected={"beneficiaries": tot_b, "amount": tot_a}, **kw))

        mg_run.log(f"running {len(T)} conversations")
        await asyncio.gather(*T)
    json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    mg_run.log("written", OUT)


if __name__ == "__main__":
    asyncio.run(main())
