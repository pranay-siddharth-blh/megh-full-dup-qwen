"""Build tests/accuracy/log_bank_2026_11_16.yaml: the LOG BANK (16 Nov 2026, before the 05:00 demo).

The questions are the user's own (app.conversation_turns since 15 Nov 17:30 IST and the voice engine's
`heard '...'` lines in D:/Full Duplex Architecture/run/logs/megh.log), their spoken paraphrases, one fully
specified question for EVERY block (scheme / measure / FY / district / block in one breath), vague starts with
their ask-back, and the follow-up chains the user speaks. Truth = this file's own SQL on the curated views
(definitions as data/metric_catalog_verified.yaml / app/metric_catalog.py), recomputed live by the runner.

Same schema as gold_bank.yaml, plus three keys the log runner (run_log_bank.py) checks after the gold judge:
  not_route   the turn must NOT take this route (e.g. knowledge for a data question)
  rw_lacks    the rewritten (standalone) question must not contain these words (follow-up glue)
  max_s       the turn must answer within this many seconds

    .venv/Scripts/python.exe tests/accuracy/build_log_bank.py      # needs megh_db (VPN)
"""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import yaml  # noqa: E402

OUT = os.path.join(ROOT, "tests", "accuracy", "log_bank_2026_11_16.yaml")
FY = {y: f"{y}-{str(y + 1)[2:]}" for y in range(2015, 2030)}
SRC_LOG = "user live session 15-16 Nov 2026 (conversation_turns / megh.log)"


def q(s: str) -> str:
    return s.replace("'", "''")


# ── measures: (scheme, spoken measure, sql template, unit, years, block column) ─────────────────────
# {w} = the WHERE clause (place + year)
MEASURES = [
    ("MGNREGA", "person-days generated", "SELECT SUM(person_days) FROM curated.v_employment WHERE {w}", "count",
     [2022, 2023, 2024, 2025], "lgd_block"),
    ("MGNREGA", "total expenditure", "SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE {w}", "lakh",
     [2022, 2023, 2024, 2025], "lgd_block"),
    ("PMAY-G", "houses sanctioned", "SELECT COUNT(*) FROM curated.v_pmay WHERE {w}", "count",
     [2019, 2020, 2022, 2023], "lgd_block"),
    ("MGNREGA", "households employed", "SELECT SUM(households_employed) FROM curated.v_employment WHERE {w}", "count",
     [2022, 2023, 2024, 2025], "lgd_block"),
    ("PMAY-G", "houses completed", "SELECT COUNT(*) FROM curated.v_pmay WHERE is_completed AND {w}", "count",
     [2019, 2020, 2022, 2023], "lgd_block"),
    ("Focus Legacy", "producer groups", "SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE {w}", "count",
     [2022, 2024, 2025], "lgd_block"),
    ("MGNREGA", "material expenditure", "SELECT ROUND(SUM(material_exp), 2) FROM curated.v_expenditure WHERE {w}",
     "lakh", [2022, 2023, 2024, 2025], "lgd_block"),
    ("Focus Plus", "beneficiaries", "SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE {w}",
     "count", [2022, 2025], "UPPER(block_name_raw)"),
    ("PMAY-G", "amount released", "SELECT SUM(COALESCE(amount_released, 0)) FROM curated.v_pmay WHERE {w}", "rupees",
     [2020, 2022, 2023], "lgd_block"),
    ("Focus Legacy", "amount disbursed", "SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE {w}",
     "rupees", [2022, 2024, 2025], "lgd_block"),
]

# the ways the user puts everything in one breath (spoken order varies)
ONE_SHOT = [
    "{scheme} {measure} for FY {fy} in {district}, {block} block",
    "What were the {scheme} {measure} in {block} block of {district} in {fy}?",
    "Can you give me the {measure} under {scheme} for {block} block, {district} district, financial year {fy}?",
    "In {fy}, how much {scheme} {measure} did {block} block in {district} have?",
    "Okay, show me {block} block in {district}, {scheme} {measure}, FY {fy}.",
]


def title(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split())


def fig(sql, unit, label=None):
    f = {"sql": sql, "unit": unit}
    if label:
        f["label"] = label
    return f


def rows(sql, unit="count", take="all"):
    r = {"sql": sql, "unit": unit}
    if take != "all":
        r["take"] = take
    return r


def turn(qs, **kw):
    t = {"q": qs}
    t.update(kw)
    return t


def case(cid, cat, shape, turns, src=SRC_LOG):
    return {"id": cid, "cat": cat, "shape": shape, "src": src, "turns": turns}


EMP = "curated.v_employment"
EXP = "curated.v_expenditure"
PM = "curated.v_pmay"
FL = "curated.v_focus_legacy"
FP = "curated.v_focus_plus"
WGH, EKH, WKH, NGH = "WEST GARO HILLS", "EAST KHASI HILLS", "WEST KHASI HILLS", "NORTH GARO HILLS"


