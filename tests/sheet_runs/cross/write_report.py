"""Write the cross-scheme results into 'reference_documents/Cross Scheme Test Cases.xlsx'
(back it up first). Sheet1 keeps the 2026-10-13 columns D..H and gets the
2026-10-30 re-run in columns I..M (before the fixes, after the fixes), plus a
'Coverage' summary and an 'All conversations' tab with every case run.

Usage (repo root): python tests/sheet_runs/cross/write_report.py [results.json] [baseline_graded.json]"""
import collections
import json
import os
import sys

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WB = os.path.join("reference_documents", "Cross Scheme Test Cases.xlsx")
RES_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "cross_results.json")
BASE_PATH = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "baseline_1030_graded.json")
RES = json.load(open(RES_PATH, encoding="utf-8"))
RES = {k: v for k, v in RES.items() if not k.startswith("VI--")}       # placeholder geography rows
BASE = json.load(open(BASE_PATH, encoding="utf-8")) if os.path.exists(BASE_PATH) else {}
RUN_DATE = "2026-10-30"
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


def sheet_case(cid):
    return cid.split("|")[0]


def main():
    wb = load_workbook(WB)
    ws = wb["Sheet1"]
    heads = [f"{RUN_DATE} Run (before fixes)", f"{RUN_DATE} remarks", f"After Fix ({RUN_DATE})",
             "After Fix — conversations passed", "After Fix remarks"]
    col0 = 9                                   # I..M; D..H hold the 2026-10-13 run
    for i, h in enumerate(heads):
        c = ws.cell(row=1, column=col0 + i, value=h)
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
        b = BASE.get(tid)
        if b:
            st = "Pass" if b["ok"] else "Fail"
            rm = ("Each scheme's figure checked against megh_db." if b["ok"]
                  else "; ".join(b["bad"])[:400] + " | answer: " + (b.get("answer") or "")[:300])
        else:
            st, rm = "", ""
        ws.cell(row=row, column=col0, value=st).fill = RED if st == "Fail" else GREEN
        ws.cell(row=row, column=col0 + 1, value=rm).alignment = WRAP
        runs = by_case.get(tid, [])
        ok = sum(r["ok"] for _, r in runs)
        st2 = "Pass" if runs and ok == len(runs) else ("Fail" if runs else "")
        ws.cell(row=row, column=col0 + 2, value=st2).fill = GREEN if st2 == "Pass" else RED
        ws.cell(row=row, column=col0 + 3, value=f"{ok}/{len(runs)}")
        if len(runs) > 1:
            lvl = "every district" if tid in ("CROSS-8", "CROSS-11", "CROSS-14") else (
                "every block" if tid == "CROSS-9" else "district trios")
            note = f"Run for {lvl} ({len(runs)} conversations); each scheme's figure checked against megh_db."
            fails = [f"{k}: {'; '.join(r['bad'])[:120]}" for k, r in runs if not r["ok"]]
            if fails:
                note += " Failed: " + " | ".join(fails)[:600]
        else:
            note = ("Each scheme's figure checked against megh_db. " + (runs[0][1]["turns"][-1]["answer"] or "")[:300]) \
                if runs else ""
            if runs and not runs[0][1]["ok"]:
                note = "; ".join(runs[0][1]["bad"])[:300] + " | " + note
        ws.cell(row=row, column=col0 + 4, value=note).alignment = WRAP
    for col, w in zip("ABCDEFGHIJKLM", (11, 38, 60, 14, 60, 12, 14, 70, 14, 60, 12, 14, 70)):
        ws.column_dimensions[col].width = w

    for name in ("Coverage", "All conversations"):
        if name in wb.sheetnames:
            del wb[name]
    cv = wb.create_sheet("Coverage")
    cv.append([f"Re-run {RUN_DATE}: every conversation through the live LangGraph pipeline, every figure checked "
               "against megh_db (tests/sheet_runs/cross/)"])
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
    for c in cv[2]:
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
