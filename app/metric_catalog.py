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

import json
import logging
import threading
import time
import dataclasses
from dataclasses import dataclass
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp

from app import db, scheme_registry, schema_introspect
from app.config import settings
from app.text_match import tokens

logger = logging.getLogger(__name__)

# subject_area in the catalogue -> the scheme name the pipeline uses. cmss,
# homestay_legacy and nrlm are not schemes this service answers: not loaded.
SUBJECT_TO_SCHEME = scheme_registry.SUBJECT_TO_SCHEME   # E5, D-079

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
# B1 (RAG plan, user decision 2026-10-27): officers' wordings a person approved from
# the meaning-shadow log (tests/metric_meaning/review.py), {metric_key: [wording]}.
# Read as exact catalogue phrases, the same as the data team's synonyms, until the
# team adds them to semantic.metric_definitions.
SYNONYMS_FILE = Path(__file__).resolve().parent.parent / "data" / "metric_catalog_synonyms.yaml"
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
    # status "several": the measures named, in the order the question names them, when each named span points at
    # exactly one measure (2026-11-14: a question asking two figures, read by combine_totals)
    several: tuple = ()


# Helper verbs the rephraser adds inside a measure's words ("houses WERE
# sanctioned", "money WAS spent", "people WERE covered"): skipped when matching.
_AUX = frozenset("is are was were be been being has have had".split())


_state: dict = {"metrics": {}, "by_scheme": {}, "verified": {t: {} for t in QUERY_TYPES},
                "single_year": frozenset(), "no_block_level": frozenset(), "loaded": False}


def _stem(word: str) -> str:
    """Plural-blind: "households" and "household" are one word for matching; "beneficiaries" and "beneficiary" too
    (2026-11-15: the "-ies" plural was cut to "beneficiarie", so "per beneficiary" never named the measure)."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _phrase(text: str, noise: frozenset = _NAME_NOISE) -> tuple[str, ...]:
    words = [t.low for t in tokens(text)]
    while words and words[0] in noise:
        words.pop(0)
    while words and words[-1] in _NAME_TAIL_NOISE:
        words.pop()
    return tuple(_stem(w) for w in words) if any(w not in noise for w in words) else ()


# An APPROVED wording (SYNONYMS_FILE) is an exact phrase a person checked: only articles and "total" come off it.
# Read with _NAME_NOISE it lost its own words: "total disbursement" (CM Elevate Legacy) became an empty phrase,
# because "disbursement" is noise in the data team's display names ("CM Elevate Disbursement -- total paid out"),
# so "CM Elevate Legacy total disbursement" named no measure (no-model gold bank PF-CL-terse, 2026-11-14).
_APPROVED_NOISE = frozenset("total the of a an".split())


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
    approved = _load_approved_synonyms()
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
        phrases |= {p for p in (_phrase(t, _APPROVED_NOISE) for t in approved.get(r["metric_key"], [])) if p}
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
    # 2026-11-15: the block names each no_block_level view's source column holds (a block filter there is read on
    # that column only for a block it names; source_block_column)
    source_blocks: dict[str, frozenset] = {}
    for m in metrics.values():
        if m.scheme in no_block and m.base_object not in source_blocks:
            col = source_block_column(m)
            if col is not None:
                got = await db.fetch_rows_readonly(
                    f"SELECT DISTINCT {col} AS b FROM {m.base_object} WHERE {col} IS NOT NULL", [])
                source_blocks[m.base_object] = frozenset(str(r["b"]).upper() for r in got)
    _state.update(metrics=metrics, by_scheme=by_scheme, verified=verified_types, single_year=single,
                  no_block_level=no_block, source_blocks=source_blocks, loaded=True)
    logger.info("metric catalogue (%s): %d metrics for %d schemes; %d not usable here (%s); verified: %s",
                settings.METRIC_CATALOG_MODE, len(metrics), len(by_scheme), len(skipped),
                ", ".join(skipped) or "-",
                ", ".join(f"{t}={len(v)}" for t, v in _state["verified"].items()))


def _load_approved_synonyms() -> "dict[str, list[str]]":
    """{metric_key: [wording]} from SYNONYMS_FILE; {} when absent or unreadable."""
    try:
        data = yaml.safe_load(SYNONYMS_FILE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001 — a bad file must not stop the catalogue
        logger.warning("metric catalogue: %s unreadable (%s) — no approved synonyms", SYNONYMS_FILE.name, e)
        return {}
    return {str(k): [str(w) for w in (v or []) if str(w).strip()] for k, v in data.items()
            if isinstance(v, list)}


# ── B1 meaning shadow (user decision 2026-10-27) ─────────────────────────────
# Measured live (tests/metric_meaning/run_eval.py): embeddings rank "administrative
# expenditure" next to total expenditure (0.873, margin 0.119) and "wage rate" next to
# the wage share (0.902) — as high as true paraphrases — so a meaning match NEVER
# answers. It only records the officer's unmatched wording and its nearest measure,
# for a person to approve as an exact synonym (SYNONYMS_FILE).
_meaning_vectors: dict = {}
_meaning_lock = threading.Lock()


async def _phrase_vectors(scheme: str) -> "list[tuple[str, str, list[float]]]":
    """(metric_key, phrase, vector) for the scheme's catalogue phrases, cached."""
    if scheme not in _meaning_vectors:
        from app import llm
        items = [(m.key, " ".join(p)) for m in _state["by_scheme"].get(scheme, []) for p in m.phrases]
        vecs = await llm.call_embedding([p for _k, p in items]) if items else []
        _meaning_vectors[scheme] = [(k, p, v) for (k, p), v in zip(items, vecs)]
    return _meaning_vectors[scheme]