def log_cases() -> list[dict]:
    """(a) every logged user question verbatim (as the conversation it was asked in) + spoken paraphrases."""
    C = []
    # A1: the headline figure of one scheme for one district (went to knowledge, 15 Nov 19:14 UTC)
    pd_wgh = fig(f"SELECT SUM(person_days) FROM {EMP} WHERE lgd_district = '{WGH}'", "count", "person-days WGH")
    for i, s in enumerate(["Give me the figure of MGNREGA for West Garo Hills?",
                           "Okay, could you give me the headline? Can you give me the figure of MGNREGA for West Garo Hills?",
                           "What's the MGNREGA figure for West Garo Hills?",
                           "Can you give me the MGNREGA numbers for West Garo Hills",
                           "Give me the headline figure of MGNREGA in West Garo Hills"]):
        C.append(case(f"LOG-A1-{i}", "log-headline", "scheme-district-headline",
                      [turn(s, figures=[pd_wgh], pause=False, route="data", schemes=["MGNREGA"], place=WGH,
                            not_route="knowledge", max_s=25)]))
    # A2: expenditure by FY -> by district -> East AND West Khasi Hills by block (heading said only WKH)
    fy_rows = rows(f"SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM {EXP} GROUP BY 1 ORDER BY 1", "lakh")
    dist_rows = rows(f"SELECT lgd_district, ROUND(SUM(total_exp), 2) FROM {EXP} GROUP BY 1 ORDER BY 2 DESC", "lakh")
    ekwk_rows = rows(f"SELECT lgd_block, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district IN ('{EKH}', '{WKH}') "
                     "GROUP BY 1 ORDER BY 2 DESC", "lakh")
    for i, (a, b, c) in enumerate([
        ("Give me the Mandriga expenditure by financial year.", "break that down by district",
         "Break down East and West Khasi Hills expenditure by block for MGNREGA."),
        ("Show me the MGNREGA expenditure by financial year.", "Okay, now can you break it down by the district?",
         "Now can you just can you break down East and West Khasi Hills by the block for the same."),
        ("I want you to show me the MGNREGA expenditure for every financial year.", "and by district?",
         "Now show me the blocks of East Khasi Hills and West Khasi Hills for the same"),
    ]):
        C.append(case(f"LOG-A2-{i}", "log-chain", "fy-district-twodistricts-block", [
            turn(a, rows=[fy_rows], pause=False, schemes=["MGNREGA"], lacks=["≈"], max_s=25),
            turn(b, rows=[dist_rows], pause=False, schemes=["MGNREGA"], lacks=["≈"], max_s=25),
            turn(c, rows=[ekwk_rows], pause=False, schemes=["MGNREGA"], lacks=["≈", "in West Khasi Hills district with"],
                 has=["East Khasi Hills"], max_s=30)]))
    # A3: change over the last three years in one district (listed only two FYs)
    last3 = rows(f"SELECT financial_year_short, SUM(person_days) FROM {EMP} WHERE lgd_district = '{WGH}' AND year_key >= 2023 "
                 "GROUP BY 1 ORDER BY 1")
    for i, s in enumerate(["How have MGNREGA person-days changed over the last three years in West Garo Hills?",
                           "How did MGNREGA person-days in West Garo Hills change in the last three years?",
                           "Okay, can you tell me the MGNREGA person-days trend in West Garo Hills for the last three years"]):
        C.append(case(f"LOG-A3-{i}", "log-trend", "district-last3", [
            turn(s, rows=[last3], pause=False, schemes=["MGNREGA"], has=["2023-24", "2024-25", "2025-26"], max_s=25)]))
    # A4: a year outside the data (went to knowledge)
    for i, s in enumerate(["MGNREGA in 2020.", "Show me MGNREGA person-days in 2020",
                           "What was the MGNREGA expenditure in 2019-20?"]):
        C.append(case(f"LOG-A4-{i}", "log-year-outside", "year-outside-coverage", [
            turn(s, pause="either", not_route="knowledge", any_of=[["2022-23"], ["2025-26"]], max_s=25)]))
    # A5: month by month (wrote "2021-12-01" for a month)
    for i, s in enumerate(["Month by month, how many PMAY-G houses were sanctioned in 2021?",
                           "Show me PMAY-G houses sanctioned month by month in FY 2023-24"]):
        C.append(case(f"LOG-A5-{i}", "log-month", "month-by-month", [
            turn(s, pause=False, schemes=["PMAY-G"], lacks=["-01-01", "-02-01", "-03-01", "-04-01", "-05-01", "-06-01",
                                                           "-07-01", "-08-01", "-09-01", "-10-01", "-11-01", "-12-01"],
                 max_s=30)]))
    # A6: a standalone cross-scheme question after a comparison (glued onto the previous by the rewriter)
    for i, s in enumerate(["Which scheme has the widest coverage across districts?",
                           "Which scheme reaches the most villages?",
                           "Give me the headline figure of every scheme",
                           "Okay, now give me the headline figure of every scheme",
                           "Okay. Which scheme has the widest coverage across districts?"]):
        C.append(case(f"LOG-A6-{i}", "log-standalone", "compare-then-standalone", [
            turn("Compare the total beneficiaries in PMAY-G and MGNREGA", pause=False, max_s=30),
            turn(s, pause=False, rw_lacks=["Compare", "compare", "beneficiaries in PMAY-G and MGNREGA"], max_s=30)]))
    # A7: the per-FY money in one district (statewide per FY was "₹91,605.96 lakh (≈ ₹916.06 crore)")
    C.append(case("LOG-A7-0", "log-money", "money-wording", [
        turn("What was the total expenditure in West Garo Hills during 2023-24?",
             figures=[fig(f"SELECT ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district = '{WGH}' AND year_key = 2023",
                          "lakh")], pause=False, place=WGH, year=2023, lacks=["≈"], max_s=25)]))
    C.append(case("LOG-A7-1", "log-money", "money-wording", [
        turn("What was the total expenditure in West Garo Hills during two thousand twenty-three twenty-four?",
             figures=[fig(f"SELECT ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district = '{WGH}' AND year_key = 2023",
                          "lakh")], pause=False, place=WGH, year=2023, lacks=["≈"], max_s=25)]))
    # A8: "Meghalaya expenditure per financial (year) across all districts" -> then North Garo Hills by blocks
    ngh_blocks = rows(f"SELECT lgd_block, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district = '{NGH}' GROUP BY 1 "
                      "ORDER BY 2 DESC", "lakh")
    for i, (a, b) in enumerate([
        ("Show me the Meghalaya expenditure per financial across all districts?",
         "Okay, could you break down North Garo Hills by the blocks?"),
        ("Could you please show me the MGNREGA expenditure per financial year across all districts?",
         "Okay, now could you break this? Could you break North Garo Hills by blocks for the same?"),
        ("Show me MGNREGA expenditure for each financial year for the whole state",
         "break down North Garo Hills block wise"),
    ]):
        C.append(case(f"LOG-A8-{i}", "log-chain", "fy-then-district-blocks", [
            turn(a, rows=[fy_rows], pause=False, schemes=["MGNREGA"], lacks=["≈"], max_s=25),
            turn(b, rows=[ngh_blocks], pause=False, schemes=["MGNREGA"], place=NGH, lacks=["≈"], max_s=30)]))
    # A9: block breakdown with no scheme -> ask-back -> pick (then "couldn't build a working query")
    wgh_pd_blocks = rows(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE lgd_district = '{WGH}' GROUP BY 1 "
                         "ORDER BY 2 DESC")
    wgh_exp_blocks = rows(f"SELECT lgd_block, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district = '{WGH}' "
                          "GROUP BY 1 ORDER BY 2 DESC", "lakh")
    for i, (a, b) in enumerate([("Show me the breakdown by blocks of West Garo Hills?", "MGNREGA"),
                                ("Could you show me the breakdown by blocks of West Garo Hills?", "For MGNREGA."),
                                ("Break down West Garo Hills by block", "MGNREGA please")]):
        C.append(case(f"LOG-A9-{i}", "log-askback", "noscheme-block-pick", [
            turn(a, pause=True, max_s=20),
            turn(b, rows=[{"any": [wgh_pd_blocks, wgh_exp_blocks]}], pause=False, schemes=["MGNREGA"], max_s=30,
                 lacks=["couldn't build"])]))
    C.append(case("LOG-A9-3", "log-oneshot", "block-breakdown-scheme-named", [
        turn("I want you to show me the breakdown by blocks of West Garo Hills for the scheme MGNREGA.",
             rows=[{"any": [wgh_pd_blocks, wgh_exp_blocks]}], pause=False, schemes=["MGNREGA"], lacks=["couldn't build"],
             max_s=30)]))
    # A10: top 5 Focus Plus -> by block (D-110 b: the blocks INSIDE those districts) -> back to the dashboard
    top5 = rows(f"SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM {FP} WHERE lgd_district IS NOT NULL "
                "GROUP BY 1 ORDER BY 2 DESC", take=5)
    C.append(case("LOG-A10-0", "log-chain", "top5-by-block-nav", [
        turn("Can you can you show me the top 5 districts by Focus Plus beneficiaries?", rows=[top5], pause=False,
             schemes=["Focus Plus"], max_s=25),
        turn("Can you break this down by block?", pause=False, schemes=["Focus Plus"], max_s=30),
        turn("Take me back to the dashboard.", pause=False, lacks=["can't apply", "book, pay"], max_s=10)]))
    # A11: PMAY-G completed by district -> 3 districts only -> bar
    comp_d = rows(f"SELECT lgd_district, COUNT(*) FROM {PM} WHERE is_completed GROUP BY 1 ORDER BY 2 DESC")
    comp3 = rows(f"SELECT lgd_district, COUNT(*) FROM {PM} WHERE is_completed AND lgd_district IN "
                 f"('{WGH}', '{EKH}', 'EAST GARO HILLS') GROUP BY 1 ORDER BY 2 DESC")
    for i, b in enumerate(["Now, can you show me this only for West Garo Hills, East Khasi Hills, and East Garo Hills?",
                           "Can you show me the same thing only for West Garo Hills, East Khasi Hills, and East Garo Hills?"]):
        C.append(case(f"LOG-A11-{i}", "log-chain", "district-then-3-districts", [
            turn("Can you show me the PMAY-G houses completed by district?", rows=[comp_d], pause=False,
                 schemes=["PMAY-G"], max_s=25),
            turn(b, rows=[comp3], pause=False, schemes=["PMAY-G"], max_s=25),
            turn("Can you show it to me in a bar graph?", pause=False, chart="bar", max_s=10)]))
    # A12: every scheme's headline -> just MGNREGA -> West Garo Hills by block
    C.append(case("LOG-A12-0", "log-chain", "headline-scheme-district-block", [
        turn("Can you give me the headline figure of every scheme?", pause=False, max_s=30),
        turn("Okay, and now can you give me the headline just for MGNREGA?",
             figures=[fig(f"SELECT SUM(person_days) FROM {EMP}", "count", "MGNREGA person-days")], pause=False,
             schemes=["MGNREGA"], max_s=25),
        turn("Okay, for West Garo Hills, can you break it down by block?", rows=[wgh_pd_blocks], pause=False,
             schemes=["MGNREGA"], max_s=30)]))
    # A13: district + year, scheme implied by the measure word
    C.append(case("LOG-A13-0", "log-oneshot", "measure-implies-scheme", [
        turn("How many total person-days were generated in East Khasi Hills during 2023-24?",
             figures=[fig(f"SELECT SUM(person_days) FROM {EMP} WHERE lgd_district = '{EKH}' AND year_key = 2023",
                          "count")], pause=False, schemes=["MGNREGA"], place=EKH, year=2023, max_s=25)]))
    C.append(case("LOG-A13-1", "log-oneshot", "measure-implies-scheme", [
        turn("How many job cards are there in West Garo Hills in 2023-24?",
             figures=[fig(f"SELECT SUM(job_cards_issued_total) FROM {EMP} WHERE lgd_district = '{WGH}' AND year_key = 2023",
                          "count")], pause=False, schemes=["MGNREGA"], place=WGH, year=2023, max_s=25)]))
    # A14: Focus Legacy remitted by FY -> bar ; top 5 Focus Plus as a pie
    C.append(case("LOG-A14-0", "log-chain", "fy-then-view", [
        turn("Okay, now could you show me the total Focus Legacy amount remitted in each financial year?",
             rows=[rows(f"SELECT financial_year_short, SUM(amount_disbursed) FROM {FL} GROUP BY 1 ORDER BY 1", "rupees")],
             pause=False, schemes=["Focus Legacy"], max_s=25),
        turn("Can you show it to me in a bar graph?", pause=False, chart="bar", max_s=10)]))
    C.append(case("LOG-A14-1", "log-oneshot", "top5-pie", [
        turn("Okay, I wanted to show me the top five districts by Focus Plus beneficiaries as a pie chart.",
             rows=[top5], pause=False, schemes=["Focus Plus"], chart="pie", max_s=25)]))
    C.append(case("LOG-A14-2", "log-oneshot", "fy-line", [
        turn("Show me MGNREGA person-days trend over the years as a line chart.",
             rows=[rows(f"SELECT financial_year_short, SUM(person_days) FROM {EMP} GROUP BY 1 ORDER BY 1")], pause=False,
             schemes=["MGNREGA"], chart="line", max_s=25)]))
    # A15: compare two schemes (user's own wording)
    C.append(case("LOG-A15-0", "log-oneshot", "compare-two", [
        turn("Could you also compare the total beneficiaries in PMAY-G and MGNREGA?", pause=False, max_s=30)]))
    # A16: PMAY-G data for all districts -> WGH block wise
    sanc_d = rows(f"SELECT lgd_district, COUNT(*) FROM {PM} GROUP BY 1 ORDER BY 2 DESC")
    wgh_sanc_b = rows(f"SELECT lgd_block, COUNT(*) FROM {PM} WHERE lgd_district = '{WGH}' GROUP BY 1 ORDER BY 2 DESC")
    C.append(case("LOG-A16-0", "log-chain", "district-then-block", [
        turn("Can you give me the data of PMAY-G for Meghalaya as of all the districts?", rows=[sanc_d], pause=False,
             schemes=["PMAY-G"], max_s=25),
        turn("Can you break down West Garo Hills by blockwise?", rows=[wgh_sanc_b], pause=False, schemes=["PMAY-G"],
             place=WGH, max_s=25)]))
    # A17: PMAY-G completed by district -> WGH by block -> Demdema by village
    C.append(case("LOG-A17-0", "log-chain", "district-block-village", [
        turn("How many PMAY-G houses have been completed in Meghalaya, by district?", rows=[comp_d], pause=False,
             schemes=["PMAY-G"], max_s=25),
        turn("Break that down by block within West Garo Hills.",
             rows=[rows(f"SELECT lgd_block, COUNT(*) FROM {PM} WHERE is_completed AND lgd_district = '{WGH}' GROUP BY 1 "
                        "ORDER BY 2 DESC")], pause=False, schemes=["PMAY-G"], max_s=25),
        turn("Break that down by village within Demdema block.",
             rows=[rows(f"SELECT lgd_village_name, COUNT(*) FROM {PM} WHERE is_completed AND lgd_block = 'DEMDEMA' "
                        "GROUP BY 1 ORDER BY 2 DESC", take=3)], pause=False, schemes=["PMAY-G"], max_s=30)]))
    # A18: knowledge / meta the user asked
    C.append(case("LOG-A18-0", "log-knowledge", "about-scheme", [
        turn("Can you tell me about the PMAY-G?", pause=False, route="knowledge", max_s=25)]))
    C.append(case("LOG-A18-1", "log-meta", "blocks-count", [
        turn("Can you tell me how many blocks are there in Meghalaya?", pause=False, max_s=25)]))
    C.append(case("LOG-A18-2", "log-dashboard", "cm-elevate-status", [
        turn("Could you show me the CM Elevate applications by their status?",
             rows=[{"any": [rows("SELECT file_status, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate GROUP BY 1 "
                                 "ORDER BY 2 DESC", take=3),
                            rows("SELECT file_status, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE "
                                 "data_verified = 'Valid' GROUP BY 1 ORDER BY 2 DESC", take=3)]}], pause=False, max_s=25)]))
    # A19: person-days by district in a year -> West Garo Hills -> by block (the bank's most-run chain)
    C.append(case("LOG-A19-0", "log-chain", "district-year-then-place-block", [
        turn("Show me MGNREGA person-days generated by district", rows=[rows(
            f"SELECT lgd_district, SUM(person_days) FROM {EMP} GROUP BY 1 ORDER BY 2 DESC")], pause=False, max_s=25),
        turn("Show me MGNREGA person-days generated for West Garo Hills", figures=[pd_wgh], pause=False, place=WGH,
             max_s=25),
        turn("Break it down by block", rows=[wgh_pd_blocks], pause=False, max_s=25)]))
    return C


