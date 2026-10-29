"""RAG upgrade Phase 4 (2026-10-15): better questions.

- Search with other wordings of the question too (rag._alt_queries), merged
  by rank (rag._fuse); any failure searches with the question alone.
- Khasi / Garo (the KHA / GAR buttons) are translated to English before the
  pipeline (app/translate.py); English, unknown languages and failures pass
  the question through unchanged."""
import asyncio

import pytest

from app import llm, rag, translate
from app.config import settings
from app.routers import query as router


def _fake_model(monkeypatch, reply, calls=None):
    async def fake_call_model(**kw):
        if calls is not None:
            calls.append(kw)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(llm, "call_model", fake_call_model)


# ── other wordings ──────────────────────────────────────────────────────────

def test_alt_queries_parsed_deduplicated_and_capped(monkeypatch):
    monkeypatch.setattr(settings, "RAG_MULTI_QUERY", 2)
    _fake_model(monkeypatch, '{"queries": ["documents required PMAY-G registration", "documents?", '
                             '"PMAY-G documents required for registration", "third one"]}')
    out = asyncio.run(rag._alt_queries("documents?", "PMAY-G"))
    assert out == ["documents required PMAY-G registration", "PMAY-G documents required for registration"]


@pytest.mark.parametrize("reply", [RuntimeError("gateway down"), "not json at all", '{"queries": "x"}'])
def test_alt_queries_failure_searches_the_question_alone(monkeypatch, reply):
    monkeypatch.setattr(settings, "RAG_MULTI_QUERY", 2)
    _fake_model(monkeypatch, reply)
    assert asyncio.run(rag._alt_queries("documents?", "PMAY-G")) == [] or reply == '{"queries": "x"}'


def test_alt_queries_off(monkeypatch):
    monkeypatch.setattr(settings, "RAG_MULTI_QUERY", 0)
    calls = []
    _fake_model(monkeypatch, '{"queries": ["a b c"]}', calls)
    assert asyncio.run(rag._alt_queries("documents?", "PMAY-G")) == [] and not calls


def test_fuse_puts_pieces_several_wordings_find_first_and_keeps_the_best_score():
    a = {"doc": "d", "heading": "A", "text": "a", "score": 0.6}
    b = {"doc": "d", "heading": "B", "text": "b", "score": 0.7}
    c = {"doc": "d", "heading": "C", "text": "c", "score": 0.5}
    fused = rag._fuse([[b, a], [a, c], [a, dict(b, score=0.9)]])
    assert [p["heading"] for p in fused] == ["A", "B", "C"]
    assert fused[1]["score"] == 0.9


def test_retrieve_searches_every_wording(monkeypatch):
    monkeypatch.setattr(settings, "RAG_MULTI_QUERY", 2)
    seen = []

    async def keep_order(q, texts):
        return [(i, 0.5) for i in range(len(texts))]

    monkeypatch.setattr(llm, "call_reranker", keep_order)

    async def alts(q, scheme):
        return ["alt one", "alt two"]

    async def embed(texts):
        return [[0.1, 0.2] for _ in texts]

    async def search_one(vec, text, k, scheme):
        seen.append(text)
        return [{"doc": "d", "heading": text, "text": text, "score": 0.7}]

    monkeypatch.setattr(rag, "_alt_queries", alts)
    monkeypatch.setattr(llm, "call_embedding", embed)
    monkeypatch.setattr(rag, "_search_one", search_one)
    out = asyncio.run(rag.retrieve("documents?", scheme="PMAY-G"))
    assert seen == ["documents?", "alt one", "alt two"] and len(out) == 3


def test_the_term_scheme_helper_does_not_expand(monkeypatch):
    called = []

    async def alts(q, scheme):
        called.append(q)
        return ["x"]

    async def texts():
        return {}

    async def fake_retrieve(q, scheme=None, expand=True):
        assert expand is False
        return []

    monkeypatch.setattr(rag, "_alt_queries", alts)
    monkeypatch.setattr(rag, "_kb_texts_by_scheme", texts)
    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    asyncio.run(rag.best_kb_scheme("what is the block office?"))
    assert not called


# ── Khasi / Garo ────────────────────────────────────────────────────────────

def test_khasi_is_translated(monkeypatch):
    monkeypatch.setattr(settings, "TRANSLATE_ENABLED", True)
    calls = []
    _fake_model(monkeypatch, '{"english": "How do I apply for PMAY-G?"}', calls)
    out = asyncio.run(translate.to_english("Kumno nga lah ban apply ia ka PMAY-G?", "kha"))
    assert out == "How do I apply for PMAY-G?"
    assert "Khasi" in calls[0]["prompt"] and "katno" in calls[0]["prompt"]


def test_garo_is_translated(monkeypatch):
    monkeypatch.setattr(settings, "TRANSLATE_ENABLED", True)
    calls = []
    _fake_model(monkeypatch, '{"english": "How do I apply for PMAY-G?"}', calls)
    assert asyncio.run(translate.to_english("PMAY-G-ko maidake apply ka·gen?", "gar")) == "How do I apply for PMAY-G?"
    assert "Garo" in calls[0]["prompt"]


@pytest.mark.parametrize("lang", ["en", "", None, "hi", "xx"])
def test_english_or_unknown_language_is_never_sent_for_translation(monkeypatch, lang):
    calls = []
    _fake_model(monkeypatch, '{"english": "WRONG"}', calls)
    assert asyncio.run(translate.to_english("Who is eligible for PMAY-G?", lang)) == "Who is eligible for PMAY-G?"
    assert not calls


@pytest.mark.parametrize("reply", [RuntimeError("down"), "garbage", '{"english": ""}', '{"english": "' + "x" * 900 + '"}'])
def test_a_failed_translation_answers_the_question_as_typed(monkeypatch, reply):
    monkeypatch.setattr(settings, "TRANSLATE_ENABLED", True)
    _fake_model(monkeypatch, reply)
    assert asyncio.run(translate.to_english("Aiu ka MGNREGA?", "kha")) == "Aiu ka MGNREGA?"


def test_translation_switch(monkeypatch):
    monkeypatch.setattr(settings, "TRANSLATE_ENABLED", False)
    calls = []
    _fake_model(monkeypatch, '{"english": "What is MGNREGA?"}', calls)
    assert asyncio.run(translate.to_english("Aiu ka MGNREGA?", "kha")) == "Aiu ka MGNREGA?" and not calls


def test_the_request_carries_the_language_button():
    assert router.QueryRequest(question="Aiu ka MGNREGA?", language="kha").language == "kha"
    assert router.QueryRequest(question="What is MGNREGA?").language == "en"