def _cosine(a: "list[float]", b: "list[float]") -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return num / den if den else 0.0


async def meaning_shadow(wording: str, scheme: str) -> "dict | None":
    """Log the nearest catalogue measure for an unmatched wording (never used to
    answer). Best-effort: any failure is a debug line, nothing else."""
    if not settings.METRIC_MEANING_SHADOW or not wording.strip() or not _state["loaded"]:
        return None
    try:
        from app import llm
        rows = await _phrase_vectors(scheme)
        if not rows:
            return None
        q = (await llm.call_embedding([wording]))[0]
        best: dict[str, tuple[float, str]] = {}
        for key, phrase, vec in rows:
            c = _cosine(q, vec)
            if c > best.get(key, (-1.0, ""))[0]:
                best[key] = (c, phrase)
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
        (k1, (c1, p1)) = ranked[0]
        c2 = ranked[1][1][0] if len(ranked) > 1 else 0.0
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "scheme": scheme, "wording": wording,
                  "nearest": k1, "nearest_phrase": p1, "score": round(c1, 3), "margin": round(c1 - c2, 3)}
        path = Path(settings.METRIC_MEANING_FILE)
        path = path if path.is_absolute() else Path(__file__).resolve().parent.parent / path
        from app.pii_mask import mask_record      # the officer's wording: personal data masked (PII_LOG_MODE)
        with _meaning_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(mask_record(record), ensure_ascii=False) + "\n")
        return record
    except Exception:  # noqa: BLE001 — shadow only: never affects a turn
        logger.debug("metric catalogue: meaning shadow failed", exc_info=True)
        return None


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
    # read like an approved wording (2026-11-15): with the display-name noise "disbursement" became an empty phrase
    # and excluded nothing (Focus Plus payments ranking, gold bank SH-F023)
    excluded = {_phrase(str(w), _APPROVED_NOISE) for w in (entry.get("except_words") or [])}
    if phrases and phrases <= excluded:
        return None
    return entry


def single_year(key: str) -> bool:
    """The measure is a per-year tally: adding years overstates it (the
    catalogue's own note, e.g. job cards "MUST filter to a single year_key")."""
    return key in _state["single_year"]


