"""
app/defaults_engine.py — silent, disclosed defaults for conditions the
`*_default_rules.yaml` files already describe (node 5.5), instead of the
system always pausing with a clarifying question.

Deterministic, no model call — mirrors app/premise_check.py's shape: a pure
`apply_defaults(question, ...)` function over already-resolved query state,
returning note strings appended to the same `notes` channel premise_check
already writes into ahead of `compose_response`.

Collision rule (enforced here in code, not just documented in the YAML
header): a matched condition is applied ONLY when it is not already the job
of an existing hardcoded `_needs_*_clarification` predicate in
app/pipeline.py. `_COLLISION_CONDITIONS` below is that boundary, kept
deliberately conservative — a condition stays in the collision set (never
defaulted) whenever its topic overlaps an existing predicate's domain at
all, even for the narrower instances where that predicate's own regex
wouldn't actually have fired for a given phrasing. Erring toward "ask" is
silent and safe; erring toward "default" silently changes behavior a user
never asked for — so ties go to asking. `missing_top_n` is the flagship
example: it always stays in the collision set here, so this module ships
zero behavior change to `_needs_topn_clarification` by default. Flipping
that (or any other collision) to a silent default is a separate,
explicitly-flagged product decision — not made by this module.

Only a subset of each scheme's `*_default_rules.yaml` conditions have a
matcher wired in below (see `_MATCHERS`). Extending coverage is additive —
write one matcher function and register it — not a redesign, the same
posture app/annotations.py documents for its own not-yet-wired files.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

import yaml

logger = logging.getLogger(__name__)

# app/defaults_engine.py -> repo root -> data/
_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"

_DEFAULT_RULES_FILE = {
    "MGNREGA": _DATA_ROOT / "mgnrega" / "mgnrega_default_rules.yaml",
    "PMAY-G": _DATA_ROOT / "pmay" / "pmay_default_rules.yaml",
    "Focus Plus": _DATA_ROOT / "focus_plus" / "focusplus_default_rules.yaml",
    "CM Elevate": _DATA_ROOT / "cm_elevate" / "cmelevate_default_rules.yaml",
}

# condition name -> {"default_value": ..., "assumption_text": ...}, per scheme.
_rules_cache: dict[str, dict[str, dict]] = {}
_loaded_schemes: set[str] = set()


def _load_scheme_rules(scheme: str) -> dict[str, dict]:
    """Read `scheme`'s `*_default_rules.yaml` once, caching the result. Any
    failure (missing file, unreadable, malformed YAML, unexpected shape)
    degrades to "no conditions for this scheme" — this module must never
    raise because a rules file is absent or broken."""
    if scheme in _loaded_schemes:
        return _rules_cache.get(scheme, {})
    _loaded_schemes.add(scheme)
    path = _DEFAULT_RULES_FILE.get(scheme)
    conditions: dict[str, dict] = {}
    if path is not None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for rule in (data or {}).get("default_rules", []) or []:
                name = rule.get("condition")
                if name:
                    conditions[name] = rule
        except FileNotFoundError:
            logger.warning("defaults_engine: no default-rules file for %s at %s", scheme, path)
        except Exception:  # noqa: BLE001 — malformed YAML, wrong shape, etc.
            logger.warning("defaults_engine: failed to load default-rules file for %s at %s",
                            scheme, path, exc_info=True)
    _rules_cache[scheme] = conditions
    return conditions


# ── Collision set — conditions that stay the job of an existing hardcoded ───
# clarification predicate. Never matched/applied by this module regardless of
# what the matcher functions below would otherwise say.
_COLLISION_CONDITIONS: frozenset[str] = frozenset({
    # ranking-count family -> _needs_topn_clarification's domain
    "missing_top_n",
    "singular_superlative_without_n",
    # geography family -> _needs_scope_clarification's domain
    "missing_geography",
    # year/time family -> _needs_year_clarification's (and, when geography is
    # also missing, _needs_scope_clarification's) domain
    "missing_time_period",
    "relative_year_latest",
    "relative_year_previous",
    "relative_year_earliest",
    "multi_year_request_without_years",
    "trend_without_period",
    "comparison_without_second_period",
    "year_range_partly_outside_data",
    "job_cards_without_year",
    # Focus Plus tranche family -> _needs_tranche_clarification's domain
    "tranche_unspecified",
})


# ── Condition matchers ───────────────────────────────────────────────────────
# Each takes (question, resolved) and returns True when that condition
# applies. Scheme-agnostic where the underlying phrasing is (the same
# vocabulary appears verbatim in every scheme's default-rules file); a
# matcher is only ever consulted for a scheme whose YAML actually defines
# that condition name (see apply_defaults), so it never fires for a scheme
# it wasn't authored against.

# A bare mention of expenditure/amount/money with no unit word (crore/lakh)
# anywhere in the question — mirrors the "no _needs_*_clarification predicate
# exists for units" gap the proposal calls a safe additive default: there is
# no hardcoded gate for currency units at all, so this is genuinely
# non-colliding, not just outside today's regex coverage.
_EXPENDITURE_TERM = re.compile(
    r"\b(expenditure|spend(?:ing)?|spent|amount|disburs\w*|cost|rupees?)\b",
    re.IGNORECASE,
)
_UNIT_STATED = re.compile(r"\b(crore\w*|lakh\w*|rupees?\s*\d|rs\.?\s*\d|₹)\b", re.IGNORECASE)


def _match_expenditure_unit_unspecified(question: str, resolved: dict) -> bool:
    q = question or ""
    return bool(_EXPENDITURE_TERM.search(q)) and not _UNIT_STATED.search(q)


# Ranking language with no explicit count and no dimension noun to rank over —
# kept in the collision set (see above); matcher still implemented so the
# collision check has something real to skip in tests, rather than asserting
# against a condition that can never match.
_RANKING_CUE = re.compile(
    r"\b(top|bottom|highest|lowest|most|least|best|worst|leading|"
    r"rank(?:ed|ing)?|largest|smallest|biggest|maximum|minimum)\b",
    re.IGNORECASE,
)
_RANK_DIMENSION = re.compile(
    r"\b(districts?|blocks?|villages?|panchayats?|gram panchayats?|gps?)\b",
    re.IGNORECASE,
)
_EXPLICIT_COUNT = re.compile(
    r"\btop[\s-]*\d+\b"
    r"|\b(?:top|bottom|first|last)\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\b"
    r"|\b\d+\s+(?:highest|lowest|largest|biggest|smallest|top|best|worst|most|least)\b",
    re.IGNORECASE,
)
_WANTS_ALL = re.compile(
    r"\b(all|every|each|entire|complete|full)\b.{0,20}\b(districts?|blocks?|villages?|"
    r"panchayats?|list|row|rows)\b"
    r"|\blist\s+(?:of\s+)?all\b|\bfor\s+all\b|\bacross\s+all\b|\bno limit\b|\bevery row\b",
    re.IGNORECASE,
)


def _match_missing_top_n(question: str, resolved: dict) -> bool:
    q = question or ""
    if not (_RANKING_CUE.search(q) and _RANK_DIMENSION.search(q)):
        return False
    if _EXPLICIT_COUNT.search(q) or _WANTS_ALL.search(q):
        return False
    return True


_MATCHERS: dict[str, Callable[[str, dict], bool]] = {
    "expenditure_unit_unspecified": _match_expenditure_unit_unspecified,
    "missing_top_n": _match_missing_top_n,
}


class _SafePlaceholder(dict):
    """`str.format_map` support that leaves an unresolvable `{placeholder}`
    literal instead of raising — an assumption_text missing its
    interpolation context should still surface (degraded, not absent), and
    must never turn a UI-facing note into a 500."""

    def __missing__(self, key):  # noqa: D105
        return "{" + key + "}"


def _format_assumption(text: str, resolved: dict) -> str:
    try:
        return text.format_map(_SafePlaceholder(resolved or {}))
    except Exception:  # noqa: BLE001 — a stray brace in curated text, etc.
        return text


def apply_defaults(question: str, schemes: list[str], resolved: dict) -> list[str]:
    """Assumption-text notes for every non-colliding default-rule condition
    that matches `question`/`resolved`, across `schemes`. Empty list when
    nothing matches, a scheme's rules file is missing/malformed, or every
    matched condition collides with an existing hardcoded clarification
    predicate — this function never raises."""
    notes: list[str] = []
    seen: set[str] = set()
    for scheme in schemes or []:
        conditions = _load_scheme_rules(scheme)
        for name, matcher in _MATCHERS.items():
            if name in _COLLISION_CONDITIONS:
                continue
            rule = conditions.get(name)
            if rule is None:
                continue
            try:
                if not matcher(question, resolved or {}):
                    continue
            except Exception:  # noqa: BLE001 — a matcher must never abort the turn
                logger.warning("defaults_engine: matcher for %s failed", name, exc_info=True)
                continue
            text = _format_assumption(rule.get("assumption_text", ""), resolved or {})
            if text and text not in seen:
                seen.add(text)
                notes.append(text)
    return notes