async def fetch(sql):
    from app import db
    r = await db.fetch_rows_readonly(sql)
    return [[(float(x) if isinstance(x, Decimal) else x) for x in row.values()] for row in r]


async def block_cases() -> list[dict]:
    """(b) one fully specified question for EVERY block, rotating scheme / measure / year / phrasing."""
    blocks = await fetch("SELECT lgd_block, lgd_district, COUNT(*) FROM curated.v_pmay WHERE lgd_block IS NOT NULL "
                         "GROUP BY 1, 2 ORDER BY 1, 3 DESC")
    seen, out = set(), []
    for b, d, _n in blocks:
        if b in seen:
            continue
        seen.add(b)
        out.append((b, d))
    C = []
    k = 0
    for i, (b, d) in enumerate(out):
        for j in range(2):                      # two different measures per block
            scheme, measure, tpl, unit, years, bcol = MEASURES[(i * 2 + j) % len(MEASURES)]
            y = years[(i + j) % len(years)]
            if scheme == "Focus Plus":
                have = await fetch(f"SELECT COUNT(*) FROM curated.v_focus_plus WHERE UPPER(block_name_raw) = '{q(b)}'")
                if not have[0][0]:
                    scheme, measure, tpl, unit, years, bcol = MEASURES[0]
                    y = years[i % len(years)]
            w = f"{bcol} = '{q(b)}' AND year_key = {y}"
            sql = tpl.format(w=w)
            val = (await fetch(sql))[0][0]
            phr = ONE_SHOT[k % len(ONE_SHOT)]
            k += 1
            s = phr.format(scheme=scheme, measure=measure, fy=FY[y], district=title(d), block=title(b))
            t = turn(s, figures=[fig(sql, unit)], pause=False, schemes=[scheme], place=b, year=y, max_s=25)
            if val is None or val == 0:
                t.pop("figures")
                t["any_of"] = [["no ", "not ", "0", "nil", "zero"]]
            C.append(case(f"BLK-{b.replace(' ', '_')}-{j}", "block-oneshot", f"{scheme}/{measure}", [t],
                          src="block list from curated.v_pmay (LGD); one breath: scheme, measure, FY, district, block"))
    return C


