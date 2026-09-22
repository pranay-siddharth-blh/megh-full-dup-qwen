"""
RAG / knowledge-base path (app/rag.py, app/kb_ingest.py, app/vectorstore.py's
megh_scheme_kb table) — pure-logic + monkeypatched-dependency checks, same
layered stance as tests/test_schema_retrieval.py, PLUS a best-effort live
section against the real Neon pgvector instance. Run:
`python tests/test_rag.py`, exit code 0 = all pass. The live section prints
SKIP (not FAIL) for anything needing the model gateway (unreachable from this
dev sandbox — same environmental limit test_schema_retrieval.py's live
section already documents), so this suite stays runnable offline.

Distinct from schema-retrieval: this is narrative FAQ/reference knowledge
("what is MGNREGA", "who is eligible for PMAY-G"), never table/column
schema — see openspec/changes/rag-knowledge-base-verification/proposal.md
for the live-verification pass this suite makes durable.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import kb_ingest, llm, rag, vectorstore  # noqa: E402
from app.config import settings  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  SKIP  {name}  — {reason}")


# ── 1. kb_ingest._chunk() — pure-function splitting logic ──────────────────
print("1. CHUNKING SPLITS H2/H3 SECTIONS AND FLAT FAQ DOCS CORRECTLY")

_MULTI_H2_DOC = """## Section One
Body text for section one, long enough to clear the 50-character floor.

## Section Two
Body text for section two, long enough to clear the 50-character floor.
"""

_chunks = kb_ingest._chunk(_MULTI_H2_DOC)
check("a doc with two short H2 sections produces two chunks",
      len(_chunks) == 2, str(_chunks))
check("each chunk is prefixed with its own heading",
      _chunks[0][0] == "Section One" and _chunks[1][0] == "Section Two", str(_chunks))

_OVERSIZED_H2_DOC = "## Big Section\n" + (
    "### Sub A\n" + ("word " * 400) + "\n\n### Sub B\n" + ("word " * 400)
)
_big_chunks = kb_ingest._chunk(_OVERSIZED_H2_DOC)
check("an oversized H2 section splits at H3 boundaries into 2+ chunks",
      len(_big_chunks) >= 2, str([h for h, _ in _big_chunks]))

_x_body = ("X is a thing, described here at enough length to clear the 50-char floor. " * 15).strip()
_y_body = ("Y is another thing, described here at enough length to clear the floor. " * 15).strip()
_FLAT_FAQ_DOC = f"""### What is X?
{_x_body}

### What is Y?
{_y_body}
"""
_faq_chunks = kb_ingest._chunk(_FLAT_FAQ_DOC)
check("a flat '### Question?' doc with no H2 produces one chunk per question",
      len(_faq_chunks) == 2 and _faq_chunks[0][0] == "What is X?" and _faq_chunks[1][0] == "What is Y?",
      str(_faq_chunks))


# ── 2. kb_ingest._collect_chunks() — PMAY-G/PMAY-U separation ──────────────
print("2. PMAY-G/PMAY-U SEPARATION AT INGEST TIME")


def _run_pmay_split_check():
    # Bodies padded well past _CHUNK_SIZE (1500 chars combined) so _chunk()
    # actually splits at the H3 boundary into two separate (heading, text)
    # chunks — the real-world case this separation logic targets, per
    # kb_ingest.py's own comment about PMAY doc section "7." staying merged
    # only when short enough to survive as one chunk.
    gramin_body = ("Gramin applicants apply via the Gram Panchayat. " * 20).strip()
    urban_body = ("Urban applicants apply via ULB income categories EWS/LIG/MIG. " * 20).strip()
    doc_text = f"""## 7. Application Process

### 7.1 PMAY-Gramin
{gramin_body}

