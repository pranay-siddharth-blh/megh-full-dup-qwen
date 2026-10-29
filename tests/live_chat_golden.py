"""LIVE golden data-answer suite (data-accuracy brief, 2026-10-29).

The user's brief (megh_chatbot_fix_prompt.md) gave ten data questions with known
answers (D1-D10), and asked for a suite that checks the FINAL answer: the figures in
the sentence (Indian grouping, ₹, the crore size, no ".00"), the caveats, the scheme
routing (no scheme nobody asked about) and no needless "which year?" pause. Plus one
check per dashboard card figure, paraphrases, and negative questions.

Not collected by pytest (not named test_*.py). Needs the office VPN (megh_db + gateway).
Each case runs in a FRESH chat through the product's own conversation layer and graph
(tests/conversation_harness InProcessDriver), as the router does.

    .venv/Scripts/python.exe tests/live_chat_golden.py
    .venv/Scripts/python.exe tests/live_chat_golden.py --only D5,D10,CARD
    .venv/Scripts/python.exe tests/live_chat_golden.py --out logs/golden.json

Expected values for D1-D10 are the brief's, checked against megh_db on 2026-10-29
(read-only). Never change one to make a case pass; if one looks wrong, show the SQL
and flag it. Card figures are read live with the cards' own SQL (routers/stats.py),
so a data load never makes the suite stale (user rule: everything dynamic).

Exit code: 0 all passed, 1 a case failed.
"""
import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))

from conversation_harness.drivers import InProcessDriver  # noqa: E402

ALL_SCHEMES = ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy", "CM Elevate Legacy"]


def case(cid, question, *, has=(), any_of=(), lacks=(), schemes=None, pause=False, why=""):
    """has: every string must be in the answer; any_of: lists, one of each must be;
    lacks: none may be; schemes: the answer's schemes must be exactly these;
    pause: True = a clarification is the right outcome, False = it must answer."""
    return {"id": cid, "q": question, "has": list(has), "any_of": [list(a) for a in any_of], "lacks": list(lacks),
            "schemes": schemes, "pause": pause, "why": why}


# Formatting the brief requires of every money answer: never Western-grouped figures
# or a ".00" tail on a whole rupee amount.
NO_WESTERN = ["27,264,054", "466,430,000", "510,105,000", "171,107", "129,941", ".00 ", ".00.", ".00)"]

