"""
D-074 (2026-10-27): the project uses only two Qdrant collections on the data
box — megh_knowledge (RAG) and megh_sql_metadata (SQL examples) — both loaded
by another pipeline and only READ by the app.

Pinned here, on the real functions:
  - megh_knowledge's payload shape (source_file / section / scheme LIST) reads
    the same as the app's own (doc / heading / scheme string);
  - the scheme filter matches a tag inside a list, and "CM Elevate" also finds
    the pieces megh_knowledge tags "CM Elevate Legacy";
  - read-only: startup ingest never rebuilds the collection (the old checks
    would have DELETED megh_knowledge: it has no BM25 vector), and writes refuse;
  - the term cache (rag._kb_texts_by_scheme) survives list tags;
  - SQL_EXAMPLES_SOURCE: "yaml" (default) gives exactly the YAML few-shots;
    "qdrant" uses the fetched examples, never a two-scheme example in a
    one-scheme prompt, and falls back to YAML on any failure.
"""
import asyncio
from types import SimpleNamespace

import pytest
from qdrant_client import models

from app import annotations, kb_ingest, llm, prompt_builder, rag, sql_examples, vectorstore
from app.config import settings


@pytest.fixture(autouse=True, scope="module")
def _loaded():
    annotations.load_all()


def test_piece_reads_both_payload_shapes():
    own = vectorstore.piece({"text": "t", "doc": "PMAY-G/faq.md", "heading": "A > B", "scheme": "PMAY-G"}, 0.5)
    theirs = vectorstore.piece({"text": "t", "source_file": "PMAY-G/faq.md", "section": "A > B",
                                "scheme": ["PMAY-G"], "doc_title": "PMAY-G FAQ"}, 0.5)
    base = {"score": 0.5, "text": "t", "doc": "PMAY-G/faq.md", "heading": "A > B",
            "scheme": "PMAY-G", "source_type": "sme", "doc_type": ""}
    assert own == dict(base, title="")
    assert theirs == dict(base, title="PMAY-G FAQ")


def test_scheme_tags_string_or_list():
    assert vectorstore.scheme_tags({"scheme": "MGNREGA"}) == ["MGNREGA"]
    assert vectorstore.scheme_tags({"scheme": ["MGNREGA", "PMAY-G"]}) == ["MGNREGA", "PMAY-G"]
    assert vectorstore.scheme_tags({}) == []


def test_scheme_filter_matches_any_and_cm_elevate_legacy_tag():
    assert vectorstore.scheme_filter(None) is None
    cond = vectorstore.scheme_filter("CM Elevate").must[0]
    assert isinstance(cond.match, models.MatchAny)
    assert set(cond.match.any) == {"CM Elevate", "CM Elevate Legacy"}
    assert vectorstore.scheme_filter("MGNREGA").must[0].match.any == ["MGNREGA"]


def test_read_only_refuses_writes(monkeypatch):
    monkeypatch.setattr(settings, "QDRANT_KB_READ_ONLY", True)
    with pytest.raises(vectorstore.ReadOnlyCollectionError):
        asyncio.run(vectorstore.recreate_collection(dim=1024, sparse=True))
    with pytest.raises(vectorstore.ReadOnlyCollectionError):
        asyncio.run(vectorstore.upsert([]))


def test_read_only_ingest_never_rebuilds(monkeypatch):
    monkeypatch.setattr(settings, "QDRANT_KB_READ_ONLY", True)
    calls = []

    async def count():
        return 207

    async def must_not_run(*a, **k):
        calls.append(a)
        raise AssertionError("read-only ingest touched the collection")

    monkeypatch.setattr(vectorstore, "collection_count", count)
    monkeypatch.setattr(vectorstore, "recreate_collection", must_not_run)
    monkeypatch.setattr(vectorstore, "upsert", must_not_run)
    monkeypatch.setattr(kb_ingest, "_embed_all", must_not_run)
    out = asyncio.run(kb_ingest.ingest_kb(force=True))
    assert out["skipped"] and out["reason"] == "read-only collection" and out["points"] == 207
    assert not calls


