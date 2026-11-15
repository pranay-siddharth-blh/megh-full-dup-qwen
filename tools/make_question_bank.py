"""Build the verified QUESTION BANK for Megh One AI (15 Nov 2026).

A guide for people who demo or test the app: client-style questions (per scheme, by district / block,
rankings, trends, comparisons, shares, cross-scheme, follow-up conversations, and what the app declines),
each with the answer read straight from megh_db.

How every answer is verified
  * Each question carries its OWN read-only SQL, written here by hand from the verified measure definitions
    (semantic.metric_definitions as listed in data/metric_catalog_verified.yaml). The app's pipeline is never
    called to compute an answer.
  * A question taken word for word from tests/accuracy/gold_bank.yaml is cross-checked against that bank's
    independent truth SQL (run live): every figure the bank expects must be one of this file's figures.
  * --app runs every question (and every follow-up conversation) through the real pipeline in-process, with
    the model ON, exactly as tests/accuracy/run_gold.py does (same runner, same grader: facts only, wording is
    not judged), and records per question whether the app's answer carries the DB's figures.

Usage (from the repo root, VPN up):
    .venv/Scripts/python.exe tools/make_question_bank.py            # DB truth + gold cross-check + render
    .venv/Scripts/python.exe tools/make_question_bank.py --app      # also run the app (model ON), then render
    .venv/Scripts/python.exe tools/make_question_bank.py --render   # render again from the saved results

Writes docs/Megh_Question_Bank.md, docs/Megh_Question_Bank.pdf and the evidence
docs/question_bank/qbank_results.json (truth, SQL, cross-check, app answers). App runs are also saved as
tests/accuracy/results/<stamp>_qbank.json. Read-only: no query writes, no app code is changed.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import datetime
import html
import json
import os
import shutil
import string
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)                                   # .env is read relative to the working directory
for p in (ROOT, os.path.join(ROOT, "tests"), os.path.join(ROOT, "tests", "accuracy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import yaml  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
OUT_MD = os.path.join(DOCS, "Megh_Question_Bank.md")
OUT_PDF = os.path.join(DOCS, "Megh_Question_Bank.pdf")
DATA = os.path.join(DOCS, "question_bank", "qbank_results.json")
GOLD = os.path.join(ROOT, "tests", "accuracy", "gold_bank.yaml")
GOLD_RUN = os.path.join(ROOT, "tests", "accuracy", "results", "2026-11-15_1613_merged-3.json")
NOMODEL_RUN = os.path.join(ROOT, "tests", "accuracy", "results", "2026-11-15_1601_nomodel-19.json")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# ── the views and the verified measures (semantic.metric_definitions) ─────────────────────────────────
EMP, EXP = "curated.v_employment", "curated.v_expenditure"
PMV, FPV, FLV = "curated.v_pmay", "curated.v_focus_plus", "curated.v_focus_legacy"
CEV, CLV = "curated.v_cm_elevate", "curated.v_cm_elevate_disbursement"
CSV, HSV = "curated.v_cmss", "curated.v_homestay_api"

MG_PD, MG_HH, MG_PE = "SUM(person_days)", "SUM(households_employed)", "SUM(persons_employed)"
MG_W, MG_100, MG_JC = "SUM(women_employment_provided)", "SUM(households_completed_100_days)", "SUM(job_cards_issued_total)"
MG_EXP, MG_MAT = "ROUND(SUM(total_exp), 2)", "ROUND(SUM(material_exp), 2)"          # stored in lakh rupees
PM_H, PM_C = "COUNT(*)", "COUNT(*) FILTER (WHERE is_completed)"
PM_IP, PM_REL = "COUNT(*) FILTER (WHERE is_in_progress)", "SUM(amount_released)"
PM_SAN, PM_PEND = "SUM(sanctioned_amount)", "SUM(amount_pending)"
FP_B, FP_A, FP_P = "COUNT(DISTINCT beneficiary_key)", "SUM(amount_disbursed)", "COUNT(*)"
FL_PG, FL_M, FL_A = "COUNT(DISTINCT pg_id)", "SUM(no_of_pg_members)", "SUM(amount_disbursed)"
CE_V, CE_ALL = "COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid')", "COUNT(DISTINCT request_id)"
CL_T, CL_S, CL_L = "SUM(total_disbursement)", "SUM(total_subsidy_disbursement)", "SUM(total_loan_disbursement)"
# "Sanctioned applicants": records with a sanctioned amount. 3 records were de-sanctioned (refused, no sanctioned
# amount, nothing paid), so this is 2,820 where the catalogue's COUNT(DISTINCT application_number) gives 2,823.
CL_APP, CL_REC = "COUNT(sanctioned_amount)", "COUNT(*)"
CS_PAID, CS_APPS, CS_A = "COUNT(*) FILTER (WHERE is_disbursed)", "COUNT(*)", "SUM(amount_disbursed)"
HS_APPS, HS_APR = "COUNT(*)", "COUNT(*) FILTER (WHERE file_status = 'Approved')"

MG, PM, FP, CE, FL, CL, CS, HS = ("MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy",
                                  "CM Elevate Legacy", "CMSS", "Homestay")


def W(*c):
    c = [x for x in c if x]
    return (" WHERE " + " AND ".join(c)) if c else ""


def one(expr, view, *c):
    return f"SELECT {expr} FROM {view}{W(*c)}"


def by(col, expr, view, *c, asc=False):
    return (f"SELECT {col}, {expr} FROM {view}{W(f'{col} IS NOT NULL', *c)} GROUP BY 1 "
            f"ORDER BY 2 {'ASC' if asc else 'DESC'} NULLS LAST, 1")


def byfy(expr, view, *c):
    return (f"SELECT financial_year_short, {expr} FROM {view}{W('financial_year_short IS NOT NULL', *c)} "
            f"GROUP BY 1 ORDER BY 1")


def dist(x):
    return f"lgd_district = '{x}'"


def blk(x):
    return f"lgd_block = '{x}'"


def yr(k):
    return f"year_key = {k}"


def vil(x):
    return f"UPPER(lgd_village_name) = '{x}'"


def acn(x):
    return f"UPPER(ac_name) = '{x}'"


# ── a small DSL for questions ────────────────────────────────────────────────────────────────────────

def V(name, sql, unit="count", label=None, word=None, ck=True):
    """One figure: the first cell of the first row. ck=False: shown in the answer, not required of the app."""
    return {"name": name, "kind": "v", "sql": " ".join(sql.split()), "unit": unit, "label": label, "word": word,
            "ck": ck}


def VA(name, *alts, why=""):
    """Two defensible readings (e.g. CM Elevate valid-only vs every application): the app must give one."""
    return {"name": name, "kind": "va", "alts": list(alts), "why": why, "ck": any(a["ck"] for a in alts)}


def R(name, sql, unit="count", take="all", ck=True, word=None):
    """Rows (label, value). take = rows shown in the answer; ck = rows the app must give: True = the same
    rows as shown, an int = the first N, False = not checked."""
    return {"name": name, "kind": "r", "sql": " ".join(sql.split()), "unit": unit, "take": take,
            "ck": take if ck is True else ck, "word": word}


def RA(name, *alts, why=""):
    return {"name": name, "kind": "ra", "alts": list(alts), "why": why, "ck": any(a["ck"] for a in alts)}


def T(q, *facts, say="", pause=False, route=None, any_of=(), lacks=(), has=(), schemes=None):
    return {"q": q, "facts": list(facts), "say": say, "pause": pause, "route": route, "any_of": [list(a) for a in any_of],
            "lacks": list(lacks), "has": list(has), "schemes": schemes}


BANK: list[dict] = []
SECTIONS = [
    ("A", "Every scheme at a glance (cross-scheme)",
     "Questions that look across the schemes at once: headline figures, money, the same place in every scheme."),
    ("M", "MGNREGA", "Employment (households, persons, person-days, women, 100 days, job cards) and expenditure, "
                     "by financial year. Money is stored in lakh rupees."),
    ("P", "PMAY-G", "Rural houses: sanctioned, completed, under construction, and the money sanctioned, released "
                    "and still to be released."),
    ("F", "Focus Plus", "Beneficiaries and the amount disbursed, in tranches."),
    ("L", "Focus Legacy", "Producer groups, their members and the amount remitted to them."),
    ("E", "CM Elevate (applications)", "Applications to the CM Elevate schemes. By default the app counts VALID "
                                       "applications and says so; ask for 'all applications' to count every one."),
    ("C", "CM Elevate Legacy (disbursements)", "Sanctioned applicants and the subsidy and loan paid out."),
    ("S", "CMSS and Homestay", "The two newest schemes: CMSS students paid, and Homestay applications."),
    ("V", "Conversations: follow-up questions",
     "Two to four turns in one chat. Each later turn only makes sense after the one before it."),
    ("K", "Asking for a chart", "The same figures, drawn. The numbers are what is checked."),
    ("D", "What the app declines or asks back",
     "Questions it should NOT answer with a number, or where it should ask which dataset you mean."),
]


def Q(qid, sec, *turns, gold=None, note=None, cat=None):
    qid = f"{sec}{sum(1 for q in BANK if q['sec'] == sec) + 1}"     # numbered in order within the section
    BANK.append({"id": qid, "sec": sec, "turns": list(turns), "gold": gold, "note": note, "cat": cat})


# ═════════════════════════════ A. cross-scheme ═════════════════════════════
HEADLINE = [
    V("mg", one(MG_HH, EMP), label="MGNREGA households (summed over financial years)"),
    V("pm", one(PM_H, PMV), label="PMAY-G houses"),
    V("fp", one(FP_B, FPV), label="Focus Plus beneficiaries"),
    V("fl", one(FL_M, FLV), label="Focus Legacy members"),
    V("cs", one(CS_PAID, CSV), label="CMSS students paid"),
    V("hs", one(HS_APPS, HSV), label="Homestay applications"),
    V("ce", one(CE_ALL, CEV), label="CM Elevate applications (all)", ck=False),
    V("cev", one(CE_V, CEV), label="CM Elevate valid applications", ck=False),
    V("cl", one(CL_APP, CLV), label="CM Elevate Legacy applicants", ck=False),
]
HEADLINE_SAY = ("MGNREGA {mg} households given work (each financial year counted on its own, 2022-23 to 2025-26); "
                "PMAY-G {pm} houses sanctioned; Focus Plus {fp} beneficiaries; Focus Legacy {fl} producer-group "
                "members; CMSS {cs} students paid; Homestay {hs} applications; CM Elevate {ce} applications "
                "({cev} of them valid); CM Elevate Legacy {cl} applicants sanctioned.")
MONEY = [
    V("mg", one(MG_EXP, EXP), "lakh", label="MGNREGA expenditure"),
    V("pm", one(PM_REL, PMV), "rupees", label="PMAY-G released"),
    V("fp", one(FP_A, FPV), "rupees", label="Focus Plus disbursed"),
    V("fl", one(FL_A, FLV), "rupees", label="Focus Legacy disbursed"),
    V("cl", one(CL_T, CLV), "rupees", label="CM Elevate Legacy disbursed"),
    V("cs", one(CS_A, CSV), "rupees", label="CMSS disbursed"),
]
MONEY_SAY = ("MGNREGA {mg} spent; PMAY-G {pm} released; Focus Plus {fp}; CM Elevate Legacy {cl} (subsidy and loan); "
             "CMSS {cs}; Focus Legacy {fl}. CM Elevate and Homestay record applications only, no money.")

Q("A1", "A", T("Give me the headline figure of every scheme", *HEADLINE, say=HEADLINE_SAY), gold="W4-XS-01")
Q("A2", "A", T("Compare all eight schemes", *HEADLINE, *[dict(f, name="m" + f["name"], ck=False) for f in MONEY],
               say=HEADLINE_SAY + " Money: MGNREGA {mmg} spent, PMAY-G {mpm} released, Focus Plus {mfp}, "
                                  "CM Elevate Legacy {mcl}, CMSS {mcs}, Focus Legacy {mfl}."), gold="W4-XS-06")
Q("A3", "A", T("How much money has each scheme disbursed?", *MONEY, say=MONEY_SAY), gold="W4-XS-04")
Q("A4", "A", T("Which scheme has disbursed the most money?", MONEY[0], dict(MONEY[1], ck=False),
               say="MGNREGA, by far: {mg} spent over 2022-23 to 2025-26. Next is PMAY-G with {pm} released.",
               any_of=[["MGNREGA"]]), gold="W4-XS-05")
Q("A6", "A", T("Total beneficiaries of each scheme excluding MGNREGA", HEADLINE[1], HEADLINE[2],
               *[dict(f, ck=False) for f in HEADLINE[3:6]],
               say="PMAY-G {pm} houses; Focus Plus {fp} beneficiaries; Focus Legacy {fl} members; CMSS {cs} "
                   "students paid; Homestay {hs} applications.", lacks=["14,94,437"]), gold="XS-08")


def place_figs(c):
    return [V("mg", one(MG_HH, EMP, c), label="MGNREGA households"), V("pm", one(PM_H, PMV, c), label="PMAY-G houses"),
            V("fp", one(FP_B, FPV, c), label="Focus Plus beneficiaries"),
            V("cs", one(CS_PAID, CSV, c), label="CMSS students paid"),
            V("hs", one(HS_APPS, HSV, c), label="Homestay applications"),
            V("fl", one(FL_M, FLV, c), label="Focus Legacy members", ck=False),
            V("ce", one(CE_V, CEV, c), label="CM Elevate valid applications", ck=False),
            V("cl", one(CL_T, CLV, c), "rupees", label="CM Elevate Legacy disbursed", ck=False)]


PLACE_SAY = ("MGNREGA {mg} households given work (all years added); PMAY-G {pm} houses; Focus Plus {fp} beneficiaries; "
             "CMSS {cs} students paid; Homestay {hs} applications; Focus Legacy {fl} members; CM Elevate {ce} valid "
             "applications; CM Elevate Legacy {cl} disbursed.")
Q("A7", "A", T("In Ri Bhoi, give me each scheme's figures", *place_figs(dist("RI BHOI")), say=PLACE_SAY),
  gold="W4-XS-RB")
Q("A8", "A", T("In East Khasi Hills, give me each scheme's figures", *place_figs(dist("EAST KHASI HILLS")),
               say=PLACE_SAY))
Q("A9", "A", T("Each year, for all schemes, what was disbursed?",
               V("mg23", one(MG_EXP, EXP, yr(2023)), "lakh"), V("pm23", one(PM_REL, PMV, yr(2023)), "rupees"),
               V("fl24", one(FL_A, FLV, yr(2024)), "rupees"), V("cs25", one(CS_A, CSV, yr(2025)), "rupees"),
               R("mg", byfy(MG_EXP, EXP), "lakh", ck=False), R("pm", byfy(PM_REL, PMV), "rupees", ck=False),
               R("fp", byfy(FP_A, FPV), "rupees", ck=False), R("fl", byfy(FL_A, FLV), "rupees", ck=False),
               R("cl", byfy(CL_T, CLV), "rupees", ck=False), R("cs", byfy(CS_A, CSV), "rupees", ck=False),
               say="MGNREGA spent {mg:list}. PMAY-G released {pm:list}. Focus Plus {fp:list}. Focus Legacy {fl:list}. "
                   "CM Elevate Legacy {cl:list} (plus some payments with no year). CMSS {cs:list}."),
  gold="W4-XS-YEAR", note="The test bank checks four sample years (MGNREGA and PMAY-G 2023-24, Focus Legacy 2024-25, "
                          "CMSS 2025-26); the full table is shown here.")
COMBINED = ("SELECT d, SUM(r) FROM ("
            f"SELECT lgd_district AS d, SUM(total_exp) * 100000 AS r FROM {EXP} GROUP BY 1 "
            f"UNION ALL SELECT lgd_district, SUM(amount_released) FROM {PMV} GROUP BY 1 "
            f"UNION ALL SELECT lgd_district, SUM(amount_disbursed) FROM {FPV} GROUP BY 1 "
            f"UNION ALL SELECT lgd_district, SUM(amount_disbursed) FROM {FLV} GROUP BY 1 "
            f"UNION ALL SELECT lgd_district, SUM(total_disbursement) FROM {CLV} GROUP BY 1 "
            f"UNION ALL SELECT lgd_district, SUM(amount_disbursed) FROM {CSV} GROUP BY 1"
            ") t WHERE d IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
Q("A10", "A", T("Which district gets the most money across all the schemes that have money?",
                R("all", COMBINED, "rupees", take=3, ck=False),
                R("mg", by("lgd_district", MG_EXP, EXP), "lakh", take=1, ck=False),
                R("pm", by("lgd_district", PM_REL, PMV), "rupees", take=1, ck=False),
                say="West Garo Hills. Adding up every scheme that records money, {all:lead3}. It also leads MGNREGA "
                    "({mg:firstv}) and PMAY-G ({pm:firstv}) on their own.",
                any_of=[["West Garo Hills", "WEST GARO HILLS"]]), gold="XS-05")
Q("A11", "A", T("Which district leads in each scheme?",
                R("mg", by("lgd_district", MG_HH, EMP), take=1), R("pm", by("lgd_district", PM_H, PMV), take=1),
                RA("fp", R("a", by("lgd_district", FP_B, FPV), take=1), R("b", by("district_name_raw", FP_B, FPV), take=1)),
                R("fl", by("lgd_district", FL_M, FLV), take=1),
                RA("ce", R("a", by("lgd_district", CE_V, CEV), take=1, word="valid"),
                   R("b", by("lgd_district", CE_ALL, CEV), take=1)),
                R("cl", by("lgd_district", CL_APP, CLV), take=1), R("cs", by("lgd_district", CS_PAID, CSV), take=1),
                R("hs", by("lgd_district", HS_APPS, HSV), take=1),
                say="MGNREGA: {mg:first} ({mg:firstv} households). PMAY-G: {pm:first} ({pm:firstv} houses). Focus Plus: "
                    "{fp:first} ({fp:firstv} beneficiaries). Focus Legacy: {fl:first} ({fl:firstv} members). CM Elevate: "
                    "{ce:first} ({ce:firstv} valid applications). CM Elevate Legacy: {cl:first} ({cl:firstv} applicants). "
                    "CMSS: {cs:first} ({cs:firstv} students paid). Homestay: {hs:first} ({hs:firstv} applications)."))
Q("A12", "A", T("Compare MGNREGA households employed and PMAY-G houses in Ri Bhoi",
                V("mg", one(MG_HH, EMP, dist("RI BHOI"))), V("pm", one(PM_H, PMV, dist("RI BHOI"))),
                say="Ri Bhoi: {mg} MGNREGA households given work (all years added) and {pm} PMAY-G houses."), gold="XS-03")
Q("A13", "A", T("In Dalu block, how many MGNREGA households and PMAY-G houses are there?",
                V("mg", one(MG_HH, EMP, blk("DALU"))), V("pm", one(PM_H, PMV, blk("DALU"))),
                say="Dalu block: {mg} MGNREGA households given work (all years added) and {pm} PMAY-G houses."),
  gold="XS-07")
Q("A14", "A", T("Compare Focus Plus and Focus Legacy amounts in FY 2022-23",
                V("fp", one(FP_A, FPV, yr(2022)), "rupees"), V("fl", one(FL_A, FLV, yr(2022)), "rupees"),
                say="In 2022-23 Focus Plus disbursed {fp} and Focus Legacy {fl}."), gold="XS-04")
Q("A15", "A", T("Compare the number of beneficiaries and the total amount for Focus Plus, Focus Legacy and "
                "CM Elevate Legacy.",
                V("fpb", one(FP_B, FPV)), V("fpa", one(FP_A, FPV), "rupees"), V("fla", one(FL_A, FLV), "rupees"),
                V("cla", one(CL_T, CLV), "rupees"), V("flm", one(FL_M, FLV), ck=False),
                V("flg", one(FL_PG, FLV), ck=False), V("clb", one(CL_APP, CLV), ck=False),
                say="Focus Plus: {fpb} beneficiaries, {fpa}. Focus Legacy: {flm} members in {flg} producer groups, "
                    "{fla}. CM Elevate Legacy: {clb} applicants, {cla}."), gold="XS-06")
Q("A16", "A", T("Compare Focus Plus beneficiaries and CMSS students paid in East Khasi Hills",
                V("fp", one(FP_B, FPV, dist("EAST KHASI HILLS"))), V("cs", one(CS_PAID, CSV, dist("EAST KHASI HILLS"))),
                say="East Khasi Hills: {fp} Focus Plus beneficiaries and {cs} CMSS students paid."))

# ═════════════════════════════ M. MGNREGA ═════════════════════════════
Q("M1", "M", T("Total MGNREGA person-days statewide in FY 2023-24?", V("v", one(MG_PD, EMP, yr(2023))),
               say="{v} person-days of employment in 2023-24."), gold="G-D1")
Q("M2", "M", T("Total MGNREGA expenditure across all financial years in Meghalaya?", V("v", one(MG_EXP, EXP), "lakh"),
               say="{v} spent from 2022-23 to 2025-26."), gold="CARD-mg-exp")
Q("M3", "M", T("How many villages had MGNREGA activity in Meghalaya?",
               V("v", f"SELECT COUNT(DISTINCT village_code) FROM (SELECT village_code FROM {EMP} UNION "
                      f"SELECT village_code FROM {EXP}) t"),
               say="{v} villages appear in MGNREGA's employment or expenditure records."), gold="CARD-mg-vil")
Q("M4", "M", T("How many households completed 100 days of MGNREGA work in 2025-26?", V("v", one(MG_100, EMP, yr(2025))),
               say="{v} households completed 100 days in 2025-26."))
Q("M5", "M", T("What was the total expenditure in West Garo Hills during 2023-24?",
               V("v", one(MG_EXP, EXP, dist("WEST GARO HILLS"), yr(2023)), "lakh"),
               say="MGNREGA spent {v} in West Garo Hills in 2023-24."), gold="UAT-M02")
Q("M6", "M", T("how many person days did nrega give in west garo hills in 23-24",
               V("v", one(MG_PD, EMP, dist("WEST GARO HILLS"), yr(2023))),
               say="{v} person-days in West Garo Hills in 2023-24."), gold="PF-MG-casual")
Q("M7", "M", T("Uh, MGNREGA, total expenditure, East Garo Hills, twenty twenty four twenty five?",
               V("v", one(MG_EXP, EXP, dist("EAST GARO HILLS"), yr(2024)), "lakh"),
               say="{v} spent in East Garo Hills in 2024-25."), gold="W2-PF-MGX-spoken")
Q("M9", "M", T("What was the total expenditure in Gambegre block during 2022-23?",
               V("v", one(MG_EXP, EXP, blk("GAMBEGRE"), yr(2022)), "lakh"),
               say="{v} spent in Gambegre block in 2022-23."), gold="UAT-M03")
Q("M10", "M", T("How many households received employment in Nongstoin block during 2025-26?",
                V("v", one(MG_HH, EMP, blk("NONGSTOIN"), yr(2025))), say="{v} households in Nongstoin block in 2025-26."),
  gold="UAT-M07")
Q("M11", "M", T("How many person-days did Jakrem village get under MGNREGA in 2024-25?",
                V("v", one(MG_PD, EMP, vil("JAKREM"), yr(2024))), say="{v} person-days in Jakrem in 2024-25."),
  gold="W3-VL-01")
Q("M12", "M", T("How many person-days were generated in Mawsynram constituency in 2024-25?",
                V("v", one(MG_PD, EMP, acn("MAWSYNRAM"), yr(2024))),
                say="{v} person-days in Mawsynram constituency in 2024-25."), gold="CV-MG-07")
Q("M13", "M", T("MGNREGA expenditure by district in 2022-23", R("r", by("lgd_district", MG_EXP, EXP, yr(2022)), "lakh"),
                say="{r:lead3}. All twelve: {r:list}."), gold="CV-MG-09")
Q("M14", "M", T("Show MGNREGA person-days by district", R("r", by("lgd_district", MG_PD, EMP)),
                say="All years added: {r:lead3}. All twelve: {r:list}."), gold="CH-07")
Q("M15", "M", T("Which district had the most households completing 100 days in FY 2022-23?",
                R("r", by("lgd_district", MG_100, EMP, yr(2022)), take=3, ck=1),
                say="{r:lead3}."), gold="G-D3")
Q("M16", "M", T("Top 5 districts by MGNREGA person-days in FY 2023-24", R("r", by("lgd_district", MG_PD, EMP, yr(2023)), take=5),
                say="{r:top5}."), gold="G-S5")
Q("M17", "M", T("Which district had the lowest MGNREGA person-days in 2023-24?",
                R("r", by("lgd_district", MG_PD, EMP, yr(2023), asc=True), take=3, ck=1),
                say="{r:first}, with {r:firstv}; then {r:l2} {r:v2} and {r:l3} {r:v3}."), gold="CV-MG-05")
Q("M18", "M", T("Top 3 blocks by MGNREGA expenditure in 2024-25", R("r", by("lgd_block", MG_EXP, EXP, yr(2024)), "lakh", take=3),
                say="{r:top3}."), gold="CV-MG-04")
Q("M20", "M", T("Which block generated the highest person-days during 2023-24?",
                R("r", by("lgd_block", MG_PD, EMP, yr(2023)), take=3, ck=1), say="{r:lead3}."), gold="UAT-M10")
Q("M21", "M", T("Which district had the highest women employment during 2023-24?",
                R("r", by("lgd_district", MG_W, EMP, yr(2023)), take=3, ck=1),
                say="{r:first}, with {r:firstv} women given work; next {r:l2} {r:v2} and {r:l3} {r:v3}."), gold="SH-M027")
Q("M22", "M", T("MGNREGA households provided employment in each financial year", R("r", byfy(MG_HH, EMP)),
                say="{r:list}."), gold="CV-MG-01")
Q("M23", "M", T("MGNREGA expenditure in Ri Bhoi from 2022-23 to 2024-25, year by year",
                R("r", byfy(MG_EXP, EXP, dist("RI BHOI"), "year_key BETWEEN 2022 AND 2024"), "lakh"),
                say="{r:list}."), gold="G-S6")
Q("M24", "M", T("In which financial year was MGNREGA expenditure the highest?",
                R("r", by("financial_year_short", MG_EXP, EXP), "lakh", take=4, ck=1),
                say="{r:first}, with {r:firstv}. The other years: {r:rest}."), gold="W3-YR-01")
Q("M25", "M", T("Compare MGNREGA expenditure in FY 2022-23 vs FY 2023-24 statewide",
                V("a", one(MG_EXP, EXP, yr(2022)), "lakh"), V("b", one(MG_EXP, EXP, yr(2023)), "lakh"),
                say="2022-23: {a}. 2023-24: {b}. Spending fell in 2023-24."), gold="G-S3")
Q("M26", "M", T("Compare MGNREGA person-days in East Khasi Hills and West Garo Hills in 2023-24",
                V("a", one(MG_PD, EMP, dist("EAST KHASI HILLS"), yr(2023))),
                V("b", one(MG_PD, EMP, dist("WEST GARO HILLS"), yr(2023))),
                say="West Garo Hills {b} against East Khasi Hills {a} person-days in 2023-24."), gold="CV-MG-08")
Q("M27", "M", T("Compare MGNREGA expenditure in Ri Bhoi, West Garo Hills and East Khasi Hills in 2024-25",
                V("a", one(MG_EXP, EXP, dist("RI BHOI"), yr(2024)), "lakh"),
                V("b", one(MG_EXP, EXP, dist("WEST GARO HILLS"), yr(2024)), "lakh"),
                V("c", one(MG_EXP, EXP, dist("EAST KHASI HILLS"), yr(2024)), "lakh"),
                say="2024-25: West Garo Hills {b}, East Khasi Hills {c}, Ri Bhoi {a}."))
Q("M28", "M", T("Share of women employed in Ri Bhoi FY 2023-24?",
                V("p", f"SELECT 100.0 * {MG_W} / {MG_PE} FROM {EMP}{W(dist('RI BHOI'), yr(2023))}", "pct"),
                V("w", one(MG_W, EMP, dist("RI BHOI"), yr(2023))), V("n", one(MG_PE, EMP, dist("RI BHOI"), yr(2023))),
                say="{p}: {w} women out of {n} persons employed in Ri Bhoi in 2023-24."), gold="G-D4")
Q("M29", "M", T("What is the cost per person-day under MGNREGA in West Jaintia Hills in 2023-24?",
                V("v", "SELECT SUM(total_exp) * 100000 / NULLIF(SUM(person_days), 0) FROM curated.v_district_year_summary "
                       "WHERE lgd_district = 'WEST JAINTIA HILLS' AND year_key = 2023", "rs"),
                say="{v} per person-day in West Jaintia Hills in 2023-24 (expenditure divided by person-days)."),
  gold="CV-MG-06")
Q("M30", "M", T("What share of MGNREGA expenditure went to unskilled wages in 2024-25 statewide?",
                V("v", f"SELECT 100.0 * SUM(unskilled_wage_exp) / NULLIF(SUM(total_exp), 0) FROM {EXP} WHERE year_key = 2024",
                  "pct"), say="{v} of the money spent in 2024-25 went to unskilled wages."), gold="CV-MG-10")
Q("M33", "M", T("Compare total expenditure and employment generated in East Khasi Hills during 2025-26.",
                V("e", one(MG_EXP, EXP, dist("EAST KHASI HILLS"), yr(2025)), "lakh"),
                V("p", one(MG_PD, EMP, dist("EAST KHASI HILLS"), yr(2025))),
                say="East Khasi Hills, 2025-26: {e} spent and {p} person-days of employment."), gold="SH-M030")
Q("M34", "M", T("Give me the expenditure breakdown for Myriem during 2023-24.",
                V("u", one("ROUND(SUM(unskilled_wage_exp), 2)", EXP, vil("MYRIEM"), yr(2023)), "lakh"),
                V("s", one("ROUND(SUM(semi_skilled_wage_exp), 2)", EXP, vil("MYRIEM"), yr(2023)), "lakh"),
                V("m", one(MG_MAT, EXP, vil("MYRIEM"), yr(2023)), "lakh"),
                V("t", one(MG_EXP, EXP, vil("MYRIEM"), yr(2023)), "lakh"),
                say="Myriem, 2023-24: unskilled wages {u}, semi-skilled wages {s}, materials {m}; total {t}."),
  gold="UAT-M09")
Q("M35", "M", T("What was MGNREGA material expenditure statewide in 2024-25?", V("v", one(MG_MAT, EXP, yr(2024)), "lakh"),
                say="{v} was spent on materials in 2024-25."))

# ═════════════════════════════ P. PMAY-G ═════════════════════════════
Q("P1", "P", T("How many PMAY-G houses in total, and how many completed?",
               V("h", one(PM_H, PMV)), V("c", one(PM_C, PMV)), V("i", one(PM_IP, PMV), ck=False),
               V("o", one("COUNT(*) FILTER (WHERE is_completed IS NOT TRUE AND is_in_progress IS NOT TRUE)", PMV),
                 label="neither completed nor under construction", ck=False),
               say="{h} houses sanctioned; {c} completed, {i} still under construction and {o} not started or with "
                   "no status."), gold="G-D5")
Q("P2", "P", T("How many PMAY-G houses have been sanctioned and completed in Meghalaya, and what is the completion rate?",
               V("h", one(PM_H, PMV)), V("c", one(PM_C, PMV)),
               VA("r", V("a", f"SELECT 100.0 * {PM_C} / COUNT(*) FROM {PMV}", "pct"),
                  V("b", f"SELECT 100.0 * {PM_C} / COUNT(*) FROM {PMV} WHERE sanctioned_amount > 0", "pct"),
                  why="all houses, or only houses with a sanctioned amount"),
               say="{h} sanctioned, {c} completed: a completion rate of {r}."), gold="RAG-D1")
Q("P3", "P", T("Total PMAY-G amount released in Meghalaya across all years?", V("v", one(PM_REL, PMV), "rupees"),
               say="{v} released."), gold="CARD-pm-rel")
Q("P4", "P", T("Total PMAY-G amount still pending statewide?", V("v", one(PM_PEND, PMV), "rupees"),
               V("s", one(PM_SAN, PMV), "rupees", ck=False),
               say="{v} is still to be released, out of {s} sanctioned."), gold="G-D7")
Q("P6", "P", T("How many PMAY houses have been completed in West Garo Hills?", V("v", one(PM_C, PMV, dist("WEST GARO HILLS"))),
               say="{v} houses completed in West Garo Hills."), gold="UAT-P10")
Q("P7", "P", T("How much PMAY-G money has been released in East Jaintia Hills?",
               V("v", one(PM_REL, PMV, dist("EAST JAINTIA HILLS")), "rupees"), say="{v} released in East Jaintia Hills."),
  gold="CV-PM-04")
Q("P8", "P", T("How many houses are still incomplete in Ri Bhoi?",
               VA("v", V("a", one("COUNT(*) FILTER (WHERE is_completed IS NOT TRUE)", PMV, dist("RI BHOI")), label="not completed"),
                  V("b", one(PM_IP, PMV, dist("RI BHOI")), label="under construction"),
                  why="every house not completed, or only those under construction"),
               say="{v} houses in Ri Bhoi are not completed ({v:a2} of them under construction)."), gold="SH-P005")
Q("P9", "P", T("Give me the PMAY financial summary for East Garo Hills.",
               V("s", one(PM_SAN, PMV, dist("EAST GARO HILLS")), "rupees"),
               V("r", one("SUM(COALESCE(amount_released, 0))", PMV, dist("EAST GARO HILLS")), "rupees"),
               V("p", one("SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0))", PMV, dist("EAST GARO HILLS")), "rupees"),
               say="East Garo Hills: {s} sanctioned, {r} released, {p} still to be released."), gold="SH-P016")
Q("P10", "P", T("Give me the PMAY financial summary for Amlarem block.",
                V("s", one(PM_SAN, PMV, blk("AMLAREM")), "rupees"),
                V("r", one("SUM(COALESCE(amount_released, 0))", PMV, blk("AMLAREM")), "rupees"),
                V("p", one("SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0))", PMV, blk("AMLAREM")), "rupees"),
                say="Amlarem block: {s} sanctioned, {r} released, {p} still to be released."), gold="UAT-P07")
Q("P12", "P", T("How many PMAY beneficiaries are there in GABIL SONGGITCHAM?", V("v", one(PM_H, PMV, vil("GABIL SONGGITCHAM"))),
                say="{v} beneficiaries (houses sanctioned) in Gabil Songgitcham."), gold="UAT-P01")
Q("P13", "P", T("Give me the house status breakdown for GABIL SONGGITCHAM.",
                R("r", by("COALESCE(status_name, 'No status')", "COUNT(*)", PMV, vil("GABIL SONGGITCHAM"))),
                say="{r:list}."), gold="UAT-P04")
Q("P15", "P", T("PMAY-G houses completed by district", R("r", by("lgd_district", PM_C, PMV)),
                say="{r:lead3}. All twelve: {r:list}."), gold="CH-01")
Q("P16", "P", T("PMAY-G houses sanctioned in each financial year", R("r", byfy(PM_H, PMV)),
                V("n", one(PM_H, PMV, "year_key IS NULL"), ck=False),
                say="{r:list} ({n} houses carry no year)."), gold="CV-PM-01")
Q("P17", "P", T("Top 5 districts by PMAY-G houses completed", R("r", by("lgd_district", PM_C, PMV), take=5),
                say="{r:top5}."), gold="W2-RK-01")
Q("P18", "P", T("Top 3 blocks by PMAY-G houses completed", R("r", by("lgd_block", PM_C, PMV), take=3),
                say="{r:top3}."), gold="CV-PM-02")
Q("P19", "P", T("How many PMAY-G houses in total, and which district has the most?", V("h", one(PM_H, PMV)),
                R("r", by("lgd_district", PM_H, PMV), take=3, ck=2),
                say="{h} houses; {r:lead3}."), gold="G-S4")
Q("P20", "P", T("Compare PMAY-G houses completed in Ri Bhoi and West Jaintia Hills",
                V("a", one(PM_C, PMV, dist("RI BHOI"))), V("b", one(PM_C, PMV, dist("WEST JAINTIA HILLS"))),
                say="Ri Bhoi {a} completed, West Jaintia Hills {b}."), gold="CV-PM-05")
Q("P22", "P", T("What percentage of PMAY houses are completed in South Garo Hills?",
                VA("v", V("a", f"SELECT 100.0 * {PM_C} / COUNT(*) FROM {PMV} WHERE lgd_district = 'SOUTH GARO HILLS'", "pct"),
                   V("b", f"SELECT 100.0 * {PM_C} / COUNT(*) FROM {PMV} WHERE lgd_district = 'SOUTH GARO HILLS' "
                          "AND sanctioned_amount > 0", "pct"), why="all houses, or houses with a sanctioned amount"),
                say="{v} of the houses in South Garo Hills are completed."), gold="SH-P020")
Q("P23", "P", T("What percentage of the sanctioned amount has been released in North Garo Hills?",
                V("v", f"SELECT 100.0 * SUM(COALESCE(amount_released, 0)) / SUM(sanctioned_amount) FROM {PMV} "
                       "WHERE lgd_district = 'NORTH GARO HILLS'", "pct"),
                say="{v} of the sanctioned amount has been released in North Garo Hills."), gold="SH-P021")
Q("P24", "P", T("What share of all PMAY-G houses are in West Garo Hills?",
                V("v", f"SELECT 100.0 * COUNT(*) FILTER (WHERE lgd_district = 'WEST GARO HILLS') / COUNT(*) FROM {PMV}", "pct"),
                V("n", one(PM_H, PMV, dist("WEST GARO HILLS")), ck=False), V("t", one(PM_H, PMV), ck=False),
                say="{v}: {n} of the state's {t} houses."), gold="W3-RT-03")
Q("P25", "P", T("Which block in West Garo Hills has the most PMAY-G houses completed?",
                R("r", by("lgd_block", PM_C, PMV, dist("WEST GARO HILLS")), take=3, ck=1), say="{r:lead3}."))

# ═════════════════════════════ F. Focus Plus ═════════════════════════════
FP_DIST = ("Focus Plus district figures follow the source file's district names; for West Garo Hills and South West "
           "Garo Hills these differ from the LGD map by about 20 beneficiaries (KI-065), so either reading is accepted.")
Q("F1", "F", T("Total amount disbursed under Focus Plus across all years?", V("v", one(FP_A, FPV), "rupees"),
               V("n", one(FP_P, FPV), ck=False), say="{v} disbursed in {n} payments."), gold="CARD-fp-amt")
Q("F2", "F", T("Focus Plus beneficiaries FY 2022-23 and amount paid?", V("b", one(FP_B, FPV, yr(2022))),
               V("a", one(FP_A, FPV, yr(2022)), "rupees"), say="{b} beneficiaries were paid {a} in 2022-23."), gold="G-D8")
Q("F3", "F", T("Focus Plus amount disbursed by financial year", R("r", byfy(FP_A, FPV), "rupees"),
               say="{r:list}. The data holds only these two years."), gold="W3-YR-02")
Q("F5", "F", T("How many Focus+ beneficiaries are there in each district?",
               RA("r", R("a", by("lgd_district", FP_B, FPV)), R("b", by("district_name_raw", FP_B, FPV)), why=FP_DIST),
               say="{r:lead3}. All twelve: {r:list}."), gold="SH-F002", note=FP_DIST)
Q("F6", "F", T("Which district received the highest total Focus Plus disbursement?",
               RA("r", R("a", by("lgd_district", FP_A, FPV), "rupees", take=3, ck=1),
                  R("b", by("district_name_raw", FP_A, FPV), "rupees", take=3, ck=1), why=FP_DIST),
               say="{r:lead3}."), gold="SH-F023")
Q("F7", "F", T("Which district has the fewest Focus Plus beneficiaries?",
               RA("r", R("a", by("lgd_district", FP_B, FPV, asc=True), take=3, ck=1),
                  R("b", by("district_name_raw", FP_B, FPV, asc=True), take=3, ck=1), why=FP_DIST),
               say="{r:first}, with {r:firstv}; then {r:l2} {r:v2} and {r:l3} {r:v3}."), gold="W2-RK-05")
Q("F8", "F", T("Give me the gender-wise breakdown of Focus+ beneficiaries.", R("r", by("gender", FP_B, FPV)),
               V("n", one(FP_B, FPV, "gender IS NULL"), ck=False),
               say="{r:list}. Gender is filled in only for these; the other {n} beneficiaries have none recorded."),
  gold="SH-F008")
Q("F9", "F", T("What is the average Focus Plus amount disbursed per beneficiary?",
               V("v", f"SELECT 1.0 * {FP_A} / {FP_B} FROM {FPV}", "rs"), say="About {v} per beneficiary."), gold="SH-F024")
Q("F10", "F", T("Compare the number of Focus Plus beneficiaries in East Khasi Hills and North Garo Hills.",
                V("a", one(FP_B, FPV, dist("EAST KHASI HILLS"))), V("b", one(FP_B, FPV, dist("NORTH GARO HILLS"))),
                say="East Khasi Hills {a}, North Garo Hills {b}."), gold="SH-F026")
Q("F11", "F", T("How many Focus Plus beneficiaries are there in Selsella block?",
                V("v", one(FP_B, FPV, "UPPER(block_name_raw) = 'SELSELLA'")), say="{v} beneficiaries in Selsella block."),
  gold="CV-FP-01")
Q("F12", "F", T("How much was disbursed under Focus Plus Tranch 1?", V("v", one(FP_A, FPV, "tranche_label = 'Tranch 1'"), "rupees"),
                R("t", by("tranche_label", FP_A, FPV), "rupees", ck=False),
                say="{v} under Tranche 1. By tranche: {t:list}."), gold="SH-F007")

# ═════════════════════════════ L. Focus Legacy ═════════════════════════════
Q("L1", "L", T("Focus Legacy producer groups and total, all years?", V("g", one(FL_PG, FLV)), V("a", one(FL_A, FLV), "rupees"),
               R("y", byfy(FL_A, FLV), "rupees", ck=False),
               say="{g} producer groups were paid {a} in all ({y:list})."), gold="G-D9")
Q("L3", "L", T("What was the total Focus Legacy amount remitted in FY 2024-25?", V("v", one(FL_A, FLV, yr(2024)), "rupees"),
               say="{v} remitted in 2024-25."), gold="SH-L023")
Q("L4", "L", T("Focus Legacy amount remitted by financial year", R("r", byfy(FL_A, FLV), "rupees"),
               say="{r:list}. There are no Focus Legacy payments for 2023-24."), gold="CH-14")
Q("L5", "L", T("How many Focus Legacy producer groups are mapped to each district?", R("r", by("lgd_district", FL_PG, FLV)),
               say="{r:lead3}. All twelve: {r:list}."), gold="SH-L025")
Q("L6", "L", T("Which district received the highest Focus Legacy amount?",
               R("r", by("lgd_district", FL_A, FLV), "rupees", take=3, ck=1), say="{r:lead3}."), gold="CV-FL-02")
Q("L7", "L", T("Top 3 districts by number of Focus Legacy producer groups", R("r", by("lgd_district", FL_PG, FLV), take=3),
               say="{r:top3}."), gold="W2-RK-03")
Q("L8", "L", T("Compare the total Focus Legacy remittance between FY 2022-23 and FY 2024-25",
               V("a", one(FL_A, FLV, yr(2022)), "rupees"), V("b", one(FL_A, FLV, yr(2024)), "rupees"),
               say="2022-23: {a}. 2024-25: {b}."), gold="CV-FL-03")
Q("L9", "L", T("Compare the Focus Legacy amounts in Ri Bhoi, West Garo Hills and East Khasi Hills",
               V("a", one(FL_A, FLV, dist("RI BHOI")), "rupees"), V("b", one(FL_A, FLV, dist("WEST GARO HILLS")), "rupees"),
               V("c", one(FL_A, FLV, dist("EAST KHASI HILLS")), "rupees"),
               say="West Garo Hills {b}, East Khasi Hills {c}, Ri Bhoi {a}."), gold="W3-MP-01")
Q("L10", "L", T("What is the average Focus Legacy amount per producer group in East Jaintia Hills?",
                V("v", f"SELECT SUM(amount_disbursed)::numeric / COUNT(DISTINCT pg_id) FROM {FLV} "
                       "WHERE lgd_district = 'EAST JAINTIA HILLS'", "rs"),
                say="About {v} per producer group."), gold="W3-RT-04")
Q("L11", "L", T("How many Focus Legacy producer groups are mapped to Mawsynram constituency?",
                V("v", one(FL_PG, FLV, acn("MAWSYNRAM"))), say="{v} producer groups."), gold="SH-L028")
Q("L12", "L", T("How many Focus Legacy producer groups are there in Mawkyrwat block?", V("v", one(FL_PG, FLV, blk("MAWKYRWAT"))),
                say="{v} producer groups in Mawkyrwat block."), gold="CV-FL-01")

# ═════════════════════════════ E. CM Elevate (applications) ═════════════════════════════
CEWHY = "D-B1-CME-01: valid applications by default (the answer says 'valid'), or every application"


def ce(name, *c):
    return VA(name, V("a", one(CE_V, CEV, *c), label="valid applications", word="valid"),
              V("b", one(CE_ALL, CEV, *c), label="all applications"), why=CEWHY)


def ce_rows(name, col, *c, take="all", ck=True):
    return RA(name, R("a", by(col, CE_V, CEV, *c), take=take, ck=ck, word="valid"),
              R("b", by(col, CE_ALL, CEV, *c), take=take, ck=ck), why=CEWHY)


Q("E1", "E", T("How many CM Elevate applications are there in total?", ce("v"),
               R("s", by("COALESCE(data_verified, 'not recorded')", CE_ALL, CEV), ck=False),
               say="{v} valid applications; {v:a2} counting every application ({s:list})."), gold="CARD-cme-apps")
Q("E2", "E", T("How many CM ELEVATE applicants are there in each district?", ce_rows("r", "lgd_district"),
               say="Valid applications: {r:lead3}. All twelve: {r:list}. (Every application: {r:a2.top3} …)"),
  gold="SH-C004")
Q("E3", "E", T("How many applicants are there under each CM ELEVATE program?", ce_rows("r", "scheme_name", take=5),
               say="Valid applications, top five: {r:top5}."), gold="SH-C005")
Q("E4", "E", T("Which CM Elevate scheme has the most applications?", ce_rows("r", "scheme_name", take=2, ck=1),
               say="{r:first}: {r:firstv} valid applications ({r:a2.firstv} in all). Next {r:l2} with {r:v2}."),
  gold="CV-CE-02")
Q("E5", "E", T("How many CM Elevate applications are there in East Khasi Hills?", ce("v", dist("EAST KHASI HILLS")),
               say="{v} valid applications ({v:a2} in all)."), gold="CV-CE-01")
Q("E6", "E", T("How many CM Elevate applications came from Jirang block?", ce("v", blk("JIRANG")),
               say="{v} valid applications from Jirang block ({v:a2} in all)."), gold="W2-BLK-07")
Q("E7", "E", T("How many applicants are there under the Piggery scheme in Ri Bhoi?",
               ce("v", dist("RI BHOI"), "scheme_name = 'Meghalaya Piggery Development Scheme'"),
               say="{v} valid applications to the Piggery Development Scheme in Ri Bhoi ({v:a2} in all)."), gold="SH-C006")
Q("E8", "E", T("How many CM ELEVATE applications are pending?",
               V("v", one("COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid' AND file_status IN "
                          "('Pending', 'Send Back'))", CEV)),
               say="{v} valid applications are pending (waiting, or sent back to the applicant)."), gold="SH-C018")
Q("E9", "E", T("How many CM Elevate applications have been rejected?", ce("v", "file_status = 'Rejected'"),
               say="{v} valid applications were rejected ({v:a2} counting every application)."), gold="W2-CE-REJ-02")
Q("E11", "E", T("CM Elevate applications by status as a donut chart", ce_rows("r", "COALESCE(file_status, '(not recorded)')"),
                say="Valid applications by status: {r:list}."), gold="CH-04")

# ═════════════════════════════ C. CM Elevate Legacy ═════════════════════════════
Q("C1", "C", T("What is the total amount disbursed under CM Elevate Legacy?", V("v", one(CL_T, CLV), "rupees"),
               say="{v} disbursed (subsidy and loan together)."), gold="SH-X017", cat="cm_elevate_legacy")
Q("C2", "C", T("How much has been disbursed under CM Elevate Legacy, split into subsidy and loan?",
               V("t", one(CL_T, CLV), "rupees"), V("s", one(CL_S, CLV), "rupees"), V("l", one(CL_L, CLV), "rupees"),
               say="{t} in all: {s} subsidy and {l} loan."), gold="CARD-cml-amt", cat="cm_elevate_legacy")
Q("C3", "C", T("How many records does CM Elevate Legacy have?", V("v", one(CL_REC, CLV)), V("a", one(CL_APP, CLV), ck=False),
               V("d", one("COUNT(*) FILTER (WHERE sanctioned_amount IS NULL)", CLV), ck=False),
               say="{v} records; {a} of them have a sanctioned amount ({d} were de-sanctioned and paid nothing)."), gold="CARD-cml-rec", cat="cm_elevate_legacy")
Q("C4", "C", T("What is the total amount disbursed under each CM Elevate Legacy scheme?",
               R("r", by("scheme_name", CL_T, CLV), "rupees", take=5), say="Top five: {r:top5}."),
  gold="SH-X018", cat="cm_elevate_legacy")
Q("C5", "C", T("Which 3 CM Elevate Legacy schemes got the most subsidy?", R("r", by("scheme_name", CL_S, CLV), "rupees", take=3),
               say="{r:top3}."), gold="W2-RK-04", cat="cm_elevate_legacy")
Q("C6", "C", T("What is the total CM Elevate Legacy disbursement amount for each district?",
               R("r", by("lgd_district", CL_T, CLV), "rupees", take=5),
               say="{r:lead3}; then {r:l4} {r:v4} and {r:l5} {r:v5}."), gold="SH-X027", cat="cm_elevate_legacy")
Q("C7", "C", T("How many CM Elevate Legacy applications are associated with each loan entity?",
               R("r", by("loan_entity", CL_REC, CLV)), V("n", one(CL_REC, CLV, "loan_entity IS NULL"), ck=False),
               say="{r:list} ({n} have no loan entity recorded)."), gold="SH-X021", cat="cm_elevate_legacy")
Q("C8", "C", T("What was the total CM Elevate Legacy disbursement in each financial year?", R("r", byfy(CL_T, CLV), "rupees"),
               V("n", one(CL_T, CLV, "year_key IS NULL"), "rupees", ck=False),
               say="{r:list}; another {n} was paid on records with no year."), gold="SH-X024", cat="cm_elevate_legacy")
Q("C9", "C", T("How much CM Elevate Legacy subsidy was disbursed in Ri Bhoi?", V("v", one(CL_S, CLV, dist("RI BHOI")), "rupees"),
               say="{v} of subsidy in Ri Bhoi."), gold="CV-CL-01", cat="cm_elevate_legacy")
Q("C10", "C", T("How much CM Elevate Legacy loan was disbursed through LIFCOM?",
                V("v", one(CL_L, CLV, "loan_entity = 'LIFCOM'"), "rupees"), say="{v} of loan through LIFCOM."),
  gold="CV-CL-03", cat="cm_elevate_legacy")
Q("C11", "C", T("Compare the number of sanctioned CM Elevate Legacy applications across West Garo Hills and East Khasi Hills.",
                V("a", one(CL_APP, CLV, dist("WEST GARO HILLS"))), V("b", one(CL_APP, CLV, dist("EAST KHASI HILLS"))),
                say="West Garo Hills {a}, East Khasi Hills {b} sanctioned applicants."), gold="SH-X035",
  note="East Khasi Hills also has 1 de-sanctioned record, which is not counted.",
  cat="cm_elevate_legacy")
Q("C12", "C", T("CM Elevate Legacy total disbursement in Ri Bhoi in 2025-26",
                V("v", one(CL_T, CLV, dist("RI BHOI"), yr(2025)), "rupees"), say="{v} in Ri Bhoi in 2025-26."),
  gold="W3-TT-02", cat="cm_elevate_legacy")

# ═════════════════════════════ S. CMSS and Homestay ═════════════════════════════
Q("S1", "S", T("How many students were paid under CMSS?", V("v", one(CS_PAID, CSV)), V("a", one(CS_A, CSV), "rupees", ck=False),
               say="{v} students were paid, {a} in all (2025-26)."), gold="W4-RG-CSPA-A")
Q("S2", "S", T("How much has been disbursed under CMSS?", V("v", one(CS_A, CSV), "rupees"), say="{v} disbursed (2025-26)."))
Q("S3", "S", T("How many CMSS applications are there, and how many have been paid?", V("a", one(CS_APPS, CSV)),
               V("p", one(CS_PAID, CSV)), say="{a} applications, of which {p} have been paid."))
Q("S4", "S", T("Which district has the most CMSS students paid?", R("r", by("lgd_district", CS_PAID, CSV), take=3, ck=1),
               say="{r:lead3}."))
Q("S5", "S", T("How many Homestay applications are there?", V("v", one(HS_APPS, HSV)),
               say="{v} applications (2025-26 and 2026-27)."), gold="W4-RG-HSAP-A")
Q("S6", "S", T("How many Homestay applications have been approved?", V("v", one(HS_APR, HSV)),
               R("s", by("COALESCE(file_status, 'not recorded')", HS_APPS, HSV), ck=False),
               say="{v} approved. All applications by status: {s:list}."))
Q("S7", "S", T("Which district has the most Homestay applications?", R("r", by("lgd_district", HS_APPS, HSV), take=3, ck=1),
               say="{r:lead3}."))
Q("S8", "S", T("How many Homestay applications came in each financial year?", R("r", byfy(HS_APPS, HSV)),
               say="{r:list}."))

# ═════════════════════════════ V. conversations ═════════════════════════════
Q("V1", "V", T("MGNREGA person-days in East Khasi Hills in 2023-24.", V("v", one(MG_PD, EMP, dist("EAST KHASI HILLS"), yr(2023))),
               say="{v} person-days."),
  T("And for Ri Bhoi?", V("v", one(MG_PD, EMP, dist("RI BHOI"), yr(2023))), say="{v} in Ri Bhoi (2023-24).", schemes=[MG]),
  T("What about the year before?", V("v", one(MG_PD, EMP, dist("RI BHOI"), yr(2022))), say="{v} in Ri Bhoi in 2022-23.",
    schemes=[MG]), gold="FU-01")
Q("V2", "V", T("Tell me about PMAY-G houses by district.", R("r", by("lgd_district", PM_H, PMV), take=3),
               say="{r:lead3} … (all twelve districts)."),
  T("Only the completed ones.", R("r", by("lgd_district", PM_C, PMV), take=3), say="Completed: {r:lead3} …",
    schemes=[PM], route="data"),
  T("Top 3 districts.", R("r", by("lgd_district", PM_C, PMV), take=3), say="{r:top3}.", schemes=[PM]), gold="FU-02")
Q("V3", "V", T("Total MGNREGA expenditure statewide by financial year", R("r", byfy(MG_EXP, EXP), "lakh"), say="{r:list}."),
  T("break that down by district for 2023-24", R("r", by("lgd_district", MG_EXP, EXP, yr(2023)), "lakh", take=5),
    say="2023-24: {r:lead3} …", schemes=[MG]),
  T("only West Garo Hills", V("v", one(MG_EXP, EXP, dist("WEST GARO HILLS"), yr(2023)), "lakh"),
    say="West Garo Hills, 2023-24: {v}.", schemes=[MG]), gold="FU-04")
Q("V4", "V", T("How many households got MGNREGA work in West Garo Hills in 2023-24?",
               V("v", one(MG_HH, EMP, dist("WEST GARO HILLS"), yr(2023))), say="{v} households."),
  T("and persons?", V("v", one(MG_PE, EMP, dist("WEST GARO HILLS"), yr(2023))), say="{v} persons.", schemes=[MG]),
  T("and how many of them were women?", V("v", one(MG_W, EMP, dist("WEST GARO HILLS"), yr(2023))), say="{v} women.",
    schemes=[MG]), gold="FU-08")
Q("V5", "V", T("PMAY-G houses completed in Ri Bhoi", V("v", one(PM_C, PMV, dist("RI BHOI"))), say="{v} houses completed."),
  T("and the sanctioned amount there?", V("v", one(PM_SAN, PMV, dist("RI BHOI")), "rupees"), say="{v} sanctioned.",
    schemes=[PM]),
  T("what percentage of it has been released?",
    V("v", f"SELECT 100.0 * SUM(COALESCE(amount_released, 0)) / SUM(sanctioned_amount) FROM {PMV} "
           "WHERE lgd_district = 'RI BHOI'", "pct"), say="{v} has been released.", schemes=[PM]), gold="FU-09")
Q("V6", "V", T("Focus Legacy amount by financial year", R("r", byfy(FL_A, FLV), "rupees"), say="{r:list}."),
  T("which year had the most?", R("r", by("financial_year_short", FL_A, FLV), "rupees", take=1),
    say="{r:first}, with {r:firstv}.", schemes=[FL]), gold="FU-10")
Q("V7", "V", T("Which district had the most PMAY-G houses sanctioned in 2020-21?",
               R("r", by("lgd_district", PM_H, PMV, yr(2020)), take=1), say="{r:first}, with {r:firstv} houses."),
  T("and the least?", R("r", by("lgd_district", PM_H, PMV, yr(2020), asc=True), take=1),
    say="{r:first}, with {r:firstv} houses.", schemes=[PM]), gold="FU-15")
Q("V8", "V", T("MGNREGA person-days in Ri Bhoi in 2023-24", V("v", one(MG_PD, EMP, dist("RI BHOI"), yr(2023))),
               say="{v} person-days."),
  T("break that down by block", R("r", by("lgd_block", MG_PD, EMP, dist("RI BHOI"), yr(2023))), say="{r:list}.",
    schemes=[MG]), gold="FU-16")
Q("V9", "V", T("How many Focus Plus beneficiaries are there in East Khasi Hills?", V("v", one(FP_B, FPV, dist("EAST KHASI HILLS"))),
               say="{v} beneficiaries."),
  T("And in Ri Bhoi?", V("v", one(FP_B, FPV, dist("RI BHOI"))), say="{v} in Ri Bhoi.", schemes=[FP]),
  T("and how much was paid there?", V("v", one(FP_A, FPV, dist("RI BHOI")), "rupees"), say="{v} paid in Ri Bhoi.",
    schemes=[FP]), gold="FU-25")
Q("V11", "V", T("MGNREGA households employed in Ri Bhoi in 2024-25", V("v", one(MG_HH, EMP, dist("RI BHOI"), yr(2024))),
                say="{v} households."),
  T("and in 2023-24?", V("v", one(MG_HH, EMP, dist("RI BHOI"), yr(2023))), say="{v} in 2023-24.", schemes=[MG]),
  T("and in Umling block?", V("v", one(MG_HH, EMP, blk("UMLING"), yr(2023))), say="{v} in Umling block (2023-24).",
    schemes=[MG]), gold="W2-CH-01")
Q("V12", "V", T("Focus Legacy amount by district", R("r", by("lgd_district", FL_A, FLV), "rupees", take=3), say="{r:lead3} …"),
  T("which district had the least?", R("r", by("lgd_district", FL_A, FLV, asc=True), "rupees", take=1),
    say="{r:first}, with {r:firstv}.", schemes=[FL]), gold="W2-CH-03")
Q("V13", "V", T("Women employed under MGNREGA in East Garo Hills in 2023-24",
                V("v", one(MG_W, EMP, dist("EAST GARO HILLS"), yr(2023))), say="{v} women."),
  T("break that down by block", R("r", by("lgd_block", MG_W, EMP, dist("EAST GARO HILLS"), yr(2023))), say="{r:list}.",
    schemes=[MG]), gold="W2-CH-09")
Q("V14", "V", T("PMAY-G houses by block in East Khasi Hills", R("r", by("lgd_block", PM_H, PMV, dist("EAST KHASI HILLS")), take=3),
                say="{r:lead3} … (eleven blocks)."),
  T("which block has the most?", R("r", by("lgd_block", PM_H, PMV, dist("EAST KHASI HILLS")), take=1),
    say="{r:first}, with {r:firstv} houses.", schemes=[PM]), gold="W3-CH-03")
Q("V15", "V", T("Compare MGNREGA households employed in Ri Bhoi and East Khasi Hills in 2023-24",
                V("a", one(MG_HH, EMP, dist("RI BHOI"), yr(2023))), V("b", one(MG_HH, EMP, dist("EAST KHASI HILLS"), yr(2023))),
                say="Ri Bhoi {a}, East Khasi Hills {b}."),
  T("only Ri Bhoi", V("v", one(MG_HH, EMP, dist("RI BHOI"), yr(2023))), say="Ri Bhoi: {v}.", schemes=[MG]), gold="W3-CH-07")
Q("V16", "V", T("How many MGNREGA person-days were generated in West Garo Hills in 2023-24?",
                V("v", one(MG_PD, EMP, dist("WEST GARO HILLS"), yr(2023))), say="{v} person-days."),
  T("what about the households instead", V("v", one(MG_HH, EMP, dist("WEST GARO HILLS"), yr(2023))), say="{v} households.",
    schemes=[MG]), gold="W5-FU-03")
Q("V17", "V", T("How many PMAY-G houses were sanctioned by district?", R("r", by("lgd_district", PM_H, PMV), take=3),
                say="{r:lead3} …"),
  T("only the incomplete ones", R("r", by("lgd_district", PM_IP, PMV), take=3), say="Under construction: {r:lead3} …",
    schemes=[PM]), gold="W5-FU-04")
Q("V19", "V", T("How many MGNREGA person-days were generated?", V("v", one(MG_PD, EMP)), say="{v} person-days (all years)."),
  T("break that down by district", R("r", by("lgd_district", MG_PD, EMP)), say="{r:lead3} … (all twelve).", schemes=[MG],
    route="data"),
  T("now break it down by block", R("r", by("lgd_block", MG_PD, EMP), take=5), say="Top blocks: {r:top5} …", schemes=[MG],
    route="data"),
  T("break it down by financial year", R("r", byfy(MG_PD, EMP)), say="{r:list}.", schemes=[MG], route="data"),
  gold="W4-RG-MGPD-A")
Q("V20", "V", T("How many PMAY-G houses were completed in East Garo Hills?", V("v", one(PM_C, PMV, dist("EAST GARO HILLS"))),
                say="{v} houses completed."),
  T("break that down by block", R("r", by("lgd_block", PM_C, PMV, dist("EAST GARO HILLS"))), say="{r:list}.", schemes=[PM],
    route="data"),
  T("break it down by financial year", R("r", byfy(PM_C, PMV, dist("EAST GARO HILLS"))), say="{r:list}.", schemes=[PM],
    route="data"), gold="W4-RG-PMCO-C")
Q("V21", "V", T("What is the total Focus Legacy amount disbursed in West Garo Hills?",
                V("v", one(FL_A, FLV, dist("WEST GARO HILLS")), "rupees"), say="{v}."),
  T("break that down by block", R("r", by("lgd_block", FL_A, FLV, dist("WEST GARO HILLS")), "rupees", take=5),
    say="{r:lead3} …", schemes=[FL], route="data"),
  T("break it down by financial year", R("r", byfy(FL_A, FLV, dist("WEST GARO HILLS")), "rupees"), say="{r:list}.",
    schemes=[FL], route="data"), gold="W4-RG-FLAM-C")
Q("V22", "V", T("How many CM Elevate applications are there in Ri Bhoi?", ce("v", dist("RI BHOI")),
                say="{v} valid applications ({v:a2} in all)."),
  T("scheme wise", ce_rows("r", "scheme_name", dist("RI BHOI")), say="Valid applications: {r:lead3} …", schemes=[CE],
    route="data"), gold="W4-RG-CEAP-C")
Q("V23", "V", T("Compare beneficiaries across all schemes", *HEADLINE, say=HEADLINE_SAY),
  T("break that down by district", V("mg", one(MG_HH, EMP, dist("WEST GARO HILLS"))),
    V("pm", one(PM_H, PMV, dist("WEST GARO HILLS"))),
    R("mgr", by("lgd_district", MG_HH, EMP), take=3, ck=False), R("pmr", by("lgd_district", PM_H, PMV), take=3, ck=False),
    say="Each scheme by district. MGNREGA households: {mgr:top3} …; PMAY-G houses: {pmr:top3} … (West Garo Hills leads "
        "both: {mg} and {pm}).", route="data"), gold="W4-XS-RG")
Q("V24", "V", T("How many Homestay applications are there in East Khasi Hills?", V("v", one(HS_APPS, HSV, dist("EAST KHASI HILLS"))),
                say="{v} applications."),
  T("break that down by block", R("r", by("lgd_block", HS_APPS, HSV, dist("EAST KHASI HILLS")), take=5), say="{r:lead3} …",
    schemes=[HS], route="data"), gold="W4-RG-HSAP-C")
Q("V25", "V", T("Compare MGNREGA and PMAY-G beneficiaries", V("mg", one(MG_HH, EMP)), V("pm", one(PM_H, PMV)),
                say="MGNREGA {mg} households given work (all years added); PMAY-G {pm} houses."),
  T("only PMAY-G", V("pm", one(PM_H, PMV)), say="PMAY-G: {pm} houses.", schemes=[PM], lacks=["14,94,437"]), gold="FU-05")
Q("V26", "V", T("MGNREGA person-days by district in 2023-24", R("r", by("lgd_district", MG_PD, EMP, yr(2023))),
                say="{r:lead3} … (all twelve)."),
  T("now by block", R("r", by("lgd_block", MG_PD, EMP, yr(2023)), take=5), say="Top blocks: {r:top5} …", schemes=[MG]),
  T("only Ri Bhoi", R("r", by("lgd_block", MG_PD, EMP, dist("RI BHOI"), yr(2023))), say="Ri Bhoi's blocks: {r:list}.",
    schemes=[MG]),
  T("top 3", R("r", by("lgd_block", MG_PD, EMP, dist("RI BHOI"), yr(2023)), take=3), say="{r:top3}.", schemes=[MG]))
Q("V27", "V", T("PMAY-G houses completed by district", R("r", by("lgd_district", PM_C, PMV)), say="{r:lead3} … (all twelve)."),
  T("only East Khasi Hills", V("v", one(PM_C, PMV, dist("EAST KHASI HILLS"))), say="East Khasi Hills: {v}.", schemes=[PM]),
  T("now by block", R("r", by("lgd_block", PM_C, PMV, dist("EAST KHASI HILLS")), take=5), say="{r:lead3} …", schemes=[PM]))

# ═════════════════════════════ K. charts ═════════════════════════════
Q("K1", "K", T("Show MGNREGA person-days trend over the years as a line chart", R("r", byfy(MG_PD, EMP)),
               say="A line over four years: {r:list}."), gold="CH-02")
Q("K2", "K", T("Top 5 districts by FOCUS+ beneficiaries as a pie chart",
               RA("r", R("a", by("lgd_district", FP_B, FPV), take=5), R("b", by("district_name_raw", FP_B, FPV), take=5),
                  why=FP_DIST), say="A pie of {r:top5}."),
  T("now show it as a bar chart", RA("r", R("a", by("lgd_district", FP_B, FPV), take=5),
                                     R("b", by("district_name_raw", FP_B, FPV), take=5), why=FP_DIST),
    say="The same five districts as bars.", schemes=[FP]), gold="CH-08")
Q("K3", "K", T("MGNREGA person-days by district in 2023-24", R("r", by("lgd_district", MG_PD, EMP, yr(2023))),
               say="{r:lead3} … (all twelve)."),
  T("now show the same as a horizontal bar chart", R("r", by("lgd_district", MG_PD, EMP, yr(2023))),
    say="The same twelve districts, redrawn (if a chart kind is not offered, the app says so and draws the nearest one)."),
  gold="CH-12")

# ═════════════════════════════ D. declines / asks back ═════════════════════════════
NO_DATA = [["no data", "not held", "absent", "not recorded", "no record", "does not hold", "doesn't hold"]]
Q("D1", "D", T("Focus Legacy amount disbursed in FY 2023-24?", R("y", byfy(FL_A, FLV), "rupees", ck=False),
               say="It says Focus Legacy has no payments for 2023-24 (never a zero) and names the years it does hold: "
                   "{y:yrs}.", pause=None, has=["2024-25"], any_of=NO_DATA, lacks=["₹0 ", "₹0.", "is 0", "were 0"]),
  gold="G-N1")
Q("D2", "D", T("Total CM Elevate amount disbursed in East Khasi Hills?",
               V("cl", one(CL_T, CLV, dist("EAST KHASI HILLS")), "rupees", ck=False),
               say="CM Elevate (applications) records no money, so it does not give ₹0. If you meant the payments, "
                   "CM Elevate Legacy disbursed {cl} in East Khasi Hills.", pause=None,
               any_of=[["no amount", "not record", "does not", "doesn't", "Legacy"]], lacks=["₹0"]), gold="G-N2")
Q("D3", "D", T("How many MGNREGA person-days in Gotham district in FY 2023-24?",
               say="Gotham is not a district of Meghalaya: it says it cannot find the place, never a silent 0.",
               pause=None, lacks=["is 0", ": 0", "were 0", "0 person"]), gold="G-N3")
Q("D4", "D", T("How many PM-KISAN beneficiaries are there in Meghalaya?",
               say="PM-KISAN is not one of the eight schemes it holds: said plainly, with no figure.", pause=None,
               lacks=["₹"]), gold="G-N4")
Q("D5", "D", T("What was the administrative expenditure in Gambegre block during 2023-24?",
               V("v", one("SUM(admin_total_exp)", EXP, blk("GAMBEGRE"), yr(2023)), "lakh", ck=False),
               say="Administrative expenditure is never filled in at source, so it says it is not recorded instead of "
                   "estimating (the column holds {v}).", pause=None,
               any_of=[["not populated", "never populated", "not recorded", "not available", "0.00"]]), gold="SH-M013")
Q("D6", "D", T("How many CM Elevate applications were approved?",
               R("s", by("COALESCE(file_status, '(not recorded)')", CE_ALL, CEV), ck=False),
               say="The data has no 'approved' status (only {s:yrs}), so it asks what you mean instead of guessing.",
               pause=True), gold="W2-CE-APP-01")
Q("D7", "D", T("Beneficiaries under Focus.", say="'Focus' is two schemes, so it asks: Focus Plus or Focus Legacy?", pause=True),
  T("Focus Plus", V("v", one(FP_B, FPV)), say="{v} Focus Plus beneficiaries.", schemes=[FP]), gold="FU-06")
Q("D8", "D", T("CM Elevate records in Ri Bhoi.", say="It asks which CM Elevate dataset: applications or the Legacy "
                                                    "disbursements.", pause=True),
  T("Applications", ce("v", dist("RI BHOI")), say="{v} valid applications in Ri Bhoi ({v:a2} in all).", schemes=[CE]),
  gold="FU-07")
Q("D9", "D", T("How many PMAY-G houses were sanctioned in 2025-26?", R("y", byfy(PM_H, PMV), ck=False),
               say="PMAY-G sanctions in the data run from {y:yfirst} to {y:ylast}; it says 2025-26 is not held, "
                   "never a zero.", pause=None, lacks=["is 0", "were 0", " 0 houses", ": 0"]))


# ═════════════════════════════ formatting ═════════════════════════════

def ind_int(n) -> str:
    neg = n < 0
    s = str(abs(int(round(n))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + s


def ind_dec(x, dp=2) -> str:
    x = round(float(x), dp)
    whole = int(abs(x))
    frac = f"{abs(x) - whole:.{dp}f}"[1:]
    if frac == "." + "0" * dp and abs(x) - whole > 0.5:   # rounding edge
        whole += 1
    return ("-" if x < 0 else "") + ind_int(whole) + frac


def money(rupees: float) -> str:
    r = float(rupees)
    if abs(r) >= 1e7:
        return f"₹{ind_dec(r / 1e7)} crore"
    if abs(r) >= 1e5:
        return f"₹{ind_dec(r / 1e5)} lakh"
    return f"₹{ind_int(r)}"


def fmt_val(v, unit) -> str:
    if v is None:
        return "no data"
    if unit == "count":
        return ind_int(v)
    if unit == "rupees":
        return money(v)
    if unit == "lakh":
        return money(float(v) * 1e5)
    if unit == "pct":
        return f"{float(v):.2f}%"
    if unit == "rs":
        return f"₹{ind_dec(v)}"
    if unit == "dec":
        return f"{float(v):.2f}"
    return str(v)


KEEP_UPPER = {"LIFCOM", "SEED", "PRIME"}


def pretty(label) -> str:
    if label is None:
        return "(none)"
    if isinstance(label, (int, float)):
        return str(label)
    s = str(label)
    if s.isupper() and s not in KEEP_UPPER:
        s = s.title()
    return s


def join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def row_text(r, unit) -> str:
    return f"{pretty(r[0])} {fmt_val(r[-1], unit)}"


def rows_filter(rows, unit, spec) -> str:
    if not rows:
        return "no rows"
    if spec in ("", "list"):
        return join([row_text(r, unit) for r in rows])
    if spec.startswith("top"):
        n = int(spec[3:])
        return join([row_text(r, unit) for r in rows[:n]])
    if spec.startswith("lead"):
        n = int(spec[4:])
        head = f"{pretty(rows[0][0])} leads with {fmt_val(rows[0][-1], unit)}"
        rest = rows[1:n]
        return head + (("; next " + join([row_text(r, unit) for r in rest])) if rest else "")
    if spec == "rest":
        return join([row_text(r, unit) for r in rows[1:]])
    if spec == "first":
        return pretty(rows[0][0])
    if spec == "firstv":
        return fmt_val(rows[0][-1], unit)
    if spec == "yrs":
        return join([pretty(r[0]) for r in rows])
    if spec == "yfirst":
        return pretty(rows[0][0])
    if spec == "ylast":
        return pretty(rows[-1][0])
    if spec[0] == "l" and spec[1:].isdigit():
        i = int(spec[1:]) - 1
        return pretty(rows[i][0]) if i < len(rows) else "—"
    if spec[0] == "v" and spec[1:].isdigit():
        i = int(spec[1:]) - 1
        return fmt_val(rows[i][-1], unit) if i < len(rows) else "—"
    raise ValueError(f"unknown rows filter {spec!r}")


class Say(string.Formatter):
    def __init__(self, facts: dict):
        super().__init__()
        self.facts = facts

    def get_value(self, key, args, kwargs):
        return self.facts[key]

    def format_field(self, fact, spec):
        alt = 0
        if spec[:1] == "a" and spec[1:2].isdigit():
            alt = int(spec[1]) - 1
            spec = spec[3:] if spec[2:3] == "." else spec[2:]
        if fact["kind"] in ("va", "ra"):
            fact = fact["alts"][alt]
        if fact["kind"] == "v":
            return fmt_val(fact.get("value"), fact["unit"])
        return rows_filter(fact.get("value") or [], fact["unit"], spec)


# ═════════════════════════════ truth (read-only SQL) ═════════════════════════════

def _conv(v):
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v) if v != v.to_integral_value() else int(v)
    return v


async def run_sql(sql: str):
    from app import db
    for attempt in range(3):
        try:
            return await db.fetch_rows_readonly(sql)
        except Exception:  # noqa: BLE001 — the DB times out now and then (CLAUDE.md §9): retry
            if attempt == 2:
                raise
            await asyncio.sleep(2)


async def fill(fact: dict):
    if fact["kind"] in ("va", "ra"):
        for a in fact["alts"]:
            await fill(a)
        return
    rows = await run_sql(fact["sql"])
    if fact["kind"] == "v":
        fact["value"] = _conv(list(rows[0].values())[0]) if rows else None
    else:
        fact["value"] = [[_conv(x) for x in r.values()] for r in rows]


def _vals(fact) -> list[float]:
    """Every number a fact holds (for the cross-check)."""
    if fact["kind"] in ("va", "ra"):
        return [x for a in fact["alts"] for x in _vals(a)]
    if fact["kind"] == "v":
        return [float(fact["value"])] if fact.get("value") is not None else []
    return [float(r[-1]) for r in fact.get("value") or [] if r[-1] is not None]


def _rowsets(fact) -> list[list]:
    if fact["kind"] == "ra":
        return [a.get("value") or [] for a in fact["alts"]]
    if fact["kind"] == "r":
        return [fact.get("value") or []]
    return []


def _norm(s) -> str:
    return " ".join(str(s).upper().replace("-", " ").split())


def _close(a, b) -> bool:
    return abs(float(a) - float(b)) <= max(0.006, abs(float(b)) * 1e-9)


async def gold_check(q: dict, gold_cases: dict) -> list[str]:
    """Every figure / row the gold bank expects for the same question must be one of this question's own
    figures. Returns the differences (empty = agreed)."""
    import run_gold
    case = gold_cases.get(q["gold"])
    if not case:
        return [f"gold case {q['gold']} not found"]
    out = []
    for i, turn in enumerate(q["turns"]):
        if i >= len(case["turns"]):
            break
        gt = copy.deepcopy(case["turns"][i])
        if gt["q"].strip() != turn["q"].strip():
            out.append(f"t{i + 1}: wording differs from the gold bank ({gt['q']!r})")
            continue
        await run_gold.live_truth(gt)
        mine = [x for f in turn["facts"] for x in _vals(f)]
        my_rows = [rs for f in turn["facts"] for rs in _rowsets(f)]
        for f in gt.get("figures") or []:
            alts = f["any"] if "any" in f else [f]
            lives = [a.get("live") for a in alts if a.get("live") is not None]
            if not any(_close(m, lv) for lv in lives for m in mine):
                out.append(f"t{i + 1}: gold figure {lives} ({alts[0].get('label') or alts[0]['unit']}) not among mine "
                           f"{[round(m, 2) for m in mine][:8]}")
        for r in gt.get("rows") or []:
            specs = r["any"] if "any" in r else [r]
            ok = False
            for sp in specs:
                live = sp.get("live") or []
                take = len(live) if sp.get("take", "all") == "all" else int(sp["take"])
                want = [(_norm(x[0]), x[-1]) for x in live[:take]]
                for rs in my_rows:
                    have = {_norm(x[0]): x[-1] for x in rs}
                    if all(lab in have and have[lab] is not None and _close(have[lab], v) for lab, v in want):
                        ok = True
                        break
                if ok:
                    break
            if not ok:
                sp = specs[0]
                out.append(f"t{i + 1}: gold rows ({sp['sql'][:90]}…) first rows {(sp.get('live') or [])[:3]} "
                           f"not matched by mine")
    return out


async def compute_truth() -> dict:
    with open(GOLD, encoding="utf-8") as fh:
        gold_cases = {c["id"]: c for c in yaml.safe_load(fh)["cases"]}
    gold_ok = {}
    if os.path.exists(GOLD_RUN):
        with open(GOLD_RUN, encoding="utf-8") as fh:
            gold_ok = {r["id"]: r["ok"] for r in json.load(fh)["results"]}
    for q in BANK:
        for t in q["turns"]:
            for f in t["facts"]:
                await fill(f)
            t["answer"] = Say({f["name"]: f for f in t["facts"]}).format(t["say"])
        q["gold_diffs"] = await gold_check(q, gold_cases) if q["gold"] else []
        q["gold_passed"] = gold_ok.get(q["gold"]) if q["gold"] else None
        flag = "" if not q["gold_diffs"] else "  <-- " + " | ".join(q["gold_diffs"])
        print(f"{q['id']:<5} {q['turns'][0]['answer'][:110]}{flag}", flush=True)
    return {"years": await scheme_years(), "stats": bank_stats(), "computed": time.strftime("%Y-%m-%d %H:%M")}


async def scheme_years() -> list[dict]:
    views = [(MG, EMP, "employment and expenditure"), (PM, PMV, "year a house was sanctioned"),
             (FP, FPV, "payment year"), (FL, FLV, "remittance year"), (CE, CEV, None),
             (CL, CLV, "disbursement year"), (CS, CSV, "payment year"), (HS, HSV, "application year")]
    out = []
    for name, view, what in views:
        if what is None:
            n = await run_sql(f"SELECT COUNT(DISTINCT request_id) AS n FROM {view}")
            out.append({"scheme": name, "years": [], "no_year": int(n[0]["n"]), "what": "applications carry no year"})
            continue
        rows = await run_sql(f"SELECT financial_year_short AS fy, COUNT(*) AS n FROM {view} "
                             f"GROUP BY 1 ORDER BY 1 NULLS LAST")
        out.append({"scheme": name, "years": [r["fy"] for r in rows if r["fy"]],
                    "no_year": sum(int(r["n"]) for r in rows if not r["fy"]), "what": what})
    return out


def bank_stats() -> dict:
    out = {}
    for fn, key in ((GOLD_RUN, "model_on"), (NOMODEL_RUN, "no_model")):
        if os.path.exists(fn):
            with open(fn, encoding="utf-8") as fh:
                rs = json.load(fh)["results"]
            out[key] = {"passed": sum(1 for r in rs if r["ok"]), "cases": len(rs),
                        "turns_ok": sum(1 for r in rs for t in r["turns"] if t.get("ok")),
                        "turns": sum(len(r["turns"]) for r in rs), "file": os.path.basename(fn)}
    return out


# ═════════════════════════════ the app (model ON, in-process) ═════════════════════════════

def gold_turn(t: dict) -> dict:
    """This question's turn in tests/accuracy/gold_bank.yaml form, for run_gold.run_case / judge_turn."""
    def fig(f):
        if f["kind"] == "va":
            alts = [fig(a) for a in f["alts"] if a["ck"]]
            return {"any": alts, "why": f.get("why", "")} if len(alts) > 1 else alts[0]
        g = {"sql": f["sql"], "unit": "dec" if f["unit"] == "rs" else f["unit"], "value": f.get("value")}
        if f.get("label"):
            g["label"] = f["label"]
        if f.get("word"):
            g["word"] = f["word"]
        return g

    def rows(f):
        if f["kind"] == "ra":
            alts = [rows(a) for a in f["alts"] if a["ck"]]
            return {"any": alts, "why": f.get("why", "")} if len(alts) > 1 else alts[0]
        r = {"sql": f["sql"], "unit": "dec" if f["unit"] == "rs" else f["unit"], "take": f["ck"],
             "value": f.get("value")}
        if f.get("word"):
            r["word"] = f["word"]
        return r

    out = {"q": t["q"], "pause": t["pause"]}
    figs = [fig(f) for f in t["facts"] if f["kind"] in ("v", "va") and f["ck"]]
    rws = [rows(f) for f in t["facts"] if f["kind"] in ("r", "ra") and f["ck"]]
    if figs:
        out["figures"] = figs
    if rws:
        out["rows"] = rws
    for k in ("route", "schemes"):
        if t.get(k):
            out[k] = t[k]
    for k in ("any_of", "lacks", "has"):
        if t.get(k):
            out[k] = t[k]
    return out


