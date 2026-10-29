"""
E12 security / RBAC (RAG-plan handover, 2026-10-29): KI-418, KI-419, KI-420, KI-421,
the gateway CA file failing closed, and the Qdrant key / CA in insecure_secrets.

- KI-418: a tenant admin can no longer grant super_admin, or change / reset /
  deactivate a super_admin (routers/admin.py update_user, deactivate_user).
- KI-419: the four fixed answers that return before the graph's authorize node are
  authorised (c13), and an area-pinned account gets no statewide caveat figure.
- KI-420: /api/scheme-stats returns only the caller's schemes' cards.
- KI-421: scope_from_user fails closed; the admin API refuses unknown values.

Every test calls the real function. The graph tests drive whole turns through
the LangGraph orchestrator with the models and megh_db stubbed (the env fixture
of tests/test_pipeline_graph.py). Nothing here needs the VPN.
    .venv/Scripts/python.exe -m pytest tests/test_rbac_e12_2026_10_29.py -q
"""
import asyncio
import logging
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import auth, cross_figures, llm, pipeline as p, scheme_registry  # noqa: E402
from app import config  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import admin, stats  # noqa: E402
from _graph_turn import graph_turn  # noqa: E402
from test_pipeline_graph import _loaded, env  # noqa: E402,F401 — the shared stubs

ALL = list(scheme_registry.NAMES)


def _officer(district="EAST KHASI HILLS", schemes=None, role="district_officer", cap="block"):
    return auth.UserScope(user_id="o", role=role, granularity_cap=cap,
                          schemes=list(schemes or ALL),
                          geographies={"districts": [district], "blocks": []})


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)


# ── KI-421: scope_from_user fails closed ─────────────────────────────────────

def test_a_scheme_typo_grants_no_scheme():
    sc = auth.scope_from_user({"username": "u", "role": "analyst", "schemes": ["Focus+"]})
    assert sc.schemes == []
    d = auth.authorize(sc, schemes=["MGNREGA"], resolved_entities={}, sql=None)
    assert not d.allow and d.check == "scheme"
    assert "not yet authorised for any scheme" in d.reason


def test_a_real_scheme_list_still_narrows():
    sc = auth.scope_from_user({"username": "u", "role": "analyst", "schemes": ["PMAY-G", " MGNREGA "]})
    assert sc.schemes == ["MGNREGA", "PMAY-G"]


def test_an_unknown_role_gets_public():
    sc = auth.scope_from_user({"username": "u", "role": "chief_wizard"})
    assert sc.role == "public" and sc.granularity_cap == "state" and not sc.is_admin


def test_the_user_cap_can_only_narrow_the_role_cap():
    # state_officer is capped at district: a per-user "village" used to widen it
    assert auth.scope_from_user({"role": "state_officer", "granularity_cap": "village"}).granularity_cap == "district"
    assert auth.scope_from_user({"role": "analyst", "granularity_cap": "District"}).granularity_cap == "district"


def test_an_unknown_cap_is_ignored_and_never_crashes_authorize():
    sc = auth.scope_from_user({"role": "analyst", "granularity_cap": "ward"})
    assert sc.granularity_cap == "village"
    # used to raise ValueError in GRANULARITY_ORDER.index on every data question
    assert auth.authorize(sc, schemes=["MGNREGA"], resolved_entities={"district": "RI BHOI"},
                          sql=None).allow


@pytest.mark.parametrize("model", [admin.NewUser, admin.UpdateUser])
@pytest.mark.parametrize("field,value", [("role", "chief_wizard"), ("schemes", ["Focus+"]),
                                         ("granularity_cap", "ward")])
def test_admin_api_refuses_unknown_values(model, field, value):
    base = {"username": "x", "password": "longenough1", "role": "analyst"} if model is admin.NewUser else {}
    with pytest.raises(ValidationError):
        model(**{**base, field: value})


def test_admin_api_accepts_and_normalises_known_values():
    u = admin.UpdateUser(role="district_officer", schemes=[" PMAY-G"], granularity_cap="Block")
    assert u.schemes == ["PMAY-G"] and u.granularity_cap == "block"