def vague_cases() -> list[dict]:
    """(c) the same information over a vague start -> ask-back -> pick -> follow-ups."""
    C = []
    RB = "RI BHOI"
    C.append(case("VAG-01", "vague", "no-scheme-district", [
        turn("How many beneficiaries are there in Ri Bhoi?", pause=True, max_s=20),
        turn("Focus Plus", figures=[fig(f"SELECT COUNT(DISTINCT beneficiary_key) FROM {FP} WHERE lgd_district = '{RB}'",
                                        "count")], pause=False, schemes=["Focus Plus"], place=RB, max_s=25),
        turn("what about 2022-23?", figures=[fig(f"SELECT COUNT(DISTINCT beneficiary_key) FROM {FP} WHERE "
                                                 f"lgd_district = '{RB}' AND year_key = 2022", "count")], pause=False,
             place=RB, year=2022, max_s=25)]))
    C.append(case("VAG-02", "vague", "no-scheme-block", [
        turn("Show me the data for Mawphlang block", pause=True, max_s=20),
        turn("PMAY-G", pause=False, schemes=["PMAY-G"], max_s=25),
        turn("how many were completed?", figures=[fig(f"SELECT COUNT(*) FROM {PM} WHERE is_completed AND "
                                                      "lgd_block = 'MAWPHLANG'", "count")], pause=False, max_s=25)]))
    C.append(case("VAG-03", "vague", "focus-which", [
        turn("Focus figures for Ri Bhoi", pause=True, max_s=20),
        turn("the second one", pause=False, max_s=25)]))
    C.append(case("VAG-04", "vague", "cm-elevate-dataset", [
        turn("CM Elevate applications by district", pause=True, max_s=20),
        turn("CM Elevate", rows=[{"any": [rows("SELECT lgd_district, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate "
                                               "WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC", take=3),
                                          rows("SELECT lgd_district, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate "
                                               "WHERE lgd_district IS NOT NULL AND data_verified = 'Valid' GROUP BY 1 "
                                               "ORDER BY 2 DESC", take=3)]}],
             pause=False, max_s=25)]))
    C.append(case("VAG-05", "vague", "no-measure", [
        turn("What about MGNREGA in Tikrikilla?", pause=False, schemes=["MGNREGA"], max_s=25),
        turn("and the expenditure in 2024-25?", figures=[fig(f"SELECT ROUND(SUM(total_exp), 2) FROM {EXP} WHERE "
                                                             "lgd_block = 'TIKRIKILLA' AND year_key = 2024", "lakh")],
             pause=False, year=2024, max_s=25)]))
    C.append(case("VAG-06", "vague", "houses-no-scheme", [
        turn("How many houses were completed in Ri Bhoi?",
             figures=[fig(f"SELECT COUNT(*) FROM {PM} WHERE is_completed AND lgd_district = '{RB}'", "count")],
             pause=False, max_s=25)]))
    C.append(case("VAG-07", "vague", "single-year-measure-no-year", [
        turn("MGNREGA households employed in Ri Bhoi", pause=False, any_of=[["2022-23", "2023-24", "2024-25",
                                                                              "2025-26", "which year", "financial year"]],
             max_s=25)]))
    # a block name that sits in two districts in some datasets (DALU: West Garo Hills in LGD, South West Garo
    # Hills in raw data)
    C.append(case("VAG-08", "vague", "block-two-districts", [
        turn("MGNREGA person-days in Dalu block in 2024-25",
             figures=[fig(f"SELECT SUM(person_days) FROM {EMP} WHERE lgd_block = 'DALU' AND year_key = 2024", "count")],
             pause=False, place="DALU", year=2024, max_s=25)]))
    # a block that the scheme's raw data files under two districts (Focus Plus: Zikzak 6,656 in South West Garo Hills
    # + 25 in West Garo Hills; LGD puts Zikzak in South West Garo Hills)
    zz = "SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE UPPER(block_name_raw) = 'ZIKZAK'"
    C.append(case("VAG-11", "vague", "block-in-two-districts", [
        turn("Focus Plus beneficiaries in Zikzak block", pause="either",
             figures=[{"any": [fig(zz, "count"), fig(zz + " AND lgd_district = 'SOUTH WEST GARO HILLS'", "count")]}],
             max_s=25)]))
    C.append(case("VAG-12", "vague", "block-wrong-district", [
        turn("Focus Plus beneficiaries in Zikzak block of West Garo Hills", pause="either",
             any_of=[["South West Garo Hills"]], max_s=25)]))
    C.append(case("VAG-09", "vague", "only-a-place", [
        turn("West Garo Hills", pause=True, max_s=20),
        turn("MGNREGA", figures=[pd_wgh_fig()], pause=False, schemes=["MGNREGA"], max_s=25)]))
    C.append(case("VAG-10", "vague", "only-a-year", [
        turn("What happened in 2023-24?", pause=True, max_s=20),
        turn("PMAY-G", figures=[fig(f"SELECT COUNT(*) FROM {PM} WHERE year_key = 2023", "count")], pause=False,
             year=2023, max_s=25)]))
    return C


