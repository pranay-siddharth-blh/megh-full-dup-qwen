"""
The data team's metric catalogue (semantic.metric_definitions) — D-071.

One table of 62 named measures, each with its SQL expression, the view it is
read from, its unit and the words officers use for it ("spend", "mandays",
"houses built"). This module loads the active ones for the six supported
schemes, finds the ONE measure a question names, and builds a parameter-bound
query for it, so that differently-worded questions with the same meaning read
the same figure (RAG plan A, "same meaning, same answer").

Three things keep it from changing an answer it should not:

- It never guesses. A question that names no measure, two measures, or a
  phrase two measures share gets None, and the model path answers as before.
- The pipeline (app/pipeline/common/c16_metric_catalog.py) only uses it for a
  question that asks nothing else: every word must be the measure, the scheme,
  the place, the year or plain question grammar.
- Only measures proven to give the same figure as the current answers are used
  (data/metric_catalog_verified.yaml, one list per query type). Everything else
  is logged in shadow mode and answered as before.

METRIC_CATALOG_MODE: "off" (not loaded), "shadow" (match and log only) or
"on" (verified measures answer through the catalogue query).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp

from app import db, schema_introspect
from app.config import settings
from app.text_match import tokens

logger = logging.getLogger(__name__)

# subject_area in the catalogue -> the scheme name the pipeline uses. cmss,
# homestay_legacy and nrlm are not schemes this service answers: not loaded.
SUBJECT_TO_SCHEME = {
    "mgnrega": "MGNREGA",
    "pmay": "PMAY-G",
    "focus_plus": "Focus Plus",
    "focus_legacy": "Focus Legacy",
    "cm_elevate": "CM Elevate",
    "cm_elevate_disbursement": "CM Elevate Legacy",
}

# The place and year columns a filter or a grouping may use. A view without one
# of them simply cannot take that filter (the query is then not built).
PLACE_COLUMNS = {"district": "lgd_district", "block": "lgd_block", "village_code": "village_code"}
YEAR_COLUMN = "year_key"

# Words a measure's name may START with that are not the measure itself: the
# scheme names ("MGNREGA Total Expenditure", "Focus+ beneficiaries", "CM Elevate
# Disbursement -- total paid out") and filler. Only "total" is dropped from the
# END ("pg disbursement total" keeps "disbursement"). A phrase left with only
# these words names nothing ("Focus+ total").
_NAME_NOISE = frozenset(
    "mgnrega nrega pmay focus plus cm elevate legacy disbursement disb total the of a an".split())
_NAME_TAIL_NOISE = frozenset({"total"})

VERIFIED_FILE = Path(__file__).resolve().parent.parent / "data" / "metric_catalog_verified.yaml"
QUERY_TYPES = ("total", "breakdown", "ranking", "compare")


@dataclass(frozen=True)
class Metric:
    key: str
    scheme: str
    display_name: str
    expression: str
    base_object: str
    unit: str
    notes: str
    alias: str
    phrases: tuple[tuple[str, ...], ...]
    columns: frozenset[str]           # the base object's columns (live schema)


@dataclass(frozen=True)
class Match:
    """What the matcher found for one question: `metric` when exactly one
    measure is named, else None with `status` saying why ("none", "several",
    "tied"). `spans` are the token indexes the measure words took; `phrases`
    the catalogue phrases that named it."""
    status: str
    metric: Metric | None
    spans: frozenset[int]
    phrases: frozenset[tuple[str, ...]] = frozenset()


# Helper verbs the rephraser adds inside a measure's words ("houses WERE
# sanctioned", "money WAS spent", "people WERE covered"): skipped when matching.
_AUX = frozenset("is are was were be been being has have had".split())


_state: dict = {"metrics": {}, "by_scheme": {}, "verified": {t: {} for t in QUERY_TYPES},
                "single_year": frozenset(), "no_block_level": frozenset(), "loaded": False}


def _stem(word: str) -> str:
    """Plural-blind: "households" and "household" are one word for matching."""
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _phrase(text: str) -> tuple[str, ...]:
    words = [t.low for t in tokens(text)]
    while words and words[0] in _NAME_NOISE:
        words.pop(0)
    while words and words[-1] in _NAME_TAIL_NOISE:
        words.pop()
    return tuple(_stem(w) for w in words) if any(w not in _NAME_NOISE for w in words) else ()


def _alias(key: str, prefix: str, unit: str) -> str:
    """Result-column name in the SQL-prompt convention (_lakh, _cr, _pct,
    _rupees), so the composer and the number checks read its unit."""
    name = key[len(prefix):] if prefix and key.startswith(prefix) and len(key) > len(prefix) else key
    u = (unit or "").lower()
    if u == "lakh rupees":
        return name + "_lakh"
    if u == "rupees":
        return name + "_cr"
    if u == "percent":
        return name + "_pct"
    if u.startswith("rupees per"):
        return name + "_rupees"
    return name


def _value_sql(m: Metric) -> str:
    """The measure as selected: rupees as crore (the SQL prompt's convention for
    PMAY / Focus / CM Elevate money), lakh and percent rounded to 2 places."""
    if m.alias.endswith("_cr"):
        return f"ROUND(({m.expression})::numeric / 10000000, 2)"
    if m.alias.endswith(("_lakh", "_rupees")):
        return f"ROUND(({m.expression})::numeric, 2)"
    return m.expression


def _expression_columns(expression: str) -> "set[str] | None":
    """The columns an aggregate expression reads, or None when it is not one
    plain expression (a subquery, a table, several statements)."""
    try:
        tree = sqlglot.parse_one(f"SELECT {expression} FROM _t", read="postgres")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(tree, exp.Select) or len(tree.expressions) != 1:
        return None
    if any(True for _ in tree.expressions[0].find_all(exp.Select, exp.Subquery, exp.Table)):
        return None
    if not any(True for _ in tree.expressions[0].find_all(exp.AggFunc)):
        return None
    return {c.name.lower() for c in tree.expressions[0].find_all(exp.Column)}


def _common_key_prefix(keys: list[str]) -> str:
    """The shared leading words of a scheme's metric keys ("cm_elevate_disb_")."""
    if len(keys) < 2:
        return ""
    parts = [k.split("_") for k in keys]
    out = []
    for words in zip(*parts):
        if len(set(words)) != 1:
            break
        out.append(words[0])
    return "_".join(out) + "_" if out else ""


