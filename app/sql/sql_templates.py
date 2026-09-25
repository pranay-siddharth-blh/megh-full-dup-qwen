"""
app/sql/sql_templates.py — SQL for the most common KPI shape, filled directly
from the QueryFrame with no model call (understand.sql_frame()):

    "value of <metric> for <one scheme> [+ area] [+ year] [+ Focus Plus tranche]"

Every template body is copied verbatim from the SME-verified few-shot SQL in
data/<scheme>/*few_shot.yaml (same view, same aggregate, same unit
conversion, same mandatory filter such as PMAY-G's `NOT is_placeholder`);
only the WHERE clause is filled, from the RESOLVED entity values — never from
the user's text. The result goes through exactly the same guardrails,
duplicate-record rewrite (app/sql/dedup.py) and verifiers as generated SQL.

Deliberately narrow. Anything else — a breakdown, ranking, comparison, trend,
average/share/rate, an unknown metric, or a resolved entity the template
does not know how to filter on — returns None and the model generates the
SQL as before.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.nlu.understand import QueryFrame


@dataclass(frozen=True)
class Template:
    key: str
    select: str                 # "SELECT ... FROM curated.<view>"
    base_where: tuple = ()      # filters every query on this view must carry
    year_col: "str | None" = None   # "year_key" (int) | "financial_year_short" ('2023-24')


# Words a metric may contain on top of the template's own vocabulary. Anything
# else ("new beneficiaries onboarded", "approval status") means the question is
# about a subset or a different figure — no template, the model writes the SQL.
_GENERIC_WORDS = {"total", "number", "of", "count", "the", "overall", "all", "sum", "value", "how",
                  "many", "much", "figure", "figures", "in", "under", "for", "and", "so", "far", "till",
                  "date", "to", "cumulative"}
_VOCAB = {
    "mgnrega.expenditure": {"expenditure", "spend", "spent", "spending", "money", "cost", "costs", "incurred"},
    "mgnrega.person_days": {"person", "persons", "days", "day", "persondays", "personday", "generated"},
    "mgnrega.households_employed": {"households", "household", "employed", "employment", "got", "provided",
                                    "received", "given", "work", "job", "jobs"},
    "mgnrega.persons_employed": {"persons", "person", "people", "employed", "employment", "provided"},
    "mgnrega.households_100_days": {"households", "household", "completed", "completing", "complete", "100",
                                    "hundred", "days", "day", "work"},
    "pmay.houses_completed": {"houses", "house", "homes", "home", "completed", "complete", "built"},
    "pmay.houses_in_progress": {"houses", "house", "under", "construction", "progress", "ongoing"},
    "pmay.amount_released": {"amount", "released", "release", "money", "funds", "fund"},
    "pmay.amount_sanctioned": {"amount", "sanctioned", "sanction"},
    "pmay.houses": {"houses", "house", "sanctioned", "built", "homes"},
    "focus.beneficiaries": {"beneficiaries", "beneficiary"},
    "focus.disbursement": {"disbursement", "disbursed", "amount", "money", "paid", "payout", "out"},
    "focus.payments": {"payments", "payment"},
    "cmelevate.applications": {"applications", "application", "applicants", "applicant", "received"},
}


def _vocab_ok(key: str, metric: str) -> bool:
    words = set(re.findall(r"[a-z0-9]+", metric))
    return bool(words) and words <= (_VOCAB.get(key, set()) | _GENERIC_WORDS)


# metric-matching patterns, checked against frame.metric (lower-case), in order.
_MGNREGA = [
    (re.compile(r"\b100[\s-]?days?\b|hundred days?"), Template(
        "mgnrega.households_100_days",
        "SELECT SUM(households_completed_100_days) AS households_completed_100_days FROM curated.v_employment",
        year_col="year_key")),
    (re.compile(r"person[\s-]?days?|persondays?"), Template(
        "mgnrega.person_days",
        "SELECT SUM(person_days) AS person_days FROM curated.v_employment", year_col="year_key")),
    (re.compile(r"households?\b.*\b(employ|work|job)|(employ\w*|work|job)\b.*\bhouseholds?"), Template(
        "mgnrega.households_employed",
        "SELECT SUM(households_employed) AS households_employed FROM curated.v_employment", year_col="year_key")),
    (re.compile(r"persons?\b.*\bemploy|people\b.*\bemploy"), Template(
        "mgnrega.persons_employed",
        "SELECT SUM(persons_employed) AS persons_employed FROM curated.v_employment", year_col="year_key")),
    (re.compile(r"expenditure|spend|spent|spending|money spent|cost\b"), Template(
        "mgnrega.expenditure",
        "SELECT ROUND(SUM(total_exp) / 100, 2) AS total_expenditure_crore FROM curated.v_expenditure",
        year_col="year_key")),
]
_PMAY = [
    (re.compile(r"complet"), Template(
        "pmay.houses_completed", "SELECT COUNT(*) AS completed_houses FROM curated.v_pmay",
        ("NOT is_placeholder", "is_completed"), "financial_year_short")),
    (re.compile(r"under construction|in progress|in-progress|ongoing"), Template(
        "pmay.houses_in_progress", "SELECT COUNT(*) AS in_progress_houses FROM curated.v_pmay",
        ("NOT is_placeholder", "is_in_progress"), "financial_year_short")),
    (re.compile(r"amount released|released amount|released|money released"), Template(
        "pmay.amount_released",
        "SELECT ROUND(SUM(amount_released) / 10000000.0, 2) AS amount_released_crore FROM curated.v_pmay",
        ("NOT is_placeholder",), "financial_year_short")),
    (re.compile(r"sanctioned amount|amount sanctioned"), Template(
        "pmay.amount_sanctioned",
        "SELECT ROUND(SUM(sanctioned_amount) / 10000000.0, 2) AS sanctioned_crore, COUNT(*) AS houses "
        "FROM curated.v_pmay", ("NOT is_placeholder",), "financial_year_short")),
    (re.compile(r"^(houses?|houses? sanctioned|sanctioned houses?|houses? built|number of houses?)$"), Template(
        "pmay.houses", "SELECT COUNT(*) AS houses FROM curated.v_pmay",
        ("NOT is_placeholder",), "financial_year_short")),
]
_FOCUS = [
    (re.compile(r"beneficiar"), Template(
        "focus.beneficiaries",
        "SELECT COUNT(DISTINCT (batch_label, source_sl_no)) AS beneficiaries, COUNT(*) AS payments "
        "FROM curated.v_focus_plus", year_col="financial_year_short")),
    (re.compile(r"disburs|amount|money|paid out|total paid"), Template(
        "focus.disbursement",
        "SELECT COUNT(*) AS payments, SUM(amount_disbursed) AS amount_raw FROM curated.v_focus_plus",
        year_col="financial_year_short")),
    (re.compile(r"^(number of )?payments?$"), Template(
        "focus.payments", "SELECT COUNT(*) AS payments FROM curated.v_focus_plus",
        year_col="financial_year_short")),
]
_CM = [
    (re.compile(r"^(total |number of )?(applications?|applicants?)( received)?$"), Template(
        "cmelevate.applications", "SELECT COUNT(*) AS applications FROM curated.v_cm_elevate")),
]
_BY_SCHEME = {"MGNREGA": _MGNREGA, "PMAY-G": _PMAY, "Focus Plus": _FOCUS, "CM Elevate": _CM}

# A metric that asks for a derived figure, a subset or a breakdown — never templated.
_NOT_A_PLAIN_VALUE = re.compile(
    r"\b(average|avg|mean|per|share|percent\w*|%|rate|ratio|trend|growth|compar\w*|vs|versus|"
    r"women|woman|female|male|gender|widow|category|categories|wage|material|dues|pending|unpaid|"
    r"breakdown|wise|distribution|distinct|unique|duplicate|top|highest|lowest|most|least|"
    r"status|stage|verified|valid|hold|scheme|tranche|batch|occupation|bank)\b", re.IGNORECASE)
# Resolved-entity keys a template knows how to filter on; anything else => no template.
_FILTERABLE = {"district", "district_list", "district_list_region", "block", "village_code",
               "year_key", "tranche_label"}


def _sql_literal(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def choose(frame: QueryFrame, schemes: list[str], entity_result: dict,
           gate_trace: "list[str] | None" = None) -> "tuple[str, str] | None":
    """(template key, SQL) for a plain single-scheme value question, else None."""
    if frame is None or len(schemes or []) != 1:
        return None
    if frame.query_type not in (None, "value") or frame.group_by or frame.top_n:
        return None
    if any(t.startswith("top_n:") and ":default:" in t for t in (gate_trace or [])):
        return None
    metric = (frame.metric or "").strip().casefold()
    if not metric or _NOT_A_PLAIN_VALUE.search(metric):
        return None
    resolved = (entity_result or {}).get("resolved") or {}
    if any(v not in (None, "", []) and k not in _FILTERABLE for k, v in resolved.items()):
        return None
    if resolved.get("district_list") and not resolved.get("district_list_region"):
        return None                     # a named comparison wants one row per district
    scheme = schemes[0]
    tpl = next((t for rx, t in _BY_SCHEME.get(scheme, []) if rx.search(metric)), None)
    if tpl is None or not _vocab_ok(tpl.key, metric):
        return None
    if resolved.get("tranche_label") and scheme != "Focus Plus":
        return None
    if resolved.get("year_key") is not None and tpl.year_col is None:
        return None                     # a year filter on a scheme without one — let the model explain

    where = list(tpl.base_where)
    if resolved.get("village_code") is not None:
        where.append(f"village_code = {int(resolved['village_code'])}")
    elif resolved.get("block"):
        where.append(f"lgd_block = {_sql_literal(str(resolved['block']).upper())}")
    elif resolved.get("district"):
        where.append(f"lgd_district = {_sql_literal(str(resolved['district']).upper())}")
    elif resolved.get("district_list"):
        where.append("lgd_district IN (" + ", ".join(
            _sql_literal(str(d).upper()) for d in resolved["district_list"]) + ")")
    if resolved.get("year_key") is not None:
        y = int(resolved["year_key"])
        where.append(f"year_key = {y}" if tpl.year_col == "year_key"
                     else f"financial_year_short = '{y}-{(y + 1) % 100:02d}'")
    if resolved.get("tranche_label"):
        where.append(f"tranche_label = {_sql_literal(resolved['tranche_label'])}")
    sql = tpl.select + (" WHERE " + " AND ".join(where) if where else "") + ";"
    return tpl.key, sql