def pd_wgh_fig():
    return fig(f"SELECT SUM(person_days) FROM {EMP} WHERE lgd_district = '{WGH}'", "count")


def chain_cases() -> list[dict]:
    """(d) the follow-up chains as the user speaks them."""
    C = []
    y = 2024
    pdd = rows(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = {y} GROUP BY 1 ORDER BY 2 DESC")
    wb = f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE lgd_district = '{WGH}' AND year_key = {y} GROUP BY 1 ORDER BY 2"
    C.append(case("CH-01", "chain", "district-block-rank-year-views", [
        turn("MGNREGA person-days by district in FY 2024-25", rows=[pdd], pause=False, year=y, max_s=25),
        turn("Okay, could you break down West Garo Hills by the blocks?", rows=[rows(wb + " DESC")], pause=False,
             place=WGH, year=y, max_s=25),
        turn("top 3", rows=[rows(wb + " DESC", take=3)], pause=False, max_s=25),
        turn("which is the lowest", rows=[rows(wb + " ASC", take=1)], pause=False, max_s=25),
        turn("show it as a bar chart", pause=False, chart="bar", max_s=10)]))
    C.append(case("CH-02", "chain", "district-year-swap-views", [
        turn("MGNREGA person-days by district in FY 2024-25", rows=[pdd], pause=False, year=y, max_s=25),
        turn("what about 2023-24?", rows=[rows(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 "
                                               "GROUP BY 1 ORDER BY 2 DESC")], pause=False, year=2023, max_s=25),
        turn("show it as a map", pause=False, max_s=10),
        turn("show it as a pie chart", pause=False, max_s=10),
        turn("show it as a table", pause=False, max_s=10)]))
    sd = rows(f"SELECT lgd_district, COUNT(*) FROM {PM} GROUP BY 1 ORDER BY 2 DESC")
    C.append(case("CH-03", "chain", "only-place-then-block-then-year", [
        turn("PMAY-G houses sanctioned by district", rows=[sd], pause=False, max_s=25),
        turn("only East Khasi Hills", figures=[fig(f"SELECT COUNT(*) FROM {PM} WHERE lgd_district = '{EKH}'", "count")],
             pause=False, place=EKH, max_s=25),
        turn("break it down by block", rows=[rows(f"SELECT lgd_block, COUNT(*) FROM {PM} WHERE lgd_district = '{EKH}' "
                                                  "GROUP BY 1 ORDER BY 2 DESC")], pause=False, place=EKH, max_s=25),
        turn("only Mawphlang block", figures=[fig(f"SELECT COUNT(*) FROM {PM} WHERE lgd_block = 'MAWPHLANG'", "count")],
             pause=False, place="MAWPHLANG", max_s=25)]))
    C.append(case("CH-04", "chain", "rank-then-year", [
        turn("Focus Legacy amount disbursed by district",
             rows=[rows(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FL} WHERE lgd_district IS NOT NULL GROUP BY 1 "
                        "ORDER BY 2 DESC", "rupees")], pause=False, max_s=25),
        turn("which district has the lowest",
             rows=[rows(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FL} WHERE lgd_district IS NOT NULL GROUP BY 1 "
                        "ORDER BY 2 ASC", "rupees", take=1)], pause=False, max_s=25),
        turn("what about 2024-25?",
             rows=[rows(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FL} WHERE lgd_district IS NOT NULL AND "
                        "year_key = 2024 GROUP BY 1 ORDER BY 2 ASC", "rupees", take=1)], pause=False, year=2024,
             max_s=25)]))
    ng = f"lgd_district = '{NGH}'"
    C.append(case("CH-05", "chain", "year-step-block-only", [
        turn("MGNREGA expenditure in North Garo Hills in 2023-24",
             figures=[fig(f"SELECT ROUND(SUM(total_exp), 2) FROM {EXP} WHERE {ng} AND year_key = 2023", "lakh")],
             pause=False, place=NGH, year=2023, max_s=25),
        turn("and the previous year?",
             figures=[fig(f"SELECT ROUND(SUM(total_exp), 2) FROM {EXP} WHERE {ng} AND year_key = 2022", "lakh")],
             pause=False, place=NGH, year=2022, max_s=25),
        turn("break that down by block",
             rows=[rows(f"SELECT lgd_block, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE {ng} AND year_key = 2022 GROUP BY 1 "
                        "ORDER BY 2 DESC", "lakh")], pause=False, year=2022, max_s=25),
        turn("only Resubelpara",
             figures=[fig(f"SELECT ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_block = 'RESUBELPARA' AND year_key = 2022",
                          "lakh")], pause=False, place="RESUBELPARA", year=2022, max_s=25)]))
    C.append(case("CH-06", "chain", "for-the-same-other-district", [
        turn("PMAY-G houses completed in West Garo Hills by block",
             rows=[rows(f"SELECT lgd_block, COUNT(*) FROM {PM} WHERE is_completed AND lgd_district = '{WGH}' GROUP BY 1 "
                        "ORDER BY 2 DESC")], pause=False, max_s=25),
        turn("Could you do the same for East Garo Hills?",
             rows=[rows(f"SELECT lgd_block, COUNT(*) FROM {PM} WHERE is_completed AND lgd_district = 'EAST GARO HILLS' "
                        "GROUP BY 1 ORDER BY 2 DESC")], pause=False, place="EAST GARO HILLS", max_s=25)]))
    C.append(case("CH-07", "chain", "year-by-year-district", [
        turn("MGNREGA person-days in Ri Bhoi by financial year",
             rows=[rows(f"SELECT financial_year_short, SUM(person_days) FROM {EMP} WHERE lgd_district = 'RI BHOI' GROUP BY 1 "
                        "ORDER BY 1")], pause=False, max_s=25),
        turn("show it as a line chart", pause=False, chart="line", max_s=10)]))
    return C


