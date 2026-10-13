"""Writes the Focus + sheet's 9th Result / 9th Remarks / After Fix / After Fix Remarks (columns N..Q)
from the 9th-run and final-run result files. Usage: write_fp.py <final.json> [<village_all.json>]"""
import copy
import json
import os
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

HERE = os.path.dirname(os.path.abspath(__file__))
P = r"C:/Users/Admin/OneDrive/Desktop/MCP/meghoneai/meghalaya/reference_documents/Test Case Results - 30th Sep 26.xlsx"
NINTH = json.load(open(os.path.join(HERE, "fp_results_9th.json"), encoding="utf-8"))
FINAL = json.load(open(sys.argv[1], encoding="utf-8"))
VILL = json.load(open(sys.argv[2], encoding="utf-8")) if len(sys.argv) > 2 else None

BASE = ("Tested 2026-10-10 through the LangGraph pipeline with the live models and megh_db; every expected figure "
        "computed from curated.v_focus_plus (beneficiaries = COUNT(DISTINCT beneficiary_key) over both cohorts; "
        "amount = SUM(amount_disbursed) in rupees; gender / occupation / status / verification exist only on the "
        "12.5K cohort; blocks on block_name_raw). Questions with no year were answered 'All financial years "
        "combined' at the bot's year question. ")
SCOPE = {
    "001": "every district (12), name in UPPER / Title / lower case",
    "002": "statewide list of all districts",
    "003": "every district (12), with and without the scheme name",
    "004": "every block (50; the 4 'Nan' rows with no block or district are not a block)",
    "005": "both FYs (2022-23, 2025-26) in 4 formats each",
    "006": "both batches (93K, 12.5K)",
    "007": "all 4 tranches (Tranch / Tranche / full label)",
    "018": "all 4 tranches",
    "019": "both batches",
    "020": "both FYs in 4 formats",
    "021": "both FYs in 4 formats",
    "022": "both FYs in 4 formats",
    "025": "every district (12)",
    "026": "6 district pairs",
    "027": "6 district pairs",
    "028": "4 tranche pairs",
    "017": "Pending, Approved and Rejected",
}
FAIL9 = {
    "004": "Fail (1 of 50 blocks: SHILLONG-MUNICIPAL BOARD). The mention extractor tagged the block as a district; "
           "it is not a district, so the bot replied that the place is outside Meghalaya.",
    "018": "Fail (4 of 4 tranches). Tranch 1-3 got 'no status data' without stating the 93,286 beneficiaries it "
           "covers; Tranch 4 listed only the 12,527 with a status and left out the 93,286 with none recorded.",
    "019": "Fail (1 of 2: the 93K batch). Answered '373,144 registrations': payment rows (4 per person), "
           "mislabelled; the batch is 93,286 beneficiaries, none with a status recorded.",
}
FIXES = {
    "004": "Fixed: a place the extractor tags as a district is checked against the scheme's own block list before "
           "it is called outside Meghalaya (Shillong-Municipal Board = Rs 85,000).",
    "018": "Fixed: a status breakdown for a named tranche is a fixed query: beneficiaries by status, with "
           "'status not recorded' counted (Tranch 1 = 93,286 not recorded; Tranch 4 = 105,813: not recorded 93,286, "
           "Pending 11,812, Approved 714, Rejected 1).",
    "019": "Fixed: the same fixed query for a named batch, counting beneficiaries (93K = 93,286, none with a "
           "status; 12.5K = Pending 11,812, Approved 714, Rejected 1).",
}


def tally(d, tc):
    cs = d.get("FOCUS-" + tc, [])
    return sum(1 for c in cs if c["ok"]), len(cs)


wb = openpyxl.load_workbook(P)
ws = wb["Focus +"]
hdr = ws.cell(1, 13)
for col, title in ((14, "9th Result"), (15, "9th Remarks"), (16, "After Fix"), (17, "After Fix Remarks")):
    c = ws.cell(1, col, title)
    c.font = copy.copy(hdr.font); c.fill = copy.copy(hdr.fill)
    c.border = copy.copy(hdr.border); c.alignment = copy.copy(hdr.alignment)
for L, w in (("N", 12), ("O", 95), ("P", 12), ("Q", 95)):
    ws.column_dimensions[L].width = w
green, red = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE")
vt = ""
if VILL:
    vs = [c for cs in VILL.values() for c in cs]
    vt = (f" Full hierarchy: EVERY Focus Plus village was also tested ({sum(c['ok'] for c in vs):,}/{len(vs):,} "
          "villages pass; one question each, alternating beneficiaries / amount disbursed, name in UPPER / Title / "
          "lower case, shared names answered after the which-village choice).")


def cell(r, col, text, fill=None, ok=None):
    c = ws.cell(r, col, text)
    c.border = copy.copy(ws.cell(r, 13).border)
    if fill is not None:
        c.fill = fill
        c.font = Font(bold=True, color="006100" if ok else "9C0006")
        c.alignment = Alignment(horizontal="center", vertical="top")
    else:
        c.alignment = Alignment(wrap_text=True, vertical="top")


bad = []
for r in range(2, ws.max_row + 1):
    tc = ws.cell(r, 1).value
    if not tc or not str(tc).startswith("FOCUS-"):
        continue
    k = str(tc)[-3:]
    ok9, n9 = tally(NINTH, k)
    okf, nf = tally(FINAL, k)
    sc = f" Coverage: {SCOPE[k]}." if k in SCOPE else ""
    if k in FAIL9:
        cell(r, 14, "Fail", red, False)
        cell(r, 15, BASE + FAIL9[k] + f" 9th run: {ok9}/{n9} cases.")
    else:
        cell(r, 14, "Pass", green, True)
        cell(r, 15, BASE + f"{ok9}/{n9} cases correct against the DB." + sc)
    passed = nf and okf == nf
    if not passed:
        bad.append((tc, okf, nf))
    fix = FIXES.get(k, "No fix needed for this case (passed in the 9th run).")
    cell(r, 16, "Pass" if passed else "Fail", green if passed else red, passed)
    cell(r, 17, fix + f" Re-tested live 2026-10-10 on the final code: {okf}/{nf} cases pass." + sc + vt)
wb.save(P)
print("written; not all-pass:", bad)
