"""What-is questions about scheme terms (user report 2026-10-14).

"What is Gram Panchayat?" was refused as general knowledge, "What is SECC?"
after an MGNREGA answer searched MGNREGA only ("not mentioned" — SECC is
PMAY-G's), and "What is DBT?" was rewritten into a data question about MGNREGA
bank details. A self-contained what-is question about a term the schemes use is
a knowledge question, answered from the scheme whose documents hold the term."""
import asyncio

import pytest

from app import edge, guardrails, llm, pipeline, rag
from app.config import settings


def _fake_model(monkeypatch, reply):
    async def fake_call_model(**kw):
        return reply
    monkeypatch.setattr(settings, "GUARDRAIL_MODEL_ENABLED", True)
    monkeypatch.setattr(llm, "call_model", fake_call_model)


TERM_QUESTIONS = [
    "What is Gram Panchayat?", "What is Gram Sabha?", "What is SECC?", "What is DBT?",
    "what is a muster roll", "meaning of social audit", "What is a job card?",
    "Explain producer group", "What is Awaas+?", "who is the Ombudsperson?",
    "What is a self help group?", "what is PFMS",
]
NOT_TERM_QUESTIONS = [
    "what is the capital of France?", "who is the prime minister of India?",
    "what is the weather in Shillong?", "write a poem about the Gram Panchayat",
]


@pytest.mark.parametrize("q", TERM_QUESTIONS)
def test_a_scheme_term_question_is_not_refused_as_general(monkeypatch, q):
    _fake_model(monkeypatch, '{"verdict": "OUT_OF_SCOPE", "category": "general"}')
    assert asyncio.run(guardrails.check_model(q)) is None


@pytest.mark.parametrize("q", NOT_TERM_QUESTIONS[:3])
def test_real_general_knowledge_is_still_refused(monkeypatch, q):
    _fake_model(monkeypatch, '{"verdict": "OUT_OF_SCOPE", "category": "general"}')
    v = asyncio.run(guardrails.check_model(q))
    assert v is not None and v.category == "scope_general"


def test_content_and_harm_verdicts_are_never_overruled_by_a_term(monkeypatch):
    _fake_model(monkeypatch, '{"verdict": "OUT_OF_SCOPE", "category": "content"}')
    assert asyncio.run(guardrails.check_model("write a poem about the Gram Panchayat")) is not None
    _fake_model(monkeypatch, '{"verdict": "UNSAFE", "category": "illegal"}')
    assert asyncio.run(guardrails.check_model("what is a fake job card and how to make one")) is not None


@pytest.mark.parametrize("q", [x for x in TERM_QUESTIONS if "Awaas" not in x])
def test_term_questions_are_self_contained(q):
    assert pipeline._is_scheme_term_question(q), q


def test_awaas_names_pmay_g_so_it_takes_the_named_scheme_path():
    assert pipeline._named_schemes("What is Awaas+?") == ["PMAY-G"]
    assert not pipeline._is_scheme_term_question("What is Awaas+?")


@pytest.mark.parametrize("q", [
    "what is its role in PMAY-G?",                 # names a scheme
    "What is MGNREGA?",                            # a scheme overview, handled as before
    "what is it?",                                 # points back at the previous turn
    "how many job cards were issued in Ri Bhoi in 2023-24 by each block?",
    "what is the capital of France?",
])
def test_not_a_self_contained_term_question(q):
    assert not pipeline._is_scheme_term_question(q), q


@pytest.mark.parametrize("q", ["What is DBT?", "What is SECC?", "What is Gram Sabha?", "what is PFMS"])
def test_terms_count_as_scheme_vocabulary_at_the_edge(q):
    assert edge.has_domain_vocabulary(q), q


def test_the_term_picks_the_scheme_whose_documents_hold_it(monkeypatch):
    texts = {"MGNREGA": ["gram sabha recommends works", "job card issued by the gram panchayat"],
             "PMAY-G": ["eligible households come from secc 2011", "the secc list is verified"],
             "CM Elevate": ["capital subsidy of 35% to 75%"]}

    async def fake_texts():
        return texts

    async def no_vector(*a, **k):
        raise AssertionError("the literal term decides; no vector search needed")

    monkeypatch.setattr(rag, "_kb_texts_by_scheme", fake_texts)
    monkeypatch.setattr(rag, "retrieve", no_vector)
    assert asyncio.run(rag.best_kb_scheme("What is SECC?")) == "PMAY-G"
    assert asyncio.run(rag.best_kb_scheme("What is Gram Sabha?")) == "MGNREGA"


def test_a_tie_or_unknown_term_falls_back_to_meaning_search(monkeypatch):
    async def fake_texts():
        return {"MGNREGA": ["the block office"], "PMAY-G": ["the block office"]}

    async def fake_retrieve(question, scheme=None, expand=True):
        return [{"score": 0.8 if scheme == "PMAY-G" else 0.6, "text": ""}]

    monkeypatch.setattr(rag, "_kb_texts_by_scheme", fake_texts)
    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    assert asyncio.run(rag.best_kb_scheme("what is the block office?")) == "PMAY-G"
    assert asyncio.run(rag.best_kb_scheme("what is the block office?", exclude="PMAY-G")) == "MGNREGA"


def test_distinctive_terms_drop_question_words():
    assert rag._distinctive_terms("What is SECC?") == ["secc"]
    assert rag._distinctive_terms("What is the meaning of Gram Sabha?") == ["gram", "sabha"]


@pytest.mark.parametrize("answer", [
    "SECC is not mentioned in the published scheme information.",
    'The published scheme information does not contain any information regarding "SECC".',
    "The scheme information doesn't mention a helpline.",
])
def test_not_mentioned_answers_count_as_a_refusal(answer):
    assert rag._is_whole_refusal(answer)


def test_a_real_answer_with_a_caveat_is_not_a_refusal():
    assert not rag._is_whole_refusal(
        "SECC is the Socio-Economic Caste Census, 2011. The list does not contain urban households.")
