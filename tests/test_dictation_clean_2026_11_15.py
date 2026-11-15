"""Dictation cleaning (D-111, 15 Nov 2026): the guards, fillers, the mishearing table
(data/dictation_hearing.yaml), spoken numbers, scheme / district / block spelling, joining segments, the
whole-recording merge rule and the segmenter. Offline; no model."""
import numpy as np
import pytest

from app import spelling
from app.config import settings
from app.dictation import clean as C
from app.dictation import numbers as N
from app.dictation.segmenter import Segmenter
from app.dictation.session import facts, join_parts, merge
from tests.accuracy.dictation_bank import QUESTIONS


@pytest.fixture(scope="module", autouse=True)
def _catalogue():
    C.ensure_catalogue()


def text(x):
    return C.clean(x).text


# ── every known miss ────────────────────────────────────────────────────────

KNOWN = [
    # the spoken bank (Full Duplex, 11-12 Nov)
    ("Pep M A Y G houses completed in East Garo Hills in 2021-22.", "PMAY-G houses completed in East Garo Hills in 2021-22."),
    ("Pep, M A Y G houses completed in East Garo Hills in 2021-22.", "PMAY-G houses completed in East Garo Hills in 2021-22."),
    ("Peep E M A Y G release in Eastern West Khasi Hills.", "PMAY-G release in Eastern West Khasi Hills."),
    ("In reply, give me each scheme's figures.", "In Ri Bhoi, give me each scheme's figures."),
    # the dictation bank on the real qwen3-asr (15 Nov, tests/accuracy/results/dictation_bank_qwen3-run1.json)
    ("Peep EMAYG houses completed in East Garo Hills in 2021-22.", "PMAY-G houses completed in East Garo Hills in 2021-22."),
    ("In Repui, give me each scheme's figures.", "In Ri Bhoi, give me each scheme's figures."),
    ("How many PMAY beneficiaries are there in Amleerin block?", "How many PMAY beneficiaries are there in Amlarem block?"),
    ("How many PMAY beneficiaries are there in Am Laren block?", "How many PMAY beneficiaries are there in Amlarem block?"),
    ("How many PMAY beneficiaries are there in Om Larem block?", "How many PMAY beneficiaries are there in Amlarem block?"),
    ("Give me the house status breakdown for Amlelim block.", "Give me the house status breakdown for Amlarem block."),
    ("How many persons received employment in Amrilarim constituency during 2022-23?",
     "How many persons received employment in Amlarem constituency during 2022-23?"),
    ("How many households received employment in non-stone block during 2025-26?",
     "How many households received employment in Nongstoin block during 2025-26?"),
    # voice_overlay.yaml asr_fixes / term_fixes
    ("How many CML8 applications are there?", "How many CM Elevate applications are there?"),
    ("How many c m l 8 applications are there?", "How many CM Elevate applications are there?"),
    ("see em elevate applications by status", "CM Elevate applications by status"),
    ("Mandreka person-days by district", "MGNREGA person-days by district"),
    ("m g n r e g a expenditure", "MGNREGA expenditure"),
    ("narega households employed", "MGNREGA households employed"),
    ("MGNREGA person dies in West Garo Hills", "MGNREGA person-days in West Garo Hills"),
    ("How many job cods are there in South Garo Hills?", "How many job cards are there in South Garo Hills?"),
    ("pep m a y g houses sanctioned", "PMAY-G houses sanctioned"),
    ("p m a y g houses sanctioned", "PMAY-G houses sanctioned"),
    # megh/adapter.py _DISTRICT_FIX
    ("PMAY-G houses in reply in 2022-23", "PMAY-G houses in Ri Bhoi in 2022-23"),
    ("houses in reply district", "houses in Ri Bhoi district"),
    ("houses for reply block wise", "houses for Ri Bhoi block wise"),
    ("MGNREGA wages in ree buy", "MGNREGA wages in Ri Bhoi"),
    ("MGNREGA wages in rivoi", "MGNREGA wages in Ri Bhoi"),
    ("expenditure in east cassie hills", "expenditure in East Khasi Hills"),
    ("expenditure in West Kasi", "expenditure in West Khasi"),
    ("houses in north garrow hills", "houses in North Garo Hills"),
    ("houses in west jayantia hills", "houses in West Jaintia Hills"),
    # fillers
    ("Um, how many houses?", "How many houses?"),
    ("How many, uh, houses in Ri Bhoi?", "How many, houses in Ri Bhoi?"),
    ("how many houses er in Ri Bhoi", "how many houses in Ri Bhoi"),
    # numbers
    ("MGNREGA person-days in two thousand twenty-three twenty-four", "MGNREGA person-days in 2023-24"),
    ("MGNREGA person-days in twenty twenty three to twenty twenty four", "MGNREGA person-days in 2023-24"),
    ("MGNREGA person-days in twenty three twenty four", "MGNREGA person-days in 2023-24"),
    ("MGNREGA person-days in 2023 24", "MGNREGA person-days in 2023-24"),
    ("MGNREGA person-days in 2023 to 2024", "MGNREGA person-days in 2023-24"),
    ("MGNREGA person-days in 2023 twenty four", "MGNREGA person-days in 2023-24"),
    ("MGNREGA person-days in 2023-2024", "MGNREGA person-days in 2023-24"),
    ("houses sanctioned in two thousand twenty three", "houses sanctioned in 2023"),
    ("blocks that spent over five lakh", "blocks that spent over 5 lakh"),
    ("districts above two point five crore", "districts above 2.5 crore"),
    ("schemes that paid rupees five lakh", "schemes that paid ₹5 lakh"),
    ("schemes that paid five lakh rupees", "schemes that paid ₹5 lakh"),
    ("households paid ten thousand rupees", "households paid ₹10,000"),
    ("top five districts by expenditure", "top 5 districts by expenditure"),
    ("households that completed one hundred days", "households that completed 100 days"),
    ("districts with twelve percent growth", "districts with 12% growth"),
]