CASES = [
    # ── D1-D10, the brief's table ──────────────────────────────────────────
    case("D1", "Total MGNREGA person-days statewide in FY 2023-24?", has=["2,72,64,054"], lacks=NO_WESTERN,
         schemes=["MGNREGA"]),
    case("D2", "Total MGNREGA expenditure in West Garo Hills in FY 2024-25?",
         has=["₹25,701.49 lakh", "257.01 crore"], schemes=["MGNREGA"]),
    case("D3", "Which district had the most households completing 100 days in FY 2022-23?",
         has=["East Garo Hills", "22,049", "South Garo Hills", "9,969", "South West Khasi Hills", "7,778"],
         schemes=["MGNREGA"]),
    case("D4", "Share of women employed in Ri Bhoi FY 2023-24?", has=["55.76%", "29,942", "53,700"],
         schemes=["MGNREGA"]),
    case("D5", "How many PMAY-G houses in total, and how many completed?",
         has=["1,71,107", "1,29,941", "41,041", "125"], lacks=NO_WESTERN, schemes=["PMAY-G"]),
    case("D6", "PMAY-G houses sanctioned in East Khasi Hills FY 2019-20?", has=["542"], schemes=["PMAY-G"]),
    case("D7", "Total PMAY-G amount still pending statewide?", has=["₹37,49,31,500", "37.49 crore"],
         schemes=["PMAY-G"], why="no 'which financial year?' pause: all years by default"),
    case("D8", "Focus Plus beneficiaries FY 2022-23 and amount paid?",
         has=["93,286", "₹46,64,30,000", "46.64 crore", "provisional", "not been verified"], lacks=NO_WESTERN,
         schemes=["Focus Plus"]),
    case("D9", "Focus Legacy producer groups and total, all years?",
         has=["11,906", "₹51,01,05,000", "51.01 crore", "FY 2023-24"], lacks=NO_WESTERN + ["LIMIT 1000000"],
         schemes=["Focus Legacy"]),
    case("D10", "CM Elevate Legacy: number of records, subsidy disbursed, scheme with most records?",
         has=["2,823", "52.57", "Meghalaya Piggery Development Scheme", "1,353"],
         lacks=["No MGNREGA", "MGNREGA:", "PMAY-G:", "Focus Plus:", "Focus Legacy:"],
         schemes=["CM Elevate Legacy"]),
    # ── paraphrases ────────────────────────────────────────────────────────
    case("P1", "MGNREGA person days for the whole state in FY24?", has=["2,72,64,054"], schemes=["MGNREGA"]),
    case("P1b", "How many person-days were generated under MGNREGA in Meghalaya during 2023-24?",
         has=["2,72,64,054"], schemes=["MGNREGA"]),
    # the model may divide the lakh column into crore itself: either exact form is right
    case("P2", "How much was spent under MGNREGA in West Garo Hills during 2024-25?", has=["₹"],
         any_of=[["25,701.49 lakh", "257.01 crore"]], schemes=["MGNREGA"]),
    case("P3", "Which district had the highest number of households that completed 100 days of MGNREGA work in 2022-23?",
         has=["East Garo Hills", "22,049", "South Garo Hills"], schemes=["MGNREGA"]),
    case("P4", "What percentage of MGNREGA workers in Ri-Bhoi were women in FY 2023-24?", has=["55.76"],
         schemes=["MGNREGA"]),
    case("P5", "How many PMAY houses are there in total and how many have been completed?",
         has=["1,71,107", "1,29,941"], schemes=["PMAY-G"]),
    case("P6", "How many PMAY-G houses were sanctioned in East Khasi Hills in 2019-20?", has=["542"],
         schemes=["PMAY-G"]),
    case("P7", "How much PMAY-G money is still to be released in Meghalaya?", has=["37.49 crore"],
         schemes=["PMAY-G"]),
    case("P8", "FOCUS+ beneficiaries in 2022-23 and the amount paid?", has=["93,286", "46.64 crore", "provisional"],
         schemes=["Focus Plus"]),
    case("P8b", "How many beneficiaries did Focus+ have in FY 2022-23, and how much was paid?",
         has=["93,286", "46.64 crore"], schemes=["Focus Plus"]),
    case("P9", "How many producer groups does Focus Legacy have, and how much was disbursed in all?",
         has=["11,906", "51.01 crore"], schemes=["Focus Legacy"]),
    case("P10", "For CM Elevate Legacy, how many records are there, how much subsidy was disbursed and which scheme has the most records?",
         has=["2,823", "52.57", "Piggery"], schemes=["CM Elevate Legacy"]),
    # ── the brief's §3 failure modes (probe 2026-10-29) ───────────────────
    case("S1", "MGNREGA person-days in E Khasi Hills in 2023-24?", has=["30,61,525"], schemes=["MGNREGA"],
         why="'E Khasi Hills' is East Khasi Hills, not the Khasi Hills region"),
    case("S2", "PMAY-G houses completed in W Garo Hills?", any_of=[["West Garo Hills"]], schemes=["PMAY-G"]),
    case("S3", "Compare MGNREGA expenditure in FY 2022-23 vs FY 2023-24 statewide",
         has=["FY 2022-23", "FY 2023-24", "886.29 crore", "759.61 crore"], lacks=["2022 is higher"],
         schemes=["MGNREGA"]),
    case("S4", "How many PMAY-G houses in total, and which district has the most?",
         has=["1,71,107", "West Garo Hills", "33,147", "East Khasi Hills", "23,952"], lacks=["West Jaintia"],
         schemes=["PMAY-G"], why="two asks: the total, then the winner and the next two only"),
    case("S5", "Top 5 districts by MGNREGA person-days in FY 2023-24", has=["54,89,616", "28,23,825"],
         schemes=["MGNREGA"]),
    case("S6", "MGNREGA expenditure in Ri Bhoi from 2022-23 to 2024-25, year by year",
         has=["4,575.40", "4,295.67", "5,034.09"], schemes=["MGNREGA"]),
    # ── negatives ──────────────────────────────────────────────────────────
    case("N1", "Focus Legacy amount disbursed in FY 2023-24?", any_of=[["no data", "not held", "absent"]],
         lacks=["₹0 ", "₹0.", "is 0", "were 0", "0 producer"], has=["2023-24", "2024-25"], pause=None,
         why="a year the dataset does not hold: said with the years it does hold, never a zero"),
    case("N2", "Total CM Elevate amount disbursed in East Khasi Hills?", any_of=[["no amount", "not record",
                                                                              "does not", "doesn't", "Legacy"]],
         lacks=["₹0"], why="CM Elevate (applications) records no money"),
    case("N3", "How many MGNREGA person-days in Gotham district in FY 2023-24?", lacks=["is 0", ": 0", "were 0"],
         pause=None, why="unknown district: never a silent 0"),
    case("N4", "How many PM-KISAN beneficiaries are there in Meghalaya?", lacks=["₹"], pause=None,
         why="a scheme we do not hold: said plainly, no figure"),
]


