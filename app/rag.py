"""
RAG path — answers general scheme-knowledge questions from the data/
narrative docs (see kb_ingest.py), never from the database.

Flow (the NeuralAiGovernanceProject standard, adapted to Qdrant + qwen3):
  1. embed the question           -> qwen3-embedding
  2. vector search the KB         -> Qdrant, RAG_TOP_K candidates
  3. rerank the candidates        -> qwen3-reranker, ALWAYS (D-083), fused
                                     with the vector order; keep RAG_RERANK_TOP_N
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
from app.text_match import ANY, Alt, Hit, Matcher, Opt, Seq, W, numbers, split_sentences, tokens, words

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
    "CMSS": ("CMSS", "CMSS (the Chief Minister's Scholarship Scheme) pays a flat Rs 6,000 a year to eligible students; it is a state scholarship, not the CM Elevate enterprise programme."),
    # keyed by the scheme name (as "CM Elevate Legacy"), not the KB tag "Home Stay"; the label = scheme_registry doc_label
    "Homestay": ("Homestay", "Homestay (the Chief Minister's Meghalaya Homestay Mission, Tourism Department) supports building a new homestay or upgrading an existing one; this data is its online applications from October 2025, not the older Homestay Legacy bank loans"),
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
    # KR6 (knowledge fix 2026-10-29): what it is beside its namesakes
    from app.scheme_registry import KNOWLEDGE_DISTINCTIONS
    if scheme in KNOWLEDGE_DISTINCTIONS:
        note += " " + KNOWLEDGE_DISTINCTIONS[scheme]
    return note + "\n\n"


# Schemes that are different DATASETS of one programme share ONE knowledge base.
# CM Elevate (applications) and CM Elevate Legacy (sanctions and disbursements)
# are both the CM-ELEVATE programme: its eligibility, benefits, sub-schemes and
# application process are the same whichever dataset a user is looking at, so
# both read the same reference docs — stored under "CM Elevate" (kb_ingest folds
# a Legacy-tagged doc into that tag too). The vector filter is an exact match,
# so every retrieval goes through kb_scheme(). Every other scheme maps to itself.
# Homestay (onboarded 2026-11-12): its documents are tagged "Home Stay" in megh_knowledge (39 pieces,
# shared with Home Stay Legacy); a filter on "Homestay" matched none.
_KB_SCHEME_ALIAS = {"CM Elevate Legacy": "CM Elevate", "Homestay": "Home Stay"}


def kb_scheme(scheme: str | None) -> str | None:
    """The knowledge-base tag a scheme's reference material is stored under."""
    return _KB_SCHEME_ALIAS.get(scheme, scheme) if scheme else scheme


_KB_SCHEMES = ("MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate", "CMSS", "Home Stay")

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
                # megh_knowledge tags a piece with a LIST of schemes, and keeps
                # CM Elevate Legacy's own tag (D-074): each tag counts, under
                # the knowledge base it is searched by (kb_scheme).
                for tag in vectorstore.scheme_tags(pl) or [""]:
                    out.setdefault(kb_scheme(tag) or "", []).append(str(pl.get("text", "")).lower())
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
        logger.warning("rag.retrieve: vector search failed (%s) — retrying", e)
    # Two retries, a short pause before the second: with a question's searches run in
    # parallel (2026-10-29) several pooled connections can be stale at once, and the
    # first retry met another one (golden run final4, CK-CL1).
    try:
        return await vectorstore.search(vec, top_k=k, scheme=kb_scheme(scheme), sparse=sparse)
    except Exception as e:  # noqa: BLE001
        logger.warning("rag.retrieve: vector search failed again (%s) — last retry", e)
        await asyncio.sleep(0.3)
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


