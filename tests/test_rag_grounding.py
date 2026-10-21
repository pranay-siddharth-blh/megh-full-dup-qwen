"""RAG upgrade Phase 5 (2026-10-15): the sentence check. After the composer
writes, the sentences the passages do not support are dropped
(rag.ground_answer); a failure of the check keeps the answer."""
import asyncio

import pytest

from app import llm, rag
from app.config import settings

ANSWER = """To register for PMAY-G, these details are captured:

- **Aadhaar number** — for identity verification.
- **Bank account details** — every instalment is paid into it.
- **Income certificate** — proof of annual income.

Confirm the list at your Block office."""


def _fake_model(monkeypatch, reply):
    async def fake_call_model(**kw):
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(llm, "call_model", fake_call_model)


def test_split_units_bullets_are_units_and_prose_splits_at_sentences():
    units = [u for _, u in rag.split_units("MGNREGA gives 100 days. It is demand-driven.\n\n- **Job card** — free.")]
    assert units == ["MGNREGA gives 100 days.", "It is demand-driven.", "- **Job card** — free."]


def test_an_unsupported_bullet_is_dropped_and_the_rest_kept(monkeypatch):
    units = rag.split_units(ANSWER)
    bad = next(i for i, (_, u) in enumerate(units) if "Income certificate" in u)
    _fake_model(monkeypatch, f'{{"unsupported": [{bad}]}}')
    out = asyncio.run(rag.ground_answer(ANSWER, ["Aadhaar number; bank account details."]))
    assert "Income certificate" not in out
    assert "Aadhaar number" in out and "Bank account" in out and "Block office" in out


def test_an_unsupported_sentence_inside_a_paragraph_goes_alone(monkeypatch):
    text = "PMAY-G started in 2016. It gives Rs 1.30 lakh in hill states. It also gives a free car."
    _fake_model(monkeypatch, '{"unsupported": [2]}')
    out = asyncio.run(rag.ground_answer(text, ["passage"]))
    assert out == "PMAY-G started in 2016. It gives Rs 1.30 lakh in hill states."


def test_an_intro_left_with_nothing_under_it_goes_too():
    text = "The documents are:\n\n- **Aadhaar** — identity.\n- **Income certificate** — proof of income."
    units = rag.split_units(text)
    assert rag._drop_units(text, units, {1, 2}) == ""
    assert rag._drop_units(text, units, {2}) == "The documents are:\n\n- **Aadhaar** — identity."


def test_when_every_sentence_is_flagged_the_answer_is_kept(monkeypatch):
    # The check misreading the passages, not a wholly invented answer (eval
    # 2026-10-15, Q132 "56 C&RD Blocks statewide" became "not covered").
    text = "There are 56 C&RD Blocks statewide. Some sources cite 52."
    _fake_model(monkeypatch, '{"unsupported": [0, 1]}')
    assert asyncio.run(rag.ground_answer(text, ["passage"])) == text


@pytest.mark.parametrize("reply", ['{"unsupported": []}', RuntimeError("down"), "garbage", '{"unsupported": [99]}'])
def test_nothing_flagged_or_a_failed_check_keeps_the_answer(monkeypatch, reply):
    _fake_model(monkeypatch, reply)
    assert asyncio.run(rag.ground_answer(ANSWER, ["passage"])) == ANSWER


def test_answer_from_kb_returns_no_answer_when_nothing_is_supported(monkeypatch):
    monkeypatch.setattr(settings, "RAG_GROUNDING_CHECK", True)

    async def fake_retrieve(q, scheme=None, expand=True):
        return [{"score": 0.7, "text": "Aadhaar is needed.", "doc": "d", "heading": "h"}]

    async def fake_compose(prompt):
        return "You need a free car and a pilot licence."

    async def all_bad(answer, passages):
        return ""

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(llm, "call_response_composer", fake_compose)
    monkeypatch.setattr(rag, "ground_answer", all_bad)
    assert asyncio.run(rag.answer_from_kb("documents for PMAY-G?", scheme="PMAY-G")) is None


def test_the_check_is_skipped_when_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "RAG_GROUNDING_CHECK", False)

    async def fake_retrieve(q, scheme=None, expand=True):
        return [{"score": 0.7, "text": "Aadhaar is needed.", "doc": "d", "heading": "h"}]

    async def fake_compose(prompt):
        return "Aadhaar is needed."

    async def must_not_run(answer, passages):
        raise AssertionError("check ran while switched off")

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(llm, "call_response_composer", fake_compose)
    monkeypatch.setattr(rag, "ground_answer", must_not_run)
    assert asyncio.run(rag.answer_from_kb("documents?", scheme="PMAY-G"))["answer"] == "Aadhaar is needed."