_RATE_WORDS = frozenset(_w for _w in ("rate", "percent", "percentage", "pct", "share", "ratio", "proportion"))


def _is_rate_metric(m: "Metric") -> bool:
    return str(m.unit or "").lower() in ("percent", "percentage", "pct", "%", "ratio") \
        or m.key.endswith(("_rate", "_pct", "_share", "_ratio"))


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
        # 2026-11-14: a phrase two measures share ("houses completed": the count AND the completion rate) is the
        # COUNT unless the question says rate / percent / share; it was "tied" and went to model-written SQL.
        wants_rate = any(w in _RATE_WORDS for w in all_toks)
        narrowed = []
        for i, n, ks in chosen:
            if len(ks) > 1:
                pick = {k for k in ks if _is_rate_metric(_state["metrics"][k]) == wants_rate}
                ks = pick if len(pick) == 1 else ks
            narrowed.append((i, n, ks))
        chosen = narrowed
        keys = set().union(*(c[2] for c in chosen))
    if any(len(c[2]) > 1 for c in chosen):
        return Match("tied", None, spans)
    if len(keys) != 1:
        ordered = list(dict.fromkeys(next(iter(ks)) for _i, _n, ks in sorted(chosen, key=lambda c: c[0])))
        return Match("several", None, spans, frozenset(used),
                     several=tuple(_state["metrics"][k] for k in ordered))
    return Match("one", _state["metrics"][keys.pop()], spans, frozenset(used))


# The words that set two measures side by side, between a measure and a word that shares its noun.
_ELISION_JOINS = frozenset("and vs versus or against plus".split())


def expand_elision(question: str, scheme: str) -> "str | None":
    """The question with a SHARED word written out (2026-11-15): "houses sanctioned vs completed" -> "houses
    sanctioned vs houses completed", "loan and subsidy disbursed" style questions the other way round. A catalogue
    phrase of two or more words, a join word right next to it, and on the other side ONE word no phrase took: when
    that word put in place of the phrase's first / last word makes another catalogue phrase of this scheme, the
    shared words are written out. None when nothing was written out. The caller keeps the result only when it then
    names two or three measures (match status "several")."""
    toks = list(tokens(question or ""))
    low = [_stem(t.low) for t in toks]
    phrases = {p for m in _state["by_scheme"].get(scheme, []) for p in m.phrases}
    found = [(i, len(p), p) for p in phrases if len(p) >= 2
             for i in range(len(low) - len(p) + 1) if tuple(low[i:i + len(p)]) == p]
    covered = {k for i, n, _p in found for k in range(i, i + n)}
    inserts: dict[int, str] = {}                  # character offset -> text to insert there
    for i, n, p in found:
        j = i + n                                 # "<phrase> vs <word>": the word takes the phrase's last place
        if j + 1 < len(low) and low[j] in _ELISION_JOINS and j + 1 not in covered \
                and p[:-1] + (low[j + 1],) in phrases:
            inserts[toks[j + 1].start] = " ".join(t.raw for t in toks[i:i + n - 1]) + " "
        j = i - 1                                 # "<word> and <phrase>": the word takes the phrase's first place
        if j - 1 >= 0 and low[j] in _ELISION_JOINS and j - 1 not in covered \
                and (low[j - 1],) + p[1:] in phrases:
            inserts[toks[j - 1].end] = " " + " ".join(t.raw for t in toks[i + 1:i + n])
    if not inserts:
        return None
    out = question
    for at in sorted(inserts, reverse=True):
        out = out[:at] + inserts[at] + out[at:]
    return out


def build(m: Metric, filters: dict, group: "str | None" = None, *,
          order: "str | None" = None, limit: "int | None" = None, qtype: str = "total",
          split: "str | None" = None) -> "tuple[str, list, str] | None":
    """(parameterised SQL, params, display SQL) for metric `m`; see _build."""
    return _build([m], filters, group, order=order, limit=limit, qtype=qtype, split=split)