# ── Multi-part questions, related facts, Hinglish, FAQ match (knowledge fix 2026-10-29) ──
# KR3: "When and where was Focus Plus launched, and how much does it pay?" and "When was
# PMAY-G launched, and what did it replace?" lost a part: one search for the whole
# question finds the piece that answers its first part. Each part is searched on its own
# too (_sub_asks), and a launch / amount / sub-scheme question also searches the piece
# that holds the related key facts (_RAG_FACETS), so the composer has them.
# The searches of one question run in parallel (KR13), but never more than this many at
# once across the whole worker: unbounded, two eval runs side by side got "Server
# disconnected" / read timeouts from the shared Qdrant (2026-10-29).
_RAG_SEARCH_SLOTS = 6
_rag_search_sems: "dict[int, asyncio.Semaphore]" = {}   # one per event loop


async def _bounded_search(vec: list[float], text: str, k: int, scheme: str | None) -> list[dict]:
    loop_id = id(asyncio.get_running_loop())
    sem = _rag_search_sems.get(loop_id)
    if sem is None:
        _rag_search_sems.clear()          # a new loop (tests, a restart): drop the old one
        sem = _rag_search_sems[loop_id] = asyncio.Semaphore(_RAG_SEARCH_SLOTS)
    async with sem:
        return await _search_one(vec, text, k, scheme)


_RAG_ASK_OPENERS = frozenset("when where who whom what which how is are does do can why whose".split())


def _sub_asks(question: str) -> list[str]:
    """The parts of a question that asks two or more things ("when and where was X
    launched, and how much does it pay?"), each with a question word; [] for one ask."""
    q = (question or "").strip()
    parts: list[str] = []
    for chunk in q.replace("?", "?\n").replace(";", "\n").split("\n"):
        for piece in chunk.split(","):
            for sub in _rag_split_on_and(piece):
                sub = sub.strip(" ,.?")
                first = (sub.split() or [""])[0].lower()
                if first in ("and", "also", "or", "plus"):   # "…launched, and how much…"
                    sub = sub[len(first):].strip()
                if len(sub.split()) >= 2 and words(sub)[:1] and words(sub)[0] in _RAG_ASK_OPENERS:
                    parts.append(sub + "?")
    return parts if len(parts) >= 2 else []


def _rag_split_on_and(text: str) -> list[str]:
    """`text` split at each " and " that starts a new ask ("…launched, and how much…");
    "when and where" stays one ask."""
    toks = tokens(text)
    cuts = [t for i, t in enumerate(toks)
            if t.low == "and" and i + 1 < len(toks) and toks[i + 1].low in _RAG_ASK_OPENERS
            and i >= 2]
    out, start = [], 0
    for t in cuts:
        out.append(text[start:t.start])
        start = t.end
    out.append(text[start:])
    return out


# (what the question asks about, the search for the piece holding it, the related key
# facts the composer adds in one line when the passages state them)
_RAG_FACETS = (
    (Matcher(W("launch", "launched", "start", "started", "introduced", "began", "enacted", "shuru")),
     "launched on date at place by whom, ministry or department, scheme it replaced",
     "a launch question also gets the place, who launched it, the ministry or department and the "
     "scheme it replaced"),
    (Matcher(Alt(Seq("how", "much"), W("pay", "pays", "amount", "assistance", "money", "paisa", "kitna"))),
     "amount per household or per member, paid by DBT or instalments, grant or loan",
     "a benefit-amount question also gets how it is paid (e.g. DBT), whether it is per household or "
     "per member, and whether it is a grant or a loan"),
    (Matcher(Alt(W("subsidy", "subscheme", "subschemes", "sectors"), Seq("sub", "schemes"))),
     "capital subsidy percentage and number of sub-schemes covered",
     "a subsidy or sub-scheme question also gets how many sub-schemes the programme has"),
    (Matcher(W("document", "documents", "docs", "papers", "paper", "proof", "proofs", "certificate",
               "certificates", "kagaz")),
     "required documents for application and registration", ""),
    (Matcher(Alt(W("eligible", "eligibility", "beneficiaries", "beneficiary", "benficiaries", "intended",
                   "qualify", "census", "secc", "missed", "excluded"), Seq("who", "can"), Seq("left", "out"))),
     "who is eligible, beneficiary identification and selection", ""),
    (Matcher(Alt(W("apply", "applying", "register", "registration", "enrol", "enroll"), Seq("sign", "up"))),
     "how to apply, registration steps and application",
     "a how-to-apply question starts from the very first step (registering, or getting the card "
     "the passages say is needed first) and gives the rest in order"),
)
# MGNREGA: applying means getting a job card first ("How do I apply?" was answered with
# the demand-for-work steps only; RAG eval Q032, gold "How do I apply for a job card?").
_RAG_FACET_EXTRA = {("MGNREGA", "how to apply, registration steps and application"):
                    " job card registration with photograph at the Gram Panchayat"}


