"""Final round report (2026-10-13): one workbook from the seven final_*.json result files.
Summary + one tab per sheet (every test case with its result) + every conversation.
Usage (repo root): final_report.py <out.xlsx>"""
import json
import os
import sys
from collections import OrderedDict

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import has_value, numbers_in, text_numbers  # noqa: E402
from tests._text_checks import has_phrase, zero_lakh  # noqa: E402

HERE = os.environ.get("FINAL_DIR") or os.path.dirname(os.path.abspath(__file__))
WB_IN = r"C:/Users/Admin/OneDrive/Desktop/MCP/meghoneai/meghalaya/reference_documents/Test Case Results - 30th Sep 26.xlsx"
SHEETS = [  # (report tab, workbook tab, result file, header row, scheme label)
    ("General", "General", "final_general.json", 1),
    ("MGNREGA", "MGNREGA", "final_mgnrega.json", 2),
    ("PMAY-G", "PMAY-G", "final_pmay.json", 1),
    ("CM Elevate", "CM Elevate", "final_cme.json", 1),
    ("Focus +", "Focus +", "final_focusplus.json", 1),
    ("Focus Legacy", "FOCUS Legacy", "final_focuslegacy.json", 1),
    ("CM Elevate Legacy", "CM Elevate Legacy", "final_cmelegacy.json", 1),
]
# all-village runs on the final code of each sheet session (not repeated in this round)
VILLAGES = {"MGNREGA": "6,491/6,491 (2026-10-10)", "PMAY-G": "5,121/5,121 (2026-10-10)",
            "CM Elevate": "2,087/2,087 (2026-10-10)", "Focus +": "3,513/3,513 (2026-10-11)",
            "Focus Legacy": "3,384/3,384 (2026-10-12)", "CM Elevate Legacy": "1,051/1,051 (2026-10-12)",
            "General": "TC-023 covers districts, blocks and villages"}

SCHEMES = ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy", "CM Elevate Legacy"]
REFUSAL_PHRASES = ("outside what im allowed", "outside what i'm allowed", "i can only answer", "i only help",
                   "i only cover", "i only give", "not one of", "not covered", "not among",
                   *(f"i do{n} {v}" for n in ("nt", "n't") for v in ("give", "answer", "hold", "have", "write", "cover")),
                   "cant help", "can't help", "megh one ai", "isnt one of", "isn't one of", "not part of")
BAD_WORDING_PHRASES = ("reference material", "couldnt build a working query", "couldn't build a working query",
                       "ran into an error", "error")


def refusal(text):
    """The answer declines (case-insensitive phrase list)."""
    return has_phrase(text, *REFUSAL_PHRASES)


def bad_wording(text):
    return has_phrase(text, *BAD_WORDING_PHRASES)


def answer(t):
    return t.get("answer") or ""


def kb_ok(t, min_len=60):
    a = answer(t)
    return t.get("kind") == "answer" and len(a) >= min_len and not refusal(a[:160]) and not bad_wording(a)


def schemes_named(a):
    al = a.lower()
    return [s for s in SCHEMES if s.lower().replace("-", "") in al.replace("-", "")]


