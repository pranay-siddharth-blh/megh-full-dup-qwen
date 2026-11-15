"""Dictation socket /ws/dictate (D-111, 15 Nov 2026), offline: a real uvicorn server on a free port with fake
ears (tests/dictation_fakes.py), the real segmenter, session, cleaner and limits."""
import asyncio
import logging
import os

import pytest

from app import asr_gate, llm
from app.config import settings
from app.dictation import ears, router
from tests import dictation_fakes as F


@pytest.fixture(scope="module")
def url():
    srv, th, u = F.start_server()
    yield u
    srv.should_exit = True
    th.join(5)


@pytest.fixture(autouse=True)
def wiring(monkeypatch):
    monkeypatch.setattr(router, "identify", F.fake_identify)
    ear = {"make": lambda: F.FakeEar()}
    monkeypatch.setattr(ears, "batch_ear", lambda: ear["make"]())
    router._ACTIVE.clear()
    router._HELLOS.clear()
    F.FakeEar.calls.clear()
    yield ear
    router._ACTIVE.clear()
    router._HELLOS.clear()


def run(coro):
    return asyncio.run(coro)


def types(r):
    return [m["type"] for m in r["msgs"]]


QUESTION = [["how", "many", "houses"], ["were", "completed", "in", "reply", "district"], ["during", "2023", "24"]]


# ── handshake ───────────────────────────────────────────────────────────────

def test_hello_then_ready(url):
    r = run(F.dictate(url, None, end="stop"))
    assert r["msgs"][0]["type"] == "ready"
    assert r["msgs"][0]["max_s"] == settings.DICTATE_MAX_SECONDS
    assert r["msgs"][0]["partials"] in ("asr", "off")


def test_bad_token_is_4401(url):
    r = run(F.dictate(url, None, token="nope"))
    assert r["code"] == 4401 and r["msgs"][0] == {"type": "error", "reason": "auth"}


def test_no_hello_is_4400(url):
    r = run(F.dictate(url, None, hello={"type": "nothello"}))
    assert r["code"] == 4400


def test_hello_must_come_within_five_seconds(url, monkeypatch):
    monkeypatch.setattr(router, "HELLO_SECONDS", 0.3)

    async def go():
        import websockets
        async with websockets.connect(url) as ws:
            try:
                async for _ in ws:
                    pass
            except Exception:  # noqa: BLE001
                pass
            return ws.close_code
    assert run(go()) == 4400


def test_hello_rate_limit_is_4429(url, monkeypatch):
    monkeypatch.setattr(settings, "DICTATE_HELLO_PER_MINUTE", 2)
    codes = [run(F.dictate(url, None, end="cancel"))["code"] for _ in range(3)]
    assert codes[:2] == [1000, 1000] and codes[2] == 4429


def test_engine_off_says_off(url, monkeypatch):
    monkeypatch.setattr(settings, "DICTATE_ENGINE", "off")
    r = run(F.dictate(url, None))
    assert r["msgs"][0] == {"type": "error", "reason": "off"}


# ── words ───────────────────────────────────────────────────────────────────

def test_stop_gives_the_cleaned_final_after_ordered_partials(url):
    r = run(F.dictate(url, F.speech(QUESTION)))
    t = types(r)
    assert t[0] == "ready" and "final" in t and t[-1] == "closed"
    final = r["msgs"][t.index("final")]
    assert final["text"] == "How many houses were completed in Ri Bhoi district during 2023-24."
    assert {"heard": "reply", "wrote": "Ri Bhoi", "kind": "place"} in final["corrections"]
    partials = [m for m in r["msgs"] if m["type"] == "partial"]
    assert partials, "live words while speaking"
    seqs = [p["seq"] for p in partials]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert all(t.index("final") > t.index("partial") for _ in [0])
    assert r["msgs"][-1] == {"type": "closed", "reason": "done"}


def test_stable_text_only_grows(url):
    r = run(F.dictate(url, F.speech(QUESTION)))
    stables = [m["stable"] for m in r["msgs"] if m["type"] == "partial" and m["stable"]]
    assert stables
    for a, b in zip(stables, stables[1:]):
        assert len(b.split()) >= len(a.split())


def test_cancel_sends_no_words(url):
    r = run(F.dictate(url, F.speech(QUESTION), end="cancel"))
    assert "final" not in types(r)
    assert r["msgs"][-1] == {"type": "closed", "reason": "cancelled"}


def test_silence_is_no_speech(url):
    import numpy as np
    r = run(F.dictate(url, np.zeros(16000 * 2, dtype="<i2")))
    assert "no_speech" in types(r) and "final" not in types(r)


def test_ears_down_is_an_error_not_a_blank(url, wiring):
    wiring["make"] = lambda: F.FakeEar(fail=True)
    r = run(F.dictate(url, F.speech(QUESTION)))
    assert {"type": "error", "reason": "asr"} in r["msgs"]


def test_oversize_and_odd_frames_are_dropped(url):
    before = router.STATS["frames_dropped"]
    r = run(F.dictate(url, F.speech([["show", "the", "houses"]]), extra_frames=[b"\x00" * 9000, b"\x00" * 3]))
    assert router.STATS["frames_dropped"] - before == 2
    assert r["msgs"][[m["type"] for m in r["msgs"]].index("final")]["text"] == "Show the houses."