def voice_cases(blk: list[dict]) -> list[dict]:
    """(e) the voice path: what the voice engine's shaper SENDS today (log_bank_shaper.py output, 16 Nov 01:35)
    for the user's spoken chains, asked through the typed pipeline with the conversation before it."""
    C = []
    exp_fy = rows(f"SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM {EXP} GROUP BY 1 ORDER BY 1", "lakh")
    C.append(case("VOX-01", "voice", "shaped: fy-then-district-blocks", [
        turn("Show me the Meghalaya expenditure per financial across all districts?", rows=[exp_fy], pause=False,
             max_s=25),
        turn("Break down North Garo Hills by the blocks?",
             rows=[rows(f"SELECT lgd_block, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district = '{NGH}' GROUP BY 1 "
                        "ORDER BY 2 DESC", "lakh")], pause=False, place=NGH, max_s=25)]))
    wgh_pd_blocks = rows(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE lgd_district = '{WGH}' GROUP BY 1 "
                         "ORDER BY 2 DESC")
    C.append(case("VOX-02", "voice", "shaped: multi-sentence place+block", [
        turn("Show me MGNREGA person-days generated by district", pause=False, max_s=25),
        turn("For West Garo Hills? Can you break it down by block?", rows=[wgh_pd_blocks], pause=False, place=WGH,
             max_s=25)]))
    C.append(case("VOX-03", "voice", "shaped: two districts by block", [
        turn("Show me the MGNREGA expenditure by district", pause=False, max_s=25),
        turn("Break down East and West Khasi Hills by the block for the same.",
             rows=[rows(f"SELECT lgd_block, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district IN ('{EKH}', '{WKH}') "
                        "GROUP BY 1 ORDER BY 2 DESC", "lakh")], pause=False, has=["East Khasi Hills"], max_s=30)]))
    C.append(case("VOX-04", "voice", "shaped: multi-sentence headline", [
        turn("Okay, could you give me the headline? Can you give me the figure of MGNREGA for West Garo Hills?",
             figures=[fig(f"SELECT SUM(person_days) FROM {EMP} WHERE lgd_district = '{WGH}'", "count")], pause=False,
             not_route="knowledge", max_s=25)]))
    C.append(case("VOX-05", "voice", "shaped: same thing other scheme", [
        turn("Show me MGNREGA person-days generated by district", pause=False, max_s=25),
        turn("Show me the same thing for PMAY-G", rows=[rows(f"SELECT lgd_district, COUNT(*) FROM {PM} GROUP BY 1 "
                                                             "ORDER BY 2 DESC")], pause=False, schemes=["PMAY-G"],
             max_s=25)]))
    C.append(case("VOX-06", "voice", "shaped: year step", [
        turn("MGNREGA expenditure in North Garo Hills in 2023-24", pause=False, max_s=25),
        turn("what about the year before?",
             figures=[fig(f"SELECT ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district = '{NGH}' AND year_key = 2022",
                          "lakh")], pause=False, year=2022, max_s=25)]))
    C.append(case("VOX-07", "voice", "shaped: year swap on a breakdown", [
        turn("Show me MGNREGA person-days generated by district", pause=False, max_s=25),
        turn("and what about 2023-24", rows=[rows(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 "
                                                  "GROUP BY 1 ORDER BY 2 DESC")], pause=False, year=2023, max_s=25)]))
    C.append(case("VOX-08", "voice", "shaped: headline every scheme after compare", [
        turn("Compare the total beneficiaries in PMAY-G and MGNREGA?", pause=False, max_s=25),
        turn("Okay, now give me the headline figure of every scheme", pause=False,
             rw_lacks=["Compare", "compare"], max_s=30)]))
    C.append(case("VOX-09", "voice", "shaped: what about place (block lost by the shaper)", [
        turn("Give me the data of PMAY-G for Meghalaya as of all the districts?", pause=False, max_s=25),
        turn("what about West Garo Hills?", pause=False, max_s=25)]))
    # "block wise" in every way the user says it, after a district breakdown (shaper sends these unchanged)
    sanc_d = rows(f"SELECT lgd_district, COUNT(*) FROM {PM} GROUP BY 1 ORDER BY 2 DESC")
    for i, (said, dist) in enumerate([
            ("break West Garo Hills block-wise", WGH), ("West Garo Hills block wise please", WGH),
            ("show me West Garo Hills by blocks", WGH), ("give me the blockwise figures for Ri Bhoi", "RI BHOI"),
            ("Ri Bhoi, block wise", "RI BHOI"), ("and for East Khasi Hills block wise?", EKH),
            ("Can you break down West Garo Hills by blockwise?", WGH),
            ("which block is the highest in West Garo Hills", WGH)]):
        C.append(case(f"BW-{i:02d}", "blockwise", "district-then-blockwise", [
            turn("Show me PMAY-G houses sanctioned by district", rows=[sanc_d], pause=False, max_s=25),
            turn(said, rows=[rows(f"SELECT lgd_block, COUNT(*) FROM {PM} WHERE lgd_district = '{dist}' GROUP BY 1 "
                                  "ORDER BY 2 DESC", take=(1 if "highest" in said else "all"))],
                 pause=False, place=dist, schemes=["PMAY-G"], max_s=25)]))
    # 01:50: what the shaper sends today for the spoken headline / grouping sentences
    C.append(case("VOX-10", "voice", "shaped: by FY across all the districts", [
        turn("Show me MGNREGA person-days by financial year across all the districts?",
             rows=[rows(f"SELECT financial_year_short, SUM(person_days) FROM {EMP} GROUP BY 1 ORDER BY 1")], pause=False,
             max_s=25)]))
    C.append(case("VOX-11", "voice", "shaped: headline no measure", [
        turn("Give me the MGNREGA figure for Ri Bhoi?",
             figures=[fig(f"SELECT SUM(person_days) FROM {EMP} WHERE lgd_district = 'RI BHOI'", "count")], pause=False,
             not_route="knowledge", max_s=25)]))
    C.append(case("VOX-12", "voice", "shaped: top three blocks", [
        turn("Show me MGNREGA person-days generated by district", pause=False, max_s=25),
        turn("Give me the top three blocks in West Garo Hills",
             rows=[rows(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE lgd_district = '{WGH}' GROUP BY 1 "
                        "ORDER BY 2 DESC", take=3)], pause=False, place=WGH, max_s=25)]))
    forms = ["Tell me the {scheme} {measure} for {b} block in {d} for {fy}?",
             "Show me {b} block, {d} district, the {scheme} {measure} in {fy}.",
             "{scheme} {measure}, {d}, {b} block, financial year {fy}, please."]
    for i, c in enumerate([c for c in blk if c["id"].endswith("-0")]):
        t = dict(c["turns"][0])
        scheme, measure = c["shape"].split("/", 1)
        q0 = t["q"]
        d = next(x for x in ("Eastern West Khasi Hills", "South West Garo Hills", "South West Khasi Hills",
                             "East Garo Hills", "East Jaintia Hills", "East Khasi Hills", "North Garo Hills", "Ri Bhoi",
                             "South Garo Hills", "West Garo Hills", "West Jaintia Hills", "West Khasi Hills")
                 if x.lower() in q0.lower())
        t["q"] = forms[i % 3].format(scheme=scheme, measure=measure, b=title(t["place"]), d=d, fy=FY[t["year"]])
        C.append(case(c["id"].replace("BLK-", "BLKV-"), "block-voice-shaped", c["shape"], [t],
                      src="the shaper's output for the spoken one-breath block question (log_bank_shaper.py part B)"))
    return C


