"""
Voice = typed (the independent voice audit of 15-16 Nov 2026; the engine half is in D:\\Full Duplex Architecture,
harness/megh/test_voicefix_2026_11_16.py). The Megh side of the fixes:

A. c19 spoken form says the notes that change what the figures MEAN (a year asked that holds no data and was swapped,
   a CM Elevate count of valid applications only, a scheme of a cross answer with no money / no data), each from the
   answer's own words, number-checked, never cut by the page's 320-character limit; a year swap is said FIRST.
B. app/spelling.py: "East and West Khasi Hills" names BOTH districts (typed and spoken alike; it used to answer West
   Khasi Hills alone without a word), written out and shown in the "Showing results for …" line.
C. app/voice/relay.py: the sovereign engine (VOICE_LIVE_URL) gets the pipeline's own reading of each question
   (asked_as, the answer frame) and whether `speak` is the server's spoken form; typed / chip answers and the chat's
   last answers reach it as CONTEXT_LINE data; the real Gemini Live never receives any of it.

No model, no DB.   python -m pytest tests/test_voice_parity_2026_11_16.py -q
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import entity_resolver as er, pipeline as p, spelling  # noqa: E402
from app.voice import prompt as voice_prompt, relay  # noqa: E402

er.load_all()           # the place catalogue (no DB), as the app loads it at start
spelling.reload()


@pytest.fixture(autouse=True)
def natural_on(monkeypatch):
    monkeypatch.setattr(p.settings, "ANSWER_TEMPLATES_ENABLED", True)
    monkeypatch.setattr(p.settings, "ANSWER_NATURAL_ENABLED", True)


# ── A. caveats in the spoken form ───────────────────────────────────────────
GAP_ANSWER = ("FY 2023-24 holds no data for this scheme, so FY 2022-23 — the nearest financial year that does — is "
              "compared instead. That is a gap in the records, not a zero.\n\n"
              "FY 2025-26 was higher than FY 2022-23 on Focus Plus beneficiaries: 1,05,813 against 93,286, a difference "
              "of 12,527 (13.4% more).")
GAP_ROWS = [{"financial_year": "2022-23", "beneficiaries": 93286}, {"financial_year": "2025-26", "beneficiaries": 105813}]


def test_a_swapped_year_is_said_first():
    spoken = "2025-26 was higher, with about 1.06 lakh Focus Plus beneficiaries against about 93,300 in 2022-23."
    out = p._c19_with_caveats(spoken, GAP_ANSWER, GAP_ROWS, {"schemes": ["Focus Plus"]})
    assert out.startswith("FY 2023-24 holds no data for this scheme, so FY 2022-23 is compared instead.")
    assert out.endswith(spoken)
    assert " — " not in out and "gap in the records" not in out


def test_the_spoken_form_of_a_year_swap_names_the_swap_end_to_end():
    res = {"route": "data", "answer": GAP_ANSWER, "data": GAP_ROWS, "rows": GAP_ROWS, "schemes": ["Focus Plus"],
           "sql": "SELECT financial_year, COUNT(DISTINCT beneficiary_key) AS beneficiaries FROM curated.v_focus_plus "
                  "WHERE financial_year IN ('2022-23','2025-26') GROUP BY financial_year",
           "rewritten_question": "Compare Focus Plus beneficiaries in FY 2023-24 and FY 2025-26", "resolved_entities": {}}
    spoken = p._c19_spoken_for_result(res)
    assert spoken and "holds no data" in spoken and spoken.lower().index("holds no data") < 40, spoken
    assert len(spoken) <= 320


def test_valid_only_and_no_money_are_said():
    ans = ("**All of Meghalaya, all financial years**\n- **MGNREGA:** ₹3,628.67 crore spent\n"
           "- **Homestay**: no money recorded\n- **CM Elevate**: no money recorded\n**Combined: ₹3,628.67 crore**.")
    out = p._c19_with_caveats("Combined: just over ₹3,600 crore. The full list is on your screen.", ans,
                              [{"x": 1}], {"schemes": ["MGNREGA", "Homestay", "CM Elevate"]})
    assert out == ("Combined: just over ₹3,600 crore. Homestay and CM Elevate record no money. "
                   "The full list is on your screen."), out
    cme = ("West Garo Hills has the most CM Elevate valid applications: 1,625.\n\n"
           "- **West Garo Hills** — 1,625\n- **East Khasi Hills** — 998")
    out = p._c19_with_caveats("West Garo Hills has the most. All 12 districts are on your screen.", cme,
                              [{"district": "WEST GARO HILLS", "applications": 1625}], {"schemes": ["CM Elevate"]})
    assert "These count valid applications only." in out and out.endswith("on your screen."), out


def test_a_caveat_already_said_or_unchecked_is_not_added():
    out = p._c19_with_caveats("FY 2023-24 holds no data for this scheme. FY 2025-26 had about 1.06 lakh.", GAP_ANSWER,
                              GAP_ROWS, {"schemes": ["Focus Plus"]})
    assert out.count("holds no data") == 1
    assert p._c19_with_caveats("The answer is 12.", "The answer is 12.", [{"v": 12}], {"schemes": []}) \
        == "The answer is 12."                                          # no note: nothing added


def test_the_caveat_never_pushes_the_answer_past_the_page_limit():
    long_spoken = ("West Garo Hills has the most. That is about 35,000 Focus Plus beneficiaries, about a third of the "
                   "state's total of about 1.06 lakh. West Jaintia Hills has the fewest, 283, so West Garo Hills has "
                   "more than ten times as many. East Khasi Hills is third. All 12 districts are on your screen.")
    out = p._c19_with_caveats(long_spoken, GAP_ANSWER, GAP_ROWS + [{"x": 35039}], {"schemes": ["Focus Plus"]})
    assert len(out) <= 318 and out.startswith("FY 2023-24 holds no data") and "West Garo Hills has the most." in out
    assert out.endswith("on your screen.")


# ── B. "East and West Khasi Hills" ──────────────────────────────────────────
@pytest.mark.parametrize("typed,written", [
    ("MGNREGA person-days in East and West Khasi Hills", "East Khasi Hills and West Khasi Hills"),
    ("PMAY-G houses in East, West and South West Garo Hills", "East Garo Hills, West Garo Hills and South West Garo Hills"),
    ("Focus Plus in West and East Jaintia Hills", "West Jaintia Hills and East Jaintia Hills"),
    ("MGNREGA person-days in East and West Khasi", "East Khasi Hills and West Khasi Hills"),
])
def test_two_directions_of_one_district_name_name_both(typed, written):
    n = spelling.normalise(typed)
    assert written in n.text, n.text
    assert any(c.kind == "district" and c.how == "elided" for c in n.corrections)
    assert "Showing results for" in (n.note() or "")


@pytest.mark.parametrize("typed", ["MGNREGA person-days in East Khasi Hills and West Khasi Hills",
                                   "MGNREGA person-days in West Khasi Hills", "east and west districts of the state",
                                   "North and South Khasi Hills"])
def test_names_already_whole_or_not_districts_are_left_alone(typed):
    n = spelling.normalise(typed)
    assert not any(c.how == "elided" for c in n.corrections), n.corrections


# ── C. the relay: the pipeline's reading reaches the sovereign engine only ───
class _Up:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


class _Ws:
    async def send_json(self, msg):
        pass


def _session(live_url):
    cfg = SimpleNamespace(live_url=live_url, tool_timeout=20, idle_seconds=25, max_session_minutes=0,
                          block_unsourced=True)
    up = _Up()
    up.megh_context = bool(live_url)              # the sovereign engine announced CONTEXT_LINE at setup
    s = relay.VoiceSession(_Ws(), up, cfg, relay.Officer(key="1", username="u", name="n"))
    return s


def _answer(s, result):
    s.waiting["k"] = ["c1"]
    s.batch = {"need": {"c1"}, "resps": {}}
    asyncio.run(s._answer("k", result))
    return s.up.sent[-1]["toolResponse"]["functionResponses"][0]["response"]


RESULT = {"speak": "West Garo Hills has the most. All 12 districts are on your screen.", "kind": "data",
          "read_exactly": True, "on_screen": True, "spoken_form": True,
          "asked_as": "How many CM Elevate applications are there by district?",
          "frame": {"schemes": ["CM Elevate"], "qtype": "breakdown", "group": "district"}}


def test_the_sovereign_engine_gets_the_pipelines_reading_and_the_spoken_form_flag():
    r = _answer(_session("ws://127.0.0.1:8171"), dict(RESULT))
    assert r["asked_as"] == RESULT["asked_as"] and r["frame"]["group"] == "district" and r["spoken_form"] is True
    assert r["speak"] == RESULT["speak"] and r["kind"] == "data"


def test_gemini_live_never_gets_them():
    r = _answer(_session(""), dict(RESULT))
    assert set(r) == {"speak", "kind", "read_exactly", "on_screen"}


def test_context_fields_are_bounded_plain_data():
    big = {"asked_as": "x" * 900, "frame": {"items": ["A" * 50] * 100}, "kind": "data", "speak": "s"}
    out = relay._context_fields(big)
    assert len(out["asked_as"]) == 400 and "frame" not in out          # an oversized frame is dropped
    assert relay._context_fields({"speak": "only words"}) == {}


def test_a_typed_answer_read_aloud_reaches_the_engine_as_context(monkeypatch):
    s = _session("ws://127.0.0.1:8171")
    sent = []

    async def up_text(text):
        sent.append(text)
    monkeypatch.setattr(s, "up_text", up_text)
    msgs = [{"type": "read", "text": "West Garo Hills leads.", "kind": "data",
             "asked_as": "Which are the top 5 districts by Focus Plus beneficiaries?", "frame": {"group": "district"}},
            {"type": "context", "items": [{"asked_as": "PMAY-G houses by district", "kind": "data", "speak": "s"}]}]

    class _Page:
        def __init__(self):
            self.q = [{"type": "websocket.receive", "text": json.dumps(m)} for m in msgs]

        async def receive(self):
            if self.q:
                return self.q.pop(0)
            return {"type": "websocket.disconnect"}
    s.ws = _Page()
    s.ws.send_json = _Ws().send_json
    try:
        asyncio.run(s.from_page())
    except Exception:  # noqa: BLE001 — the fake page ends with a disconnect
        pass
    ctx = [t for t in sent if t.startswith(voice_prompt.CONTEXT_LINE)]
    assert len(ctx) == 2, sent
    first = json.loads(ctx[0][len(voice_prompt.CONTEXT_LINE):])["items"][0]
    assert first["asked_as"].startswith("Which are the top 5") and first["speak"] == "West Garo Hills leads."
    assert any(t.startswith(voice_prompt.READ_LINE) for t in sent)        # and it is still read aloud
    # Gemini: the read only
    s2 = _session("")
    sent.clear()
    monkeypatch.setattr(s2, "up_text", up_text)
    s2.ws = _Page()
    s2.ws.send_json = _Ws().send_json
    try:
        asyncio.run(s2.from_page())
    except Exception:  # noqa: BLE001
        pass
    assert not [t for t in sent if t.startswith(voice_prompt.CONTEXT_LINE)] and sent, sent
    # an engine that did not announce it (an older sovereign engine) gets no context line either
    s3 = _session("ws://127.0.0.1:8171")
    s3.engine_context = False
    sent.clear()
    monkeypatch.setattr(s3, "up_text", up_text)
    s3.ws = _Page()
    s3.ws.send_json = _Ws().send_json
    try:
        asyncio.run(s3.from_page())
    except Exception:  # noqa: BLE001
        pass
    assert not [t for t in sent if t.startswith(voice_prompt.CONTEXT_LINE)] and sent, sent
