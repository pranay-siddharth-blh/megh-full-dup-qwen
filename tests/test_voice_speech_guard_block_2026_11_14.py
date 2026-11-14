"""The speech guard BLOCKS an unsourced number (14 Nov 2026, VOICE_BLOCK_UNSOURCED, on by default).

A false alarm now cuts a correct answer, so most of this file is false-positive cases: every real answer in
tests/accuracy/results read back word for word, its figures said the ways a voice says them (lakh, crore, thousand,
rounded), years, ordinals, "top N", dates and counts of the items shown. The rest pins guard_line: the unsourced
sentence is replaced, a run of them by one line, and a reply is never emptied.
"""
import glob
import json
from pathlib import Path

import pytest

from app import text_match
from app.voice import speech_guard as sg
from app.voice import settings as voice_settings

ROOT = Path(__file__).resolve().parents[1]
ANSWER = "54,89,616 person-days were generated in West Garo Hills in FY 2023-24 under the MGNREGA scheme."


def _real_answers() -> list[str]:
    seen: dict[str, None] = {}
    for f in sorted(glob.glob(str(ROOT / "tests" / "accuracy" / "results" / "*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in d.get("results") or []:
            for t in r.get("turns") or []:
                a = (t.get("answer") or "").strip()
                if a:
                    seen.setdefault(a, None)
    return list(seen)


REAL = _real_answers()


def test_there_are_real_answers_to_check():
    assert len(REAL) >= 100


def test_every_real_answer_read_word_for_word_passes_unchanged():
    bad = []
    for a in REAL:
        line, dev = sg.guard_line(a, sg.facts_from(a))
        if dev or line != a:
            bad.append((dev, a[:160]))
    assert not bad, bad[:5]


def _spoken_forms(v: float) -> list[str]:
    """How a voice says a figure: in lakh / crore (one or two decimals), in thousands, rounded, Indian / international
    grouping."""
    out = []
    if v >= 1e7:
        out += [f"{round(v / 1e7, 2)} crore", f"{round(v / 1e7, 1)} crore"]
    if v >= 1e5:
        out += [f"{round(v / 1e5, 2)} lakh", f"{round(v / 1e5, 1)} lakh", f"{v:,.0f}"]
    if 1e4 <= v < 1e6:
        out += [f"{round(v / 1e3)} thousand"]
    if v >= 100 and float(v).is_integer():
        out += [str(int(v))]
    return out


def test_real_figures_said_the_ways_a_voice_says_them_pass():
    bad = []
    n = 0
    for a in REAL:
        facts = sg.facts_from(a)
        for start, end, s in text_match.number_spans(a):
            v = text_match.to_number(s)
            if v is None or v < 100:
                continue
            for form in _spoken_forms(v):
                said = f"That comes to about {form} in all."
                n += 1
                if sg.deviations(said, facts):
                    bad.append((form, s, a[:120]))
    assert n > 200
    assert not bad, bad[:8]


@pytest.mark.parametrize("said", [
    # years and financial years, digits and words
    "In FY 2023-24 and 2024-25 the figure held.",
    "Between twenty twenty-three and twenty twenty-four it rose.",
    "From 2019 to 2024 the trend was steady.",
    # ordinals and ranks
    "West Garo Hills ranks 13th among the blocks.",
    "It was the 21st-ranked block last year.",
    "That is the 2nd highest district.",
    # the size of a ranking
    "Here are the top 15 blocks by person-days.",
    "The bottom five districts are on your screen.",
    "The first 20 villages are listed.",
    "The top twenty-five blocks are shown.",
    # dates
    "As of 31 March 2024, the data is final.",
    "The data was refreshed on November 14.",
    # small counts said in passing
    "Across all 12 districts and 3 schemes.",
    "There are two tables and one chart.",
    # the figure itself, many ways
    "Fifty-four lakh eighty-nine thousand six hundred and sixteen person-days.",
    "About 54.9 lakh person-days.",
    "Roughly 55 lakh person-days.",
    "5,489,616 person-days in FY 2023-24.",
])
def test_not_figures_and_faithful_figures_are_never_blocked(said):
    facts = sg.facts_from(ANSWER)
    assert sg.deviations(said, facts) == [], said
    assert sg.guard_line(said, facts) == (said, [])


def test_a_count_of_the_items_shown_is_allowed():
    listing = "\n".join(f"Block {i}: {1000 + i * 37:,} person-days" for i in range(1, 16))
    facts = sg.facts_from("Person-days by block:\n" + listing)
    assert sg.deviations("These 15 blocks are on your screen.", facts) == []
    semi = "; ".join(f"District {i} {200 + i}" for i in range(1, 15))
    assert sg.deviations("All 14 districts are listed.", sg.facts_from(semi)) == []


def test_a_rank_word_does_not_hide_a_real_figure_after_it():
    facts = sg.facts_from(ANSWER)
    # "top" covers the size of the ranking only, never a figure further on in the sentence
    assert sg.deviations("The top 5 had 77,77,777 person-days.", facts) == ["7777777"]


@pytest.mark.parametrize("said,bad", [
    ("It was 60 lakh person-days.", ["6000000"]),
    ("About 99,99,999 of them, roughly.", ["9999999"]),
    ("There were 12,345 person-days in that district.", ["12345"]),
    ("It was 2 crore 99 lakh in FY 2022-23.", ["29900000"]),
    ("Seventy seven thousand households.", ["77000"]),
])
def test_a_figure_from_memory_is_still_caught(said, bad):
    assert sg.deviations(said, sg.facts_from(ANSWER)) == bad


def test_guard_line_replaces_only_the_unsourced_sentence():
    facts = sg.facts_from(ANSWER)
    said = ANSWER + " Last year it was 77,77,777. That is all I have."
    line, bad = sg.guard_line(said, facts)
    assert bad == ["7777777"]
    assert line == ANSWER + " " + sg.ON_SCREEN_LINE + " That is all I have."
    assert "77,77,777" not in line


def test_a_run_of_unsourced_sentences_becomes_one_line():
    facts = sg.facts_from(ANSWER)
    said = ANSWER + " It was 61 lakh in 2022. It was 62 lakh in 2021. Nothing else."
    line, bad = sg.guard_line(said, facts)
    assert bad == ["6100000", "6200000"]
    assert line.count(sg.ON_SCREEN_LINE) == 1 and line.endswith("Nothing else.")


@pytest.mark.parametrize("said", [
    "There were 12,345 person-days in that district.",
    "It was 60 lakh. It was 61 lakh.",
])
def test_a_reply_is_never_emptied(said):
    line, bad = sg.guard_line(said, sg.facts_from(ANSWER))
    assert bad and line == sg.SAFE_LINE


def test_an_empty_line_stays_empty_and_a_clean_one_is_returned_as_is():
    assert sg.guard_line("", set()) == ("", [])
    assert sg.guard_line("Hello. Ask me anything.", set()) == ("Hello. Ask me anything.", [])


def test_the_safe_lines_hold_no_number():
    for line in (sg.SAFE_LINE, sg.ON_SCREEN_LINE):
        assert sg.spoken_values(line) == []


def test_sentences_never_split_inside_a_number():
    assert sg.sentences("Spent 3,628.67 crore. In 2023-24 it was 37.49 crore.") == [
        "Spent 3,628.67 crore.", "In 2023-24 it was 37.49 crore."]


def test_the_block_setting_is_on_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGH_VOICE_ENV", str(tmp_path / "none.env"))
    monkeypatch.delenv("VOICE_BLOCK_UNSOURCED", raising=False)
    assert voice_settings.load().block_unsourced is True
    for off in ("off", "0", "false", "no", "OFF"):
        monkeypatch.setenv("VOICE_BLOCK_UNSOURCED", off)
        assert voice_settings.load().block_unsourced is False
    monkeypatch.setenv("VOICE_BLOCK_UNSOURCED", "on")
    assert voice_settings.load().block_unsourced is True