@pytest.mark.parametrize("heard,want", KNOWN)
def test_known_misses(heard, want):
    assert text(heard) == want


LEFT_ALONE = [
    "in reply to my question",
    "In reply to your answer, show the houses",
    "Which one is higher?",
    "Over the last three years in West Garo Hills",
    "Show the reply",
    "East and West Khasi Hills",                       # ambiguous: two districts, or Eastern West Khasi Hills?
    "the first two schemes",
    "Which block has the highest person-days?",          # a block word with no name before it
    "Show the lowest block in each district",
    "Show Mylliem block and Mawkyrwat block",            # names Megh knows are left as said
    "Show the expenditure breakdown for Myriem",         # no block word: never guessed
    "How have MGNREGA person-days changed over the last three years in West Garo Hills?",
]


@pytest.mark.parametrize("said", LEFT_ALONE)
def test_ambiguous_or_correct_text_is_left_as_said(said):
    assert text(said) == said


def test_corrections_name_what_was_heard():
    c = C.clean("PMAY-G houses in reply in 2022-23")
    assert c.corrections == [{"heard": "reply", "wrote": "Ri Bhoi", "kind": "place"}]
    assert C.clean("How many CML8 applications?").corrections == [
        {"heard": "CML8", "wrote": "CM Elevate", "kind": "scheme"}]


def test_case_and_number_style_are_not_reported_as_corrections():
    c = C.clean("pmay-g houses in west garo hills in twenty twenty three to twenty twenty four")
    assert c.text == "PMAY-G houses in West Garo Hills in 2023-24"
    assert c.corrections == []


def test_spelling_pass_keeps_only_scheme_district_block():
    c = C.clean("how many fokus plus beneficiaries in ribhoy")
    assert c.text == "how many Focus Plus beneficiaries in Ri Bhoi"
    assert {x["kind"] for x in c.corrections} == {"scheme", "place"}


# ── typed questions are unaffected; cleaned text is stable under the typed pipeline ──

BANK = QUESTIONS + [k[1] for k in KNOWN] + LEFT_ALONE


# The typed pipeline's own word rewrites ("sent" -> "spent", "higher" -> "highest", KI-724) still run on a
# dictated question exactly as on a typed one; dictation adds nothing for them to undo.
TYPED_WORD_REWRITES = {"CM Elevate applications sent back in East Khasi Hills", "Which one is higher?"}


@pytest.mark.parametrize("x", BANK)
def test_typed_pipeline_does_not_rewrite_cleaned_text(x):
    once = text(x)
    n = spelling.normalise(once)
    names = [c for c in n.corrections if c.kind in C.SPELLING_KINDS and C.letters(c.typed) != C.letters(c.canonical)]
    assert names == []
    if once not in TYPED_WORD_REWRITES:
        assert n.text == once
    assert text(once) == once                           # idempotent


def test_the_table_is_read_by_dictation_only():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    users = [p for p in root.rglob("*.py") if "dictation_hearing" in p.read_text(encoding="utf-8")]
    assert {p.parent.name for p in users} == {"dictation"}
    readers = [p.name for p in users if "TABLE_FILE" in p.read_text(encoding="utf-8")]
    assert readers == ["clean.py"]


# ── guards (asr_guard + the relisten guards) ────────────────────────────────

P = settings.ASR_PROMPT


