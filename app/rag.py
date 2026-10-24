"""
RAG path — answers general scheme-knowledge questions from the data/
narrative docs (see kb_ingest.py), never from the database.

Flow (the NeuralAiGovernanceProject standard, adapted to Qdrant + qwen3):
  1. embed the question           -> qwen3-embedding
  2. vector search the KB         -> Qdrant, RAG_TOP_K candidates
  3. rerank the candidates        -> qwen3-reranker, keep RAG_RERANK_TOP_N
  4. confidence tiers:
       >= RAG_HIGH_CONFIDENCE   -> return the top chunk verbatim (no compose call)
       >= RAG_MEDIUM_CONFIDENCE -> compose an answer from the kept chunks
       below                    -> return None; the pipeline says "not in the
                                   scheme reference material"
"""
import asyncio
import json
import logging

from app import context_budget, llm, local_rank, vectorstore
from app.config import settings
from app.text_match import ANY, Alt, Hit, Matcher, Opt, Seq, W

logger = logging.getLogger(__name__)

# The KB docs are Markdown, but the chat UI renders answers as plain text, so
# raw "### " heading markers leak through and look unprofessional. Drop the
# leading hashes and keep the heading text as its own line. A line start is
# the text start or just after "\n"; up to three whitespace characters (which
# may themselves be newlines), one to six '#', then spaces/tabs are dropped.
def _rag_heading_marker_end(text: str, p: int) -> int:
    """End of a Markdown heading marker starting at line start `p`, or -1."""
    n = len(text)
    k = p
    while k < n and k - p < 3 and text[k].isspace():
        k += 1
    h = k
    while h < n and text[h] == "#":
        h += 1
    if not 1 <= h - k <= 6 or h >= n or text[h] not in " \t":
        return -1
    while h < n and text[h] in " \t":
        h += 1
    return h


def _rag_strip_md_headings(text: str) -> str:
    out, last, p, n = [], 0, 0, len(text)
    while p < n:
        end = _rag_heading_marker_end(text, p)
        if end > 0:
            out.append(text[last:p])
            last = end
            # the next line start at or after the end of this marker
            nl = text.find("\n", end - 1)
        else:
            nl = text.find("\n", p)
        if nl < 0:
            break
        p = nl + 1
    out.append(text[last:])
    return "".join(out)


# Matches the exact refusal sentence the compose prompt is told to use (see
# answer_from_kb below), with or without the leading "That" — the composer
# sometimes tacks this on as a trailing hedge after an otherwise complete
# answer, and only that sentence should be stripped, not the whole response.
def _rag_lower(text: str) -> str:
    """`text` lower-cased, one character for one (positions stay valid)."""
    low = text.lower()
    if len(low) == len(text):
        return low
    return "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in text)


_REFUSAL_SENTENCE = tuple(f"{neg} covered in the {sch}reference material"
                          for neg in ("isn't", "isnt") for sch in ("scheme ", ""))


def _rag_strip_refusal(text: str) -> str:
    """Every _REFUSAL_SENTENCE removed (any case), with a "that" and whitespace
    in front of it and the full stop after it."""
    text = text or ""
    low = _rag_lower(text)
    out, last = [], 0
    while True:
        hits = [(k, len(c)) for c in _REFUSAL_SENTENCE for k in (low.find(c, last),) if k >= 0]
        if not hits:
            break
        k, size = min(hits)
        start = j = k
        while j > last and low[j - 1].isspace():
            j -= 1
        if j < k and j - 4 >= last and low[j - 4:j] == "that":
            start = j - 4
        end = k + size
        if text[end:end + 1] == ".":
            end += 1
        out.append(text[last:start])
        last = end
    out.append(text[last:])
    return "".join(out)

# Safety net for when the composer ignores the instructed refusal sentence
# above and free-forms its own — seen in the wild as "The provided reference
# material does not contain a specific status breakdown for X.", which
# _REFUSAL_SENTENCE doesn't match, so it leaked straight to the user instead
# of falling back to the pipeline's plain "I don't have information..."
# message. Any answer containing one of these phrases (any case, even inside
# a longer word) is treated as a full refusal (return None), the same as one
# that's empty after _REFUSAL_SENTENCE stripping.
_LIKELY_REFUSAL = (
    ("reference material",)
    + tuple(f"{neg} {verb}" for neg in ("don't", "dont", "doesn't", "doesnt", "do not", "does not")
            for verb in ("contain", "have", "cover", "include", "mention"))
    # "SECC is not mentioned in the published scheme information." read as an
    # answer and stopped the other-scheme fallback (2026-10-14).
    + ("not covered", "not available", "not mentioned", "isn't mentioned", "isnt mentioned",
       "aren't mentioned", "arent mentioned", "no information available", "no information is available")
)


def _rag_likely_refusal(sentence: str) -> bool:
    low = _rag_lower(sentence)
    return any(p in low for p in _LIKELY_REFUSAL)


