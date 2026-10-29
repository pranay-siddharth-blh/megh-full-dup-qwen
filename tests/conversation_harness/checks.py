"""
Expectation checks for one turn of a conversation scenario. Pure functions over
the normalised turn record (see drivers.TurnRecord) and the earlier records of
the same conversation, so they are unit-testable without models or a database.

Expectation keys (all optional; every key present must hold):
  route               data | knowledge | edge | pause | denied | error
  edge_type           the edge reply kind (edge route only), e.g. scope_general, recap
  pause_rule          the clarification rule (pause route only), e.g. year-not-specified
  scheme / place / year
                      components of the scope banner ("MGNREGA", "West Garo Hills",
                      "FY 2023-24"); place "all" = All of Meghalaya; year "none" = no year
  banner              the whole scope banner, exactly ("(from earlier)" suffix ignored)
  from_earlier        true when the banner must carry "(from earlier)" (a ledger restore)
  new_question        true/false: the banner must / must not carry "(new question)" (D-061:
                      a self-sufficient question set the chat's scope aside)
  place_not / year_not  the banner's place / year must NOT be this (D-061: "not the old
                      district / year", whatever the latest FY is when the run happens)
  numbers_any         at least one of these numbers appears in the answer (commas ignored)
  numbers_all         every one of these numbers appears in the answer
  answer_contains     every phrase appears in the answer (case-insensitive)
  answer_not_contains no phrase appears in the answer (leak check)
  chips_contain       every phrase appears in some chip (follow-ups / options)
  chips_min           at least this many chips
  same_scope_as       1-based index of an earlier turn whose banner components must match
  except              with same_scope_as: components allowed to differ (scheme/place/year)
  same_numbers_as     1-based index of an earlier turn whose answer numbers must all reappear
  truth               {"sql": "...", "within": 0} — the first numeric cell of the first row of
                      this read-only query (run by the harness) must appear in the answer
                      (within = allowed absolute difference, default 0; evaluated by run.py)
No regex: numbers through app.text_match.numbers, text through string methods.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.text_match import numbers as _numbers

BANNER_SEP = " · "
FROM_EARLIER = "(from earlier)"
NEW_QUESTION = "(new question)"


@dataclass
class Scope:
    scheme: str | None = None
    place: str | None = None
    year: str | None = None
    from_earlier: bool = False
    new_question: bool = False

    def as_dict(self) -> dict:
        return {"scheme": self.scheme, "place": self.place, "year": self.year, "from_earlier": self.from_earlier,
                "new_question": self.new_question}


def parse_banner(banner: str | None) -> Scope:
    """'MGNREGA · West Garo Hills · FY 2023-24 (from earlier)' -> Scope. A banner has
    the scheme first, then the place, then the year when the answer had one."""
    if not banner:
        return Scope()
    text = banner.strip()
    from_earlier = text.endswith(FROM_EARLIER)
    if from_earlier:
        text = text[: -len(FROM_EARLIER)].strip()
    new_question = text.endswith(NEW_QUESTION)
    if new_question:
        text = text[: -len(NEW_QUESTION)].strip()
    parts = [p.strip() for p in text.split(BANNER_SEP) if p.strip()]
    scheme = parts[0] if parts else None
    place = parts[1] if len(parts) > 1 else None
    year = parts[2] if len(parts) > 2 else None
    if place and place.startswith("FY ") and year is None:      # no place component
        place, year = None, place
    return Scope(scheme, place, year, from_earlier, new_question)


def answer_numbers(text: str | None) -> set[float]:
    out: set[float] = set()
    for n in _numbers(text or ""):
        try:
            out.add(float(n.replace(",", "")))
        except ValueError:
            continue
    return out


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _place_matches(expected: str, actual: str | None) -> bool:
    if expected.lower() == "all":
        return (actual or "").lower() in ("all of meghalaya", "meghalaya")
    return (actual or "").lower() == expected.lower()


def _year_matches(expected: str, actual: str | None) -> bool:
    if expected.lower() == "none":
        return actual is None
    e = expected.lower().replace("fy ", "").strip()
    a = (actual or "").lower().replace("fy ", "").strip()
    return e == a


@dataclass
class TurnRecord:
    """What a driver returns for one turn, normalised across drivers."""
    say: str
    route: str                      # data | knowledge | edge | pause | denied | error | clarification
    answer: str = ""
    edge_type: str | None = None
    pause_rule: str | None = None
    banner: str | None = None
    chips: list = field(default_factory=list)
    ms: int = 0
    status: int | None = None       # HTTP status (HTTP driver)
    raw: dict = field(default_factory=dict)

    @property
    def scope(self) -> Scope:
        return parse_banner(self.banner)


def check_turn(expect: dict | None, rec: TurnRecord, earlier: list[TurnRecord],
               truth_value: float | None = None) -> list[str]:
    """The failures of `rec` against `expect` (empty = pass). `earlier` are the
    records of the previous turns, in order (index 1 = first turn). `truth_value`
    is the DB value run.py fetched for expect["truth"], or None when not fetched."""
    fails: list[str] = []
    if not expect:
        return fails
    route = rec.route if rec.route != "clarification" else "pause"
    if "route" in expect and expect["route"] != route:
        fails.append(f"route {route!r}, expected {expect['route']!r}")
    if "status" in expect and rec.status != expect["status"]:
        fails.append(f"status {rec.status!r}, expected {expect['status']!r}")
    if "edge_type" in expect and (rec.edge_type or "") != expect["edge_type"]:
        fails.append(f"edge_type {rec.edge_type!r}, expected {expect['edge_type']!r}")
    if "pause_rule" in expect and (rec.pause_rule or "") != expect["pause_rule"]:
        fails.append(f"pause_rule {rec.pause_rule!r}, expected {expect['pause_rule']!r}")
    sc = rec.scope
    if "scheme" in expect and (sc.scheme or "").lower() != str(expect["scheme"]).lower():
        fails.append(f"scheme {sc.scheme!r}, expected {expect['scheme']!r}")
    if "place" in expect and not _place_matches(str(expect["place"]), sc.place):
        fails.append(f"place {sc.place!r}, expected {expect['place']!r}")
    if "year" in expect and not _year_matches(str(expect["year"]), sc.year):
        fails.append(f"year {sc.year!r}, expected {expect['year']!r}")
    if "banner" in expect:
        got = (rec.banner or "").replace(FROM_EARLIER, "").replace(NEW_QUESTION, "").strip()
        if got != expect["banner"]:
            fails.append(f"banner {got!r}, expected {expect['banner']!r}")
    if "from_earlier" in expect and bool(expect["from_earlier"]) != sc.from_earlier:
        fails.append(f"from_earlier {sc.from_earlier}, expected {bool(expect['from_earlier'])}")
    if "new_question" in expect and bool(expect["new_question"]) != sc.new_question:
        fails.append(f"new_question {sc.new_question}, expected {bool(expect['new_question'])}")
    if "place_not" in expect and sc.place is not None and _place_matches(str(expect["place_not"]), sc.place):
        fails.append(f"place {sc.place!r} must not be {expect['place_not']!r}")
    if "year_not" in expect and sc.year is not None and _year_matches(str(expect["year_not"]), sc.year):
        fails.append(f"year {sc.year!r} must not be {expect['year_not']!r}")
    nums = answer_numbers(rec.answer)
    if "numbers_any" in expect:
        want = [_num(v) for v in expect["numbers_any"]]
        if not any(w in nums for w in want if w is not None):
            fails.append(f"none of {expect['numbers_any']} in the answer (numbers seen: {sorted(nums)[:8]})")
    if "numbers_all" in expect:
        missing = [v for v in expect["numbers_all"] if _num(v) not in nums]
        if missing:
            fails.append(f"numbers missing from the answer: {missing}")
    low = (rec.answer or "").lower()
    for phrase in expect.get("answer_contains", []) or []:
        if str(phrase).lower() not in low:
            fails.append(f"answer lacks {phrase!r}")
    for phrase in expect.get("answer_not_contains", []) or []:
        if str(phrase).lower() in low:
            fails.append(f"answer must not contain {phrase!r} (leak)")
    chips_low = [str(c).lower() for c in (rec.chips or [])]
    for phrase in expect.get("chips_contain", []) or []:
        if not any(str(phrase).lower() in c for c in chips_low):
            fails.append(f"no chip contains {phrase!r} (chips: {rec.chips[:5]})")
    if "chips_min" in expect and len(rec.chips or []) < int(expect["chips_min"]):
        fails.append(f"{len(rec.chips or [])} chips, expected at least {expect['chips_min']}")
    if "same_scope_as" in expect:
        idx = int(expect["same_scope_as"])
        if not (1 <= idx <= len(earlier)):
            fails.append(f"same_scope_as {idx}: no such earlier turn")
        else:
            ref = earlier[idx - 1].scope
            allowed = {str(x).lower() for x in (expect.get("except") or [])}
            for comp in ("scheme", "place", "year"):
                if comp in allowed:
                    continue
                if (getattr(ref, comp) or "").lower() != (getattr(sc, comp) or "").lower():
                    fails.append(f"{comp} {getattr(sc, comp)!r} differs from turn {idx} ({getattr(ref, comp)!r})")
    if "same_numbers_as" in expect:
        idx = int(expect["same_numbers_as"])
        if not (1 <= idx <= len(earlier)):
            fails.append(f"same_numbers_as {idx}: no such earlier turn")
        else:
            ref_nums = answer_numbers(earlier[idx - 1].answer)
            missing = sorted(ref_nums - nums)
            if missing:
                fails.append(f"numbers of turn {idx} missing from the answer: {missing[:6]}")
    if "truth" in expect:
        if truth_value is None:
            fails.append("truth value not available (DB not reachable or query failed)")
        else:
            within = float((expect["truth"] or {}).get("within", 0) or 0)
            if not any(abs(n - truth_value) <= within for n in nums):
                fails.append(f"truth {truth_value} not in the answer (numbers seen: {sorted(nums)[:8]})")
    return fails


SCENARIO_KEYS = {"name", "doc", "account", "tags", "turns", "skip", "drivers", "_file"}   # _file: set by the loader
TURN_KEYS = {"say", "expect", "note", "as_account"}
EXPECT_KEYS = {"route", "edge_type", "pause_rule", "scheme", "place", "year", "banner", "from_earlier", "new_question",
               "place_not", "year_not", "numbers_any",
               "numbers_all", "answer_contains", "answer_not_contains", "chips_contain", "chips_min", "same_scope_as",
               "except", "same_numbers_as", "truth", "status"}


def validate_scenario(sc: dict) -> list[str]:
    """Structural problems of a scenario dict (empty = fine)."""
    out: list[str] = []
    if not isinstance(sc, dict):
        return ["scenario is not a mapping"]
    unknown = set(sc) - SCENARIO_KEYS
    if unknown:
        out.append(f"unknown scenario keys: {sorted(unknown)}")
    if not sc.get("name"):
        out.append("missing name")
    turns = sc.get("turns")
    if not isinstance(turns, list) or not turns:
        return out + ["turns must be a non-empty list"]
    for i, t in enumerate(turns, 1):
        if not isinstance(t, dict) or not t.get("say"):
            out.append(f"turn {i}: needs 'say'")
            continue
        unknown = set(t) - TURN_KEYS
        if unknown:
            out.append(f"turn {i}: unknown keys {sorted(unknown)}")
        exp = t.get("expect") or {}
        unknown = set(exp) - EXPECT_KEYS
        if unknown:
            out.append(f"turn {i}: unknown expect keys {sorted(unknown)}")
        for ref in ("same_scope_as", "same_numbers_as"):
            if ref in exp and not (1 <= int(exp[ref]) < i):
                out.append(f"turn {i}: {ref} must point to an earlier turn")
        if "truth" in exp and not (isinstance(exp["truth"], dict) and exp["truth"].get("sql")):
            out.append(f"turn {i}: truth needs a 'sql'")
    return out
