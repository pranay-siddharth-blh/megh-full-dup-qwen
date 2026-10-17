"""
Subject-expert review of the RAG test set (2026-10-15).

Until an expert checks it, "correct" in tests/rag_eval is judged against
expected answers the model wrote from the documents. This makes the review a
short, guided job and folds the expert's decisions back into testset.json.

    python tests/rag_eval/sme_review.py export
        -> reference_documents/RAG_Test_Set_SME_Review.xlsx
           Sheet "How to review": the instructions.
           Sheet "Review": one row per question — the question, the expected
           answer, the exact quote it rests on, the document and section, and
           the chatbot's latest answer (from the newest results file), with a
           Decision column (OK / FIX / DROP, a dropdown) and a "Correct answer"
           column for FIX. Questions already reviewed are marked.

    python tests/rag_eval/sme_review.py import <filled workbook.xlsx> --reviewer "Name"
        OK   -> the expected answer is confirmed
        FIX  -> the expected answer becomes the expert's "Correct answer"
        DROP -> the question is removed from the test set
        blank-> left as it was (not reviewed)
        Every reviewed question is stamped reviewed / reviewed_by / reviewed_on,
        so run_eval.py can report an "expert-checked" score next to the full one.
        A copy of the old testset.json is kept as testset.before_review_<date>.json.
"""
import argparse
import datetime as dt
import glob
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TESTSET = HERE / "testset.json"
REVIEW_XLSX = ROOT / "reference_documents" / "RAG_Test_Set_SME_Review.xlsx"

KIND_LABEL = {"doc": "Written from the documents", "real": "Real officer question",
              "negative": "Should be 'not covered'"}

INSTRUCTIONS = [
    ("What this is", "A test of the Megh One AI chatbot's scheme-knowledge answers. Each row is one question "
                     "with the answer we expect. Your check makes the chatbot's accuracy score trustworthy."),
    ("What to do", "On the 'Review' sheet, read the Question and the Expected answer. Use the Evidence "
                   "(an exact quote from the document) and Document / Section if you want to check the source."),
    ("Decision = OK", "The expected answer is correct and complete enough for an officer."),
    ("Decision = FIX", "The expected answer is wrong or incomplete. Write the correct answer in 'Correct answer'."),
    ("Decision = DROP", "The question should not be in the test (unclear, unrealistic, duplicate, or the "
                        "documents themselves are out of date)."),
    ("Leave blank", "If you are not sure or have not checked a row yet — it stays as it is."),
    ("'Should be not covered' rows", "These ask something the documents do NOT answer. OK = right, the chatbot "
                                     "should say it is not covered. FIX = the documents (or official rules) do answer "
                                     "it — write that answer in 'Correct answer'."),
    ("Chatbot's latest answer", "For information only — what the chatbot said last time. If you see it is "
                                "wrong, please also note it in 'Comment'."),
    ("Time", "About 1 minute per row; 188 rows ≈ 2-3 hours. Partial reviews are fine — send what you have."),
    ("When done", "Save the file and send it back. It is read in with: "
                  "python tests/rag_eval/sme_review.py import <file> --reviewer \"Your name\""),
]


def _latest_answers() -> dict[str, dict]:
    files = sorted(glob.glob(str(HERE / "results" / "20*.json")))
    for f in reversed(files):
        try:
            rows = json.loads(Path(f).read_text(encoding="utf-8")).get("rows") or []
        except (OSError, ValueError):
            continue
        if rows and any(r.get("answer") for r in rows):
            return {r["id"]: r for r in rows}
    return {}