def _rag_split_after_punct(text: str) -> list[str]:
    """Split where '.', '!' or '?' is followed by whitespace (the whitespace run
    is dropped)."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i] in ".!?" and i + 1 < n and text[i + 1].isspace():
            out.append(text[start:i + 1])
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            start = i = j
            continue
        i += 1
    out.append(text[start:])
    return out


def _is_whole_refusal(text: str) -> bool:
    """True when every sentence in `text` reads as a refusal, even though it
    doesn't match the exact instructed template (_REFUSAL_SENTENCE) — the
    composer sometimes free-forms its own wording instead of the requested
    sentence. A partial caveat inside an otherwise substantive answer (e.g.
    one sentence noting a scheme "doesn't cover private land") has other,
    non-matching sentences alongside it and is left alone."""
    sentences = [s.strip() for line in text.split("\n") for s in _rag_split_after_punct(line) if s.strip()]
    return bool(sentences) and all(_rag_likely_refusal(s) for s in sentences)

# The general_faq.md sources are flat "### Question?\nAnswer." pairs (see
# kb_ingest._chunk), so a chunk's own body opens by restating the question as
# its heading. The high-confidence path below returns that body verbatim, and
# without this the chat bubble reads as a literal transcript — "What documents
# are needed for X? Typically..." — instead of a natural answer. Drop that
# leading heading line whenever it's phrased as a question (ends in "?");
# non-FAQ section headings (e.g. "### Eligibility Criteria") don't match and
# are left as useful context.
def _rag_drop_question_heading(text: str) -> str:
    """Drop a first line "#..# Question?" (one to six '#', then spaces/tabs, a
    line ending in '?' plus optional spaces/tabs) and the newlines after it."""
    nl = text.find("\n")
    if nl < 0:
        return text
    line = text[:nl]
    h = len(line) - len(line.lstrip("#"))
    if not 1 <= h <= 6 or line[h:h + 1] not in (" ", "\t") or not line.rstrip(" \t").endswith("?"):
        return text
    end = nl
    while end < len(text) and text[end] == "\n":
        end += 1
    return text[end:]


def _clean_for_display(text: str) -> str:
    return _hide_internal_sources(_rag_strip_md_headings(text).strip())


# The user must never be told about the bot's own sources — "The provided
# reference material does not contain a helpline number", "the passages do not
# specify..." (General TC-006/015, test run 2026-10-09: the expected reply is a
# user-friendly limitation, not a knowledge-base one). The prompt says so too,
# but prose rules fail under sampling, so every displayed answer is rewritten
# here: the internal source becomes "the published scheme information", which
# keeps the sentence grammatical ("...does not contain X, but notes that...").
_RAG_PASSAGE = W("passage", "passages")
_INTERNAL_SOURCE = Matcher(Seq(
    Opt("the"),
    Opt(W("provided", "available", "given", "above", "retrieved")),
    Opt("scheme"),
    Alt(Seq("reference", W("material", "passage", "passages", "document", "documents", "doc", "docs", "text"),
            sep="space"),
        Seq(W("provided", "given", "above", "retrieved"),
            W("passage", "passages", "document", "documents", "context", "text"), sep="space"),
        Seq(_RAG_PASSAGE, W("provided", "above", "given"), sep="space"),
        _RAG_PASSAGE,
        W("knowledgebase"),
        Seq("knowledge", "base", sep="space"),
        Seq("knowledge", "base", sep="dash"),
        Seq("source", W("data", "document", "documents", "material"), sep="space")),
    sep="space"))


def _rag_at_sentence_start(before: str) -> bool:
    """Does `before` (the text ahead of a match) end where a sentence starts:
    at the text start or a new line (optionally after a "- " / "* " bullet),
    or after '.', '!' or '?' and whitespace?"""
    def line_start(s: str) -> bool:
        core = s.rstrip()
        return core == "" or "\n" in s[len(core):]
    core = before.rstrip()
    if len(core) < len(before) and core[-1:] in (".", "!", "?"):
        return True
    if len(core) < len(before) and core[-1:] in ("-", "*") and line_start(core[:-1]):
        return True
    return line_start(before)


def _rag_bad_knowledge_gap(m: Hit) -> bool:
    """A "knowledge ... base" hit whose two words are split by anything other
    than one whitespace character or one '-' (not an internal source)."""
    low = _rag_lower(m.group(0))
    if not low.endswith("base") or low.endswith("knowledgebase"):
        return False
    gap = low[low.rfind("knowledge") + len("knowledge"):-len("base")]
    return not (len(gap) == 1 and (gap.isspace() or gap == "-"))


def _hide_internal_sources(text: str) -> str:
    def repl(m: Hit) -> str:
        if _rag_bad_knowledge_gap(m):
            return m.group(0)
        at_start = _rag_at_sentence_start(m.string[: m.start()])
        return "The published scheme information" if at_start else "the published scheme information"
    return _INTERNAL_SOURCE.sub(repl, text or "")


def _strip_heading(text: str) -> str:
    # Chunks are stored as "[heading path]\n<body>" — drop the tag for display.
    if text.startswith("[") and "]\n" in text:
        text = text.split("]\n", 1)[1]
    text = _rag_drop_question_heading(text)
    return _clean_for_display(text)


# How each scheme is actually WRITTEN in its own reference docs, where that
# differs from the label this system uses internally. Only Focus Legacy truly
# needs it — "Focus Legacy" is our own disambiguation label (coined to separate
# the producer-group scheme from Focus Plus) and appears NOWHERE in the SME
# prose, which says "FOCUS" throughout. Told to answer only from the passages,
# the composer then reports the scheme as "not mentioned" while sitting on the
# right material. The others are listed so the note reads naturally for them
# too, and so a future doc that prefers one spelling does not regress.
_SCHEME_DOC_NAMES = {
    "Focus Legacy": ("FOCUS", "the FOCUS scheme (Farmers' Collectivization for "
                     "Upscaling Production and Marketing Systems), the Meghalaya "
                     "producer-group scheme"),
    "Focus Plus": ("FOCUS+", "FOCUS+, the Meghalaya farmer cash-benefit scheme"),
    "CM Elevate": ("CM-ELEVATE", "CM-ELEVATE"),
    "CM Elevate Legacy": ("CM-ELEVATE", "CM-ELEVATE, the Meghalaya programme — CM "
                          "Elevate Legacy is its sanction and disbursement records and "
                          "shares the programme's reference material with CM Elevate"),
    "MGNREGA": ("MGNREGA", "MGNREGA"),
    "PMAY-G": ("PMAY-G", "PMAY-G / PMAY-Gramin"),
}


def _naming_note(scheme: str | None) -> str:
    """One line telling the composer that the passages ARE this scheme's own
    material, under whatever name the documents happen to use. Empty when the
    call is unscoped — we cannot assert whose material it is then."""
    if not scheme:
        return ""
    doc_name, description = _SCHEME_DOC_NAMES.get(scheme, (scheme, scheme))
    note = (
        f'The passages below are the reference material for {scheme}. '
        f'In those documents this scheme is written as "{doc_name}" '
        f'({description}). '
        f'"{scheme}" and "{doc_name}" are the SAME scheme — never say {scheme} '
        f'is not mentioned, or that the documents describe a different scheme, '
        f'merely because the passages use the other spelling.'
    )
    return note + "\n\n"


# Schemes that are different DATASETS of one programme share ONE knowledge base.
# CM Elevate (applications) and CM Elevate Legacy (sanctions and disbursements)
# are both the CM-ELEVATE programme: its eligibility, benefits, sub-schemes and
# application process are the same whichever dataset a user is looking at, so
# both read the same reference docs — stored under "CM Elevate" (kb_ingest folds
# a Legacy-tagged doc into that tag too). The vector filter is an exact match,
# so every retrieval goes through kb_scheme(). Every other scheme maps to itself.
_KB_SCHEME_ALIAS = {"CM Elevate Legacy": "CM Elevate"}


def kb_scheme(scheme: str | None) -> str | None:
    """The knowledge-base tag a scheme's reference material is stored under."""
    return _KB_SCHEME_ALIAS.get(scheme, scheme) if scheme else scheme