async def check_app(only: set | None, concurrency: int) -> dict:
    import run_gold
    from conversation_harness.drivers import InProcessDriver
    qs = [q for q in BANK if not only or q["id"] in only or q["sec"] in only]
    cases = [{"id": q["id"], "cat": q.get("cat") or {"C": "cm_elevate_legacy"}.get(q["sec"], q["sec"]),
              "shape": "qbank", "src": "tools/make_question_bank.py", "turns": [gold_turn(t) for t in q["turns"]]}
             for q in qs]
    print(f"app check: {len(cases)} questions, {sum(len(c['turns']) for c in cases)} turns, model ON", flush=True)
    run_gold.VIEW_ONLY.update(run_gold.view_only_map([t["q"] for c in cases for t in c["turns"]]))
    t0 = time.perf_counter()
    async with InProcessDriver() as d:
        scope = await run_gold.superadmin_scope()
        sem = asyncio.Semaphore(max(1, min(concurrency, 4)))
        results = await asyncio.gather(*(run_gold.run_case(c, d, scope, sem) for c in cases))
    for r in results:
        for t in r["turns"]:
            t.pop("data_full", None)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    path = os.path.join(ROOT, "tests", "accuracy", "results", f"{stamp}_qbank.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"label": "qbank", "when": stamp, "seconds": round(time.perf_counter() - t0),
                   "results": results}, fh, indent=1, ensure_ascii=False, default=str)
    print(f"app check done in {round(time.perf_counter() - t0)} s: "
          f"{sum(1 for r in results if r['ok'])}/{len(results)} matched; written {os.path.relpath(path, ROOT)}")
    return {"when": stamp, "file": os.path.relpath(path, ROOT).replace("\\", "/"),
            "results": {r["id"]: {"ok": r["ok"], "turns": [
                {"ok": t.get("ok"), "fails": t.get("fails"), "answer": t.get("answer"), "route": t.get("route"),
                 "dataset_pick": t.get("dataset_pick"), "local_view": t.get("local_view")} for t in r["turns"]]}
                for r in results}}


