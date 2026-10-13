"""Writes the CM Elevate sheet's 9th Result / 9th Remarks / After Fix / After Fix Remarks
(columns N..Q) from the 9th-run and final-run result files. Usage: write_ce.py <final.json> [<village_all.json>]"""
import copy
import json
import os
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

HERE = os.path.dirname(os.path.abspath(__file__))
P = r"C:/Users/Admin/OneDrive/Desktop/MCP/meghoneai/meghalaya/reference_documents/Test Case Results - 30th Sep 26.xlsx"
NINTH = json.load(open(os.path.join(HERE, "ce_results_9th.json"), encoding="utf-8"))
FINAL = json.load(open(sys.argv[1], encoding="utf-8"))
VILL = json.load(open(sys.argv[2], encoding="utf-8")) if len(sys.argv) > 2 else None

BASE = ("Tested 2026-10-10 through the LangGraph pipeline with the live models and megh_db; every expected figure "
        "computed from curated.v_cm_elevate (applicants = COUNT(DISTINCT request_id), pending = data_verified "
        "'On Hold', villages exclude entity_type 'Unresolved'). ")

# 9th-run failures: (why it failed). The first smoke run (before the 9th run) also failed 005 / 013 / 015.
FAIL9 = {
    "005": "Fail. The query rephraser turned 'applicants' into 'applications', so the bot counted rows (8,627) "
           "instead of distinct applicants (8,600).",
    "010": "Fail (3 of 65 blocks: BATABARI, RAMBRAI, RERAPARA). These block names are also village names; the bot "
           "answered for the village instead of the block, or asked nothing.",
    "012": "Fail (3 of 12). Sector is recorded only on Poultry/Dairy/Goat applications; the model-written SQL "
           "filtered on the wrong programme, so e.g. Piggery sector in North Garo Hills was given as 0 instead of the "
           "applicants recorded under other programmes.",
    "013": "Fail. The guardrail model refused 'How many applicants under <programme> belong to <sector> sector?' "
           "as out of scope.",
    "014": "Fail (2 of 12). For two named programmes and a sector the bot gave one combined or one-programme "
           "figure, not each programme's own count.",
    "015": "Fail. 'Status distribution across CM ELEVATE' was answered from the scheme documents (no figures) "
           "instead of from the data.",
    "022": "Fail (6 of 12). 'Completed data verification' was not recognised as CM Elevate vocabulary; the bot "
           "counted rows instead of distinct applicants and mixed verified / not-verified totals.",
    "025": "Fail (1 of 12: Ri Bhoi). The answer listed sector rows but not each programme's total (Poultry 241 "
           "applicants, 48 on hold).",
    "027": "Fail (4 of 6). When two districts were named, the second was dropped (or replaced by a similar "
           "name), so the comparison was for the wrong district.",
    "028": "Fail (6 of 12). 'Pending in each sector' was not answered: 'no matching records', 'data doesn't "
           "cover pending', or no working query.",
}
FIXES = {
    "005": "Fixed: the rephraser may not change applicants <-> applications (count nouns must match).",
    "010": "Fixed: a block name that is also a village name now asks 'block or village?' and the chosen level is used.",
    "012": "Fixed: sector questions are answered by a fixed, checked query across all programmes "
           "(scheme_specific->>'sector_id'), counting distinct applicants.",
    "013": "Fixed: a count question about a named programme can no longer be refused as out of scope.",
    "014": "Fixed: two named programmes + sector -> each programme's own count plus the combined total "
           "(fixed query; programmes with 0 still listed).",
    "015": "Fixed: 'status distribution / status-wise / pendency' is routed to the data, with the sendback "
           "spellings merged into 'Sent back'.",
    "022": "Fixed: 'data verification' terms pin CM Elevate; verified = data_verified 'Valid', counted by distinct "
           "applicant.",
    "025": "Fixed: rows grouped by programme and sector are answered with each programme's total, then each sector.",
    "027": "Fixed: every district named in the question is kept (two districts -> both, as an IN-list); the "
           "comparison is grouped by district.",
    "028": "Fixed: 'pending in each sector' is answered by a fixed query listing every sector (including 0 and "
           "'(not recorded)') with the total.",
}


def tally(d, tc):
    cs = d.get("CM-ELEVATE-OFF-" + tc, [])
    return sum(1 for c in cs if c["ok"]), len(cs)


wb = openpyxl.load_workbook(P)
ws = wb["CM Elevate"]
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
    vt = (f" Full hierarchy: EVERY CM Elevate village was also tested ({sum(c['ok'] for c in vs):,}/{len(vs):,} "
          "villages pass; one question each, rotating the OFF-003 / 008 / 030 shapes, name in UPPER / Title / lower "
          "case, shared names answered after the which-village choice).")


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
    if not tc or not str(tc).startswith("CM-ELEVATE-OFF-"):
        continue
    k = str(tc)[-3:]
    ok9, n9 = tally(NINTH, k)
    okf, nf = tally(FINAL, k)
    if k in FAIL9:
        cell(r, 14, "Fail", red, False)
        cell(r, 15, BASE + FAIL9[k] + (f" 9th run: {ok9}/{n9} cases." if n9 else ""))
    else:
        cell(r, 14, "Pass", green, True)
        cell(r, 15, BASE + f"{ok9}/{n9} cases correct against the DB.")
    passed = nf and okf == nf
    if not passed:
        bad.append((tc, okf, nf))
    fix = FIXES.get(k, "No fix needed for this case (passed in the 9th run).")
    cell(r, 16, "Pass" if passed else "Fail", green if passed else red, passed)
    cell(r, 17, fix + f" Re-tested live 2026-10-10 on the final code: {okf}/{nf} cases pass." + vt)
wb.save(P)
print("written; not all-pass:", bad)