_KB_SCHEMES = ("MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate")

_STOP = frozenset("""a an the is are was were be what whats what's who whom which how why when where does do
did of in on for to and or under about tell me explain define meaning describe role please kindly
scheme schemes this that it its i we you""".split())

# Lower-cased piece texts per knowledge base, read once per collection; the
# knowledge base is a few hundred pieces, so a literal term check is cheap.
_kb_text_cache: dict[str, dict[str, list[str]]] = {}


_RAG_TERM_START = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_RAG_TERM_CHARS = _RAG_TERM_START | frozenset("+&-")


def _rag_terms(text: str) -> list[str]:
    """Runs that start with an ASCII letter/digit and go on with letters,
    digits, '+', '&' or '-' (text already lower-cased)."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] in _RAG_TERM_START:
            j = i + 1
            while j < n and text[j] in _RAG_TERM_CHARS:
                j += 1
            out.append(text[i:j])
            i = j
        else:
            i += 1
    return out


def _rag_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _rag_has_term(text: str, term: str) -> bool:
    """`term` occurs in `text` with a word boundary at both ends (a term that
    ends in '+', '&' or '-' needs a word character right after it, as the old
    word-boundary rule did)."""
    if not term:
        return False
    k = text.find(term)
    while k >= 0:
        e = k + len(term)
        if _rag_is_word_char(term[0]):
            left = k == 0 or not _rag_is_word_char(text[k - 1])
        else:
            left = k > 0 and _rag_is_word_char(text[k - 1])
        if _rag_is_word_char(term[-1]):
            right = e == len(text) or not _rag_is_word_char(text[e])
        else:
            right = e < len(text) and _rag_is_word_char(text[e])
        if left and right:
            return True
        k = text.find(term, k + 1)
    return False


def _distinctive_terms(question: str) -> list[str]:
    words = _rag_terms((question or "").lower())
    return [w for w in words if w not in _STOP and len(w) >= 3][:3]


async def _kb_texts_by_scheme() -> dict[str, list[str]]:
    coll = settings.QDRANT_COLLECTION
    if coll not in _kb_text_cache:
        out: dict[str, list[str]] = {}
        client = vectorstore.get_client()
        offset = None
        while True:
            pts, offset = await client.scroll(coll, limit=256, offset=offset, with_payload=["scheme", "text"])
            for p in pts:
                pl = p.payload or {}
                out.setdefault(pl.get("scheme", ""), []).append(str(pl.get("text", "")).lower())
            if offset is None:
                break
        _kb_text_cache[coll] = out
    return _kb_text_cache[coll]


async def best_kb_scheme(question: str, exclude: str | None = None) -> str | None:
    """The knowledge base (other than `exclude`) whose best passage matches the
    question most closely, when that match reaches RAG_MEDIUM_CONFIDENCE —
    else None. For a term question whose scheme was only carried over from the
    previous turn ("What is SECC?" after an MGNREGA answer: SECC is PMAY-G's)."""
    skip = kb_scheme(exclude) if exclude else None
    # The term itself first: meaning search reads a bare acronym poorly ("What
    # is SECC?" matched CM Elevate's pieces best, though only PMAY-G's documents
    # say SECC). The scheme whose pieces contain the term most often wins; a
    # tie, or a term no document uses, falls to the meaning search below.
    terms = _distinctive_terms(question)
    if terms:
        texts = await _kb_texts_by_scheme()
        counts = {s: sum(1 for t in texts.get(s, []) if all(_rag_has_term(t, w) for w in terms))
                  for s in _KB_SCHEMES if s != skip}
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])
        if ranked and ranked[0][1] > 0 and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            return ranked[0][0]
    best, best_score = None, 0.0
    for s in _KB_SCHEMES:
        if s == skip:
            continue
        chunks = await retrieve(question, scheme=s, expand=False)
        top = max((float(c.get("score", 0.0)) for c in chunks), default=0.0)
        if top > best_score:
            best, best_score = s, top
    return best if best_score >= settings.RAG_MEDIUM_CONFIDENCE else None


