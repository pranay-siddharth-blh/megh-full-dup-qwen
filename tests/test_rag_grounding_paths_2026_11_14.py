"""RAG plumbing, 14 Nov 2026 (offline; every model and vector call is faked).

  - the multi-scheme knowledge answer runs the sentence check (it never did)
  - the DATA path's knowledge fallback searches the scheme the question names (it searched every scheme at once)
  - the knowledge bases come from the scheme registry; a start-up check names a scheme with no documents
"""
from __future__ import annotations

import asyncio

from app import pipeline as p
from app import rag
from app.config import settings


def _chunks(scheme):
    return [{"text": f"{scheme} gives 100 days of work to a household.", "doc": "d", "heading": "h", "score": 0.9}]


def test_multi_scheme_answer_is_grounded(monkeypatch):
    seen = {}

    async def fake_retrieve(q, scheme=None, **_):
        return _chunks(scheme)

    async def fake_compose(prompt):
        return ("- **MGNREGA** — 100 days of work a year.\n"
                "- **PMAY-G** — a grant of 9,99,999 rupees per house.")

    async def fake_ground(answer, passages, question=""):
        seen["passages"] = passages
        return answer.split("\n")[0]          # the check drops the invented PMAY-G line

    monkeypatch.setattr(settings, "RAG_GROUNDING_CHECK", True)
    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag.llm, "call_response_composer", fake_compose)
    monkeypatch.setattr(rag, "ground_answer", fake_ground)
    out = asyncio.run(rag.answer_from_kb_multi("what do they give", ["MGNREGA", "PMAY-G"]))
    assert out and "9,99,999" not in out["answer"] and "100 days" in out["answer"]
    assert len(seen["passages"]) == 2          # both schemes' passages were the evidence


def test_multi_scheme_answer_emptied_by_the_check_is_no_answer(monkeypatch):
    async def fake_retrieve(q, scheme=None, **_):
        return _chunks(scheme)

    async def fake_compose(prompt):
        return "- **MGNREGA** — something."

    async def fake_ground(answer, passages, question=""):
        return ""

    monkeypatch.setattr(settings, "RAG_GROUNDING_CHECK", True)
    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag.llm, "call_response_composer", fake_compose)
    monkeypatch.setattr(rag, "ground_answer", fake_ground)
    assert asyncio.run(rag.answer_from_kb_multi("q", ["MGNREGA", "PMAY-G"])) is None


def test_multi_scheme_check_off_keeps_the_answer(monkeypatch):
    async def fake_retrieve(q, scheme=None, **_):
        return _chunks(scheme)

    async def fake_compose(prompt):
        return "- **MGNREGA** — 100 days of work a year."

    async def boom(*a, **k):
        raise AssertionError("the check must not run when it is switched off")

    monkeypatch.setattr(settings, "RAG_GROUNDING_CHECK", False)
    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag.llm, "call_response_composer", fake_compose)
    monkeypatch.setattr(rag, "ground_answer", boom)
    out = asyncio.run(rag.answer_from_kb_multi("q", ["MGNREGA", "PMAY-G"]))
    assert out and "100 days" in out["answer"]


def _fallback_calls(monkeypatch, question):
    calls = []

    async def single(q, scheme=None, **_):
        calls.append(("single", scheme))
        return None

    async def multi(q, schemes):
        calls.append(("multi", tuple(schemes)))
        return None

    monkeypatch.setattr(rag, "answer_from_kb", single)
    monkeypatch.setattr(rag, "answer_from_kb_multi", multi)
    monkeypatch.setattr(p, "_is_data_shaped", lambda q: False)
    out = asyncio.run(p._data_path_kb_fallback(question))
    return calls, out


def test_fallback_searches_the_named_scheme(monkeypatch):
    calls, out = _fallback_calls(monkeypatch, "who decides which PMAY-G houses get approved")
    assert calls == [("single", "PMAY-G")]
    assert "PMAY-G" in out["answer"]           # the rephrase reply names the scheme in play


def test_fallback_two_named_schemes_takes_the_per_scheme_answer(monkeypatch):
    calls, _ = _fallback_calls(monkeypatch, "how do MGNREGA and PMAY-G differ in who decides")
    assert calls and calls[0][0] == "multi" and set(calls[0][1]) == {"MGNREGA", "PMAY-G"}


def test_fallback_no_scheme_searches_everything(monkeypatch):
    calls, _ = _fallback_calls(monkeypatch, "who decides this")
    assert calls == [("single", None)]


def test_fallback_answer_is_returned_as_knowledge(monkeypatch):
    async def single(q, scheme=None, **_):
        return {"answer": "From the documents.", "confidence": "medium", "sources": []}

    monkeypatch.setattr(rag, "answer_from_kb", single)
    monkeypatch.setattr(p, "_is_data_shaped", lambda q: False)
    out = asyncio.run(p._data_path_kb_fallback("who decides which PMAY-G houses get approved"))
    assert out["route"] == "knowledge" and out["answer"] == "From the documents."


def test_knowledge_bases_follow_the_registry():
    from app.scheme_registry import DATASETS
    assert set(rag._KB_SCHEMES) == {rag.kb_scheme(s) for s in DATASETS}
    assert "Home Stay" in rag._KB_SCHEMES and "Homestay" not in rag._KB_SCHEMES
    assert rag._KB_SCHEMES.count("CM Elevate") == 1   # Legacy shares the CM Elevate documents


def test_coverage_check_names_the_scheme_with_no_documents(monkeypatch, caplog):
    texts = {s: ["a piece"] for s in rag._KB_SCHEMES}
    texts["CMSS"] = []

    async def fake_texts():
        return texts

    monkeypatch.setattr(rag, "_kb_texts_by_scheme", fake_texts)
    with caplog.at_level("ERROR"):
        missing = asyncio.run(rag.check_kb_coverage())
    assert missing == ["CMSS"] and rag.kb_missing == ["CMSS"]
    assert "CMSS" in caplog.text
    texts["CMSS"] = ["now there"]
    assert asyncio.run(rag.check_kb_coverage()) == [] and rag.kb_missing == []