# ── KI-418: tenant admins cannot take over super_admin ───────────────────────

def _admin_scope(role="tenant_admin", uid=1):
    return auth.UserScope(user_id="a", role=role, granularity_cap="village", schemes=ALL,
                          geographies="all", tenant_id=1, db_user_id=uid)


@pytest.fixture
def users(monkeypatch):
    db = {1: {"user_id": 1, "tenant_id": 1, "role": "tenant_admin", "username": "ta"},
          2: {"user_id": 2, "tenant_id": 1, "role": "super_admin", "username": "sa"},
          3: {"user_id": 3, "tenant_id": 1, "role": "district_officer", "username": "do"}}
    done = []

    async def get_user(uid):
        return dict(db[uid]) if uid in db else None

    async def update_user(uid, **kw):
        done.append(("update", uid, kw))
        return {**db[uid], **kw}

    async def delete_user(uid):
        done.append(("deactivate", uid))

    monkeypatch.setattr(admin.appdb, "get_user", get_user)
    monkeypatch.setattr(admin.appdb, "update_user", update_user)
    monkeypatch.setattr(admin.appdb, "delete_user", delete_user)
    return done


@pytest.mark.parametrize("uid,body", [
    (3, {"role": "super_admin"}),            # raise another user
    (1, {"role": "super_admin"}),            # raise yourself
    (2, {"password": "a-new-password"}),     # reset a super_admin's password
    (2, {"role": "analyst"}),                # demote a super_admin
    (2, {"is_active": False}),               # deactivate one through PATCH
])
def test_tenant_admin_cannot_touch_super_admin(users, uid, body):
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin.update_user(uid, admin.UpdateUser(**body), scope=_admin_scope()))
    assert e.value.status_code == 403 and not users


def test_tenant_admin_cannot_deactivate_super_admin(users):
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin.deactivate_user(2, scope=_admin_scope()))
    assert e.value.status_code == 403 and not users


def test_nobody_changes_their_own_role(users):
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin.update_user(1, admin.UpdateUser(role="analyst"), scope=_admin_scope()))
    assert e.value.status_code == 403 and not users


def test_tenant_admin_still_manages_officers(users):
    asyncio.run(admin.update_user(3, admin.UpdateUser(role="block_officer", password="a-new-password"),
                                  scope=_admin_scope()))
    asyncio.run(admin.deactivate_user(3, scope=_admin_scope()))
    assert [u[0] for u in users] == ["update", "deactivate"]


def test_super_admin_may_grant_and_manage_super_admin(users):
    sa = _admin_scope("super_admin", uid=99)
    asyncio.run(admin.update_user(3, admin.UpdateUser(role="super_admin"), scope=sa))
    asyncio.run(admin.update_user(2, admin.UpdateUser(password="a-new-password"), scope=sa))
    assert len(users) == 2


# ── KI-420: the welcome cards follow the caller's schemes ────────────────────

def _card_body():
    keys = list(stats._CARD_SCHEME)
    return {"cards": {k: [["1", "x"]] for k in keys}, "periods": {k: "FY" for k in keys}, "as_of": "t"}


def test_card_keys_are_the_cards_the_endpoint_builds():
    empty = {k: {c: None for c in ("person_days", "exp_lakh", "villages", "sanctioned", "completed",
                                    "released", "payments", "amount", "districts", "applications",
                                    "schemes", "groups", "memberships", "records", "disbursed")}
             for k in stats._SQL}
    assert set(stats._cards(empty, {})) == set(stats._CARD_SCHEME)


def test_a_pmay_only_user_sees_one_card(monkeypatch):
    monkeypatch.setattr(stats, "_cache", {"at": 0.0, "body": None})

    async def compute():
        return _card_body()
    monkeypatch.setattr(stats, "_compute", compute)
    sc = auth.scope_from_user({"username": "u", "role": "analyst", "schemes": ["PMAY-G"]})
    out = asyncio.run(stats.scheme_stats(scope=sc))
    assert list(out["cards"]) == ["pmay_g"] and list(out["periods"]) == ["pmay_g"]
    # the shared cache still holds all six for the next caller
    assert len(stats._cache["body"]["cards"]) == 6
    every = asyncio.run(stats.scheme_stats(scope=auth.scope_from_user({"username": "a", "role": "analyst"})))
    assert len(every["cards"]) == 6


