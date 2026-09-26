"""
app/response/findings.py — deterministic, no-model structured findings over an
already-executed query result (node 5.13): empty result, numeric extremes,
ties at an extreme, an oversized result set, an SME-authored threshold
breach (pilot scheme only — see `_THRESHOLDS_FILE`), and a stale-data note
already carried on `curated.dim_year` but never surfaced today.

Also owns `compute_result_stats`, the structured (typed, not pre-formatted)
replacement for pipeline.py's old `_result_digest` per-column computation —
pipeline.py's `_result_digest` now calls it too, so both the composer-prompt
text and this module's own detectors read the exact same numbers, computed
once per call site, never duplicated as logic. Import direction is
one-way (pipeline.py -> findings.py) to avoid a cycle, so the numeric-coercion
helpers below are local copies rather than imports from pipeline.py — the
same "no import edge back into pipeline.py" stance app/nlu/premise_check.py
already documents for its own local `_to_number`.

Each finding is a plain, JSON-serializable dict: `{type, severity, message,
column, row_ref}`. `evaluate()` never raises — a detector's own failure is
logged and skipped, never allowed to break the data route.

Known gap, not invented around: the threshold-breach detector's loader is
fully implemented and tested, but no real `*_findings_thresholds.yaml` has
been authored yet for CM Elevate (the pilot scheme per proposal.md's
Explicitly Out of Scope) — that requires SME-reviewed values this session
has no access to. Until that file exists on disk, every scheme (CM Elevate
included) correctly produces zero threshold-breach findings, exactly like
test scenario (f)'s "un-piloted scheme" case.
"""
from __future__ import annotations

import logging
import numbers
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)

# app/response/findings.py -> repo root -> data/
_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"

_THRESHOLDS_FILE = {
    "MGNREGA": _DATA_ROOT / "mgnrega" / "mgnrega_findings_thresholds.yaml",
    "PMAY-G": _DATA_ROOT / "pmay" / "pmay_findings_thresholds.yaml",
    "Focus Plus": _DATA_ROOT / "focus_plus" / "focusplus_findings_thresholds.yaml",
    "CM Elevate": _DATA_ROOT / "cm_elevate" / "cmelevate_findings_thresholds.yaml",
}

_thresholds_cache: dict[str, list[dict]] = {}
_thresholds_loaded: set[str] = set()


def _load_scheme_thresholds(scheme: str) -> list[dict]:
    """Read `scheme`'s `*_findings_thresholds.yaml` once, caching the result.
    A missing file (the common case — only a pilot scheme has one authored
    so far) or a malformed one degrades to "no thresholds for this scheme",
    never raises."""
    if scheme in _thresholds_loaded:
        return _thresholds_cache.get(scheme, [])
    _thresholds_loaded.add(scheme)
    path = _THRESHOLDS_FILE.get(scheme)
    rules: list[dict] = []
    if path is not None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            rules = list((data or {}).get("findings_thresholds", []) or [])
        except FileNotFoundError:
            logger.info("findings: no thresholds file for %s at %s (not piloted yet)", scheme, path)
        except Exception:  # noqa: BLE001 — malformed YAML, wrong shape, etc.
            logger.warning("findings: failed to load thresholds file for %s at %s",
                            scheme, path, exc_info=True)
    _thresholds_cache[scheme] = rules
    return rules


# ── numeric coercion — local copy, see module docstring ────────────────────
_NONSTAT_COL = re.compile(
    r"(^|_)(year|yr|fy|pincode|rank|serial)($|_)|_key$|_code$|_id$|(^|_)id$",
    re.IGNORECASE,
)


def _to_number(v: object) -> "int | float | None":
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, numbers.Number):
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
            return int(s) if "." not in s else float(s)
    return None


@dataclass
class NumericColumnStats:
    column: str
    count: int
    total: "int | float"
    mean: float
    max: "int | float"
    max_row: dict
    max_tied_rows: list[dict] = field(default_factory=list)
    min: "int | float" = 0
    min_row: dict = field(default_factory=dict)
    min_tied_rows: list[dict] = field(default_factory=list)