def build_several(ms: "list[Metric]", filters: dict, group: str, *, qtype: str = "breakdown"
                  ) -> "tuple[str, list, str] | None":
    """(sql, params, shown) reading two or three measures BY one grouping in ONE query: one value column per measure
    ("houses sanctioned and completed by district", 2026-11-15). Only measures of the same base view, with distinct
    result-column names: the rows then share one WHERE and one GROUP BY, so each column is exactly the figure the
    measure's own breakdown gives. Measures on different views (MGNREGA expenditure on v_expenditure, person-days on
    v_employment) are None: their groupings would have to be joined, which this query does not do."""
    if not 2 <= len(ms) <= 3 or group is None:
        return None
    if len({m.base_object for m in ms}) != 1 or len({m.scheme for m in ms}) != 1 \
            or len({m.alias for m in ms}) != len(ms):
        return None
    return _build(list(ms), filters, group, qtype=qtype)


def _build(ms: "list[Metric]", filters: dict, group: "str | None" = None, *,
           order: "str | None" = None, limit: "int | None" = None, qtype: str = "total",
           split: "str | None" = None) -> "tuple[str, list, str] | None":
    """(parameterised SQL, params, display SQL) for the measures `ms`: one, or several of one view (build_several).

    filters: {"district" | "block" | "village_code": value or list,
              "year_key": [years]} — a list becomes "= ANY".
    group:   None (one total), "district", "block" or "year".
    order:   "desc" / "asc" with `limit` for a top / bottom list.
    split:   "district" / "block" with group "year" and a LIST of those places: each place by year (a place x year
             table, the places in the order listed). A block grouping inside a list of districts carries each block's
             district the same way (2026-11-15, the drill-down behind a ranking: c18 _c18_drill).
    None when the base object lacks a column the filters or grouping need, or
    for a block filter / grouping on a scheme whose blocks are not on lgd_block
    (Focus Plus maps its blocks on block_name_raw: lgd_block is NULL on 15% of
    its rows, tests/test_focusplus_block_columns.py)."""
    m = ms[0]                  # view, scheme, place and year columns: the same for every measure (build_several)
    src_block = None
    if m.scheme in _state.get("no_block_level", ()) and (filters.get("block") or group == "block"
                                                         or split == "block"):
        # 2026-11-15: a block FILTER reads the column the scheme's blocks are kept on (Focus Plus:
        # UPPER(block_name_raw), the column the model path's resolved-entity line pins). A GROUPING by block reads it
        # too (2026-11-15, the drill-down behind a ranking): the model path's block breakdowns are grouped on it
        # (c11 _focusplus_block_breakdown_on_raw, KI-718), so both paths give the same rows; lgd_block is NULL on 15%
        # of Focus Plus rows
        src_block = source_block_column(m)
        if src_block is None:
            return None
    if split is not None and (group != "year" or split not in ("district", "block")
                              or not isinstance(filters.get(split), (list, tuple)) or len(filters[split]) < 2):
        return None
    where, params, shown = [], [], []
    for key, col in (*PLACE_COLUMNS.items(), ("year_key", YEAR_COLUMN)):
        v = filters.get(key)
        if v in (None, "", [], ()):
            continue
        if key == "block" and src_block is not None:
            values = [str(x).upper() for x in (v if isinstance(v, (list, tuple, set)) else [v])]
            known = (_state.get("source_blocks") or {}).get(m.base_object) or frozenset()
            if any(x not in known for x in values):
                return None    # a block the source never names (Focus Plus: Siju, Batabari … are on lgd_block only)
            quoted = ", ".join("'" + x.replace("'", "''") + "'" for x in values)
            params.append(values if len(values) > 1 else values[0])
            if len(values) > 1:
                where.append(f"{src_block} = ANY(${len(params)}::text[])")
                shown.append(f"{src_block} IN ({quoted})")
            else:
                where.append(f"{src_block} = UPPER(${len(params)})")
                shown.append(f"{src_block} = {quoted}")
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
    ac = filters.get("assembly_constituency")
    if ac not in (None, "", [], ()):
        col = constituency_column(m)
        if col is None:
            return None
        values = [str(x).upper() for x in (ac if isinstance(ac, (list, tuple, set)) else [ac])]
        quoted = ", ".join("'" + x.replace("'", "''") + "'" for x in values)
        if len(values) > 1:
            params.append(values)
            where.append(f"{col} = ANY(${len(params)}::text[])")
            shown.append(f"{col} IN ({quoted})")
        else:
            params.append(values[0])
            where.append(f"{col} = UPPER(${len(params)})")
            shown.append(f"{col} = {quoted}")
    tail_shown = None          # the display SQL's tail, when it differs from the bound one (a listed order)
    value = ", ".join(f"{_value_sql(x)} AS {x.alias}" for x in ms)
    # 2026-11-15: a list is ranked on the measure's own value, not on its rounded column: two CM Elevate Legacy schemes
    # both read ₹6.77 crore (67,724,601.10 and 67,670,375.90) and the third place went to the smaller one (gold bank
    # W2-RK-04). A column selected as computed (a count) is still ordered by its name.
    rank_key = m.alias if _value_sql(m) == m.expression else f"({m.expression})"
    if group is None:
        select, tail = value, ""
    elif group == "year" and split is not None:
        # each listed place by financial year, the places in the order listed (the answer the follow-up drills into)
        if YEAR_COLUMN not in m.columns:
            return None
        pcol = src_block if (split == "block" and src_block) else PLACE_COLUMNS[split]
        if pcol == PLACE_COLUMNS[split] and pcol not in m.columns:
            return None
        fy = "MAX(financial_year_short) AS financial_year, " if "financial_year_short" in m.columns else ""
        where, shown = where + [f"{YEAR_COLUMN} IS NOT NULL"], shown + [f"{YEAR_COLUMN} IS NOT NULL"]
        pos, pos_shown = _list_position(pcol, filters[split], params, split == "block" and bool(src_block))
        select = f"{pcol} AS {split}, {YEAR_COLUMN}, {fy}{value}"
        tail = f"\nGROUP BY {pcol}, {YEAR_COLUMN} ORDER BY {pos}, {YEAR_COLUMN}"
        tail_shown = f"\nGROUP BY {pcol}, {YEAR_COLUMN} ORDER BY {pos_shown}, {YEAR_COLUMN}"
    elif group == "year":
        if YEAR_COLUMN not in m.columns:
            return None
        fy = "MAX(financial_year_short) AS financial_year, " if "financial_year_short" in m.columns else ""
        # 2026-11-14: rows with no year are left out of a per-year list, as rows with no place are left out of a
        # per-place list below. PMAY-G's 126 undated registrations came back as a last "year" and the trend read
        # "fell from 15,513 in FY 2017-18 to 126 in (row), down 99.2%"; the chart could not be a line either.
        where, shown = where + [f"{YEAR_COLUMN} IS NOT NULL"], shown + [f"{YEAR_COLUMN} IS NOT NULL"]
        select, tail = f"{YEAR_COLUMN}, {fy}{value}", f"\nGROUP BY {YEAR_COLUMN}"
        if order is None:
            tail += f" ORDER BY {YEAR_COLUMN}"
    elif group == "scheme":
        # 2026-11-14: the dataset's own sub-schemes ("CM Elevate Legacy amount disbursed by scheme"), read from the
        # column the registry names (scheme_registry sub_scheme_column); a dataset with none has no such grouping.
        # Largest first: the order a "by scheme" list is read in.
        from app import scheme_registry
        facts = scheme_registry.DATASETS.get(m.scheme)
        col = facts.sub_scheme_column if facts is not None else None
        if not col or col not in m.columns:
            return None
        where, shown = where + [f"{col} IS NOT NULL"], shown + [f"{col} IS NOT NULL"]
        select, tail = f"{col} AS scheme, {value}", f"\nGROUP BY {col}"
        if order is None:
            tail += f" ORDER BY {rank_key} DESC NULLS LAST"
    else:
        col = PLACE_COLUMNS.get(group)
        if group == "block" and src_block:
            col = src_block
        elif col is None or col not in m.columns:
            return None
        # rows with no place are left out, as the model path's breakdowns do
        where, shown = where + [f"{col} IS NOT NULL"], shown + [f"{col} IS NOT NULL"]
        dists = filters.get("district")
        if group == "block" and order is None and isinstance(dists, (list, tuple)) and len(dists) > 1 \
                and PLACE_COLUMNS["district"] in m.columns:
            # 2026-11-15: the blocks of several districts (the drill-down behind a district ranking / comparison):
            # each block with its district, the districts in the order listed, each district's blocks largest first
            dcol = PLACE_COLUMNS["district"]
            pos, pos_shown = _list_position(dcol, dists, params, False)
            select = f"{dcol} AS district, {col} AS block, {value}"
            tail = f"\nGROUP BY {dcol}, {col} ORDER BY {pos}, {rank_key} DESC NULLS LAST"
            tail_shown = f"\nGROUP BY {dcol}, {col} ORDER BY {pos_shown}, {rank_key} DESC NULLS LAST"
        else:
            select, tail = f"{col} AS {group}, {value}", f"\nGROUP BY {col}"
            if order is None:
                tail += f" ORDER BY {col}"
    if order in ("desc", "asc"):
        tail += f" ORDER BY {rank_key} {order.upper()} NULLS LAST"
        if limit:
            tail += f" LIMIT {int(limit)}"

    def text(w: list[str], t: str) -> str:
        wh = ("\nWHERE " + " AND ".join(w)) if w else ""
        key = "+".join(x.key for x in ms)
        return f"/* metric:{key} {qtype} */ SELECT {select}\nFROM {m.base_object}{wh}{t}"

    return text(where, tail), params, text(shown, tail_shown if tail_shown is not None else tail)


