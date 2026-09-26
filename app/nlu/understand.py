"""
app/nlu/understand.py — the Understand node: one guided-JSON model call per
message that reads the message in its conversation (last turns, the
structured ConversationState, and any pending clarification) and returns a
structured QueryFrame — the single object the frame-driven gates will read
(see CLAUDE.md "Project rules — understanding direction").

Every message's frame is built BEFORE the pipeline runs (see
app/nlu/frame_merge.py frame_for_turn) and drives the clarification gates
(app/nlu/clarify_rules.py), routing, follow-up merge, SQL generation and the
"Understood as" line; it is also written to the audit record. The LLM never
fills a missing slot with a guess — the prompt forbids it, and the
deterministic guards below flag (not silently fix) anything the model
returned that the text does not support, so prompt problems are visible in
the audit log. When the model call fails, fallback_frame() stands in: only
what the text states, never a guess.

Grounding comes from what the pipeline already trusts, read at first use
rather than hand-copied so it cannot drift:
  - scheme names + aliases     config/scheme_registry.yaml
  - scheme-only vocabulary     pipeline._{MGNREGA,PMAY,FOCUSPLUS,CMELEVATE}_ONLY_TERMS
                               (the regexes behind _infer_scheme_from_terms)
  - per-scheme rule topics     data/*/*_classification_rules.yaml conditions
  - few-shot examples          data/understand_few_shot.yaml (from tests/eval cases)
pipeline.py is imported lazily inside functions: it imports this module, so a
top-level import would be a cycle.

build_frame() never raises — a failure here must not affect the answer.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from app.clients import llm
from app.core.config import settings

logger = logging.getLogger(__name__)

# The normalised QueryFrame for the message being answered, published by
# pipeline._run_pipeline so the frame-driven gates (app/nlu/clarify_rules.py)
# can read it from _answer_data AND from the LangGraph nodes (a node's task
# inherits the context it was created in). None => the Understand model gave
# no frame this turn (or a LangGraph checkpointer resume re-entered a node):
# the gates then read fallback_frame(question), and SQL generation runs
# without frame hints.
current_frame: "ContextVar[QueryFrame | None]" = ContextVar("current_frame", default=None)
# The one-tap choice the client sent with this message ({"slot", "value"}),
# set by the /api/query router for the duration of the call; None for a typed
# message. Read by frame_merge.frame_for_turn to fill the paused slot
# directly instead of re-understanding the chip's text.
incoming_choice: "ContextVar[dict | None]" = ContextVar("incoming_choice", default=None)

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_FEW_SHOT_FILE = _DATA / "understand_few_shot.yaml"

SCHEMES = ("MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate")
INTENTS = ("DATA", "KNOWLEDGE", "EDGE")
QUERY_TYPES = ("value", "ranking", "trend", "comparison", "list", "distribution")
GEO_LEVELS = ("state", "district", "block", "village", "assembly_constituency", "region")
_RULE_FILES = {
    "MGNREGA": "mgnrega/mgnrega_classification_rules.yaml",
    "PMAY-G": "pmay/pmay_classification_rules.yaml",
    "Focus Plus": "focus_plus/focusplus_classification_rules.yaml",
    "CM Elevate": "cm_elevate/cmelevate_classification_rules.yaml",
}


# ── the frame ──────────────────────────────────────────────────────────────
class GeoMention(BaseModel):
    text: str                                   # exactly as typed
    level: Literal["state", "district", "block", "village",
                   "assembly_constituency", "region"] | None = None  # only if the user said it


class QueryFrame(BaseModel):
    rewritten_question: str = ""
    intent: Literal["DATA", "KNOWLEDGE", "EDGE"] = "DATA"
    is_followup: bool = False
    answers_pending: bool = False
    schemes: list[Literal["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"]] = Field(default_factory=list)
    metric: str | None = None
    geo_mentions: list[GeoMention] = Field(default_factory=list)
    year_text: str | None = None
    tranche: str | None = None
    query_type: Literal["value", "ranking", "trend", "comparison", "list", "distribution"] | None = None
    group_by: str | None = None
    top_n: int | None = None
    unclear: str | None = None
    # ── filled by normalise_frame() (deterministic code), never by the model ──
    resolved_schemes: list[str] = Field(default_factory=list)   # frame ∪ text safety net
    scheme_sources: dict[str, list[str]] = Field(default_factory=dict)  # scheme -> ["frame","named",...]
    year_key: int | None = None                  # FY start year, via pipeline._parse_year_key
    entity_result: dict | None = None            # EXACT resolve_entities() shape: resolved/display/notes
    clarification: dict | None = None            # what the existing resolver would ask (question/options/rule)
    normalise_notes: list[str] = Field(default_factory=list)
    # "model" = the Understand call; "fallback" = fallback_frame() (no model
    # frame this turn) — its entity_result is never pre-resolved.
    source: Literal["model", "fallback"] = "model"


# The fields the MODEL fills — the JSON schema, the few-shot examples and the
# coercion step only ever see these, never the normalise_frame() outputs.
LLM_FIELDS = ("rewritten_question", "intent", "is_followup", "answers_pending", "schemes", "metric",
              "geo_mentions", "year_text", "tranche", "query_type", "group_by", "top_n", "unclear")


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


# Hand-written (flat, no $refs) — what vLLM guided decoding handles reliably.
FRAME_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "rewritten_question": {"type": "string"},
        "intent": {"type": "string", "enum": list(INTENTS)},
        "is_followup": {"type": "boolean"},
        "answers_pending": {"type": "boolean"},
        "schemes": {"type": "array", "items": {"type": "string", "enum": list(SCHEMES)}},
        "metric": _nullable({"type": "string"}),
        "geo_mentions": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "level": _nullable({"type": "string", "enum": list(GEO_LEVELS)})},
            "required": ["text", "level"], "additionalProperties": False}},
        "year_text": _nullable({"type": "string"}),
        "tranche": _nullable({"type": "string"}),
        "query_type": _nullable({"type": "string", "enum": list(QUERY_TYPES)}),
        "group_by": _nullable({"type": "string"}),
        "top_n": _nullable({"type": "integer"}),
        "unclear": _nullable({"type": "string"}),
    },
    "required": ["rewritten_question", "intent", "is_followup", "answers_pending", "schemes",
                 "metric", "geo_mentions", "year_text", "tranche", "query_type", "group_by",
                 "top_n", "unclear"],
    "additionalProperties": False,
}


# ── grounding: vocabulary read from what the pipeline already uses ─────────
def regex_terms(rx: "re.Pattern[str]") -> list[str]:
    """Readable phrases from a vocabulary regex's alternation, e.g.
    r"\\b(person[\\s-]?days?|job cards?)\\b" -> ["person day", "job card"].
    Alternatives that don't reduce to plain words are skipped."""
    src = rx.pattern.strip()
    wrapped = re.fullmatch(r"\\b\((.*)\)\\b", src, re.DOTALL)
    if wrapped:
        src = wrapped.group(1)
    alts, depth, cur, i = [], 0, "", 0
    while i < len(src):
        ch = src[i]
        if ch == "\\" and i + 1 < len(src):
            cur += src[i:i + 2]
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            alts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    alts.append(cur)

    out: list[str] = []
    for a in alts:
        t = a.replace("\\b", "")
        t = re.sub(r"\[\\s-\]\??|\\s[*+?]?", " ", t)
        # innermost groups: optional -> drop, required -> first alternative
        for _ in range(4):
            t = re.sub(r"\((?:\?:)?([^()]*)\)(\?)?",
                       lambda m: "" if m.group(2) else m.group(1).split("|")[0], t)
        t = re.sub(r"\\[wd][*+]", "", t)
        t = re.sub(r"\{\d+,?\d*\}", "", t)
        t = re.sub(r"(\\?.)\?", "", t)          # optional char: "cards?" -> "card"
        t = t.replace("\\+", "+").replace("\\.", ".")
        t = re.sub(r"\s+", " ", t).strip()
        if t and not re.search(r"[\\()\[\]|?*{}^$]", t) and t not in out:
            out.append(t)
    return out