@dataclass
class ResultStats:
    total_rows: int
    dimensions: dict[str, list[str]]  # column -> full ordered distinct values
    numeric: dict[str, NumericColumnStats]  # column -> stats, insertion order


def compute_result_stats(rows: list[dict]) -> "ResultStats | None":
    """The structured replacement for pipeline.py's old `_result_digest` body.
    `None` for a 0- or 1-row result — mirrors `_result_digest`'s own early
    return, since a single row has nothing to aggregate across."""
    if len(rows) < 2:
        return None

    dim_order: dict[str, list[str]] = {}
    dim_seen: dict[str, set[str]] = {}
    num_cols: list[str] = []
    for row in rows:
        for k, v in row.items():
            is_num = _to_number(v) is not None
            if is_num and not _NONSTAT_COL.search(k):
                if k not in num_cols:
                    num_cols.append(k)
                continue
            if v is None:
                continue
            s = str(v)
            if k not in dim_order:
                dim_order[k], dim_seen[k] = [], set()
            if s not in dim_seen[k]:
                dim_seen[k].add(s)
                dim_order[k].append(s)

    numeric: dict[str, NumericColumnStats] = {}
    for k in num_cols:
        pairs = [(r, _to_number(r.get(k))) for r in rows if _to_number(r.get(k)) is not None]
        if not pairs:
            continue
        nums = [n for _r, n in pairs]
        total = sum(nums)
        hi_row, hi = max(pairs, key=lambda p: p[1])
        lo_row, lo = min(pairs, key=lambda p: p[1])
        mean = total / len(nums)
        max_tied = [r for r, n in pairs if n == hi]
        min_tied = [r for r, n in pairs if n == lo]
        numeric[k] = NumericColumnStats(
            column=k, count=len(nums), total=total, mean=mean,
            max=hi, max_row=hi_row, max_tied_rows=max_tied,
            min=lo, min_row=lo_row, min_tied_rows=min_tied,
        )

    return ResultStats(total_rows=len(rows), dimensions=dim_order, numeric=numeric)


def _dim_label(row: dict, dim_cols: "list[str] | dict") -> str:
    parts = [str(row[k]) for k in dim_cols if row.get(k) is not None]
    return " / ".join(parts) if parts else "(row)"


def _finding(type_: str, severity: str, message: str,
             column: "str | None" = None, row_ref: "dict | None" = None) -> dict:
    return {"type": type_, "severity": severity, "message": message,
            "column": column, "row_ref": row_ref}


def _empty_result_finding(schemes: "list[str] | None") -> dict:
    return _finding("empty_result", "info",
                     "The query returned no matching records.")


def _extreme_findings(stats: ResultStats) -> list[dict]:
    out: list[dict] = []
    dim_cols = list(stats.dimensions.keys())
    for col, ns in stats.numeric.items():
        out.append(_finding(
            "extreme", "info",
            f"{col}: max is {ns.max} at [{_dim_label(ns.max_row, dim_cols)}], "
            f"min is {ns.min} at [{_dim_label(ns.min_row, dim_cols)}].",
            column=col, row_ref=ns.max_row,
        ))
    return out


def _tie_findings(stats: ResultStats) -> list[dict]:
    out: list[dict] = []
    dim_cols = list(stats.dimensions.keys())
    for col, ns in stats.numeric.items():
        if len(ns.max_tied_rows) > 1:
            labels = ", ".join(_dim_label(r, dim_cols) for r in ns.max_tied_rows)
            out.append(_finding(
                "tie", "warning",
                f"{col}: {len(ns.max_tied_rows)} rows are tied at the maximum ({ns.max}): {labels}.",
                column=col, row_ref=ns.max_row,
            ))
        if len(ns.min_tied_rows) > 1 and ns.min != ns.max:
            labels = ", ".join(_dim_label(r, dim_cols) for r in ns.min_tied_rows)
            out.append(_finding(
                "tie", "warning",
                f"{col}: {len(ns.min_tied_rows)} rows are tied at the minimum ({ns.min}): {labels}.",
                column=col, row_ref=ns.min_row,
            ))
    return out