def _list_position(col: str, values, params: list, upper_done: bool) -> "tuple[str, str]":
    """(SQL, display SQL) of each row's place in the listed order: array_position over the list parameter the WHERE
    already bound for this column (the same values, upper case), so the rows come in the order the places were
    named / ranked. `upper_done`: the column expression is already upper case (Focus Plus UPPER(block_name_raw))."""
    want = [str(x).upper() for x in values]
    k = next((i for i, p in enumerate(params, 1) if isinstance(p, list) and [str(x).upper() for x in p] == want), None)
    expr = col if upper_done else f"UPPER({col})"
    quoted = ", ".join("'" + x.replace("'", "''") + "'" for x in want)
    shown = f"array_position(ARRAY[{quoted}]::text[], {expr})"
    if k is None:
        params.append(want)
        k = len(params)
    return f"array_position(${k}::text[], {expr})", shown


def combine_totals(parts: "list[tuple[Metric, tuple[str, list, str]]]") -> "tuple[str, list, str]":
    """One query reading several one-row totals side by side: SELECT (q1) AS a, (q2) AS b. Each part is the
    (sql, params, shown) build() wrote for a total; its $n placeholders are renumbered after the parts before it,
    its own opening comment is dropped and one comment names every measure (`/* metric:a+b total */`)."""
    def body(text: str) -> str:
        text = text.lstrip()
        if text.startswith("/*"):
            text = text[text.index("*/") + 2:].lstrip()
        return text

    selects, shown_selects, params = [], [], []
    for m, (sql, ps, shown) in parts:
        off = len(params)
        s = body(sql)
        for k in range(len(ps), 0, -1):          # highest first: "$12" is renumbered before "$1"
            s = s.replace(f"${k}", f"${k + off}")
        params += list(ps)
        selects.append(f"({s}) AS {m.alias}")
        shown_selects.append(f"({body(shown)}) AS {m.alias}")
    head = "/* metric:" + "+".join(m.key for m, _ in parts) + " total */ SELECT "
    return head + ",\n       ".join(selects), params, head + ",\n       ".join(shown_selects)