def _rag_json_object(raw):
    """The text from the first '{' through the last '}' of a model reply, or
    the reply itself when it has no such span."""
    text = raw or ""
    i = text.find("{")
    j = text.rfind("}")
    return text[i:j + 1] if 0 <= i < j else raw


_ALT_SCHEMA = {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
               "required": ["queries"]}


async def _alt_queries(question: str, scheme: str | None) -> list[str]:
    """Other wordings of the question for search (Phase 4, 2026-10-15): the
    words an officer types ("documents?", "how much money i get") are often
    not the words the documents use ("documents required at registration",
    "unit assistance amount"). One short call to the fast model; any failure
    returns [] and the question is searched alone."""
    n = settings.RAG_MULTI_QUERY
    if n <= 0 or not (question or "").strip():
        return []
    about = f"the {scheme} scheme" if scheme else "a government scheme"
    prompt = f"""An officer in Meghalaya, India asked a helpdesk chatbot about {about}:
"{question}"

Write {n} different short search queries (5-12 words each) that would find the answer in the
scheme's official reference documents. Use the plain words such documents use (for example
"eligibility criteria", "documents required", "unit assistance amount", "how to apply",
"grievance redressal"), keep every specific term from the question, and do not answer it.
Reply as JSON: {{"queries": ["...", "..."]}}"""
    try:
        raw = await asyncio.wait_for(llm.call_model(
            base_url=settings.CLASSIFIER_BASE_URL, model=settings.CLASSIFIER_MODEL,
            api_key=settings.CLASSIFIER_API_KEY, prompt=prompt, temperature=0.0, max_tokens=160,
            timeout=settings.RAG_MULTI_QUERY_TIMEOUT_SECONDS, role="rag_multi_query",
            guided={"guided_json": _ALT_SCHEMA} if settings.GUIDED_DECODING_ENABLED else None),
            timeout=settings.RAG_MULTI_QUERY_TIMEOUT_SECONDS + 1)
        qs = json.loads(_rag_json_object(raw)).get("queries") or []
    except Exception as e:  # noqa: BLE001 — search with the question alone
        logger.info("rag: alternative wordings unavailable (%s)", type(e).__name__)
        return []
    seen = {" ".join(question.lower().split())}
    out = []
    for q in qs:
        if isinstance(q, str) and q.strip() and " ".join(q.lower().split()) not in seen:
            seen.add(" ".join(q.lower().split()))
            out.append(q.strip()[:200])
    return out[:n]


async def _search_one(vec: list[float], text: str, k: int, scheme: str | None) -> list[dict]:
    sparse = None
    if settings.RAG_HYBRID_ENABLED and settings.RAG_SPARSE_MODEL:
        sparse = await local_rank.sparse_query(text)
    try:
        return await vectorstore.search(vec, top_k=k, scheme=kb_scheme(scheme), sparse=sparse)
    except Exception as e:  # noqa: BLE001
        # The Qdrant server closes idle keep-alive connections; the next request
        # on a stale one fails with "Server disconnected without sending a
        # response" and the user got HTTP 502 (two knowledge turns in the test
        # run of 2026-10-06). One retry opens a fresh connection; a real outage
        # still raises.
        logger.warning("rag.retrieve: vector search failed (%s) — retrying once", e)
        return await vectorstore.search(vec, top_k=k, scheme=kb_scheme(scheme), sparse=sparse)


def _fuse(lists: list[list[dict]]) -> list[dict]:
    """Merge the result lists of several wordings by rank (reciprocal rank
    fusion, k=60): a piece several wordings find comes first. Each piece keeps
    its best meaning score."""
    acc: dict[tuple, dict] = {}
    for results in lists:
        for rank, c in enumerate(results, 1):
            key = (c.get("doc"), c.get("heading"), (c.get("text") or "")[:80])
            if key not in acc:
                acc[key] = {"piece": dict(c), "rrf": 0.0}
            acc[key]["rrf"] += 1.0 / (60 + rank)
            if c.get("score", 0.0) > acc[key]["piece"].get("score", 0.0):
                acc[key]["piece"]["score"] = c["score"]
    return [v["piece"] for v in sorted(acc.values(), key=lambda v: -v["rrf"])]