# ═════════════════════════════ save / load ═════════════════════════════

def save(meta: dict, app: dict | None):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    old_app = None
    if app is None and os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as fh:
            old_app = json.load(fh).get("app")
    with open(DATA, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "bank": BANK, "app": app if app is not None else old_app}, fh, indent=1,
                  ensure_ascii=False, default=str)


def load() -> tuple[dict, list, dict | None]:
    with open(DATA, encoding="utf-8") as fh:
        d = json.load(fh)
    return d["meta"], d["bank"], d.get("app")


# ═════════════════════════════ rendering ═════════════════════════════

def sql_lines(t) -> list[tuple[str, str]]:
    out = []
    for f in t["facts"]:
        for a in (f["alts"] if f["kind"] in ("va", "ra") else [f]):
            tag = f["name"] + (f" ({a['name']})" if f["kind"] in ("va", "ra") else "")
            out.append((tag, a["sql"]))
    return out


def status(q, app) -> tuple[str, str]:
    """(app mark, test-bank mark) for one question."""
    a = (app or {}).get("results", {}).get(q["id"])
    app_mark = "not run" if a is None else ("✓" if a["ok"] else "✗")
    if q["gold"]:
        bank = "test bank ✓" if q.get("gold_passed") else ("test bank ✗" if q.get("gold_passed") is False else "test bank")
    else:
        bank = "new"
    return app_mark, bank


