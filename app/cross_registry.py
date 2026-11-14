"""
Each scheme's cross-scheme roles, read from data/cross_scheme.yaml (2026-11-14).

A question across schemes ("the headline figures across all schemes", "money spent in each scheme in Ri Bhoi",
"compare beneficiaries across all eight schemes") reads each scheme's count, money, villages, years, constituency
and headline figure. Those were hand-kept tables in app/cross_figures.py (_QUERIES, _BEN_NOUN, _MONEY_VERB, _PER,
_COUNT_NOTE, _MONEY_NOTE, _AC_COL, _VILLAGE_SET_FILTER, NO_YEAR, MAIN, SUPPORTED, SHORT), app/cross_scheme.py
(ORDER, SPECS) and app/conversation_layer.py (_MONEY_LABEL); a newly onboarded scheme had to be added to each by
hand, and Homestay was missed in four (2026-11-14). They are now built here from ONE declaration per scheme, so
onboarding a scheme is one YAML entry.

Data only: this module imports nothing from the app but scheme_registry, so any module can import it. The file is
read once at import; a broken file raises at import (a missing scheme would otherwise be a silent wrong answer).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app import scheme_registry

FILE = Path(__file__).resolve().parents[1] / "data" / "cross_scheme.yaml"

# the metric names cross_figures reads; a scheme's own details (completed, sanctioned, pgs, payments, records) are
# allowed beside them
METRIC_NAMES = ("ben", "money", "villages", "districts", "blocks", "completed", "sanctioned", "pgs", "payments",
                "records")


@dataclass(frozen=True)
class Query:
    view: str
    district: str
    block: str
    metrics: "tuple[tuple[str, str], ...]"
    block_fallback: "str | None" = None
    constituency: "str | None" = None


@dataclass(frozen=True)
class Headline:
    """The welcome card's lead figure (routers/stats.py): the same SQL there and in a cross-scheme answer."""
    card: str
    figure: str
    label: str
    noun: str
    view: str
    expr: str


@dataclass(frozen=True)
class Village:
    count_view: str
    base_where: str = "TRUE"
    village_where: str = "village_code IS NOT NULL"
    set_filter: "str | None" = None


@dataclass(frozen=True)
class Entry:
    name: str
    main: bool
    noun: str
    count_note: str
    per: "str | None"
    in_combined: bool
    summed_over_years: bool          # the count adds yearly tallies (no person id: household-years)
    money_verb: "str | None"          # None: the scheme records no money
    money_note: str
    money_label: "str | None"
    years: bool
    constituency: "str | None"
    village: Village
    headline: Headline
    queries: "tuple[Query, ...]"

    @property
    def has_money(self) -> bool:
        return any(m == "money" for q in self.queries for m, _e in q.metrics)


class CrossRegistryError(ValueError):
    pass


def _fixed_sql(where: str, s) -> str:
    """A fixed SQL fragment: a non-empty string with no statement separator or comment."""
    if not isinstance(s, str) or not s.strip():
        raise CrossRegistryError(f"{where}: expected a SQL fragment, got {s!r}")
    for bad in (";", "--", "/*", "$"):
        if bad in s:
            raise CrossRegistryError(f"{where}: {bad!r} is not allowed in a fixed fragment ({s!r})")
    return s


def _entry(d: dict) -> Entry:
    name = d.get("name")
    if name not in scheme_registry.BY_NAME:
        raise CrossRegistryError(f"{name!r} is not a scheme of app/scheme_registry.py")
    count = d.get("count") or {}
    money = d.get("money")
    queries = []
    for i, q in enumerate(d.get("queries") or []):
        where = f"{name} queries[{i}]"
        metrics = []
        for m, e in (q.get("metrics") or {}).items():
            if m not in METRIC_NAMES:
                raise CrossRegistryError(f"{where}: unknown metric {m!r}")
            metrics.append((m, _fixed_sql(f"{where}.{m}", e)))
        queries.append(Query(view=_fixed_sql(f"{where}.view", q.get("view")),
                             district=_fixed_sql(f"{where}.district", q.get("district")),
                             block=_fixed_sql(f"{where}.block", q.get("block")),
                             metrics=tuple(metrics),
                             block_fallback=q.get("block_fallback"),
                             constituency=q.get("constituency")))
    if not queries or not any(m == "ben" for m, _e in queries[0].metrics):
        raise CrossRegistryError(f"{name}: the first query must hold the count (metric 'ben')")
    v = d.get("village") or {}
    village = Village(count_view=_fixed_sql(f"{name}.village.count_view", v.get("count_view")),
                      base_where=v.get("base_where") or "TRUE",
                      village_where=v.get("village_where") or "village_code IS NOT NULL",
                      set_filter=v.get("set_filter"))
    h = d.get("headline") or {}
    headline = Headline(card=str(h.get("card") or ""), figure=str(h.get("figure") or ""),
                        label=str(h.get("label") or ""), noun=str(h.get("noun") or ""),
                        view=_fixed_sql(f"{name}.headline.view", h.get("view")),
                        expr=_fixed_sql(f"{name}.headline.expr", h.get("expr")))
    if not (headline.card and headline.figure and headline.label and headline.noun):
        raise CrossRegistryError(f"{name}: headline needs card, figure, label and noun")
    if headline.view not in {q.view for q in queries}:
        raise CrossRegistryError(f"{name}: the headline view {headline.view} is not one of its queries' views")
    e = Entry(
        name=name, main=bool(d.get("main")),
        noun=str(count.get("noun") or ""), count_note=str(count.get("note") or ""),
        per=count.get("per"), in_combined=count.get("combined", True) is not False,
        summed_over_years=bool(count.get("summed_over_years")),
        money_verb=(money or {}).get("verb"), money_note=(money or {}).get("note") or "no money recorded",
        money_label=(money or {}).get("label"),
        years=d.get("years", True) is not False, constituency=d.get("constituency"),
        village=village, headline=headline, queries=tuple(queries))
    if not e.noun:
        raise CrossRegistryError(f"{name}: count.noun is required")
    if (money is None) == e.has_money:
        raise CrossRegistryError(f"{name}: `money: null` must go with no 'money' metric, and a money metric with "
                                 "a money entry")
    return e