async def retrieve(question: str, scheme: str | None = None, expand: bool = True) -> list[dict]:
    """Return the reranked, score-filtered candidate chunks, best first.
    `scheme`, when given, restricts retrieval to that scheme's chunks.
    `expand` searches with other wordings of the question too (Phase 4)."""
    queries = [question] + (await _alt_queries(question, scheme) if expand else [])
    try:
        vecs = await llm.call_embedding(queries)
    except Exception as e:  # noqa: BLE001
        logger.warning("rag.retrieve: embedding failed — %s", e)
        return []
    # Phase 3 (2026-10-14): keyword search beside meaning search, and a wider
    # candidate pool when a re-ranker will pick the best of it.
    hybrid = settings.RAG_HYBRID_ENABLED and bool(settings.RAG_SPARSE_MODEL)
    k = settings.RAG_CANDIDATES if (hybrid or settings.RAG_LOCAL_RERANKER) else settings.RAG_TOP_K
    lists = [await _search_one(v, q, k, scheme) for v, q in zip(vecs, queries)]
    candidates = lists[0] if len(lists) == 1 else _fuse(lists)[:max(k, settings.RAG_RERANK_TOP_N)]
    if not candidates:
        return []

    # The local cross-encoder reads the question with each candidate and puts
    # the piece that answers it first. It only reorders: `score` stays the
    # meaning similarity the confidence tiers are tuned on.
    if settings.RAG_LOCAL_RERANKER and len(candidates) > 1:
        cut = settings.RAG_RERANK_CHARS or None
        scores = await local_rank.rerank(question, [c["text"][:cut] for c in candidates])
        if scores and len(scores) == len(candidates):
            ranked = sorted(zip(scores, range(len(candidates))), key=lambda x: -x[0])
            candidates = [dict(candidates[i], rerank_score=sc) for sc, i in ranked]

    # Reranker is opt-in — the deployed qwen3-reranker inverts relevance on this
    # KB, so by default we trust the embedding model's vector order directly.
    # RAG_MIN_SCORE is a real floor (2026-10-16): a piece below it never reaches
    # the composer. It used to fall back to the unfiltered top pieces when none
    # passed, so a question the KB does not cover was answered from unrelated text
    # (audit 2026-10-15: made-up rate 16%). Nothing kept -> "not covered".
    if not settings.RERANKER_ENABLED:
        return [c for c in candidates[: settings.RAG_RERANK_TOP_N]
                if c.get("score", 0.0) >= settings.RAG_MIN_SCORE]

    order = await llm.call_reranker(question, [c["text"] for c in candidates])
    reranked: list[dict] = []
    for idx, score in order[: settings.RAG_RERANK_TOP_N]:
        if 0 <= idx < len(candidates) and score >= settings.RAG_MIN_SCORE:
            c = dict(candidates[idx])
            c["score"] = score
            reranked.append(c)
    # Below the floor everywhere -> nothing (same rule as above; no fallback to
    # the raw vector order).
    return reranked


# ── Citations (RAG upgrade Phase 6, 2026-10-15) ──────────────────────────────
# "Source: PMAY-G FAQ › What documents are typically required" under a
# knowledge answer, so an officer can see where it came from. Built from the
# best-ranked pieces (the re-sorter puts the piece that answers first).

_SCHEME_TITLE = {"Focus Plus": "FOCUS+", "Focus Legacy": "FOCUS (Legacy)", "CM Elevate": "CM-ELEVATE"}


def _doc_title(doc: str, scheme: str) -> str:
    name = (doc or "").rsplit("/", 1)[-1].lower()
    s = _SCHEME_TITLE.get(scheme, scheme or "Scheme")
    if "wikipedia" in name or (doc or "").startswith("web/"):
        return f"{s} background (Wikipedia)"
    if "faq" in name:
        return f"{s} FAQ"
    if "reference" in name:
        return f"{s} Reference"
    stem = _rag_dash_runs_to_space(name.rsplit(".", 1)[0]).strip()
    return f"{s} — {stem}" if stem else s


def _rag_dash_runs_to_space(s: str) -> str:
    """Each run of '_' / '-' becomes one space."""
    out, prev = [], False
    for ch in s:
        if ch in "_-":
            if not prev:
                out.append(" ")
            prev = True
        else:
            out.append(ch)
            prev = False
    return "".join(out)


def _rag_drop_number_prefix(p: str) -> str:
    """Drop a leading section number — "3. ", "7.1 ", "2a) " — that is followed
    by whitespace; anything else is returned unchanged."""
    n = len(p)
    i = 0
    while i < n and p[i].isspace():
        i += 1
    j = i
    while j < n and p[j].isdecimal():
        j += 1
    if j == i:
        return p
    if j < n and "a" <= p[j] <= "z":
        j += 1
    while j + 1 < n and p[j] == "." and p[j + 1].isdecimal():
        j += 1
        while j < n and p[j].isdecimal():
            j += 1
    if j < n and p[j] in ".)":
        j += 1
    k = j
    while k < n and p[k].isspace():
        k += 1
    return p[k:] if k > j else p


