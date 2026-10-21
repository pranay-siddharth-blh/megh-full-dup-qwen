"""
Builds the RAG test set (RAG upgrade, Phase 1, 2026-10-14) -> testset.json.

Three kinds of question, all for the five knowledge bases (CM Elevate Legacy
shares CM Elevate's, see rag.kb_scheme):

  doc       written by the model from one section of an SME reference / FAQ
            doc, in an officer's words (several styles), with the expected
            answer and an EVIDENCE quote copied verbatim from that section.
  real      genuine knowledge questions officers asked (app.conversation_turns,
            read-only), each labelled with the section that answers it.
  negative  realistic questions the docs do NOT answer (checked against the
            scheme's whole text); the right reply is "not covered".

A retrieval "hit" is any retrieved piece whose text contains the evidence
quote, so the test set stays valid when Phase 2+ re-chunk the docs or move
them (doc paths and headings change; the words do not).

The set is a draft for an SME to check (reference_documents/rag_test_set.xlsx,
written by run_eval.py --export-testset). Re-running this script replaces it.

    python -m tests.rag_eval.build_testset            # from the repo root
"""
import asyncio
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from app import llm, vectorstore  # noqa: E402
from app.config import settings  # noqa: E402
from tests._text_checks import has_phrase, is_word_char  # noqa: E402

OUT = Path(__file__).with_name("testset.json")
SCHEMES = ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate"]
DOC_PER_SCHEME = 30
REAL_PER_SCHEME = 6
NEG_PER_SCHEME = 5
CONCURRENCY = 4
SEED = 20261014

STYLES = [
    "a short, keyword-style question typed quickly by a busy officer (4-8 words)",
    "a complete, polite question in plain English",
    "an informal question with one small, natural spelling mistake",
    "a question asked in the first person by a citizen who wants to benefit",
    "a question about one specific detail in the section (a number, amount, date, document or step), if it has one",
    "a question that uses different words from the section (synonyms, no copied phrases)",
]

_sem = asyncio.Semaphore(CONCURRENCY)


