"""Captions word by word (2026-11-16, the user's live test on the sovereign engine): the unsourced-number check
released captions a FINISHED sentence at a time, and a real-time engine said one ~15 s sentence, so the transcript and
the picture (lit from the captions) came at its end. Now the open sentence goes out word by word: a figure is held
until its unit has arrived and the prefix passes the same check; the finished sentence is still checked as a whole."""
import asyncio

from app.voice import relay, speech_guard

ANSWER = ("Tikrikilla has the most MGNREGA person-days of employment across all financial years: 46,89,766, well ahead "
          "of Rongram (30,09,245). That is about a quarter (26.7%) of the 1,75,39,710 across all eight blocks.")
SAID = ("Okay, sir, Tikrikilla has the most, about 47 lakh MGNREGA person-days of employment, which is about a quarter "
        "of the total of about 1.8 crore, while Demdema has the fewest, and all 8 blocks are on your screen.")


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


def _feed(s, text, step=6):
    async def go():
        for i in range(0, len(text), step):
            s.turn["said"] += text[i:i + step]
            await s._guard_scan(final=False)
        await s._guard_scan(final=True)
    asyncio.run(go())
    return [e for e in s.sent if e.get("type") == "out"]


def test_words_go_out_while_the_sentence_is_still_being_said():
    s = _session()
    outs = _feed(s, SAID)
    assert len(outs) > 10                                    # word by word, not one caption at the end
    assert "Tikrikilla" in outs[0]["text"] or "Tikrikilla" in "".join(o["text"] for o in outs[:3])
    assert "".join(o["text"] for o in outs).split() == speech_guard.scrub(SAID).split()


def test_a_figure_waits_for_its_unit():
    s = _session()
    outs = []
    async def go():
        for w in SAID.split(" "):
            s.turn["said"] += w + " "
            await s._guard_scan(final=False)
            outs.append("".join(e["text"] for e in s.sent if e.get("type") == "out"))
    asyncio.run(go())
    for shown in outs:                                       # "47" is never shown without "lakh" after it
        assert not shown.rstrip().endswith("47")


def test_an_unsourced_figure_still_cuts_the_sentence_and_is_never_captioned():
    s = _session()
    outs = _feed(s, "Okay, sir, Tikrikilla has the most, 92,13,004 person-days, far ahead of the rest of the state.")
    text = "".join(o["text"] for o in outs)
    assert "92,13,004" not in text
    assert any(e.get("type") == "interrupted" and e.get("guard") == "unsourced" for e in s.sent)


def test_two_sentences_join_with_one_space():
    s = _session()
    outs = _feed(s, "Tikrikilla has the most. That is about 47 lakh person-days. All 8 blocks are on your screen.")
    assert "".join(o["text"] for o in outs) == ("Tikrikilla has the most. That is about 47 lakh person-days. "
                                                "All 8 blocks are on your screen.")
