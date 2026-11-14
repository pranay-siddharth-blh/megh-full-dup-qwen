"""The full-duplex voice relay (app/voice, 2026-11-02), offline.

The relay runs alone (only its router, in a uvicorn thread on a free port), connected to the fake Gemini Live server
(tests/voice/fake_live.py, a subprocess). No database, no gateway, no real model: the login check is faked and the
page's part (answering ask_megh) is played by the test. Covers the contract the chat page relies on and every rule
carried over from Mitra's relay: hello + login, ready, the call handed to the page with the words heard, the answer read
back (the call's own question, the transcript as a fallback), repeats answered once, the silence nudge, a cancelled call, a model answering from memory (a deviation), a
greeting (no call), a refused upstream (fallback + lockout), one session per officer, audio frames forwarded, the voice
switched off, an answer read on request, and the no-regex rule (D-046 / D-047).
"""
import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
import websockets
from fastapi import FastAPI

from app.voice import relay, speech_guard
from app.voice import settings as voice_settings

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "voice" / "fake_live.py"
GOOD = "good-token"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_port(port: int, secs: float = 15) -> None:
    t = time.time()
    while time.time() - t < secs:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"port {port} never opened")


@pytest.fixture(scope="module")
def fakes():
    good, bad = _free_port(), _free_port()
    procs = [subprocess.Popen([sys.executable, str(FAKE), str(good)], cwd=ROOT),
             subprocess.Popen([sys.executable, str(FAKE), str(bad), "--fail"], cwd=ROOT)]
    _wait_port(good)
    _wait_port(bad)
    yield {"good": f"ws://127.0.0.1:{good}", "bad": f"ws://127.0.0.1:{bad}"}
    for p in procs:
        p.kill()


@pytest.fixture(scope="module")
def server():
    app = FastAPI()
    app.include_router(relay.router)
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    _wait_port(port)
    yield f"ws://127.0.0.1:{port}/ws/voice"
    srv.should_exit = True
    th.join(5)


@pytest.fixture(autouse=True)
def _wiring(monkeypatch, fakes):
    async def ident(token):
        return relay.Officer(key="7", username="wgh-officer", name="Test Officer") if token == GOOD else None
    monkeypatch.setattr(relay, "identify", ident)
    state = {"url": fakes["good"], "engine": "gemini"}

    def load():
        return voice_settings.VoiceSettings(api_key="", engine=state["engine"], model="fake", voice="Kore",
                                            live_url=state["url"], idle_seconds=25, max_sessions=40, tool_timeout=20)
    monkeypatch.setattr(voice_settings, "load", load)
    relay._LOCK["until"] = 0.0
    relay._ACTIVE.clear()
    yield state
    relay._LOCK["until"] = 0.0


class Page:
    """The chat page's side of /ws/voice: JSON events and audio frames, answering ask_megh like the page does."""

    def __init__(self, url, token=GOOD):
        self.url, self.token, self.events, self.audio = url, token, [], 0

    async def __aenter__(self):
        self.ws = await websockets.connect(self.url, max_size=None)
        await self.ws.send(json.dumps({"type": "hello", "token": self.token}))
        self.reader = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *a):
        self.reader.cancel()
        try:
            await self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    async def _read(self):
        try:
            async for m in self.ws:
                if isinstance(m, bytes):
                    self.audio += len(m)
                else:
                    self.events.append(json.loads(m))
        except Exception:  # noqa: BLE001
            pass

    async def until(self, pred, secs=15.0):
        t = time.time()
        while time.time() - t < secs:
            for e in self.events:
                if pred(e):
                    return e
            await asyncio.sleep(0.05)
        raise AssertionError(f"no matching event in {secs}s; got {[e.get('type') for e in self.events]}")

    async def send(self, obj):
        await self.ws.send(json.dumps(obj))

    async def answer(self, call, speak, kind="data"):
        await self.send({"type": "tool_result", "id": call["id"],
                         "result": {"speak": speak, "kind": kind, "read_exactly": True}})


def run(coro):
    return asyncio.run(coro)


ANSWER = "54,89,616 person-days were generated in West Garo Hills in FY 2023-24 under the MGNREGA scheme."


def test_login_is_required(server):
    async def go():
        async with Page(server, token="bad") as p:
            e = await p.until(lambda e: e["type"] in ("error", "ready"))
            assert e == {"type": "error", "reason": "auth"}
    run(go())


