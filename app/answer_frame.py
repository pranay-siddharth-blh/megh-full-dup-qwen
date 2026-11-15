"""
The answer frame (D-110, 2026-11-15): a structured record of WHAT the last data answer was.

Why: every follow-up rule ("break that down by district", "only Ri Bhoi", "which is the lowest", "top 3", "what about
2023-24", "and the households instead") used to re-read the previous question's WORDS and edit them (c01). The words
of a question do not say reliably what was answered: "across all districts" was a district grouping to one reader and
a statewide total to another, a rule's own output ("Top 3 districts: ...") was a shape the next rule could not read,
and nothing carried the measure, the grouping, the order or the limit. The pieces existed (the catalogue's metric
key, the final SQL, the resolved filters, the chart) and were thrown away after the answer.

What: one small plain-data record per data answer, filled DETERMINISTICALLY after the answer is assembled
(pipeline c18 `_c18_fill_frame`): from the catalogue's own query when it answered, else from the final SQL (sql_ast),
else left empty. Nothing is guessed: a field the evidence does not state is None. It lives on `Turn.answer_frame`
(a dict, so the turn stays JSON-round-trippable through the graph state and the durable snapshot), in the topic
ledger and in the context frames (D-100).

The follow-up resolver (c18 `_c18_frame_followup`) reads a follow-up as an EDIT of this record and renders one
canonical standalone question from the edited record, so every rule's output is a shape the rules read back.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

QTYPES = ("total", "breakdown", "ranking", "compare", "list", "other")
GROUPS = ("district", "block", "village", "constituency", "year", "month", "scheme")
SOURCES = ("catalogue", "fixed", "model", "cross")
# The resolved-entity keys a frame records as its filters (exactly as resolved).
FILTER_KEYS = ("district", "block", "village_code", "village", "assembly_constituency", "year_key",
               "district_list", "block_list", "village_code_list", "assembly_constituency_list", "year_key_list")


@dataclass
class AnswerFrame:
    schemes: list = field(default_factory=list)
    metric_key: "str | None" = None          # the catalogue key, when the catalogue answered or named it
    measure_text: "str | None" = None        # the question's own measure words (scheme kept), no scope / shape
    qtype: "str | None" = None               # one of QTYPES, None when the evidence does not say
    group: "str | None" = None               # one of GROUPS, None = no grouping (or unknown when qtype is None)
    filters: dict = field(default_factory=dict)
    all_years: bool = False                  # the question stated all financial years and no year
    order: "str | None" = None               # "asc" / "desc"
    limit: "int | None" = None
    chart: "str | None" = None
    source: "str | None" = None              # one of SOURCES, None when unknown
    sql_shape: "str | None" = None           # a short fingerprint of the final SQL's shape
    question: str = ""                       # the standalone question the frame describes

    def to_dict(self) -> dict:
        d = asdict(self)
        d["schemes"] = list(self.schemes or [])
        d["filters"] = dict(self.filters or {})
        return d

    @classmethod
    def from_dict(cls, d: "dict | None") -> "AnswerFrame":
        d = d if isinstance(d, dict) else {}
        limit = d.get("limit")
        try:
            limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit = None
        return cls(schemes=list(d.get("schemes") or []), metric_key=d.get("metric_key"),
                   measure_text=d.get("measure_text"), qtype=d.get("qtype"), group=d.get("group"),
                   filters=dict(d.get("filters") or {}), all_years=bool(d.get("all_years")),
                   order=d.get("order"), limit=limit, chart=d.get("chart"), source=d.get("source"),
                   sql_shape=d.get("sql_shape"), question=str(d.get("question") or ""))

    def is_empty(self) -> bool:
        return not self.schemes and self.qtype is None and not self.question


def from_turn(turn) -> AnswerFrame:
    """The frame a turn carries (an empty frame for a turn written before frames existed)."""
    return AnswerFrame.from_dict(getattr(turn, "answer_frame", None) or {})
