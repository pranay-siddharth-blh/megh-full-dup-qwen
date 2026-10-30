"""uat/make_report.py -> uat/CM Elevate UAT Results (Exhaustive) - <date>.xlsx

Summary (per category: generated / executed / passed / failed / errors / disputed / needs-review / pass %), one
sheet per category (Test ID, Category, Input, Expected (SQL), Actual (App), Status, Root Cause, Fix Commit),
Bugs, and the latest row per test from results.csv."""
import csv
import json
import os
import sys
import time

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
csv.field_size_limit(10 ** 8)
DATE = time.strftime("%Y-%m-%d")
matrix = list(csv.DictReader(open(os.path.join(HERE, "test_matrix.csv"), newline="", encoding="utf-8")))
last, first = {}, {}
for r in csv.DictReader(open(os.path.join(HERE, "results.csv"), newline="", encoding="utf-8")):
    first.setdefault(r["id"], r)
    last[r["id"]] = r
bugs = json.load(open(os.path.join(HERE, "bugs.json"), encoding="utf-8")) if os.path.exists(os.path.join(HERE, "bugs.json")) else []
rootmap = json.load(open(os.path.join(HERE, "rootcause.json"), encoding="utf-8")) if os.path.exists(os.path.join(HERE, "rootcause.json")) else {}
disputed = set(json.load(open(os.path.join(HERE, "disputed_ids.json")))) if os.path.exists(os.path.join(HERE, "disputed_ids.json")) else set()
review = set(json.load(open(os.path.join(HERE, "needs_review_ids.json")))) if os.path.exists(os.path.join(HERE, "needs_review_ids.json")) else set()

GREEN, RED, AMBER, HEAD = (PatternFill("solid", fgColor=c) for c in ("C6EFCE", "FFC7CE", "FFEB9C", "1F4E78"))
WRAP = Alignment(wrap_text=True, vertical="top")


def sheet(ws, header, rows, widths, status_col=None):
    ws.append(header)
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), HEAD, WRAP
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    if status_col:
        for row in ws.iter_rows(min_row=2):
            v = str(row[status_col - 1].value or "")
            row[status_col - 1].fill = GREEN if v == "Pass" else RED if v == "Fail" else AMBER if v else PatternFill()
    ws.freeze_panes = "A2"


def root_for(tid):
    for k in sorted(rootmap, key=len, reverse=True):
        if tid.startswith(k):
            return rootmap[k]
    return None


wb = Workbook()
ws = wb.active
ws.title = "Summary"
cats = sorted({t["category"] for t in matrix})
rows, tot = [], [0] * 7
for c in cats:
    ts = [t for t in matrix if t["category"] == c]
    gen = len(ts)
    ex = sum(1 for t in ts if t["id"] in last)
    p = sum(1 for t in ts if last.get(t["id"], {}).get("status") == "Pass")
    f = sum(1 for t in ts if last.get(t["id"], {}).get("status") == "Fail")
    e = sum(1 for t in ts if last.get(t["id"], {}).get("status") == "Error")
    d = sum(1 for t in ts if t["id"] in disputed)
    n = sum(1 for t in ts if t["id"] in review)
    rows.append([c, gen, ex, p, f, e, d, n, f"{100 * p / gen:.2f}%"])
    for i, v in enumerate((gen, ex, p, f, e, d, n)):
        tot[i] += v
rows.append(["TOTAL", *tot, f"{100 * tot[2] / tot[0]:.2f}%"])
sheet(ws, ["Category", "Generated", "Executed", "Passed", "Failed", "Errors", "Disputed", "Needs review", "Pass %"], rows,
      [26, 11, 11, 11, 11, 11, 11, 13, 10])
ws.append([])
ws.append([f"Unique test IDs in results.csv: {len(last)} / matrix total {len(matrix)}"])
ws.append([f"Generated {time.strftime('%Y-%m-%d %H:%M')} from uat/test_matrix.csv and uat/results.csv (latest row per test)."])
ws.append([])
ws.append(["Run of each result (latest row per test)", "Tests", "Passed"])
import collections
_runs = collections.Counter(); _runs_p = collections.Counter()
for t in matrix:
    r = last.get(t["id"])
    if r:
        _runs[r.get("run", "")] += 1
        _runs_p[r.get("run", "")] += r.get("status") == "Pass"
for k in sorted(_runs, key=lambda x: -_runs[x]):
    ws.append([k, _runs[k], _runs_p[k]])
ws.append([])
ws.append(["Sheet test case", "Questions", "Passed", "Status"])
_tc = collections.defaultdict(lambda: [0, 0])
for t in matrix:
    if t["tc"].startswith("CM-ELEVATE"):
        _tc[t["tc"]][0] += 1
        _tc[t["tc"]][1] += last.get(t["id"], {}).get("status") == "Pass"
for k in sorted(_tc):
    ws.append([k, _tc[k][0], _tc[k][1], "Working" if _tc[k][0] == _tc[k][1] else "Not working"])

HDR = ["Test ID", "Category", "Input", "Expected (SQL)", "Actual (App)", "Status", "Root Cause", "Fix Commit", "Run"]
for c in cats:
    ws = wb.create_sheet(c[:31])
    data = []
    for t in matrix:
        if t["category"] != c:
            continue
        r = last.get(t["id"], {})
        rc = root_for(t["id"]) if first.get(t["id"], {}).get("status") in ("Fail", "Error") or r.get("status") != "Pass" else None
        q = t["question"]
        if t["kind"] == "chain":
            q = " -> ".join(x["say"] for x in json.loads(q))
        exp = f"{t['checks']}" + (f" total {t['total']}" if t["total"] else "") + f"\n{t['truth_sql']}"
        root = ""
        if r.get("status") != "Pass" and r.get("fails"):
            root = r["fails"][:500]
        if rc:
            root = (rc.get("root", "") + (" | " + root if root and r.get("status") != "Pass" else "")).strip(" |")
        data.append([t["id"], c, q[:2000], exp[:2000], (r.get("actual") or "")[:3000], r.get("status", "Not run"),
                     root[:1500], (rc or {}).get("commit", "") if rc else "", r.get("run", "")])
    sheet(ws, HDR, data, [26, 18, 50, 45, 70, 9, 50, 14, 10], status_col=6)
ws = wb.create_sheet("Bugs")
sheet(ws, ["Bug", "Symptom", "Root cause", "Fix", "Files", "Commit", "Shared code?"],
      [[b.get("bug"), b.get("symptom"), b.get("root"), b.get("fix"), b.get("files"), b.get("commit", ""), b.get("shared", "")]
       for b in bugs], [26, 50, 55, 55, 40, 14, 25])
out = os.path.join(HERE, f"CM Elevate UAT Results (Exhaustive) - {DATE}.xlsx")
wb.save(out)
print("saved", out, "| results", len(last), "/ matrix", len(matrix))