# ── KI-419: the four fixed answers are authorised ────────────────────────────

def _pg_row(district, block):
    return {"pg_id": "PG-1", "pg_name": "Green Valley", "district": district, "block": block,
            "group_size": 12, "smallest_recorded_size": 12, "payments": 2, "amount_disbursed": 20000}


def test_pg_name_answer_drops_groups_outside_the_area(monkeypatch, auth_on):
    async def run_readonly(sql):
        return [] if "pg_search" in sql.split("FROM", 1)[1].split("WHERE")[0] else [
            _pg_row("WEST GARO HILLS", "SELSELLA")]
    monkeypatch.setattr(p, "run_readonly", run_readonly)
    q = "How many members are there in Green Valley PG?"
    out = asyncio.run(p._focus_legacy_pg_name_answer(q, _officer("EAST KHASI HILLS")))
    assert "SELSELLA" not in out["answer"].upper() and "WEST GARO" not in out["answer"].upper()
    assert "authorised area" in out["answer"] and out["rows"] == []
    # inside the area it is answered as before
    inside = asyncio.run(p._focus_legacy_pg_name_answer(q, _officer("WEST GARO HILLS")))
    assert "12 members" in inside["answer"] and inside["rows"]
    # no scope (AUTH off / admin path): unchanged
    assert "12 members" in asyncio.run(p._focus_legacy_pg_name_answer(q))["answer"]


def test_pg_name_answer_is_scheme_checked_on_the_graph(env, monkeypatch, auth_on):
    async def classify_scheme(_q):
        return ["Focus Legacy"]
    monkeypatch.setattr(p, "classify_scheme", classify_scheme)
    env.run_rows = [[], [_pg_row("EAST KHASI HILLS", "MYLLIEM")]]
    out = asyncio.run(graph_turn("How many members are there in Green Valley PG?",
                                 scope=_officer(schemes=["MGNREGA"])))
    assert out["route"] == "denied" and out["denied_by"] == "scheme"
    assert "Green Valley" not in out["answer"]


def test_focus_plus_summary_is_authorised_on_the_graph(env, monkeypatch, auth_on):
    async def classify_scheme(_q):
        return ["Focus Plus"]
    monkeypatch.setattr(p, "classify_scheme", classify_scheme)
    seen = []

    async def run_readonly(sql):
        seen.append(sql)
        return [{"payments": 1}]
    monkeypatch.setattr(p, "run_readonly", run_readonly)
    out = asyncio.run(graph_turn("Give me an overall Focus+ data summary", scope=_officer()))
    assert out["route"] == "denied" and out["denied_by"] == "geography"
    assert p._FOCUSPLUS_OVERALL_SUMMARY_SQL not in seen