def years_text(y) -> str:
    if not y["years"]:
        return f"no financial year ({y['what']}; {ind_int(y['no_year'])} applications)"
    s = join(y["years"]) if len(y["years"]) <= 3 else f"{y['years'][0]} to {y['years'][-1]}"
    gaps = ""
    if y["scheme"] == FL:
        gaps = " (no 2023-24)"
    if y["scheme"] == FP:
        gaps = " (only these two years)"
    extra = f"; {ind_int(y['no_year'])} records have no year" if y["no_year"] else ""
    return f"{s}{gaps}, by {y['what']}{extra}"


def summarise(bank, app):
    per = []
    tot = {"q": 0, "turns": 0, "gold": 0, "new": 0, "ok": 0, "bad": 0, "run": 0, "diff": 0}
    for sid, title, _ in SECTIONS:
        qs = [q for q in bank if q["sec"] == sid]
        res = [(app or {}).get("results", {}).get(q["id"]) for q in qs]
        row = {"sid": sid, "title": title, "q": len(qs), "turns": sum(len(q["turns"]) for q in qs),
               "gold": sum(1 for q in qs if q["gold"]), "new": sum(1 for q in qs if not q["gold"]),
               "run": sum(1 for r in res if r is not None), "ok": sum(1 for r in res if r and r["ok"]),
               "bad": sum(1 for r in res if r and not r["ok"]), "diff": sum(1 for q in qs if q.get("gold_diffs"))}
        per.append(row)
        for k in tot:
            tot[k] += row[k]
    return per, tot