def load(path: "Path | str" = FILE) -> "tuple[Entry, ...]":
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = tuple(_entry(d) for d in (data.get("schemes") or []))
    names = [e.name for e in entries]
    if len(set(names)) != len(names):
        raise CrossRegistryError(f"a scheme is declared twice: {names}")
    missing = [n for n in scheme_registry.NAMES if n not in names]
    if missing:
        raise CrossRegistryError(f"no cross-scheme entry for {missing} in {path}")
    return entries


ENTRIES: "tuple[Entry, ...]" = load()
BY_NAME: "dict[str, Entry]" = {e.name: e for e in ENTRIES}
ORDER: "tuple[str, ...]" = tuple(e.name for e in ENTRIES)


# ── the tables the cross-scheme code reads, built from the entries ──────────────

def queries() -> "dict[str, list[tuple[str, str, str, list[tuple[str, str]]]]]":
    """cross_figures._QUERIES: {scheme: [(view, district column, block column, [(metric, SQL)])]}."""
    return {e.name: [(q.view, q.district, q.block, list(q.metrics)) for q in e.queries] for e in ENTRIES}


def ben_noun() -> "dict[str, str]":
    return {e.name: e.noun for e in ENTRIES}


def count_note() -> "dict[str, str]":
    return {e.name: e.count_note for e in ENTRIES}


def money_note() -> "dict[str, str]":
    return {e.name: e.money_note for e in ENTRIES}


def money_verb() -> "dict[str, str]":
    """Only the schemes that record money (the others are answered "no money recorded")."""
    return {e.name: e.money_verb for e in ENTRIES if e.money_verb}


def money_label() -> "dict[str, str]":
    return {e.name: e.money_label for e in ENTRIES if e.money_label}


def per() -> "dict[str, str]":
    return {e.name: e.per for e in ENTRIES if e.per}


def no_money() -> frozenset:
    return frozenset(e.name for e in ENTRIES if not e.has_money)


def no_year() -> frozenset:
    return frozenset(e.name for e in ENTRIES if not e.years)


def apart_in_combined() -> frozenset:
    return frozenset(e.name for e in ENTRIES if not e.in_combined)


def main() -> "tuple[str, ...]":
    return tuple(e.name for e in ENTRIES if e.main)


def ac_col() -> "dict[str, str]":
    """The schemes a constituency filter can read, and the column (the others record none)."""
    return {e.name: e.constituency for e in ENTRIES if e.constituency}


def ac_view_col() -> "dict[str, str]":
    """A view whose own constituency column differs from its scheme's (MGNREGA employment)."""
    return {q.view: q.constituency for e in ENTRIES for q in e.queries if q.constituency}


def village_set_filter() -> "dict[str, str]":
    return {e.name: e.village.set_filter for e in ENTRIES if e.village.set_filter}


def block_fallback() -> "dict[str, str]":
    """{scheme: the column a block is looked up by when the scheme's own block names never use it}."""
    return {e.name: q.block_fallback for e in ENTRIES for q in e.queries if q.block_fallback}


def headlines() -> "dict[str, Headline]":
    return {e.name: e.headline for e in ENTRIES}


def headline_for_card(card: str) -> Headline:
    """The headline of the welcome card `card` (routers/stats.py card keys)."""
    for e in ENTRIES:
        if e.headline.card == card:
            return e.headline
    raise KeyError(card)


def headline_query(scheme: str) -> "tuple[str, str, str, list[tuple[str, str]]]":
    """The headline as one query in the _QUERIES shape, on the view its card reads, with that view's own place
    columns: (view, district column, block column, [("headline", SQL), ("ben", SQL)]). The scheme's count (`ben`)
    rides along when it is another figure on the same view (MGNREGA person-days and households given work), so a
    "headline figures" answer also carries the count every other cross-scheme answer compares on."""
    e = BY_NAME[scheme]
    q = next(q for q in e.queries if q.view == e.headline.view)
    metrics = [("headline", e.headline.expr)]
    ben = dict(q.metrics).get("ben")
    if ben is not None and ben != e.headline.expr:
        metrics.append(("ben", ben))
    return (q.view, q.district, q.block, metrics)
