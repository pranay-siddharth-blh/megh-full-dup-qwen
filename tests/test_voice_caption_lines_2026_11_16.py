"""The voice's lines on the page are exactly what it said (2026-11-16, the user's live test on the sovereign engine:
"for 'One moment, sir.' a 'the' is there in front of the 'One'; when the voice says 'Sure' one more word comes").
The engine speaks a holding line and then the answer line, word by word in real time. The relay's word-by-word
captions held the last word of a line ("sir.") until the next line began, and after a barge-in a word held back at the
cut was glued to the next line's first word ("theOne")."""
import asyncio

from app.voice import relay, speech_guard

ANSWER = "West Garo Hills has the most. That is just over 33,000 houses."


def _session():
    s = relay.VoiceSession.__new__(relay.VoiceSession)
    s.turn = relay.VoiceSession._new_turn()
    s.facts = speech_guard.facts_from(ANSWER)
    s.sent = []

    async def send(obj):
        s.sent.append(obj)
    s.send = send
    s.officer = relay.Officer(key="7", username="t", name="T")
    return s


def _say(s, pieces):
    async def go():
        for p in pieces:
            s.turn["said"] += p
            await s._guard_scan(final=False)
    asyncio.run(go())


def _out(s):
    return "".join(e["text"] for e in s.sent if e.get("type") == "out")


def test_a_line_s_last_word_goes_out_with_the_line_not_with_the_next_one():
    s = _session()
    _say(s, ["One", " moment,", " sir."])
    assert _out(s) == "One moment, sir."                  # whole before the answer's first word arrives
    _say(s, [" West", " Garo"])
    assert _out(s) == "One moment, sir. West"
    t = _session()
    _say(t, ["Sure,", " sir."])
    assert _out(t) == "Sure, sir."


def test_a_figure_at_the_end_of_a_line_still_waits_for_the_line_to_end():
    s = _session()
    _say(s, ["That", " is", " just", " over", " 33,000."])
    assert "33,000" not in _out(s)


def test_after_a_barge_in_the_next_line_starts_on_its_own():
    s = _session()
    _say(s, ["West", " Garo", " Hills", " has", " the most. That"])   # "That" is held (no space after it yet)
    # the engine's `interrupted`, as the relay handles it
    s.turn.update(said="", checked=0, part_i=-1, part_txt="")
    _say(s, ["One", " moment,", " sir."])
    out = _out(s)
    assert "ThatOne" not in out and "theOne" not in out
    assert out.endswith("One moment, sir.")


def test_the_relay_resets_the_open_sentence_on_interrupted():
    src = open(relay.__file__, encoding="utf-8").read()
    assert 'self.turn.update(said="", checked=0, part_i=-1, part_txt="")' in src