HEADLINE = {   # each scheme's headline figure (what its overview card leads with), own SQL
    "MGNREGA": ("SELECT SUM(person_days) FROM curated.v_employment WHERE {w}", None),
    "PMAY-G": ("SELECT COUNT(*) FROM curated.v_pmay WHERE {w}", None),
    "Focus Legacy": ("SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE {w}", None),
    "Focus Plus": ("SELECT COUNT(*) FROM curated.v_focus_plus WHERE {w}",
                   "SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE {w}"),
    "CMSS": ("SELECT COUNT(*) FROM curated.v_cmss WHERE {w}", None),
}


def headline_cases() -> list[dict]:
    """(f) KIND 2 permutations: a scheme + a place and NO measure ("the figure / numbers / overview of X for P")
    must give the scheme's headline figure for that place, never the knowledge route."""
    C = []
    places = [("West Garo Hills", "lgd_district = 'WEST GARO HILLS'"), ("Ri Bhoi", "lgd_district = 'RI BHOI'"),
              ("East Khasi Hills", "lgd_district = 'EAST KHASI HILLS'"), ("Tikrikilla block", "lgd_block = 'TIKRIKILLA'"),
              ("Mawphlang block", "lgd_block = 'MAWPHLANG'")]
    phr = ["Give me the figure of {s} for {p}?", "What are the {s} numbers in {p}?", "{s} in {p}.",
           "Show me {s} for {p}", "How is {s} doing in {p}?", "Give me an overview of {s} in {p}",
           "What's the {s} figure for {p}?", "Okay, so what about {s} in {p}?"]
    k = 0
    for i, (s, (sql, alt)) in enumerate(HEADLINE.items()):
        for j, (p, w) in enumerate(places):
            if s == "Focus Plus" and "block" in p:
                w = w.replace("lgd_block", "UPPER(block_name_raw)")
            if s == "CMSS" and j > 2:
                continue
            f = fig(sql.format(w=w), "count")
            if alt:
                f = {"any": [fig(sql.format(w=w), "count"), fig(alt.format(w=w), "count")]}
            q0 = phr[k % len(phr)].format(s=s, p=p)
            k += 1
            C.append(case(f"HEAD-{i}{j}", "headline-no-measure", f"{s}/{p}", [
                turn(q0, figures=[f], pause=False, not_route="knowledge", max_s=25)]))
    return C