def mismatches(bank, app) -> list[dict]:
    out = []
    for q in bank:
        a = (app or {}).get("results", {}).get(q["id"])
        if not a or a["ok"]:
            continue
        for i, (t, at) in enumerate(zip(q["turns"], a["turns"])):
            if at.get("ok"):
                continue
            out.append({"id": q["id"], "turn": i + 1, "q": t["q"], "db": t["answer"], "app": (at.get("answer") or "")[:700],
                        "why": "; ".join(at.get("fails") or [])[:500], "prior": [x["q"] for x in q["turns"][:i]]})
        if len(a["turns"]) < len(q["turns"]):
            out.append({"id": q["id"], "turn": len(a["turns"]) + 1, "q": q["turns"][len(a["turns"])]["q"],
                        "db": q["turns"][len(a["turns"])]["answer"], "app": "(not reached)", "why": "an earlier turn failed",
                        "prior": []})
    return out


INTRO_WHAT = [
    "Figures from eight schemes: MGNREGA, PMAY-G, Focus Plus, Focus Legacy, CM Elevate (applications), CM Elevate "
    "Legacy (disbursements), CMSS and Homestay.",
    "For the whole state, a district, a block, a village or an assembly constituency; for one financial year, a few, "
    "or all of them.",
    "Totals, breakdowns (by district, block, year, scheme, status, gender…), rankings (top or bottom N), trends, "
    "comparisons of places, years or schemes, shares and averages.",
    "Several schemes at once: the headline of every scheme, money by scheme, one place across every scheme.",
    "Follow-ups in the same chat: “now by block”, “only Ri Bhoi”, “top 3”, “which is the lowest”, “what about 2023-24”, "
    "“and the households instead”.",
    "How a scheme works (eligibility, rules) is answered from the scheme documents; this guide covers the figures.",
]
TIPS = [
    "Name the scheme, the place and the year: “MGNREGA person-days in Ri Bhoi in 2023-24”. Without a year the app adds "
    "up every year it holds and says so.",
    "Short names work: WGH, EKH, “nrega”, “PMAY gramin”, “Focus+”, “23-24”, “FY24”. Casual and spoken wording works too.",
    "Follow-ups keep what you asked before: after a district breakdown, “now by block”, “only Ri Bhoi”, “top 3”, "
    "“and in 2024-25?”, “what about the households instead”.",
    "For CM Elevate, say “applications” or “Legacy” (the payments). A new chat may ask which one you mean: tap it.",
    "MGNREGA households and persons are counted once per financial year, so a total over several years counts a "
    "household again in each year it worked. Ask for one year when you want a head count.",
    "PMAY-G “beneficiaries” are the houses sanctioned. Focus Legacy “beneficiaries” are producer-group members.",
    "Money is shown in ₹ crore or ₹ lakh; MGNREGA money is stored in lakh rupees.",
]


