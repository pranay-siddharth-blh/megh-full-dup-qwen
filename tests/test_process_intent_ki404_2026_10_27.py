"""KI-404 — "How does MGNREGA job card registration work?" tripped the "job card"
DATA cue, matched no knowledge cue and went down the data path (year chips, then an
area question; live 2026-10-24, same on 384 and 1024 dims). A "how does / is <X>
work / get issued / released" or "process / procedure / steps for" question asks how
the scheme works: KNOWLEDGE, unless it counts ("how many / how much") or names a year.

OFFLINE: calls the real `classify_intent`; the model is stubbed to an unusable reply,
so a fall-through shows as the code's DATA default.
    .venv/Scripts/python.exe -m pytest tests/test_process_intent_ki404_2026_10_27.py -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm, pipeline as p  # noqa: E402


@pytest.fixture
def no_model(monkeypatch):
    async def classifier(*_a, **_kw):
        return '{"intent": "neither"}'
    monkeypatch.setattr(llm, "call_classifier", classifier)


def _intent(q):
    return asyncio.new_event_loop().run_until_complete(p.classify_intent(q))


@pytest.mark.parametrize("q", [
    "How does MGNREGA job card registration work?",
    "How does PMAY-G house sanction work?",
    "How is a job card issued under MGNREGA?",
    "How are PMAY-G instalments released?",
    "How is the wage rate calculated under MGNREGA?",
    "What is the process to get a job card in MGNREGA?",
    "Steps to apply for CM Elevate",
])
def test_how_it_works_is_knowledge(no_model, q):
    assert _intent(q) == "KNOWLEDGE"


@pytest.mark.parametrize("q", [
    "How many job cards were issued in Ri Bhoi in 2023-24?",
    "How much wages were paid in Ri Bhoi in 2023-24?",
    "How many houses were sanctioned in Ri Bhoi?",
    "How does job card issuance in 2023-24 compare with 2022-23?",
    "How does Ri Bhoi compare with East Khasi Hills on person-days?",
    "How did people apply to CM Elevate?",
])
def test_figures_stay_data(no_model, q):
    assert _intent(q) == "DATA"