# A scheme's own first step, said in its FAQ ("How do I apply for a job card?"), for a
# bare how-to-apply question.
_RAG_APPLY_FIRST = {"MGNREGA": "for MGNREGA the first step is the household's job card: an adult member "
                               "applies to the Gram Panchayat (a simple form with a photograph) and the card "
                               "is issued within 15 days, free; only a registered household then applies "
                               "for work"}


def _facets(question: str) -> list[tuple[str, str]]:
    return [(query, line) for m, query, line in _RAG_FACETS if m.search(question or "")]


def _facet_queries(question: str, scheme: str | None) -> list[str]:
    if not scheme:
        return []
    name = _SCHEME_DOC_NAMES.get(scheme, (scheme, scheme))[0]
    return [f"{name} {query}{_RAG_FACET_EXTRA.get((scheme, query), '')}" for query, _ in _facets(question)]


# KR11: "awas yojana gramin kab shuru hui?" found no launch piece (best 0.42, wrong
# pieces) and was answered "the launch date is not published". Romanised Hindi is not
# caught by translate.script_language (a script check); one of these common words is
# enough to add an English wording of the question to the search.
_RAG_HINGLISH = Matcher(W(
    "kab", "kya", "kitna", "kitne", "kitni", "kaise", "kaun", "kaunsa", "kahan", "kyun", "kyon", "hai", "hain",
    "hui", "hua", "milta", "milte", "milega", "milegi", "shuru", "paisa", "paise", "din", "kaam", "ke", "ki",
    "ka", "mein", "me", "nahi", "deta", "deti", "dete", "yojana", "chahiye", "karna", "karein", "wala"))


def _looks_hinglish(question: str) -> bool:
    return len(_RAG_HINGLISH.findall(question or "")) >= 2


async def _english_wording(question: str) -> str | None:
    try:
        from app import translate as _rag_tr
        out = await _rag_tr.to_english(question, "hi")   # Hindi, here in Latin letters
    except Exception as e:  # noqa: BLE001 — search with the question alone
        logger.info("rag: English wording unavailable (%s)", type(e).__name__)
        return None
    out = (out or "").strip()
    return out if out and out.lower() != (question or "").strip().lower() else None


# KR12: an FAQ piece whose own question IS the officer's question ("Is Common Facility
# Centre part of CM Elevate?" -> 'Is "Common Facility Centre (CFC)" a CM-ELEVATE
# scheme?') goes first, and the composer is told it is that entry: the CFC answer
# followed a reference table instead and said "one of its 15 sub-schemes", which the
# FAQ entry says it is not (in the data). Matched on content words (5-letter stems),
# scheme names left out.
_FAQ_MATCH_SHARE = 0.75


def _rag_stems(text: str) -> set[str]:
    out = set()
    for w in words(text):
        if len(w) > 2 and w not in _STOP and w not in _FAQ_NAME_WORDS:
            out.add(_FAQ_SAME_STEM.get(w[:5], w[:5]))
    return out


# scheme names (the pieces are already filtered by scheme) and filler words
_FAQ_NAME_WORDS = frozenset("""mgnrega nrega mgnregs pmay pmayg gramin awaas focus plus legacy elevate cm
meghalaya under part exactly actually really specific intended context""".split())
# "who are the intended beneficiaries" asks "who is eligible" (RAG eval Q184)
_FAQ_SAME_STEM = {"benef": "eligi", "benfi": "eligi", "quali": "eligi"}