def intro_accuracy(meta, tot) -> list[str]:
    s = meta["stats"]
    mo, nm = s.get("model_on", {}), s.get("no_model", {})
    out = []
    if mo:
        out.append(f"The full test bank of {mo['cases']} checked questions ({mo['turns']} turns, every answer compared "
                   f"with an independent database query) passed {mo['passed']} of {mo['cases']} on 15 Nov 2026, with the "
                   f"AI model on.")
    if nm:
        out.append(f"With the AI model switched off entirely, the app still answered {nm['passed']} of {nm['cases']} "
                   f"correctly ({round(100 * nm['passed'] / nm['cases'])}%): most questions are answered by fixed, "
                   f"verified queries, and the model is needed mainly for unusual wordings.")
    if tot["run"]:
        out.append(f"This guide was then run through the app again (model on): it gave the database figures for "
                   f"{tot['ok']} of {tot['run']} questions here. The ones it missed are listed at the end.")
    return out


def md(meta, bank, app) -> str:
    per, tot = summarise(bank, app)
    L = []
    L.append("# Megh One AI: verified question bank")
    L.append("")
    L.append(f"*Built {meta['computed']} from megh_db (read-only). {tot['q']} questions, {tot['turns']} turns. "
             f"Regenerate with `tools/make_question_bank.py`.*")
    L.append("")
    L.append("Use this as a guide when you ask the app questions by voice or by typing. Every answer below was read "
             "straight from the database with its own query (listed at the end), not taken from the app.")
    L.append("")
    L.append("## How good is the app today")
    L.append("")
    for p in intro_accuracy(meta, tot):
        L.append(f"- {p}")
    L.append("")
    L.append("## What you can ask")
    L.append("")
    for p in INTRO_WHAT:
        L.append(f"- {p}")
    L.append("")
    L.append("## Which years each scheme covers")
    L.append("")
    for y in meta["years"]:
        L.append(f"- **{y['scheme']}**: {years_text(y)}.")
    L.append("")
    L.append("## Tips for asking")
    L.append("")
    for p in TIPS:
        L.append(f"- {p}")
    L.append("")
    L.append("## What is in this guide")
    L.append("")
    L.append("| Section | Questions | From the test bank | New | App matched the DB |")
    L.append("|---|---:|---:|---:|---:|")
    for r in per:
        m = f"{r['ok']} of {r['run']}" if r["run"] else "not run"
        L.append(f"| {r['title']} | {r['q']} | {r['gold']} | {r['new']} | {m} |")
    m = f"{tot['ok']} of {tot['run']}" if tot["run"] else "not run"
    L.append(f"| **All** | **{tot['q']}** | **{tot['gold']}** | **{tot['new']}** | **{m}** |")
    L.append("")
    L.append("Marks under each answer: **test bank ✓** = the same words are in the 401-question test bank and passed "
             "there; **new** = added for this guide; **app ✓ / ✗** = what the app answered when this guide was checked "
             "(facts only; wording is not judged).")
    L.append("")
    for sid, title, blurb in SECTIONS:
        qs = [q for q in bank if q["sec"] == sid]
        if not qs:
            continue
        L.append(f"## {title}")
        L.append("")
        L.append(f"*{blurb}*")
        L.append("")
        for q in qs:
            app_mark, bank_mark = status(q, app)
            if len(q["turns"]) == 1:
                t = q["turns"][0]
                L.append(f"**{q['id']}. {t['q']}**  ")
                L.append(f"{t['answer']}  ")
            else:
                L.append(f"**{q['id']}. A conversation**  ")
                for i, t in enumerate(q["turns"]):
                    L.append(f"{i + 1}. **“{t['q']}”** → {t['answer']}  ")
            note = f" · {q['note']}" if q.get("note") else ""
            L.append(f"<sub>{bank_mark} · app {app_mark}{note}</sub>")
            L.append("")
    L.extend(md_findings(bank, app))
    L.append("## Appendix: the database query behind every answer")
    L.append("")
    L.append("Each query is read-only and runs against `megh_db`, schema `curated`. MGNREGA money columns are in lakh "
             "rupees; every other money column is in rupees.")
    L.append("")
    for q in bank:
        L.append(f"**{q['id']}**  ")
        for i, t in enumerate(q["turns"]):
            for tag, sql in sql_lines(t):
                pre = f"turn {i + 1}, " if len(q["turns"]) > 1 else ""
                L.append(f"- {pre}`{tag}`: `{sql}`")
        L.append("")
    return "\n".join(L) + "\n"


