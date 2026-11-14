"""The live voice transcribes Indian figures as digits + scale words ('2 crore 55 lakh 96 thousand 237').
A descending run is ONE figure, so a correct reading is not a deviation (no spurious 'To be exact' re-read)."""
from app.voice import speech_guard as sg

ANSWER = "Employment generated fell from 2,55,96,237 in FY 2022-23 to 2,33,87,018 in FY 2025-26"


def test_composes_digit_scale_runs():
    assert sg.spoken_values("2 crore 55 lakh 96 thousand 237") == [(25596237.0,)]
    assert sg.spoken_values("1 lakh 71 thousand 107") == [(171107.0,)]
    assert sg.spoken_values("96 thousand 237") == [(96237.0,)]
    assert sg.spoken_values("2 crore and 33 lakh, 87 thousand 18 person-days") == [(23387018.0,)]


def test_words_still_compose():
    vals = sg.spoken_values("nine crore nine lakh fifteen thousand one hundred eighty-one")
    assert vals == [(90915181.0,)]
    assert sg.spoken_values("two crore fifty-five lakh ninety-six thousand two hundred thirty-seven") == [(25596237.0,)]


def test_existing_readings_kept():
    assert sg.spoken_values("37.49 crore") == [(37.49, 374900000.0)]
    assert sg.spoken_values("3,628.67 crore") == [(3628.67, 36286700000.0)]
    assert sg.spoken_values("54,89,616") == [(5489616.0,)]
    assert sg.spoken_values("2023-24") == [(2023.0,), (24.0,)]
    assert sg.spoken_values("5 hundred") == [(5.0,)]


def test_real_voice_transcripts_no_deviation():
    facts = sg.facts_from(ANSWER)
    for said in (
        "Employment generated fell from 2 crore 55 lakh 96 thousand 237 in FY 2022-23 "
        "to 2 crore 33 lakh 87 thousand 18 in FY 2025-26.",
        "It fell from two crore fifty-five lakh ninety-six thousand two hundred thirty-seven "
        "to two crore thirty-three lakh eighty-seven thousand eighteen.",
        "About 2 crore 56 lakh to 2 crore 34 lakh.",
    ):
        assert sg.deviations(said, facts) == [], said


def test_other_answers_no_deviation():
    for answer, said in (
        ("Beneficiaries: 1,71,107.", "There are 1 lakh 71 thousand 107 beneficiaries."),
        ("Spent 3,628.67 crore.", "They spent 3,628.67 crore."),
        ("Total 96,237 households.", "That is 96 thousand 237 households."),
        ("Outlay 9,09,15,181.", "The outlay is nine crore nine lakh fifteen thousand one hundred eighty-one."),
    ):
        assert sg.deviations(said, sg.facts_from(answer)) == [], said


def test_wrong_figure_still_flagged():
    facts = sg.facts_from(ANSWER)
    assert sg.deviations("It was 2 crore 99 lakh in FY 2022-23.", facts) == ["29900000"]