def _faq_match(question: str, chunks: list[dict]) -> int | None:
    """Index of the FAQ piece whose heading asks the same thing as `question`."""
    q = _rag_stems(question)
    if not q:
        return None
    best, best_share = None, 0.0
    for i, c in enumerate(chunks):
        heading = (c.get("heading") or "").split(">")[-1].strip()
        if not heading.endswith("?"):
            continue
        h = _rag_stems(heading)
        share = len(q & h) / len(q)
        # ...and the heading is not mostly about something else: "How do I apply?" is not
        # "What documents are needed to apply for MGNREGA?" (one word of three)
        # (or the question is one short acronym the heading spells out: "Is CFC a CM
        # Elevate scheme?")
        if share >= _FAQ_MATCH_SHARE and share > best_share and h and (
                len(q & h) / len(h) >= 0.4 or (q <= h and min(len(x) for x in q) <= 4)):
            best, best_share = i, share
    return best


async def retrieve(question: str, scheme: str | None = None, expand: bool = True,
                   english: str | None = None) -> list[dict]:
    """Return the reranked, score-filtered candidate chunks, best first.
    `scheme`, when given, restricts retrieval to that scheme's chunks.
    `expand` searches with other wordings of the question too (Phase 4), each
    part of a multi-part question, the related-facts piece (KR3) and an English
    wording of a Hinglish question (KR11)."""
    queries = [question] + (await _alt_queries(question, scheme) if expand else [])
    asks = _sub_asks(question)
    rank_q = question
    if expand:
        queries += [a if scheme is None or _rag_has_term(a.lower(), scheme.lower()) else f"{a} ({scheme})"
                    for a in asks]
        queries += _facet_queries(question, scheme)
        if english or _looks_hinglish(question):
            eng = english or await _english_wording(question)
            if eng:
                queries += [eng] + _facet_queries(eng, scheme)
                rank_q = eng
    queries = list(dict.fromkeys(queries))
    try:
        vecs = await llm.call_embedding(queries)
    except Exception as e:  # noqa: BLE001
        logger.warning("rag.retrieve: embedding failed — %s", e)
        return []
    # Phase 3 (2026-10-14): keyword search beside meaning search.
    hybrid = settings.RAG_HYBRID_ENABLED and bool(settings.RAG_SPARSE_MODEL)
    k = settings.RAG_CANDIDATES if hybrid else settings.RAG_TOP_K
    lists = list(await asyncio.gather(*(_bounded_search(v, q, k, scheme) for v, q in zip(vecs, queries))))
    # a multi-part question needs room for each part's piece (KR3)
    top_n = settings.RAG_RERANK_TOP_N + (4 if asks else 0)
    candidates = lists[0] if len(lists) == 1 else _fuse(lists)[:max(k, top_n)]
    if not candidates:
        return []

    candidates = await _rerank(rank_q, candidates)

    # RAG_MIN_SCORE is a real floor (2026-10-16): a piece below it never reaches
    # the composer. It used to fall back to the unfiltered top pieces when none
    # passed, so a question the KB does not cover was answered from unrelated text
    # (audit 2026-10-15: made-up rate 16%). Nothing kept -> "not covered".
    kept = [c for c in candidates[:top_n] if c.get("score", 0.0) >= settings.RAG_MIN_SCORE]
    faq = _faq_match(rank_q, kept)
    if faq is not None:
        kept = [dict(kept[faq], faq_match=True)] + kept[:faq] + kept[faq + 1:]
    context_budget.log_decision("rag_retrieve", queries=len(queries), sub_asks=len(asks),
                                faq_match=faq is not None, kept=len(kept))
    return kept