RESOLVED = [
    "PMAY-G houses (P1): 1,71,107 sanctioned = 1,29,941 completed + 41,041 under construction + 125 not started or "
    "with no status. The test bank also checks the 125; it is now shown.",
    "CM Elevate Legacy “sanctioned applicants”: 3 records (Ri Bhoi, East Garo Hills, East Khasi Hills) were "
    "de-sanctioned, with no sanctioned amount and nothing paid. Counting records with a sanctioned amount gives 2,820 "
    "(East Khasi Hills 240), as the test bank and the app's all-scheme comparison do; the data team's catalogue measure "
    "cm_elevate_disb_beneficiaries (COUNT(DISTINCT application_number), named “sanctioned applicants”) gives "
    "2,823 (East Khasi Hills 241). This guide uses 2,820. Worth a word with the data team.",
    "Focus Plus by district: the source file's district names and the LGD map differ by about 20 beneficiaries for "
    "West Garo Hills and South West Garo Hills (KI-065). Both readings are accepted for those two districts.",
    "MGNREGA households over several years: the app adds the yearly figures (14,94,437 statewide), the same as its "
    "welcome card; a household that worked in several years is counted once per year (an open owner decision, "
    "CLAUDE.md §0a''').",
    "CM Elevate applications: 7,375 valid by default; 8,938 counting every application. The app's “compare all "
    "eight schemes” answer uses 8,938 while a direct question uses 7,375; both are correct readings, labelled.",
]


