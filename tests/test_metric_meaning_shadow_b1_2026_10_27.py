"""B1 (RAG plan; user decision 2026-10-27) — meaning matching never answers.

Measured live (tests/metric_meaning/run_eval.py): embeddings rank "administrative
expenditure" next to total expenditure and "wage rate" next to the wage share as
high as true paraphrases, so a meaning match would state a wrong figure. Instead:
a wording that names no catalogue measure is LOGGED with its nearest measure
(background, never used), and a person approves good wordings as exact synonyms
(data/metric_catalog_synonyms.yaml).

OFFLINE: the real metric_catalog / c16 functions; the embedding call is stubbed.
    .venv/Scripts/python.exe -m pytest tests/test_metric_meaning_shadow_b1_2026_10_27.py -q
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm, metric_catalog as mc, pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402

PD = mc.Metric(key="mgnrega_employment_generated", scheme="MGNREGA", display_name="Person days",
               expression="SUM(person_days)", base_object="curated.v_employment", unit="person days",
               notes="", alias="employment_generated", phrases=(("person", "day"),),
               columns=frozenset({"person_days", "year_key", "lgd_district", "lgd_block", "village_code"}))
EXP = mc.Metric(key="mgnrega_total_expenditure", scheme="MGNREGA", display_name="Expenditure",
                expression="SUM(total_exp)", base_object="curated.v_expenditure", unit="lakh rupees",
                notes="", alias="total_expenditure_lakh", phrases=(("expenditure",),),
                columns=frozenset({"total_exp", "year_key", "lgd_district"}))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def catalogue(monkeypatch, tmp_path):
    monkeypatch.setitem(mc._state, "metrics", {PD.key: PD, EXP.key: EXP})
    monkeypatch.setitem(mc._state, "by_scheme", {"MGNREGA": [PD, EXP]})
    monkeypatch.setitem(mc._state, "loaded", True)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    monkeypatch.setattr(settings, "METRIC_MEANING_SHADOW", True)
    monkeypatch.setattr(settings, "METRIC_MEANING_FILE", str(tmp_path / "shadow.jsonl"))
    monkeypatch.setattr(mc, "_meaning_vectors", {})

    async def embed(texts):          # "labour"/"person" words point one way, money the other
        return [[1.0, 0.1] if ("day" in t or "labour" in t) else [0.1, 1.0] for t in texts]
    monkeypatch.setattr(llm, "call_embedding", embed)
    return tmp_path / "shadow.jsonl"


def test_the_shadow_logs_the_nearest_measure(catalogue):
    rec = _run(mc.meaning_shadow("labour days", "MGNREGA"))
    assert rec["nearest"] == "mgnrega_employment_generated" and rec["score"] > rec["score"] - rec["margin"]
    line = json.loads(catalogue.read_text(encoding="utf-8").splitlines()[0])
    assert line["wording"] == "labour days" and line["scheme"] == "MGNREGA"


def test_the_shadow_is_off_when_switched_off(catalogue, monkeypatch):
    monkeypatch.setattr(settings, "METRIC_MEANING_SHADOW", False)
    assert _run(mc.meaning_shadow("labour days", "MGNREGA")) is None
    assert not catalogue.exists()


def test_an_unmatched_wording_is_recorded_but_never_answered(catalogue):
    er = {"resolved": {"district": "RI BHOI", "year_key": 2023}, "display": {"district": "Ri Bhoi"}}
    plan = p._metric_catalog_plan("How many labour days in Ri Bhoi in FY 2023-24?", ["MGNREGA"], er)
    assert plan["status"] == "none" and plan["query"] is None
    assert plan["unmatched_words"] == "labour days"
    # a literal catalogue wording still matches as before, with nothing logged
    plan = p._metric_catalog_plan("How many person days in Ri Bhoi in FY 2023-24?", ["MGNREGA"], er)
    assert plan["metric"] == "mgnrega_employment_generated" and "unmatched_words" not in plan


def test_approved_synonyms_load_as_exact_phrases(monkeypatch, tmp_path):
    f = tmp_path / "syn.yaml"
    f.write_text("mgnrega_employment_generated:\n  - labour days\nbad: not-a-list\n", encoding="utf-8")
    monkeypatch.setattr(mc, "SYNONYMS_FILE", f)
    assert mc._load_approved_synonyms() == {"mgnrega_employment_generated": ["labour days"]}
    assert mc._phrase("labour days") == ("labour", "day")
    monkeypatch.setattr(mc, "SYNONYMS_FILE", tmp_path / "missing.yaml")
    assert mc._load_approved_synonyms() == {}


def test_the_shipped_synonyms_file_reads():
    assert isinstance(mc._load_approved_synonyms(), dict)