def test_kb_text_cache_reads_list_tags(monkeypatch):
    pts = [SimpleNamespace(payload={"scheme": ["PMAY-G"], "text": "SECC list"}),
           SimpleNamespace(payload={"scheme": ["CM Elevate Legacy"], "text": "Refused records"}),
           SimpleNamespace(payload={"scheme": "MGNREGA", "text": "Job card"})]

    class Client:
        async def scroll(self, coll, limit, offset, with_payload):
            return pts, None

    monkeypatch.setattr(vectorstore, "get_client", lambda: Client())
    monkeypatch.setattr(settings, "QDRANT_COLLECTION", "test_two_collections_cache")
    rag._kb_text_cache.pop("test_two_collections_cache", None)
    texts = asyncio.run(rag._kb_texts_by_scheme())
    assert texts == {"PMAY-G": ["secc list"], "CM Elevate": ["refused records"], "MGNREGA": ["job card"]}


def test_yaml_source_is_the_old_fewshots():
    q = "total person days by district in FY 2024-25"
    for schemes in (["MGNREGA"], ["MGNREGA", "PMAY-G"], ["CM Elevate Legacy"]):
        sql_examples._examples_var.set(None)
        assert prompt_builder._fewshot_examples(schemes, q, 5) == annotations.few_shot_examples(schemes, q, top_k=5)


def _ex(i, tags):
    return {"question": f"q{i}", "sql": f"SELECT {i}", "id": i, "tags": tags}


def test_qdrant_examples_scoped_to_the_prompt_and_deduped():
    cross = _ex("cross_1", ["MGNREGA", "PMAY-G"])
    sql_examples._examples_var.set({
        "MGNREGA": [cross, _ex("mg_1", ["MGNREGA"]), _ex("mg_2", ["MGNREGA"])],
        "PMAY-G": [cross, _ex("pm_1", ["PMAY-G"])],
    })
    try:
        both = [e["id"] for e in prompt_builder._fewshot_examples(["MGNREGA", "PMAY-G"], "q", 5)]
        assert both == ["cross_1", "mg_1", "mg_2", "pm_1"]
        # one half of a cross-scheme question (generated per scheme, D-062)
        assert [e["id"] for e in prompt_builder._fewshot_examples(["MGNREGA"], "q", 5)] == ["mg_1", "mg_2"]
        # the prompt sees only question / sql / id
        assert set(prompt_builder._fewshot_examples(["PMAY-G"], "q", 5)[0]) == {"question", "sql", "id"}
        # a scheme with nothing fetched stays on its YAML bank
        assert (prompt_builder._fewshot_examples(["Focus Plus"], "q", 3)
                == annotations.few_shot_examples(["Focus Plus"], "q", top_k=3))
    finally:
        sql_examples._examples_var.set(None)


def test_prefetch_does_nothing_on_yaml(monkeypatch):
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "yaml")

    async def boom(*a, **k):
        raise AssertionError("embedding called with SQL_EXAMPLES_SOURCE=yaml")

    monkeypatch.setattr(llm, "call_embedding", boom)
    asyncio.run(sql_examples.prefetch("q", ["MGNREGA"]))
    assert sql_examples.current("MGNREGA") is None


def test_prefetch_failure_falls_back_to_yaml(monkeypatch):
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "qdrant")

    async def down(*a, **k):
        raise ConnectionError("gateway down")

    monkeypatch.setattr(llm, "call_embedding", down)

    async def turn():
        await sql_examples.prefetch("total person days", ["MGNREGA"])
        return sql_examples.current("MGNREGA"), prompt_builder._fewshot_examples(["MGNREGA"], "total person days", 5)

    fetched, used = asyncio.run(turn())
    assert fetched is None
    assert used == annotations.few_shot_examples(["MGNREGA"], "total person days", top_k=5)


def test_prefetch_keeps_only_examples_of_schemes_in_play(monkeypatch):
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "qdrant")

    async def embed(texts):
        return [[0.1] * 4 for _ in texts]

    hits = [SimpleNamespace(payload={"kind": "example", "scheme": ["MGNREGA", "Focus Plus"],
                                     "example_id": "x1", "question": "a", "sql": "SELECT 1"}),
            SimpleNamespace(payload={"kind": "example", "scheme": ["MGNREGA"],
                                     "example_id": "m1", "question": "b", "sql": "SELECT 2 "})]

    class Client:
        async def query_points(self, collection_name, query, query_filter, limit, with_payload):
            assert collection_name == settings.SQL_EXAMPLES_COLLECTION
            keys = {c.key for c in query_filter.must}
            assert keys == {"kind", "scheme"}
            return SimpleNamespace(points=hits)

    monkeypatch.setattr(llm, "call_embedding", embed)
    monkeypatch.setattr(vectorstore, "get_client", lambda: Client())

    async def turn():
        await sql_examples.prefetch("q", ["MGNREGA"])
        return sql_examples.current("MGNREGA")

    got = asyncio.run(turn())
    assert [e["id"] for e in got] == ["m1"] and got[0]["sql"] == "SELECT 2"


