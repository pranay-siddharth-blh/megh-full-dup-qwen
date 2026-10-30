"""Writes the PMAY-G sheet's 2026-10-30 re-test columns (U..X: "30 Oct Result", "30 Oct Remarks",
"30 Oct After Fix", "30 Oct After Fix Remarks"; the 2026-10-10 columns Q..T are kept) from the
first run's log (pm_run.py on the code before the fixes; the VPN dropped before it finished, so a
case it never reached is judged on the final run, which the fixes do not touch), the final-run
result file and the all-villages result file.
Usage: write_pm.py <first_run.log> <final.json> <villages.json>"""
import copy
import json
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

P = r"C:/Users/Admin/OneDrive/Desktop/MCP/meghoneai/reference_documents/Test Case Results - 30th Sep 26.xlsx"
FIRST_LOG, FINAL, VILL = sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8")), \
    json.load(open(sys.argv[3], encoding="utf-8"))

BASE = ("Re-tested 2026-10-30 through the LangGraph pipeline with the live models and megh_db; every expected figure "
        "computed from curated.v_pmay (beneficiaries = every row incl. the 126 zero-sanction registrations, D-060; "
        "amounts in rupees; a full release needs sanctioned_amount > 0). Hierarchy: 2 villages per district (24, "
        "UPPER / Title case), EVERY block (56, bare and as 'X block'), EVERY district (12), EVERY assembly "
        "constituency (56, as 'X constituency' / 'X assembly constituency' / 'X AC'), every district x every FY "
        "(84, four year formats), village / block / district pairs, 12 sanction dates in 4 formats. ")
AC_FAIL = ("Fail at constituency level (district and block level passed). PMAY-G was not constituency-capable "
           "(KI-445), so 'X constituency' went to the SQL model, which wrote ac_name = 'AMLAREM' against the "
           "Title Case 'Amlarem' and answered a false 0 (Amlarem: true 2,677 beneficiaries), 'no matching records', "
           "or 'couldn't build a working query'; the follow-up chips said 'in Meghalaya'.")
AC_FIX = ("Fixed: PMAY-G records the constituency (v_pmay.ac_name, D-096): 'X constituency / assembly constituency / "
          "AC' is answered by the fixed PMAY-G query (UPPER(ac_name), one row, named '<X> assembly constituency'); "
          "the model path gets a case-insensitive ac_name rewrite and a repair when a resolved constituency is not "
          "filtered; chips keep the constituency. ")
TWIN_FIX = ("Hierarchy fix from the all-villages run (KI-630): a name shared by 2-3 villages (D-089 J-10: answered "
            "for each) left the fixed PMAY-G query, and the model summed the villages ('39 beneficiaries in Kotchugre "
            "(Batabari block) and Kotchugre (Tikrikilla block)' for 12 and 27) or failed to build a query. The "
            "fixed query now answers twins too: one row per village named with its block, never added up, result "
            "table carries the block. ")
VILLAGE_TCS = {"001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "026", "028"}
DISTRICT_TCS = {"015", "016", "017", "018", "019", "020", "021"}
SCOPE = {**{k: "24 villages (2 per district)" for k in VILLAGE_TCS},
         **{k: "every block (56), bare and as 'X block'" for k in ("011", "012", "013", "014")},
         **{k: "every district (12) + every assembly constituency (56)" for k in DISTRICT_TCS},
         "022": "24 village pairs inside one block", "023": "28 block pairs", "024": "6 district pairs",
         "025": "every district x every FY 2017-18..2023-24 (84), year written 4 ways",
         "027": "12 sanction dates (the 8 busiest + 4 others) in 4 date formats"}


def first_run():
    """{tc: (ok, bad, ac_bad)} from the first run's log lines 'TC | label | OK/BAD | ...'."""
    out = {}
    for ln in open(FIRST_LOG, encoding="utf-8", errors="replace"):
        parts = [x.strip() for x in ln.split(" | ")]
        if len(parts) < 4 or not parts[0].startswith("PMAY-OFF-") or "ended in error" in ln:
            continue
        ok, bad, ac = out.get(parts[0], (0, 0, 0))
        if parts[2] == "OK":
            ok += 1
        else:
            bad += 1
            ac += parts[1].startswith("AC ")
        out[parts[0]] = (ok, bad, ac)
    return out


def tally(d, tc):
    cs = d.get("PMAY-OFF-" + tc, [])
    return sum(1 for c in cs if c["ok"]), len(cs)


FIRST = first_run()
vs = [c for cs in VILL.values() for c in cs]
VT = (f" Full hierarchy: EVERY PMAY-G village was also tested ({sum(c['ok'] for c in vs):,}/{len(vs):,} villages "
      "pass; one question each rotating over the 12 village cases, name in UPPER / Title / lower case, shared "
      "names answered one row per village).")

wb = openpyxl.load_workbook(P)
ws = wb["PMAY-G"]
hdr = ws.cell(1, 16)
for col, title in ((21, "30 Oct Result"), (22, "30 Oct Remarks"), (23, "30 Oct After Fix"), (24, "30 Oct After Fix Remarks")):
    c = ws.cell(1, col, title)
    c.font = copy.copy(hdr.font); c.fill = copy.copy(hdr.fill)
    c.border = copy.copy(hdr.border); c.alignment = copy.copy(hdr.alignment)
for L, w in (("U", 14), ("V", 95), ("W", 16), ("X", 95)):
    ws.column_dimensions[L].width = w
green, red = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE")


def cell(r, col, text, fill=None, ok=None):
    c = ws.cell(r, col, text)
    c.border = copy.copy(ws.cell(r, 16).border)
    if fill is not None:
        c.fill = fill
        c.font = Font(bold=True, color="006100" if ok else "9C0006")
        c.alignment = Alignment(horizontal="center", vertical="top")
    else:
        c.alignment = Alignment(wrap_text=True, vertical="top")


bad = []
for r in range(2, ws.max_row + 1):
    tc = ws.cell(r, 1).value
    if not tc or not str(tc).startswith("PMAY-OFF-"):
        continue
    k = str(tc)[-3:]
    ok1, bad1, ac1 = FIRST.get(str(tc), (0, 0, 0))
    okf, nf = tally(FINAL, k)
    sc = f" Coverage: {SCOPE.get(k, '')}."
    if bad1:
        cell(r, 21, "Fail", red, False)
        detail = AC_FAIL if ac1 == bad1 else f"{bad1} of {ok1 + bad1} conversations wrong."
        cell(r, 22, BASE + f"First run: {ok1}/{ok1 + bad1} pass. " + detail + sc)
    elif ok1:
        cell(r, 21, "Pass", green, True)
        cell(r, 22, BASE + f"First run: {ok1}/{ok1} correct against the DB." + sc)
    else:
        cell(r, 21, "Pass" if nf and okf == nf else "Fail", green if nf and okf == nf else red, nf and okf == nf)
        cell(r, 22, BASE + "The VPN dropped before the first run reached this case; judged on the complete run on the "
                    f"final code, which the fixes (constituency, shared village names) do not touch: {okf}/{nf} pass." + sc)
    passed = nf and okf == nf
    if not passed:
        bad.append((tc, okf, nf))
    fix = (AC_FIX if k in DISTRICT_TCS else TWIN_FIX if k in VILLAGE_TCS
           else "No fix needed for this case. ")
    cell(r, 23, "Pass" if passed else "Fail", green if passed else red, passed)
    cell(r, 24, fix + f"Re-tested live 2026-10-30 on the final code: {okf}/{nf} cases pass." + sc + VT)
wb.save(P)
print("written; not all-pass:", bad)