def _section_title(heading: str) -> str:
    parts = [_rag_drop_number_prefix(p).strip()
             for p in (heading or "").split(">")]
    parts = [p for p in parts if p and p != "(intro)"] or ["Overview"]
    text = " › ".join(parts[-2:])
    return text if len(text) <= 80 else text[:77].rstrip() + "…"


def citations(chunks: list[dict], n: int = 2) -> list[dict]:
    """Up to `n` distinct {title, section} for the best-ranked pieces."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for c in chunks:
        title = _doc_title(c.get("doc", ""), c.get("scheme", ""))
        section = _section_title(c.get("heading", ""))
        key = (title, section.split(" › ")[0])
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "section": section})
        if len(out) >= n:
            break
    return out


# ── Sentence check (RAG upgrade Phase 5, 2026-10-15) ─────────────────────────
# The composer is told to use only the passages, but under sampling it still
# adds details they do not state (eval 2026-10-14: an "income certificate" in
# CM Elevate's documents list, "up to 100 days" for MGNREGA's "at least").
# After it writes, a second short call marks every sentence the passages do
# not support, and those sentences are dropped.

_RAG_SENTENCE_OPENERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\"'(*₹")


def _rag_split_sentences(text: str) -> list[str]:
    """Split after '.', '!' or '?' where whitespace and then an ASCII capital,
    an ASCII digit, a quote, '(', '*' or '₹' follow (the whitespace goes)."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i] in ".!?":
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j > i + 1 and j < n and text[j] in _RAG_SENTENCE_OPENERS:
                out.append(text[start:i + 1])
                start = i = j
                continue
        i += 1
    out.append(text[start:])
    return out


def _rag_is_bullet(s: str) -> bool:
    """Starts (after whitespace) with "-", "*", "•" or "12." / "3)" and then
    whitespace."""
    t = s.lstrip()
    if t[:1] in ("-", "*", "•"):
        return t[1:2].isspace()
    k = 0
    while k < len(t) and t[k].isdecimal():
        k += 1
    return k > 0 and t[k:k + 1] in (".", ")") and t[k + 1:k + 2].isspace()


def split_units(text: str) -> list[tuple[int, str]]:
    """(line number, unit) for each checkable unit of an answer: a bullet line
    is one unit; any other line splits at sentence ends."""
    units: list[tuple[int, str]] = []
    for li, line in enumerate((text or "").split("\n")):
        s = line.strip()
        if not s:
            continue
        if _rag_is_bullet(s):
            units.append((li, s))
            continue
        units += [(li, part.strip()) for part in _rag_split_sentences(s) if part.strip()]
    return units


_GROUND_SCHEMA = {"type": "object", "properties": {
    "unsupported": {"type": "array", "items": {"type": "integer"}}}, "required": ["unsupported"]}


def _drop_units(text: str, units: list[tuple[int, str]], drop: set[int]) -> str:
    kept: dict[int, list[str]] = {}
    for i, (li, u) in enumerate(units):
        if i not in drop:
            kept.setdefault(li, []).append(u)
    out: list[str] = []
    for li, line in enumerate(text.split("\n")):
        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        if li in kept:
            out.append(line if _rag_is_bullet(line.strip()) else " ".join(kept[li]))
    while out and out[-1] == "":
        out.pop()
    # An intro line ("The documents are:") left with nothing under it goes too.
    if out and out[-1].rstrip().endswith(":"):
        out.pop()
    return "\n".join(out).strip()


async def ground_answer(answer: str, passages: list[str]) -> str:
    """The answer without the sentences the passages do not support; "" when
    nothing of substance is left. Any failure keeps the answer as it is."""
    units = split_units(answer)
    if not units or not passages:
        return answer
    context = "\n\n---\n\n".join(p[:2500] for p in passages)
    numbered = "\n".join(f"[{i}] {u}" for i, (_, u) in enumerate(units))
    prompt = f"""Reference passages:
<<<
{context}
>>>

An answer written from those passages, one numbered sentence per line:
{numbered}

List the numbers of the sentences that state a fact the passages do NOT state or clearly imply —
an added number, amount, date, name, document, rule, condition or step.
These always count as supported: advice on where to confirm, ask or apply (Block office, Gram
Panchayat, official portal, helpline); a line that only introduces a list; a sentence that only
repeats the question or says what is not published.
Reply as JSON: {{"unsupported": [numbers]}}"""
    try:
        raw = await llm.call_model(
            base_url=settings.RESPONSE_MODEL_BASE_URL, model=settings.RESPONSE_MODEL,
            api_key=settings.RESPONSE_MODEL_API_KEY, prompt=prompt, temperature=0.0, max_tokens=120,
            timeout=settings.RAG_GROUNDING_TIMEOUT_SECONDS, role="rag_grounding",
            guided={"guided_json": _GROUND_SCHEMA} if settings.GUIDED_DECODING_ENABLED else None)
        idx = json.loads(_rag_json_object(raw)).get("unsupported") or []
        drop = {int(i) for i in idx if isinstance(i, (int, float)) and 0 <= int(i) < len(units)}
    except Exception as e:  # noqa: BLE001 — never lose an answer to the check itself
        logger.warning("rag: sentence check unavailable (%s) — answer kept", type(e).__name__)
        return answer
    if not drop:
        return answer
    kept = _drop_units(answer, units, drop)
    # Flagging EVERY sentence is the check misreading the passages, not the
    # composer inventing a whole answer: eval 2026-10-15 lost correct answers
    # that way ("56 C&RD Blocks statewide", Q132) and turned them into "not
    # covered". A question the documents do not answer is already caught
    # earlier (score floor, composer refusal), so the answer is kept.
    if not kept or _is_whole_refusal(kept):
        context_budget.log_decision("rag_grounding", removed=0, units=len(units), kept="all-flagged")
        return answer
    context_budget.log_decision("rag_grounding", removed=len(drop), units=len(units),
                                sentences=[units[i][1][:120] for i in sorted(drop)])
    return kept


