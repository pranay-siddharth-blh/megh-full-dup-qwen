"""Write the cross-scheme results into 'reference_documents/Cross Scheme Test Cases.xlsx'
(back it up first): Sheet1 gets the 9th-run and After-fix columns, plus a
'Coverage' summary and an 'All conversations' tab with every case run.

Usage (repo root): python tests/sheet_runs/cross/write_report.py"""
import collections
import json
import os
import sys

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WB = os.path.join("reference_documents", "Cross Scheme Test Cases.xlsx")
BASE = json.load(open(os.path.join(HERE, "baseline.json"), encoding="utf-8"))
RES = json.load(open(os.path.join(HERE, "cross_results.json"), encoding="utf-8"))
RES = {k: v for k, v in RES.items() if not k.startswith("VI--")}       # placeholder geography rows
GREEN, RED, AMBER = (PatternFill("solid", fgColor=c) for c in ("C6EFCE", "FFC7CE", "FFEB9C"))
WRAP = Alignment(wrap_text=True, vertical="top")
FAM = {"sheet": "Sheet cases (CROSS-1..20, every [district] / [block] filled)",
       "state": "Every scheme combination (57) x count / money / both, statewide",
       "rank": "Every combination: which scheme is higher (count, money)",
       "coverage": "Every combination: coverage (districts / blocks / villages reached)",
       "year": "Every financial year 2017-18..2025-26 x combinations (incl. years a scheme lacks)",
       "dwise": "District-wise / leading scheme per district / top districts; block-wise in every district",
       "words": "Wording variants (vs, &, lowercase, nrega, pmayg, 'all schemes', 'scheme-wise')",
       "district": "Every district (12) x every combination (57)",
       "block": "Every block (69), two combinations each",
       "ac": "Every assembly constituency (60), two combinations each",
       "village": "Every village any scheme holds (one question each)"}

# 9th run (before the fixes): the 20 questions verbatim, [district] = East Khasi Hills, [block] = Mylliem
NINTH = {}
for k, r in BASE.items():
    if r["kind"] == "pause":
        NINTH[k] = ("Fail", f"Paused ({r.get('rule')}): {(r.get('answer') or '')[:220]}")
    elif k == "CROSS-14":
        NINTH[k] = ("Fail", "Answered with '(no label)' rows and figures not tied to schemes: "
                    + (r.get("answer") or "")[:200])
    elif k == "CROSS-20":
        NINTH[k] = ("Fail", "Added MGNREGA expenditure, PMAY-G releases and Focus Plus disbursements into "
                    "one 'total across all schemes'; no beneficiary figures: " + (r.get("answer") or "")[:160])
    else:
        NINTH[k] = ("Fail", (r.get("answer") or "")[:240])


def sheet_case(cid):
    return cid.split("|")[0]


def main():
    wb = load_workbook(WB)
    ws = wb["Sheet1"]
    heads = ["9th Run (2026-10-13, before fixes)", "9th Run remarks", "After Fix (2026-10-13)",
             "After Fix — conversations passed", "After Fix remarks"]
    for i, h in enumerate(heads):
        c = ws.cell(row=1, column=4 + i, value=h)
        c.font = Font(bold=True)
        c.alignment = WRAP
    by_case = collections.defaultdict(list)
    for k, r in RES.items():
        if r["fam"] == "sheet":
            by_case[sheet_case(k)].append((k, r))
    for row in range(2, ws.max_row + 1):
        tid = ws.cell(row=row, column=1).value
        if not tid:
            continue
        st, rm = NINTH.get(tid, ("", ""))
        ws.cell(row=row, column=4, value=st).fill = RED if st == "Fail" else GREEN
        ws.cell(row=row, column=5, value=rm).alignment = WRAP
        runs = by_case.get(tid, [])
        ok = sum(r["ok"] for _, r in runs)
        st2 = "Pass" if runs and ok == len(runs) else ("Fail" if runs else "")
        ws.cell(row=row, column=6, value=st2).fill = GREEN if st2 == "Pass" else RED
        ws.cell(row=row, column=7, value=f"{ok}/{len(runs)}")
        if len(runs) > 1:
            lvl = "every district" if tid in ("CROSS-8", "CROSS-11", "CROSS-14") else (
                "every block" if tid == "CROSS-9" else "district trios")
            note = f"Run for {lvl} ({len(runs)} conversations); each scheme's figure checked against megh_db."
        else:
            note = "Each scheme's figure checked against megh_db. " + (runs[0][1]["turns"][-1]["answer"] or "")[:300] if runs else ""
        ws.cell(row=row, column=8, value=note).alignment = WRAP
    for col, w in zip("ABCDEFGH", (11, 38, 60, 14, 60, 12, 14, 70)):
        ws.column_dimensions[col].width = w

    for name in ("Coverage", "All conversations"):
        if name in wb.sheetnames:
            del wb[name]
    cv = wb.create_sheet("Coverage")
    cv.append(["Family", "What it covers", "Conversations", "Passed", "Result"])
    tot = [0, 0]
    for fam, desc in FAM.items():
        rs = [r for r in RES.values() if r["fam"] == fam]
        if not rs:
            continue
        ok = sum(r["ok"] for r in rs)
        tot[0] += len(rs)
        tot[1] += ok
        cv.append([fam, desc, len(rs), ok, "Pass" if ok == len(rs) else "Fail"])
    cv.append(["TOTAL", "", tot[0], tot[1], "Pass" if tot[0] == tot[1] else "Fail"])
    combos = collections.Counter(tuple(sorted(r["schemes"])) for r in RES.values())
    cv.append([])
    cv.append(["Scheme combinations exercised", len(combos)])
    lv = collections.Counter(r.get("level") or ("year" if r["f"].get("year") else "state") for r in RES.values())
    for k, n in sorted(lv.items()):
        cv.append([f"Level: {k}", n])
    for c in cv[1]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDE", (14, 80, 14, 10, 10)):
        cv.column_dimensions[col].width = w

    al = wb.create_sheet("All conversations")
    al.append(["Case", "Family", "Shape", "Schemes", "Level", "Place / year filter", "Question(s) asked",
               "Pauses answered", "Bot's final answer", "Result", "Failures"])
    for k, r in RES.items():
        qs = " → ".join(t["q"] for t in r["turns"])
        al.append([k, r["fam"], r["shape"], ", ".join(r["schemes"]), r.get("level") or "",
                   json.dumps(r["f"], ensure_ascii=False), qs, "; ".join(r["notes"]),
                   (r["turns"][-1]["answer"] or "")[:1500], "Pass" if r["ok"] else "Fail", "; ".join(r["bad"])[:800]])
        al.cell(row=al.max_row, column=10).fill = GREEN if r["ok"] else RED
    for c in al[1]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJK", (26, 10, 11, 40, 12, 30, 70, 30, 90, 8, 60)):
        al.column_dimensions[col].width = w
    al.freeze_panes = "A2"
    wb.save(WB)
    print(f"written {WB}: sheet 20 rows, {tot[1]}/{tot[0]} conversations")


if __name__ == "__main__":
    main()