def test_question_goes_to_the_page_with_the_words_heard_and_the_answer_is_read(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] MGNREGA person-days in West Garo Hills in 2023-24"})
            assert (await p.until(lambda e: e["type"] == "in"))["text"].startswith("MGNREGA person-days")
            call = await p.until(lambda e: e["type"] == "tool_call")
            assert call["heard"] == "MGNREGA person-days in West Garo Hills in 2023-24"
            await p.answer(call, ANSWER)
            done = await p.until(lambda e: e["type"] == "turn_complete")
            assert "54,89,616" in done["said"] and done["called"] == 1 and done["deviations"] == []
            assert p.audio > 0                       # the answer came back as audio frames
    run(go())


def test_the_call_carries_the_whole_question_when_the_transcript_lags(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] !!lag and for Ri Bhoi"})
            call = await p.until(lambda e: e["type"] == "tool_call")
            assert call["question"] == "and for Ri Bhoi" and call["heard"] == "and for"
            await p.answer(call, "Ri Bhoi: 12,04,331 person-days in FY 2023-24.")
            await p.until(lambda e: e["type"] == "turn_complete")
    run(go())


def test_repeated_calls_in_one_turn_reach_the_page_once(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "!!repeat 3 houses sanctioned under PMAY-G"})
            call = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(call, "1,71,107 houses were sanctioned under PMAY-G.")
            done = await p.until(lambda e: e["type"] == "turn_complete")
            assert sum(1 for e in p.events if e["type"] == "tool_call") == 1
            assert done["called"] == 3 and "1,71,107" in done["said"]
    run(go())


def test_a_quiet_model_is_nudged_to_read_the_answer(server):
    async def go():
        before = relay.STATS["nudges"]
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "!!quiet how many job cards in Ri Bhoi"})
            call = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(call, "Ri Bhoi has 41,212 job cards.")
            done = await p.until(lambda e: e["type"] == "turn_complete", secs=12)
            assert "41,212" in done["said"] and relay.STATS["nudges"] == before + 1
    run(go())


def test_a_cancelled_call_stops_the_answer_on_the_page(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "!!cancel total MGNREGA expenditure"})
            call = await p.until(lambda e: e["type"] == "tool_call")
            cancel = await p.until(lambda e: e["type"] == "tool_cancel")
            assert cancel["key"] == call["key"]
            await p.answer(call, "too late")         # a late answer is ignored
            await p.until(lambda e: e["type"] == "turn_complete")
    run(go())


def test_a_number_from_the_models_own_memory_is_a_deviation(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "!!memory person-days in Tura"})
            done = await p.until(lambda e: e["type"] == "turn_complete")
            assert done["called"] == 0 and done["deviations"] == ["12345"]
    run(go())


def test_a_greeting_calls_nothing(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "hello"})
            done = await p.until(lambda e: e["type"] == "turn_complete")
            assert done["called"] == 0 and not any(e["type"] == "tool_call" for e in p.events)
    run(go())


def test_a_refused_upstream_falls_back_and_locks_out(server, _wiring, fakes):
    async def go():
        _wiring["url"] = fakes["bad"]
        async with Page(server) as p:
            e = await p.until(lambda e: e["type"] in ("fallback", "ready"))
            assert e["type"] == "fallback"
        assert relay._LOCK["until"] > time.monotonic()
        _wiring["url"] = fakes["good"]
        async with Page(server) as p:            # locked out: no new attempt for a while
            e = await p.until(lambda e: e["type"] in ("fallback", "ready"))
            assert e["type"] == "fallback"
    run(go())


def test_one_live_session_per_officer(server):
    async def go():
        async with Page(server) as a:
            await a.until(lambda e: e["type"] == "ready")
            async with Page(server) as b:
                await b.until(lambda e: e["type"] == "ready")
                closed = await a.until(lambda e: e["type"] == "closed")
                assert closed["reason"] == "replaced"
                assert len(relay._ACTIVE) == 1
    run(go())


def test_audio_frames_are_forwarded(server):
    async def go():
        before = relay.STATS["audio_in_s"]
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            for _ in range(10):
                await p.ws.send(b"\x00\x00" * 1280)      # 80 ms of silence at 16 kHz
            await asyncio.sleep(0.5)
        assert relay.STATS["audio_in_s"] - before == pytest.approx(0.8, abs=0.01)
    run(go())


def test_voice_switched_off(server, _wiring):
    async def go():
        _wiring["engine"] = "off"
        async with Page(server) as p:
            e = await p.until(lambda e: e["type"] in ("fallback", "ready"))
            assert e == {"type": "fallback", "reason": "voice off"}
        _wiring["engine"] = "gemini"
    run(go())


def test_an_answer_got_another_way_is_read_on_request(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "read", "text": "CM Elevate has 8,921 applications."})
            done = await p.until(lambda e: e["type"] == "turn_complete")
            assert "8,921" in done["said"] and done["deviations"] == []
    run(go())