async def card_cases() -> list:
    """One case per dashboard card figure, its truth read with the cards' own SQL."""
    from app.routers import stats
    from app.pipeline import _c12_indian
    from app.db import fetch_rows
    r = {k: dict((await fetch_rows(sql))[0]) for k, sql in stats._SQL.items()}

    def ind(v):
        return _c12_indian(int(round(float(v))))

    def cr(rupees):
        return f"{float(rupees) / 1e7:,.2f}"
    m, p, f, c, fl, cl = (r[k] for k in ("mgnrega", "pmay_g", "focus_plus", "cm_elevate", "focus_legacy",
                                         "cm_elevate_legacy"))
    return [
        case("CARD-mg-pd", "Total MGNREGA person-days across all financial years in Meghalaya?",
             has=[ind(m["person_days"])], schemes=["MGNREGA"]),
        case("CARD-mg-exp", "Total MGNREGA expenditure across all financial years in Meghalaya?",
             has=[f"{float(m['exp_lakh']) / 100:,.2f} crore"], schemes=["MGNREGA"]),
        case("CARD-pm-houses", "How many PMAY-G houses have been sanctioned in Meghalaya in total?",
             has=[ind(p["sanctioned"])], schemes=["PMAY-G"]),
        case("CARD-pm-done", "How many PMAY-G houses have been completed in Meghalaya?",
             has=[ind(p["completed"])], schemes=["PMAY-G"]),
        case("CARD-pm-rel", "Total PMAY-G amount released in Meghalaya across all years?",
             has=[cr(p["released"]) + " crore"], schemes=["PMAY-G"]),
        case("CARD-fp-pay", "How many Focus Plus disbursements have been made in total?",
             has=[ind(f["payments"])], schemes=["Focus Plus"]),
        case("CARD-fp-amt", "Total amount disbursed under Focus Plus across all years?",
             has=[cr(f["amount"]) + " crore", "provisional"], schemes=["Focus Plus"]),
        case("CARD-cme-apps", "How many CM Elevate applications are there in total?",
             has=[ind(c["applications"])], schemes=["CM Elevate"]),
        case("CARD-fl-pg", "How many producer groups are there under Focus Legacy?", has=[ind(fl["groups"])],
             schemes=["Focus Legacy"]),
        case("CARD-fl-mem", "Total Focus Legacy PG memberships paid across all years?", has=[ind(fl["memberships"])],
             schemes=["Focus Legacy"]),
        case("CARD-fl-amt", "Total Focus Legacy amount remitted across all years?", has=[cr(fl["amount"]) + " crore"],
             schemes=["Focus Legacy"]),
        # "sanction records" (the card's label) reads as SANCTIONED records in chat: the 2,820
        # with a sanctioned amount (_cm_legacy_sanctioned_count). The card counts every row.
        case("CARD-cml-rec", "How many records does CM Elevate Legacy have?", has=[ind(cl["records"])],
             schemes=["CM Elevate Legacy"]),
        case("CARD-cml-amt", "Total CM Elevate Legacy amount disbursed, subsidy plus loan, across all years?",
             has=[cr(cl["disbursed"]) + " crore"], schemes=["CM Elevate Legacy"]),
    ]


def judge(c, rec) -> list:
    fails = []
    text = rec.answer or ""
    if c["pause"] is True and rec.route != "pause":
        fails.append("expected a clarification")
    if c["pause"] is False and rec.route in ("pause", "error"):
        fails.append(f"no answer: {rec.route} — {text[:160]}")
        return fails
    for s in c["has"]:
        if s not in text:
            fails.append(f"missing {s!r}")
    for alts in c["any_of"]:
        if not any(a.lower() in text.lower() for a in alts):
            fails.append(f"none of {alts!r}")
    for s in c["lacks"]:
        if s in text:
            fails.append(f"must not say {s!r}")
    if c["schemes"] is not None and rec.route != "pause":
        got = list((rec.raw or {}).get("schemes") or [])
        if got != c["schemes"]:
            fails.append(f"schemes {got} != {c['schemes']}")
    return fails


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list of case ids or prefixes (D, P, N, CARD)")
    ap.add_argument("--out")
    args = ap.parse_args()
    results, failed = [], 0
    async with InProcessDriver() as d:
        cases = CASES + await card_cases()
        if args.only:
            keys = args.only.split(",")
            cases = [c for c in cases if any(c["id"] == k or c["id"].startswith(k) for k in keys)]
        for c in cases:
            conv = d.new_conversation()
            t0 = time.perf_counter()
            rec = await conv.ask(c["q"])
            fails = judge(c, rec)
            failed += bool(fails)
            print(f"{'PASS' if not fails else 'FAIL'} {c['id']:<14} {rec.route:<6} {round(time.perf_counter() - t0, 1):>5}s"
                  + ("" if not fails else "  " + "; ".join(fails)), flush=True)
            if fails:
                print("      " + (rec.answer or "").replace("\n", "\n      ")[:900], flush=True)
            results.append({**c, "route": rec.route, "answer": rec.answer, "fails": fails,
                            "schemes_got": (rec.raw or {}).get("schemes"), "sql": (rec.raw or {}).get("sql_query")})
    print(f"\n{len(results) - failed}/{len(results)} passed")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1, ensure_ascii=False, default=str)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
