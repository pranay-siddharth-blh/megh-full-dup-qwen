"""KI-573 (2026-10-29): "Statewide, all financial years combined, how many PMAY-G houses have
received no release at all?" was answered with the statewide summary (houses, sanctioned,
released). The fixed-shape path's "none" words knew "received no amount / money / fund /
payment / instalment" but not "received no release", so the question fell through to
houses + released. Drives the real _pmay_metrics and _pmay_facts_query (no model, no DB)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402

ALL = " across all financial years"


@pytest.mark.parametrize("q", [
    "Statewide, all financial years combined, how many PMAY-G houses have received no release at all?",
    "How many PMAY-G houses have received no release?",
    "How many beneficiaries in Lempluh got no release yet?",
    "How many houses have been paid no releases so far in Ri Bhoi?",
])
def test_received_no_release_is_the_none_count(q):
    assert p._pmay_metrics(q, False) == ["none"]
    assert p._pmay_metrics(q + ALL, False) == ["none"]


@pytest.mark.parametrize("q,expected", [
    # the wordings that already worked keep working
    ("How many beneficiaries in Lempluh have not received any amount?", ["none"]),
    ("How many beneficiaries have received no amount in Lempluh?", ["none"]),
    ("How many houses with no release has been received in Lempluh?", ["none"]),
    # a plain release question is still the released amount, not the "none" count
    ("How much has been released in Ri Bhoi?", ["released"]),
    ("How many houses were sanctioned and how much was released in Ri Bhoi during 2019-20?",
     ["houses", "sanctioned", "released"]),
])
def test_neighbouring_wordings_unchanged(q, expected):
    assert p._pmay_metrics(q, False) == expected


def test_statewide_question_builds_the_no_release_count():
    q = "Statewide, all financial years combined, how many PMAY-G houses have received no release at all?"
    spec = p._pmay_facts_query(q, ["PMAY-G"], {})
    assert spec is not None and spec["dim"] == "state"
    assert spec["metrics"] == ["none"]
    assert "AS no_release" in spec["sql"]