@pytest.mark.parametrize("said,answer,bad", [
    ("Fifty-four lakh eighty-nine thousand six hundred and sixteen person-days.", ANSWER, []),
    ("5,489,616 person-days.", ANSWER, []),
    ("About 54.9 lakh person-days.", ANSWER, []),
    ("Rupees 37.49 crore was spent.", "₹37,49,31,500 (≈ ₹37.49 crore)", []),
    ("It was 60 lakh person-days.", ANSWER, ["6000000"]),
    ("There were 3 districts and 12 blocks.", "", []),
    ("In twenty twenty-three twenty-four.", ANSWER, []),
])
def test_spoken_numbers_against_the_answer(said, answer, bad):
    facts = speech_guard.facts_from(answer)
    assert speech_guard.deviations(said, facts) == bad


def test_engine_names_never_reach_the_screen():
    assert speech_guard.scrub("I am Gemini by Google") == "I am Megh One AI by Megh One AI"


def test_the_voice_package_uses_no_regex():
    for f in (ROOT / "app" / "voice").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert "import re" not in src and "from re " not in src, f.name


def test_a_reworded_call_in_one_turn_is_the_same_question(server):
    """Gemini asking again in other words (one turn, the officer said nothing new) is one question: one call reaches
    the page, one card, one picture (the visualisation popped 3-4 times on the real voice, 2026-11-02)."""
    async def go():
        before = relay.STATS["coalesced"]
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] !!reword 3 houses completed under PMAY-G by district"})
            call = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(call, "1,29,941 houses were completed under PMAY-G.")
            done = await p.until(lambda e: e["type"] == "turn_complete")
            assert sum(1 for e in p.events if e["type"] == "tool_call") == 1
            assert done["called"] == 3 and "1,29,941" in done["said"]
        assert relay.STATS["coalesced"] - before == 2
    run(go())


def test_the_model_asking_again_after_reading_gets_no_second_answer(server):
    """After the answer was read, the model calling once more on its own (the officer silent) is held: nothing reaches
    the page and nothing is read twice."""
    async def go():
        before = relay.STATS["repeats_held"]
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] !!again Focus Plus beneficiaries in Ri Bhoi"})
            call = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(call, "Ri Bhoi has 9,876 Focus Plus beneficiaries.")
            await p.until(lambda e: e["type"] == "turn_complete")
            await asyncio.sleep(2.5)
            assert sum(1 for e in p.events if e["type"] == "tool_call") == 1
            assert sum(1 for e in p.events if e["type"] == "turn_complete") == 1
        assert relay.STATS["repeats_held"] - before == 1
    run(go())


def test_a_new_question_after_an_answer_is_not_held(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] houses sanctioned under PMAY-G"})
            c1 = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(c1, "1,71,107 houses were sanctioned under PMAY-G.")
            await p.until(lambda e: e["type"] == "turn_complete")
            await p.send({"type": "text", "text": "[voice] and how many were completed"})
            c2 = await p.until(lambda e: e["type"] == "tool_call" and e["id"] != c1["id"])
            assert "completed" in c2["question"]
            await p.answer(c2, "1,29,941 were completed.")
            await p.until(lambda e: e["type"] == "turn_complete" and "1,29,941" in e["said"])
    run(go())


def test_an_answer_read_again_unprompted_never_reaches_the_page(server):
    """After the answer was read, the model saying it again on its own (no new words from the officer) is dropped:
    no second turn, no audio, no caption (found on the real voice 2026-11-03)."""
    async def go():
        before = relay.STATS["unprompted_dropped"]
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] !!echo PMAY-G houses completed in total"})
            call = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(call, "1,29,941 houses were completed under PMAY-G.")
            await p.until(lambda e: e["type"] == "turn_complete")
            n_out = sum(1 for e in p.events if e["type"] == "out")
            await asyncio.sleep(4.0)
            assert sum(1 for e in p.events if e["type"] == "turn_complete") == 1
            assert sum(1 for e in p.events if e["type"] == "out") == n_out
        assert relay.STATS["unprompted_dropped"] > before
    run(go())