def norm(s: str) -> str:
    """Lower-case, unify quotes/dashes, collapse whitespace and drop markdown
    emphasis — so an evidence quote matches the chunk text it came from."""
    s = (s or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("₹", "rs ")
    s = "".join(" " if ch in "*_`#>|" else ch for ch in s)
    return " ".join(s.split())


def parse_json(raw: str):
    lines = []
    for line in (raw or "").strip().split("\n"):     # code fences at a line start / end
        if line.startswith("```json"):
            line = line[7:]
        elif line.startswith("```"):
            line = line[3:]
        if line.endswith("```"):
            line = line[:-3]
        lines.append(line)
    raw = "\n".join(lines).strip()
    opens = [k for k in (raw.find("["), raw.find("{")) if k != -1]
    first = min(opens) if opens else -1
    last = max(raw.rfind("]"), raw.rfind("}"))
    return json.loads(raw[first:last + 1] if first != -1 and last > first else raw)


async def ask(prompt: str, schema: dict, max_tokens: int = 700, temperature: float = 0.3):
    async with _sem:
        for attempt in range(3):
            try:
                raw = await llm.call_model(
                    base_url=settings.RESPONSE_MODEL_BASE_URL, model=settings.RESPONSE_MODEL,
                    api_key=settings.RESPONSE_MODEL_API_KEY, prompt=prompt,
                    temperature=temperature, max_tokens=max_tokens, timeout=120,
                    guided={"guided_json": schema} if settings.GUIDED_DECODING_ENABLED else None,
                    role="rag_eval")
                return parse_json(raw)
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    print("  model call failed:", type(e).__name__, str(e)[:120])
                    return None
                await asyncio.sleep(2 + attempt * 3)


async def load_chunks() -> dict[str, list[dict]]:
    """SME chunks of the live KB collection, per scheme (web background excluded)."""
    client = vectorstore.get_client()
    by_scheme: dict[str, list[dict]] = defaultdict(list)
    offset = None
    while True:
        pts, offset = await client.scroll(settings.QDRANT_COLLECTION, limit=256, offset=offset,
                                          with_payload=True)
        for p in pts:
            pl = p.payload or {}
            if pl.get("source_type", "sme") == "web" or len(pl.get("text", "")) < 160:
                continue
            by_scheme[pl.get("scheme", "")].append(
                {"doc": pl.get("doc", ""), "heading": pl.get("heading", ""), "text": pl.get("text", "")})
        if offset is None:
            break
    for s in by_scheme:
        by_scheme[s].sort(key=lambda c: (c["doc"], c["heading"]))
    return by_scheme


def pick_sections(chunks: list[dict], n: int, rnd: random.Random) -> list[dict]:
    """n picks spread over every section: each section once, then again
    (with a different style) for the longest ones until n is reached."""
    order = chunks[:]
    rnd.shuffle(order)
    picks = order[:n]
    extra = sorted(chunks, key=lambda c: -len(c["text"]))
    i = 0
    while len(picks) < n and extra:
        picks.append(extra[i % len(extra)])
        i += 1
    return picks


DOC_SCHEMA = {"type": "object", "properties": {
    "question": {"type": "string"}, "answer": {"type": "string"}, "evidence": {"type": "string"}},
    "required": ["question", "answer", "evidence"]}


async def doc_item(scheme: str, chunk: dict, style: str) -> dict | None:
    prompt = f"""You are writing test questions for a government scheme helpdesk chatbot in Meghalaya, India.

Scheme: {scheme}
Section of the official reference document:
<<<
{chunk['text'][:3500]}
>>>

Write ONE question that an officer or citizen would really ask, which THIS section fully answers.
Style: {style}.
Rules:
- Mention the scheme naturally (e.g. "{scheme}") unless the style is keyword-style.
- Do not copy the section heading word for word.
- The question must be answerable from this section alone.
Then give:
- "answer": the correct answer in 1-3 sentences, using only this section.
- "evidence": an EXACT quote of 6-25 consecutive words copied character-for-character from the
  section above that proves the answer (no "..." and no changes).
Reply as JSON: {{"question": "...", "answer": "...", "evidence": "..."}}"""
    for _ in range(2):
        r = await ask(prompt, DOC_SCHEMA)
        if r and r.get("question") and norm(r.get("evidence", "")) and norm(r["evidence"]) in norm(chunk["text"]):
            return {"kind": "doc", "scheme": scheme, "question": r["question"].strip(),
                    "expected_answer": r["answer"].strip(), "evidence": r["evidence"].strip(),
                    "gold_doc": chunk["doc"], "gold_heading": chunk["heading"], "style": style}
    return None


LABEL_SCHEMA = {"type": "object", "properties": {
    "section": {"type": "integer"}, "answer": {"type": "string"}, "evidence": {"type": "string"}},
    "required": ["section", "answer", "evidence"]}


async def real_item(scheme: str, q: str, chunks: list[dict]) -> dict | None:
    """Label a logged question with the section that answers it (or none)."""
    listing = "\n\n".join(f"[{i}] {c['text'][:700]}" for i, c in enumerate(chunks))
    prompt = f"""Question asked to a {scheme} helpdesk chatbot: "{q}"

Numbered sections of the official {scheme} documents:
{listing}

Which ONE section fully answers the question? If none of them answers it, use -1.
If one does, also give "answer" (1-3 sentences, from that section only) and "evidence": an EXACT
quote of 6-25 consecutive words copied from that section that proves the answer.
Reply as JSON: {{"section": <number or -1>, "answer": "...", "evidence": "..."}}"""
    r = await ask(prompt, LABEL_SCHEMA, max_tokens=500, temperature=0.0)
    if not r:
        return None
    i = r.get("section", -1)
    if isinstance(i, int) and 0 <= i < len(chunks) and norm(r.get("evidence", "")) in norm(chunks[i]["text"]) \
            and norm(r.get("evidence", "")):
        return {"kind": "real", "scheme": scheme, "question": q, "expected_answer": r["answer"].strip(),
                "evidence": r["evidence"].strip(), "gold_doc": chunks[i]["doc"],
                "gold_heading": chunks[i]["heading"], "style": "logged officer question"}
    return {"kind": "unanswered_real", "scheme": scheme, "question": q}


NEG_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
              "required": ["questions"]}
CHECK_SCHEMA = {"type": "object", "properties": {"answerable": {"type": "boolean"}, "why": {"type": "string"}},
                "required": ["answerable", "why"]}


async def answerable(scheme: str, q: str, full_text: str) -> bool | None:
    prompt = f"""Official {scheme} reference text:
<<<
{full_text}
>>>

Question: "{q}"
Can this question be answered (fully or mostly) from the text above? Answer strictly.
Reply as JSON: {{"answerable": true|false, "why": "one short reason"}}"""
    r = await ask(prompt, CHECK_SCHEMA, max_tokens=120, temperature=0.0)
    return None if r is None else bool(r.get("answerable"))