def source_block_column(m: Metric) -> "str | None":
    """The expression a block filter reads for a scheme whose blocks are not on lgd_block (no_block_level), from the
    cross-scheme registry (data/cross_scheme.yaml: Focus Plus = UPPER(block_name_raw)); None when the registry names
    none for the view, names lgd_block, or the view lacks the column."""
    from app import cross_registry
    col = cross_registry.view_block_col().get(m.base_object)
    if not col:
        return None
    bare = (col.split("(", 1)[1].split(")", 1)[0] if "(" in col else col).strip().lower()
    if bare == PLACE_COLUMNS["block"] or bare not in m.columns:
        return None
    return col


def constituency_column(m: Metric) -> "str | None":
    """The expression a constituency filter reads for this measure's view, from the cross-scheme registry
    (data/cross_scheme.yaml: the view's own column first, else the scheme's), or None when the scheme records none or
    the view lacks the column. MGNREGA employment reads assembly_constituency_name, the others ac_name (truth SQL of
    the gold bank, 2026-11-14)."""
    from app import cross_registry
    col = cross_registry.ac_view_col().get(m.base_object) or cross_registry.ac_col().get(m.scheme)
    if not col:
        return None
    bare = col.split("(", 1)[1].split(")", 1)[0] if "(" in col else col
    return col if bare.strip().lower() in m.columns else None