def test_after_an_answer_a_new_question_is_heard_and_answered(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] PMAY-G houses completed in total"})
            c1 = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(c1, "1,29,941 houses were completed under PMAY-G.")
            await p.until(lambda e: e["type"] == "turn_complete")
            await p.send({"type": "text", "text": "[voice] and how many were sanctioned"})
            c2 = await p.until(lambda e: e["type"] == "tool_call" and e["id"] != c1["id"])
            await p.answer(c2, "1,71,107 houses were sanctioned under PMAY-G.")
            done = await p.until(lambda e: e["type"] == "turn_complete" and "1,71,107" in e["said"])
            assert done["called"] == 1
            # a read the page asks for after an answer is spoken (the greeting, a typed answer)
            await p.send({"type": "read", "text": "Here is the typed answer: 8,921 applications."})
            await p.until(lambda e: e["type"] == "turn_complete" and "8,921" in e["said"])
    run(go())


def test_the_last_answer_read_again_before_a_new_question_never_reaches_the_page(server):
    """On the real voice (2026-11-03: A5->A6, B5->B6, B16->B17) the officer asked the next question and the model first
    read its previous answer again, then called for the new one, in the same turn. The re-read is not forwarded: one
    call for the new question, and the only spoken turn after it carries the new answer, never the old one."""
    async def go():
        before = relay.STATS["rereads_dropped"]
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] PMAY-G houses completed in total"})
            c1 = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(c1, "1,29,941 houses were completed under PMAY-G.")
            await p.until(lambda e: e["type"] == "turn_complete" and "1,29,941" in e["said"])
            mark = len(p.events)
            await p.send({"type": "text", "text": "[voice] !!reread houses sanctioned under PMAY-G"})
            c2 = await p.until(lambda e: e["type"] == "tool_call" and e["id"] != c1["id"])
            assert "sanctioned" in c2["question"]
            await p.answer(c2, "1,71,107 houses were sanctioned under PMAY-G.")
            await p.until(lambda e: e["type"] == "turn_complete" and "1,71,107" in e["said"])
            await asyncio.sleep(1.0)
            after = p.events[mark:]
            assert sum(1 for e in after if e["type"] == "tool_call") == 1
            said = [e for e in after if e["type"] == "turn_complete" and e["said"]]
            assert len(said) == 1
            assert "1,71,107" in said[0]["said"] and "1,29,941" not in said[0]["said"]
        assert relay.STATS["rereads_dropped"] - before == 1
    run(go())


def test_a_chit_chat_reply_after_an_answer_is_still_forwarded(server):
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] PMAY-G houses completed in total"})
            c1 = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(c1, "1,29,941 houses were completed under PMAY-G.")
            await p.until(lambda e: e["type"] == "turn_complete" and "1,29,941" in e["said"])
            await p.send({"type": "text", "text": "[voice] hello"})
            await p.until(lambda e: e["type"] == "turn_complete" and "Hello" in e["said"])
    run(go())


def test_the_reread_comparison_is_letters_and_digits_only():
    assert relay._letters("1,29,941 Houses were!") == "129941houseswere"


def test_a_repeat_the_officer_asked_for_is_still_forwarded(server):
    """"Repeat that" is a re-read the officer wants: the re-read guard must not drop it."""
    async def go():
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "[voice] PMAY-G houses completed in total"})
            c1 = await p.until(lambda e: e["type"] == "tool_call")
            await p.answer(c1, "1,29,941 houses were completed under PMAY-G.")
            await p.until(lambda e: e["type"] == "turn_complete" and "1,29,941" in e["said"])
            mark = len(p.events)
            await p.send({"type": "text", "text": "[voice] repeat that"})
            await p.until(lambda e: e["type"] == "turn_complete" and "1,29,941" in e["said"] and e["user"])
            assert not any(e["type"] == "tool_call" for e in p.events[mark:])
    run(go())


def test_the_voice_speaks_only_english(server):
    """English only (user, 2026-11-03): speech in another script never reaches the page; the voice then says, in
    English, that it speaks English only. The setup asks Gemini for en-IN and the instruction forbids other languages."""
    async def go():
        before = relay.STATS["non_english_dropped"]
        async with Page(server) as p:
            await p.until(lambda e: e["type"] == "ready")
            await p.send({"type": "text", "text": "!!hindi हिंदी में बताओ"})
            done = await p.until(lambda e: e["type"] == "turn_complete" and "only speak English" in (e.get("said") or ""))
            outs = "".join(e.get("text", "") for e in p.events if e["type"] == "out")
            assert not relay.not_english(outs) and not relay.not_english(done["said"])
        assert relay.STATS["non_english_dropped"] > before
        cfg = relay.setup_msg(type("C", (), {"model": "m", "voice": "v"})(), type("O", (), {"name": ""})())
        assert cfg["setup"]["generationConfig"]["speechConfig"]["languageCode"] == "en-IN"
        assert "ONLY English" in cfg["setup"]["systemInstruction"]["parts"][0]["text"]
    run(go())