def _large_result_finding(row_count: int) -> "dict | None":
    if row_count > settings.FINDINGS_LARGE_RESULT_ROWS:
        return _finding(
            "large_result_set", "info",
            f"This result has {row_count} rows, above the {settings.FINDINGS_LARGE_RESULT_ROWS}-row "
            "threshold for a single answer.",
        )
    return None


_OPS = {
    "gt": lambda v, t: v > t, "gte": lambda v, t: v >= t,
    "lt": lambda v, t: v < t, "lte": lambda v, t: v <= t,
}


def _threshold_findings(schemes: "list[str]", rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for scheme in schemes or []:
        rules = _load_scheme_thresholds(scheme)
        for rule in rules:
            col = rule.get("column")
            op = _OPS.get(rule.get("operator", ""))
            threshold = rule.get("value")
            if not col or op is None or threshold is None:
                continue
            for row in rows:
                n = _to_number(row.get(col))
                if n is None:
                    continue
                try:
                    if op(n, threshold):
                        out.append(_finding(
                            "threshold_breach", rule.get("severity", "warning"),
                            rule.get("message", f"{col} crossed the configured threshold ({threshold}).").format(
                                value=n, threshold=threshold),
                            column=col, row_ref=row,
                        ))
                except Exception:  # noqa: BLE001 — a malformed rule must not abort evaluation
                    logger.warning("findings: threshold rule failed for %s/%s", scheme, col, exc_info=True)
    return out


_STALE_NOTE_COLUMNS = ("data_quality_note", "year_note")


def _stale_data_findings(rows: list[dict]) -> list[dict]:
    """Surface a `data_quality_note`/`year_note` already present in the
    result's own rows (curated.dim_year, pre-joined into most scheme views).
    Read only from the rows this specific query actually returned — never
    from a separate per-scheme lookup — because the column is shared across
    schemes and a note authored for one scheme's data would misattribute if
    copied onto another scheme's answer (confirmed in
    focusplus_foreign_key_augmentation.yaml: "data_quality_note on this
    dimension is scheme-blind - do not surface MGNREGA's notes on a Focus
    Plus answer"). Reading it straight off the rows this query itself
    produced sidesteps that risk entirely."""
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        for col in _STALE_NOTE_COLUMNS:
            val = row.get(col)
            if val and str(val).strip() and str(val) not in seen:
                seen.add(str(val))
                out.append(_finding("stale_data", "warning", str(val).strip(), column=col, row_ref=row))
    return out


def evaluate(question: str, schemes: "list[str] | None", rows: list[dict],
             resolved: "dict | None" = None) -> list[dict]:
    """Structured findings for `rows`. Always a list, never `None`, even when
    nothing fires. Never raises — each detector is isolated so one failing
    check cannot take down the others or the response."""
    findings: list[dict] = []

    if not rows:
        findings.append(_empty_result_finding(schemes))
        return findings

    try:
        findings.extend(_stale_data_findings(rows))
    except Exception:  # noqa: BLE001
        logger.warning("findings: stale-data detector failed", exc_info=True)

    try:
        large = _large_result_finding(len(rows))
        if large:
            findings.append(large)
    except Exception:  # noqa: BLE001
        logger.warning("findings: large-result-set detector failed", exc_info=True)

    try:
        findings.extend(_threshold_findings(schemes or [], rows))
    except Exception:  # noqa: BLE001
        logger.warning("findings: threshold detector failed", exc_info=True)

    stats = compute_result_stats(rows)
    if stats is not None:
        try:
            findings.extend(_extreme_findings(stats))
        except Exception:  # noqa: BLE001
            logger.warning("findings: extremes detector failed", exc_info=True)
        try:
            findings.extend(_tie_findings(stats))
        except Exception:  # noqa: BLE001
            logger.warning("findings: ties detector failed", exc_info=True)

    return findings