async def negatives(scheme: str, chunks: list[dict], full_text: str) -> list[dict]:
    heads = "\n".join(sorted({f"- {c['heading']}" for c in chunks}))
    prompt = f"""A chatbot answers questions about the {scheme} scheme in Meghalaya from documents with
these sections:
{heads}

Write 10 realistic questions an officer might ask about {scheme} that these documents would NOT
answer — e.g. a specific local office phone number, a named person's application, next year's
budget, a rule from another state, a deadline that is not published, a comparison with an
unrelated programme. Keep them plausible and on the topic of {scheme}.
Reply as JSON: {{"questions": ["...", "..."]}}"""
    r = await ask(prompt, NEG_SCHEMA, max_tokens=700, temperature=0.7)
    out = []
    for q in (r or {}).get("questions", [])[:10]:
        ok = await answerable(scheme, q, full_text)
        if ok is False:
            out.append({"kind": "negative", "scheme": scheme, "question": q.strip(),
                        "expected_answer": "Not covered by the scheme documents (should say so, not guess).",
                        "evidence": "", "gold_doc": "", "gold_heading": "", "style": "not covered"})
        if len(out) >= NEG_PER_SCHEME:
            break
    return out


# Whole words / phrases, any case; '#' is one digit (tests/_text_checks.find_phrase).
_DATAISH = ("how many", "count", "number of", "total", "distribution", "breakdown", "district", "block",
            "village", "batch", "list all", "list the", "top #", "status of", "amount released",
            "amount disbursed", "compare", "trend", "year-wise", "year wise", "per year", "in 20##")
_QUESTION_OPENERS = {"what", "who", "how", "is", "are", "can", "does", "do", "when", "where", "why", "which",
                     "tell", "explain", "describe", "eligib", "document", "documents"}


def _dataish(q: str) -> bool:
    return has_phrase(q, *_DATAISH, bounded=True)


def _questionish(q: str) -> bool:
    """A '?' anywhere, or the text opens with a question word (the whole first word)."""
    if "?" in q:
        return True
    k = 0
    while k < len(q) and is_word_char(q[k]):
        k += 1
    return q[:k].lower() in _QUESTION_OPENERS


async def real_candidates() -> dict[str, list[str]]:
    """Logged knowledge questions, read-only, over ONE connection (the shared
    database is often near its connection limit; a pool would ask for more)."""
    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncpg.connect(dsn, timeout=20)
    except Exception as e:  # noqa: BLE001
        print("  logged questions unavailable (" + type(e).__name__ + ") - building without them")
        return {}
    try:
        rows = await conn.fetch(
            """SELECT DISTINCT ON (lower(question)) question, schemes
               FROM app.conversation_turns WHERE route = 'knowledge'""")
    finally:
        await conn.close()
    by: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        q = " ".join((r["question"] or "").split())
        sch = {("CM Elevate" if s == "CM Elevate Legacy" else s) for s in (r["schemes"] or [])}
        if len(sch) != 1 or not (15 <= len(q) <= 200) or _dataish(q) or not _questionish(q):
            continue
        if not q.isascii():
            continue
        by[sch.pop()].append(q)
    return by


async def main() -> None:
    rnd = random.Random(SEED)
    await llm.init_client()
    await vectorstore.init_qdrant()
    try:
        by_scheme = await load_chunks()
        logged = await real_candidates()
        items: list[dict] = []
        for scheme in SCHEMES:
            chunks = by_scheme.get(scheme, [])
            full = "\n\n".join(c["text"] for c in chunks)
            picks = pick_sections(chunks, DOC_PER_SCHEME + 6, rnd)   # spare picks for rejects
            styles = [STYLES[i % len(STYLES)] for i in range(len(picks))]
            rnd.shuffle(styles)
            docs = [d for d in await asyncio.gather(*(doc_item(scheme, c, s) for c, s in zip(picks, styles))) if d]
            docs = docs[:DOC_PER_SCHEME]
            cands = logged.get(scheme, [])
            rnd.shuffle(cands)
            reals = [x for x in await asyncio.gather(*(real_item(scheme, q, chunks) for q in cands[:REAL_PER_SCHEME * 3])) if x]
            real_ok = [x for x in reals if x["kind"] == "real"][:REAL_PER_SCHEME]
            negs = await negatives(scheme, chunks, full)
            print(f"{scheme:13} sections={len(chunks):3}  doc={len(docs):3}  real={len(real_ok):2} "
                  f"(of {len(cands)} logged)  negative={len(negs)}")
            items += docs + real_ok + negs
        for i, it in enumerate(items, 1):
            it["id"] = f"Q{i:03d}"
        OUT.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n{len(items)} questions -> {OUT}")
    finally:
        await vectorstore.close_qdrant()
        await llm.close_client()


if __name__ == "__main__":
    asyncio.run(main())