@pytest.mark.parametrize("raw,voiced,secs,why", [
    ("", 1.0, 1.0, "empty"),
    ("Okay.", 0.4, 1.0, "no speech"),
    ("I'm not sure.", 2.0, 2.0, "no speech"),
    (P, 0.0, 4.0, "prompt echo"),
    ("Questions about Meghalaya government schemes", 0.0, 2.0, "prompt echo"),
    ("Yes.", 2.4, 3.0, "a lone word for a long stretch of voice"),
    ("How many houses were sanctioned in every district of the state this year", 0.2, 0.3,
     "too many letters for the voice heard"),
])
def test_guards(raw, voiced, secs, why):
    assert C.why_not(raw, P, voiced, secs) == why


@pytest.mark.parametrize("raw", ["Yes.", "No", "How many houses in Ri Bhoi?",
                                 "Compare East Khasi Hills and West Garo Hills across every scheme"])
def test_real_words_pass_the_guards(raw):
    assert C.why_not(raw, P, 1.0, 3.0) == ""


# ── numbers on their own ────────────────────────────────────────────────────

@pytest.mark.parametrize("n,want", [(5, "5"), (1000, "1,000"), (100000, "1,00,000"), (12345678, "1,23,45,678")])
def test_indian_grouping(n, want):
    assert N.indian(n) == want


def test_twenty_five_to_twenty_six_is_a_range_not_a_year():
    assert N.spoken_text("twenty five to twenty six households") == "25 to 26 households"


def test_non_consecutive_years_stay_a_range():
    assert N.spoken_text("from 2019 to 2022") == "from 2019 to 2022"


# ── joining segments and the whole-recording pass ───────────────────────────

def test_a_full_stop_at_a_short_pause_is_dropped():
    assert join_parts([("How many houses.", 0.0), ("Were completed in Ri Bhoi?", 0.6)]) == \
        "How many houses were completed in Ri Bhoi?"


def test_a_name_keeps_its_capital_and_a_long_pause_keeps_the_stop():
    assert join_parts([("Houses in.", 0.0), ("Ri Bhoi.", 0.6)]) == "Houses in Ri Bhoi."
    assert join_parts([("Show the houses.", 0.0), ("Now the wages.", 1.4)]) == "Show the houses. Now the wages."


def test_whole_pass_wins_unless_it_loses_a_fact():
    segs = "MGNREGA person-days in Ri Bhoi in 2023-24"
    assert merge("MGNREGA person days in Ri Bhoi in 2023-24.", segs)[1] == "whole"
    assert merge("MGNREGA person-days in reply in 2023-24", segs) == (segs, "segments")
    assert merge("MGNREGA person-days in Ri Bhoi", segs) == (segs, "segments")
    assert merge("", segs) == (segs, "segments")
    assert facts("CM Elevate Legacy subsidy in FY 2023-24") == {"cm elevate legacy", "2023-24"}


# ── the segmenter ───────────────────────────────────────────────────────────

def _tone(s, amp=0.2):
    t = np.arange(int(s * 16000)) / 16000
    return np.sin(2 * np.pi * 200 * t) * amp


def _pcm(x):
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def test_a_pause_of_half_a_second_closes_a_segment_and_nothing_is_dropped():
    x = np.concatenate([np.zeros(3200), _tone(1.0), np.zeros(int(0.7 * 16000)), _tone(0.8), np.zeros(3200)])
    s = Segmenter()
    segs = []
    data = _pcm(x)
    for i in range(0, len(data), 2560):
        segs += s.feed(data[i:i + 2560])
    tail = s.flush()
    segs.append(tail)
    assert len(segs) == 2
    assert sum(len(g.pcm) for g in segs) == len(data)            # every sample, once
    assert abs(segs[0].end_s - 1.7) < 0.1


def test_a_short_breath_does_not_cut():
    x = np.concatenate([_tone(1.0), np.zeros(int(0.3 * 16000)), _tone(1.0)])
    s = Segmenter()
    assert s.feed(_pcm(x)) == []


def test_twelve_seconds_without_a_pause_is_cut_at_the_quietest_point():
    pieces = []
    for k in range(16):
        pieces += [_tone(0.9), np.zeros(int(0.2 * 16000)) + (0.0 if k == 12 else 0.0)]
    x = np.concatenate(pieces)
    s = Segmenter()
    segs = s.feed(_pcm(x))
    assert segs and segs[0].seconds <= 12.0
    first = segs[0].pcm
    tail = np.frombuffer(first[-640:], dtype="<i2")
    assert np.abs(tail).max() < 100                              # cut in a gap, not inside a "word"


def test_silence_only_is_not_cut_at_pauses():
    s = Segmenter()
    assert s.feed(_pcm(np.zeros(16000 * 5))) == []