# ── limits ──────────────────────────────────────────────────────────────────

def test_max_seconds_finishes_with_the_words(url, monkeypatch):
    monkeypatch.setattr(settings, "DICTATE_MAX_SECONDS", 2)
    long = F.speech([["show", "the", "houses"]] * 4)
    r = run(F.dictate(url, long, end="none"))
    final = next(m for m in r["msgs"] if m["type"] == "final")
    assert final["ended"] == "max length" and final["text"].startswith("Show the houses")
    assert r["msgs"][-1] == {"type": "closed", "reason": "max length"}


def test_idle_page_is_finished(url, monkeypatch):
    monkeypatch.setattr(settings, "DICTATE_IDLE_SECONDS", 1)
    r = run(F.dictate(url, F.speech([["show", "the", "houses"]]), end="none"))
    assert any(m["type"] == "final" for m in r["msgs"])
    assert r["msgs"][-1] == {"type": "closed", "reason": "idle"}


def test_newest_dictation_of_a_user_wins(url):
    async def go():
        first = asyncio.create_task(F.dictate(url, F.speech(QUESTION), realtime=1.0, end="none", wait_close=8))
        await asyncio.sleep(0.8)
        second = await F.dictate(url, F.speech([["show", "the", "houses"]]))
        return await first, second
    first, second = run(go())
    assert {"type": "closed", "reason": "replaced"} in first["msgs"]
    assert "final" not in types(first)
    assert "final" in types(second)


def test_busy_when_the_worker_is_full(url, monkeypatch):
    monkeypatch.setattr(settings, "DICTATE_MAX_SESSIONS", 1)

    async def go():
        a = asyncio.create_task(F.dictate(url, F.speech(QUESTION), token="user-1", realtime=1.0, end="cancel"))
        await asyncio.sleep(0.5)
        b = await F.dictate(url, None, token="user-2")
        await a
        return b
    assert run(go())["msgs"][0] == {"type": "error", "reason": "busy"}


# ── privacy ─────────────────────────────────────────────────────────────────

def test_no_file_is_written_even_with_the_debug_dir_set(url, monkeypatch, tmp_path):
    debug = tmp_path / "asr_debug"
    monkeypatch.setattr(settings, "ASR_DEBUG_DIR", str(debug))
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    run(F.dictate(url, F.speech(QUESTION)))
    assert not debug.exists()
    assert list(work.iterdir()) == []


def test_logs_hold_counts_never_words(url, caplog):
    caplog.set_level(logging.DEBUG)
    r = run(F.dictate(url, F.speech(QUESTION)))
    assert "final" in types(r)
    # the server's records (the test's own websockets client logs the frames it receives; that is the page)
    logged = " ".join(rec.getMessage() for rec in caplog.records
                      if not rec.name.startswith("websockets.client")).lower()
    assert "dictation: final" in logged
    for w in ("houses", "completed", "reply", "ri bhoi", "district"):
        assert w not in logged, w


# ── the speech gate is not the LLM gate ─────────────────────────────────────

def test_dictation_works_while_the_llm_gate_is_saturated(url, monkeypatch):
    held = asyncio.Semaphore(0)          # no LLM slot is free, and none will be
    monkeypatch.setattr(llm, "_gate", held)
    monkeypatch.setattr(settings, "MODEL_QUEUE_TIMEOUT_SECONDS", 1)
    r = run(F.dictate(url, F.speech(QUESTION)))
    assert next(m for m in r["msgs"] if m["type"] == "final")["text"].startswith("How many houses")


def test_transcribe_upload_uses_the_speech_gate_not_the_llm_gate(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "How many beneficiaries?"}

    class Client:
        async def post(self, *a, **k):
            return Resp()
    monkeypatch.setattr(llm, "_client", Client())
    monkeypatch.setattr(llm, "_gate", asyncio.Semaphore(0))
    monkeypatch.setattr(settings, "MODEL_QUEUE_TIMEOUT_SECONDS", 1)
    assert run(llm.call_asr(b"RIFF....", "a.wav")) == "How many beneficiaries?"


def test_speech_gate_sheds_when_full(monkeypatch):
    monkeypatch.setattr(settings, "ASR_MAX_CONCURRENCY", 1)
    asr_gate._gates.clear()

    async def go():
        async with asr_gate.slot("upload", 1):
            with pytest.raises(llm.ModelBusyError):
                async with asr_gate.slot("upload", 0.1):
                    pass
            return asr_gate.in_use("upload")
    assert run(go()) == 1
    asr_gate._gates.clear()


def test_debug_dir_is_never_read_by_the_dictation_code():
    here = os.path.dirname(router.__file__)
    for name in os.listdir(here):
        if name.endswith(".py"):
            src = open(os.path.join(here, name), encoding="utf-8").read()
            assert "ASR_DEBUG_DIR" not in src.replace("ASR_DEBUG_DIR never", "").replace(
                "ASR_DEBUG_DIR does not", ""), name