_DOCS_QUESTION = Matcher(Alt(
    W("document", "documents", "docs", "paper", "papers", "proof", "proofs", "certificate", "certificates"),
    Seq("what", Alt(Seq("do", "i", sep="space"), Seq("should", "i", sep="space"), "to"),
        W("carry", "bring", "submit"), sep="space")))
_LIST_QUESTION = Matcher(Alt(
    _DOCS_QUESTION.node,
    Seq("how", W("do", "can", "should", "to", "does"),
        Opt(Alt(W("i", "we", "one", "someone"), Seq("a", ANY, sep="space"))),
        W("apply", "register", "enrol", "get"), sep="space"),
    Seq("application", W("process", "steps", "procedure"), sep="space"),
    W("steps")))
_DOCS_RULE = """
Documents question — split the list into two groups, each with its own short intro
line: "Required:" for documents the passages present as needed for everyone, and
"May also be asked for:" for those the passages qualify ("where required", "may",
"if applicable", "for urban groups", "any additional form"). Where the passages say a
document is NOT needed (e.g. "no income certificate is required"), add one closing
line saying so. Never move a document into "Required" that the passages qualify."""


async def answer_from_kb(question: str, scheme: str | None = None,
                         retrieval_query: str | None = None) -> dict | None:
    """Answer a scheme-knowledge question, or None if the KB doesn't cover it.
    `retrieval_query`, when given, is embedded for retrieval in place of the
    question (the answer is still written to `question`)."""
    chunks = await retrieve(retrieval_query or question, scheme=scheme)
    if not chunks:
        return None

    top = chunks[0]
    top_score = float(top.get("score", 0.0))
    # Re-ranked (Phase 3), the first piece is the one that answers best, not
    # necessarily the closest in meaning: whether there is enough to answer at
    # all is judged on the strongest piece kept.
    best_score = max(float(c.get("score", 0.0)) for c in chunks)
    sources = [{"doc": c["doc"], "heading": c["heading"],
                "source_type": c.get("source_type", "sme")} for c in chunks]

    # A documents or how-to-apply question is always composed, never the top
    # chunk verbatim: verbatim, MGNREGA's "documents?" was one run-on sentence
    # and nothing marked which documents are required (General TC-006, test
    # run 2026-10-09). The composer's list and required/optional rules apply.
    if top_score >= settings.RAG_HIGH_CONFIDENCE and not _LIST_QUESTION.search(question or ""):
        return {
            "answer": _strip_heading(top["text"]),
            "confidence": "high",
            "sources": sources[:1],
            "citations": citations(chunks, n=1),
        }

    if best_score >= settings.RAG_MEDIUM_CONFIDENCE:
        context = "\n\n---\n\n".join(_strip_heading(c["text"]) for c in chunks)
        docs_rule = _DOCS_RULE if _DOCS_QUESTION.search(question or "") else ""
        prompt = f"""{_naming_note(scheme)}Answer the question using ONLY the reference passages below. If they do
not contain the answer, say "That isn't covered in the scheme reference material."
Do not invent numbers, dates, or amounts. No Markdown headings ("#", "##", "###").
Speak to the user directly. Never mention "reference material", "passages",
"documents provided", "context" or a knowledge base in your answer; when a detail is
not published, say so plainly (e.g. "There is no single published checklist") and
say where to confirm it (the Block office, Gram Panchayat or the scheme portal).
Answer exactly what is asked: a "how to apply" question gets the application steps
in order, not a list of documents.{docs_rule}

Formatting — this is read in a chat bubble, so structure it for a quick scan:
- If the answer is a single fact, give it in one to two plain sentences.
- If the answer lists two or more items (schemes, sectors, steps, documents,
  eligibility conditions, etc.), use one short bullet per item on its own line,
  formatted exactly as "- **Item name** — one-line description", never a
  paragraph that runs items together in prose.
- Bold (**text**) only the item name being defined in each bullet, nothing else.
- Keep each bullet to one line. Put a blank line between an intro sentence and
  the bullets, and between the bullets and any closing sentence.

Question: "{question}"

Reference passages:
{context}

Answer:"""
        context_budget.log_prompt_context(
            "compose", [("retrieved_passages", context), ("question", question)],
            prompt=prompt, route="rag", chunks=len(chunks))
        answer = await llm.call_response_composer(prompt)
        # The composer sometimes answers correctly AND tacks on a stray
        # "that isn't covered..." hedge sentence (about some tangential detail
        # it wasn't asked for) even though the actual question was answered in
        # full from the passages above it. A blind substring check on the
        # whole answer used to discard that entire good answer whenever the
        # phrase appeared anywhere — strip just the refusal sentence instead,
        # and only treat it as "no answer" when nothing substantive remains.
        cleaned = _rag_strip_refusal(answer).strip()
        if cleaned and _is_whole_refusal(cleaned):
            cleaned = ""
        if not cleaned:
            # Not just a stray hedge sentence — the composer refused outright.
            # Runs at non-zero temperature, so on passages that genuinely do
            # answer the question this is sometimes just a bad sample: verified
            # directly on CM Elevate's intro chunk at top_score ~0.77 (well
            # above RAG_MEDIUM_CONFIDENCE) — the identical prompt outright
            # refused twice in one run, then answered correctly on the next
            # sample with no code change. One retry on the same (already-good)
            # context is cheap; a second outright refusal is trusted as real.
            answer = await llm.call_response_composer(prompt)
            cleaned = _rag_strip_refusal(answer).strip()
            if cleaned and _is_whole_refusal(cleaned):
                cleaned = ""
            if not cleaned:
                return None
        if settings.RAG_GROUNDING_CHECK:
            cleaned = await ground_answer(cleaned, [c["text"] for c in chunks])
            if not cleaned or _is_whole_refusal(cleaned):
                return None
        return {
            "answer": _clean_for_display(cleaned),
            "confidence": "high" if top_score >= settings.RAG_HIGH_CONFIDENCE else "medium",
            "sources": sources,
            "citations": citations(chunks),
        }

    logger.info("rag.answer_from_kb: best score %.3f below medium floor — no answer", best_score)
    return None