def grouping_cases() -> list[dict]:
    """(g) the grouping words the user says ("per financial year across all districts", "for every financial year",
    "district wise" ...) must group by that dimension."""
    C = []
    meas = [("MGNREGA expenditure", f"ROUND(SUM(total_exp), 2) FROM {EXP}", "lakh"),
            ("PMAY-G houses sanctioned", f"COUNT(*) FROM {PM}", "count"),
            ("MGNREGA person-days", f"SUM(person_days) FROM {EMP}", "count"),
            ("Focus Legacy amount disbursed", f"SUM(amount_disbursed) FROM {FL}", "rupees")]
    fy = ["Show me the {m} for every financial year", "{m} per financial year across all districts",
          "{m} year wise", "Give me the {m} for each year", "How did the {m} move year by year?",
          "Okay, can you show me {m} financial year wise for the whole state"]
    dist = ["{m} district wise", "Show me the {m} for every district", "{m} per district",
            "What is the {m} in each district?", "Show me {m} across all the districts"]
    k = 0
    for i, (m, expr, unit) in enumerate(meas):
        for j in range(3):
            q0 = fy[k % len(fy)].format(m=m)
            C.append(case(f"GRP-FY-{i}{j}", "grouping-words", "by financial year", [
                turn(q0, rows=[rows(f"SELECT financial_year_short, {expr} WHERE year_key IS NOT NULL GROUP BY 1 "
                                    "ORDER BY 1", unit)], pause=False, max_s=25)]))
            q1 = dist[k % len(dist)].format(m=m)
            C.append(case(f"GRP-D-{i}{j}", "grouping-words", "by district", [
                turn(q1, rows=[rows(f"SELECT lgd_district, {expr} WHERE lgd_district IS NOT NULL GROUP BY 1 "
                                    "ORDER BY 2 DESC", unit)], pause=False, max_s=25)]))
            k += 1
    return C


async def drill_cases() -> list[dict]:
    """(h) every district drilled the way the user speaks it: <scheme measure> by district -> break down <district>
    by the blocks -> top 3 -> which is the lowest -> only <its top block> -> what about <another FY>."""
    C = []
    plan = [  # (scheme measure said, expr FROM view, unit, block column, year for the last turn)
        ("MGNREGA person-days", f"SUM(person_days) FROM {EMP}", "count", "lgd_block", 2023),
        ("PMAY-G houses sanctioned", f"COUNT(*) FROM {PM}", "count", "lgd_block", 2022),
        ("MGNREGA expenditure", f"ROUND(SUM(total_exp), 2) FROM {EXP}", "lakh", "lgd_block", 2024),
        ("PMAY-G houses completed", f"COUNT(*) FROM {PM} WHERE is_completed AND TRUE", "count", "lgd_block", 2020),
        ("Focus Legacy producer groups", f"COUNT(DISTINCT pg_id) FROM {FL}", "count", "lgd_block", 2025),
    ]
    dists = [r[0] for r in await fetch("SELECT DISTINCT lgd_district FROM curated.v_pmay WHERE lgd_district IS NOT NULL "
                                       "ORDER BY 1")]
    spoken_drill = ["Okay, could you break down {d} by the blocks?", "Now show me {d} block wise",
                    "Can you break {d} down by block for the same?", "okay and for {d}, by block please"]
    for i, d in enumerate(dists):
        m, expr, unit, bc, y = plan[i % len(plan)]
        if " WHERE " in expr:
            base, cond = expr.split(" WHERE ", 1)
            w = lambda extra: f"{base} WHERE {cond} AND {extra}"  # noqa: E731
        else:
            w = lambda extra, expr=expr: f"{expr} WHERE {extra}"  # noqa: E731
        blocks_sql = f"SELECT {bc}, {w(f'lgd_district = {chr(39)}{q(d)}{chr(39)}')} GROUP BY 1 ORDER BY 2 DESC"
        brows = await fetch(blocks_sql)
        if not brows:
            continue
        top = brows[0][0]
        C.append(case(f"DRL-{d.replace(' ', '_')}", "district-drill", f"{m}: {d}", [
            turn(f"{m} by district", rows=[rows(f"SELECT lgd_district, {w('lgd_district IS NOT NULL')} GROUP BY 1 "
                                                "ORDER BY 2 DESC", unit)], pause=False, max_s=25),
            turn(spoken_drill[i % len(spoken_drill)].format(d=title(d)), rows=[rows(blocks_sql, unit)], pause=False,
                 place=d, max_s=25),
            turn("top 3", rows=[rows(blocks_sql, unit, take=3)], pause=False, max_s=25),
            turn("which is the lowest", rows=[rows(blocks_sql.replace("ORDER BY 2 DESC", "ORDER BY 2 ASC"), unit,
                                                   take=1)], pause=False, max_s=25),
            turn(f"only {title(top)} block", figures=[fig(f"SELECT {w(f'{bc} = {chr(39)}{q(top)}{chr(39)}')}", unit)],
                 pause=False, place=top, max_s=25),
            turn(f"what about {FY[y]}?",
                 figures=[fig(f"SELECT {w(f'{bc} = {chr(39)}{q(top)}{chr(39)} AND year_key = {y}')}", unit)],
                 pause=False, place=top, year=y, max_s=25)]))
    return C


async def main():
    blk = await block_cases()
    cases = log_cases() + blk + vague_cases() + chain_cases() + voice_cases(blk) + headline_cases() + grouping_cases()
    cases += await drill_cases()
    bank = {"bank": "Megh One AI LOG BANK (the user's own questions, every block, vague starts, spoken follow-ups)",
            "built_by": "tests/accuracy/build_log_bank.py", "truth_recorded": "2026-11-16", "cases": cases}
    with open(OUT, "w", encoding="utf-8") as fh:
        yaml.safe_dump(bank, fh, allow_unicode=True, sort_keys=False, width=120)
    print(len(cases), "cases,", sum(len(c["turns"]) for c in cases), "turns ->", os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    asyncio.run(main())
