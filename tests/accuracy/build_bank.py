"""Build tests/accuracy/gold_bank.yaml — the ACCURACY gold bank (2026-11-11).

The bank is written here, in Python, because most of it is families (one question shape
over places, years, wordings); the YAML is what run_gold.py reads. Edit THIS file, then:

    .venv/Scripts/python.exe tests/accuracy/build_bank.py            # writes gold_bank.yaml + records truth
    .venv/Scripts/python.exe tests/accuracy/build_bank.py --no-db    # writes the YAML without recording

Every expected figure carries `sql`: an INDEPENDENT read-only query written by hand against `curated`
(never the pipeline's own SQL or answer). The builder runs each one through the app's read-only pool
(READ ONLY transaction) and stores the value it returned (`value`) and the date (`truth_recorded`);
run_gold.py recomputes them live on every run, so a data reload never makes the bank stale. A figure
copied from a client PDF / the UAT sheet is kept as `ref` (+ `ref_src`); when it disagrees with the SQL
the builder prints both — the SQL wins and the case's `note` says why.

Units (what the figure is, not how it is written): count | lakh (MGNREGA money, stored in lakh ₹) |
rupees | crore | pct | dec. run_gold.py accepts every faithful rendering of each (Indian grouping,
₹ X lakh / ₹ X crore at two decimals, the exact rupee figure).

Aggregates only: no truth query returns a person, a name of a beneficiary or an account.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "tests", "accuracy", "gold_bank.yaml")

# ── small DSL ──────────────────────────────────────────────────────────────────────────


def F(sql, unit="count", label=None, ref=None, ref_src=None, word=None):
    """One expected figure: the first cell of the first row of `sql`. `word`: a word the answer
    must also carry for this reading (e.g. 'valid')."""
    f = {"sql": " ".join(sql.split()), "unit": unit}
    if label:
        f["label"] = label
    if ref is not None:
        f["ref"] = ref
        f["ref_src"] = ref_src
    if word:
        f["word"] = word
    return f


def ANY(*figs, why=""):
    """Two defensible readings: the answer passes if ONE of them holds (each with its own word)."""
    return {"any": list(figs), "why": why}


def R(sql, unit="count", take="all", ref=None, ref_src=None, word=None):
    """A breakdown / ranking: rows of (label..., value). take='all' = every row must be in the answer
    (text or its table) with its own value; take=N = the first N rows in this order."""
    r = {"sql": " ".join(sql.split()), "unit": unit, "take": take}
    if word:
        r["word"] = word
    if ref is not None:
        r["ref"] = ref
        r["ref_src"] = ref_src
    return r


def RANY(*specs, why=""):
    """Two defensible readings of a breakdown: one must hold (each with its own word)."""
    return {"any": list(specs), "why": why}


def ce_rows(group_sql_expr, extra_where="", take="all", order="ORDER BY 2 DESC"):
    """A CM Elevate breakdown: valid-only by default (called 'valid'), or every application."""
    def q(cond):
        wh = " AND ".join(c for c in (cond, extra_where) if c)
        return (f"SELECT {group_sql_expr}, COUNT(DISTINCT request_id) FROM {CEV}"
                f"{' WHERE ' + wh if wh else ''} GROUP BY 1 {order}")
    return RANY(R(q("data_verified = 'Valid'"), take=take, word="valid"), R(q(""), take=take),
                why="D-B1-CME-01: valid-only by default, or every application")


def T(q, *figs, rows=None, schemes=None, pause=False, chart=None, has=(), any_of=(), lacks=(), place=None,
      year=None, strict=False, note=None, route=None):
    t = {"q": q}
    if figs:
        t["figures"] = list(figs)
    if rows:
        t["rows"] = rows if isinstance(rows, list) else [rows]
    if schemes is not None:
        t["schemes"] = schemes
    t["pause"] = pause
    if chart:
        t["chart"] = chart
    if has:
        t["has"] = list(has)
    if any_of:
        t["any_of"] = [list(a) for a in any_of]
    if lacks:
        t["lacks"] = list(lacks)
    if place:
        t["place"] = place
    if year is not None:
        t["year"] = year
    if strict:
        t["strict"] = True
    if note:
        t["note"] = note
    if route:
        t["route"] = route
    return t


def C(cid, cat, shape, src, *turns, note=None):
    c = {"id": cid, "cat": cat, "shape": shape, "src": src, "turns": list(turns)}
    if note:
        c["note"] = note
    return c


MG, PM, FP, CE, FL, CL = "MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy", "CM Elevate Legacy"
EMP, EXP = "curated.v_employment", "curated.v_expenditure"
PMV, FPV, CEV, FLV, CLV = ("curated.v_pmay", "curated.v_focus_plus", "curated.v_cm_elevate", "curated.v_focus_legacy",
                           "curated.v_cm_elevate_disbursement")


def w(*conds):
    conds = [c for c in conds if c]
    return (" WHERE " + " AND ".join(conds)) if conds else ""


def dist(d):
    return f"lgd_district = '{d}'"


def blk(b):
    return f"lgd_block = '{b}'"


def vil(v):
    return f"UPPER(lgd_village_name) = '{v}'"


def yr(y):
    return f"year_key = {y}"


def emp(col, *conds):
    return f"SELECT SUM({col}) FROM {EMP}{w(*conds)}"


def exp_(col, *conds):
    return f"SELECT ROUND(SUM({col}), 2) FROM {EXP}{w(*conds)}"


def pm_count(*conds):
    return f"SELECT COUNT(*) FROM {PMV}{w(*conds)}"


def fp_ben(*conds):
    return f"SELECT COUNT(DISTINCT beneficiary_key) FROM {FPV}{w(*conds)}"


def fp_amt(*conds):
    return f"SELECT SUM(amount_disbursed) FROM {FPV}{w(*conds)}"


def ce_apps(*conds, label="applications"):
    """CM Elevate: the user rule of 2026-10-30 (D-B1-CME-01) counts VALID applications by default and says
    'valid'; a question that asks for all applications gets every one. Both readings are accepted, each
    with its own word (the valid count must be called valid)."""
    valid = w(*conds, "data_verified = 'Valid'")
    return ANY(F(f"SELECT COUNT(DISTINCT request_id) FROM {CEV}{valid}", "count",
                 label=f"valid {label}", word="valid"),
               F(f"SELECT COUNT(DISTINCT request_id) FROM {CEV}{w(*conds)}", "count", label=f"all {label}"),
               why="D-B1-CME-01: valid-only by default (said 'valid'), or every application when all are asked")


def fl_pg(*conds):
    return f"SELECT COUNT(DISTINCT pg_id) FROM {FLV}{w(*conds)}"


def fl_amt(*conds):
    return f"SELECT SUM(amount_disbursed) FROM {FLV}{w(*conds)}"


def cl(col, *conds):
    return f"SELECT SUM({col}) FROM {CLV}{w(*conds)}"


DISTRICTS_TOP = "ORDER BY 2 DESC"

# ── the bank ───────────────────────────────────────────────────────────────────────────
B: list = []
add = B.append

# ════ 1. The brief's goldens (tests/live_chat_golden.py D1-D10, P, S, N) ════
G = "live_chat_golden.py (brief 2026-10-29)"
add(C("G-D1", "mgnrega", "state-year", G + " D1",
      T("Total MGNREGA person-days statewide in FY 2023-24?", F(emp("person_days", yr(2023)), ref="2,72,64,054",
                                                                 ref_src=G), schemes=[MG], year=2023, strict=True)))
add(C("G-D2", "mgnrega", "district-year", G + " D2",
      T("Total MGNREGA expenditure in West Garo Hills in FY 2024-25?",
        F(exp_("total_exp", dist("WEST GARO HILLS"), yr(2024)), "lakh", ref="25,701.49 lakh", ref_src=G),
        schemes=[MG], place="WEST GARO HILLS", year=2024, strict=True)))
add(C("G-D3", "mgnrega", "ranking", G + " D3",
      T("Which district had the most households completing 100 days in FY 2022-23?",
        rows=R(f"SELECT lgd_district, SUM(households_completed_100_days) FROM {EMP} WHERE year_key = 2022 "
               f"GROUP BY 1 ORDER BY 2 DESC", take=1, ref="East Garo Hills 22,049", ref_src=G),
        schemes=[MG], year=2022)))
add(C("G-D4", "mgnrega", "ratio", G + " D4",
      T("Share of women employed in Ri Bhoi FY 2023-24?",
        F(f"SELECT 100.0 * SUM(women_employment_provided) / SUM(persons_employed) FROM {EMP} "
          f"WHERE lgd_district = 'RI BHOI' AND year_key = 2023", "pct", ref="55.76%", ref_src=G),
        F(emp("women_employment_provided", dist("RI BHOI"), yr(2023)), ref="29,942", ref_src=G),
        F(emp("persons_employed", dist("RI BHOI"), yr(2023)), ref="53,700", ref_src=G),
        schemes=[MG], place="RI BHOI", year=2023)))
add(C("G-D5", "pmay", "state-total", G + " D5",
      T("How many PMAY-G houses in total, and how many completed?",
        F(pm_count(), ref="1,71,107", ref_src=G), F(pm_count("is_completed"), ref="1,29,941", ref_src=G),
        F(pm_count("is_in_progress"), label="in progress", ref="41,041", ref_src=G),
        F(f"SELECT COUNT(*) FROM {PMV} WHERE status_name IS NULL OR status_name IN ('Proposed Site', "
          f"'Existing site(Old House)')", label="not started / no status", ref="125", ref_src=G),
        schemes=[PM])))
add(C("G-D6", "pmay", "district-year", G + " D6",
      T("PMAY-G houses sanctioned in East Khasi Hills FY 2019-20?",
        F(pm_count(dist("EAST KHASI HILLS"), yr(2019)), ref="542", ref_src=G), schemes=[PM],
        place="EAST KHASI HILLS", year=2019, strict=True)))
add(C("G-D7", "pmay", "state-total", G + " D7",
      T("Total PMAY-G amount still pending statewide?",
        F(f"SELECT SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) FROM {PMV}", "rupees",
          ref="₹37,49,31,500", ref_src=G), schemes=[PM], note="all years by default: no 'which year?' pause")))
add(C("G-D8", "focus_plus", "state-year", G + " D8",
      T("Focus Plus beneficiaries FY 2022-23 and amount paid?",
        F(fp_ben(yr(2022)), ref="93,286", ref_src=G), F(fp_amt(yr(2022)), "rupees", ref="46.64 crore", ref_src=G),
        schemes=[FP], year=2022,
        note="2026-11-15: no 'provisional' required — that Note was removed by user decision 2026-11-03")))
add(C("G-D9", "focus_legacy", "state-total", G + " D9",
      T("Focus Legacy producer groups and total, all years?",
        F(fl_pg(), ref="11,906", ref_src=G), F(fl_amt(), "rupees", ref="51.01 crore", ref_src=G),
        schemes=[FL], has=["2022-23", "2024-25"], lacks=["LIMIT"],
        note="the Note lists the years the data covers (user decision 2026-11-03), so FY 2023-24 shows as a gap")))
add(C("G-D10", "cm_elevate_legacy", "state-total", G + " D10",
      T("CM Elevate Legacy: number of records, subsidy disbursed, scheme with most records?",
        F(f"SELECT COUNT(*) FROM {CLV}", ref="2,823", ref_src=G),
        F(cl("total_subsidy_disbursement"), "rupees", ref="52.57 crore", ref_src=G),
        rows=R(f"SELECT scheme_name, COUNT(*) FROM {CLV} GROUP BY 1 ORDER BY 2 DESC", take=1,
               ref="Meghalaya Piggery Development Scheme 1,353", ref_src=G),
        schemes=[CL], lacks=["MGNREGA:", "PMAY-G:", "Focus Plus:"])))
add(C("G-P1", "mgnrega", "paraphrase-terse", G + " P1",
      T("MGNREGA person days for the whole state in FY24?", F(emp("person_days", yr(2023))), schemes=[MG],
        year=2023, note="FY24 = FY 2023-24")))
add(C("G-P3", "mgnrega", "ranking", G + " P3",
      T("Which district had the highest number of households that completed 100 days of MGNREGA work in 2022-23?",
        rows=R(f"SELECT lgd_district, SUM(households_completed_100_days) FROM {EMP} WHERE year_key = 2022 "
               f"GROUP BY 1 ORDER BY 2 DESC", take=2), schemes=[MG], year=2022)))
add(C("G-P5", "pmay", "paraphrase-casual", G + " P5",
      T("How many PMAY houses are there in total and how many have been completed?", F(pm_count()),
        F(pm_count("is_completed")), schemes=[PM])))
add(C("G-P7", "pmay", "paraphrase-formal", G + " P7",
      T("How much PMAY-G money is still to be released in Meghalaya?",
        F(f"SELECT SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) FROM {PMV}", "rupees"),
        schemes=[PM])))
add(C("G-P8b", "focus_plus", "paraphrase-formal", G + " P8b",
      T("How many beneficiaries did Focus+ have in FY 2022-23, and how much was paid?", F(fp_ben(yr(2022))),
        F(fp_amt(yr(2022)), "rupees"), schemes=[FP], year=2022)))
add(C("G-P9", "focus_legacy", "paraphrase-casual", G + " P9",
      T("How many producer groups does Focus Legacy have, and how much was disbursed in all?", F(fl_pg()),
        F(fl_amt(), "rupees"), schemes=[FL])))
add(C("G-S1", "mgnrega", "entity-abbrev", G + " S1",
      T("MGNREGA person-days in E Khasi Hills in 2023-24?", F(emp("person_days", dist("EAST KHASI HILLS"), yr(2023)),
                                                               ref="30,61,525", ref_src=G),
        schemes=[MG], place="EAST KHASI HILLS", year=2023, strict=True)))
add(C("G-S2", "pmay", "entity-abbrev", G + " S2",
      T("PMAY-G houses completed in W Garo Hills?", F(pm_count(dist("WEST GARO HILLS"), "is_completed")),
        schemes=[PM], place="WEST GARO HILLS")))
add(C("G-S3", "mgnrega", "comparison-years", G + " S3",
      T("Compare MGNREGA expenditure in FY 2022-23 vs FY 2023-24 statewide",
        F(exp_("total_exp", yr(2022)), "lakh", ref="886.29 crore", ref_src=G),
        F(exp_("total_exp", yr(2023)), "lakh", ref="759.61 crore", ref_src=G),
        schemes=[MG], lacks=["2022 is higher"], chart=None)))
add(C("G-S4", "pmay", "total+ranking", G + " S4",
      T("How many PMAY-G houses in total, and which district has the most?", F(pm_count()),
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} GROUP BY 1 ORDER BY 2 DESC", take=2), schemes=[PM],
        lacks=["West Jaintia"], note="two asks: the total, then the winner (and the runner-up)")))
add(C("G-S5", "mgnrega", "ranking-topn", G + " S5",
      T("Top 5 districts by MGNREGA person-days in FY 2023-24",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 DESC",
               take=5), schemes=[MG], year=2023)))
add(C("G-S6", "mgnrega", "year-series", G + " S6",
      T("MGNREGA expenditure in Ri Bhoi from 2022-23 to 2024-25, year by year",
        rows=R(f"SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE lgd_district = 'RI BHOI' "
               f"AND year_key BETWEEN 2022 AND 2024 GROUP BY 1 ORDER BY 1", "lakh"),
        schemes=[MG], place="RI BHOI")))
add(C("G-N1", "focus_legacy", "negative-year", G + " N1",
      T("Focus Legacy amount disbursed in FY 2023-24?", pause=None,
        any_of=[["no data", "not held", "absent", "not recorded", "no record", "does not hold", "doesn't hold"]],
        has=["2024-25"], lacks=["₹0 ", "₹0.", "is 0", "were 0"],
        note="a year the dataset does not hold: said with the years it does hold, never a zero")))
add(C("G-N2", "cm_elevate", "negative-measure", G + " N2",
      T("Total CM Elevate amount disbursed in East Khasi Hills?", pause=None,
        any_of=[["no amount", "not record", "does not", "doesn't", "Legacy"]], lacks=["₹0"],
        note="CM Elevate (applications) records no money; a money word may pin Legacy (D-064)")))
add(C("G-N3", "mgnrega", "negative-place", G + " N3",
      T("How many MGNREGA person-days in Gotham district in FY 2023-24?", pause=None,
        lacks=["is 0", ": 0", "were 0", "0 person"], note="unknown district: never a silent 0")))
add(C("G-N4", "out_of_scope", "negative-scheme", G + " N4",
      T("How many PM-KISAN beneficiaries are there in Meghalaya?", pause=None, lacks=["₹"],
        note="a scheme not held: said plainly, no figure")))

# ════ 2. The dashboard cards (golden CARD-*), truth written independently ════
CD = "live_chat_golden.py card_cases"
add(C("CARD-mg-pd", "mgnrega", "state-all-years", CD,
      T("Total MGNREGA person-days across all financial years in Meghalaya?", F(emp("person_days"),
                                                                                 ref="9,09,15,181", ref_src="chart PDF #2"),
        schemes=[MG], strict=True)))
add(C("CARD-mg-exp", "mgnrega", "state-all-years", CD,
      T("Total MGNREGA expenditure across all financial years in Meghalaya?", F(exp_("total_exp"), "lakh",
                                                                                ref="3,628.67 crore", ref_src="chart PDF #6"),
        schemes=[MG])))
add(C("CARD-mg-vil", "mgnrega", "state-villages", CD + " + RAG PDF data #7 (72-village gap)",
      T("How many villages had MGNREGA activity in Meghalaya?",
        F(f"SELECT COUNT(DISTINCT village_code) FROM (SELECT village_code FROM {EMP} UNION "
          f"SELECT village_code FROM {EXP}) v", ref="6,491", ref_src="UAT sheet / home card"),
        schemes=[MG], lacks=["6,419"], note="KI-574: villages = an employment OR expenditure record (6,491)")))
add(C("CARD-pm-houses", "pmay", "state-total", CD,
      T("How many PMAY-G houses have been sanctioned in Meghalaya in total?",
        ANY(F(pm_count(), label="all houses (D-060: placeholders are beneficiaries)"),
            F(pm_count("NOT is_placeholder"), label="houses with a sanction (stats card rule)"),
            why="D-060: 'houses sanctioned' excludes the 126 zero-sanction rows on the card; the chat counts all"),
        schemes=[PM])))
add(C("CARD-pm-rel", "pmay", "state-total", CD + " + RAG PDF data #2",
      T("Total PMAY-G amount released in Meghalaya across all years?",
        F(f"SELECT SUM(amount_released) FROM {PMV}", "rupees", ref="2,185.26 crore", ref_src="RAG PDF #2"),
        schemes=[PM])))
add(C("CARD-fp-pay", "focus_plus", "state-count", CD + " + RAG PDF data #10 (count shown as money)",
      T("How many Focus Plus disbursements have been made in total?", F(f"SELECT COUNT(*) FROM {FPV}",
                                                                       ref="3,85,671", ref_src="RAG PDF #10"),
        schemes=[FP], lacks=["Rs. 3,85,671", "₹3,85,671", "3.86 lakh"])))
add(C("CARD-fp-amt", "focus_plus", "state-total", CD + " + RAG PDF data #4",
      T("Total amount disbursed under Focus Plus across all years?", F(fp_amt(), "rupees", ref="119.74 crore",
                                                                      ref_src="RAG PDF #4"),
        schemes=[FP], note="2026-11-15: no 'provisional' required (Note removed, user decision 2026-11-03)")))
add(C("CARD-cme-apps", "cm_elevate", "state-count", CD,
      T("How many CM Elevate applications are there in total?", ce_apps(), schemes=[CE],
        note="KI-699: card 8,9xx (all) vs chat valid-only (D-B1-CME-01); either, each named for what it counts")))
add(C("CARD-fl-mem", "focus_legacy", "state-total", CD + " + RAG PDF data #5",
      T("How many producer groups and memberships have been paid under Focus Legacy?", F(fl_pg()),
        F(f"SELECT SUM(no_of_pg_members) FROM {FLV}", ref="1,02,021", ref_src="RAG PDF #5"), schemes=[FL])))
add(C("CARD-cml-rec", "cm_elevate_legacy", "state-count", CD,
      T("How many records does CM Elevate Legacy have?", F(f"SELECT COUNT(*) FROM {CLV}"), schemes=[CL])))
add(C("CARD-cml-amt", "cm_elevate_legacy", "state-total", CD + " + RAG PDF data #6",
      T("How much has been disbursed under CM Elevate Legacy, split into subsidy and loan?",
        F(cl("total_disbursement"), "rupees", ref="82.90 crore", ref_src="RAG PDF #6"),
        F(cl("total_subsidy_disbursement"), "rupees", ref="52.57 crore", ref_src="RAG PDF #6"),
        F(cl("total_loan_disbursement"), "rupees", ref="30.33 crore", ref_src="RAG PDF #6"), schemes=[CL])))

# ════ 3. UAT PDF — MGNREGA 10/10 and PMAY-G 10/10 (questions typed exactly) ════
U = "UAT Passed Questions PDF (30 Oct 2026)"
add(C("UAT-M01", "mgnrega", "village-year", U + " DATA-001",
      T("What was the total expenditure in MAWJYRSIM during 2022-23?",
        F(exp_("total_exp", vil("MAWJYRSIM"), yr(2022)), "lakh", ref="31.70 lakh", ref_src=U), schemes=[MG],
        place="MAWJYRSIM", year=2022, strict=True)))
add(C("UAT-M02", "mgnrega", "district-year", U + " DATA-002",
      T("What was the total expenditure in West Garo Hills during 2023-24?",
        F(exp_("total_exp", dist("WEST GARO HILLS"), yr(2023)), "lakh", ref="14,880.51 lakh", ref_src=U),
        schemes=[MG], place="WEST GARO HILLS", year=2023, strict=True)))
add(C("UAT-M03", "mgnrega", "block-year", U + " DATA-003",
      T("What was the total expenditure in Gambegre block during 2022-23?",
        F(exp_("total_exp", blk("GAMBEGRE"), yr(2022)), "lakh", ref="1,455.28 lakh", ref_src=U), schemes=[MG],
        place="GAMBEGRE", year=2022, strict=True)))
add(C("UAT-M04", "mgnrega", "constituency-year", U + " DATA-004",
      T("How many persons received employment in Amlarem constituency during 2022-23?",
        F(emp("persons_employed", "assembly_constituency_name = 'AMLAREM'", yr(2022)), ref="5,048", ref_src=U),
        schemes=[MG], place="AMLAREM", year=2022, strict=True)))
add(C("UAT-M05", "mgnrega", "constituency-list", U + " DATA-014",
      T("Which villages in Ampathi constituency received employment in 2023-24?",
        F(f"SELECT COUNT(DISTINCT village_code) FROM {EMP} WHERE assembly_constituency_name = 'AMPATHI' "
          f"AND year_key = 2023 AND households_employed > 0", label="villages", ref="114", ref_src=U),
        schemes=[MG], place="AMPATHI", year=2023)))
add(C("UAT-M06", "mgnrega", "district-year", U + " DATA-015",
      T("How many total person-days were generated in East Khasi Hills during 2023-24?",
        F(emp("person_days", dist("EAST KHASI HILLS"), yr(2023)), ref="30,61,525", ref_src=U), schemes=[MG],
        place="EAST KHASI HILLS", year=2023, strict=True)))
add(C("UAT-M07", "mgnrega", "block-year", U + " DATA-016",
      T("How many households received employment in Nongstoin block during 2025-26?",
        F(emp("households_employed", blk("NONGSTOIN"), yr(2025)), ref="8,323", ref_src=U), schemes=[MG],
        place="NONGSTOIN", year=2025, strict=True)))
add(C("UAT-M08", "mgnrega", "ratio", U + " DATA-021",
      T("What was the average number of person-days per employment household in South West Khasi Hills during 2024-25?",
        F(f"SELECT 1.0 * SUM(person_days) / SUM(households_employed) FROM {EMP} WHERE "
          f"lgd_district = 'SOUTH WEST KHASI HILLS' AND year_key = 2024", "dec", ref="58.51", ref_src=U),
        schemes=[MG], place="SOUTH WEST KHASI HILLS", year=2024)))
add(C("UAT-M09", "mgnrega", "breakdown", U + " DATA-022",
      T("Give me the expenditure breakdown for Myriem during 2023-24.",
        F(exp_("unskilled_wage_exp", vil("MYRIEM"), yr(2023)), "lakh", label="unskilled", ref="17.52", ref_src=U),
        F(exp_("semi_skilled_wage_exp", vil("MYRIEM"), yr(2023)), "lakh", label="semi-skilled", ref="4.58",
          ref_src=U),
        F(exp_("material_exp", vil("MYRIEM"), yr(2023)), "lakh", label="materials", ref="8.77", ref_src=U),
        F(exp_("total_exp", vil("MYRIEM"), yr(2023)), "lakh", label="total", ref="30.87", ref_src=U),
        schemes=[MG], place="MYRIEM", year=2023)))
add(C("UAT-M10", "mgnrega", "ranking", U + " DATA-025",
      T("Which block generated the highest person-days during 2023-24?",
        rows=R(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 DESC",
               take=1, ref="Zikzak 14,40,124", ref_src=U), schemes=[MG], year=2023)))
GAB = vil("GABIL SONGGITCHAM")
add(C("UAT-P01", "pmay", "village", U + " PMAY-OFF-001",
      T("How many PMAY beneficiaries are there in GABIL SONGGITCHAM?", F(pm_count(GAB), ref="345", ref_src=U),
        schemes=[PM], place="GABIL SONGGITCHAM", strict=True)))
add(C("UAT-P02", "pmay", "village-money", U + " PMAY-OFF-002",
      T("What is the total amount sanctioned in GABIL SONGGITCHAM?",
        F(f"SELECT SUM(sanctioned_amount) FROM {PMV} WHERE {GAB}", "rupees", ref="4,48,50,000", ref_src=U),
        schemes=[PM], place="GABIL SONGGITCHAM")))
add(C("UAT-P03", "pmay", "village", U + " PMAY-OFF-004",
      T("How many PMAY houses have been completed in GABIL SONGGITCHAM?", F(pm_count(GAB, "is_completed"), ref="179",
                                                                           ref_src=U),
        schemes=[PM], place="GABIL SONGGITCHAM", strict=True)))
add(C("UAT-P04", "pmay", "breakdown", U + " PMAY-OFF-006",
      T("Give me the house status breakdown for GABIL SONGGITCHAM.",
        rows=R(f"SELECT COALESCE(status_name, 'No status'), COUNT(*) FROM {PMV} WHERE {GAB} GROUP BY 1 ORDER BY 2 DESC",
               ref="Completed 179, Roof Cast 91, Plinth 73, House Sanctioned 2", ref_src=U),
        schemes=[PM], place="GABIL SONGGITCHAM")))
add(C("UAT-P05", "pmay", "village-money", U + " PMAY-OFF-007",
      T("How much sanctioned amount is still to be released in GABIL SONGGITCHAM?",
        F(f"SELECT SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE {GAB}", "rupees",
          ref="10,81,500", ref_src=U), schemes=[PM], place="GABIL SONGGITCHAM")))
add(C("UAT-P06", "pmay", "block", U + " PMAY-OFF-011",
      T("How many PMAY beneficiaries are there in Amlarem block?", F(pm_count(blk("AMLAREM")), ref="2,377", ref_src=U),
        schemes=[PM], place="AMLAREM")))
add(C("UAT-P07", "pmay", "block-money", U + " PMAY-OFF-012",
      T("Give me the PMAY financial summary for Amlarem block.",
        F(f"SELECT SUM(sanctioned_amount) FROM {PMV} WHERE {blk('AMLAREM')}", "rupees", label="sanctioned",
          ref="30,88,80,000", ref_src=U),
        F(f"SELECT SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE {blk('AMLAREM')}", "rupees", label="released",
          ref="29,99,64,500", ref_src=U),
        F(f"SELECT SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE {blk('AMLAREM')}",
          "rupees", label="remaining", ref="89,15,500", ref_src=U), schemes=[PM], place="AMLAREM")))
add(C("UAT-P08", "pmay", "breakdown", U + " PMAY-OFF-014",
      T("Give me the house status breakdown for Amlarem block.",
        rows=R(f"SELECT COALESCE(status_name, 'No status'), COUNT(*) FROM {PMV} WHERE {blk('AMLAREM')} "
               f"GROUP BY 1 ORDER BY 2 DESC", ref="Completed 1,693, Roof Cast 402, Plinth 215, House Sanctioned 66, "
                                                  "Proposed Site 1", ref_src=U),
        schemes=[PM], place="AMLAREM")))
add(C("UAT-P09", "pmay", "district", U + " PMAY-OFF-015",
      T("How many PMAY beneficiaries are there in West Garo Hills?", F(pm_count(dist("WEST GARO HILLS")),
                                                                      ref="33,147", ref_src=U),
        schemes=[PM], place="WEST GARO HILLS", strict=True)))
add(C("UAT-P10", "pmay", "district", U + " PMAY-OFF-017",
      T("How many PMAY houses have been completed in West Garo Hills?",
        F(pm_count(dist("WEST GARO HILLS"), "is_completed"), ref="26,822", ref_src=U), schemes=[PM],
        place="WEST GARO HILLS", strict=True)))

# ════ 4. RAG PDF — data table (Table 2) ════
RG = "RAG Knowledge and Data Test PDF, Table 2 (30 Oct 2026)"
add(C("RAG-D1", "pmay", "state-total+rate", RG + " #1",
      T("How many PMAY-G houses have been sanctioned and completed in Meghalaya, and what is the completion rate?",
        F(pm_count(), ref="1,71,107", ref_src=RG), F(pm_count("is_completed"), ref="1,29,941", ref_src=RG),
        ANY(F(f"SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM {PMV}", "pct",
              label="completed / all houses"),
            F(f"SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM {PMV} WHERE sanctioned_amount > 0",
              "pct", label="completed / sanctioned houses"),
            why="rate over all houses (75.94%) or over the houses with a sanction (126 placeholders out)"),
        schemes=[PM])))
add(C("RAG-D3", "cm_elevate", "count+list", RG + " #3 (FAIL in PDF: routed to documents)",
      T("How many CM Elevate applications are there and how many schemes do they cover?", ce_apps(),
        ANY(F(f"SELECT COUNT(DISTINCT scheme_name) FROM {CEV} WHERE data_verified = 'Valid'", label="schemes (valid)",
              word="valid"),
            F(f"SELECT COUNT(DISTINCT scheme_name) FROM {CEV}", label="schemes", ref="15", ref_src=RG),
            why="schemes the (valid) applications cover, or all 15"),
        schemes=[CE], route="data")))
add(C("RAG-D7", "mgnrega", "state-villages+total", RG + " #7 (PARTIAL: 6,419 not 6,491)",
      T("How many villages had MGNREGA activity and how many person-days were generated in total?",
        F(f"SELECT COUNT(DISTINCT village_code) FROM (SELECT village_code FROM {EMP} UNION "
          f"SELECT village_code FROM {EXP}) v", ref="6,491", ref_src="UAT sheet"),
        F(emp("person_days"), ref="9,09,15,181", ref_src=RG), schemes=[MG], lacks=["6,419"])))
add(C("RAG-D8", "pmay", "hybrid", RG + " #8",
      T("What is the PMAY-G unit assistance per house in Meghalaya, and how much has actually been released in West Garo Hills?",
        F(f"SELECT SUM(amount_released) FROM {PMV} WHERE {dist('WEST GARO HILLS')}", "rupees", ref="425.01 crore",
          ref_src=RG), any_of=[["1.30 lakh", "1,30,000", "130000", "1.3 lakh"]], schemes=None)))
add(C("RAG-D9", "mgnrega", "hybrid", RG + " #9",
      T("How many days of work does MGNREGA guarantee, and how many households completed 100 days in Meghalaya in 2025-26?",
        F(emp("households_completed_100_days", yr(2025)), ref="33,397", ref_src=RG), has=["100"], schemes=None,
        year=2025)))
add(C("RAG-D10", "focus_plus", "count+districts", RG + " #10 (PARTIAL: count shown as money)",
      T("How many FOCUS+ disbursements have been made and in how many districts?",
        F(f"SELECT COUNT(*) FROM {FPV}", ref="3,85,671", ref_src=RG),
        F(f"SELECT COUNT(DISTINCT district_name_raw) FROM {FPV}", label="districts", ref="12", ref_src=RG),
        schemes=[FP], lacks=["Rs. 3,85,671", "₹3,85,671", "Rs 3,85,671", "3.86 lakh"])))

# ════ 5. Chart PDF — 11 working + the 5 'not working' + minor ════
CH = "Chart Test Questions PDF (30 Oct 2026)"
add(C("CH-01", "chart", "breakdown-district", CH + " #1",
      T("PMAY-G houses completed by district",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE is_completed GROUP BY 1 ORDER BY 2 DESC"),
        schemes=[PM])))
add(C("CH-02", "chart", "year-series", CH + " #2",
      T("Show MGNREGA person-days trend over the years as a line chart",
        rows=R(f"SELECT financial_year_short, SUM(person_days) FROM {EMP} GROUP BY 1 ORDER BY 1"),
        schemes=[MG], chart="line")))
add(C("CH-03", "chart", "year-series", CH + " #3",
      T("Show total Focus Legacy amount remitted in each financial year as a line chart",
        rows=R(f"SELECT financial_year_short, SUM(amount_disbursed) FROM {FLV} GROUP BY 1 ORDER BY 1", "rupees"),
        schemes=[FL], chart="line", lacks=["2023-24: ₹0"],
        note="FY 2023-24 absent: a gap, never a zero; the Note lists covered years (user decision 2026-11-03)")))
add(C("CH-04", "chart", "breakdown-status", CH + " #4",
      T("CM Elevate applications by status as a donut chart",
        rows=ce_rows("COALESCE(file_status, '(not recorded)')"),   # D-101 (team, 2026-11-13): the plain file_status column
        schemes=[CE], chart="doughnut",
        note="status = current_file_status (KI-123). Valid-only default may apply: see the result note")))
add(C("CH-05", "chart", "grouped", CH + " #5",
      T("Compare PMAY-G houses sanctioned vs completed by district in a grouped bar chart",
        rows=R(f"SELECT lgd_district, COUNT(*) FILTER (WHERE is_completed) FROM {PMV} GROUP BY 1 ORDER BY 2 DESC"),
        schemes=[PM], chart="grouped_bar", note="completed series checked (sanctioned excludes placeholders or not)")))
add(C("CH-06", "chart", "year-series", CH + " #6",
      T("Show MGNREGA expenditure by financial year as bar chart",
        rows=R(f"SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM {EXP} GROUP BY 1 ORDER BY 1", "lakh"),
        schemes=[MG], chart="bar")))
add(C("CH-07", "chart", "breakdown-district", CH + " #7",
      T("Show MGNREGA person-days by district",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} GROUP BY 1 ORDER BY 2 DESC"), schemes=[MG])))
add(C("CH-08", "chart", "ranking-topn", CH + " #8-9 (pie, then a bar follow-up)",
      T("Top 5 districts by FOCUS+ beneficiaries as a pie chart",
        rows=R(f"SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE lgd_district IS NOT NULL "
               f"GROUP BY 1 ORDER BY 2 DESC", take=5),
        schemes=[FP], chart="pie", note="WGH / SWGH differ by 20 between LGD and source district (KI-065)"),
      T("now show it as a bar chart",
        rows=R(f"SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE lgd_district IS NOT NULL "
               f"GROUP BY 1 ORDER BY 2 DESC", take=5), schemes=[FP], chart="bar")))
add(C("CH-10", "chart", "cross-compare", CH + " #10-11 (comparison, then three chart follow-ups)",
      T("So compare total beneficiaries in PMAY-G and MGNREGA", F(emp("households_employed"), label="MGNREGA households",
                                                                   ref="14,94,437", ref_src=CH),
        F(pm_count(), label="PMAY-G houses", ref="1,71,107", ref_src=CH)),
      T("for above one give me the bar chart", F(emp("households_employed")), F(pm_count()), chart="bar"),
      T("now give me pie chart", F(emp("households_employed")), F(pm_count()), chart="pie"),
      T("give me donut", F(emp("households_employed")), F(pm_count()), chart="doughnut")))
add(C("CH-12", "chart", "unsupported-view", CH + " §2 (horizontal bar drawn vertical)",
      T("MGNREGA person-days by district in 2023-24",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 DESC")),
      T("now show the same as a horizontal bar chart",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 DESC"),
        chart="horizontal_bar", note="the UI has no horizontal bar: either draw it or say so — never claim it")))
add(C("CH-13", "chart", "multi-chart", CH + " §2 (three charts asked, one drawn)",
      T("Show MGNREGA expenditure by financial year as bar chart, pie chart and line chart",
        rows=R(f"SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM {EXP} GROUP BY 1 ORDER BY 1", "lakh"),
        schemes=[MG], chart="multi", lacks=["The following charts", "following charts"])))
add(C("CH-14", "chart", "year-series", CH + " §2 (wrong SQL: DISTINCT year_key)",
      T("Focus Legacy amount remitted by financial year",
        rows=R(f"SELECT financial_year_short, SUM(amount_disbursed) FROM {FLV} GROUP BY 1 ORDER BY 1", "rupees"),
        schemes=[FL])))
add(C("CH-14b", "chart", "unsupported-view", CH + " §2 (area chart)",
      T("Focus Legacy amount remitted by financial year as an area chart",
        rows=R(f"SELECT financial_year_short, SUM(amount_disbursed) FROM {FLV} GROUP BY 1 ORDER BY 1", "rupees"),
        schemes=[FL], chart="unsupported:area")))
add(C("CH-15", "chart", "stacked", CH + " §2 (subsidy + loan by scheme, stacked)",
      T("CM Elevate Legacy subsidy and loan disbursed by scheme as a stacked bar chart",
        rows=[R(f"SELECT scheme_name, SUM(total_subsidy_disbursement) FROM {CLV} GROUP BY 1 ORDER BY 2 DESC", "rupees",
                take=5),
              R(f"SELECT scheme_name, SUM(total_loan_disbursement) FROM {CLV} GROUP BY 1 ORDER BY 2 DESC", "rupees",
                take=5)],
        schemes=[CL], chart="stacked", lacks=["The values are:"])))
add(C("CH-16", "chart", "unsupported-view", CH + " §2 (radar falls back silently)",
      T("Show MGNREGA person-days by district as a radar chart",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} GROUP BY 1 ORDER BY 2 DESC"),
        schemes=[MG], chart="unsupported:radar", lacks=["This radar chart", "radar chart displays", "radar chart shows"])))

# ════ 6. The UAT sheet's shapes (Test Case Results - 30th Sep 26.xlsx), concrete places ════
S = "Test Case Results sheet"
add(C("SH-M005", "mgnrega", "village-year", S + " MGNREGA DATA-005",
      T("How many households received employment in JAKREM during 2023-24?",
        F(emp("households_employed", vil("JAKREM"), yr(2023))), schemes=[MG], place="JAKREM", year=2023, strict=True)))
add(C("SH-M007", "mgnrega", "village-stock", S + " MGNREGA DATA-007",
      T("How many job cards were issued in JAKREM in 2024-25?",
        F(emp("job_cards_issued_total", vil("JAKREM"), yr(2024))), schemes=[MG], place="JAKREM", year=2024)))
add(C("SH-M013", "mgnrega", "unsupported-measure", S + " MGNREGA DATA-013",
      T("What was the administrative expenditure in Gambegre block during 2023-24?", pause=None,
        any_of=[["not populated", "never populated", "not recorded", "not available", "0.00"]], schemes=None,
        note="admin expenditure is never populated at source: said, never estimated")))
add(C("SH-M019", "mgnrega", "ratio", S + " MGNREGA DATA-019",
      T("What percentage of employment persons were women in East Garo Hills in 2022-23?",
        F(f"SELECT 100.0 * SUM(women_employment_provided) / SUM(persons_employed) FROM {EMP} "
          f"WHERE lgd_district = 'EAST GARO HILLS' AND year_key = 2022", "pct"), schemes=[MG],
        place="EAST GARO HILLS", year=2022)))
add(C("SH-M020", "mgnrega", "ratio", S + " MGNREGA DATA-020",
      T("What percentage of employment households completed 100 days in Tikrikilla block in 2023-24?",
        F(f"SELECT 100.0 * SUM(households_completed_100_days) / SUM(households_employed) FROM {EMP} "
          f"WHERE lgd_block = 'TIKRIKILLA' AND year_key = 2023", "pct"), schemes=[MG], place="TIKRIKILLA", year=2023)))
add(C("SH-M023", "mgnrega", "comparison-measures", S + " MGNREGA DATA-023",
      T("Was more spent on wages or materials in JAKREM in 2023-24?",
        F(exp_("unskilled_wage_exp + semi_skilled_wage_exp", vil("JAKREM"), yr(2023)), "lakh", label="wages"),
        F(exp_("material_exp", vil("JAKREM"), yr(2023)), "lakh", label="materials"),
        schemes=[MG], place="JAKREM", year=2023,
        note="wages = unskilled + semi-skilled; an answer giving unskilled only is checked by the figure list")))
add(C("SH-M024", "mgnrega", "ranking", S + " MGNREGA DATA-024",
      T("Which district had the highest expenditure during 2025-26?",
        rows=R(f"SELECT lgd_district, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE year_key = 2025 GROUP BY 1 "
               f"ORDER BY 2 DESC", "lakh", take=1), schemes=[MG], year=2025)))
add(C("SH-M026", "mgnrega", "ranking-village", S + " MGNREGA DATA-026",
      T("Which village generated the highest person-days during 2025-26?",
        rows=R(f"SELECT UPPER(lgd_village_name), SUM(person_days) FROM {EMP} WHERE year_key = 2025 "
               f"GROUP BY village_code, 1 ORDER BY 2 DESC", take=1), schemes=[MG], year=2025)))
add(C("SH-M027", "mgnrega", "ranking", S + " MGNREGA DATA-027",
      T("Which district had the highest women employment during 2023-24?",
        rows=R(f"SELECT lgd_district, SUM(women_employment_provided) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 "
               f"ORDER BY 2 DESC", take=1), schemes=[MG], year=2023)))
add(C("SH-M029", "mgnrega", "combined", S + " MGNREGA DATA-029",
      T("Compare expenditure and person-days in Gambegre block during 2022-23.",
        F(exp_("total_exp", blk("GAMBEGRE"), yr(2022)), "lakh", ref="1,455.28 lakh", ref_src=S),
        F(emp("person_days", blk("GAMBEGRE"), yr(2022)), ref="500,656", ref_src=S), schemes=[MG], place="GAMBEGRE",
        year=2022)))
add(C("SH-M030", "mgnrega", "combined", S + " MGNREGA DATA-030",
      T("Compare total expenditure and employment generated in East Khasi Hills during 2025-26.",
        F(exp_("total_exp", dist("EAST KHASI HILLS"), yr(2025)), "lakh", ref="9,576.58 lakh", ref_src=S),
        F(emp("person_days", dist("EAST KHASI HILLS"), yr(2025)), ref="2,951,690", ref_src=S), schemes=[MG],
        place="EAST KHASI HILLS", year=2025)))
add(C("SH-P005", "pmay", "district", S + " PMAY-OFF-005",
      T("How many houses are still incomplete in Ri Bhoi?",
        ANY(F(pm_count(dist("RI BHOI"), "is_completed IS NOT TRUE"), label="not completed"),
            F(pm_count(dist("RI BHOI"), "is_in_progress"), label="in progress"),
            why="'incomplete' = every house not completed (is_completed NULL on no-status rows), or in progress"),
        schemes=[PM], place="RI BHOI")))
add(C("SH-P008", "pmay", "release-status", S + " PMAY-OFF-008",
      T("How many beneficiaries in JAKREM have received their full sanctioned amount?",
        F(f"SELECT COUNT(*) FROM {PMV} WHERE {vil('JAKREM')} AND sanctioned_amount > 0 AND "
          f"COALESCE(amount_released, 0) >= sanctioned_amount"), schemes=[PM], place="JAKREM")))
add(C("SH-P010", "pmay", "release-status", S + " PMAY-OFF-010",
      T("How many beneficiaries in West Khasi Hills have not received any amount?",
        F(pm_count(dist("WEST KHASI HILLS"), "COALESCE(amount_released, 0) = 0")), schemes=[PM],
        place="WEST KHASI HILLS")))
add(C("SH-P016", "pmay", "district-money", S + " PMAY-OFF-016",
      T("Give me the PMAY financial summary for East Garo Hills.",
        F(f"SELECT SUM(sanctioned_amount) FROM {PMV} WHERE {dist('EAST GARO HILLS')}", "rupees", label="sanctioned"),
        F(f"SELECT SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE {dist('EAST GARO HILLS')}", "rupees",
          label="released"),
        F(f"SELECT SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE "
          f"{dist('EAST GARO HILLS')}", "rupees", label="remaining"), schemes=[PM], place="EAST GARO HILLS")))
add(C("SH-P020", "pmay", "ratio", S + " PMAY-OFF-020",
      T("What percentage of PMAY houses are completed in South Garo Hills?",
        ANY(F(f"SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM {PMV} WHERE "
              f"{dist('SOUTH GARO HILLS')}", "pct"),
            F(f"SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM {PMV} WHERE "
              f"{dist('SOUTH GARO HILLS')} AND sanctioned_amount > 0", "pct"),
            why="over all houses or over houses with a sanction"), schemes=[PM], place="SOUTH GARO HILLS")))
add(C("SH-P021", "pmay", "ratio", S + " PMAY-OFF-021",
      T("What percentage of the sanctioned amount has been released in North Garo Hills?",
        F(f"SELECT 100.0 * SUM(COALESCE(amount_released, 0)) / SUM(sanctioned_amount) FROM {PMV} WHERE "
          f"{dist('NORTH GARO HILLS')}", "pct"), schemes=[PM], place="NORTH GARO HILLS")))
add(C("SH-P023", "pmay", "comparison-places", S + " PMAY-OFF-023",
      T("Compare the sanctioned amounts of Amlarem and Laskein blocks.",
        F(f"SELECT SUM(sanctioned_amount) FROM {PMV} WHERE {blk('AMLAREM')}", "rupees", label="Amlarem"),
        F(f"SELECT SUM(sanctioned_amount) FROM {PMV} WHERE {blk('LASKEIN')}", "rupees", label="Laskein"),
        schemes=[PM])))
add(C("SH-P025", "pmay", "district-year", S + " PMAY-OFF-025",
      T("How many houses were sanctioned and how much was released in Ri Bhoi during 2020-21?",
        F(pm_count(dist("RI BHOI"), yr(2020))),
        F(f"SELECT SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE {dist('RI BHOI')} AND year_key = 2020", "rupees"),
        schemes=[PM], place="RI BHOI", year=2020)))
add(C("SH-C004", "cm_elevate", "breakdown-district", S + " CM-ELEVATE-OFF-004",
      T("How many CM ELEVATE applicants are there in each district?",
        rows=ce_rows("lgd_district", "lgd_district IS NOT NULL"),
        schemes=[CE], note="valid-only default (D-B1-CME-01)")))
add(C("SH-C005", "cm_elevate", "breakdown-scheme", S + " CM-ELEVATE-OFF-005",
      T("How many applicants are there under each CM ELEVATE program?",
        rows=ce_rows("scheme_name", take=5), schemes=[CE], note="valid-only default")))
add(C("SH-C006", "cm_elevate", "district-program", S + " CM-ELEVATE-OFF-006",
      T("How many applicants are there under the Piggery scheme in Ri Bhoi?",
        ce_apps(dist("RI BHOI"), "scheme_name = 'Meghalaya Piggery Development Scheme'"), schemes=[CE],
        place="RI BHOI")))
add(C("SH-C018", "cm_elevate", "pending", S + " CM-ELEVATE-OFF-018 (D-B1-CME-01)",
      T("How many CM ELEVATE applications are pending?",
        F(f"SELECT COUNT(DISTINCT request_id) FROM {CEV} WHERE data_verified = 'Valid' AND "
          f"file_status IN ('Pending', 'Send Back')", label="pending (Valid + Pending/Send Back)"),
        schemes=[CE], note="the user's pending rule; v_cm_elevate now has a plain file_status column")))
add(C("SH-C020", "cm_elevate", "ranking", S + " CM-ELEVATE-OFF-020",
      T("Which districts have the highest number of pending CM ELEVATE applications?", pause=None,
        note="D-099 (user decision 2026-11-03): a new chat asks which CM Elevate dataset first"),
      T("CM Elevate", pause=None,
        note="the dataset pick; plural 'districts' with no N then asks how many (ranking-count-not-specified)"),
      T("top 3",
        rows=R(f"SELECT lgd_district, COUNT(DISTINCT request_id) FROM {CEV} WHERE data_verified = 'Valid' AND "
               f"file_status IN ('Pending', 'Send Back') AND lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
               take=3), schemes=[CE])))
add(C("SH-F002", "focus_plus", "breakdown-district", S + " FOCUS-002",
      T("How many Focus+ beneficiaries are there in each district?",
        rows=R(f"SELECT district_name_raw, COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE district_name_raw IS NOT NULL "
               f"AND UPPER(district_name_raw) NOT IN ('WEST GARO HILLS', 'SOUTH WEST GARO HILLS') GROUP BY 1 ORDER BY 2 DESC"),
        schemes=[FP], note="WGH/SWGH left out of the check: LGD vs source district differ by 20 (KI-065)")))
add(C("SH-F005", "focus_plus", "state-year", S + " FOCUS-005",
      T("What was the total Focus Plus amount disbursed during 2025-26?", F(fp_amt(yr(2025)), "rupees"), schemes=[FP],
        year=2025)))
add(C("SH-F007", "focus_plus", "tranche", S + " FOCUS-007",
      T("How much was disbursed under Focus Plus Tranch 1?", F(fp_amt("tranche_label = 'Tranch 1'"), "rupees"),
        schemes=[FP], note="KI-648: 'Tranch N' is not a place")))
add(C("SH-F008", "focus_plus", "breakdown-gender", S + " FOCUS-008",
      T("Give me the gender-wise breakdown of Focus+ beneficiaries.",
        rows=R(f"SELECT gender, COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE gender IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC"), schemes=[FP], note="12.5K cohort only holds gender")))
add(C("SH-F023", "focus_plus", "ranking", S + " FOCUS-023",
      T("Which district received the highest total Focus Plus disbursement?",
        rows=R(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FPV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", "rupees", take=1), schemes=[FP],
        note="WGH leads on either district column")))
add(C("SH-F024", "focus_plus", "ratio", S + " FOCUS-024",
      T("What is the average Focus Plus amount disbursed per beneficiary?",
        F(f"SELECT 1.0 * SUM(amount_disbursed) / COUNT(DISTINCT beneficiary_key) FROM {FPV}", "dec"), schemes=[FP],
        note="KI-585: ~₹11,316 with a tranche note")))
add(C("SH-F026", "focus_plus", "comparison-places", S + " FOCUS-026",
      T("Compare the number of Focus Plus beneficiaries in East Khasi Hills and North Garo Hills.",
        F(fp_ben(dist("EAST KHASI HILLS"))), F(fp_ben(dist("NORTH GARO HILLS"))), schemes=[FP])))
add(C("SH-L017", "focus_legacy", "district", S + " FOCUS Legacy TC-17",
      T("What is the total number of Focus Legacy PG members in East Khasi Hills?",
        F(f"SELECT SUM(no_of_pg_members) FROM {FLV} WHERE {dist('EAST KHASI HILLS')}"), schemes=[FL],
        place="EAST KHASI HILLS")))
add(C("SH-L018", "focus_legacy", "district-money", S + " FOCUS Legacy TC-18",
      T("What is the total Focus Legacy amount disbursed for West Garo Hills?",
        F(fl_amt(dist("WEST GARO HILLS")), "rupees"), schemes=[FL], place="WEST GARO HILLS")))
add(C("SH-L023", "focus_legacy", "state-year", S + " FOCUS Legacy TC-23",
      T("What was the total Focus Legacy amount remitted in FY 2024-25?", F(fl_amt(yr(2024)), "rupees"), schemes=[FL],
        year=2024)))
add(C("SH-L025", "focus_legacy", "breakdown-district", S + " FOCUS Legacy TC-25",
      T("How many Focus Legacy producer groups are mapped to each district?",
        rows=R(f"SELECT lgd_district, COUNT(DISTINCT pg_id) FROM {FLV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC"), schemes=[FL])))
add(C("SH-L028", "focus_legacy", "constituency", S + " FOCUS Legacy TC-28",
      T("How many Focus Legacy producer groups are mapped to Mawsynram constituency?",
        F(f"SELECT COUNT(DISTINCT f.pg_id) FROM {FLV} f JOIN curated.dim_geography g ON g.geography_key = "
          f"f.geography_key WHERE UPPER(g.ac_name) = 'MAWSYNRAM'"), schemes=[FL], place="MAWSYNRAM")))
add(C("SH-X017", "cm_elevate_legacy", "state-total", S + " CM Elevate Legacy TC-17",
      T("What is the total amount disbursed under CM Elevate Legacy?", F(cl("total_disbursement"), "rupees"),
        schemes=[CL])))
add(C("SH-X018", "cm_elevate_legacy", "breakdown-scheme", S + " CM Elevate Legacy TC-18",
      T("What is the total amount disbursed under each CM Elevate Legacy scheme?",
        rows=R(f"SELECT scheme_name, SUM(total_disbursement) FROM {CLV} GROUP BY 1 ORDER BY 2 DESC", "rupees", take=5),
        schemes=[CL])))
add(C("SH-X021", "cm_elevate_legacy", "breakdown-lender", S + " CM Elevate Legacy TC-21",
      T("How many CM Elevate Legacy applications are associated with each loan entity?",
        rows=R(f"SELECT loan_entity, COUNT(*) FROM {CLV} WHERE loan_entity IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"),
        schemes=[CL])))
add(C("SH-X024", "cm_elevate_legacy", "year-series", S + " CM Elevate Legacy TC-24",
      T("What was the total CM Elevate Legacy disbursement in each financial year?",
        rows=R(f"SELECT financial_year_short, SUM(total_disbursement) FROM {CLV} WHERE year_key IS NOT NULL GROUP BY 1 "
               f"ORDER BY 1", "rupees"), schemes=[CL])))
add(C("SH-X027", "cm_elevate_legacy", "breakdown-district", S + " CM Elevate Legacy TC-27",
      T("What is the total CM Elevate Legacy disbursement amount for each district?",
        rows=R(f"SELECT lgd_district, SUM(total_disbursement) FROM {CLV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", "rupees", take=5), schemes=[CL])))
add(C("SH-X035", "cm_elevate_legacy", "comparison-places", S + " CM Elevate Legacy TC-35",
      T("Compare the number of sanctioned CM Elevate Legacy applications across West Garo Hills and East Khasi Hills.",
        F(f"SELECT COUNT(sanctioned_amount) FROM {CLV} WHERE {dist('WEST GARO HILLS')}"),
        F(f"SELECT COUNT(sanctioned_amount) FROM {CLV} WHERE {dist('EAST KHASI HILLS')}"), schemes=[CL])))

# ════ 7. Paraphrase families: one figure, five ways of asking ════
PF = "paraphrase family"
fams = [
    ("PF-MG", "mgnrega", F(emp("person_days", dist("WEST GARO HILLS"), yr(2023))), [MG], "WEST GARO HILLS", 2023, [
        ("formal", "What was the total number of person-days generated under MGNREGA in West Garo Hills during FY 2023-24?"),
        ("casual", "how many person days did nrega give in west garo hills in 23-24"),
        ("terse", "MGNREGA persondays WGH 2023-24"),
        ("misspelt", "mgnrega persondays in west garo hils 2023 24"),
        ("spoken", "Okay so um, MGNREGA, person-days, West Garo Hills, for twenty twenty three twenty four, please?"),
    ]),
    ("PF-PM", "pmay", F(pm_count(dist("EAST KHASI HILLS"), "is_completed")), [PM], "EAST KHASI HILLS", None, [
        ("formal", "Kindly provide the number of PMAY-G houses completed in East Khasi Hills district."),
        ("casual", "how many pmay houses are done in east khasi hills"),
        ("terse", "PMAY-G completed EKH"),
        ("misspelt", "pmay housses completd in east khasi hils"),
        ("spoken", "So, uh, for East Khasi Hills, how many PMAY gramin houses got completed?"),
    ]),
    ("PF-FP", "focus_plus", F(fp_amt(), "rupees"), [FP], None, None, [
        ("formal", "What is the total amount disbursed under the FOCUS+ scheme across Meghalaya?"),
        ("casual", "how much money has focus plus paid out so far"),
        ("terse", "Focus+ total disbursed"),
        ("misspelt", "focus pluss totel amount disbursd"),
        ("spoken", "Tell me, uh, how much Focus Plus money has gone out overall?"),
    ]),
    ("PF-FL", "focus_legacy", F(fl_amt(yr(2024)), "rupees"), [FL], None, 2024, [
        ("formal", "What was the total amount remitted to producer groups under Focus Legacy in FY 2024-25?"),
        ("casual", "how much did focus legacy pay out in 2024-25"),
        ("terse", "Focus Legacy amount FY25"),
        ("misspelt", "focus legasy amount remited 2024-25"),
        ("spoken", "Um, Focus Legacy, the amount for twenty twenty four twenty five?"),
    ]),
    ("PF-CL", "cm_elevate_legacy", F(cl("total_disbursement"), "rupees"), [CL], None, None, [
        ("formal", "What is the total disbursement, subsidy and loan combined, under CM Elevate Legacy?"),
        ("casual", "how much has cm elevate legacy disbursed in all"),
        ("terse", "CM Elevate Legacy total disbursement"),
        ("misspelt", "cm elevat legacy totl disbursment"),
        ("spoken", "So for CM Elevate Legacy, uh, what's the total disbursed, subsidy plus loan?"),
    ]),
    ("PF-CE", "cm_elevate", ce_apps(dist("WEST GARO HILLS")), [CE], "WEST GARO HILLS", None, [
        ("formal", "How many CM Elevate applications have been received from West Garo Hills district?"),
        ("casual", "how many cm elevate applications came from west garo hills"),
        ("terse", "CM Elevate applications WGH"),
        ("misspelt", "cm elevate aplications west garo hils"),
        ("spoken", "Okay, uh, CM Elevate applications in West Garo Hills, how many?"),
    ]),
]
for fid, cat, fig, schemes, place, year, ways in fams:
    for style, q in ways:
        add(C(f"{fid}-{style}", cat, f"paraphrase-{style}", PF, T(q, fig, schemes=schemes, place=place, year=year)))

# ════ 8. Coverage: scheme × measure × place level × year; rankings; ratios ════
CV = "coverage matrix"
add(C("CV-MG-01", "mgnrega", "state-by-year", CV,
      T("MGNREGA households provided employment in each financial year",
        rows=R(f"SELECT financial_year_short, SUM(households_employed) FROM {EMP} GROUP BY 1 ORDER BY 1"), schemes=[MG])))
add(C("CV-MG-02", "mgnrega", "block-year", CV,
      T("How many women got MGNREGA work in Mawphlang block in 2022-23?",
        F(emp("women_employment_provided", blk("MAWPHLANG"), yr(2022))), schemes=[MG], place="MAWPHLANG", year=2022)))
add(C("CV-MG-03", "mgnrega", "district-all-years", CV,
      T("Total MGNREGA expenditure in South Garo Hills across all years",
        F(exp_("total_exp", dist("SOUTH GARO HILLS")), "lakh"), schemes=[MG], place="SOUTH GARO HILLS")))
add(C("CV-MG-04", "mgnrega", "ranking-topn", CV,
      T("Top 3 blocks by MGNREGA expenditure in 2024-25",
        rows=R(f"SELECT lgd_block, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE year_key = 2024 GROUP BY 1 ORDER BY 2 DESC",
               "lakh", take=3), schemes=[MG], year=2024)))
add(C("CV-MG-05", "mgnrega", "ranking-bottom", CV,
      T("Which district had the lowest MGNREGA person-days in 2023-24?",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 ASC",
               take=1), schemes=[MG], year=2023)))
add(C("CV-MG-06", "mgnrega", "ratio", CV,
      T("What is the cost per person-day under MGNREGA in West Jaintia Hills in 2023-24?",
        F(f"SELECT 100000.0 * (SELECT SUM(total_exp) FROM {EXP} WHERE {dist('WEST JAINTIA HILLS')} AND year_key = 2023) "
          f"/ (SELECT SUM(person_days) FROM {EMP} WHERE {dist('WEST JAINTIA HILLS')} AND year_key = 2023)", "dec",
          label="₹ per person-day"), schemes=[MG], place="WEST JAINTIA HILLS", year=2023)))
add(C("CV-MG-07", "mgnrega", "constituency-year", CV,
      T("How many person-days were generated in Mawsynram constituency in 2024-25?",
        F(emp("person_days", "assembly_constituency_name = 'MAWSYNRAM'", yr(2024))), schemes=[MG], place="MAWSYNRAM",
        year=2024)))
add(C("CV-MG-08", "mgnrega", "comparison-places", CV,
      T("Compare MGNREGA person-days in East Khasi Hills and West Garo Hills in 2023-24",
        F(emp("person_days", dist("EAST KHASI HILLS"), yr(2023))), F(emp("person_days", dist("WEST GARO HILLS"), yr(2023))),
        schemes=[MG], year=2023)))
add(C("CV-MG-09", "mgnrega", "breakdown-district", CV,
      T("MGNREGA expenditure by district in 2022-23",
        rows=R(f"SELECT lgd_district, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE year_key = 2022 GROUP BY 1 ORDER BY 2 DESC",
               "lakh"), schemes=[MG], year=2022)))
add(C("CV-MG-10", "mgnrega", "ratio", CV,
      T("What share of MGNREGA expenditure went to unskilled wages in 2024-25 statewide?",
        F(f"SELECT 100.0 * SUM(unskilled_wage_exp) / SUM(total_exp) FROM {EXP} WHERE year_key = 2024", "pct"),
        schemes=[MG], year=2024)))
add(C("CV-MG-11", "mgnrega", "village-year", CV,
      T("Person-days in UMRNONG village in 2022-23 under MGNREGA",
        F(emp("person_days", vil("UMRNONG"), yr(2022))), schemes=[MG], place="UMRNONG", year=2022, strict=True)))
add(C("CV-MG-12", "mgnrega", "district-stock", CV,
      T("How many MGNREGA job cards were there in Ri Bhoi in 2025-26?",
        F(emp("job_cards_issued_total", dist("RI BHOI"), yr(2025))), schemes=[MG], place="RI BHOI", year=2025)))
add(C("CV-PM-01", "pmay", "state-by-year", CV,
      T("PMAY-G houses sanctioned in each financial year",
        rows=R(f"SELECT financial_year_short, COUNT(*) FROM {PMV} WHERE year_key IS NOT NULL GROUP BY 1 ORDER BY 1"),
        schemes=[PM])))
add(C("CV-PM-02", "pmay", "ranking-topn", CV,
      T("Top 3 blocks by PMAY-G houses completed",
        rows=R(f"SELECT lgd_block, COUNT(*) FROM {PMV} WHERE is_completed GROUP BY 1 ORDER BY 2 DESC", take=3),
        schemes=[PM])))
add(C("CV-PM-03", "pmay", "constituency", CV,
      T("How many PMAY-G houses are there in Ampathi constituency?",
        F(f"SELECT COUNT(*) FROM {PMV} WHERE UPPER(ac_name) = 'AMPATHI'"), schemes=[PM], place="AMPATHI")))
add(C("CV-PM-04", "pmay", "district-money", CV,
      T("How much PMAY-G money has been released in East Jaintia Hills?",
        F(f"SELECT SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE {dist('EAST JAINTIA HILLS')}", "rupees"),
        schemes=[PM], place="EAST JAINTIA HILLS")))
add(C("CV-PM-05", "pmay", "comparison-places", CV,
      T("Compare PMAY-G houses completed in Ri Bhoi and West Jaintia Hills",
        F(pm_count(dist("RI BHOI"), "is_completed")), F(pm_count(dist("WEST JAINTIA HILLS"), "is_completed")),
        schemes=[PM])))
add(C("CV-FP-01", "focus_plus", "block", CV,
      T("How many Focus Plus beneficiaries are there in Selsella block?",
        F(f"SELECT COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE UPPER(block_name_raw) = 'SELSELLA'"), schemes=[FP],
        place="SELSELLA")))
add(C("CV-FP-02", "focus_plus", "district-money", CV,
      T("How much Focus Plus money was disbursed in East Garo Hills?", F(fp_amt(dist("EAST GARO HILLS")), "rupees"),
        schemes=[FP], place="EAST GARO HILLS")))
add(C("CV-FP-03", "focus_plus", "village", CV,
      T("How many Focus Plus beneficiaries are there in JAKREM village?", F(fp_ben(vil("JAKREM"))), schemes=[FP],
        place="JAKREM")))
add(C("CV-CE-01", "cm_elevate", "district", CV,
      T("How many CM Elevate applications are there in East Khasi Hills?", ce_apps(dist("EAST KHASI HILLS")),
        schemes=[CE], place="EAST KHASI HILLS")))
add(C("CV-CE-02", "cm_elevate", "ranking", CV,
      T("Which CM Elevate scheme has the most applications?",
        rows=ce_rows("scheme_name", take=1), schemes=[CE])))
add(C("CV-FL-01", "focus_legacy", "block", CV,
      T("How many Focus Legacy producer groups are there in Mawkyrwat block?", F(fl_pg(blk("MAWKYRWAT"))), schemes=[FL],
        place="MAWKYRWAT")))
add(C("CV-FL-02", "focus_legacy", "ranking", CV,
      T("Which district received the highest Focus Legacy amount?",
        rows=R(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FLV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", "rupees", take=1), schemes=[FL])))
add(C("CV-FL-03", "focus_legacy", "comparison-years", CV,
      T("Compare the total Focus Legacy remittance between FY 2022-23 and FY 2024-25",
        F(fl_amt(yr(2022)), "rupees"), F(fl_amt(yr(2024)), "rupees"), schemes=[FL])))
add(C("CV-CL-01", "cm_elevate_legacy", "district", CV,
      T("How much CM Elevate Legacy subsidy was disbursed in Ri Bhoi?",
        F(cl("total_subsidy_disbursement", dist("RI BHOI")), "rupees"), schemes=[CL], place="RI BHOI")))
add(C("CV-CL-02", "cm_elevate_legacy", "state-year", CV,
      T("How many CM Elevate Legacy applicants were sanctioned in 2024-25?",
        F(f"SELECT COUNT(sanctioned_amount) FROM {CLV} WHERE year_key = 2024"), schemes=[CL], year=2024)))
add(C("CV-CL-03", "cm_elevate_legacy", "lender", CV,
      T("How much CM Elevate Legacy loan was disbursed through LIFCOM?",
        F(cl("total_loan_disbursement", "loan_entity = 'LIFCOM'"), "rupees"), schemes=[CL])))

# ════ 9. Cross-scheme ════
X = "cross-scheme"
add(C("XS-01", "cross", "cross-beneficiaries", X + " (voice bank A2)",
      T("What is the beneficiary count across MGNREGA, PMAY-G, Focus Plus and Focus Legacy?",
        F(emp("households_employed"), label="MGNREGA households"), F(pm_count(), label="PMAY-G houses"),
        F(fp_ben(), label="Focus Plus beneficiaries"), F(f"SELECT SUM(no_of_pg_members) FROM {FLV}",
                                                         label="Focus Legacy members"),
        schemes=None)))
add(C("XS-02", "cross", "cross-money", X + " (voice bank A17)",
      T("How much money has each scheme disbursed?",
        F(exp_("total_exp"), "lakh", label="MGNREGA expenditure"),
        F(f"SELECT SUM(amount_released) FROM {PMV}", "rupees", label="PMAY-G released"),
        F(fp_amt(), "rupees", label="Focus Plus"), F(fl_amt(), "rupees", label="Focus Legacy"),
        F(cl("total_disbursement"), "rupees", label="CM Elevate Legacy"), schemes=None)))
add(C("XS-03", "cross", "cross-district", X,
      T("Compare MGNREGA households employed and PMAY-G houses in Ri Bhoi",
        F(emp("households_employed", dist("RI BHOI"))), F(pm_count(dist("RI BHOI"))), schemes=None, place="RI BHOI")))
add(C("XS-04", "cross", "cross-year", X,
      T("Compare Focus Plus and Focus Legacy amounts in FY 2022-23",
        F(fp_amt(yr(2022)), "rupees"), F(fl_amt(yr(2022)), "rupees"), schemes=None, year=2022)))
add(C("XS-05", "cross", "cross-ranking", X + " (voice bank A13)",
      T("Which district gets the most money across all the schemes that have money?",
        any_of=[["West Garo Hills", "WEST GARO HILLS"]], schemes=None)))
add(C("XS-06", "cross", "cross-three", X + " (voice bank A10)",
      T("Compare the number of beneficiaries and the total amount for Focus Plus, Focus Legacy and CM Elevate Legacy.",
        F(fp_ben()), F(fp_amt(), "rupees"), F(fl_amt(), "rupees"), F(cl("total_disbursement"), "rupees"),
        schemes=None)))
add(C("XS-07", "cross", "cross-block", X + " (voice bank A11)",
      T("In Dalu block, how many MGNREGA households and PMAY-G houses are there?",
        F(emp("households_employed", blk("DALU"))), F(pm_count(blk("DALU"))), schemes=None, place="DALU")))
add(C("XS-08", "cross", "cross-excluding", X,
      T("Total beneficiaries of each scheme excluding MGNREGA",
        F(pm_count()), F(fp_ben()), schemes=None, lacks=["14,94,437"])))

# ════ 10. Follow-up chains (2-4 turns, one conversation) ════
FU = "follow-up chain"
add(C("FU-01", "chain", "and-for-place", FU + " (voice bank C1)",
      T("MGNREGA person-days in East Khasi Hills in 2023-24.", F(emp("person_days", dist("EAST KHASI HILLS"), yr(2023)))),
      T("And for Ri Bhoi?", F(emp("person_days", dist("RI BHOI"), yr(2023))), schemes=[MG], place="RI BHOI", year=2023),
      T("What about the year before?", F(emp("person_days", dist("RI BHOI"), yr(2022))), schemes=[MG], place="RI BHOI",
        year=2022)))
add(C("FU-02", "chain", "only-filter", FU + " (voice bank C2, KI-701)",
      T("Tell me about PMAY-G houses by district.",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} GROUP BY 1 ORDER BY 2 DESC", take=3)),
      T("Only the completed ones.",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE is_completed GROUP BY 1 ORDER BY 2 DESC", take=3),
        schemes=[PM], route="data"),
      T("Top 3 districts.",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE is_completed GROUP BY 1 ORDER BY 2 DESC", take=3),
        schemes=[PM])))
add(C("FU-03", "chain", "add-scheme", FU + " (voice bank C3)",
      T("Compare the number of beneficiaries in Focus Plus and Focus Legacy.", F(fp_ben())),
      T("Same for CM Elevate Legacy.",
        ANY(F(f"SELECT COUNT(sanctioned_amount) FROM {CLV}", label="applicants sanctioned (D-097)"),
            F(f"SELECT COUNT(*) FROM {CLV}", label="records"), why="CM Elevate Legacy beneficiaries = sanctioned or records"),
        any_of=[["CM Elevate Legacy", "Elevate"]])))
add(C("FU-04", "chain", "breakdown-followup", FU,
      T("Total MGNREGA expenditure statewide by financial year",
        rows=R(f"SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM {EXP} GROUP BY 1 ORDER BY 1", "lakh")),
      T("break that down by district for 2023-24",
        rows=R(f"SELECT lgd_district, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE year_key = 2023 GROUP BY 1 "
               f"ORDER BY 2 DESC", "lakh", take=5), schemes=[MG], year=2023),
      T("only West Garo Hills", F(exp_("total_exp", dist("WEST GARO HILLS"), yr(2023)), "lakh"), schemes=[MG],
        place="WEST GARO HILLS", year=2023)))
add(C("FU-05", "chain", "one-of-comparison", FU,
      T("Compare MGNREGA and PMAY-G beneficiaries", F(emp("households_employed")), F(pm_count())),
      T("only PMAY-G", F(pm_count()), schemes=[PM], lacks=["14,94,437"])))
add(C("FU-06", "chain", "clarification", FU + " (voice bank E1)",
      T("Beneficiaries under Focus.", pause=True),
      T("Focus Plus", F(fp_ben()), schemes=[FP])))
add(C("FU-07", "chain", "clarification", FU + " (voice bank E2)",
      T("CM Elevate records in Ri Bhoi.", pause=True),
      T("Applications", ce_apps(dist("RI BHOI")), schemes=[CE], place="RI BHOI")))
add(C("FU-08", "chain", "measure-swap", FU,
      T("How many households got MGNREGA work in West Garo Hills in 2023-24?",
        F(emp("households_employed", dist("WEST GARO HILLS"), yr(2023)))),
      T("and persons?", F(emp("persons_employed", dist("WEST GARO HILLS"), yr(2023))), schemes=[MG],
        place="WEST GARO HILLS", year=2023),
      T("and how many of them were women?", F(emp("women_employment_provided", dist("WEST GARO HILLS"), yr(2023))),
        schemes=[MG], place="WEST GARO HILLS", year=2023)))
add(C("FU-09", "chain", "measure-swap", FU,
      T("PMAY-G houses completed in Ri Bhoi", F(pm_count(dist("RI BHOI"), "is_completed"))),
      T("and the sanctioned amount there?", F(f"SELECT SUM(sanctioned_amount) FROM {PMV} WHERE {dist('RI BHOI')}",
                                              "rupees"), schemes=[PM], place="RI BHOI"),
      T("what percentage of it has been released?",
        F(f"SELECT 100.0 * SUM(COALESCE(amount_released, 0)) / SUM(sanctioned_amount) FROM {PMV} WHERE {dist('RI BHOI')}",
          "pct"), schemes=[PM], place="RI BHOI")))
add(C("FU-10", "chain", "ranking-followup", FU,
      T("Focus Legacy amount by financial year",
        rows=R(f"SELECT financial_year_short, SUM(amount_disbursed) FROM {FLV} GROUP BY 1 ORDER BY 1", "rupees")),
      T("which year had the most?",
        rows=R(f"SELECT financial_year_short, SUM(amount_disbursed) FROM {FLV} GROUP BY 1 ORDER BY 2 DESC", "rupees",
               take=1), schemes=[FL])))
add(C("FU-11", "chain", "and-for-year", FU,
      T("Top 5 blocks by MGNREGA person-days in 2023-24",
        rows=R(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 DESC", take=5)),
      T("and in 2024-25?",
        rows=R(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE year_key = 2024 GROUP BY 1 ORDER BY 2 DESC", take=5),
        schemes=[MG], year=2024)))
add(C("FU-12", "chain", "measure-swap", FU,
      T("CM Elevate Legacy subsidy disbursed by district",
        rows=R(f"SELECT lgd_district, SUM(total_subsidy_disbursement) FROM {CLV} WHERE lgd_district IS NOT NULL "
               f"GROUP BY 1 ORDER BY 2 DESC", "rupees", take=3)),
      T("and the loan?",
        rows=R(f"SELECT lgd_district, SUM(total_loan_disbursement) FROM {CLV} WHERE lgd_district IS NOT NULL "
               f"GROUP BY 1 ORDER BY 2 DESC", "rupees", take=3), schemes=[CL])))
add(C("FU-13", "chain", "compare-with", FU,
      T("Focus Plus beneficiaries in East Garo Hills", F(fp_ben(dist("EAST GARO HILLS")))),
      T("compare with North Garo Hills", F(fp_ben(dist("EAST GARO HILLS"))), F(fp_ben(dist("NORTH GARO HILLS"))),
        schemes=[FP])))
add(C("FU-14", "chain", "measure-swap", FU,
      T("MGNREGA expenditure in Gambegre block in 2022-23", F(exp_("total_exp", blk("GAMBEGRE"), yr(2022)), "lakh")),
      T("and person-days?", F(emp("person_days", blk("GAMBEGRE"), yr(2022))), schemes=[MG], place="GAMBEGRE",
        year=2022)))
add(C("FU-15", "chain", "ranking-flip", FU,
      T("Which district had the most PMAY-G houses sanctioned in 2020-21?",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE year_key = 2020 GROUP BY 1 ORDER BY 2 DESC", take=1)),
      T("and the least?",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE year_key = 2020 GROUP BY 1 ORDER BY 2 ASC", take=1),
        schemes=[PM], year=2020)))
add(C("FU-16", "chain", "breakdown-followup", FU,
      T("MGNREGA person-days in Ri Bhoi in 2023-24", F(emp("person_days", dist("RI BHOI"), yr(2023)))),
      T("break that down by block",
        rows=R(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE lgd_district = 'RI BHOI' AND year_key = 2023 "
               f"GROUP BY 1 ORDER BY 2 DESC"), schemes=[MG], year=2023)))
add(C("FU-17", "chain", "village-chain", FU,
      T("How many PMAY houses in GABIL SONGGITCHAM?", F(pm_count(GAB))),
      T("how many completed?", F(pm_count(GAB, "is_completed")), schemes=[PM], place="GABIL SONGGITCHAM"),
      T("how much is still to be released?",
        F(f"SELECT SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE {GAB}", "rupees"),
        schemes=[PM], place="GABIL SONGGITCHAM")))
add(C("FU-18", "chain", "chart-switch", FU + " (voice bank D5)",
      T("MGNREGA person-days by district in 2023-24.",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 DESC")),
      T("Show the same as a pie chart.",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 DESC"),
        chart="pie")))
add(C("FU-19", "chain", "and-for-place", FU + " (voice bank C4)",
      T("CM Elevate applications in South Garo Hills.", ce_apps(dist("SOUTH GARO HILLS")), pause=False),   # D-099 pick
      T("And in West Khasi Hills?", ce_apps(dist("WEST KHASI HILLS")), schemes=[CE], place="WEST KHASI HILLS")))
add(C("FU-20", "chain", "year-filter", FU,
      T("PMAY-G houses sanctioned in 2023-24", F(pm_count(yr(2023)))),
      T("how many of those are completed?", F(pm_count(yr(2023), "is_completed")), schemes=[PM], year=2023)))
add(C("FU-21", "chain", "measure-swap", FU,
      T("What was MGNREGA expenditure in each financial year?",
        rows=R(f"SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM {EXP} GROUP BY 1 ORDER BY 1", "lakh")),
      T("and person-days?", rows=R(f"SELECT financial_year_short, SUM(person_days) FROM {EMP} GROUP BY 1 ORDER BY 1"),
        schemes=[MG])))
add(C("FU-22", "chain", "place-measure", FU,
      T("Focus Legacy producer groups in West Garo Hills", F(fl_pg(dist("WEST GARO HILLS")))),
      T("and the amount?", F(fl_amt(dist("WEST GARO HILLS")), "rupees"), schemes=[FL], place="WEST GARO HILLS"),
      T("and in East Khasi Hills?", F(fl_amt(dist("EAST KHASI HILLS")), "rupees"), schemes=[FL],
        place="EAST KHASI HILLS")))
add(C("FU-23", "chain", "only-filter", FU,
      T("CM Elevate Legacy records by scheme",
        rows=R(f"SELECT scheme_name, COUNT(*) FROM {CLV} GROUP BY 1 ORDER BY 2 DESC", take=3)),
      T("only piggery", F(f"SELECT COUNT(*) FROM {CLV} WHERE scheme_name = 'Meghalaya Piggery Development Scheme'"),
        schemes=[CL])))
add(C("FU-24", "chain", "which-higher", FU,
      T("MGNREGA expenditure in 2022-23 and 2023-24 statewide", F(exp_("total_exp", yr(2022)), "lakh"),
        F(exp_("total_exp", yr(2023)), "lakh")),
      T("which year was higher?", F(exp_("total_exp", yr(2022)), "lakh"), any_of=[["2022-23"]], schemes=[MG],
        lacks=["2023-24 was higher", "2023-24 is higher"])))
add(C("FU-25", "chain", "and-for-place", FU,
      T("How many Focus Plus beneficiaries are there in East Khasi Hills?", F(fp_ben(dist("EAST KHASI HILLS")))),
      T("And in Ri Bhoi?", F(fp_ben(dist("RI BHOI"))), schemes=[FP], place="RI BHOI"),
      T("and how much was paid there?", F(fp_amt(dist("RI BHOI")), "rupees"), schemes=[FP], place="RI BHOI")))
add(C("FU-26", "chain", "scheme-swap", FU,
      T("PMAY-G houses in West Khasi Hills", F(pm_count(dist("WEST KHASI HILLS")))),
      T("what about MGNREGA households employed there in 2024-25?",
        F(emp("households_employed", dist("WEST KHASI HILLS"), yr(2024))), schemes=[MG], place="WEST KHASI HILLS",
        year=2024)))



# ════ 11. Wave 2 (2026-11-12): every district, more blocks, years, rankings, chains, paraphrases ════
W2 = "wave 2 (accuracy round 2026-11-12)"
D12 = ["EASTERN WEST KHASI HILLS", "EAST GARO HILLS", "EAST JAINTIA HILLS", "EAST KHASI HILLS", "NORTH GARO HILLS",
       "RI BHOI", "SOUTH GARO HILLS", "SOUTH WEST GARO HILLS", "SOUTH WEST KHASI HILLS", "WEST GARO HILLS",
       "WEST JAINTIA HILLS", "WEST KHASI HILLS"]
MG_YEARS = [2022, 2023, 2024, 2025]


def title(name):
    return " ".join(w.capitalize() for w in name.split())


def fy(y):
    return f"{y}-{(y + 1) % 100:02d}"


# MGNREGA person-days, every district, a year each, three wordings
MG_WORDS = ["How many person-days were generated under MGNREGA in {d} in FY {y}?",
            "MGNREGA person-days in {d} for {y}",
            "What were the total person days under NREGA in {d} district during {y}?"]
for i, d in enumerate(D12):
    y = MG_YEARS[i % 4]
    add(C(f"W2-MGD-{i + 1:02d}", "mgnrega", "district-year", W2,
          T(MG_WORDS[i % 3].format(d=title(d), y=fy(y)), F(emp("person_days", dist(d), yr(y))), schemes=[MG], place=d,
            year=y)))

# PMAY-G completed houses, every district
PM_WORDS = ["How many PMAY-G houses have been completed in {d}?",
            "Completed PMAY-G houses in {d} district",
            "In {d}, how many houses under PMAY gramin are complete?"]
for i, d in enumerate(D12):
    add(C(f"W2-PMD-{i + 1:02d}", "pmay", "district", W2,
          T(PM_WORDS[i % 3].format(d=title(d)), F(pm_count(dist(d), "is_completed")), schemes=[PM], place=d)))

# Focus Plus beneficiaries / Focus Legacy producer groups / CM Elevate Legacy subsidy / CM Elevate, six districts each
for i, d in enumerate(D12[::2]):
    add(C(f"W2-FPD-{i + 1:02d}", "focus_plus", "district", W2,
          T(f"How many Focus Plus beneficiaries are there in {title(d)}?", F(fp_ben(dist(d))), schemes=[FP], place=d)))
for i, d in enumerate(D12[1::2]):
    add(C(f"W2-FLD-{i + 1:02d}", "focus_legacy", "district", W2,
          T(f"Number of Focus Legacy producer groups in {title(d)}", F(fl_pg(dist(d))), schemes=[FL], place=d)))
for i, d in enumerate(D12[::2]):
    add(C(f"W2-CLD-{i + 1:02d}", "cm_elevate_legacy", "district-money", W2,
          T(f"How much CM Elevate Legacy subsidy has been disbursed in {title(d)}?",
            F(cl("total_subsidy_disbursement", dist(d)), "rupees"), schemes=[CL], place=d)))
for i, d in enumerate(D12[1::2]):
    add(C(f"W2-CED-{i + 1:02d}", "cm_elevate", "district", W2,
          T(f"How many CM Elevate applications are there from {title(d)}?", ce_apps(dist(d)), schemes=[CE], place=d)))

# Blocks
add(C("W2-BLK-01", "mgnrega", "block-year", W2,
      T("How many households were provided MGNREGA employment in Umling block in 2024-25?",
        F(emp("households_employed", blk("UMLING"), yr(2024))), schemes=[MG], place="UMLING", year=2024)))
add(C("W2-BLK-02", "mgnrega", "block-year", W2,
      T("MGNREGA total expenditure in Resubelpara block for 2023-24",
        F(exp_("total_exp", blk("RESUBELPARA"), yr(2023)), "lakh"), schemes=[MG], place="RESUBELPARA", year=2023)))
add(C("W2-BLK-03", "pmay", "block", W2,
      T("How many PMAY-G houses are completed in Songsak block?", F(pm_count(blk("SONGSAK"), "is_completed")),
        schemes=[PM], place="SONGSAK")))
add(C("W2-BLK-04", "pmay", "block", W2,
      T("Total PMAY-G houses in Laskein block", F(pm_count(blk("LASKEIN"))), schemes=[PM], place="LASKEIN")))
add(C("W2-BLK-05", "focus_legacy", "block-money", W2,
      T("How much Focus Legacy money went to Mairang block?", F(fl_amt(blk("MAIRANG")), "rupees"), schemes=[FL],
        place="MAIRANG")))
add(C("W2-BLK-06", "cm_elevate_legacy", "block", W2,
      T("How much CM Elevate Legacy loan was disbursed in Zikzak block?",
        F(cl("total_loan_disbursement", blk("ZIKZAK")), "rupees"), schemes=[CL], place="ZIKZAK")))
add(C("W2-BLK-07", "cm_elevate", "block", W2,
      T("How many CM Elevate applications came from Jirang block?", ce_apps(blk("JIRANG")), schemes=[CE],
        place="JIRANG")))
add(C("W2-BLK-08", "focus_plus", "block", W2,
      T("How many Focus Plus beneficiaries are there in Tikrikilla block?",
        F(f"SELECT COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE UPPER(block_name_raw) = 'TIKRIKILLA'"),
        schemes=[FP], place="TIKRIKILLA")))
add(C("W2-BLK-09", "mgnrega", "block-year", W2,
      T("Person-days generated in Zikzak block in 2022-23 under MGNREGA",
        F(emp("person_days", blk("ZIKZAK"), yr(2022))), schemes=[MG], place="ZIKZAK", year=2022)))
add(C("W2-BLK-10", "focus_legacy", "block", W2,
      T("How many Focus Legacy producer groups are there in Nongstoin block?", F(fl_pg(blk("NONGSTOIN"))),
        schemes=[FL], place="NONGSTOIN")))

# Rankings
add(C("W2-RK-01", "pmay", "ranking-topn", W2,
      T("Top 5 districts by PMAY-G houses completed",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE is_completed GROUP BY 1 ORDER BY 2 DESC", take=5),
        schemes=[PM])))
add(C("W2-RK-02", "mgnrega", "ranking-bottom", W2,
      T("Which 3 blocks in East Khasi Hills had the lowest MGNREGA person-days in 2024-25?",
        rows=R(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE {dist('EAST KHASI HILLS')} AND year_key = 2024 "
               f"GROUP BY 1 ORDER BY 2 ASC", take=3), schemes=[MG], year=2024)))
add(C("W2-RK-03", "focus_legacy", "ranking-topn", W2,
      T("Top 3 districts by number of Focus Legacy producer groups",
        rows=R(f"SELECT lgd_district, COUNT(DISTINCT pg_id) FROM {FLV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", take=3), schemes=[FL])))
add(C("W2-RK-04", "cm_elevate_legacy", "ranking-topn", W2,
      T("Which 3 CM Elevate Legacy schemes got the most subsidy?",
        rows=R(f"SELECT scheme_name, SUM(total_subsidy_disbursement) FROM {CLV} GROUP BY 1 ORDER BY 2 DESC NULLS LAST",
               "rupees", take=3), schemes=[CL])))
add(C("W2-RK-05", "focus_plus", "ranking-bottom", W2,
      T("Which district has the fewest Focus Plus beneficiaries?",
        rows=R(f"SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE lgd_district IS NOT NULL "
               f"GROUP BY 1 ORDER BY 2 ASC", take=1), schemes=[FP])))
add(C("W2-RK-06", "mgnrega", "ranking-topn", W2,
      T("Top 3 districts by MGNREGA households employed in 2025-26",
        rows=R(f"SELECT lgd_district, SUM(households_employed) FROM {EMP} WHERE year_key = 2025 GROUP BY 1 "
               f"ORDER BY 2 DESC", take=3), schemes=[MG], year=2025)))

# Year comparisons
add(C("W2-YR-01", "mgnrega", "comparison-years", W2,
      T("Compare MGNREGA person-days in West Garo Hills between 2022-23 and 2024-25",
        F(emp("person_days", dist("WEST GARO HILLS"), yr(2022))), F(emp("person_days", dist("WEST GARO HILLS"), yr(2024))),
        schemes=[MG], place="WEST GARO HILLS")))
add(C("W2-YR-02", "pmay", "comparison-years", W2,
      T("PMAY-G houses sanctioned in 2019-20 versus 2021-22", F(pm_count(yr(2019))), F(pm_count(yr(2021))),
        schemes=[PM])))
add(C("W2-YR-03", "cm_elevate_legacy", "state-by-year", W2,
      T("CM Elevate Legacy total disbursement by financial year",
        rows=R(f"SELECT financial_year_short, SUM(total_disbursement) FROM {CLV} WHERE year_key IS NOT NULL "
               f"GROUP BY 1 ORDER BY 1", "rupees"), schemes=[CL])))

# Follow-up chains
add(C("W2-CH-01", "chain", "year-then-block", W2,
      T("MGNREGA households employed in Ri Bhoi in 2024-25", F(emp("households_employed", dist("RI BHOI"), yr(2024)))),
      T("and in 2023-24?", F(emp("households_employed", dist("RI BHOI"), yr(2023))), schemes=[MG], place="RI BHOI",
        year=2023),
      T("and in Umling block?", F(emp("households_employed", blk("UMLING"), yr(2023))), schemes=[MG], place="UMLING",
        year=2023)))
add(C("W2-CH-02", "chain", "breakdown-then-place", W2,
      T("PMAY-G houses completed by district",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE is_completed GROUP BY 1 ORDER BY 2 DESC", take=3)),
      T("only Ri Bhoi", F(pm_count(dist("RI BHOI"), "is_completed")), schemes=[PM], place="RI BHOI")))
add(C("W2-CH-03", "chain", "ranking-followup", W2,
      T("Focus Legacy amount by district",
        rows=R(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FLV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", "rupees", take=3)),
      T("which district had the least?",
        rows=R(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FLV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 ASC", "rupees", take=1), schemes=[FL])))
add(C("W2-CH-04", "chain", "one-of-comparison", W2,
      T("Compare the Focus Plus and Focus Legacy amounts disbursed", F(fp_amt(), "rupees"), F(fl_amt(), "rupees")),
      T("only Focus Legacy", F(fl_amt(), "rupees"), schemes=[FL])))
add(C("W2-CH-05", "chain", "measure-then-place", W2,
      T("CM Elevate Legacy subsidy disbursed in West Garo Hills",
        F(cl("total_subsidy_disbursement", dist("WEST GARO HILLS")), "rupees")),
      T("and the loan?", F(cl("total_loan_disbursement", dist("WEST GARO HILLS")), "rupees"), schemes=[CL],
        place="WEST GARO HILLS"),
      T("and in Ri Bhoi?", F(cl("total_loan_disbursement", dist("RI BHOI")), "rupees"), schemes=[CL],
        place="RI BHOI")))
add(C("W2-CH-06", "chain", "measure-keeps-breakdown", W2,
      T("MGNREGA expenditure by district in 2024-25",
        rows=R(f"SELECT lgd_district, ROUND(SUM(total_exp), 2) FROM {EXP} WHERE year_key = 2024 GROUP BY 1 "
               f"ORDER BY 2 DESC", "lakh", take=3)),
      T("and person-days?",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2024 GROUP BY 1 ORDER BY 2 DESC",
               take=3), schemes=[MG], year=2024)))
add(C("W2-CH-07", "chain", "only-filter-keeps-breakdown", W2,
      T("PMAY-G houses sanctioned in each financial year",
        rows=R(f"SELECT financial_year_short, COUNT(*) FROM {PMV} WHERE year_key IS NOT NULL GROUP BY 1 ORDER BY 1")),
      T("only the completed ones",
        rows=R(f"SELECT financial_year_short, COUNT(*) FROM {PMV} WHERE is_completed AND year_key IS NOT NULL "
               f"GROUP BY 1 ORDER BY 1"), schemes=[PM], route="data")))
add(C("W2-CH-08", "chain", "place-measure-compare", W2,
      T("Focus Plus beneficiaries in Ri Bhoi", F(fp_ben(dist("RI BHOI")))),
      T("and the amount disbursed there?", F(fp_amt(dist("RI BHOI")), "rupees"), schemes=[FP], place="RI BHOI"),
      T("compare with East Khasi Hills", F(fp_amt(dist("RI BHOI")), "rupees"), F(fp_amt(dist("EAST KHASI HILLS")), "rupees"),
        schemes=[FP])))
add(C("W2-CH-09", "chain", "breakdown-followup", W2,
      T("Women employed under MGNREGA in East Garo Hills in 2023-24",
        F(emp("women_employment_provided", dist("EAST GARO HILLS"), yr(2023)))),
      T("break that down by block",
        rows=R(f"SELECT lgd_block, SUM(women_employment_provided) FROM {EMP} WHERE {dist('EAST GARO HILLS')} "
               f"AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC"), schemes=[MG], year=2023)))
add(C("W2-CH-10", "chain", "ranking-then-place", W2,
      T("CM Elevate applications by district", rows=ce_rows("lgd_district", take=3)),
      T("which district had the most?", rows=ce_rows("lgd_district", take=1), schemes=[CE])))
add(C("W2-CH-11", "chain", "and-for-year", W2,
      T("Focus Legacy amount remitted in FY 2022-23", F(fl_amt(yr(2022)), "rupees")),
      T("and in 2025-26?", F(fl_amt(yr(2025)), "rupees"), schemes=[FL], year=2025)))
add(C("W2-CH-12", "chain", "scheme-swap", W2,
      T("PMAY-G houses completed in East Garo Hills", F(pm_count(dist("EAST GARO HILLS"), "is_completed"))),
      T("and Focus Plus beneficiaries there?", F(fp_ben(dist("EAST GARO HILLS"))), schemes=[FP],
        place="EAST GARO HILLS")))

# Paraphrase families, wave 2
fams2 = [
    ("W2-PF-MGX", "mgnrega", F(exp_("total_exp", dist("EAST GARO HILLS"), yr(2024)), "lakh"), [MG], "EAST GARO HILLS", 2024, [
        ("formal", "What was the total MGNREGA expenditure in East Garo Hills district during FY 2024-25?"),
        ("casual", "how much did nrega spend in east garo hills in 24-25"),
        ("terse", "MGNREGA expenditure EGH 2024-25"),
        ("misspelt", "mgnrega expenditur east garo hils 2024-25"),
        ("spoken", "Uh, MGNREGA, total expenditure, East Garo Hills, twenty twenty four twenty five?"),
    ]),
    ("W2-PF-FLP", "focus_legacy", F(fl_pg(dist("RI BHOI"))), [FL], "RI BHOI", None, [
        ("formal", "How many producer groups are registered under Focus Legacy in Ri Bhoi district?"),
        ("casual", "how many focus legacy PGs are there in ribhoi"),
        ("terse", "Focus Legacy PGs Ri Bhoi"),
        ("misspelt", "focus legasy producer grups ri bhoi"),
        ("spoken", "So, um, Focus Legacy producer groups in Ri Bhoi, how many?"),
    ]),
    ("W2-PF-PMR", "pmay", F(f"SELECT SUM(COALESCE(amount_released, 0)) FROM {PMV} WHERE {dist('WEST GARO HILLS')}",
                            "rupees"), [PM], "WEST GARO HILLS", None, [
        ("formal", "What is the total amount released under PMAY-G in West Garo Hills district?"),
        ("casual", "how much pmay money has been released in west garo hills"),
        ("terse", "PMAY-G amount released WGH"),
        ("misspelt", "pmay amout relesed west garo hils"),
        ("spoken", "Okay, PMAY-G, how much has been released in West Garo Hills, uh, in total?"),
    ]),
]
for fid, cat, fig, schemes, place, year, ways in fams2:
    for style, q in ways:
        add(C(f"{fid}-{style}", cat, f"paraphrase-{style}", W2, T(q, fig, schemes=schemes, place=place, year=year)))

# ════ 12. Wave 2b (2026-11-12): CM Elevate decisions on the plain file_status column; cross-scheme "there" ════
def ce_state(cond, *conds, label="applications"):
    """A CM Elevate file-status count: valid-only by default (said 'valid'), or every application."""
    valid = "data_verified = 'Valid'"
    return ANY(F(f"SELECT COUNT(DISTINCT request_id) FROM {CEV}{w(cond, *conds, valid)}",
                 label=f"valid {label}", word="valid"),
               F(f"SELECT COUNT(DISTINCT request_id) FROM {CEV}{w(cond, *conds)}", label=f"all {label}"),
               why="D-B1-CME-01: valid-only by default (said 'valid'), or every application")


add(C("W2-CE-REJ-01", "cm_elevate", "file-status", W2 + " (KI-720)",
      T("How many CM Elevate applications were rejected in Ri Bhoi?", ce_state("file_status = 'Rejected'", dist("RI BHOI")),
        schemes=[CE], place="RI BHOI")))
add(C("W2-CE-REJ-02", "cm_elevate", "file-status", W2 + " (KI-720)",
      T("How many CM Elevate applications have been rejected?", ce_state("file_status = 'Rejected'"), schemes=[CE])))
add(C("W2-CE-SB-01", "cm_elevate", "file-status", W2,
      T("How many CM Elevate applications were sent back in West Garo Hills?",
        ce_state("file_status = 'Send Back'", dist("WEST GARO HILLS")), schemes=[CE], place="WEST GARO HILLS")))
add(C("W2-CE-PEND-01", "cm_elevate", "pending", W2 + " (D-B1-CME-01, KI-707)",
      T("How many CM Elevate applications are pending in East Khasi Hills?",
        F(f"SELECT COUNT(DISTINCT request_id) FROM {CEV} WHERE {dist('EAST KHASI HILLS')} AND data_verified = 'Valid' "
          f"AND file_status IN ('Pending', 'Send Back')"), schemes=[CE], place="EAST KHASI HILLS")))
add(C("W2-CE-APP-01", "cm_elevate", "not-recorded", W2 + " (KI-720)",
      T("How many CM Elevate applications were approved?", pause=True)))
add(C("W2-CH-13", "chain", "other-scheme-there", W2 + " (KI-722)",
      T("PMAY-G houses in Ri Bhoi", F(pm_count(dist("RI BHOI")))),
      T("what about MGNREGA households employed there?", F(emp("households_employed", dist("RI BHOI"))), schemes=[MG],
        place="RI BHOI")))
add(C("W2-CH-14", "chain", "other-scheme-there", W2 + " (KI-722)",
      T("Focus Legacy producer groups in South Garo Hills", F(fl_pg(dist("SOUTH GARO HILLS")))),
      T("and CM Elevate Legacy subsidy there?", F(cl("total_subsidy_disbursement", dist("SOUTH GARO HILLS")), "rupees"),
        schemes=[CL], place="SOUTH GARO HILLS")))
add(C("W2-CL-LOAN-01", "cm_elevate_legacy", "district-money", W2 + " (KI-721)",
      T("How much CM Elevate Legacy loan was disbursed in West Garo Hills?",
        F(cl("total_loan_disbursement", dist("WEST GARO HILLS")), "rupees"), schemes=[CL], place="WEST GARO HILLS")))
add(C("W2-CL-LOAN-02", "cm_elevate_legacy", "lender", W2 + " (KI-721)",
      T("How much CM Elevate Legacy loan was given by banks?",
        F(cl("total_loan_disbursement", "loan_entity = 'Bank'"), "rupees"), schemes=[CL])))

# ════ 13. Wave 3 (2026-11-12): ratios, shares, constituencies, villages, multi-place, harder chains ════
W3 = "wave 3 (accuracy round 2026-11-12)"
add(C("W3-RT-01", "focus_plus", "ratio", W3,
      T("What is the average Focus Plus amount per beneficiary in West Garo Hills?",
        F(f"SELECT SUM(amount_disbursed)::numeric / COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE {dist('WEST GARO HILLS')}",
          "dec", label="₹ per beneficiary"), schemes=[FP], place="WEST GARO HILLS")))
add(C("W3-RT-02", "pmay", "ratio", W3,
      T("What percentage of PMAY-G houses in Ri Bhoi are completed?",
        F(f"SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM {PMV} WHERE {dist('RI BHOI')}", "pct"),
        schemes=[PM], place="RI BHOI")))
add(C("W3-RT-03", "pmay", "share", W3,
      T("What share of all PMAY-G houses are in West Garo Hills?",
        F(f"SELECT 100.0 * COUNT(*) FILTER (WHERE {dist('WEST GARO HILLS')}) / COUNT(*) FROM {PMV}", "pct"),
        schemes=[PM])))
add(C("W3-RT-04", "focus_legacy", "ratio", W3,
      T("What is the average Focus Legacy amount per producer group in East Jaintia Hills?",
        F(f"SELECT SUM(amount_disbursed)::numeric / COUNT(DISTINCT pg_id) FROM {FLV} WHERE {dist('EAST JAINTIA HILLS')}",
          "dec", label="₹ per PG"), schemes=[FL], place="EAST JAINTIA HILLS")))
add(C("W3-AC-01", "mgnrega", "constituency-year", W3,
      T("MGNREGA person-days in Rongjeng constituency in 2023-24",
        F(emp("person_days", "assembly_constituency_name = 'RONGJENG'", yr(2023))), schemes=[MG], place="RONGJENG",
        year=2023)))
add(C("W3-AC-02", "pmay", "constituency", W3,
      T("How many PMAY-G houses are in Songsak constituency?",
        F(f"SELECT COUNT(*) FROM {PMV} WHERE UPPER(ac_name) = 'SONGSAK'"), schemes=[PM], place="SONGSAK")))
add(C("W3-VL-01", "mgnrega", "village-year", W3,
      T("How many person-days did Jakrem village get under MGNREGA in 2024-25?",
        F(emp("person_days", vil("JAKREM"), yr(2024))), schemes=[MG], place="JAKREM", year=2024)))
add(C("W3-VL-02", "pmay", "village", W3,
      T("How many PMAY-G houses are there in Silkata village?", F(pm_count(vil("SILKATA"))), schemes=[PM],
        place="SILKATA")))
add(C("W3-MP-01", "focus_legacy", "comparison-three", W3,
      T("Compare the Focus Legacy amounts in Ri Bhoi, West Garo Hills and East Khasi Hills",
        F(fl_amt(dist("RI BHOI")), "rupees"), F(fl_amt(dist("WEST GARO HILLS")), "rupees"),
        F(fl_amt(dist("EAST KHASI HILLS")), "rupees"), schemes=[FL])))
add(C("W3-MP-02", "mgnrega", "comparison-blocks", W3,
      T("Compare MGNREGA person-days in Zikzak and Betasing blocks in 2024-25",
        F(emp("person_days", blk("ZIKZAK"), yr(2024))), F(emp("person_days", blk("BETASING"), yr(2024))), schemes=[MG],
        year=2024)))
add(C("W3-YR-01", "mgnrega", "which-year", W3,
      T("In which financial year was MGNREGA expenditure the highest?",
        rows=R(f"SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM {EXP} GROUP BY 1 ORDER BY 2 DESC", "lakh",
               take=1), schemes=[MG])))
add(C("W3-YR-02", "focus_plus", "state-by-year", W3,
      T("Focus Plus amount disbursed by financial year",
        rows=R(f"SELECT financial_year_short, SUM(amount_disbursed) FROM {FPV} WHERE year_key IS NOT NULL GROUP BY 1 "
               f"ORDER BY 1", "rupees"), schemes=[FP])))
add(C("W3-TT-01", "mgnrega", "district-all-years", W3,
      T("Total MGNREGA person-days in North Garo Hills across all years",
        F(emp("person_days", dist("NORTH GARO HILLS"))), schemes=[MG], place="NORTH GARO HILLS")))
add(C("W3-TT-02", "cm_elevate_legacy", "district-year", W3,
      T("CM Elevate Legacy total disbursement in Ri Bhoi in 2025-26",
        F(cl("total_disbursement", dist("RI BHOI"), yr(2025)), "rupees"), schemes=[CL], place="RI BHOI", year=2025)))
# chains
add(C("W3-CH-01", "chain", "same-for-year", W3,
      T("MGNREGA person-days in West Jaintia Hills in 2024-25", F(emp("person_days", dist("WEST JAINTIA HILLS"), yr(2024)))),
      T("same for 2022-23", F(emp("person_days", dist("WEST JAINTIA HILLS"), yr(2022))), schemes=[MG],
        place="WEST JAINTIA HILLS", year=2022)))
add(C("W3-CH-02", "chain", "breakdown-by-year", W3,
      T("Focus Legacy amount in West Garo Hills", F(fl_amt(dist("WEST GARO HILLS")), "rupees")),
      T("break it down by financial year",
        rows=R(f"SELECT financial_year_short, SUM(amount_disbursed) FROM {FLV} WHERE {dist('WEST GARO HILLS')} "
               f"GROUP BY 1 ORDER BY 1", "rupees"), schemes=[FL])))
add(C("W3-CH-03", "chain", "breakdown-then-top", W3,
      T("PMAY-G houses by block in East Khasi Hills",
        rows=R(f"SELECT lgd_block, COUNT(*) FROM {PMV} WHERE {dist('EAST KHASI HILLS')} GROUP BY 1 ORDER BY 2 DESC",
               take=3)),
      T("which block has the most?",
        rows=R(f"SELECT lgd_block, COUNT(*) FROM {PMV} WHERE {dist('EAST KHASI HILLS')} GROUP BY 1 ORDER BY 2 DESC",
               take=1), schemes=[PM])))
add(C("W3-CH-04", "chain", "and-statewide", W3,
      T("Focus Plus beneficiaries in South Garo Hills", F(fp_ben(dist("SOUTH GARO HILLS")))),
      T("and statewide?", F(fp_ben()), schemes=[FP])))
add(C("W3-CH-05", "chain", "measure-swap", W3,
      T("CM Elevate Legacy records in East Khasi Hills",
        ANY(F(f"SELECT COUNT(*) FROM {CLV} WHERE {dist('EAST KHASI HILLS')}", label="records"),
            F(f"SELECT COUNT(sanctioned_amount) FROM {CLV} WHERE {dist('EAST KHASI HILLS')}", label="sanctioned"),
            why="records, or sanctioned records (D-097)")),
      T("and the total disbursement?", F(cl("total_disbursement", dist("EAST KHASI HILLS")), "rupees"), schemes=[CL],
        place="EAST KHASI HILLS")))
add(C("W3-CH-06", "chain", "place-then-year", W3,
      T("PMAY-G houses sanctioned in South West Khasi Hills", F(pm_count(dist("SOUTH WEST KHASI HILLS")))),
      T("how many in 2022-23?", F(pm_count(dist("SOUTH WEST KHASI HILLS"), yr(2022))), schemes=[PM],
        place="SOUTH WEST KHASI HILLS", year=2022)))
add(C("W3-CH-07", "chain", "compare-two-places-then-one", W3,
      T("Compare MGNREGA households employed in Ri Bhoi and East Khasi Hills in 2023-24",
        F(emp("households_employed", dist("RI BHOI"), yr(2023))), F(emp("households_employed", dist("EAST KHASI HILLS"), yr(2023)))),
      T("only Ri Bhoi", F(emp("households_employed", dist("RI BHOI"), yr(2023))), schemes=[MG], place="RI BHOI",
        year=2023)))
add(C("W3-CH-08", "chain", "measure-keeps-district-breakdown", W3,
      T("Focus Plus beneficiaries by district",
        rows=R(f"SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM {FPV} WHERE lgd_district IS NOT NULL "
               f"GROUP BY 1 ORDER BY 2 DESC", take=3)),
      T("and the amount?",
        rows=R(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FPV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", "rupees", take=3), schemes=[FP])))
# ════ 13b. Follow-ups by rule (2026-11-14, the model server down): the voice shaper's canonical wordings ════
# "what about the {measure} instead", "only the {value} ones", "and the {measure}?", "what about the year before?",
# "which is the lowest": each the previous question changed in one way (c01 _c01_measure_swap_question,
# _c01_year_only_question, _c01_rank_question). Truth written here from the views.
W5 = "follow-up rules (2026-11-14, voice shaper wordings)"
add(C("W5-FU-01", "chain", "measure-instead", W5,
      T("How many PMAY-G houses were sanctioned in Ri Bhoi?", F(pm_count(dist("RI BHOI")))),
      T("what about the amount released instead",
        F(f"SELECT SUM(amount_released) FROM {PMV} WHERE {dist('RI BHOI')}", "rupees"), schemes=[PM],
        place="RI BHOI")))
add(C("W5-FU-02", "chain", "measure-instead", W5,
      T("Focus Legacy amount disbursed in West Garo Hills", F(fl_amt(dist("WEST GARO HILLS")), "rupees")),
      T("what about the members instead",
        F(f"SELECT SUM(no_of_pg_members) FROM {FLV} WHERE {dist('WEST GARO HILLS')}"), schemes=[FL],
        place="WEST GARO HILLS")))
add(C("W5-FU-03", "chain", "measure-instead", W5,
      T("How many MGNREGA person-days were generated in West Garo Hills in 2023-24?",
        F(emp("person_days", dist("WEST GARO HILLS"), yr(2023)))),
      T("what about the households instead", F(emp("households_employed", dist("WEST GARO HILLS"), yr(2023))),
        schemes=[MG], place="WEST GARO HILLS", year=2023)))
add(C("W5-FU-04", "chain", "value-filter", W5,
      T("How many PMAY-G houses were sanctioned by district?",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
               take=3)),
      T("only the incomplete ones",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE lgd_district IS NOT NULL AND is_in_progress "
               f"GROUP BY 1 ORDER BY 2 DESC", take=3), schemes=[PM])))
add(C("W5-FU-05", "chain", "measure-swap", W5,
      T("CM Elevate Legacy loan disbursed in Ri Bhoi", F(cl("total_loan_disbursement", dist("RI BHOI")), "rupees")),
      T("and the subsidy?", F(cl("total_subsidy_disbursement", dist("RI BHOI")), "rupees"), schemes=[CL],
        place="RI BHOI")))
add(C("W5-FU-06", "chain", "year-before", W5,
      T("How many PMAY-G houses were sanctioned in West Garo Hills in FY 2023-24?",
        F(pm_count(dist("WEST GARO HILLS"), yr(2023)))),
      T("what about the year before?", F(pm_count(dist("WEST GARO HILLS"), yr(2022))), schemes=[PM],
        place="WEST GARO HILLS", year=2022)))
add(C("W5-FU-07", "chain", "rank-lowest", W5,
      T("Focus Plus amount disbursed by district",
        rows=R(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FPV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", "rupees", take=3)),
      T("which is the lowest",
        rows=R(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FPV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 ASC", "rupees", take=1), schemes=[FP])))
# ════ 14. Wave 4 (2026-11-14): the regroup matrix and the all-scheme matrix ════
# The report after the merge with the team's Main: "break that down by district / block / financial year / as per
# scheme" after a data answer was not answered, and all-scheme questions were not answered over all eight schemes.
# This wave is GENERATED: every measure below x every grouping it holds x four previous-answer shapes (a total, an
# answer already grouped, an answer inside a district, an answer inside a year), each follow-up in the plain words an
# officer uses. The truth is written here from the views (never from the pipeline's catalogue), so it is independent.
W4 = "wave 4 (regroup + all-scheme matrix, 2026-11-14)"
CMV, HSV = "curated.v_cmss", "curated.v_homestay_api"
CS, HS = "CMSS", "Homestay"

# (id, scheme, opening question, view, aggregate, unit, fixed condition, groupings held, a year it holds, a district)
_W4_MEASURES = [
    ("MGPD", MG, "How many MGNREGA person-days were generated", EMP, "SUM(person_days)", "count", "",
     ("district", "block", "year"), 2023, "WEST GARO HILLS"),
    ("MGHH", MG, "How many households were employed under MGNREGA", EMP, "SUM(households_employed)", "count", "",
     ("district", "block", "year"), 2024, "EAST KHASI HILLS"),
    ("MGEX", MG, "What is the total MGNREGA expenditure", EXP, "ROUND(SUM(total_exp), 2)", "lakh", "",
     ("district", "block", "year"), 2023, "RI BHOI"),
    ("PMSA", PM, "How many PMAY-G houses were sanctioned", PMV, "COUNT(*)", "count", "",
     ("district", "block", "year"), 2022, "WEST GARO HILLS"),
    ("PMCO", PM, "How many PMAY-G houses were completed", PMV, "COUNT(*)", "count", "is_completed",
     ("district", "block", "year"), 2020, "EAST GARO HILLS"),
    ("FPBE", FP, "How many Focus Plus beneficiaries are there", FPV, "COUNT(DISTINCT beneficiary_key)", "count", "",
     ("district", "year"), 2025, "WEST GARO HILLS"),                     # Focus Plus holds no block level
    ("FPAM", FP, "What is the total Focus Plus amount disbursed", FPV, "SUM(amount_disbursed)", "rupees", "",
     ("district", "year"), 2022, "SOUTH WEST GARO HILLS"),
    ("FLAM", FL, "What is the total Focus Legacy amount disbursed", FLV, "SUM(amount_disbursed)", "rupees", "",
     ("district", "block", "year"), 2024, "WEST GARO HILLS"),
    ("FLPG", FL, "How many producer groups were paid under Focus Legacy", FLV, "COUNT(DISTINCT pg_id)", "count", "",
     ("district", "block", "year"), 2022, "EAST KHASI HILLS"),
    ("CLDI", CL, "What is the total CM Elevate Legacy amount disbursed", CLV, "SUM(total_disbursement)", "rupees", "",
     ("district", "block", "year", "scheme"), 2024, "WEST GARO HILLS"),
    ("CSPA", CS, "How many students were paid under CMSS", CMV, "COUNT(*)", "count", "is_disbursed",
     ("district", "block"), None, "EAST KHASI HILLS"),
    ("HSAP", HS, "How many Homestay applications are there", HSV, "COUNT(*)", "count", "",
     ("district", "block"), None, "EAST KHASI HILLS"),
]
_W4_COL = {"district": "lgd_district", "block": "lgd_block", "year": "financial_year_short", "scheme": "scheme_name"}
_W4_SAY = {"district": "break that down by district", "block": "now break it down by block",
           "year": "break it down by financial year", "scheme": "break down as per scheme"}


def _w4_total(view, agg, *conds):
    return f"SELECT {agg} FROM {view}{w(*conds)}"


def _w4_rows(view, agg, unit, dim, *conds):
    """The truth of a grouping: every district / year / sub-scheme, the top five blocks."""
    col = _W4_COL[dim]
    order = "ORDER BY 1" if dim == "year" else "ORDER BY 2 DESC"
    sql = f"SELECT {col}, {agg} FROM {view}{w(f'{col} IS NOT NULL', *conds)} GROUP BY 1 {order}"
    return R(sql, unit, take=5 if dim == "block" else "all")


for _id, _s, _q, _v, _agg, _u, _fix, _dims, _yr, _d in _W4_MEASURES:
    # A. a statewide total, then every grouping it holds, one after another (each replaces the one before)
    add(C(f"W4-RG-{_id}-A", "regroup", "total-then-each-grouping", W4,
          T(f"{_q}?", F(_w4_total(_v, _agg, _fix), _u)),
          *[T(_W4_SAY[g], rows=_w4_rows(_v, _agg, _u, g, _fix), schemes=[_s], route="data") for g in _dims]))
    # B. an answer that is already grouped: the old grouping goes, the new one comes
    if "year" in _dims:
        add(C(f"W4-RG-{_id}-B", "regroup", "grouped-by-year-then-district", W4,
              T(f"{_q} by financial year?", rows=_w4_rows(_v, _agg, _u, "year", _fix)),
              T("break it down by district", rows=_w4_rows(_v, _agg, _u, "district", _fix), schemes=[_s], route="data")))
    # C. inside a district: the district stays, the blocks (and the years) are its own
    if "block" in _dims:
        _turns = [T(f"{_q} in {title(_d)}?", F(_w4_total(_v, _agg, _fix, dist(_d)), _u), place=_d),
                  T("break that down by block", rows=_w4_rows(_v, _agg, _u, "block", _fix, dist(_d)), schemes=[_s],
                    place=_d, route="data")]
        if "year" in _dims:
            _turns.append(T("break it down by financial year", rows=_w4_rows(_v, _agg, _u, "year", _fix, dist(_d)),
                            schemes=[_s], place=_d, route="data"))
        add(C(f"W4-RG-{_id}-C", "regroup", "in-district-then-block-then-year", W4, *_turns))
    # D. inside a year: the year stays
    if _yr is not None:
        add(C(f"W4-RG-{_id}-D", "regroup", "in-year-then-district", W4,
              T(f"{_q} in {fy(_yr)}?", F(_w4_total(_v, _agg, _fix, yr(_yr)), _u), year=_yr),
              T("district wise", rows=_w4_rows(_v, _agg, _u, "district", _fix, yr(_yr)), schemes=[_s], year=_yr,
                route="data")))

# CM Elevate: valid applications by default (D-B1-CME-01), its own groupings
add(C("W4-RG-CEAP-A", "regroup", "total-then-each-grouping", W4,
      T("How many CM Elevate applications are there?", ce_apps()),
      T("break that down by district", rows=ce_rows("lgd_district", "lgd_district IS NOT NULL"), schemes=[CE], route="data"),
      T("break down as per scheme", rows=ce_rows("scheme_name", "scheme_name IS NOT NULL"), schemes=[CE], route="data")))
add(C("W4-RG-CEAP-C", "regroup", "in-district-then-scheme", W4,
      T("How many CM Elevate applications are there in Ri Bhoi?", ce_apps(dist("RI BHOI")), place="RI BHOI"),
      T("scheme wise", rows=ce_rows("scheme_name", "scheme_name IS NOT NULL AND lgd_district = 'RI BHOI'"), schemes=[CE],
        place="RI BHOI", route="data")))

# a chart asked with the regroup comes along
add(C("W4-RG-CHART-1", "regroup", "regroup-with-chart", W4,
      T("How many PMAY-G houses were sanctioned?", F(pm_count())),
      T("break that down by district as a bar chart", rows=_w4_rows(PMV, "COUNT(*)", "count", "district"),
        schemes=[PM], chart="bar", route="data"),
      T("break it down by financial year as a line chart", rows=_w4_rows(PMV, "COUNT(*)", "count", "year"),
        schemes=[PM], chart="line", route="data")))
# the wordy spoken forms the voice hears (the shaper reduces them; typed, the rule reads them as they are)
add(C("W4-RG-WORDY-1", "regroup", "spoken-wording", W4,
      T("How many MGNREGA person-days were generated?", F(emp("person_days"))),
      T("can you break that down by district please", rows=_w4_rows(EMP, "SUM(person_days)", "count", "district"),
        schemes=[MG], route="data"),
      T("yearwise", rows=_w4_rows(EMP, "SUM(person_days)", "count", "year"), schemes=[MG], route="data")))

# ── the all-scheme matrix: one figure per scheme, every scheme that holds it, never a guess ──
_W4_COUNT = [F(emp("households_employed"), label="MGNREGA households"), F(pm_count(), label="PMAY-G houses"),
             F(fp_ben(), label="Focus Plus beneficiaries"),
             F(f"SELECT SUM(no_of_pg_members) FROM {FLV}", label="Focus Legacy members"),
             F(f"SELECT COUNT(*) FROM {CMV} WHERE is_disbursed", label="CMSS students paid"),
             F(f"SELECT COUNT(*) FROM {HSV}", label="Homestay applications")]
_W4_MONEY = [F(exp_("total_exp"), "lakh", label="MGNREGA expenditure"),
             F(f"SELECT SUM(amount_released) FROM {PMV}", "rupees", label="PMAY-G released"),
             F(fp_amt(), "rupees", label="Focus Plus"), F(fl_amt(), "rupees", label="Focus Legacy"),
             F(cl("total_disbursement"), "rupees", label="CM Elevate Legacy"),
             F(f"SELECT SUM(amount_disbursed) FROM {CMV}", "rupees", label="CMSS")]
for _n, (_q, _figs, _extra) in enumerate([
        ("Give me the headline figure of every scheme", _W4_COUNT, {}),
        ("Compare beneficiaries across all schemes", _W4_COUNT, {}),
        ("Give me each scheme's figures", _W4_COUNT, {}),
        ("How much money has each scheme disbursed?", _W4_MONEY, {"any_of": [["no money"]]}),
        ("Which scheme has disbursed the most money?", _W4_MONEY[:1], {"any_of": [["MGNREGA"]]}),
        ("Compare all eight schemes", _W4_COUNT, {}),
], 1):
    add(C(f"W4-XS-{_n:02d}", "cross", "all-schemes", W4, T(_q, *_figs, schemes=None, **_extra)))
# the same words twice in fresh chats must give the same figures (the totals-once, by-year-next report)
for _n in (1, 2):
    add(C(f"W4-XS-SAME-{_n}", "cross", "same-words-same-answer", W4,
          T("Give me the headline figure of every scheme", *_W4_COUNT, schemes=None)))
# all schemes inside one district
add(C("W4-XS-RB", "cross", "all-schemes-in-district", W4,
      T("In Ri Bhoi, give me each scheme's figures",
        F(emp("households_employed", dist("RI BHOI"))), F(pm_count(dist("RI BHOI"))), F(fp_ben(dist("RI BHOI"))),
        F(f"SELECT COUNT(*) FROM {CMV} WHERE is_disbursed AND lgd_district = 'RI BHOI'"),
        F(f"SELECT COUNT(*) FROM {HSV} WHERE lgd_district = 'RI BHOI'"), schemes=None, place="RI BHOI")))
# each year, every scheme that holds years; the ones that hold none are said so, never shown as 0
add(C("W4-XS-YEAR", "cross", "all-schemes-by-year", W4,
      T("Each year, for all schemes, what was disbursed?",
        F(exp_("total_exp", yr(2023)), "lakh", label="MGNREGA 2023-24"),
        F(f"SELECT SUM(amount_released) FROM {PMV} WHERE year_key = 2023", "rupees", label="PMAY-G 2023-24"),
        F(fl_amt(yr(2024)), "rupees", label="Focus Legacy 2024-25"),
        F(f"SELECT SUM(amount_disbursed) FROM {CMV} WHERE year_key = 2025", "rupees", label="CMSS 2025-26"),
        schemes=None, any_of=[["no money"]])))
# a regroup of an all-scheme answer
add(C("W4-XS-RG", "cross", "all-schemes-then-district", W4,
      T("Compare beneficiaries across all schemes", *_W4_COUNT, schemes=None),
      T("break that down by district",
        F(emp("households_employed", dist("WEST GARO HILLS")), label="MGNREGA WGH"),
        F(pm_count(dist("WEST GARO HILLS")), label="PMAY-G WGH"), schemes=None, route="data")))

# ════ 15. Drill-down behind an answer (2026-11-15, the user's live report) ════
# "Show me the top five districts by Focus Plus beneficiaries." then "Can you break this down by block?" answered the
# same five districts again. A regroup after an answer about a SET of places keeps those places: "by block" after a
# top N = every block of those districts (each with its district), "by year" = each of them by year. The truth finds
# the ranked districts itself (a CTE over the view), so it never copies the pipeline's list. Rows are written
# (block, district, value) / (district, year, value): run_gold reads the first column as the label, the last as value.
BD = "drill-down behind an answer (user report 2026-11-15)"


def _bd_top(view, agg, n, *conds):
    """The n districts with the largest `agg` (ties broken by name), as a subquery."""
    return (f"(SELECT lgd_district FROM {view}{w('lgd_district IS NOT NULL', *conds)} GROUP BY lgd_district "
            f"ORDER BY {agg} DESC, lgd_district LIMIT {n})")


def _bd_blocks(view, agg, unit, n, *conds, block="lgd_block"):
    """Every block of the top n districts, with its own figure."""
    return R(f"SELECT {block}, lgd_district, {agg} FROM {view}"
             f"{w(f'lgd_district IN {_bd_top(view, agg, n, *conds)}', f'{block} IS NOT NULL', *conds)} "
             f"GROUP BY 1, 2 ORDER BY 2, 3 DESC", unit)


def _bd_years(view, agg, unit, places_sql, *conds):
    """Each listed district by financial year."""
    return R(f"SELECT lgd_district, financial_year_short, {agg} FROM {view}"
             f"{w(f'lgd_district IN {places_sql}', 'year_key IS NOT NULL', *conds)} GROUP BY 1, 2 ORDER BY 1, 2", unit)


_FP_BEN = "COUNT(DISTINCT beneficiary_key)"
_FP_RAW = "UPPER(block_name_raw)"
add(C("BD-01", "drilldown", "top5-then-by-block", BD + " — the exact two turns",
      T("Show me the top five districts by Focus Plus beneficiaries.",
        rows=R(f"SELECT lgd_district, {_FP_BEN} FROM {FPV} WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
               take=5)),
      T("Can you break this down by block?", rows=_bd_blocks(FPV, _FP_BEN, "count", 5, block=_FP_RAW),
        schemes=[FP], route="data")))
add(C("BD-02", "drilldown", "top5-then-by-year", BD,
      T("Show me the top five districts by Focus Plus beneficiaries.",
        rows=R(f"SELECT lgd_district, {_FP_BEN} FROM {FPV} WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
               take=5)),
      T("break it down by year", rows=_bd_years(FPV, _FP_BEN, "count", _bd_top(FPV, _FP_BEN, 5)), schemes=[FP],
        route="data")))
add(C("BD-03", "drilldown", "top3-in-a-year-then-drill", BD,
      T("Top 3 districts by MGNREGA person-days in FY 2023-24",
        rows=R(f"SELECT lgd_district, SUM(person_days) FROM {EMP} WHERE year_key = 2023 GROUP BY 1 ORDER BY 2 DESC",
               take=3)),
      T("drill down into blocks", rows=_bd_blocks(EMP, "SUM(person_days)", "count", 3, yr(2023)), schemes=[MG],
        year=2023, route="data")))
add(C("BD-04", "drilldown", "which-most-then-blocks", BD,
      T("Which district has the most PMAY-G houses sanctioned?",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {PMV} WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
               take=1)),
      T("break this down by block", rows=_bd_blocks(PMV, "COUNT(*)", "count", 1), schemes=[PM], route="data")))
add(C("BD-05", "drilldown", "top3-then-split-by-block", BD,
      T("Top 3 districts by Focus Legacy amount disbursed",
        rows=R(f"SELECT lgd_district, SUM(amount_disbursed) FROM {FLV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", "rupees", take=3)),
      T("split this by block", rows=_bd_blocks(FLV, "SUM(amount_disbursed)", "rupees", 3), schemes=[FL],
        route="data")))
add(C("BD-06", "drilldown", "top3-then-block-wise", BD,
      T("Top 3 districts by CM Elevate Legacy total disbursement",
        rows=R(f"SELECT lgd_district, SUM(total_disbursement) FROM {CLV} WHERE lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", "rupees", take=3)),
      T("block-wise please", rows=_bd_blocks(CLV, "SUM(total_disbursement)", "rupees", 3), schemes=[CL],
        route="data")))
add(C("BD-07", "drilldown", "top3-then-and-by-block", BD,
      T("Top 3 districts by students paid under CMSS",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {CMV} WHERE is_disbursed AND lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", take=3)),
      T("and by block?", rows=_bd_blocks(CMV, "COUNT(*)", "count", 3, "is_disbursed"), schemes=[CS], route="data")))
add(C("BD-08", "drilldown", "top3-then-by-block", BD,
      T("Top 3 districts by Homestay applications",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {HSV} WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
               take=3)),
      T("break this down by block", rows=_bd_blocks(HSV, "COUNT(*)", "count", 3), schemes=[HS], route="data")))
_BD_PAIR = "('RI BHOI', 'WEST GARO HILLS')"
add(C("BD-09", "drilldown", "compare-then-by-year", BD,
      T("Compare PMAY-G houses completed in Ri Bhoi and West Garo Hills",
        F(pm_count(dist("RI BHOI"), "is_completed")), F(pm_count(dist("WEST GARO HILLS"), "is_completed"))),
      T("break it down by year", rows=_bd_years(PMV, "COUNT(*)", "count", _BD_PAIR, "is_completed"), schemes=[PM],
        route="data"),
      T("only Ri Bhoi",
        rows=R(f"SELECT financial_year_short, COUNT(*) FROM {PMV} WHERE is_completed AND lgd_district = 'RI BHOI' "
               f"AND year_key IS NOT NULL GROUP BY 1 ORDER BY 1"), schemes=[PM], place="RI BHOI", route="data")))
add(C("BD-10", "drilldown", "compare-then-blocks-then-rank", BD,
      T("Compare MGNREGA person-days in Ri Bhoi and East Khasi Hills in FY 2023-24",
        F(emp("person_days", dist("RI BHOI"), yr(2023))), F(emp("person_days", dist("EAST KHASI HILLS"), yr(2023)))),
      T("break it down by block",
        rows=R(f"SELECT lgd_block, lgd_district, SUM(person_days) FROM {EMP} WHERE lgd_district IN "
               f"('RI BHOI', 'EAST KHASI HILLS') AND year_key = 2023 GROUP BY 1, 2 ORDER BY 3 DESC"),
        schemes=[MG], year=2023, route="data"),
      T("which block has the most?",
        rows=R(f"SELECT lgd_block, SUM(person_days) FROM {EMP} WHERE lgd_district IN ('RI BHOI', 'EAST KHASI HILLS') "
               f"AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC", take=1), schemes=[MG], year=2023, route="data")))
add(C("BD-11", "drilldown", "one-district-then-blocks", BD + " (Focus Plus blocks on block_name_raw, KI-718)",
      T("Focus Plus beneficiaries in West Garo Hills", F(fp_ben(dist("WEST GARO HILLS"))), place="WEST GARO HILLS"),
      T("break it down by block",
        rows=R(f"SELECT {_FP_RAW}, {_FP_BEN} FROM {FPV} WHERE lgd_district = 'WEST GARO HILLS' GROUP BY 1 "
               f"ORDER BY 2 DESC"), schemes=[FP], place="WEST GARO HILLS", route="data")))
add(C("BD-12", "drilldown", "total-then-district-then-block", BD,
      T("How many students were paid under CMSS?", F(f"SELECT COUNT(*) FROM {CMV} WHERE is_disbursed")),
      T("break this down by district",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {CMV} WHERE is_disbursed AND lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC"), schemes=[CS], route="data"),
      T("which district has the most?",
        rows=R(f"SELECT lgd_district, COUNT(*) FROM {CMV} WHERE is_disbursed AND lgd_district IS NOT NULL GROUP BY 1 "
               f"ORDER BY 2 DESC", take=1), schemes=[CS], route="data"),
      T("break it down by block", rows=_bd_blocks(CMV, "COUNT(*)", "count", 1, "is_disbursed"), schemes=[CS],
        route="data")))


def _strs(obj):
    if isinstance(obj, dict):
        return {k: _strs(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strs(v) for v in obj]
    return obj


def _conv(v):
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v) if v != v.to_integral_value() else int(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return str(v)
    return v


async def record(bank: list) -> None:
    """Run every truth query (read-only pool, READ ONLY transaction) and store what it returned."""
    sys.path.insert(0, ROOT)
    from app import db
    await db.init_pool()
    disagreements = []
    try:
        async def one_fig(f, where):
            if "any" in f:
                for g in f["any"]:
                    await one_fig(g, where)
                return
            rows = await db.fetch_rows_readonly(f["sql"])
            val = _conv(list(rows[0].values())[0]) if rows else None
            f["value"] = val
            if f.get("ref") is not None:
                disagreements.append((where, f.get("ref"), val, f.get("ref_src")))

        for c in bank:
            for i, t in enumerate(c["turns"]):
                where = f"{c['id']} t{i + 1}"
                for f in t.get("figures") or []:
                    await one_fig(f, where)
                for r in [x for y in (t.get("rows") or []) for x in (y["any"] if "any" in y else [y])]:
                    rows = await db.fetch_rows_readonly(r["sql"])
                    r["value"] = [[_conv(x) for x in row.values()] for row in rows]
                    if r.get("ref") is not None:
                        disagreements.append((where, r["ref"], r["value"][:5], r.get("ref_src")))
    finally:
        await db.close_pool()
    print("\nReference figures (PDF / sheet) beside the SQL truth — check each by eye:")
    for where, ref, val, src in disagreements:
        print(f"  {where:<14} ref {ref!s:<40} sql {val}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-db", action="store_true")
    args = ap.parse_args()
    ids = [c["id"] for c in B]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise SystemExit(f"duplicate ids: {sorted(dup)}")
    if not args.no_db:
        os.chdir(ROOT)
        asyncio.run(record(B))
    doc = {"bank": "Megh One AI accuracy gold bank", "built_by": "tests/accuracy/build_bank.py",
           "truth_recorded": str(datetime.date.today()) if not args.no_db else None,
           "cases": B}
    with open(OUT, "w", encoding="utf-8") as fh:
        yaml.safe_dump(_strs(doc), fh, sort_keys=False, allow_unicode=True, width=120)
    n_turns = sum(len(c["turns"]) for c in B)
    print(f"\n{len(B)} cases, {n_turns} turns -> {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
