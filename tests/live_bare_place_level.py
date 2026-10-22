"""Live: a place's LEVEL is decided by the database, not by the word "village"
(user report 2026-10-21, "How many job cards in Mawphlang?").

Each case runs one chat (one or more turns) through the graph, as the router does
and prints what the entities node produced (entity_result) and the outcome
(answer or pause). Needs the office VPN (megh_db + gateway).

    .venv/Scripts/python.exe tests/live_bare_place_level.py

Facts from curated.dim_geography (2026-10-21): MAWPHLANG is a C&RD block and
assembly constituency 24, and NO village is named exactly "Mawphlang" (only
look-alikes: Mission Mawphlang, Dom Mawphlang, Ladmawphlang, ...).
LADMAWPHLANG (278534, Khatarshnong Laitkroh block) has MGNREGA, PMAY-G and
NRLM rows and no CM Elevate rows. AMBARE ADING (274865, East Garo Hills) has
MGNREGA and PMAY-G rows. MAWLAI is a block, a constituency and a village.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))

from app import pipeline as p  # noqa: E402
from app.session_store import SessionStore  # noqa: E402
from conversation_harness.drivers import _InProcessConversation  # noqa: E402

_CAPTURED: dict = {}
_entity_stage = p._data_entity_stage


async def _spy_entity_stage(d, scope=None):
    r = await _entity_stage(d, scope)
    _CAPTURED["entity_result"] = d.get("entity_result")
    return r

p._data_entity_stage = _spy_entity_stage


def _answer(code):
    return lambda o: (o.get("resolved") or {}).get("village_code") == code and "answer" in o


def _pause_with(*needles):
    def check(o):
        text = " ".join([o.get("pause", "")] + o.get("chips", [])).upper()
        return "pause" in o and all(n.upper() in text for n in needles)
    return check


def _not_offering(*needles):
    def check(o):
        text = " ".join([o.get("pause", "")] + o.get("chips", []) + [o.get("answer", "")]).upper()
        return not any(n.upper() in text for n in needles)
    return check


def _no_village(o):
    text = " ".join([o.get("pause", "")] + o.get("chips", [])).upper()
    return not (o.get("resolved") or {}).get("village_code") and "CENTRE VILLAGE" not in text


def _with_year(code, year):
    return lambda o: _answer(code)(o) and (o.get("resolved") or {}).get("year_key") == year


# (turns, expectation, why) — a str is one fresh-chat turn; a list is one chat,
# checked on its last turn.
CASES = [
    ("How many job cards in Ambare Ading in FY 2023-24?", _answer(274865),
     "bare village -> the village"),
    ("How many job cards in Ambare Ading village in FY 2023-24?", _answer(274865),
     "same with 'village' -> same result"),
    ("How many job cards in Ladmawphlang in FY 2023-24?", _answer(278534),
     "bare village containing a block name -> the village"),
    ("How many job cards in Mawphlang in FY 2023-24?", _pause_with("block", "constituency"),
     "Mawphlang is a block AND a constituency, no village of that name -> ask those two"),
    ("total expenditure in Mawlai during 2023-24", _pause_with("block", "village", "Shallang"),
     "Mawlai is block + village, no context -> chips saying where each lies"),
    (["How many households were employed under MGNREGA in West Khasi Hills in FY 2023-24?",
      "what about Mawlai?"], _answer(276564),
     "remembered district West Khasi Hills holds the Mawlai village, not the block -> village, silently"),
    (["How many households were employed under MGNREGA in Shallang block in FY 2023-24?",
      "what about Mawlai?"], _answer(276564),
     "remembered block Shallang holds the Mawlai village -> village, silently"),
    ("How many job cards in Ladmawplang in FY 2023-24?", _answer(278534),
     "typo of the village Ladmawphlang -> the village (not the Mawphlang block)"),
    ("How many job cards in Ambare Adinng in FY 2023-24?", _answer(274865),
     "typo in a two-word village -> the village"),
    ("How many CM Elevate applications from Ladmawphlang?", _not_offering("Mawphlang C&RD block", "MAWPHLANG assembly"),
     "exact village with no CM Elevate rows -> explain, never offer the Mawphlang block"),
    ("How many PMAY-G houses were completed near the centre in FY 2023-24?", _no_village,
     "'centre' is a village name but an ordinary word -> not a place"),
    (["How many PMAY-G houses were completed by district for FY 2019-20", "give me for dalu"],
     lambda o: (o.get("resolved") or {}).get("block") == "DALU" and "268" in o.get("answer", ""),
     "user chat 18:18: Dalu is a block (no village of that name) -> 268 completed houses, no village chips"),
    (["Total PMAY-G amount released for FY 2023-24 for North Garo Hills", "in dalu", "in DADENGGIRI",
      "in Pakregre"],
     lambda o: (o.get("resolved") or {}).get("village_code") == 274885
     and (o.get("resolved") or {}).get("district") == "EAST GARO HILLS" and "9,10,000" in o.get("answer", ""),
     "user chat 18:33 (KI-347): the measure survives every place swap; Pakregre is East Garo Hills (DB 9,10,000)"),
    (["Total PMAY-G amount released for FY 2023-24 for North Garo Hills", "in dalu", "in DADENGGIRI",
      "in Pakregre", "in dalu", "in dalu block"],
     lambda o: (o.get("resolved") or {}).get("block") == "DALU" and "28,28,52,000" in o.get("answer", ""),
     "user chat 18:33-18:37 (KI-347): Dalu after a village is the block, amount released (DB 28,28,52,000)"),
    (["Total PMAY-G amount released for FY 2023-24 in Mawphlang village", "its block"],
     lambda o: (o.get("resolved") or {}).get("block") == "MAWPHLANG" and "34,43,50,000" in o.get("answer", ""),
     "'its block' answers a village pause with the block (DB 34,43,50,000)"),
    (["How many job cards in Ambare Ading in FY 2023-24?", "what about Ladmawphlang?"],
     _with_year(278534, 2023),
     "follow-up 'what about <village>' -> keeps scheme and year, replaces the place"),
]


async def _run_one(conv, question):
    """One turn as the router runs it (conversation layer, the graph, the turn
    recorded on the session), so a follow-up sees the chat's state."""
    _CAPTURED.clear()
    rec = await conv.ask(question)
    out: dict = {}
    if rec.route == "pause":
        out["pause"] = str(rec.answer)
        out["chips"] = [str(c) for c in rec.chips or []]
    else:
        out["answer"] = str(rec.answer)
    er_ = _CAPTURED.get("entity_result") or {}
    out["resolved"] = er_.get("resolved")
    out["display"] = er_.get("display")
    return out