def export() -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    items = json.loads(TESTSET.read_text(encoding="utf-8"))
    latest = _latest_answers()
    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="5B2C8F")
    head_font = Font(bold=True, color="FFFFFF")
    wrap = Alignment(vertical="top", wrap_text=True)

    ins = wb.active
    ins.title = "How to review"
    ins.append(["Step", "What to do"])
    for r in INSTRUCTIONS:
        ins.append(list(r))
    for c in ins[1]:
        c.fill, c.font = head_fill, head_font
    for row in ins.iter_rows(min_row=2):
        for c in row:
            c.alignment = wrap
        row[0].font = Font(bold=True)
    ins.column_dimensions["A"].width = 28
    ins.column_dimensions["B"].width = 110

    ws = wb.create_sheet("Review")
    header = ["ID", "Scheme", "Type", "Question", "Expected answer", "Evidence (exact quote from the document)",
              "Document", "Section", "Chatbot's latest answer", "Decision (OK / FIX / DROP)",
              "Correct answer (for FIX)", "Comment", "Already reviewed"]
    ws.append(header)
    for c in ws[1]:
        c.fill, c.font, c.alignment = head_fill, head_font, Alignment(vertical="center", wrap_text=True)
    for it in sorted(items, key=lambda x: (x["scheme"], x["kind"], x["id"])):
        bot = latest.get(it["id"], {})
        ws.append([it["id"], it["scheme"], KIND_LABEL.get(it["kind"], it["kind"]), it["question"],
                   it.get("expected_answer", ""), it.get("evidence", ""), it.get("gold_doc", ""),
                   it.get("gold_heading", ""), (bot.get("answer") or "(said not covered)")[:1500] if bot else "",
                   "", "", it.get("review_comment", ""),
                   f"{it.get('reviewed_by', '')} {it.get('reviewed_on', '')}".strip() if it.get("reviewed") else ""])
    widths = [7, 12, 18, 42, 50, 40, 26, 26, 55, 14, 45, 30, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = wrap
    decide = PatternFill("solid", fgColor="FFF7D6")
    for r in range(2, ws.max_row + 1):
        for col in (10, 11, 12):
            ws.cell(r, col).fill = decide
    dv = DataValidation(type="list", formula1='"OK,FIX,DROP"', allow_blank=True,
                        error="Choose OK, FIX or DROP (or leave blank).", errorTitle="Decision")
    ws.add_data_validation(dv)
    dv.add(f"J2:J{ws.max_row}")
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = ws.dimensions
    REVIEW_XLSX.parent.mkdir(exist_ok=True)
    wb.save(REVIEW_XLSX)
    return REVIEW_XLSX


def import_review(path: Path, reviewer: str) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb.active
    head = [str(c.value or "").strip() for c in ws[1]]

    def col(prefix: str) -> int:
        for i, h in enumerate(head):
            if h.lower().startswith(prefix.lower()):
                return i
        raise SystemExit(f"column starting '{prefix}' not found in {path.name}")

    c_id, c_dec, c_fix, c_com = col("ID"), col("Decision"), col("Correct answer"), col("Comment")
    decisions: dict[str, tuple[str, str, str]] = {}
    problems: list[str] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        qid = str(row[c_id] or "").strip()
        dec = str(row[c_dec] or "").strip().upper()
        if not qid or not dec:
            continue
        if dec not in ("OK", "FIX", "DROP"):
            problems.append(f"{qid}: decision '{dec}' is not OK / FIX / DROP — skipped")
            continue
        fix = str(row[c_fix] or "").strip()
        if dec == "FIX" and not fix:
            problems.append(f"{qid}: FIX without a correct answer — skipped")
            continue
        decisions[qid] = (dec, fix, str(row[c_com] or "").strip())

    items = json.loads(TESTSET.read_text(encoding="utf-8"))
    today = dt.date.today().isoformat()
    backup = HERE / f"testset.before_review_{today}.json"
    if not backup.exists():
        shutil.copyfile(TESTSET, backup)
    kept, counts = [], {"OK": 0, "FIX": 0, "DROP": 0}
    known = {it["id"] for it in items}
    for qid in decisions:
        if qid not in known:
            problems.append(f"{qid}: not in testset.json — skipped")
    for it in items:
        d = decisions.get(it["id"])
        if not d:
            kept.append(it)
            continue
        dec, fix, comment = d
        counts[dec] += 1
        if dec == "DROP":
            continue
        if dec == "FIX":
            it["expected_answer_model"] = it.get("expected_answer", "")
            it["expected_answer"] = fix
            if it["kind"] == "negative":
                # The documents do answer it after all: it is an answerable
                # question now, judged on the expert's answer (no quote to find).
                it["kind"] = "real"
                it["evidence"] = ""
        it.update(reviewed=True, reviewed_by=reviewer, reviewed_on=today, review_decision=dec)
        if comment:
            it["review_comment"] = comment
        kept.append(it)
    TESTSET.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": counts["OK"], "fixed": counts["FIX"], "dropped": counts["DROP"],
            "questions_now": len(kept), "reviewed_total": sum(1 for x in kept if x.get("reviewed")),
            "backup": str(backup), "problems": problems}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    im = sub.add_parser("import")
    im.add_argument("file")
    im.add_argument("--reviewer", required=True)
    a = ap.parse_args()
    if a.cmd == "export":
        print("wrote", export())
    else:
        r = import_review(Path(a.file), a.reviewer)
        for p in r.pop("problems"):
            print("  !", p)
        print(json.dumps(r, indent=1))


if __name__ == "__main__":
    sys.exit(main())