async def answer_from_kb_multi(question: str, schemes: list[str]) -> dict | None:
    """A KNOWLEDGE question that names two or more schemes outright ("how do I
    apply across MGNREGA, PMAY-G, Focus Plus and CM Elevate"). A single
    unscoped `retrieve()` pulls RAG_TOP_K candidates from the whole KB in one
    shot, so whichever scheme's passages happen to embed closest to the
    question crowd out the others — a named scheme with real reference
    material can come back "not covered" simply because its chunks never made
    the cut. Retrieve each named scheme separately instead, then compose one
    answer that addresses every scheme that had material."""
    # Schemes sharing one knowledge base (CM Elevate + CM Elevate Legacy) are
    # retrieved ONCE, under one header naming both — retrieving per scheme
    # would put the same passages in twice and invite two identical answers.
    groups: dict[str, list[str]] = {}
    for s in schemes:
        groups.setdefault(kb_scheme(s), []).append(s)
    per_scheme: dict[str, list[dict]] = {}
    covered: set[str] = set()
    for kb, members in groups.items():
        chunks = await retrieve(question, scheme=kb)
        if chunks:
            per_scheme[" / ".join(members)] = chunks[:4]  # cap so the composer isn't flooded
            covered.update(members)

    if not per_scheme:
        return None

    sections = []
    sources = []
    # One citation per scheme answered: its best piece.
    cites = [c for chunks in per_scheme.values() for c in citations(chunks, n=1)]
    for s, chunks in per_scheme.items():
        body = "\n\n".join(_strip_heading(c["text"]) for c in chunks)
        sections.append(f"=== {s} ===\n{body}")
        sources.extend({"doc": c["doc"], "heading": c["heading"],
                         "source_type": c.get("source_type", "sme")} for c in chunks)
    context = "\n\n---\n\n".join(sections)

    prompt = f"""Answer the question using ONLY the reference passages below, which are
grouped by scheme under "=== SchemeName ===" headers. Answer separately for EVERY
scheme that has a section below — do not skip one, and do not invent an answer
for a scheme that has no section. Do not invent numbers, dates, or amounts.
No Markdown headings ("#", "##", "###").

Formatting — one short bullet per scheme, formatted exactly as
"- **SchemeName** — one or two sentence answer", one bullet per line.

Question: "{question}"

Reference passages:
{context}

Answer:"""
    context_budget.log_prompt_context(
        "compose", [("retrieved_passages", context), ("question", question)],
        prompt=prompt, route="rag_multi", chunks=len(sources))
    answer = await llm.call_response_composer(prompt)
    cleaned = _rag_strip_refusal(answer).strip()
    if cleaned and _is_whole_refusal(cleaned):
        cleaned = ""
    if not cleaned:
        # Same one-retry tolerance as answer_from_kb — a non-zero-temperature
        # outright refusal on passages that do answer the question is
        # sometimes just a bad sample.
        answer = await llm.call_response_composer(prompt)
        cleaned = _rag_strip_refusal(answer).strip()
        if cleaned and _is_whole_refusal(cleaned):
            cleaned = ""
        if not cleaned:
            return None

    missing = [s for s in schemes if s not in covered]
    if missing:
        cleaned += ("\n\nI don't have published information covering this for "
                    f"{', '.join(missing)}.")

    return {
        "answer": _clean_for_display(cleaned),
        "confidence": "medium",
        "sources": sources,
        "citations": cites,
    }
