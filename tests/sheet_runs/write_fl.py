"""Writes the FOCUS (Focus Legacy) sheet's 9th Result / 9th Remarks / After Fix / After Fix Remarks
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

BASE = ("Tested 2026-10-12 through the LangGraph pipeline with the live models and megh_db (Focus Legacy); every "
        "expected figure computed from curated.v_focus_legacy only (payments = COUNT(*), producer groups = "
        "COUNT(DISTINCT pg_id), memberships = SUM(no_of_pg_members), amount = SUM(amount_disbursed) = memberships x "
        "Rs 5,000; FY 2023-24 holds no payments). The sheet's questions say 'FOCUS', so the bot asks Focus Legacy or "
        "Focus Plus; Focus Legacy was chosen. ")
# 9th run = the first run, judged on the bot only (the test runner first picked Focus Plus at the Focus
# Legacy-or-Plus question, a runner error; those cases were re-asked with Focus Legacy before any fix).
FAIL9 = {
    "03": "Fail. The answer described the beneficiaries but did not state the Rs 5,000 per member assistance.",
    "06": "Fail. The support was described without the Rs 5,000 per member mobilisation fund.",
    "09": "Fail. 'Give me a short overview of FOCUS that I can use for an official briefing' was refused as "
          "content writing.",
    "12": "Fail (as the testers reported). Duplicates were explained (0 duplicate records, 2,655 groups paid more "
          "than once) but the 2,663 repeat payments were not stated.",
    "15": "Fail. 'List top 5 FOCUS PGs which has more than 20 members' was refused as content writing.",
    "20": "Fail. 'Show me all FOCUS remittances made between April and June 2025' was refused as 'I can't do things "
          "on your behalf'; 'January to March 2026' was told no data is held for 2026.",
    "24": "Fail (1 of 4 pairs). 'Compare … between FY 2022-23 and FY 2025-26' was reworded into a plain total and "
          "answered with one combined figure (Rs 32.69 crore) instead of each year.",
    "26": "Fail (5 of 68). 'under FOCUS' made the SQL filter programme_variant = 'FOCUS', dropping the top-up "
          "payments (Wapung 218 groups for 380); 'NONGSTOIN block' got the literal 'NONGstoin' and 0 groups.",
    "28": "Fail (5 of 55 constituencies). Khliehriat, Mairang, Nongstoin and Resubelpara (also HQ towns / blocks) "
          "offered district / block / village but not the constituency; 'North Tura' was refused as outside "
          "Meghalaya.",
}
FIXES = {
    "03": "Fixed: a Focus Legacy answer about benefits / support / eligibility / an overview always states the "
          "Rs 5,000 per member fund (from the scheme documents).",
    "06": "Fixed: as TC-03 — the Rs 5,000 per member fund is always stated.",
    "09": "Fixed: a request for an overview or data of a named scheme is never refused as content writing; "
          "explicit content requests ('write a post / speech') are still refused. Rs 5,000 per member stated.",
    "12": "Fixed: a fixed query and answer: 0 duplicate records (same group, same date), 2,655 groups paid more "
          "than once, and those repeats are 2,663 of the 14,569 payments.",
    "15": "Fixed: as TC-09 — a list of a scheme's groups is a data request, not content writing.",
    "20": "Fixed: date-range requests are not refused; a calendar month before a year ('January and March 2026') "
          "is read as that month (FY 2025-26), and the SQL checker no longer rejects the date filter "
          "(Jan-Mar 2026 = 33 remittances, Rs 22.10 lakh).",
    "24": "Fixed: the rewording step may not drop 'compare'; a two-year comparison is a fixed query giving each "
          "year and the difference (FY 2022-23 Rs 14.18 crore vs FY 2025-26 Rs 18.51 crore); a year with no "
          "payments (FY 2023-24) is stated first.",
    "26": "Fixed: 'FOCUS' (the scheme name) never becomes a programme_variant filter; UPPER(lgd_block) = '...' "
          "literals are upper-cased (Nongstoin 460 groups).",
    "28": "Fixed: a name that is also a constituency of a scheme holding constituency data offers the "
          "constituency (Khliehriat 386 groups); 'North Tura' is read as the constituency.",
    "18": "No fix needed at district level (passed). Hierarchy fix found in the all-villages run: 'amount "
          "disbursed for <village>' made the SQL also filter producer-group names on the village name (null or a "
          "fraction, e.g. Charbatapara Rs 2.10 lakh for Rs 15.45 lakh) — that filter is now removed (also when "
          "the model misspells the village), and a negated village filter is replaced by the village code.",
    "27": "No fix needed for the sheet cases (passed). Hierarchy fix from the all-villages run: the village "
          "'CHOKCHAKIA' was refused as violence ('chok…') — every scheme's village names are now masked before "
          "the harm checks; real harmful requests are still refused.",
}
SCOPE = {"14": "12 producer groups (one per district) named as 'X PG' / 'X Producer Group' / bare",
         "17": "every district (12)", "18": "every district (12)", "21": "all 4 FYs", "22": "all 4 FYs",
         "23": "all 4 FYs in 4 formats, plus FY 2023-24 (no data)", "24": "4 FY pairs incl. 2023-24",
         "25": "every district", "26": "every district's block breakdown (12) and every block on its own (56)",
         "27": "2 villages per district (24)", "28": "every assembly constituency (55)",
         "13": "two group names that do not exist", "15": "top 5 > 20 and top 10 > 25 members",
         "19": "more than Rs 5 lakh and Rs 7.5 lakh", "20": "Apr-Jun 2025, Jan-Mar 2026, Aug-Dec 2021"}


def tally(d, tc):
    cs = d.get("TC-" + tc, [])
    return sum(1 for c in cs if c["ok"]), len(cs)


wb = openpyxl.load_workbook(P)
ws = wb["FOCUS"]
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
    vt = (f" Full hierarchy: EVERY Focus Legacy village was also tested ({sum(c['ok'] for c in vs):,}/{len(vs):,} "
          "villages pass; one question each, alternating producer groups mapped / amount disbursed, name in UPPER / "
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