def test_cross_scheme_figures_are_authorised(monkeypatch, auth_on):
    # _cross_scheme_scope is the clarification_gate stage of a cross-scheme turn
    ran = []

    async def fetch_rows(sql, params):
        ran.append(sql)
        if "DISTINCT year_key AS y" in sql:
            return [{"y": 2023}]
        return [{"k": k, "ben": 10, "money": 1.0, "villages": 1, "districts": 1, "blocks": 1,
                 "completed": 1, "sanctioned": 1.0, "pgs": 1, "payments": 1}
                for k in ("EAST KHASI HILLS", "WEST GARO HILLS")]
    monkeypatch.setattr(cross_figures.db, "fetch_rows", fetch_rows)
    two = ["PMAY-G", "Focus Plus"]

    def turn(q, scope, resolved=None):
        ran.clear()
        d = {"question": q, "schemes": two, "cross": {"text": q, "schemes": two},
             "entity_result": {"resolved": dict(resolved or {}), "display": {}},
             "prior_resolved": {}, "skip_scope_clarify": False}
        return asyncio.run(p._data_clarification_stage(d, scope))

    per_district = "In which districts does Focus+ have more beneficiaries than PMAY-G?"
    assert cross_figures.plan(per_district, two, {}, {}, p._SCHEME_NAME_MATCHER).by_district
    denied = turn(per_district, _officer())
    assert denied["route"] == "denied" and denied["denied_by"] == "geography"
    assert not ran and "WEST GARO" not in denied["answer"].upper()        # nothing was queried
    # a state officer may see one figure per district (district is their cap)
    state = turn(per_district, auth.scope_from_user({"username": "s", "role": "state_officer"}))
    assert state["route"] == "data" and state["rows"] and ran
    # a district officer: their own district, never another one
    own = "Compare beneficiaries in PMAY-G and Focus Plus in East Khasi Hills"
    assert turn(own, _officer(), {"district": "EAST KHASI HILLS"})["route"] == "data"
    other = turn(own.replace("East Khasi", "West Garo"), _officer(), {"district": "WEST GARO HILLS"})
    assert other["route"] == "denied" and other["denied_by"] == "geography" and not ran


def test_women_unrecorded_answer_is_authorised_on_the_graph(env, monkeypatch, auth_on):
    async def classify_scheme(_q):
        return ["MGNREGA"]

    async def year_women():
        return [{"year_key": 2024, "fy": "2024-25", "women": 5}, {"year_key": 2025, "fy": "2025-26", "women": 0}]
    monkeypatch.setattr(p, "classify_scheme", classify_scheme)
    monkeypatch.setattr(p, "_mgnrega_year_women", year_women)
    out = asyncio.run(graph_turn("How many women were employed under MGNREGA in East Khasi Hills in FY 2025-26?",
                                 scope=_officer("WEST GARO HILLS")))
    assert out["route"] == "denied" and out["denied_by"] == "geography"


def test_admin_expenditure_caveat_has_no_statewide_figure_for_a_pinned_account(monkeypatch):
    async def fetch_rows(*_a):
        raise AssertionError("statewide figure read for an area-pinned account")
    monkeypatch.setattr(p, "fetch_rows", fetch_rows)
    out = asyncio.run(p._mgnrega_admin_expenditure_answer([{"admin_expenditure_lakh": 0}],
                                                          {"district": "East Khasi Hills"}, statewide=False))
    assert "never populated at source" in out and "Statewide" not in out


# ── Gateway CA file and insecure_secrets ─────────────────────────────────────

def test_missing_ca_file_is_critical_and_flagged(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(settings, "AI_MODEL_CA_BUNDLE_PATH", str(tmp_path / "missing.pem"))
    monkeypatch.setattr(settings, "BOOT_GUARD_ENFORCE", False)
    with caplog.at_level(logging.CRITICAL, logger=llm.logger.name):
        assert llm._get_ssl_verify() is False
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    assert any(s.startswith("AI_MODEL_CA_BUNDLE_PATH") for s in config.insecure_secrets())


def test_missing_ca_file_refuses_in_prod_when_enforced(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AI_MODEL_CA_BUNDLE_PATH", str(tmp_path / "missing.pem"))
    monkeypatch.setattr(settings, "BOOT_GUARD_ENFORCE", True)
    monkeypatch.setattr(settings, "ENV", "prod")
    with pytest.raises(RuntimeError):
        llm._get_ssl_verify()
    monkeypatch.setattr(settings, "ENV", "dev")          # a dev box still boots
    assert llm._get_ssl_verify() is False


def test_present_ca_file_is_used_and_not_flagged(monkeypatch, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    monkeypatch.setattr(settings, "AI_MODEL_CA_BUNDLE_PATH", str(ca))
    monkeypatch.setattr(settings, "BOOT_GUARD_ENFORCE", True)
    assert llm._get_ssl_verify() == str(ca)
    assert not any(s.startswith("AI_MODEL_CA_BUNDLE_PATH") for s in config.insecure_secrets())
