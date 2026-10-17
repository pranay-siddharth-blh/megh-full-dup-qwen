"""RAG upgrade Phase 6 (2026-10-15): citations under knowledge answers and
👍 / 👎 feedback (app/routers/feedback.py, table app.answer_feedback)."""
import asyncio
import json

import pytest

from app import auth, rag
from app.routers import feedback as fb


# ── citations ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("doc,scheme,heading,title,section", [
    ("incoming/PMAY-G/pmay_gramin_general_faq.md", "PMAY-G",
     "What documents are typically required for PMAY-Gramin?",
     "PMAY-G FAQ", "What documents are typically required for PMAY-Gramin?"),
    ("incoming/PMAY-G/pmay_gramin_complete_reference.md", "PMAY-G",
     "5. Eligibility Criteria > 5.2 PMAY-Gramin Beneficiary Identification",
     "PMAY-G Reference", "Eligibility Criteria › PMAY-Gramin Beneficiary Identification"),
    ("incoming/Focus_Legacy/FOCUS_LEGACY_FAQ.md", "Focus Legacy", "8a. How do I apply for FOCUS?",
     "FOCUS (Legacy) FAQ", "How do I apply for FOCUS?"),
    ("web/MGNREGA_Wikipedia.md", "MGNREGA", "(intro)", "MGNREGA background (Wikipedia)", "Overview"),
    ("incoming/CM_Elevate/CM_Elevate_Complete_Reference.md", "CM Elevate", "12. Complete End-to-End Process Flow",
     "CM-ELEVATE Reference", "Complete End-to-End Process Flow"),
])
def test_citation_titles(doc, scheme, heading, title, section):
    assert rag.citations([{"doc": doc, "scheme": scheme, "heading": heading}]) == [{"title": title, "section": section}]


def test_citations_are_distinct_and_capped():
    ch = [{"doc": "incoming/PMAY-G/pmay_gramin_complete_reference.md", "scheme": "PMAY-G",
           "heading": "5. Eligibility Criteria > 5.1 General"},
          {"doc": "incoming/PMAY-G/pmay_gramin_complete_reference.md", "scheme": "PMAY-G",
           "heading": "5. Eligibility Criteria > 5.2 Identification"},
          {"doc": "incoming/PMAY-G/pmay_gramin_general_faq.md", "scheme": "PMAY-G", "heading": "Who is eligible?"},
          {"doc": "web/PMAY_Wikipedia.md", "scheme": "PMAY-G", "heading": "(intro)"}]
    out = rag.citations(ch)
    assert [c["title"] for c in out] == ["PMAY-G Reference", "PMAY-G FAQ"]


def test_a_long_section_is_shortened():
    c = rag.citations([{"doc": "x_faq.md", "scheme": "MGNREGA", "heading": "Q " * 80}])[0]
    assert len(c["section"]) <= 80 and c["section"].endswith("…")


def test_answer_from_kb_returns_citations(monkeypatch):
    async def fake_retrieve(q, scheme=None, expand=True):
        return [{"score": 0.7, "text": "Aadhaar is needed.", "doc": "incoming/PMAY-G/pmay_gramin_general_faq.md",
                 "heading": "What documents are typically required for PMAY-Gramin?", "scheme": "PMAY-G"}]

    async def fake_compose(prompt):
        return "Aadhaar is needed."

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag.llm, "call_response_composer", fake_compose)
    monkeypatch.setattr(rag.settings, "RAG_GROUNDING_CHECK", False)
    out = asyncio.run(rag.answer_from_kb("documents for PMAY-G?", scheme="PMAY-G"))
    assert out["citations"] == [{"title": "PMAY-G FAQ",
                                 "section": "What documents are typically required for PMAY-Gramin?"}]


# ── feedback ────────────────────────────────────────────────────────────────

def _scope(tenant=1, cross=False):
    return auth.UserScope(user_id="u", username="officer1", tenant_id=tenant, db_user_id=7,
                          role="super_admin" if cross else "tenant_admin", granularity_cap="village",
                          schemes=[], geographies="all")


@pytest.fixture
def calls(monkeypatch):
    log = []

    async def execute(sql, params=None):
        log.append((" ".join(sql.split()), params))
        return "OK"

    async def fetch_rows(sql, params=None):
        log.append((" ".join(sql.split()), params))
        return [{"feedback_id": 1, "citations": json.dumps([{"title": "PMAY-G FAQ", "section": "Docs"}]),
                 "rating": -1, "question": "q"}]

    async def fetchrow(sql, params=None):
        log.append((" ".join(sql.split()), params))
        return {"up": 3, "down": 2}

    monkeypatch.setattr(fb.db, "execute", execute)
    monkeypatch.setattr(fb.db, "fetch_rows", fetch_rows)
    monkeypatch.setattr(fb.db, "fetchrow", fetchrow)
    return log


def test_a_vote_is_saved_as_the_officer_and_upserted(calls):
    body = fb.FeedbackBody(message_key="s1:m4", rating=-1, question="documents?", answer="Aadhaar.",
                           route="knowledge", schemes=["PMAY-G"],
                           citations=[{"title": "PMAY-G FAQ", "section": "Docs"}], comment="  Incomplete ")
    assert asyncio.run(fb.give_feedback(body, _scope())) == {"ok": True, "rating": -1}
    sql, params = calls[0]
    assert "INSERT INTO app.answer_feedback" in sql and "ON CONFLICT (user_id, message_key)" in sql
    assert params[1] == 7 and params[2] == "officer1" and params[4] == "s1:m4" and params[10] == -1
    assert params[11] == "Incomplete" and json.loads(params[9]) == [{"title": "PMAY-G FAQ", "section": "Docs"}]


def test_rating_zero_takes_the_vote_back_for_this_officer_only(calls):
    body = fb.FeedbackBody(message_key="s1:m4", rating=0, question="documents?")
    asyncio.run(fb.give_feedback(body, _scope()))
    sql, params = calls[0]
    assert sql.startswith("DELETE FROM app.answer_feedback WHERE user_id = $1") and params == [7, "s1:m4"]


@pytest.mark.parametrize("bad", [2, -2])
def test_only_up_down_or_zero(bad):
    with pytest.raises(Exception):
        fb.FeedbackBody(message_key="k", rating=bad, question="q")


def test_tenant_admin_sees_only_their_tenant(calls):
    out = asyncio.run(fb.list_feedback(rating=-1, limit=50, tenant_id=99, scope=_scope(tenant=1)))
    sql, params = calls[0]
    assert "tenant_id = $1" in sql and "rating = $2" in sql and params == [1, -1, 50]
    assert out["up"] == 3 and out["down"] == 2
    assert out["feedback"][0]["citations"] == [{"title": "PMAY-G FAQ", "section": "Docs"}]


def test_super_admin_sees_all_or_the_tenant_asked_for(calls):
    asyncio.run(fb.list_feedback(rating=None, limit=50, tenant_id=None, scope=_scope(cross=True)))
    assert "WHERE" not in calls[0][0] and calls[0][1] == [50]
