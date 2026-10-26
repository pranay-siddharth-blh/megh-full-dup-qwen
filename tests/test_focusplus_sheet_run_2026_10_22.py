"""Focus + sheet re-test 2026-10-22 (raw_uc/Focus+ Test Case Observation.xlsx, report
new_docs/Focus_Plus_Test_Report_2026-10-22.md): regression tests for FOCUS-019 and FOCUS-004,
against the real functions.

1. FOCUS-019 (KI-360): "Give me the status breakdown for 12.5K batch." was refused 5/5 by the
   guardrail model ("I can't do things on your behalf"), "Break down the 12.5K batch by status"
   bounced by the edge whitelist gate, "12.5 K" read as no scheme. Only "... for THE 12.5K
   batch" passed.
2. FOCUS-004 (KI-361): "Shillong Municipal Board" -> the generator wrote 'SHILLONG-MUNICIPAL_BOARD',
   the lgd_block fallback took it, the resolved-block check refused it 4 times: "couldn't build
   a working query" (5/5). "Baghmara MB" answered the rural Baghmara block; "William Nagar
   Municipal Board" asked the constituency pause and then said 0.

Offline: the Focus Plus block list is stubbed with the 50 names curated.v_focus_plus stores."""
import asyncio

import pytest

from app import edge
from app import pipeline as p
from app import sql_ast

# the urban bodies and their rural namesakes, as UPPER(block_name_raw) stores them
FP_RAW_BLOCKS = {
    "BAGHMARA", "BAGHMARA-MUNICIPAL BOARD", "RESUBELPARA", "RESUBELPARA-MUNICIPAL BOARD",
    "SHILLONG-MUNICIPAL BOARD", "TURA MUNICIPAL BOARD-MUNICIPAL BOARD", "WILLIAMNAGAR-MUNICIPAL BOARD",
    "SELSELLA", "DAMBO RONGJENG", "SHELLA BHOLAGANJ", "KHATARSHNONG LAITKROH", "SAMANDA", "NAN",
}

BATCH_QUESTIONS = [
    "Give me the status breakdown for 12.5K batch.", "Give me the status breakdown for 12.5k batch",
    "Give me the status breakdown for 12.5 K batch", "Give me status breakdown of 12.5K batch",
    "status breakdown for 12.5K batch", "Break down the 12.5K batch by status",
    "Give me the status split of 12.5K batch", "Please give the status wise breakdown for 12.5K batch",
    "show status wise count for 12.5K batch", "12.5K batch status breakdown",
    "Give me the status breakdown for 93K batch.", "Give me the status breakdown for 93 K batch",
    "Show the status wise breakdown for batch 93K",
]


@pytest.fixture
def raw_blocks(monkeypatch):
    monkeypatch.setattr(p, "_FOCUSPLUS_RAW_BLOCKS", set(FP_RAW_BLOCKS))


# ── 1. FOCUS-019: a batch status breakdown is a data question ───────────────
@pytest.mark.parametrize("q", BATCH_QUESTIONS)
def test_batch_status_breakdown_overrules_a_scope_refusal(q):
    assert p._overrules_scope_verdict(q)


@pytest.mark.parametrize("q", BATCH_QUESTIONS)
def test_batch_status_breakdown_is_focus_plus(q):
    assert p._infer_scheme_from_terms(q) == ["Focus Plus"]


@pytest.mark.parametrize("q", BATCH_QUESTIONS)
def test_batch_status_breakdown_passes_the_edge_gate(q):
    assert edge.detect_edge_case(q) is None


@pytest.mark.parametrize("q", ["Give me the status breakdown for 12.5 K batch", "status breakdown for 93 K batch"])
def test_spaced_batch_label_reaches_the_fixed_status_query(q):
    sql, params, _ = p._fp_status_cohort_query(q, ["Focus Plus"], {})
    assert "fp-status-cohort" in sql and params[0] in (["12.5K"], ["93K"])


@pytest.mark.parametrize("q", ["book a payment of 12.5K", "write a poem about the 12.5K batch",
                               "apply for me in the 12.5K batch", "transfer 93K to my account"])
def test_task_and_content_requests_are_still_the_models_call(q):
    assert not p._overrules_scope_verdict(q)


@pytest.mark.parametrize("q", ["tell me a joke", "who is elon musk", "split the bill"])
def test_off_topic_still_off_topic(q):
    assert edge.detect_edge_case(q) is not None


# ── 2. FOCUS-004: municipal boards ─────────────────────────────────────────
def _fix(sql):
    return asyncio.run(p._focusplus_lgd_only_block(["Focus Plus"], sql))


def test_mistyped_board_literal_snaps_to_the_stored_block(raw_blocks):
    out = _fix("SELECT SUM(amount_disbursed) FROM curated.v_focus_plus "
               "WHERE UPPER(block_name_raw) = 'SHILLONG-MUNICIPAL_BOARD'")
    assert sql_ast.filter_values(out, "block_name_raw") == ["SHILLONG-MUNICIPAL BOARD"]
    assert not sql_ast.references_column(out, "lgd_block")


@pytest.mark.parametrize("typed, stored", [("SHILLONG MUNICIPAL BOARD", "SHILLONG-MUNICIPAL BOARD"),
                                           ("WILLIAMNAGAR MUNICIPAL_BOARD", "WILLIAMNAGAR-MUNICIPAL BOARD"),
                                           ("DAMBO-RONGJENG", "DAMBO RONGJENG")])
def test_same_letters_are_the_same_block(raw_blocks, typed, stored):
    out = _fix(f"SELECT COUNT(*) FROM curated.v_focus_plus WHERE UPPER(block_name_raw) = '{typed}'")
    assert sql_ast.filter_values(out, "block_name_raw") == [stored]


def test_rural_block_and_its_board_stay_apart(raw_blocks):
    for name in ("BAGHMARA", "BAGHMARA-MUNICIPAL BOARD"):
        out = _fix(f"SELECT COUNT(*) FROM curated.v_focus_plus WHERE UPPER(block_name_raw) = '{name}'")
        assert sql_ast.filter_values(out, "block_name_raw") == [name]


def test_lgd_only_block_still_moves_to_lgd_block(raw_blocks):
    out = _fix("SELECT COUNT(*) FROM curated.v_focus_plus WHERE UPPER(block_name_raw) = 'ADOKGRE'")
    assert sql_ast.references_column(out, "lgd_block")


@pytest.mark.parametrize("mention, stored", [
    ("Baghmara MB", "BAGHMARA-MUNICIPAL BOARD"), ("Baghmara-MB", "BAGHMARA-MUNICIPAL BOARD"),
    ("Resubelpara MB", "RESUBELPARA-MUNICIPAL BOARD"), ("Shillong MB", "SHILLONG-MUNICIPAL BOARD"),
    ("Shillong Municipal Board", "SHILLONG-MUNICIPAL BOARD"), ("Tura MB", "TURA MUNICIPAL BOARD-MUNICIPAL BOARD"),
    ("William Nagar Municipal Board", "WILLIAMNAGAR-MUNICIPAL BOARD"),
    ("Williamnagar Municipal Board", "WILLIAMNAGAR-MUNICIPAL BOARD"),
])
def test_urban_body_mention_is_the_focus_plus_board(raw_blocks, mention, stored):
    assert asyncio.run(p._cm_elevate_block_from_mention(mention, ["Focus Plus"])) == stored


def test_plain_block_mention_is_not_turned_into_a_board(raw_blocks):
    assert asyncio.run(p._cm_elevate_block_from_mention("Baghmara", ["Focus Plus"])) == "BAGHMARA"
