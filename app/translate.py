"""
Khasi / Garo questions into English (RAG upgrade Phase 4, 2026-10-15).

The chat's KHA / GAR language buttons send `language` with every question, but
the pipeline — routing, the keyword gates, retrieval, SQL generation — reads
English, and the documents are English. Khasi and Garo are written in the Latin
alphabet, so they cannot be told apart from English by their letters; the
officer's choice of button is the signal. With KHA or GAR selected, the
question is translated by the gateway's response model before anything else runs
(the fast classifier model mistranslated counts, 2026-10-15).

Names are kept as written (districts, blocks, villages, schemes, numbers,
years), because the entity resolver matches them against the registry. A
question already in English comes back unchanged. Any failure returns the
question as it was, so a translation outage never blocks an answer.

The answer itself is still written in English (the UI's Khasi / Garo strings
are English placeholders too — frontend/src/chat/constants.js).
"""
import json
import logging

from app import llm
from app.config import settings

logger = logging.getLogger(__name__)

LANGUAGE_NAMES = {"kha": "Khasi", "gar": "Garo"}

# Common question words, so a count ("katno" = how many) is not read as a
# person's name — the fast model translated "Katno ki job card la pynmih ha Ri
# Bhoi…" (how many job cards were issued in Ri Bhoi…) as "Is the job card for
# Katno's name correct" (2026-10-15). Kept to words that are not in doubt.
_HINTS = {
    "Khasi": ('\nKhasi question words: "katno" = how many / how much, "kumno" = how, "aiu" = what, '
              '"mano" = who, "haei" = where, "lano" = when; "ha" = in, "snem" = year.'),
}

_SCHEMA = {"type": "object", "properties": {"english": {"type": "string"}}, "required": ["english"]}


async def to_english(text: str, language: str | None) -> str:
    """The question in English; unchanged for English, an unknown language or
    any failure."""
    name = LANGUAGE_NAMES.get((language or "").lower())
    if not name or not settings.TRANSLATE_ENABLED or not (text or "").strip():
        return text
    prompt = f"""Translate this message from {name} (a language of Meghalaya, India) into plain English.
It is a question to a government scheme helpdesk (MGNREGA, PMAY-G, Focus Plus, Focus Legacy,
CM Elevate), often asking for a count, an amount or how something works.{_HINTS.get(name, "")}
Keep every name exactly as written — districts, blocks, villages, schemes, people,
numbers and years. If the message is already in English, return it unchanged. Translate only;
do not answer it.

<message>
{text.replace("</message>", "")}
</message>

Reply as JSON: {{"english": "..."}}"""
    try:
        raw = await llm.call_model(
            base_url=settings.RESPONSE_MODEL_BASE_URL, model=settings.RESPONSE_MODEL,
            api_key=settings.RESPONSE_MODEL_API_KEY, prompt=prompt, temperature=0.0,
            max_tokens=300, timeout=settings.TRANSLATE_TIMEOUT_SECONDS, role="translate",
            guided={"guided_json": _SCHEMA} if settings.GUIDED_DECODING_ENABLED else None)
        body = raw or ""
        lo, hi = body.find("{"), body.rfind("}")
        # First '{' through the last '}' (the model may wrap the JSON in prose).
        english = str(json.loads(body[lo:hi + 1] if 0 <= lo < hi else raw).get("english") or "").strip()
    except Exception as e:  # noqa: BLE001 — answer the question as typed
        logger.warning("translate: %s -> English failed (%s); using the question as typed", name, type(e).__name__)
        return text
    if not english or len(english) > 4 * len(text) + 200:
        return text
    return english