### 7.2 PMAY-Urban
{urban_body}
"""
    orig_data_part = kb_ingest._DATA_PART
    orig_sources = kb_ingest._SOURCES

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "reference").mkdir()
        (tmp_path / "reference" / "pmay_gramin_complete_reference.md").write_text(
            doc_text, encoding="utf-8")

        kb_ingest._DATA_PART = tmp_path
        kb_ingest._SOURCES = [("reference/pmay_gramin_complete_reference.md", "PMAY-G")]
        try:
            chunks = kb_ingest._collect_chunks()
        finally:
            kb_ingest._DATA_PART = orig_data_part
            kb_ingest._SOURCES = orig_sources

    schemes = {c["scheme"] for c in chunks}
    check("a PMAY doc with an Urban H3 subsection produces a PMAY-U-tagged chunk",
          "PMAY-U" in schemes, str(schemes))
    pmay_g_chunks = [c for c in chunks if c["scheme"] == "PMAY-G"]
    check("no PMAY-G-tagged chunk's body mentions 'Urban' after stripping",
          all("urban" not in c["text"].lower() for c in pmay_g_chunks),
          str([c["text"] for c in pmay_g_chunks]))


_run_pmay_split_check()


# ── 3. rag.retrieve() degrades safely on an embedding failure ──────────────
print("3. RETRIEVE() DEGRADES SAFELY, NEVER RAISES")


async def _run_embedding_failure_check():
    orig_call_embedding = llm.call_embedding

    async def _boom(*_a, **_kw):
        raise RuntimeError("embedding service down")

    llm.call_embedding = _boom
    try:
        result = await rag.retrieve("any question", scheme="MGNREGA")
        check("embedding failure -> [] not an exception", result == [])
    finally:
        llm.call_embedding = orig_call_embedding


asyncio.run(_run_embedding_failure_check())


# ── 4. answer_from_kb()'s confidence-tier branching ─────────────────────────
print("4. ANSWER_FROM_KB() CONFIDENCE-TIER BRANCHING")


def _fake_chunk(score: float, text: str = "[Heading]\nSome answer text.") -> dict:
    return {"score": score, "text": text, "doc": "reference/x.md",
            "heading": "Heading", "scheme": "MGNREGA", "source_type": "sme"}


async def _run_high_confidence_check():
    orig_retrieve = rag.retrieve
    orig_compose = llm.call_response_composer
    composer_called = {"n": 0}

    async def _fake_retrieve(*_a, **_kw):
        return [_fake_chunk(settings.RAG_HIGH_CONFIDENCE + 0.02)]

    async def _fake_compose(*_a, **_kw):
        composer_called["n"] += 1
        return "should not be called"

    rag.retrieve = _fake_retrieve
    llm.call_response_composer = _fake_compose
    try:
        result = await rag.answer_from_kb("any question", scheme="MGNREGA")
        check("high-confidence top score returns verbatim with confidence 'high'",
              result is not None and result["confidence"] == "high", str(result))
        check("no composer call is made on the high-confidence path",
              composer_called["n"] == 0)
    finally:
        rag.retrieve = orig_retrieve
        llm.call_response_composer = orig_compose


asyncio.run(_run_high_confidence_check())


async def _run_medium_confidence_check():
    orig_retrieve = rag.retrieve
    orig_compose = llm.call_response_composer

    async def _fake_retrieve(*_a, **_kw):
        mid = (settings.RAG_HIGH_CONFIDENCE + settings.RAG_MEDIUM_CONFIDENCE) / 2
        return [_fake_chunk(mid)]

    async def _fake_compose(*_a, **_kw):
        return "A composed answer from the passages."

    rag.retrieve = _fake_retrieve
    llm.call_response_composer = _fake_compose
    try:
        result = await rag.answer_from_kb("any question", scheme="MGNREGA")
        check("medium-confidence top score composes an answer, confidence 'medium'",
              result is not None and result["confidence"] == "medium"
              and "composed answer" in result["answer"].lower(), str(result))
    finally:
        rag.retrieve = orig_retrieve
        llm.call_response_composer = orig_compose


asyncio.run(_run_medium_confidence_check())


async def _run_below_floor_check():
    orig_retrieve = rag.retrieve

    async def _fake_retrieve(*_a, **_kw):
        return [_fake_chunk(settings.RAG_MEDIUM_CONFIDENCE - 0.05)]

    rag.retrieve = _fake_retrieve
    try:
        result = await rag.answer_from_kb("any question", scheme="MGNREGA")
        check("below-medium-floor top score returns None", result is None, str(result))
    finally:
        rag.retrieve = orig_retrieve


asyncio.run(_run_below_floor_check())


# ── 5. RAG_RERANKER_ENABLED path — the flag split from schema retrieval ────
print("5. RERANKER PATH (RAG_RERANKER_ENABLED)")


def _fake_kb_candidates(n: int) -> list[dict]:
    return [
        {"score": 1.0 - i * 0.01, "text": f"[Heading {i}]\nContent {i}.",
         "doc": "reference/x.md", "heading": f"Heading {i}", "scheme": "MGNREGA",
         "source_type": "sme"}
        for i in range(n)
    ]


async def _run_rag_rerank_disabled_check():
    orig_call_embedding = llm.call_embedding
    orig_search = vectorstore.search
    llm.call_embedding = lambda *_a, **_kw: asyncio.sleep(0, result=[[0.1, 0.2]])
    vectorstore.search = lambda *_a, **_kw: asyncio.sleep(0, result=_fake_kb_candidates(settings.RAG_TOP_K))
    orig_enabled = settings.RAG_RERANKER_ENABLED
    settings.RAG_RERANKER_ENABLED = False
    try:
        result = await rag.retrieve("any question", scheme="MGNREGA")
        check("RAG reranker disabled -> cosine order truncated to RAG_RERANK_TOP_N",
              [c["heading"] for c in result] == [f"Heading {i}" for i in range(settings.RAG_RERANK_TOP_N)],
              str([c["heading"] for c in result]))
    finally:
        llm.call_embedding = orig_call_embedding
        vectorstore.search = orig_search
        settings.RAG_RERANKER_ENABLED = orig_enabled


asyncio.run(_run_rag_rerank_disabled_check())


async def _run_rag_rerank_enabled_check():
    orig_call_embedding = llm.call_embedding
    orig_search = vectorstore.search
    orig_call_reranker = llm.call_reranker
    llm.call_embedding = lambda *_a, **_kw: asyncio.sleep(0, result=[[0.1, 0.2]])
    vectorstore.search = lambda *_a, **_kw: asyncio.sleep(0, result=_fake_kb_candidates(settings.RAG_TOP_K))

    async def _reversed_rerank(_q, docs):
        n = len(docs)
        return [(n - 1 - i, 1.0) for i in range(n)]  # all above RAG_MIN_SCORE

    llm.call_reranker = _reversed_rerank
    orig_enabled = settings.RAG_RERANKER_ENABLED
    settings.RAG_RERANKER_ENABLED = True
    try:
        result = await rag.retrieve("any question", scheme="MGNREGA")
        n = settings.RAG_TOP_K
        top_n = settings.RAG_RERANK_TOP_N
        expected = [f"Heading {i}" for i in range(n - 1, n - 1 - top_n, -1)]
        check("RAG reranker enabled -> output follows reranked order, not cosine order",
              [c["heading"] for c in result] == expected, str([c["heading"] for c in result]))
    finally:
        llm.call_embedding = orig_call_embedding
        vectorstore.search = orig_search
        llm.call_reranker = orig_call_reranker
        settings.RAG_RERANKER_ENABLED = orig_enabled


asyncio.run(_run_rag_rerank_enabled_check())


# ── 6. Live section — real Neon pgvector, real megh_scheme_kb data ─────────
print("6. LIVE — RETRIEVAL QUALITY AND SCOPING AGAINST THE REAL megh_scheme_kb TABLE")


async def _run_live_checks():
    try:
        await llm.init_client()
        await vectorstore.init_pgvector()
    except Exception as e:  # noqa: BLE001
        skip("live RAG checks", f"pgvector/gateway unreachable — {e}")
        return

    try:
        count = await vectorstore.collection_count()
        if count <= 0:
            skip("live RAG checks", "megh_scheme_kb is empty — run kb_ingest.ingest_kb() first")
            return

        expected = len(kb_ingest._collect_chunks())
        check("live megh_scheme_kb row count matches the current data/ sources' expected count",
              count == expected, f"live={count} expected={expected}")

        # Scheme-scoped retrieval returns on-topic, correctly-scoped results.
        chunks = await rag.retrieve(
            "How many days of employment does MGNREGA guarantee per household?",
            scheme="MGNREGA")
        check("MGNREGA-scoped retrieval returns at least one chunk", len(chunks) > 0)
        check("every retrieved chunk is tagged MGNREGA",
              all(c["scheme"] == "MGNREGA" for c in chunks), str([c["scheme"] for c in chunks]))
        check("top chunk scores reasonably high on a direct factual question",
              chunks[0]["score"] >= settings.RAG_MEDIUM_CONFIDENCE, str(chunks[0]["score"]))

        # PMAY-G/PMAY-U separation holds against real ingested data.
        urban_chunks = await rag.retrieve(
            "What are the income categories for PMAY urban?", scheme="PMAY-G")
        check("a PMAY-G-scoped query never surfaces PMAY-U-tagged chunks live",
              all(c["scheme"] != "PMAY-U" for c in urban_chunks),
              str([c["scheme"] for c in urban_chunks]))

        # Confidence tiers fire on real data for a clean high-confidence question.
        result = await rag.answer_from_kb(
            "How many days of employment are guaranteed under MGNREGA?", scheme="MGNREGA")
        check("a clean, well-covered MGNREGA question resolves at high confidence live",
              result is not None and result["confidence"] == "high", str(result))
    finally:
        await vectorstore.close_pgvector()
        await llm.close_client()


asyncio.run(_run_live_checks())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL RAG/KNOWLEDGE-BASE CHECKS PASSED")
