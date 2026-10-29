"""E7 (RAG plan) — a word from the MATCHED measure's own catalogue vocabulary does not
make the question "ask more than the measure".

metric_catalog_eval 2026-10-29: the rephraser writes "person days" as "person days
generated" and "payout" as "disbursement payout"; the catalogue declined those ("asks
more than the measure: generated") although "generated" is the measure's own word
("employment generated"). Words that change the measure ("job cards issued" vs the
job-card stock, "money" for a count) are not in the matched measure's vocabulary and
are still refused.

OFFLINE: the real _metric_catalog_plan with a faked catalogue.
    .venv/Scripts/python.exe -m pytest tests/test_catalogue_vocabulary_e7_2026_10_29.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import metric_catalog as mc, pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402

PD = mc.Metric(key="mgnrega_employment_generated", scheme="MGNREGA", display_name="MGNREGA Person Days",
               expression="SUM(person_days)", base_object="curated.v_employment", unit="person days",
               notes="", alias="employment_generated",
               phrases=(("person", "day"), ("employment", "generated"), ("work", "generated")),
               columns=frozenset({"person_days", "year_key", "lgd_district", "lgd_block", "village_code"}))
JC = mc.Metric(key="mgnrega_job_card_stock", scheme="MGNREGA", display_name="Job card stock",
               expression="SUM(job_cards_issued_total)", base_object="curated.v_employment", unit="job cards",
               notes="", alias="job_card_stock", phrases=(("job", "card"), ("job", "card", "stock")),
               columns=frozenset({"job_cards_issued_total", "year_key", "lgd_district"}))
ER = {"resolved": {"district": "RI BHOI", "year_key": 2023}, "display": {"district": "Ri Bhoi"}}


@pytest.fixture(autouse=True)
def catalogue(monkeypatch):
    monkeypatch.setitem(mc._state, "metrics", {PD.key: PD, JC.key: JC})
    monkeypatch.setitem(mc._state, "by_scheme", {"MGNREGA": [PD, JC]})
    monkeypatch.setitem(mc._state, "loaded", True)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")


def test_the_measures_own_word_is_not_extra():
    plan = p._metric_catalog_plan("How many person days generated in Ri Bhoi in FY 2023-24?", ["MGNREGA"], ER)
    assert plan["metric"] == "mgnrega_employment_generated" and plan["status"] == "built", plan["reason"]


def test_a_word_that_changes_the_measure_is_still_refused():
    plan = p._metric_catalog_plan("How many job cards issued in Ri Bhoi in FY 2023-24?", ["MGNREGA"], ER)
    assert plan["metric"] == "mgnrega_job_card_stock" and plan["query"] is None
    assert "issued" in plan["reason"]
    plan = p._metric_catalog_plan("How much money for person days in Ri Bhoi in FY 2023-24?", ["MGNREGA"], ER)
    assert plan["query"] is None and "money" in plan["reason"]


def test_another_measures_word_is_not_borrowed():
    # "stock" belongs to the job-card measure, not to person days
    plan = p._metric_catalog_plan("person days stock in Ri Bhoi in FY 2023-24", ["MGNREGA"], ER)
    assert plan["query"] is None


def test_the_vocabulary_is_only_the_matched_measures():
    v = p._c16_measure_vocabulary(PD)
    assert {"person", "day", "employment", "generated", "work"} <= v
    assert "stock" not in v and "card" not in v