def md_findings(bank, app) -> list[str]:
    L = ["## Differences found", "",
         "**Checked and explained** (this guide's queries against the test bank and the catalogue):", ""]
    L += [f"- {r}" for r in RESOLVED] + [""]
    diffs = [q for q in bank if q.get("gold_diffs")]
    if diffs:
        L.append("**This guide's query against the test bank's query** (both independent of the app):")
        L.append("")
        for q in diffs:
            for d in q["gold_diffs"]:
                L.append(f"- {q['id']} ({q['gold']}): {d}")
        L.append("")
    else:
        L.append("- Every figure the 401-question test bank expects for the same questions is also this guide's "
                 "figure: the two independent sets of queries agree.")
        L.append("")
    mm = mismatches(bank, app)
    if app is None:
        L.append("- The app has not been run against this guide yet.")
    elif not mm:
        L.append("- The app gave the database figures for every question in this guide.")
    else:
        L.append(f"**Where the app's answer did not carry the database figures** (checked {app['when']}, model on):")
        L.append("")
        for m in mm:
            prior = (" (after: " + " → ".join(f"“{p}”" for p in m["prior"]) + ")") if m["prior"] else ""
            L.append(f"- **{m['id']} turn {m['turn']}: “{m['q']}”**{prior}  ")
            L.append(f"  DB: {m['db']}  ")
            L.append(f"  App: {m['app'].replace(chr(10), ' / ')}  ")
            L.append(f"  <sub>{m['why']}</sub>")
    L.append("")
    return L


CSS = """
:root{--ink:#16202a;--muted:#6b7785;--line:#e3e8ee;--accent:#0f6e5a;--soft:#f4f7f9;--bad:#b3261e}
*{box-sizing:border-box}
body{font-family:"Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;color:var(--ink);background:#fff;
 margin:0;padding:0 16px;line-height:1.45;font-size:10.5pt}
main{max-width:860px;margin:0 auto}
h1{font-size:22pt;margin:18px 0 4px;color:var(--accent)}
h2{font-size:14pt;margin:22px 0 6px;padding-bottom:4px;border-bottom:2px solid var(--accent);break-after:avoid}
h2.sec{page-break-before:always}
.sub{color:var(--muted);font-size:9.5pt;margin:0 0 10px}
ul{margin:4px 0 8px 18px;padding:0}
li{margin:2px 0}
table{border-collapse:collapse;width:100%;margin:6px 0 10px;font-size:9.5pt}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}
td.n,th.n{text-align:right}
.tw{overflow-x:auto;max-width:100%}
main{overflow-wrap:anywhere}
.q{border-left:3px solid var(--line);padding:5px 0 5px 10px;margin:7px 0;break-inside:avoid}
.q .t{font-weight:600}
.q .a{margin-top:2px}
.q .m{color:var(--muted);font-size:8.5pt;margin-top:2px}
.q .m .x{color:var(--bad);font-weight:600}
.q .m .ok{color:var(--accent);font-weight:600}
ol.turns{margin:2px 0 0 18px;padding:0}
ol.turns li{margin:3px 0}
.blurb{color:var(--muted);font-style:italic;margin:0 0 6px}
.mm{background:var(--soft);border-radius:6px;padding:6px 9px;margin:6px 0;break-inside:avoid;font-size:9.5pt}
.mm .w{color:var(--muted);font-size:8.5pt}
.sql{font-family:Consolas,"Cascadia Mono",monospace;font-size:7.5pt;color:#34414e;margin:1px 0 1px 10px;
 word-break:break-word}
.sqlq{break-inside:avoid;margin:6px 0}
@media (max-width:600px){body{font-size:11pt}h1{font-size:18pt}table{font-size:9pt}}
@page{size:A4;margin:14mm 12mm}
"""


def page_html(meta, bank, app) -> str:
    e = html.escape
    per, tot = summarise(bank, app)
    H = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
         f"content='width=device-width,initial-scale=1'><title>Megh One AI question bank</title><style>{CSS}</style>"
         f"</head><body><main>"]
    H.append("<h1>Megh One AI: verified question bank</h1>")
    H.append(f"<p class='sub'>Built {e(meta['computed'])} from megh_db (read-only) · {tot['q']} questions, "
             f"{tot['turns']} turns</p>")
    H.append("<p>Use this as a guide when you ask the app questions by voice or by typing. Every answer below was read "
             "straight from the database with its own query (listed at the end), not taken from the app.</p>")
    H.append("<h2>How good is the app today</h2><ul>" + "".join(f"<li>{e(p)}</li>" for p in intro_accuracy(meta, tot))
             + "</ul>")
    H.append("<h2>What you can ask</h2><ul>" + "".join(f"<li>{e(p)}</li>" for p in INTRO_WHAT) + "</ul>")
    H.append("<h2>Which years each scheme covers</h2><ul>" + "".join(
        f"<li><b>{e(y['scheme'])}</b>: {e(years_text(y))}.</li>" for y in meta["years"]) + "</ul>")
    H.append("<h2>Tips for asking</h2><ul>" + "".join(f"<li>{e(p)}</li>" for p in TIPS) + "</ul>")
    H.append("<h2>What is in this guide</h2><div class='tw'><table><tr><th>Section</th><th class='n'>Questions</th>"
             "<th class='n'>From the test bank</th><th class='n'>New</th><th class='n'>App matched the DB</th></tr>")
    for r in per:
        m = f"{r['ok']} of {r['run']}" if r["run"] else "not run"
        H.append(f"<tr><td>{e(r['title'])}</td><td class='n'>{r['q']}</td><td class='n'>{r['gold']}</td>"
                 f"<td class='n'>{r['new']}</td><td class='n'>{m}</td></tr>")
    m = f"{tot['ok']} of {tot['run']}" if tot["run"] else "not run"
    H.append(f"<tr><th>All</th><th class='n'>{tot['q']}</th><th class='n'>{tot['gold']}</th><th class='n'>{tot['new']}</th>"
             f"<th class='n'>{m}</th></tr></table></div>")
    H.append("<p class='sub'>Marks under each answer: <b>test bank ✓</b> = the same words are in the 401-question test "
             "bank and passed there; <b>new</b> = added for this guide; <b>app ✓ / ✗</b> = what the app answered when "
             "this guide was checked (facts only; wording is not judged).</p>")
    for sid, title, blurb in SECTIONS:
        qs = [q for q in bank if q["sec"] == sid]
        H.append(f"<h2 class='sec'>{e(title)}</h2><p class='blurb'>{e(blurb)}</p>")
        for q in qs:
            app_mark, bank_mark = status(q, app)
            cls = "ok" if app_mark == "✓" else ("x" if app_mark == "✗" else "")
            note = f" · {e(q['note'])}" if q.get("note") else ""
            if len(q["turns"]) == 1:
                t = q["turns"][0]
                body = f"<div class='t'>{q['id']}. {e(t['q'])}</div><div class='a'>{e(t['answer'])}</div>"
            else:
                body = (f"<div class='t'>{q['id']}. A conversation</div><ol class='turns'>" + "".join(
                    f"<li><b>“{e(t['q'])}”</b> → {e(t['answer'])}</li>" for t in q["turns"]) + "</ol>")
            H.append(f"<div class='q'>{body}<div class='m'>{e(bank_mark)} · app <span class='{cls}'>{app_mark}</span>"
                     f"{note}</div></div>")
    H.append("<h2 class='sec'>Differences found</h2><p><b>Checked and explained</b> (this guide's queries against "
             "the test bank and the catalogue):</p><ul>" + "".join(f"<li>{e(r)}</li>" for r in RESOLVED) + "</ul>")
    diffs = [q for q in bank if q.get("gold_diffs")]
    if diffs:
        H.append("<p><b>This guide's query against the test bank's query</b> (both independent of the app):</p><ul>"
                 + "".join(f"<li>{q['id']} ({e(q['gold'])}): {e(d)}</li>" for q in diffs for d in q["gold_diffs"])
                 + "</ul>")
    else:
        H.append("<ul><li>Every figure the 401-question test bank expects for the same questions is also this guide's "
                 "figure: the two independent sets of queries agree.</li></ul>")
    mm = mismatches(bank, app)
    if app is None:
        H.append("<p>The app has not been run against this guide yet.</p>")
    elif not mm:
        H.append("<p>The app gave the database figures for every question in this guide.</p>")
    else:
        H.append(f"<p><b>Where the app's answer did not carry the database figures</b> (checked {e(app['when'])}, "
                 f"model on):</p>")
        for x in mm:
            prior = (" <span class='w'>(after: " + " → ".join(f"“{e(p)}”" for p in x["prior"]) + ")</span>") \
                if x["prior"] else ""
            H.append(f"<div class='mm'><b>{x['id']} turn {x['turn']}: “{e(x['q'])}”</b>{prior}<br>DB: {e(x['db'])}"
                     f"<br>App: {e(x['app'])}<br><span class='w'>{e(x['why'])}</span></div>")
    H.append("<h2 class='sec'>Appendix: the database query behind every answer</h2><p class='sub'>Read-only, against "
             "megh_db schema curated. MGNREGA money columns are in lakh rupees; every other money column is in rupees."
             "</p>")
    for q in bank:
        lines = []
        for i, t in enumerate(q["turns"]):
            for tag, sql in sql_lines(t):
                pre = f"turn {i + 1}, " if len(q["turns"]) > 1 else ""
                lines.append(f"<div class='sql'>{pre}{e(tag)}: {e(sql)}</div>")
        H.append(f"<div class='sqlq'><b>{q['id']}</b>{''.join(lines)}</div>")
    H.append("</main></body></html>")
    return "".join(H)


def render(meta, bank, app):
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(md(meta, bank, app))
    tmp = tempfile.mkdtemp(prefix="qbank_")
    src, pdf = os.path.join(tmp, "qbank.html"), os.path.join(tmp, "qbank.pdf")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(page_html(meta, bank, app))
    if os.path.exists(EDGE):
        subprocess.run([EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
                        f"--user-data-dir={os.path.join(tmp, 'edge')}",
                        f"--print-to-pdf={pdf}", "file:///" + src.replace("\\", "/")],
                       capture_output=True, timeout=180)
    if os.path.exists(pdf):
        shutil.copyfile(pdf, OUT_PDF)
        print(f"written {os.path.relpath(OUT_MD, ROOT)} and {os.path.relpath(OUT_PDF, ROOT)}")
    else:
        print(f"written {os.path.relpath(OUT_MD, ROOT)}; PDF NOT written (Edge headless failed)")
    shutil.rmtree(tmp, ignore_errors=True)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", action="store_true", help="also run every question through the app (model ON)")
    ap.add_argument("--only", help="comma list of question ids or section letters for --app")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--render", action="store_true", help="only render again from the saved results")
    args = ap.parse_args()
    if args.render:
        meta, bank, app = load()
        render(meta, bank, app)
        return 0
    meta = await compute_truth()
    app = None
    if args.app:
        only = {x.strip() for x in args.only.split(",")} if args.only else None
        app = await check_app(only, args.concurrency)
        if only and os.path.exists(DATA):          # a partial run updates the saved one
            with open(DATA, encoding="utf-8") as fh:
                prev = json.load(fh).get("app") or {"results": {}}
            prev["results"].update(app["results"])
            prev.update({k: app[k] for k in ("when", "file")})
            app = prev
    save(meta, app)
    meta, bank, app = load()
    render(meta, bank, app)
    diffs = sum(1 for q in bank if q.get("gold_diffs"))
    print(f"{len(bank)} questions; {diffs} with a difference against the gold bank")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