async def _rerank(question: str, candidates: list[dict]) -> list[dict]:
    """Every knowledge question is re-ranked by qwen3-reranker (D-083,
    2026-10-29; user rule: the re-ranker is never switched off — there is no
    setting for it). Its order is fused with the vector order by rank (RRF,
    k=60), not used on its own: on megh_knowledge (137 eval questions, top 12)
    right piece first was vector 60.2%, reranker alone 55.6%, fused 62.4%; in
    the top 3 82.7% / 83.5% / 88.0%. `score` stays the meaning (cosine)
    similarity the floor and confidence tiers are tuned on — the deployed
    reranker scores nearly every piece 0.99+, so its score is no cut-off;
    it is kept as `rerank_score`. A gateway failure keeps the vector order for
    this one question and logs a warning; the answer is still given."""
    if len(candidates) < 2:
        return candidates
    try:
        order = await llm.call_reranker(question, [c["text"] for c in candidates])
    except Exception as e:  # noqa: BLE001
        logger.warning("rag.rerank: qwen3-reranker failed (%s: %s) — vector order kept for this question",
                       type(e).__name__, e)
        return candidates
    rerank_score = {idx: sc for idx, sc in order if 0 <= idx < len(candidates)}
    fused = {i: 1.0 / (60 + i + 1) for i in range(len(candidates))}
    for pos, (idx, _sc) in enumerate(order, 1):
        if idx in fused:
            fused[idx] += 1.0 / (60 + pos)
    ranked = sorted(fused, key=lambda i: -fused[i])
    return [dict(candidates[i], rerank_score=rerank_score.get(i, 0.0)) for i in ranked]


# ── Citations (RAG upgrade Phase 6, 2026-10-15) ──────────────────────────────
# "Source: PMAY-G FAQ › What documents are typically required" under a
# knowledge answer, so an officer can see where it came from. Built from the
# best-ranked pieces (the re-sorter puts the piece that answers first).

_SCHEME_TITLE = {"Focus Plus": "FOCUS+", "Focus Legacy": "FOCUS (Legacy)", "CM Elevate": "CM-ELEVATE", "CMSS": "CMSS", "Homestay": "Homestay"}


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


def _supporting_chunks(answer: str, chunks: list[dict]) -> list[dict]:
    """The pieces the answer's sentences come from, in order of first use (KR4,
    knowledge fix 2026-10-29): K2's sources listed "What happens if authorities delay
    wage payment?" under an unemployment-allowance answer, because sources were the
    top pieces retrieved, not the pieces used. Each sentence is credited to the piece
    holding most of its content words (and all its numbers); a piece no sentence
    leans on is not cited. The best-ranked piece when nothing matches."""
    if not chunks:
        return []
    facts = [(_rag_unit_numbers(c.get("text", "")), _rag_stems(c.get("text", ""))) for c in chunks]
    used: list[int] = []
    for _, unit in split_units(answer):
        own, own_n = _rag_stems(unit), _rag_unit_numbers(unit)
        if len(own) < 3:
            continue
        best, best_share = None, 0.5
        for i, (nums, stems) in enumerate(facts):
            if own_n - nums:
                continue
            share = len(own & stems) / len(own)
            if share > best_share:
                best, best_share = i, share
        if best is not None and best not in used:
            used.append(best)
    return [chunks[i] for i in used] or chunks[:1]