def money_scale(m: Metric) -> "float | None":
    """Rupees per unit of the measure's RAW expression (`m.expression`), or None when it is not money. A crore
    alias ("_cr") is a rupee expression divided only when selected (_value_sql); a lakh alias is already lakh."""
    # a RATE is never a money total (review 2026-11-15): "cost_per_person_day_rupees" (unit "rupees per person-day")
    # divided by a count gave about ₹0
    if "_per_" in m.alias or " per " in f" {str(m.unit).lower()} ":
        return None
    if m.alias.endswith("_lakh"):
        return 1e5
    if m.alias.endswith(("_cr", "_rupees")) or str(m.unit).lower() in ("rupees", "rupee"):
        return 1.0
    return None


def ratio_query(num: Metric, den: Metric, filters: dict, alias: str) -> "tuple[str, list, str] | None":
    """(sql, params, shown) for num / den: the money measure's rupees per one of the counted things, each a total
    over the same filters, in one statement of two scalar subqueries; None if either cannot be built."""
    scale = money_scale(num)
    if scale is None:
        # 2026-11-15: a count per a count (person-days per household): no unit to convert; a rate or money below the
        # line is never divided into a count
        if money_scale(den) is not None or _is_rate_metric(num) or _is_rate_metric(den):
            return None
        scale = 1.0
    raw_num = dataclasses.replace(num, alias="num_raw")        # the raw expression, not crore-rounded
    raw_den = dataclasses.replace(den, alias="den_raw")
    qn, qd = build(raw_num, filters, None, qtype="total"), build(raw_den, filters, None, qtype="total")
    if qn is None or qd is None:
        return None
    sql, params, shown = combine_totals([(raw_num, qn), (raw_den, qd)])
    head = f"/* metric:{num.key}/{den.key} ratio */ "

    def ratio(text: str) -> str:
        body = text[text.index("SELECT ") + len("SELECT "):]
        first, _, second = body.partition(",\n       ")
        a = first[:first.rindex(") AS num_raw")] + ")"
        b = second[:second.rindex(") AS den_raw")] + ")"
        return (head + f"SELECT ROUND(({a})::numeric * {scale:g} / NULLIF(({b}), 0), 2) AS {alias}")
    return ratio(sql), params, ratio(shown)


def is_catalog_sql(sql: "str | None") -> bool:
    """A query this module built (its opening /* metric:<key> … */ comment)."""
    return (sql or "").lstrip().startswith("/* metric:")
