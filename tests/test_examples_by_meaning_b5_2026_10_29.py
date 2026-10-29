"""B5 (RAG plan) — the reviewed YAML few-shot banks ranked by MEANING
(SQL_EXAMPLES_SOURCE=yaml_meaning), not by shared words.

KI-438: the megh_sql_metadata examples (ranked by meaning) are all `validated: false`
and measured slightly worse than the reviewed YAML banks (54.1% vs 56.8%, 4 repairs vs
0). "Top 3 districts" and "which three districts had the highest" share few words, so
word ranking can show them different examples. yaml_meaning keeps the reviewed banks
and their refusal rules, and only changes the order. The bank is embedded once, in
the background; until then a turn keeps the word ranking.

OFFLINE: the real annotations / sql_examples / prompt_builder; embeddings are faked.
    .venv/Scripts/python.exe -m pytest tests/test_examples_by_meaning_b5_2026_10_29.py -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, llm, prompt_builder, sql_examples  # noqa: E402
from app.config import settings  # noqa: E402

BANK = [
    {"id": "T1", "question": "Total person days in a district", "sql": "SELECT 1"},
    {"id": "T2", "question": "Top 3 districts by person days", "sql": "SELECT 2", "variants": ["highest three districts"]},
    {"id": "T3", "question": "Wage rate history", "sql": None, "status": "UNANSWERABLE", "reason": "not held"},
]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def bank(monkeypatch):
    monkeypatch.setitem(annotations._few_shot_cache, "MGNREGA", BANK)
    monkeypatch.setattr(sql_examples, "_yaml_vectors", {})
    monkeypatch.setattr(sql_examples, "_yaml_pending", set())
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "yaml_meaning")

    async def embed(texts):          # "three / top / highest" -> ranking direction
        return [[1.0, 0.0] if any(w in t.lower() for w in ("three", "top", "highest")) else
                [0.0, 1.0] if "wage" in t.lower() else [0.5, 0.5] for t in texts]
    monkeypatch.setattr(llm, "call_embedding", embed)


def test_rank_reorders_the_bank_and_default_is_unchanged(bank):
    by_id = {"T1": 0.1, "T2": 0.9, "T3": 0.5}
    got = annotations.few_shot_examples(["MGNREGA"], "", 3, rank=lambda ex: by_id[ex["id"]])
    assert [e["id"] for e in got] == ["T2", "T3", "T1"]
    assert got[1]["sql"] is None and got[1]["reason"] == "not held"
    assert annotations.few_shot_examples(["MGNREGA"], "", 3) == annotations.few_shot_examples(["MGNREGA"], "", 3)


def test_first_turn_keeps_word_ranking_then_meaning(bank):
    async def turns():
        await sql_examples.prefetch("which three districts had the highest person days", ["MGNREGA"], 2)
        first = sql_examples.current("MGNREGA")
        await asyncio.sleep(0)                     # the background embedding of the bank
        await asyncio.sleep(0)
        await sql_examples.prefetch("which three districts had the highest person days", ["MGNREGA"], 2)
        return first, sql_examples.current("MGNREGA")
    first, second = _run(turns())
    assert first is None                            # not embedded yet: word ranking
    assert second[0]["id"] == "T2" and second[0]["tags"] == ["MGNREGA"]


def test_paraphrases_get_the_same_first_example(bank):
    async def top(q):
        await sql_examples.prefetch(q, ["MGNREGA"], 2)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await sql_examples.prefetch(q, ["MGNREGA"], 2)
        return sql_examples.current("MGNREGA")[0]["id"]
    assert _run(top("Top 3 districts by person-days")) == _run(top("which three districts had the highest"))


def test_a_refusal_example_reaches_the_prompt_with_its_reason(bank, monkeypatch):
    monkeypatch.setattr(sql_examples, "current", lambda s, ss=None: [
        {"question": "Wage rate history", "sql": None, "reason": "not held", "id": "T3", "tags": ["MGNREGA"]},
        {"question": "Total person days in a district", "sql": "SELECT 1", "id": None, "tags": ["MGNREGA"]},
        {"question": "Top 3 districts by person days", "sql": "SELECT 2", "id": None, "tags": ["MGNREGA"]}])
    block = prompt_builder._fewshot_block(["MGNREGA"], "wage rate")
    assert "NOT ANSWERABLE from this data — not held" in block
    assert "SELECT 1" in block and "SELECT 2" in block    # id-less examples are not deduplicated away


def test_the_qdrant_and_yaml_modes_are_untouched(monkeypatch):
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "qdrant")
    assert sql_examples.enabled() and not sql_examples.meaning_ranked_yaml()
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "yaml")
    assert not sql_examples.enabled() and not sql_examples.meaning_ranked_yaml()