@lru_cache(maxsize=1)
def scheme_grounding() -> str:
    """The SCHEMES block of the prompt: names, aliases, scheme-only vocabulary
    and rule topics — built once from the pipeline's own sources."""
    from app.knowledge import scheme_registry
    from app.orchestration import pipeline

    vocab_rx = {
        "MGNREGA": pipeline._MGNREGA_ONLY_TERMS,
        "PMAY-G": pipeline._PMAY_ONLY_TERMS,
        "Focus Plus": pipeline._FOCUSPLUS_ONLY_TERMS,
        "CM Elevate": pipeline._CMELEVATE_ONLY_TERMS,
    }
    registry = getattr(scheme_registry, "_registry", {}) or {}
    lines = []
    for s in SCHEMES:
        aliases = sorted(set((registry.get(s) or {}).get("aliases") or []) | {s.lower()})
        vocab = regex_terms(vocab_rx[s])
        topics = []
        try:
            rules = yaml.safe_load((_DATA / _RULE_FILES[s]).read_text(encoding="utf-8")) or {}
            topics = [str(r.get("condition", "")).replace("_", " ")
                      for r in rules.get("clarification_rules") or [] if r.get("condition")]
        except Exception:  # noqa: BLE001
            logger.warning("understand: could not read rule topics for %s", s, exc_info=True)
        lines.append(f"- {s}\n    aliases: {', '.join(aliases)}\n"
                     f"    scheme-only words (imply {s} on their own): {', '.join(vocab)}\n"
                     f"    topics its rules cover: {', '.join(topics[:30])}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def few_shot_block() -> str:
    try:
        spec = yaml.safe_load(_FEW_SHOT_FILE.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        logger.warning("understand: few-shot file unreadable", exc_info=True)
        return ""
    parts = []
    for ex in spec.get("examples") or []:
        frame = QueryFrame.model_validate(ex["frame"]).model_dump(include=set(LLM_FIELDS))
        ctx = ex.get("context") or {}
        head = []
        if ctx.get("recent_turns"):
            head.append("Recent turns: " + json.dumps(ctx["recent_turns"], ensure_ascii=False))
        if ctx.get("pending_question"):
            head.append(f"Pending clarification: the bot paused on \"{ctx['pending_question']}\" "
                        f"offering {json.dumps(ctx.get('pending_options') or [], ensure_ascii=False)}")
        parts.append("\n".join(head + [f"Message: {json.dumps(ex['message'], ensure_ascii=False)}",
                                       "JSON: " + json.dumps(frame, ensure_ascii=False)]))
    return "\n\n".join(parts)


# ── conversation context ───────────────────────────────────────────────────
_STATE_KEYS = ("scheme", "district", "block", "village", "year", "metric", "tranche",
               "tranche_all_combined", "comparison_entities", "comparison_kind",
               "last_intent", "last_route", "last_question", "last_standalone_question")


def snapshot_context(session) -> dict:
    """Everything the model sees besides the message, captured synchronously
    — the caller must take this BEFORE the pending pause
    (ConversationState.pending_frame) is consumed."""
    if session is None:
        return {}
    turns = []
    for t in list(getattr(session, "turns", []) or [])[-settings.UNDERSTAND_HISTORY_TURNS:]:
        ent = {k: v for k, v in (t.resolved_entities or {}).items()
               if k in ("district", "block", "village", "year_key", "tranche_label") and v}
        turn = {"user": t.raw_question, "route": t.route, "schemes": list(t.schemes or [])}
        if t.question and t.question != t.raw_question:
            turn["standalone"] = t.question
        if ent:
            turn["entities"] = ent
        turns.append(turn)
    st = getattr(session, "state", None)
    state = {}
    pending = None
    if st is not None:
        d = st.to_dict() if hasattr(st, "to_dict") else {}
        state = {k: d[k] for k in _STATE_KEYS if d.get(k) not in (None, "", [], False, 0)}
        pf = getattr(st, "pending_frame", None)
        if pf and pf.get("kind", "pause") == "pause":
            # The pause: what the user asked AND what the bot asked back.
            pending = {"question": pf.get("base_question") or "", "asked": pf.get("asked") or "",
                       "options": [o.get("label") or o.get("question")
                                   for o in (pf.get("options") or []) if isinstance(o, dict)]}
    return {"recent_turns": turns, "state": state, "pending": pending}


def build_prompt(message: str, ctx: dict) -> str:
    conv = []
    if ctx.get("recent_turns"):
        conv.append("Recent turns (oldest first): " + json.dumps(ctx["recent_turns"], ensure_ascii=False))
    if ctx.get("state"):
        conv.append("Conversation state: " + json.dumps(ctx["state"], ensure_ascii=False))
    if ctx.get("pending"):
        p = ctx["pending"]
        if p.get("asked"):
            conv.append(f"Pending clarification: the user asked \"{p['question']}\" and the bot asked back "
                        f"\"{p['asked']}\" offering {json.dumps(p.get('options') or [], ensure_ascii=False)}"
                        f" — the message may be the answer.")
        else:
            conv.append(f"Pending clarification: the bot paused on \"{p['question']}\" offering "
                        f"{json.dumps(p.get('options') or [], ensure_ascii=False)} — the message may be the answer.")
    conversation = "\n".join(conv) or "(new conversation — no earlier turns)"
    return f"""You are the Understand step of Megh One AI, a data assistant for four Meghalaya government schemes.
Read the user's MESSAGE in its conversation and output ONE JSON object (a QueryFrame).
Users write with typos, Hinglish, fragments and no punctuation: understand the meaning,
but record only what they actually said or what the conversation makes certain.

SCHEMES (output these exact names):
{scheme_grounding()}

FIELDS
rewritten_question: the message as one clear standalone English question (merge a follow-up or a
  pending-clarification answer with the conversation). Keep place names exactly as typed.
intent: DATA (a figure/list/ranking from scheme data — INCLUDING "why" questions about the figures
  or the data itself: "why did employment drop in 2024-25", "why is occupation missing", "are there
  duplicate applications") | KNOWLEDGE (how a scheme works: eligibility, documents, how to apply,
  rules, history, definitions) | EDGE (greeting, thanks, small talk, off-topic, or text with no
  recognisable meaning such as keyboard mash).
is_followup: true only if the message continues the previous turn and cannot stand alone.
answers_pending: true only if a clarification is pending and the message just answers it.
schemes: only schemes named, aliased (misspellings count, e.g. "manrega"), implied by scheme-only
  words above (e.g. applicant/application ALWAYS means CM Elevate; person-days means MGNREGA), or
  certain from the conversation. NEVER guess: generic words (expenditure,
  beneficiaries, disbursement, amount, payment) imply no scheme — leave [].
metric: the quantity asked for, in a few words, or null.
geo_mentions: every named place, text copied EXACTLY as typed (keep typos and abbreviations);
  level only if the user said district/block/village/constituency, "state" for Meghalaya, else null.
  A level word on its own ("top 5 district", "block wise", "by village") names no place:
  it is group_by, not a geo_mention.
year_text: the time period exactly as typed ("2023-24", "last year", "all years"), or null.
tranche: Focus Plus tranche or batch exactly as typed, or null.
query_type: value | ranking | trend | comparison | list | distribution, or null. A question about
  BOTH ends ("best and worst", "highest and lowest", "top and bottom") is comparison, not ranking.
group_by: the breakdown dimension (district, block, village, year, scheme, tranche, status, gender, ...), or null.
top_n: N from "top N" / "N highest"; 1 when the question asks for THE single highest / lowest /
  best / worst ("which district has the most", "the worst block"); null for both ends or no count.
unclear: a short note on what is missing or ambiguous, or null.

RULES
- Fill a field only if the user said it or the conversation makes it certain; otherwise null / [] / false.
- Never fill a missing detail with a default (no assumed year, scheme, area or top-N).
- If the message only answers the pending clarification: set answers_pending=true and fill ONLY the
  slot(s) the answer supplies; rewritten_question is the paused question with that answer merged in.
- A follow-up carries over the previous turn's scheme and metric; new details in the message win.

EXAMPLES
{few_shot_block()}

CONVERSATION
{conversation}

MESSAGE: {json.dumps(message, ensure_ascii=False)}
JSON:"""


# ── parsing + guards ───────────────────────────────────────────────────────
def _extract_json(raw: str) -> "dict | None":
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _coerce(payload: dict, flags: list[str]) -> QueryFrame:
    """Validate field by field so one bad field doesn't lose the frame."""
    clean: dict = {}
    for name in LLM_FIELDS:
        if name not in payload:
            continue
        try:
            QueryFrame.model_validate({name: payload[name]})
            clean[name] = payload[name]
        except Exception:  # noqa: BLE001
            if name == "schemes" and isinstance(payload[name], list):
                ok = [s for s in payload[name] if s in SCHEMES]
                flags.append(f"invalid scheme(s) dropped: {[s for s in payload[name] if s not in SCHEMES]}")
                clean[name] = ok
            elif name == "geo_mentions" and isinstance(payload[name], list):
                good = []
                for g in payload[name]:
                    if isinstance(g, dict) and isinstance(g.get("text"), str):
                        lvl = g.get("level") if g.get("level") in GEO_LEVELS else None
                        good.append({"text": g["text"], "level": lvl})
                clean[name] = good
                flags.append("geo_mentions coerced")
            else:
                flags.append(f"invalid {name} dropped: {str(payload[name])[:60]!r}")
    return QueryFrame.model_validate(clean)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w+]+", " ", (s or "").casefold())).strip()


def guard_flags(frame: QueryFrame, message: str, ctx: dict) -> list[str]:
    """Deterministic checks of the model's output against the text. They FLAG
    — they don't rewrite — so a prompt problem is visible, not papered over."""
    from app.orchestration import pipeline

    flags: list[str] = []
    context_text = json.dumps(ctx, ensure_ascii=False)
    haystack = _norm(message) + " " + _norm(context_text)
    for g in frame.geo_mentions:
        if _norm(g.text) and _norm(g.text) not in haystack:
            flags.append(f"geo not as typed: {g.text!r}")
    if frame.year_text and _norm(frame.year_text) not in haystack:
        flags.append(f"year not as typed: {frame.year_text!r}")
    if frame.schemes:
        corrected = pipeline._correct_scheme_spelling(message)
        evident = set(pipeline._named_schemes(corrected)) | set(pipeline._fuzzy_named_schemes(message))
        evident |= set(pipeline._infer_scheme_from_terms(corrected) or [])
        ctx_schemes = set((ctx.get("state") or {}).get("scheme") and [ctx["state"]["scheme"]] or [])
        for t in ctx.get("recent_turns") or []:
            ctx_schemes |= set(t.get("schemes") or [])
        if ctx.get("pending"):
            ctx_schemes |= set(pipeline._named_schemes(ctx["pending"]["question"]))
        unsupported = [s for s in frame.schemes if s not in evident and s not in ctx_schemes]
        if unsupported:
            flags.append(f"scheme without text/context evidence: {unsupported}")
    if frame.answers_pending and not ctx.get("pending"):
        flags.append("answers_pending but nothing pending")
    if frame.top_n is not None and not (1 <= frame.top_n <= 1000):
        flags.append(f"implausible top_n {frame.top_n}")
    return flags


async def build_frame(message: str, ctx: dict) -> dict:
    """Run the Understand call. Returns {"frame": {...}|None, "meta": {...}}.
    Never raises."""
    started = time.monotonic()
    meta: dict = {"model": settings.UNDERSTAND_MODEL, "flags": []}
    try:
        raw = await llm.call_model(
            base_url=settings.UNDERSTAND_BASE_URL or settings.SQL_VERIFY_BASE_URL,
            model=settings.UNDERSTAND_MODEL,
            api_key=settings.UNDERSTAND_API_KEY or settings.SQL_VERIFY_API_KEY,
            prompt=build_prompt(message, ctx),
            temperature=0.0,
            max_tokens=settings.UNDERSTAND_MAX_TOKENS,
            timeout=settings.UNDERSTAND_TIMEOUT_SECONDS,
            guided={"guided_json": FRAME_JSON_SCHEMA} if settings.GUIDED_DECODING_ENABLED else None,
        )
        payload = _extract_json(raw)
        if payload is None:
            meta["error"] = "no JSON in model output"
            meta["raw"] = (raw or "")[:500]
            return {"frame": None, "meta": meta}
        frame = _coerce(payload, meta["flags"])
        meta["flags"] += guard_flags(frame, message, ctx)
        return {"frame": frame.model_dump(), "meta": meta}
    except Exception as e:  # noqa: BLE001
        logger.warning("understand.build_frame failed (non-fatal, fallback frame): %s", e)
        meta["error"] = f"{type(e).__name__}: {e}"[:300]
        return {"frame": None, "meta": meta}
    finally:
        meta["latency_ms"] = round((time.monotonic() - started) * 1000)


# ── normalise: frame -> the pipeline's own canonical values ────────────────
# The model copies places/years exactly as typed; the deterministic code the
# pipeline already trusts turns them into database values. Nothing here is
# re-implemented: schemes go through the same spelling/naming/vocabulary
# checks the pipeline runs on raw text, geography through the same
# resolve_entities() body (fed the frame's mentions instead of re-extracting
# them with an LLM call), years through _parse_year_key + the data-range check.
_STATEWIDE = {"meghalaya", "all of meghalaya", "whole of meghalaya", "state", "statewide",
              "state-wide", "whole state", "all districts"}
_LEVEL_SLOT = {"district": "district", "block": "block", "village": "village",
               "assembly_constituency": "assembly_constituency"}
# Words that describe a geographic LEVEL or a ranking, never a place. A
# mention made only of these ("districts", "top 5 districts", "District-wise",
# "a district", "village-code") names no place: it is a breakdown (group_by).
_LEVEL_WORDS = {"district", "districts", "block", "blocks", "village", "villages", "gp", "gps",
                "panchayat", "panchayats", "constituency", "constituencies", "wise", "level", "code",
                "lgd", "a", "an", "the", "each", "every", "all", "any", "top", "bottom", "best",
                "worst", "which", "per", "by", "my", "one", "x"}
_LEVEL_OF = {"district": "district", "districts": "district", "block": "block", "blocks": "block",
             "village": "village", "villages": "village", "gp": "village", "gps": "village",
             "panchayat": "village", "panchayats": "village"}


# A year expression naming a PERIOD, not one financial year ("since 2020",
# "2022-23 and 2025-26", "from 2019 to 2021", "2020 onwards"). Pinning its
# first year as a single-FY filter would answer the wrong period; left as
# text for the SQL step instead.
_YEAR_PERIOD = re.compile(r"\b(since|from|after|before|until|till|between|and|to|through|thru|"
                          r"onwards?|upto|up to|over|last \d+|past \d+)\b|[–—]|\s-\s",
                          re.IGNORECASE)


def single_year_text(year_text: "str | None") -> bool:
    """True when year_text names one specific financial year."""
    return bool(year_text) and not _YEAR_PERIOD.search(year_text)


def level_word_only(text: str) -> "str | None":
    """The level a mention like "top 5 districts" describes, if the mention
    is made only of level/ranking words (and numbers) — else None."""
    toks = re.findall(r"[a-z]+", (text or "").casefold())
    if toks and all(t in _LEVEL_WORDS for t in toks):
        return next((_LEVEL_OF[t] for t in toks if t in _LEVEL_OF), "district")
    return None


def _union(*lists) -> list[str]:
    out: list[str] = []
    for lst in lists:
        for x in lst or []:
            if x in SCHEMES and x not in out:
                out.append(x)
    return out


async def frame_mentions(frame: QueryFrame, scheme: str, notes: list[str]) -> dict:
    """QueryFrame.geo_mentions (+ year_text) -> extract_entity_mentions()'s
    dict shape, so resolve_entities() can consume them unchanged.

    Level comes from what the user said; a mention with no stated level is
    tagged district when the district catalogue recognises it (resolved or
    ambiguous), otherwise block — the same convention the LLM extractor uses
    for a bare name, whose block path already falls back to district/village.
    A stated level the database contradicts is overridden: "the village of
    West Garo Hills" is a district, so it is resolved as one, with a note."""
    from app.nlu import entity_resolver
    from app.orchestration import pipeline

    by_slot: dict[str, list[str]] = {}
    for g in frame.geo_mentions:
        text = (g.text or "").strip()
        if not text or g.level in ("state", "region") or text.casefold() in _STATEWIDE:
            continue
        lvl = level_word_only(text)
        if lvl:
            notes.append(f"'{text}' names a level, not a place — treated as a {lvl} breakdown")
            if not frame.group_by:
                frame.group_by = lvl
            continue
        as_district = await entity_resolver.resolve_dimension(text, scheme, "district")
        district_known = as_district.status in ("resolved", "ambiguous")
        if g.level is None:
            slot = "district" if district_known else "block"
        elif g.level in ("village", "block") and as_district.status == "resolved":
            # Trust the database over the level word the user used.
            slot = "district"
            notes.append(f"'{text}' was called a {g.level} but is a district in the data — "
                         f"resolved as the district {as_district.display or as_district.canonical}.")
        else:
            slot = _LEVEL_SLOT.get(g.level, "block")
        by_slot.setdefault(slot, []).append(text)

    mentions: dict[str, object] = {}
    for slot, texts in by_slot.items():
        if slot in ("district", "block") and len(texts) >= 2:
            mentions[slot + "s"] = texts          # the extractor's plural compare form
        else:
            mentions[slot] = texts[0]
            if len(texts) > 1:
                notes.append(f"more than one {slot} named ({', '.join(texts)}); only '{texts[0]}' used")
    if single_year_text(frame.year_text) and pipeline._parse_year_key(frame.year_text) is not None:
        mentions["year"] = frame.year_text
    return mentions


async def normalise_frame(frame: QueryFrame, message: str) -> QueryFrame:
    """Fill resolved_schemes / year_key / entity_result / clarification on the
    frame from the pipeline's own deterministic code. Never raises; a
    ClarificationNeeded the resolver would raise is RECORDED on the frame
    (question, options, rule); resolve_for_answer() raises it when the gates
    get there."""
    from app.orchestration import pipeline

    notes: list[str] = []
    try:
        # Schemes: the frame, unioned with the pipeline's own text safety net.
        # A reply to a pending question ("wgh, 2017") or a follow-up names no
        # scheme itself; the frame's merged rewritten_question does.
        text = f"{message} {frame.rewritten_question}" \
            if (frame.answers_pending or frame.is_followup) else message
        corrected = pipeline._correct_scheme_spelling(text)
        named = pipeline._named_schemes(corrected)
        inferred = pipeline._infer_scheme_from_terms(corrected) or []
        schemes = _union(frame.schemes, named, inferred)
        frame.resolved_schemes = schemes
        frame.scheme_sources = {s: [src for src, lst in (("frame", frame.schemes), ("named", named),
                                                          ("vocabulary", inferred)) if s in lst]
                                for s in schemes}

        # Year: FY start + the data-window check the pipeline applies.
        if frame.year_text:
            frame.year_key = pipeline._parse_year_key(frame.year_text)
            out_of_range = pipeline._out_of_range_year_in(frame.year_text, schemes or None)
            if out_of_range:
                frame.year_key = None
                notes.append(f"year '{out_of_range}' is outside the data range"
                             + (f" for {', '.join(schemes)}" if schemes else ""))
            elif not single_year_text(frame.year_text):
                frame.year_key = None
                notes.append(f"year '{frame.year_text}' is a period, not one financial year — left to the SQL step")
            elif frame.year_key is None:
                notes.append(f"year '{frame.year_text}' is not a specific financial year — left for the rules")

        if frame.intent == "EDGE":
            return frame
        if not schemes:
            notes.append("no scheme — geography not resolved (a scheme picks the catalogue)")
            return frame

        mentions = await frame_mentions(frame, schemes[0], notes)
        question = frame.rewritten_question or message
        try:
            frame.entity_result = await pipeline.resolve_entities(question, schemes, mentions=mentions)
        except pipeline.ClarificationNeeded as e:
            frame.clarification = {"question": e.question, "rule": e.rule,
                                   "options": list(e.options or []),
                                   "resolved_so_far": dict(e.resolved_so_far or {}),
                                   "village_hint": e.village_hint}
        except pipeline.OutOfScope as e:
            frame.clarification = {"question": str(e), "rule": "out-of-scope", "options": []}
    except Exception as e:  # noqa: BLE001 — a normalise failure never fails the turn
        logger.warning("understand.normalise_frame failed (non-fatal): %s", e)
        notes.append(f"normalise error: {type(e).__name__}: {e}"[:200])
    finally:
        frame.normalise_notes = notes
    return frame


def fallback_frame(question: str) -> QueryFrame:
    """The frame the gates read when the Understand model gave none for this
    question — the call failed or timed out, or a LangGraph checkpointer
    resume (pipeline_graph.resume_via_graph / langgraph_followup) re-entered a
    node with its merged question. Holds only what the text states: the
    schemes the pipeline's naming/vocabulary checks pin, a breakdown, a time
    series, an explicit all-years ask. Metric, top-N, places and the year are
    left empty — places and the year are resolved by resolve_entities' own
    extractor (source="fallback"), so nothing is guessed and the gates ask
    or apply a disclosed default exactly as for a model frame."""
    from app.orchestration import pipeline

    text = pipeline._correct_scheme_spelling(question or "")
    schemes = [s for s in (pipeline._shortcut_scheme(text) or []) if s in SCHEMES]
    frame = QueryFrame(rewritten_question=question or "", schemes=schemes, source="fallback",
                       resolved_schemes=list(schemes),
                       scheme_sources={s: ["text"] for s in schemes},
                       normalise_notes=["fallback frame (no Understand frame for this question)"])
    if pipeline._HAS_BREAKDOWN.search(text):
        frame.group_by = "breakdown"
    if pipeline._TIME_SERIES_CUE.search(text):
        frame.query_type = "trend"
    all_years = pipeline._ALL_YEARS_CUE.search(text)
    if all_years:
        frame.year_text = all_years.group(0)
    return frame


# ── frame -> the pipeline's scheme / entity inputs ─────────────────────────
# Called by pipeline._answer_data AND the LangGraph nodes (node_scope_scheme,
# node_entities), so both paths read the frame identically.
async def schemes_for_answer(frame: QueryFrame, question: str) -> tuple:
    """(schemes, ScopeMeta): a model frame's normalised schemes — no second
    classifier call. With a fallback frame (no model frame this turn), or a
    frame that pins none, the pipeline's own scheme classification runs,
    exactly as it did before the frame existed."""
    from app.orchestration import pipeline

    if frame.source == "model" and frame.resolved_schemes:
        return list(frame.resolved_schemes), pipeline.ScopeMeta(
            confidence=1.0, source="frame",
            reason="QueryFrame: " + "; ".join(f"{s} ({'+'.join(src)})"
                                              for s, src in frame.scheme_sources.items()))
    return await pipeline._classify_scheme_detailed(question)


async def resolve_for_answer(frame: QueryFrame, question: str, schemes: list[str],
                             prior_resolved: "dict | None" = None,
                             village_hint: "str | None" = None) -> dict:
    """resolve_entities(), fed the frame's place/year mentions. Reuses the
    frame's own normalise-time resolution when nothing turn-specific (a
    checkpointer resume's prior/village hint) differs from it. A fallback
    frame has no mentions: resolve_entities extracts them itself."""
    from app.core import request_trace
    from app.orchestration import pipeline

    if frame.source == "fallback":
        with request_trace.stage("entities"):
            return await pipeline.resolve_entities(question, schemes, prior_resolved=prior_resolved,
                                                   village_hint=village_hint)
    if prior_resolved is None and village_hint is None and list(frame.resolved_schemes) == list(schemes):
        if frame.clarification:
            c = frame.clarification
            raise pipeline.ClarificationNeeded(c["question"], options=c.get("options"), rule=c.get("rule"),
                                               village_hint=c.get("village_hint"),
                                               resolved_so_far=c.get("resolved_so_far"))
        if frame.entity_result is not None:
            return copy.deepcopy(frame.entity_result)
    mentions = await frame_mentions(frame, schemes[0], [])
    return await pipeline.resolve_entities(question, schemes, prior_resolved=prior_resolved,
                                           village_hint=village_hint, mentions=mentions)


# ── "Understood as" / "Assumed" and the audit copy of the frame ────────────
def frame_for_audit(frame: QueryFrame) -> dict:
    """The normalised frame as the audit record keeps it: model slots plus the
    canonical values normalise produced (resolved entities, not the whole
    entity_result payload)."""
    d = frame.model_dump(include=set(LLM_FIELDS))
    d.update({"resolved_schemes": frame.resolved_schemes, "scheme_sources": frame.scheme_sources,
              "year_key": frame.year_key, "normalise_notes": frame.normalise_notes,
              "resolved": (frame.entity_result or {}).get("resolved"),
              "clarification_rule": (frame.clarification or {}).get("rule"),
              "source": frame.source})
    return d


def meaningfully_different(typed: str, understood: str) -> bool:
    """True when the frame's reading is worth showing: after normalising case
    and punctuation, it is not (nearly) what the user typed."""
    import difflib

    def norm(t: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", (t or "").casefold()))
    a, b = norm(typed), norm(understood)
    if not b or a == b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() < 0.85


def prepend_understanding(result: dict, typed: str, frame: QueryFrame) -> None:
    """Prefix the answer with what the bot understood and assumed, so the user
    can correct it: an "Understood as: ..." line when the frame's standalone
    question differs meaningfully from what was typed, and an "Assumed: ..."
    line carrying every default the gates applied (each default's own
    assumption_text from *_default_rules.yaml). Deterministic text added AFTER
    compose_response — the composer's number-faithfulness check
    (_answer_numbers_faithful) still runs on its own output, untouched."""
    lines = []
    understood = (frame.rewritten_question or "").strip()
    if understood and meaningfully_different(typed, understood):
        lines.append(f"_Understood as: {understood}_")
        result["understood_as"] = understood
    assumed = [a.strip() for a in (result.get("assumptions") or []) if a and a.strip()]
    if assumed:
        lines.append("_Assumed: " + " ".join(assumed) + "_")
    if lines:
        result["answer"] = "\n".join(lines) + "\n\n" + (result.get("answer") or "")


# ── deterministic SQL check against the frame ──────────────────────────────
def sql_frame() -> "QueryFrame | None":
    """The frame SQL generation reads (templates, REQUIRED FILTERS, the frame
    SQL check): this turn's frame when the Understand model produced it. A
    fallback frame states nothing the SQL step can use, so SQL is then
    generated exactly as without a frame."""
    frame = current_frame.get()
    return frame if frame is not None and frame.source == "model" else None


_TABLE_REF = re.compile(r"\b(?:curated|semantic)\.([a-z_][a-z0-9_]*)", re.IGNORECASE)
_GROUP_BY_CLAUSE = re.compile(r"\bgroup\s+by\b(.*?)(?:\border\s+by\b|\blimit\b|\bhaving\b|\)|;|$)",
                              re.IGNORECASE | re.DOTALL)
_LIMIT_N = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)
_GROUP_COLUMNS = {"district": r"lgd_district|district", "block": r"lgd_block|block",
                  "year": r"year_key|financial_year|fy\b|year", "tranche": r"tranche"}


def frame_sql_issue(frame: "QueryFrame | None", schemes: list[str], entity_result: dict,
                    sql: str) -> "str | None":
    """Deterministic check of the SQL against the QueryFrame, run by
    pipeline._verify_sql before the model verifier: the scheme's own tables,
    the requested breakdown in GROUP BY, and LIMIT = top_n. Only what the
    frame states EXPLICITLY is enforced — never a guess — so a correct query
    cannot be bounced into a repair loop over an assumption."""
    from app.sql import prompt_builder

    if frame is None or not sql:
        return None
    s = sql.lower()
    # 1. the question's scheme(s): the SQL must read at least one of their tables.
    owners = {prompt_builder._scheme_of(t) for t in _TABLE_REF.findall(s)}
    owners -= {"shared", "cross"}
    if owners and schemes and not (owners & set(schemes)):
        return (f"the question is about {', '.join(schemes)} but this query only reads "
                f"{', '.join(sorted(owners))} tables — use the {schemes[0]} tables.")
    # 2. the breakdown the question asked for.
    group = (frame.group_by or "").casefold()
    if group in _GROUP_COLUMNS and frame.query_type in ("distribution", "ranking", "trend", None):
        m = _GROUP_BY_CLAUSE.search(s)
        if m is None:
            return (f"the question asks for a {group}-wise breakdown but this query has no GROUP BY — "
                    f"GROUP BY the {group} column and keep every filter.")
        if not re.search(_GROUP_COLUMNS[group], m.group(1)):
            return (f"the question asks for a {group}-wise breakdown but this query groups by "
                    f"something else — GROUP BY the {group} column.")
    # 3. top-N: LIMIT must be exactly N.
    n = prompt_builder.effective_top_n(frame, entity_result)
    if n and frame.query_type == "ranking":
        limits = [int(x) for x in _LIMIT_N.findall(s)]
        if not limits:
            return f"the question asks for the top {n} — ORDER BY the metric DESC and add LIMIT {n}."
        if limits[-1] != n:
            return f"the question asks for the top {n} but this query has LIMIT {limits[-1]} — use LIMIT {n}."
    return None


# ── slot-filling resume ────────────────────────────────────────────────────
# A pause stores the paused QueryFrame + WHICH slot it asked
# (ConversationState.pending_frame). The reply fills that slot on the frame:
# a one-tap option directly (no model call), a typed reply via Understand with
# the pause as context. The standalone question is then rebuilt from the
# frame's slots — never by gluing the reply text onto the paused question.
# Every option carries {slot, value} next to its unchanged "question" text, so
# older clients that only send the text keep working.
SLOT_FOR_RULE = {
    "scheme-not-specified": "scheme",
    "metric-not-specified": "metric",
    "ranking-count-not-specified": "top_n",
    "scope-not-specified": "area",
    "area-level-name": "area",
    "year-not-specified": "year",
    "year-ambiguous": "year",
    "year-out-of-range": "year",
    "tranche-not-specified": "tranche",
    "entity-ambiguous": "entity",
    # node 5.3's clarification engine ("the source can't answer this as asked —
    # which reading?"): its chips pick a reading of the metric. Held as a slot
    # like the others, so a click keeps the frame (ranking / group_by / top_n)
    # instead of re-understanding glued text ("..., Report the overall rate"),
    # which read "which district is worst on completion rate" as "overall rate".
    "column-not-held": "engine_choice",
}
AREA_LEVELS = ("district", "block", "village")
_FY_LABEL = re.compile(r"\bFY\s*(20\d{2})\s*-\s*\d{2}\b", re.IGNORECASE)
_TOP_LABEL = re.compile(r"^\s*top\s+(\d+)\b", re.IGNORECASE)
_VILLAGE_LABEL = re.compile(r"^(?P<village>.+?)\s+[—-]\s+(?P<block>.+?)\s+block,\s+(?P<district>.+)$")


def _option_value(slot: str, opt: dict) -> object:
    label = str(opt.get("label") or "")
    low = label.casefold()
    if slot == "scheme":
        if low.startswith("compare"):
            return "all"
        return next((s for s in SCHEMES if low.startswith(s.casefold())), None)
    if slot == "area":
        if "all of meghalaya" in low:
            return {"area": "statewide", "year": "all" if "all years" in low else None}
        return {"district": label}
    if slot == "year":
        if (opt.get("pins") or {}).get("year_key") is not None:
            return int(opt["pins"]["year_key"])
        m = _FY_LABEL.search(label)
        return int(m.group(1)) if m else ("all" if "all" in low else None)
    if slot == "tranche":
        return "all" if "all tranches" in low else label
    if slot == "top_n":
        m = _TOP_LABEL.match(label)
        return int(m.group(1)) if m else ("all" if "all" in low else None)
    if slot == "entity":
        m = _VILLAGE_LABEL.match(label)
        return {k: v.strip() for k, v in m.groupdict().items()} if m else {"label": label}
    if slot == "metric":
        return label
    if slot == "engine_choice":
        return {"label": label, "question": str(opt.get("question") or "")}
    return None


def annotate_options(rule: "str | None", options: "list[dict] | None") -> list[dict]:
    """Stamp {slot, value} on each option of a pause, next to its unchanged
    "question" text. Options of rules that ask no slot are returned as-is."""
    slot = SLOT_FOR_RULE.get(rule or "")
    out = []
    for o in options or []:
        o = dict(o)
        if slot and "slot" not in o:
            value = _option_value(slot, o)
            if value is not None:
                o["slot"], o["value"] = slot, value
        out.append(o)
    return out


def pending_record(frame: QueryFrame, rule: "str | None", asked: str, options: list[dict],
                   base_question: str, *, level: "str | None" = None, kind: str = "pause") -> dict:
    """What ConversationState.pending_frame holds for one pause (JSON-safe)."""
    slot = "area_level" if kind == "correction" else SLOT_FOR_RULE.get(rule or "")
    return {"frame": frame.model_dump(), "slot": slot, "rule": rule, "asked": asked,
            "options": options, "base_question": base_question, "level": level, "kind": kind}


def _stem(q: str) -> str:
    return (q or "").strip().rstrip(" ?.")


def fill_slot(pending: dict, slot: str, value: object) -> "tuple[QueryFrame, str]":
    """A one-tap choice -> (frame with that slot filled, rebuilt question).
    Deterministic: no model call. The question is built from the frame's
    base question plus the phrase for the filled slot — the same wording the
    option builders use for their own chip questions."""
    from app.orchestration import pipeline

    frame = _resumable(pending)
    stem = _stem(pending.get("base_question") or frame.rewritten_question)
    if slot == "scheme":
        frame.schemes = list(SCHEMES) if value == "all" else [str(value)]
        q = (f"{stem} across MGNREGA, PMAY-G, Focus Plus and CM Elevate" if value == "all"
             else pipeline._scheme_option_question(stem, str(value)))
    elif slot == "area":
        v = value if isinstance(value, dict) else {"district": str(value)}
        if v.get("area") == "statewide":
            frame.geo_mentions = [GeoMention(text="Meghalaya", level="state")]
            q = f"{stem} for all of Meghalaya"
            if v.get("year") == "all":
                frame.year_text, q = "all years", f"{q}, all years"
        else:
            level = next((lv for lv in AREA_LEVELS if v.get(lv)), "district")
            name = str(v.get(level))
            frame.geo_mentions = [GeoMention(text=name, level=level)]
            q = f"{stem} for {name}"
    elif slot == "year":
        if value == "all":
            frame.year_text, q = "all financial years", f"{stem} across all financial years"
        else:
            y = int(value)
            frame.year_text = f"FY {y}-{(y + 1) % 100:02d}"
            q = f"{stem} for {frame.year_text}"
    elif slot == "tranche":
        frame.tranche = "all tranches" if value == "all" else str(value)
        q = f"{stem} across all tranches" if value == "all" else f"{stem} for {value}"
    elif slot == "top_n":
        if value == "all":
            frame.top_n, frame.query_type = None, "list"
            q = f"{stem}, return every row with no limit"
        else:
            frame.top_n = int(value)
            q = pipeline._inject_topn(stem, int(value)).rstrip(" ?")
    elif slot == "entity":
        v = value if isinstance(value, dict) else {}
        if v.get("village"):
            frame.geo_mentions = [GeoMention(text=v["village"], level="village"),
                                  GeoMention(text=v["block"], level="block"),
                                  GeoMention(text=v["district"], level="district")]
            q = f"{stem} for {v['village']}, {v['block']} block, {v['district']}"
        else:
            q = f"{stem} for {v.get('label', '')}".strip()
    elif slot == "metric":
        frame.metric = str(value)
        q = f"{stem}, {value}"
    elif slot == "engine_choice":
        # The reading the user picked joins the metric; every other slot
        # (ranking, group_by, top_n, place, year) stays exactly as understood.
        v = value if isinstance(value, dict) else {"label": str(value)}
        label = str(v.get("label") or "").strip()
        frame.metric = f"{frame.metric} — {label}" if frame.metric and label else (label or frame.metric)
        q = v.get("question") or f"{stem}, {label}"
    else:
        raise ValueError(f"unknown slot {slot!r}")
    frame.answers_pending, frame.is_followup = False, False
    frame.rewritten_question = q.rstrip(" ?") + "?"
    return frame, frame.rewritten_question


def merge_reply(pending: dict, reply: QueryFrame) -> QueryFrame:
    """A typed reply that answers the pause (answers_pending / is_followup):
    the paused frame, with every slot the reply supplied laid over it. The
    reply's own rewritten_question — Understand saw the pause as context and
    merged it — is the standalone question."""
    frame = _resumable(pending)
    if reply.schemes:
        frame.schemes = list(reply.schemes)
    if reply.geo_mentions:
        level = pending.get("level")
        frame.geo_mentions = [GeoMention(text=g.text, level=g.level or level) for g in reply.geo_mentions]
    for f in ("metric", "year_text", "tranche", "top_n", "group_by", "query_type"):
        v = getattr(reply, f)
        if v not in (None, "", []):
            setattr(frame, f, v)
    frame.rewritten_question = _with_level(reply.rewritten_question or frame.rewritten_question,
                                           frame.geo_mentions, pending.get("level"))
    frame.answers_pending, frame.is_followup = False, False
    return frame


def _resumable(pending: dict) -> QueryFrame:
    """The paused frame, ready to take a filled slot. Its SETTLED schemes are
    carried as stated: normalise re-derives schemes from the frame's own
    `schemes` plus the text, and a scheme the pause settled through
    vocabulary or an earlier chip ("houses" -> PMAY-G) must not be lost
    because a bare reply ("ekh") names none."""
    frame = QueryFrame.model_validate(pending["frame"])
    if not frame.schemes and frame.resolved_schemes:
        frame.schemes = list(frame.resolved_schemes)
    frame.entity_result, frame.clarification = None, None
    return frame


def _with_level(question: str, mentions: list, level: "str | None") -> str:
    """Make the standalone question name the level the user chose ("Which
    block?" -> "... in selsella block"): the resolver reads a stated level
    from the question text, and without it a name that is both a block and a
    village gets asked about again."""
    if not level or not mentions or re.search(rf"\b{level}\b", question or "", re.IGNORECASE):
        return question
    name = mentions[0].text
    hit = re.search(re.escape(name), question or "", re.IGNORECASE)
    if hit:
        return question[:hit.end()] + f" {level}" + question[hit.end():]
    return f"{_stem(question)} ({name} {level})?"


def area_level_question(level: str) -> str:
    return {"district": "Which district should the answer cover? Type its name, for example West Garo Hills.",
            "block": "Which block should the answer cover? Type its name, for example Selsella.",
            "village": "Which village should the answer cover? Type its name, and its block if you know it.",
            }[level]


def correction_options(stem: str) -> list[dict]:
    """"Change area" chips under an answer that used the statewide default —
    the user corrects the assumption instead of being asked up front."""
    return [{"label": lv.title(), "question": f"{_stem(stem)} for a specific {lv}",
             "slot": "area_level", "value": lv} for lv in AREA_LEVELS]