def test_defaults_name_only_the_two_collections():
    from app.config import Settings
    fields = Settings.model_fields
    assert fields["QDRANT_COLLECTION"].default == "megh_knowledge"
    assert fields["SQL_EXAMPLES_COLLECTION"].default == "megh_sql_metadata"
    assert fields["SQL_EXAMPLES_SOURCE"].default == "qdrant"
    assert fields["QDRANT_KB_READ_ONLY"].default is True
    assert fields["CONTEXT_SEMANTIC_MEMORY_ENABLED"].default is False


def test_citation_uses_the_collections_own_document_title():
    own = {"doc": "PMAY-G/pmayg_faq.md", "heading": "Eligibility", "scheme": "PMAY-G", "title": ""}
    theirs = {"doc": "CM_Elevate/CM_Elevate_Complete_Reference.md", "heading": "1. Overview",
              "scheme": "CM Elevate", "title": "CM-ELEVATE — Complete Scheme Reference"}
    assert rag.citations([own])[0]["title"] == "PMAY-G FAQ"
    assert rag.citations([theirs])[0]["title"] == "CM-ELEVATE — Complete Scheme Reference"


_META = [
    {"kind": "view", "scheme": ["MGNREGA"], "view_name": "curated.v_employment", "prompt_text": "VIEW employment"},
    {"kind": "view", "scheme": ["PMAY-G"], "view_name": "curated.v_pmay", "prompt_text": "VIEW pmay"},
    {"kind": "view", "scheme": ["MGNREGA", "PMAY-G"], "view_name": "curated.v_cross", "prompt_text": "VIEW cross"},
    {"kind": "join", "scheme": ["MGNREGA", "PMAY-G"], "join_id": "mg__pm", "prompt_text": "JOIN mg pm"},
    {"kind": "join", "scheme": ["CM Elevate", "CM Elevate Legacy"], "join_id": "cm__cml",
     "prompt_text": "NOT JOINABLE cm"},
]


def test_views_and_joins_reach_only_prompts_holding_their_schemes(monkeypatch):
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "qdrant")
    monkeypatch.setitem(sql_examples._meta_cache, "points", list(_META))
    assert sql_examples.metadata_text(["MGNREGA"]) == "VIEW employment"
    assert sql_examples.metadata_text(["MGNREGA", "PMAY-G"]).split("\n\n") == [
        "VIEW employment", "VIEW pmay", "VIEW cross", "JOIN mg pm"]
    assert sql_examples.metadata_text(["CM Elevate", "CM Elevate Legacy"]) == "NOT JOINABLE cm"
    assert "VIEW employment" in prompt_builder._sql_metadata_block(["MGNREGA"])
    # the budget's first compressor keeps the joins only
    assert sql_examples.metadata_text(["MGNREGA", "PMAY-G"], ("join",)) == "JOIN mg pm"
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "yaml")
    assert prompt_builder._sql_metadata_block(["MGNREGA"]) == ""


def test_example_notes_reach_the_prompt():
    sql_examples._examples_var.set({"Focus Legacy": [
        {"question": "payments by month", "sql": "SELECT 1", "id": "fl_1", "tags": ["Focus Legacy"],
         "notes": "date_of_remittance is blank on 171 rows; say so."}]})
    try:
        block = prompt_builder._fewshot_block(["Focus Legacy"], "payments by month")
        assert 'Q: "payments by month"\nNote: date_of_remittance is blank on 171 rows; say so.\nSQL: SELECT 1' in block
    finally:
        sql_examples._examples_var.set(None)


def test_sql_prompt_carries_the_metadata_section(monkeypatch):
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "qdrant")
    monkeypatch.setitem(sql_examples._meta_cache, "points", list(_META))
    prompt = prompt_builder.build_sql_prompt("person days by district", ["MGNREGA"], {"resolved": {}, "notes": []})
    assert "VIEW AND JOIN NOTES" in prompt and "VIEW employment" in prompt
