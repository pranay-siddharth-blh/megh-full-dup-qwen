"""Write the 2026-10-30 UAT round into the MGNREGA sheet of the testers' workbook:
columns U..X = "UAT 30-Oct Result", "UAT 30-Oct Remarks" (the first run, before the fixes),
"After Fix 30-Oct", "After Fix 30-Oct Remarks" (the re-run on the fixed code). One row per DATA-0xx.
Also adds a tab "MGNREGA UAT 30-Oct" with every conversation of the after-fix run.

Usage (repo root): write_mg_uat.py <before.json ...> -- <after.json ...>
(the result files of mg_uat.py / mg_uat_villages.py; a "-state" / "-xdistrict" / "-xblock" / "-samename"
tag on a test-case key is folded into its DATA-0xx row). Back up the workbook first."""
import collections
import json
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

WB = "reference_documents/Test Case Results - 30th Sep 26.xlsx"
LEVEL_WORDS = {"-state": "statewide", "-xdistrict": "at every district", "-xblock": "at every block",
               "-samename": "same-name villages"}

args = sys.argv[1:]
cut = args.index("--")
BEFORE, AFTER = args[:cut], args[cut + 1:]


def load(files):
    R = collections.defaultdict(list)
    for f in files:
        for k, v in json.load(open(f, encoding="utf-8")).items():
            R[k] += v
    return R


def reason(c):
    t = c["turns"][-1]
    if c.get("defects"):
        return "; ".join(c["defects"])
    if t["kind"] != "answer":
        return f"ended in {t['kind']} {t.get('rule') or ''}".strip()
    if c.get("value_ok") and c.get("level_ok") is False:
        return "answered at the wrong place level"
    return "wrong figure (" + (c.get("note") or "") + ")"


def fold(R):
    """DATA-0xx -> {"n", "ok", "by_tag": {tag: (ok, n)}, "fails": [(label, q, reason, answer)]}"""
    out = {}
    for key, cs in R.items():
        tc, tag = (key.split("-", 2)[0] + "-" + key.split("-", 2)[1]), ""
        if key.count("-") >= 2:
            tag = "-" + key.split("-", 2)[2]
        d = out.setdefault(tc, {"n": 0, "ok": 0, "by_tag": collections.defaultdict(lambda: [0, 0]), "fails": []})
        for c in cs:
            d["n"] += 1
            d["by_tag"][tag][1] += 1
            if c["ok"]:
                d["ok"] += 1
                d["by_tag"][tag][0] += 1
            else:
                d["fails"].append((c["label"], c["q"], reason(c), (c["turns"][-1].get("answer") or "")[:160]))
    return out


def coverage(d):
    parts = []
    for tag, (ok, n) in sorted(d["by_tag"].items()):
        parts.append(f"{ok}/{n}" + (f" {LEVEL_WORDS[tag]}" if tag else " at the case's own level"))
    return "; ".join(parts)


def remarks_before(d):
    head = (f"Tested 2026-10-30 through the LangGraph pipeline (live models, megh_db; every expected figure computed "
            f"from curated.v_expenditure / v_employment; no year = all financial years; every district, block and "
            f"constituency, the 24 sample villages, 40 same-name villages and all 6,491 villages). {d['ok']}/{d['n']} "
            f"conversations passed ({coverage(d)}).")
    if not d["fails"]:
        return head
    why = collections.Counter(r.split(" (")[0] for _l, _q, r, _a in d["fails"])
    ex = "; ".join(f"{l}: {r} — bot: {a!r}" for l, _q, r, a in d["fails"][:3])
    return head + f" Failures: {dict(why)}. Examples: {ex}"


def remarks_after(d, fixed_note):
    head = (f"Re-tested 2026-10-30 on the fixed code (same harness, same coverage): {d['ok']}/{d['n']} "
            f"({coverage(d)}).")
    if d["fails"]:
        head += " STILL FAILING: " + "; ".join(f"{l}: {r}" for l, _q, r, _a in d["fails"][:5])
    return (fixed_note + " " if fixed_note else "No fix needed for this case. ") + head