def _latency_p95() -> float:
    from app import entity_resolver as er
    qs = [q for turns, _ok, _why in CASES for q in ([turns] if isinstance(turns, str) else turns)]
    t = []
    for _ in range(20):
        for q in qs:
            t0 = time.perf_counter()
            er.match_places(q, is_ordinary=p._is_known_word)
            t.append((time.perf_counter() - t0) * 1000)
    t.sort()
    return t[int(len(t) * 0.95)]


async def main():
    from app import main as app_main
    failed = 0
    store = SessionStore(ttl=3600, max_sessions=500, max_turns=50)
    async with app_main.lifespan(app_main.app):
        for turns, ok, why in CASES:
            turns = [turns] if isinstance(turns, str) else turns
            conv = _InProcessConversation(store)
            for q in turns:
                o = await _run_one(conv, q)
            passed = ok(o)
            failed += not passed
            print(f"{'PASS' if passed else 'FAIL'}  {' -> '.join(turns)}")
            print(f"      want: {why}")
            print(f"      entity_result.resolved={json.dumps(o['resolved'])} display={json.dumps(o['display'])}")
            print(f"      {'answer: ' + o['answer'][:160] if 'answer' in o else 'PAUSE: ' + o['pause'][:160]}")
            if o.get("chips"):
                print(f"      chips: {o['chips']}")
        p95 = _latency_p95()
        lat_ok = p95 < 10.0
        failed += not lat_ok
        print(f"{'PASS' if lat_ok else 'FAIL'}  match_places p95 {p95:.2f} ms (< 10 ms)")
    print()
    print(f"{len(CASES) + 1 - failed}/{len(CASES) + 1} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
