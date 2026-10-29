"""
CTX-06 (KI-337, 2026-10-29): the shared answer caches are keyed on the words
and the caller's scope, not on the conversation, so routers.query.is_cacheable
must refuse every turn whose answer depends on the chat. It decides before the
pipeline runs, from several word-level checks; this table test runs the REAL
is_cacheable over every turn of every conversation-harness scenario
(tests/conversation_harness/scenarios/*.yaml), so a new scenario is covered the
day it is added.

Nothing about a turn is labelled by hand. A turn depends on its chat when it
replies to a pause, or when its own words do not carry the scope its
expectation names: the scheme (pipeline._named_schemes), the year
(context_policy.extract_year_keys) or the place (entity_resolver.place_mentions).
The chat before it is folded in from the earlier turns' expectations, the way
the conversation would hold it.

Measured 2026-10-29: 274 answered turns, 0 dependent turns the gate would cache,
0 self-contained opening questions it would refuse. No fix was needed.
    .venv/Scripts/python.exe -m pytest tests/test_cacheable_shapes_2026_10_28.py -q
"""
import glob
import sys
import time
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_policy as cp, entity_resolver as er, pipeline as p, topic_memory as tm  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers.query import is_cacheable  # noqa: E402
from app.session_store import Session, Turn  # noqa: E402

_SCENARIOS = sorted(glob.glob(str(Path(__file__).resolve().parent / "conversation_harness" / "scenarios" / "*.yaml")))
_ANSWERED = ("data", "knowledge")


def _scenarios():
    for f in _SCENARIOS:
        for sc in yaml.safe_load(Path(f).read_text(encoding="utf-8")) or []:
            yield pytest.param(sc, id=f"{Path(f).stem}:{sc.get('name')}")


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    er.load_all()


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED", "BACKWARD_RESOLVER_ENABLED"):
        monkeypatch.setattr(settings, flag, True)


def _years(text) -> set:
    return cp.extract_year_keys(text or "")


def _names_scheme(text: str, scheme: str) -> bool:
    return any(tm.same_scheme_family(s, scheme) for s in p._named_schemes(text))


def _names_place(text: str, place) -> bool:
    if not place or str(place).lower() in ("all", "none"):
        return True
    want = set(er.place_mentions(place)) or {str(place).upper()}
    return bool(want & set(er.place_mentions(text)))


def _depends_on_chat(say: str, expect: dict, after_pause: bool) -> bool:
    if after_pause:
        return True
    year = expect.get("year")
    return (not _names_scheme(say, expect["scheme"])
            or (bool(year) and year != "none" and not (_years(year) & _years(say)))
            or not _names_place(say, expect.get("place")))


def _fold(s: Session, say: str, expect: dict) -> None:
    """The chat after this turn, from its expectation."""
    route = expect.get("route")
    s.pending_scope_q = say if route == "pause" else None
    if route == "data" and expect.get("scheme"):
        s.state.scheme = expect["scheme"]
        yk = _years(expect.get("year") or "")
        s.state.year = min(yk) if yk else None
        s.state.district = s.state.block = s.state.village = None
        for name, dim in er.place_mentions(expect.get("place") or "").items():
            if dim in ("district", "block"):
                setattr(s.state, dim, name)
        s.turns.append(Turn(question=say, raw_question=say, route="data", schemes=[expect["scheme"]]))


@pytest.mark.parametrize("scenario", list(_scenarios()))
def test_no_turn_that_depends_on_its_chat_is_cacheable(scenario):
    s = Session(session_id="cache-shapes", user_id="u", created=time.time(), last_seen=time.time())
    prev_route = None
    for i, turn in enumerate(scenario.get("turns") or []):
        say, expect = turn["say"], turn.get("expect") or {}
        if expect.get("route") in _ANSWERED and expect.get("scheme"):
            dependent = _depends_on_chat(say, expect, prev_route == "pause")
            if i == 0:
                dependent = False                   # a fresh chat: nothing to depend on
            cacheable = is_cacheable(say, s)
            assert not (dependent and cacheable), \
                f"turn {i} {say!r} depends on the chat ({expect}) but would be shared through the cache"
            if i == 0:
                assert cacheable, f"the opening question {say!r} names its own scope but is never cached"
        _fold(s, say, expect)
        prev_route = expect.get("route")


def test_the_harness_scenarios_are_found():
    assert len(list(_scenarios())) >= 50
