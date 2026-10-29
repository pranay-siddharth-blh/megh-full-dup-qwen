"""B2 (RAG plan) — the scheme from its vocabulary when no scheme is named.

Measured 2026-10-29 on tests/scheme_vocab/labels.json (32 own wordings): 27/32. The
five misses each used a word only one scheme's data holds, so the bot asked "which
scheme?": "mandays" (MGNREGA's catalogue synonym), "unskilled labour" (only MGNREGA
holds unskilled_wage_exp), "LAMPS" (a Focus Legacy pg_entity_type), "level 2" (only
v_cm_elevate has current_level), "loan" (only v_cm_elevate_disbursement has loan
columns; checked in information_schema). After: 32/32. Generic words still ask.

OFFLINE: calls the real _infer_scheme_from_terms on the shipped label set.
    .venv/Scripts/python.exe -m pytest tests/test_scheme_vocabulary_b2_2026_10_29.py -q
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402

LABELS = json.loads((Path(__file__).resolve().parent / "scheme_vocab" / "labels.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("q,expected", LABELS)
def test_the_label_set(q, expected):
    got = p._infer_scheme_from_terms(q)
    assert (got[0] if got else "ASK") == expected


@pytest.mark.parametrize("q,scheme", [
    ("How many man-days were generated in Ri Bhoi?", "MGNREGA"),
    ("Unskilled workers employed in Tura block", "MGNREGA"),
    ("How many LAMPS were paid in 2022-23?", "Focus Legacy"),
    ("Applications at level 3 in Ri Bhoi", "CM Elevate"),
    ("Total loans disbursed in West Garo Hills", "CM Elevate Legacy"),
])
def test_the_new_words(q, scheme):
    assert p._infer_scheme_from_terms(q) == [scheme]


@pytest.mark.parametrize("q", [
    "How many beneficiaries are there in Ri Bhoi?",       # every scheme has beneficiaries
    "Total amount disbursed in West Garo Hills",
    "district level figures for payments",                 # "level" with no number
    "Loans and person-days in Ri Bhoi",                    # two schemes' words: still asks
])
def test_shared_or_mixed_words_still_ask(q):
    assert p._infer_scheme_from_terms(q) is None