def judge_general(tc, c, db):
    """(ok, note) for one General conversation case without a value check."""
    T = c["turns"]
    last = T[-1]
    a = answer(last)
    lab = c["label"]
    if tc == "TC-001":
        n = len(schemes_named(a))
        return n >= 6, f"{n}/6 schemes named"
    if tc in ("TC-002", "TC-004", "TC-005", "TC-006", "TC-009"):
        return kb_ok(last), "scheme answer given in context" if kb_ok(last) else f"{last.get('kind')}: {a[:80]}"
    if tc == "TC-003":
        if lab == "no context":
            ok = last.get("kind") == "pause" or len(schemes_named(a)) >= 2
            return ok, "asks which scheme / lists schemes" if ok else a[:80]
        return kb_ok(last), "eligibility answered in context"
    if tc == "TC-019":
        ok = all(kb_ok(t, 40) for t in T[1:])
        return ok, "every short follow-up answered in context" if ok else "a follow-up was not answered"
    if tc == "TC-007":
        a_, b_ = lab.split(" vs ")
        ok = kb_ok(last) and a_.lower() in a.lower() and b_.lower() in a.lower()
        return ok, "both schemes compared" if ok else a[:80]
    if tc == "TC-008":
        return len(schemes_named(a)) >= 2, f"{len(schemes_named(a))} schemes suggested"
    if tc == "TC-010":
        ok = all(kb_ok(t, 40) for t in T)
        return ok, "4 turns answered in context" if ok else "a turn was not answered"
    if tc == "TC-011":
        # no earlier context: asking which scheme (a pause, or a reply listing the schemes) is right
        ok = last.get("kind") == "pause" or len(schemes_named(a)) >= 4 or (kb_ok(last) and has_phrase(a, "apply", "application"))
        return bool(ok), "asks which scheme / explains applying"
    if tc == "TC-012":
        big = [n for n in text_numbers(a) if n >= 100 and n not in (2005, 2016, 2022, 2023, 2024, 2025)]
        ok = bool(refusal(a) or has_phrase(a, "not held", "not available", "not part", "does not cover",
                                             "dont cover", "don't cover")) and not big
        return ok, "says the scheme is not covered; no invented figure" if ok else a[:80]
    if tc in ("TC-013", "TC-014"):
        ok = refusal(a)
        return ok, "politely declined (out of scope)" if ok else a[:80]
    if tc == "TC-015":
        ok = last.get("kind") == "answer" and len(a) > 40 and not bad_wording(a)
        return ok, "points to the right office / route" if ok else a[:80]
    if tc == "TC-016":
        return len(schemes_named(a)) >= 4, f"{len(schemes_named(a))} schemes listed"
    if tc == "TC-017":
        ok = kb_ok(last) and "pmay" in a.lower()
        return ok, "misspelt question answered" if ok else a[:80]
    if tc == "TC-018":
        return kb_ok(last), "eligibility explained" if kb_ok(last) else a[:80]
    if tc == "TC-020":
        ok = last.get("kind") == "pause" and len(last.get("options") or []) >= 2 or kb_ok(last)
        return bool(ok), "asks which ADUGRE (3 villages)"
    if tc == "TC-021":
        d = db.get("TC-021", {})
        want = [d.get("ekh_pd"), d.get("ekh_hh"), d.get("wgh_hh"), d.get("wgh_exp")]
        got = [w is None or has_value(t, w) for t, w in zip(T, want)]
        return all(got), f"turn values {sum(got)}/{len(got)} (EKH person-days, households, WGH households, expenditure)"
    if tc == "TC-022":
        d = db.get("TC-022", {})
        by = {int(r["year_key"]): float(r["t"]) for r in d.get("abagre_by_year", [])}
        got = [has_value(T[0], d.get("abagre_all", 0)) or T[0].get("rule") == "year-not-specified",
               all(has_value(T[1], v) for v in by.values()),
               has_value(T[2], by.get(2023, 0))]
        return all(got), f"total / year-wise / 2023-24: {got}"
    if tc == "TC-024":
        d = db.get("TC-024", {})
        if "after MGNREGA" in lab:
            ok = has_value(T[1], d.get("wgh_persons_2024")) or has_value(T[1], d.get("wgh_hh_2024"))
        elif "fresh employment" in lab:
            ok = has_value(last, d.get("egh_hh_2023"))
        else:
            ok = has_value(last, d.get("rb_jobcards_2024"))
        return bool(ok), "MGNREGA inferred; figure matches the DB" if ok else a[:80]
    return kb_ok(last), ""


def load_meta(ws_name, hr):
    ws = WB.worksheets[[w.title for w in WB.worksheets].index(ws_name)]
    meta = OrderedDict()
    for r in range(hr + 1, ws.max_row + 1):
        tc = ws.cell(r, 1).value
        if tc and "A" <= str(tc)[:1] <= "Z":
            meta[str(tc).strip()] = (ws.cell(r, 2).value or "", str(ws.cell(r, 3).value or "").strip("“”\" "))
    return meta


