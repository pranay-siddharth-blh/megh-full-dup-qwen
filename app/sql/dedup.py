"""
Duplicate-record guard for generated SQL — every read of a view that holds
duplicate records is swapped, just before execution, for a de-duplicated
version of that view, so counts, breakdowns AND money totals are all computed
over distinct records, whatever SQL the generator wrote.

Why (2026-09-23): "How many CM Elevate applications are there in Jirang?"
answered 760 — the raw row count — when Jirang holds 752 distinct applications;
8 application numbers appear twice. A live audit of every curated view found:

  curated.v_cm_elevate  8,627 rows / 8,600 distinct request_id — 27 application
                        numbers repeated (Piggery 22, Poultry 5): the same
                        application recorded twice with small form-data edits.
  curated.v_pmay        170,981 house rows / 170,613 distinct reg_no — 368
                        registrations repeated with IDENTICAL village, stage,
                        sanctioned amount and sanction date: the same house
                        listed twice, inflating house counts and money sums.
  curated.v_employment / v_expenditure — several rows per village-year are
                        legitimate separate records; the only identical rows
                        are all-zero, so sums are unaffected (village counts
                        already use COUNT(DISTINCT village_code)). Not rewritten.
  curated.v_focus_plus  no duplicate (batch, source_sl_no, tranche) — clean.
  curated.v_focus_legacy 7 group-years with a second, differently-dated
                        remittance — genuine separate payments. Not rewritten.

The swap happens AFTER every validator (join, PII, authorization, verifier)
has judged the generator's own SQL, and the rewritten SQL is what the UI shows
as "SQL query used", so the de-duplication is visible, not hidden.
"""
from __future__ import annotations

import re

# view -> (distinct key expression, tie-break ORDER BY within a key — which
# duplicate row to keep, human description for the answer note)
DEDUP_VIEWS: dict[str, tuple[str, str, str]] = {
    "curated.v_cm_elevate": (
        "request_id",
        "cm_elevate_fact_id DESC",   # keep the latest record of the application
        "application number",
    ),
    "curated.v_pmay": (
        # reg_no is never NULL on real rows; the fact id keeps any NULL-reg_no
        # placeholder row distinct instead of collapsing them into one.
        "COALESCE(reg_no, 'fact:' || pmay_fact_id::text)",
        "pmay_fact_id",
        "registration number",
    ),
}

_NOT_ALIAS = {
    "where", "join", "left", "right", "inner", "outer", "full", "cross", "on",
    "group", "order", "limit", "having", "union", "except", "intersect",
    "window", "offset", "fetch", "natural", "using", "lateral", "for",
}


def dedupe_sql(sql: str) -> tuple[str, list[str]]:
    """(rewritten SQL, descriptions of the keys de-duplicated on). Each
    `curated.<view> [AS] [alias]` in a FROM/JOIN becomes
    `(SELECT DISTINCT ON (<key>) * FROM curated.<view> ORDER BY <key>, <tiebreak>) AS <alias>`
    — the alias defaults to the bare view name so `v_pmay.col` references keep
    working. Idempotent: an already-rewritten statement is left alone."""
    applied: list[str] = []
    out = sql or ""
    for view, (key, tiebreak, label) in DEDUP_VIEWS.items():
        if "DISTINCT ON" in out and view in out and f"FROM {view} ORDER BY" in out:
            continue  # already rewritten
        bare = view.split(".", 1)[1]
        pat = re.compile(
            rf"(?P<kw>\b(?:FROM|JOIN)\s+){re.escape(view)}\b"
            rf"(?:(?P<sep>\s+)(?P<as>AS\s+)?(?P<alias>[A-Za-z_]\w*))?",
            re.IGNORECASE)

        def _swap(m: re.Match) -> str:
            alias = m.group("alias")
            trailing = ""
            if alias and alias.lower() in _NOT_ALIAS and not m.group("as"):
                # a keyword, not an alias — put it back with its own whitespace
                trailing, alias = f"{m.group('sep')}{alias}", None
            name = alias or bare
            return (f"{m.group('kw')}(SELECT DISTINCT ON ({key}) * FROM {view} "
                    f"ORDER BY {key}, {tiebreak}) AS {name}{trailing}")

        new, n = pat.subn(_swap, out)
        if n:
            out = new
            applied.append(label)
    return out, applied


def note_for(applied: list[str]) -> str:
    """One-line disclosure for the answer when de-duplication was applied."""
    if not applied:
        return ""
    keys = " / ".join(dict.fromkeys(applied))
    return f"_Duplicate records (same {keys}) are counted once._"