def citations(chunks: list[dict], n: int = 2) -> list[dict]:
    """Up to `n` distinct {title, section} for the best-ranked pieces."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for c in chunks:
        # megh_knowledge names each document itself (doc_title, D-074); the
        # app's own pieces fall back to a title built from the file name
        title = c.get("title") or _doc_title(c.get("doc", ""), c.get("scheme", ""))
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
            # not after an initial: "Conrad K. Sangma" is one sentence (the check had kept
            # only "Sangma." — 2026-10-29)
            initial = i >= 1 and text[i - 1].isupper() and (i == 1 or not text[i - 2].isalnum())
            if j > i + 1 and j < n and text[j] in _RAG_SENTENCE_OPENERS and not initial:
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


def _rag_unit_numbers(text: str) -> set[str]:
    """The numbers in `text`, commas dropped (1,20,000 -> 120000; 35% -> 35)."""
    return {n.replace(",", "") for n in numbers(text or "")}


_RAG_SPELT = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
_RAG_SPELT.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
                   "eighty": "80", "ninety": "90", "hundred": "100"})


def _question_numbers(question: str) -> set[str]:
    """The numbers the officer typed, in digits or words ("fifty lakh" -> 50; RAG eval Q072
    lost "you are asking for ₹50 lakh" to the number rule)."""
    spelt = {_RAG_SPELT[w] for w in words(question) if w in _RAG_SPELT}
    return _rag_unit_numbers(question) | spelt


def _passage_facts(passages: list[str]) -> tuple[set[str], set[str]]:
    joined = "\n".join(passages)
    return _rag_unit_numbers(joined), _rag_stems(joined)


def _rag_unit_supported(unit: str, nums: set[str], stems: set[str]) -> bool:
    if _rag_unit_numbers(unit) - nums:
        return False
    own = _rag_stems(unit)
    return bool(own) and len(own & stems) / len(own) >= 0.8


async def ground_answer(answer: str, passages: list[str], question: str = "") -> str:
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
        drop = set()
    # KR5 (knowledge fix 2026-10-29), checked on the words, not by the model: a unit
    # whose every number is in the passages and whose content words mostly are is
    # supported — the check had dropped "FOCUS was launched in 2021, with sources citing
    # March or September 2021", leaving only "please confirm the exact date"; and a
    # unit with a number or date no passage holds is dropped, whatever the check said.
    nums, stems = _passage_facts(passages)
    # a number the officer typed may be repeated ("whether it rises from ₹2.5 lakh to ₹5 lakh
    # for 2025-26 is not published" — RAG eval Q118 lost that honest sentence)
    nums |= _question_numbers(question)
    # The check flagging EVERY sentence is it misreading the passages (see below): keep them
    # all, as before; only the number rule still applies then.
    if len(drop) == len(units):
        drop = set()
    rescued = {i for i in drop if _rag_unit_supported(units[i][1], nums, stems)}
    invented = {i for i, (_, u) in enumerate(units) if _rag_unit_numbers(u) - nums}
    model_drop = drop - rescued
    drop = model_drop | invented
    if rescued or invented:
        context_budget.log_decision("rag_grounding_words", rescued=len(rescued), invented=len(invented))
    if not drop:
        return answer
    kept = _drop_units(answer, units, drop)
    # the number rule must not empty the answer (passages that spell the figures out in
    # words): then only the model's own verdicts are applied
    if (not kept or _is_whole_refusal(kept)) and invented and model_drop:
        drop = model_drop
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


# Knowledge fix 2026-10-29. KR3: K5 "When was PMAY-G launched, and what did it replace?"
# left out the ministry and K9 left out the 15 sub-schemes, both in the passages; a
# multi-part question dropped parts. KR12: the FAQ entry for the very question goes
# first and wins (CFC). KR5: one scheme's facts never answer another; national rules
# and Meghalaya's own details are kept apart. Deterministic backstops: _sub_asks in
# retrieve, the number check in ground_answer, tests/live_chat_knowledge.py.
_RELATED_FACTS_RULE = """
Answer every part of the question, opening with what the passages DO say. Only for a
part they do not answer at all, add one short closing sentence that this detail is not
published in the scheme documents; never open with what is missing, and never drop a
part silently.
Keep national rules (the Act, central guidelines) apart from Meghalaya's own details,
and never state one scheme's facts as another scheme's."""
_FAQ_FIRST_RULE = """
The passages open with the OFFICIAL FAQ ANSWER to this very question. Open your answer
by restating its facts — every date, number, name and qualification in it ("but",
"not", "only"); background passages may add detail but never overrule it."""


# KR3 backstop, on the words: the related-facts rule is prose and fails under sampling
# (K5 "When was PMAY-G launched, and what did it replace?" lost the ministry in 1 of 2
# live runs, 2026-10-29). For a launch question whose passages name exactly ONE
# "Ministry of ..." and an answer that names none, that ministry is added in one line,
# word for word from the passages.
def _passage_ministries(chunks: list[dict]) -> set[str]:
    found: set[str] = set()
    for c in chunks:
        text = c.get("text") or ""
        toks = tokens(text)
        for i, t in enumerate(toks[:-2]):
            if t.raw == "Ministry" and toks[i + 1].low == "of":
                name, j = ["Ministry", "of"], i + 2
                # (stops at punctuation: "...Rural Development. The Union Cabinet")
                while j < len(toks) and (toks[j].raw[:1].isupper() or toks[j].low == "and") \
                        and not any(ch in ".,;:()" for ch in text[toks[j - 1].end:toks[j].start]):
                    name.append(toks[j].raw)
                    j += 1
                while name and name[-1] == "and":
                    name.pop()
                if len(name) > 2:
                    found.add(" ".join(name))
    return found


# Same backstop for the other two facts the composer dropped in some live runs only
# (2026-10-29): the matched FAQ entry's own dates and numbers (CFC "notified 11 March
# 2024"), and a programme's sub-scheme count for a subsidy / sub-scheme question (K9).
_RAG_COUNT_NOUNS = frozenset({"sub", "subscheme", "subschemes", "schemes", "sectors"})
_RAG_NUMBER_WORDS = {"fifteen": "15", "twelve": "12", "ten": "10", "twenty": "20"}


def _with_faq_facts(answer: str, chunks: list[dict]) -> str:
    if not chunks or not chunks[0].get("faq_match"):
        return answer
    have = _rag_unit_numbers(answer)
    adds = []
    for sentence in split_sentences(_strip_heading(chunks[0].get("text") or "")):
        nums = _rag_unit_numbers(sentence)
        if nums and not nums <= have and len(adds) < 2:
            adds.append(sentence.strip())
            have |= nums
    if not adds:
        return answer
    text = " ".join(adds)
    context_budget.log_decision("rag_related_fact", added="faq_numbers")
    return f"{answer.rstrip()}\n\nFrom the scheme FAQ: {text[:1].lower()}{text[1:]}"


def _passage_subscheme_counts(chunks: list[dict]) -> set[str]:
    counts: set[str] = set()
    for c in chunks:
        toks = tokens(c.get("text") or "")
        for i, t in enumerate(toks):
            n = _RAG_NUMBER_WORDS.get(t.low) or (t.raw if t.raw.isdigit() and len(t.raw) <= 3 else None)
            if n is None:
                continue
            # "8,823 applicant records across 13 sub-schemes" counts the DATA, not the
            # programme's design (the FAQ: "Fifteen") — not a programme count
            if {x.low for x in toks[max(0, i - 4):i]} & {"records", "record", "applicant", "applications"}:
                continue
            after = [x.low for x in toks[i + 1:i + 3]]
            # "15 sub-schemes", "15 covered sectors"; the FAQ's "Fifteen. Publicly announced ..."
            if any(w in _RAG_COUNT_NOUNS for w in after) or (t.low in _RAG_NUMBER_WORDS and after[:1] == ["publicly"]):
                counts.add(n)
    return counts


def _with_subscheme_count(question: str, answer: str, chunks: list[dict]) -> str:
    if not _RAG_FACETS[2][0].search(question or ""):
        return answer
    counts = _passage_subscheme_counts(chunks)
    if len(counts) != 1:
        return answer
    n = next(iter(counts))
    words_in = set(words(answer))
    if n in _rag_unit_numbers(answer) or any(w in words_in for w, d in _RAG_NUMBER_WORDS.items() if d == n):
        return answer
    context_budget.log_decision("rag_related_fact", added="subscheme_count")
    return f"{answer.rstrip()}\n\nThe programme covers {n} sub-schemes."


def _with_related_ministry(question: str, answer: str, chunks: list[dict]) -> str:
    if not _RAG_FACETS[0][0].search(question or "") or "ministry" in (answer or "").lower():
        return answer
    ministries = _passage_ministries(chunks)
    if len(ministries) != 1:
        return answer
    context_budget.log_decision("rag_related_fact", added="ministry")
    return f"{answer.rstrip()}\n\nIt is implemented by the {next(iter(ministries))}."


def _completeness_rule(question: str, chunks: list[dict], scheme: str | None = None) -> str:
    rule = _RELATED_FACTS_RULE
    lines = [line for _, line in _facets(question) if line]
    if scheme in _RAG_APPLY_FIRST and any(q.startswith("how to apply") for q, _ in _facets(question)):
        lines.append(_RAG_APPLY_FIRST[scheme])
    if lines:
        rule += ("\nAdd closely related key facts in one short line, only when the passages state "
                 "them: " + "; ".join(lines) + ".")
    asks = _sub_asks(question)
    if asks:
        rule += "\nThe parts to answer: " + " | ".join(asks)
    if chunks and chunks[0].get("faq_match"):
        rule += _FAQ_FIRST_RULE
    return rule


async def answer_from_kb(question: str, scheme: str | None = None,
                         retrieval_query: str | None = None) -> dict | None:
    """Answer a scheme-knowledge question, or None if the KB doesn't cover it.
    `retrieval_query`, when given, is embedded for retrieval in place of the
    question (the answer is still written to `question`)."""
    # KR11: a romanised-Hindi question is searched AND answered with its English wording
    # beside it ("narega me kitne din kaam milta hai?" was answered "within 15 days")
    english = await _english_wording(question) if not retrieval_query and _looks_hinglish(question) else None
    chunks = await retrieve(retrieval_query or question, scheme=scheme, **({"english": english} if english else {}))
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
        if chunks[0].get("faq_match"):
            # KR12: the FAQ entry for this very question, set apart so it is read as the
            # answer and the rest as background (CFC, knowledge fix 2026-10-29)
            context = (f"OFFICIAL FAQ ANSWER — {(chunks[0].get('heading') or '').split('>')[-1].strip()}\n"
                       f"{_strip_heading(chunks[0]['text'])}\n\n=== Background passages ===\n\n"
                       + "\n\n---\n\n".join(_strip_heading(c["text"]) for c in chunks[1:]))
        docs_rule = _DOCS_RULE if _DOCS_QUESTION.search(question or "") else ""
        extra_rules = _completeness_rule(question, chunks, scheme)
        docs_rule += extra_rules
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

Question: "{question}"{f' (in English: "{english}")' if english else ""}

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
            # ...without the knowledge-fix rules (D-094): they must never cause a refusal the
            # plain prompt would not ("…launched together at the same gatherings?", RAG eval Q108)
            answer = await llm.call_response_composer(prompt.replace(extra_rules, "", 1))
            cleaned = _rag_strip_refusal(answer).strip()
            if cleaned and _is_whole_refusal(cleaned):
                cleaned = ""
            if not cleaned:
                return None
        if settings.RAG_GROUNDING_CHECK:
            cleaned = await ground_answer(cleaned, [c["text"] for c in chunks], question)
            if not cleaned or _is_whole_refusal(cleaned):
                return None
        shown = _clean_for_display(cleaned)
        # deterministic backstops for the related facts the composer may drop (KR3, KR12)
        shown = _with_faq_facts(shown, chunks)
        shown = _with_subscheme_count(question, _with_related_ministry(question, shown, chunks), chunks)
        used = _supporting_chunks(shown, chunks)
        return {
            "answer": shown,
            "confidence": "high" if top_score >= settings.RAG_HIGH_CONFIDENCE else "medium",
            "sources": [{"doc": c["doc"], "heading": c["heading"], "source_type": c.get("source_type", "sme")}
                        for c in used],
            "citations": citations(used),
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
        # KR6: which namesake is which ("Is Focus Plus the same as Focus Legacy?")
        from app.scheme_registry import KNOWLEDGE_DISTINCTIONS
        note = " ".join(KNOWLEDGE_DISTINCTIONS[m] for m in s.split(" / ") if m in KNOWLEDGE_DISTINCTIONS)
        sections.append(f"=== {s} ===\n" + (f"(In short: {note})\n" if note else "") + body)
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