def case_rows(sheet, data):
    """[(tc, label, questions, answer, expected, ok, note)]"""
    out = []
    db = data.get("_db", {})
    for tc, cases in data.items():
        if tc.startswith("_"):
            continue
        for c in cases:
            T = c.get("turns") or []
            qs = " → ".join(t.get("q", "") for t in T)
            ans = answer(T[-1]) if T else ""
            if T and T[-1].get("kind") == "pause":
                ans = "[asks] " + ans
            if "ok" in c:
                ok, note = bool(c["ok"]), c.get("note") or ""
                # MGNREGA checker corrections, as in mg_score.py: a 0-vs-0 wages/materials tie with both
                # zeros stated, and a percentage whose denominator is 0 answered "cannot be calculated"
                if not ok and sheet == "MGNREGA" and T and T[-1].get("kind") == "answer":
                    exp_ = c.get("expected")
                    if tc == "DATA-023" and isinstance(exp_, dict) and not exp_.get("wages")                             and not exp_.get("material") and zero_lakh(ans):
                        ok, note = True, "both 0 — the answer says neither was higher"
                    elif exp_ is None and ("cannot be calculated" in ans or "divided by is 0" in ans):
                        ok, note = True, "denominator 0 — the answer says it cannot be calculated"
            elif "value_ok" in c:
                ok = bool(c["value_ok"]) and c.get("level_ok") in (True, None)
                note = "figure matches the DB" if ok else f"expected {c.get('expected')}"
            else:
                ok, note = judge_general(tc, c, db)
            exp = c.get("expected")
            out.append((tc, c.get("label", ""), qs, ans, "" if exp is None else json.dumps(exp, default=str)[:300], ok, note))
    return out


thin = Side(style="thin", color="BFBFBF")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
HEAD = PatternFill("solid", fgColor="1F4E78")
GREEN, RED, GREY = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE"), PatternFill("solid", fgColor="F2F2F2")


def table(ws, headers, rows, widths, start=1, status_col=None):
    for j, h in enumerate(headers, 1):
        c = ws.cell(start, j, h)
        c.font, c.fill, c.alignment, c.border = Font(bold=True, color="FFFFFF"), HEAD, Alignment(wrap_text=True, vertical="center"), BORDER
    for i, row in enumerate(rows, start + 1):
        for j, v in enumerate(row, 1):
            c = ws.cell(i, j, v)
            c.alignment, c.border = Alignment(wrap_text=True, vertical="top"), BORDER
            if status_col and j == status_col:
                c.fill = GREEN if v == "Pass" else RED if v == "Fail" else GREY
                c.font = Font(bold=True, color="006100" if v == "Pass" else "9C0006")
                c.alignment = Alignment(horizontal="center", vertical="top")
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(start + 1, 1)


WB = openpyxl.load_workbook(WB_IN, read_only=False)
out = openpyxl.Workbook()
summary = out.active
summary.title = "Summary"
all_rows, sum_rows = [], []
tot = dict(tc=0, tcp=0, cv=0, cvp=0)
for tab, ws_name, fn, hr in SHEETS:
    path = os.path.join(HERE, fn)
    meta = load_meta(ws_name, hr)
    if not os.path.exists(path):
        sum_rows.append((tab, len(meta), "", "", "", "", "NOT RUN", VILLAGES.get(tab, "")))
        continue
    rows = case_rows(tab, json.load(open(path, encoding="utf-8")))
    by_tc = OrderedDict((tc, []) for tc in meta)
    for r in rows:
        by_tc.setdefault(r[0], []).append(r)
    tc_rows = []
    for tc, rs in by_tc.items():
        scen, inp = meta.get(tc, ("", ""))
        if not rs:
            tc_rows.append((tc, scen, inp, 0, 0, "Not run", "", "", ""))
            continue
        okn = sum(1 for r in rs if r[5])
        status = "Pass" if okn == len(rs) else "Fail"
        fails = [r for r in rs if not r[5]]
        detail = "; ".join(f"{r[1]}: {r[6]}"[:160] for r in fails[:5]) + (f" (+{len(fails) - 5} more)" if len(fails) > 5 else "")
        sample = rs[0]
        tc_rows.append((tc, scen, inp, len(rs), okn, status, sample[2][:300], sample[3][:600], detail))
        all_rows += [(tab, r[0], r[1], r[2][:500], r[3][:800], r[4], "Pass" if r[5] else "Fail", r[6][:200]) for r in rs]
    ws = out.create_sheet(tab[:31])
    ws.cell(1, 1, f"{tab} — final round 2026-10-13 (LangGraph pipeline, live models, figures checked against megh_db)").font = Font(bold=True, size=12)
    table(ws, ["TC ID", "Test scenario", "Sheet input", "Conversations run", "Passed", "Result",
               "Example question asked", "Bot's answer (example)", "Failures (if any)"],
          tc_rows, [14, 28, 40, 12, 10, 10, 45, 70, 50], start=3, status_col=6)
    n_tc, n_tcp = len(tc_rows), sum(1 for r in tc_rows if r[5] == "Pass")
    n_cv, n_cvp = len(rows), sum(1 for r in rows if r[5])
    tot["tc"] += n_tc; tot["tcp"] += n_tcp; tot["cv"] += n_cv; tot["cvp"] += n_cvp
    sum_rows.append((tab, n_tc, n_tcp, n_tc - n_tcp, n_cv, n_cvp, "Pass" if n_tcp == n_tc else "Fail",
                     VILLAGES.get(tab, "")))