FIXES = {   # the code change each case drew (KI numbers in docs/KNOWN_ISSUES.md)
    "DATA-021": "Fixed (KI-643): with no year asked, a year filter the model invented is dropped, so the all-years average covers every financial year (59.82 had left FY 2025-26 out; correct 60.84).",
    "DATA-024": "Fixed (KI-636): a ranking of districts is a breakdown by district, so the SQL checker's 'single total' complaint no longer sends the turn to the documents.",
    "DATA-026": "Fixed (KI-635): village codes are written bare (278380), never digit-grouped like a count.",
    "DATA-014": "Fixed (KI-635, KI-641): village codes are written bare, never digit-grouped like a count; a no-year 'which villages received employment' list no longer loses its HAVING > 0 to the unasked-threshold rewrite (every constituency had ended in 'couldn't build a working query'); a list the model wrote without GROUP BY is made one row per village (Raksamgre: 124 rows for 116 villages, KI-642).",
    "DATA-001": "Fixed (KI-639): the rephraser may not add 'under the available schemes' (which drew the which-scheme pause); same-name villages are answered one row each, with the twin codes pinned when the SQL filtered none, and money in lakh (KI-637/638).",
    "DATA-005": "Fixed (KI-637, KI-640): villages that share a name are answered one row each (GROUP BY village), never summed; an exact two-word village name (RONGARE ADING) is no longer rewritten to a look-alike block (Rongara) by the spelling layer.",
    "DATA-010": "Fixed (KI-637): villages that share a name are answered one row each (GROUP BY village), never summed.",
    "DATA-011": "Fixed (KI-637, KI-638): same-name villages one row each; the SQL checker no longer rejects that per-village query; a village-grain money figure is written in lakh, never rounded to crore (1.60 lakh had read 0.02 crore).",
    "DATA-023": "Fixed (KI-639): wages vs materials for same-name villages is one verdict per village, from the fixed query.",
    "DATA-028": "Fixed (KI-637, KI-638): same-name villages one row each; the SQL checker no longer rejects that per-village query.",
}

B, A = fold(load(BEFORE)), fold(load(AFTER))
wb = openpyxl.load_workbook(WB)
ws = wb["MGNREGA"]
hdr_font = Font(bold=True)
wrap = Alignment(wrap_text=True, vertical="top")
green, red = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE")
for col, title in zip("UVWX", ["UAT 30-Oct Result", "UAT 30-Oct Remarks", "After Fix 30-Oct", "After Fix 30-Oct Remarks"]):
    ws[f"{col}2"] = title
    ws[f"{col}2"].font = hdr_font
    ws.column_dimensions[col].width = 14 if col in "UW" else 90
for row in range(3, ws.max_row + 1):
    tc = ws[f"A{row}"].value
    if not tc or not str(tc).startswith("DATA-"):
        continue
    b, a = B.get(tc), A.get(tc)
    if b:
        ws[f"U{row}"] = "Pass" if b["ok"] == b["n"] else "Fail"
        ws[f"U{row}"].fill = green if b["ok"] == b["n"] else red
        ws[f"V{row}"] = remarks_before(b)
    if a:
        ws[f"W{row}"] = "Pass" if a["ok"] == a["n"] else "Fail"
        ws[f"W{row}"].fill = green if a["ok"] == a["n"] else red
        ws[f"X{row}"] = remarks_after(a, FIXES.get(tc, "") if (b and b["fails"]) else "")
    for col in "UVWX":
        ws[f"{col}{row}"].alignment = wrap

# every after-fix conversation on its own tab
name = "MGNREGA UAT 30-Oct"
if name in wb.sheetnames:
    del wb[name]
t = wb.create_sheet(name)
t.append(["Test case", "Case", "Question", "Result", "Expected (from megh_db)", "Bot answer", "Pauses", "Defects / reason"])
for c in t[1]:
    c.font = hdr_font
for key in sorted(load(AFTER)):
    for c in load(AFTER)[key]:
        turns = c["turns"]
        t.append([key, c["label"], c["q"], "Pass" if c["ok"] else "Fail", json.dumps(c.get("expected"), default=str)[:300],
                  (turns[-1].get("answer") or "")[:1000], "; ".join(c.get("pause_notes") or []),
                  "" if c["ok"] else reason(c)])
for col, w in zip("ABCDEFGH", [12, 48, 70, 8, 40, 100, 40, 50]):
    t.column_dimensions[col].width = w
wb.save(WB)
tot_b = sum(d["n"] for d in B.values()); ok_b = sum(d["ok"] for d in B.values())
tot_a = sum(d["n"] for d in A.values()); ok_a = sum(d["ok"] for d in A.values())
print(f"before: {ok_b}/{tot_b}; after: {ok_a}/{tot_a}; cases pass before "
      f"{sum(1 for d in B.values() if d['ok'] == d['n'])}/{len(B)}, after {sum(1 for d in A.values() if d['ok'] == d['n'])}/{len(A)}")
print("written", WB)