def _load_verified() -> "tuple[dict, frozenset[str], frozenset[str]]":
    """({query type: {metric key: evidence}}, the measures read one year at a time,
    the schemes whose blocks are not on lgd_block)."""
    try:
        data = yaml.safe_load(VERIFIED_FILE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        data = {}
    out = {}
    for qtype in QUERY_TYPES:
        entries = data.get(qtype) or {}
        out[qtype] = {str(k): (v or {}) for k, v in entries.items()} if isinstance(entries, dict) else {}
    return (out, frozenset(str(k) for k in (data.get("single_year") or [])),
            frozenset(str(k) for k in (data.get("no_block_level") or [])))


async def load() -> None:
    """Read the active metrics for the supported schemes. Best-effort: a failure
    leaves the catalogue empty and every question takes the model path."""
    if (settings.METRIC_CATALOG_MODE or "off").lower() == "off":
        _state.update(metrics={}, by_scheme={}, loaded=False)
        return
    rows = await db.fetch_rows_readonly(
        "SELECT metric_key, display_name, subject_area, sql_expression, base_object, unit, "
        "synonyms, filters_required FROM semantic.metric_definitions "
        "WHERE is_active AND subject_area = ANY($1::text[]) ORDER BY metric_key",
        [list(SUBJECT_TO_SCHEME)])
    live = schema_introspect.live_columns()
    prefixes = {}
    for area in SUBJECT_TO_SCHEME:
        prefixes[area] = _common_key_prefix([r["metric_key"] for r in rows if r["subject_area"] == area])
    metrics: dict[str, Metric] = {}
    skipped = []
    for r in rows:
        base = str(r["base_object"] or "")
        cols = {c["column"].lower() for c in live.get(base, [])}
        used = _expression_columns(str(r["sql_expression"] or ""))
        if not cols or used is None or not used <= cols:
            skipped.append(r["metric_key"])
            continue
        phrases = {p for p in (_phrase(t) for t in [r["display_name"] or "", *(r["synonyms"] or [])]) if p}
        metrics[r["metric_key"]] = Metric(
            key=r["metric_key"], scheme=SUBJECT_TO_SCHEME[r["subject_area"]],
            display_name=r["display_name"] or r["metric_key"], expression=str(r["sql_expression"]),
            base_object=base, unit=str(r["unit"] or ""), notes=str(r["filters_required"] or ""),
            alias=_alias(r["metric_key"], prefixes[r["subject_area"]], str(r["unit"] or "")),
            phrases=tuple(sorted(phrases)), columns=frozenset(cols))
    by_scheme: dict[str, list[Metric]] = {}
    for m in metrics.values():
        by_scheme.setdefault(m.scheme, []).append(m)
    verified_types, single, no_block = _load_verified()
    _state.update(metrics=metrics, by_scheme=by_scheme, verified=verified_types, single_year=single,
                  no_block_level=no_block, loaded=True)
    logger.info("metric catalogue (%s): %d metrics for %d schemes; %d not usable here (%s); verified: %s",
                settings.METRIC_CATALOG_MODE, len(metrics), len(by_scheme), len(skipped),
                ", ".join(skipped) or "-",
                ", ".join(f"{t}={len(v)}" for t, v in _state["verified"].items()))


def mode() -> str:
    m = (settings.METRIC_CATALOG_MODE or "off").lower()
    return m if m in ("off", "shadow", "on") and _state["loaded"] else "off"


def metrics() -> dict[str, Metric]:
    return _state["metrics"]


def verified(qtype: str, key: str, phrases: "frozenset[tuple[str, ...]]" = frozenset()) -> "dict | None":
    """The verification entry for `key` under query type `qtype`, else None —
    also None when the question named the measure only by a wording the entry
    excludes (`except_words`: a word the current answers read another way)."""
    entry = _state["verified"].get(qtype, {}).get(key)
    if entry is None:
        return None
    excluded = {_phrase(str(w)) for w in (entry.get("except_words") or [])}
    if phrases and phrases <= excluded:
        return None
    return entry


def single_year(key: str) -> bool:
    """The measure is a per-year tally: adding years overstates it (the
    catalogue's own note, e.g. job cards "MUST filter to a single year_key")."""
    return key in _state["single_year"]


def match(question: str, scheme: str) -> Match:
    """The one measure of `scheme` the question names. Every phrase is found;
    the longest phrases win and take their words; what is left must point at
    exactly one measure."""
    all_toks = [_stem(t.low) for t in tokens(question)]
    keep = [k for k, w in enumerate(all_toks) if w not in _AUX]   # positions in the full token list
    toks = [all_toks[k] for k in keep]
    found: list[tuple[int, int, Metric, tuple]] = []   # (start, length, metric, phrase), over `toks`
    for m in _state["by_scheme"].get(scheme, []):
        for p in m.phrases:
            n = len(p)
            for i in range(len(toks) - n + 1):
                if tuple(toks[i:i + n]) == p:
                    found.append((i, n, m, p))
    if not found:
        return Match("none", None, frozenset())
    taken: set[int] = set()
    chosen: list[tuple[int, int, set[str]]] = []
    used: set[tuple] = set()
    for i, n, _m, _p in sorted(found, key=lambda f: (-f[1], f[0])):
        if set(range(i, i + n)) & taken:
            continue
        keys = {m.key for j, k, m, _ in found if j == i and k == n}
        used |= {ph for j, k, _, ph in found if j == i and k == n}
        chosen.append((i, n, keys))
        taken |= set(range(i, i + n))
    # the measure's words in the question, with any helper verb inside them
    spans = frozenset(k for i, n, _ in chosen for k in range(keep[i], keep[i + n - 1] + 1))
    keys = set().union(*(c[2] for c in chosen))
    if any(len(c[2]) > 1 for c in chosen):
        return Match("tied", None, spans)
    if len(keys) != 1:
        return Match("several", None, spans)
    return Match("one", _state["metrics"][keys.pop()], spans, frozenset(used))


def build(m: Metric, filters: dict, group: "str | None" = None, *,
          order: "str | None" = None, limit: "int | None" = None, qtype: str = "total"
          ) -> "tuple[str, list, str] | None":
    """(parameterised SQL, params, display SQL) for metric `m`.

    filters: {"district" | "block" | "village_code": value or list,
              "year_key": [years]} — a list becomes "= ANY".
    group:   None (one total), "district", "block" or "year".
    order:   "desc" / "asc" with `limit` for a top / bottom list.
    None when the base object lacks a column the filters or grouping need, or
    for a block filter / grouping on a scheme whose blocks are not on lgd_block
    (Focus Plus maps its blocks on block_name_raw: lgd_block is NULL on 15% of
    its rows, tests/test_focusplus_block_columns.py)."""
    if m.scheme in _state.get("no_block_level", ()) and (filters.get("block") or group == "block"):
        return None
    where, params, shown = [], [], []
    for key, col in (*PLACE_COLUMNS.items(), ("year_key", YEAR_COLUMN)):
        v = filters.get(key)
        if v in (None, "", [], ()):
            continue
        if col not in m.columns:
            return None
        values = list(v) if isinstance(v, (list, tuple, set)) else [v]
        if col == "village_code" or col == YEAR_COLUMN:
            try:
                values = [int(x) for x in values]
            except (TypeError, ValueError):
                return None
            params.append(values if len(values) > 1 else values[0])
            if len(values) > 1:
                where.append(f"{col} = ANY(${len(params)}::int[])")
                shown.append(f"{col} IN ({', '.join(map(str, values))})")
            else:
                where.append(f"{col} = ${len(params)}")
                shown.append(f"{col} = {values[0]}")
            continue
        values = [str(x) for x in values]
        quoted = ", ".join("'" + x.upper().replace("'", "''") + "'" for x in values)
        if len(values) > 1:
            params.append([x.upper() for x in values])
            where.append(f"UPPER({col}) = ANY(${len(params)}::text[])")
            shown.append(f"UPPER({col}) IN ({quoted})")
        else:
            params.append(values[0])
            where.append(f"UPPER({col}) = UPPER(${len(params)})")
            shown.append(f"UPPER({col}) = {quoted}")
    value = f"{_value_sql(m)} AS {m.alias}"
    if group is None:
        select, tail = value, ""
    elif group == "year":
        if YEAR_COLUMN not in m.columns:
            return None
        fy = "MAX(financial_year_short) AS financial_year, " if "financial_year_short" in m.columns else ""
        select, tail = f"{YEAR_COLUMN}, {fy}{value}", f"\nGROUP BY {YEAR_COLUMN}"
        if order is None:
            tail += f" ORDER BY {YEAR_COLUMN}"
    else:
        col = PLACE_COLUMNS.get(group)
        if col is None or col not in m.columns:
            return None
        # rows with no place are left out, as the model path's breakdowns do
        where, shown = where + [f"{col} IS NOT NULL"], shown + [f"{col} IS NOT NULL"]
        select, tail = f"{col} AS {group}, {value}", f"\nGROUP BY {col}"
        if order is None:
            tail += f" ORDER BY {col}"
    if order in ("desc", "asc"):
        tail += f" ORDER BY {m.alias} {order.upper()} NULLS LAST"
        if limit:
            tail += f" LIMIT {int(limit)}"

    def text(w: list[str]) -> str:
        wh = ("\nWHERE " + " AND ".join(w)) if w else ""
        return f"/* metric:{m.key} {qtype} */ SELECT {select}\nFROM {m.base_object}{wh}{tail}"

    return text(where), params, text(shown)


def is_catalog_sql(sql: "str | None") -> bool:
    """A query this module built (its opening /* metric:<key> … */ comment)."""
    return (sql or "").lstrip().startswith("/* metric:")