summary.cell(1, 1, "Megh One AI — final test round, 2026-10-13").font = Font(bold=True, size=14)
summary.cell(2, 1, ("Every test case of 'Test Case Results - 30th Sep 26.xlsx' (General + six schemes) re-run through the "
                    "live LangGraph pipeline on the final code. Each case is asked across the hierarchy the sheet names "
                    "(every district, block, constituency, financial year, scheme / programme, sample villages), and every "
                    "figure is checked against megh_db. A test case passes when every one of its conversations passes."))
summary.cell(2, 1).alignment = Alignment(wrap_text=True, vertical="top")
summary.merge_cells("A2:H2")
summary.row_dimensions[2].height = 60
sum_rows.append(("TOTAL", tot["tc"], tot["tcp"], tot["tc"] - tot["tcp"], tot["cv"], tot["cvp"],
                 "Pass" if tot["tc"] == tot["tcp"] else "Fail", ""))
table(summary, ["Sheet", "Test cases", "Passed", "Failed", "Conversations run", "Conversations passed",
                "Result", "Every village (earlier full-hierarchy run on the final code)"],
      sum_rows, [20, 11, 9, 9, 15, 15, 10, 40], start=4, status_col=7)
r0 = 6 + len(sum_rows)
notes = [
    "Notes",
    "• 'FOCUS' questions: the bot asks Focus Legacy or Focus Plus; the sheet's own scheme was chosen.",
    "• 'CM-ELEVATE' data questions without applications-only words are answered from CM Elevate Legacy (decision of 2026-10-12).",
    "• Questions without a year are answered 'All financial years combined' when the bot asks which year.",
    "• Money is checked in rupees, lakh or crore as stated in the answer (2-decimal rounding allowed).",
    "• Privacy: only the masked views were queried; no beneficiary names or account numbers are in this report.",
    "• Found and fixed in this round: CM Elevate 'Mairang' / 'Nongstoin' (bare names) had stopped offering the block "
    "(regression from the 2026-10-12 constituency change). After the fix CM Elevate OFF-002/007, CM Elevate Legacy "
    "TC-29/31 and Focus Legacy TC-26/28 were re-run in full; those results are the ones shown.",
    "• General TC-017 'cm elevat aplications in east khasi hils' now reads CM Elevate Legacy (decision of 2026-10-12): "
    "the bot asks the year, 'all years' was chosen, and 241 matches megh_db.",
    "• MGNREGA zero cases count as passes when the answer says so (as in the earlier scoring): a 0-vs-0 wages/materials "
    "comparison, and a percentage whose denominator is 0 ('cannot be calculated').",
]
for i, n in enumerate(notes):
    c = summary.cell(r0 + i, 1, n)
    c.font = Font(bold=(i == 0))
ws = out.create_sheet("All conversations")
table(ws, ["Sheet", "TC ID", "Case", "Question(s) asked", "Bot's final answer", "Expected (from megh_db)", "Result", "Check"],
      all_rows, [14, 12, 30, 50, 80, 30, 9, 40], start=1, status_col=7)
out.save(sys.argv[1])
print("written", sys.argv[1], tot)
