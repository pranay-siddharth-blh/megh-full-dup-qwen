"""Writes the CM Elevate Legacy sheet's 9th Result / 9th Remarks / After Fix / After Fix Remarks
(columns G..J; the sheet's last header is F) from the final-run and all-villages result files.
Usage: write_fl.py <final.json> [<village_all.json>]"""
import copy
import json
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

P = r"C:/Users/Admin/OneDrive/Desktop/MCP/meghoneai/meghalaya/reference_documents/Test Case Results - 30th Sep 26.xlsx"
FINAL = json.load(open(sys.argv[1], encoding="utf-8"))
VILL = json.load(open(sys.argv[2], encoding="utf-8")) if len(sys.argv) > 2 else None

BASE = ("Tested 2026-10-12 through the LangGraph pipeline with the live models and megh_db; every expected figure "
        "computed from curated.v_cm_elevate_disbursement only (applications = COUNT(*), sanctioned = "
        "COUNT(sanctioned_amount), disbursed = stored subsidy / loan / total, FY = financial_year_short, constituency "
        "via dim_geography.ac_name). The sheet says 'CM-ELEVATE'; this sheet is the CM Elevate Legacy (sanction and "
        "disbursement) dataset. ")
WRONG = ("Fail. A bare 'CM-ELEVATE' count was answered from the OTHER dataset (CM Elevate applications, 8,627 rows) "
         "instead of CM Elevate Legacy (2,823 sanction records) — the testers' 'neither Legacy nor legacy+api' remark. ")
FAIL9 = {
    "03": "Fail. 'Who are the intended beneficiaries' was answered as a count ('8,600 applicants') instead of from "
          "the scheme documents.",
    "11": WRONG + "Answered 8,627 for 2,823.",
    "12": WRONG + "12 of 13 schemes wrong (e.g. Piggery 3,032 for 1,353).",
    "13": WRONG + "SEED (an applications-only programme) was named top instead of Piggery (1,353).",
    "26": WRONG + "Also not in descending order of applications (testers' remark).",
    "28": WRONG + "Top districts from the wrong dataset (Ri Bhoi 2,606).",
    "29": WRONG + "30 of 59 blocks wrong.",
    "31": WRONG + "28 of 55 constituencies wrong.",
    "33": WRONG + "6 of 12 district block-breakdowns wrong.",
    "34": WRONG + "6 of 12 block village-breakdowns wrong.",
    "36": "Fail (testers' remark). The district summary was ordered by disbursement, not by applications "
          "(descending), and carried an extra all-districts row in the middle of the list order.",
}
DS = ("Fixed (the user's decision 2026-10-12): a bare 'CM-ELEVATE' data question that uses no applications-only word "
      "(applicants, pending, status, sector, on hold, verification, sent back, level, programme…) is read as CM "
      "Elevate Legacy; the rewritten question shows the reading. Questions in the applications dataset's own words "
      "(the CM Elevate sheet) are unchanged. ")
FIXES = {
    "03": "Fixed: 'Who are / who can / who is eligible…' with no count word is answered from the scheme documents.",
    "11": DS + "2,823 applications.",
    "12": DS + "Every scheme's own count (e.g. Piggery 1,353).",
    "13": DS + "Piggery 1,353 first.",
    "26": DS + "Rows ranked by applications, descending (West Garo Hills 493 first).",
    "28": DS + "Top 5 by applications.",
    "29": DS + "Every block; the Tura Municipal Board block name in the rules was corrected to the stored "
          "'TURA MUNICIPAL BOARD'.",
    "31": DS + "Every constituency; a name that is a district HQ alias and a constituency but not one of this "
          "scheme's villages (Khliehriat) asks district or constituency instead of offering villages with no records.",
    "33": DS + "Every district's block breakdown.",
    "34": DS + "Every block's village breakdown.",
    "36": "Fixed: a breakdown whose first measure is applications is ranked by applications, descending (the "
          "roll-up total last).",
}
SCOPE = {"12": "all 13 schemes", "18": "all 13 schemes", "19": "all 13 schemes", "25": "both FYs",
         "26": "all 12 districts", "27": "all 12 districts", "29": "every block (59)", "30": "every block (59)",
         "31": "every assembly constituency (55)", "32": "every assembly constituency (55)",
         "33": "all 12 districts", "34": "the 12 largest blocks", "35": "6 district pairs"}


def tally(d, tc):
    cs = d.get("TC-" + tc, [])
    return sum(1 for c in cs if c["ok"]), len(cs)


wb = openpyxl.load_workbook(P)
ws = wb["CM Elevate Legacy"]
hdr = ws.cell(1, 6)
for col, title in ((7, "9th Result"), (8, "9th Remarks"), (9, "After Fix"), (10, "After Fix Remarks")):
    c = ws.cell(1, col, title)
    c.font = copy.copy(hdr.font); c.fill = copy.copy(hdr.fill)
    c.border = copy.copy(hdr.border); c.alignment = copy.copy(hdr.alignment)
for L, w in (("G", 12), ("H", 95), ("I", 12), ("J", 95)):
    ws.column_dimensions[L].width = w
green, red = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE")
vt = ""
if VILL:
    vs = [c for cs in VILL.values() for c in cs]
    vt = (f" Full hierarchy: EVERY CM Elevate Legacy village was also tested ({sum(c['ok'] for c in vs):,}/{len(vs):,} "
          "villages pass; one question each, alternating applications / total disbursement, name in UPPER / "
          "Title / lower case, shared names answered after the which-village choice).")


def cell(r, col, text, fill=None, ok=None):
    c = ws.cell(r, col, text)
    c.border = copy.copy(ws.cell(r, 6).border)
    if fill is not None:
        c.fill = fill
        c.font = Font(bold=True, color="006100" if ok else "9C0006")
        c.alignment = Alignment(horizontal="center", vertical="top")
    else:
        c.alignment = Alignment(wrap_text=True, vertical="top")


bad = []
for r in range(2, ws.max_row + 1):
    tc = ws.cell(r, 1).value
    if not tc or not str(tc).startswith("TC-"):
        continue
    k = str(tc)[-2:]
    okf, nf = tally(FINAL, k)
    sc = f" Coverage: {SCOPE[k]}." if k in SCOPE else ""
    if k in FAIL9:
        cell(r, 7, "Fail", red, False)
        cell(r, 8, BASE + FAIL9[k])
    else:
        cell(r, 7, "Pass", green, True)
        cell(r, 8, BASE + "Correct against the DB in the first run." + sc)
    passed = nf and okf == nf
    if not passed:
        bad.append((tc, okf, nf))
    fix = FIXES.get(k, "No fix needed for this case (passed in the 9th run).")
    cell(r, 9, "Pass" if passed else "Fail", green if passed else red, passed)
    cell(r, 10, fix + f" Re-tested live 2026-10-12 on the final code: {okf}/{nf} cases pass." + sc + vt)
wb.save(P)
print("written; not all-pass:", bad)
