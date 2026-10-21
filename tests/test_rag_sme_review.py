"""The subject-expert review round trip (tests/rag_eval/sme_review.py):
export the workbook, fill OK / FIX / DROP as an expert would, import it back.
Runs on a copy of the test set, never the real one."""
import json
import shutil
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from tests.rag_eval import sme_review as R  # noqa: E402


@pytest.fixture
def copy(tmp_path, monkeypatch):
    ts = tmp_path / "testset.json"
    shutil.copyfile(R.TESTSET, ts)
    monkeypatch.setattr(R, "TESTSET", ts)
    monkeypatch.setattr(R, "HERE", tmp_path)
    monkeypatch.setattr(R, "REVIEW_XLSX", tmp_path / "review.xlsx")
    monkeypatch.setattr(R, "_latest_answers", lambda: {})
    return ts


def _fill(path: Path, decisions: dict[str, tuple[str, str]]):
    wb = openpyxl.load_workbook(path)
    ws = wb["Review"]
    head = [c.value for c in ws[1]]
    ci, cd, cf = head.index("ID") + 1, head.index("Decision (OK / FIX / DROP)") + 1, head.index("Correct answer (for FIX)") + 1
    for r in range(2, ws.max_row + 1):
        qid = ws.cell(r, ci).value
        if qid in decisions:
            ws.cell(r, cd).value, ws.cell(r, cf).value = decisions[qid]
    wb.save(path)


def test_the_workbook_has_instructions_a_dropdown_and_every_question(copy):
    path = R.export()
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["How to review", "Review"]
    ws = wb["Review"]
    n = len(json.loads(copy.read_text(encoding="utf-8")))
    assert ws.max_row - 1 == n
    assert any("OK,FIX,DROP" in (dv.formula1 or "") for dv in ws.data_validations.dataValidation)


def test_ok_fix_drop_are_applied_and_stamped(copy):
    items = json.loads(copy.read_text(encoding="utf-8"))
    pos = [x for x in items if x["kind"] != "negative"]
    neg = [x for x in items if x["kind"] == "negative"]
    ok_id, fix_id, drop_id, neg_fix_id = pos[0]["id"], pos[1]["id"], pos[2]["id"], neg[0]["id"]
    path = R.export()
    _fill(path, {ok_id: ("OK", None), fix_id: ("FIX", "The expert's corrected answer."),
                 drop_id: ("drop", None), neg_fix_id: ("FIX", "Yes - the official rule says so."),
                 pos[3]["id"]: ("MAYBE", None), pos[4]["id"]: ("FIX", None)})
    r = R.import_review(path, "Test Expert")
    after = {x["id"]: x for x in json.loads(copy.read_text(encoding="utf-8"))}
    assert r["ok"] == 1 and r["fixed"] == 2 and r["dropped"] == 1
    assert len(r["problems"]) == 2                       # MAYBE, and FIX without an answer
    assert drop_id not in after and len(after) == len(items) - 1
    assert after[ok_id]["reviewed"] and after[ok_id]["reviewed_by"] == "Test Expert"
    assert after[fix_id]["expected_answer"] == "The expert's corrected answer."
    assert after[fix_id]["expected_answer_model"] == pos[1]["expected_answer"]
    assert after[neg_fix_id]["kind"] == "real" and after[neg_fix_id]["evidence"] == ""
    assert not after[pos[3]["id"]].get("reviewed") and not after[pos[4]["id"]].get("reviewed")
    assert Path(r["backup"]).exists()


def test_a_reviewed_question_is_marked_in_the_next_export(copy):
    items = json.loads(copy.read_text(encoding="utf-8"))
    path = R.export()
    _fill(path, {items[0]["id"]: ("OK", None)})
    R.import_review(path, "Test Expert")
    ws = openpyxl.load_workbook(R.export())["Review"]
    head = [c.value for c in ws[1]]
    marked = [ws.cell(r, head.index("Already reviewed") + 1).value for r in range(2, ws.max_row + 1)]
    assert sum(1 for m in marked if m and "Test Expert" in m) == 1
