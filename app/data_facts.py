"""Live data figures for the SQL prompt (schema_context).

The hand-written rules in schema_context quote the data's own sizes — "COUNT(*) gives
8,867 records against 8,840 applications", "lgd_block is NULL on 57,649 of 385,671
rows" — and every one went stale on the next data load: on 2026-10-29 the prompt still
said 8,867 CM Elevate records while megh_db held 8,948, and Focus Legacy said both
"11,906 groups" and "~11,904" (user 2026-10-29: "the complete project is dynamic").

Each figure is now a [[name]] token in the rule text, filled from these fixed, read-only,
parameter-free queries over the same curated views and dims the chatbot reads (never a
privacy table). refresh() runs them at startup and every REFRESH_SECONDS in the
background; build_schema_context() only reads the result, so a prompt build never waits
on the database. A failed query keeps the last good figures; before the first success
each token shows its DEFAULT, the figure that was typed in the rule (so a cold start with
the database down reads exactly as before).

Typed on purpose and NOT here: dated incident history ("confirmed live 2026-09-13 …
dropped 4,670"), figures from outside megh_db (the requirement workbook, the client
API), raw-source measurements the views no longer show (Focus Plus "102,923 source rows
carry no village code", Focus Legacy "1,634 groups under more than one spelling": the views
fill the code and take one name per group) and thresholds ("fewer than 15 applications")."""
import asyncio
import logging
from datetime import datetime, timezone

from app.db import fetch_rows_readonly

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 600

# One row each; column names are unique across all queries (they are merged into one dict).
_QUERIES = {
    "focus_plus": """
        SELECT COUNT(*) AS fp_rows,
               COUNT(*) FILTER (WHERE lgd_block IS NULL) AS fp_lgdblock_null,
               SUM(amount_disbursed) FILTER (WHERE lgd_block IS NULL) AS fp_lgdblock_null_amt,
               COUNT(*) FILTER (WHERE lgd_district IS NULL) AS fp_district_null,
               COUNT(*) FILTER (WHERE lgd_village_name IS NULL) AS fp_villagename_null,
               COUNT(*) FILTER (WHERE batch_label = '12.5K') AS fp_rows_125k,
               COUNT(*) FILTER (WHERE batch_label = '93K') AS fp_rows_93k,
               COUNT(DISTINCT member_key) AS fp_members,
               COUNT(DISTINCT beneficiary_key) AS fp_benef,
               COUNT(DISTINCT beneficiary_key) FILTER (WHERE batch_label = '12.5K') AS fp_benef_125k,
               COUNT(DISTINCT beneficiary_key) FILTER (WHERE batch_label = '93K') AS fp_benef_93k,
               COUNT(DISTINCT beneficiary_key) FILTER (WHERE LOWER(gender) = 'female') AS fp_female,
               COUNT(DISTINCT beneficiary_key) FILTER (WHERE LOWER(gender) = 'male') AS fp_male,
               COUNT(DISTINCT beneficiary_key) FILTER (WHERE financial_year_short = '2022-23') AS fp_benef_2223,
               COUNT(DISTINCT beneficiary_key) FILTER (WHERE financial_year_short = '2025-26') AS fp_benef_2526,
               SUM(amount_disbursed) AS fp_amount,
               SUM(amount_disbursed) FILTER (WHERE lgd_district = 'WEST GARO HILLS') AS fp_wgh_amount,
               COUNT(DISTINCT beneficiary_key) FILTER (WHERE lgd_district = 'WEST GARO HILLS') AS fp_wgh_benef,
               SUM(amount_disbursed) FILTER (WHERE UPPER(block_name_raw) = 'MYLLIEM') AS fp_myl_amt,
               SUM(amount_disbursed) FILTER (WHERE UPPER(block_name_raw) = 'MYLLIEM' AND lgd_block IS NULL) AS fp_myl_lost,
               SUM(amount_disbursed) FILTER (WHERE UPPER(block_name_raw) = 'RONGRAM') AS fp_ron_amt,
               SUM(amount_disbursed) FILTER (WHERE UPPER(block_name_raw) = 'RONGRAM' AND lgd_block IS NULL) AS fp_ron_lost,
               SUM(amount_disbursed) FILTER (WHERE UPPER(block_name_raw) = 'LAWSOHTUN') AS fp_law_amt,
               SUM(amount_disbursed) FILTER (WHERE UPPER(block_name_raw) = 'LAWSOHTUN' AND lgd_block IS NULL) AS fp_law_lost,
               ARRAY_AGG(DISTINCT financial_year_short) FILTER (WHERE financial_year_short IS NOT NULL) AS fp_years
        FROM curated.v_focus_plus""",
    "focus_plus_recur": """
        SELECT COUNT(DISTINCT a.beneficiary_key) AS fp_recur
        FROM curated.v_focus_plus a
        WHERE a.financial_year_short = '2022-23'
          AND EXISTS (SELECT 1 FROM curated.v_focus_plus b
                      WHERE b.beneficiary_key = a.beneficiary_key AND b.financial_year_short = '2025-26')""",
    "pmay": """
        SELECT COUNT(*) AS pm_rows,
               COUNT(*) FILTER (WHERE is_placeholder) AS pm_placeholder,
               COUNT(*) FILTER (WHERE sanctioned_amount = 0) AS pm_zero_sanction,
               COUNT(*) FILTER (WHERE year_key IS NULL) AS pm_year_null,
               MIN(year_key) AS pm_year_min, MAX(year_key) AS pm_year_max,
               COUNT(*) FILTER (WHERE amount_released IS NULL AND NOT is_placeholder) AS pm_released_null,
               COUNT(*) FILTER (WHERE status_name IS NULL) AS pm_status_null
        FROM curated.v_pmay""",
    "mgnrega": """
        SELECT SUM(persons_employed) AS mg_rb_persons, SUM(women_employment_provided) AS mg_rb_women
        FROM curated.v_employment
        WHERE lgd_district = 'RI BHOI' AND financial_year_short = '2023-24'""",
    "cm_elevate": """
        SELECT COUNT(*) AS cme_records, COUNT(DISTINCT request_id) AS cme_apps,
               COUNT(*) FILTER (WHERE sector_id IS NOT NULL) AS cme_sector,
               COUNT(DISTINCT request_id) FILTER (WHERE scheme_name ILIKE 'PRIME Small%') AS cme_prime
        FROM curated.v_cm_elevate""",
    "cm_elevate_dups": """
        SELECT COALESCE(SUM(n), 0) AS cme_dup_apps,
               STRING_AGG(n || ' ' || s, ', ' ORDER BY n DESC, s) AS cme_dup_split
        FROM (SELECT s, COUNT(*) AS n FROM (
                SELECT request_id, MIN(SPLIT_PART(REPLACE(scheme_name, 'Meghalaya ', ''), ' ', 1)) AS s
                FROM curated.v_cm_elevate GROUP BY request_id HAVING COUNT(*) > 1) d
              GROUP BY s) t""",
    "cm_elevate_schemes": """
        SELECT COUNT(*) AS cme_schemes,
               COUNT(*) FILTER (WHERE COALESCE(a.n, 0) < 15) AS cme_small_schemes
        FROM curated.dim_cm_elevate_scheme d
        LEFT JOIN (SELECT scheme_name, COUNT(DISTINCT request_id) AS n
                   FROM curated.v_cm_elevate GROUP BY scheme_name) a ON a.scheme_name = d.scheme_name""",
    "focus_legacy": """
        SELECT COUNT(*) AS fl_rows, COUNT(DISTINCT pg_id) AS fl_groups,
               COUNT(DISTINCT pg_name) AS fl_names, SUM(no_of_pg_members) AS fl_members,
               COUNT(*) FILTER (WHERE amount_disbursed <> no_of_pg_members * 5000) AS fl_identity_breaks,
               MAX(amount_disbursed) AS fl_max_amount,
               COUNT(*) FILTER (WHERE SPLIT_PART(pg_id, '-', 3) = 'WKH'
                                  AND lgd_district = 'EASTERN WEST KHASI HILLS') AS fl_stale_wkh,
               COUNT(*) FILTER (WHERE SPLIT_PART(pg_id, '-', 3) = 'WGH'
                                  AND lgd_district = 'SOUTH WEST GARO HILLS') AS fl_stale_wgh,
               MIN(date_of_remittance) AS fl_date_min, MAX(date_of_remittance) AS fl_date_max,
               COUNT(DISTINCT date_of_remittance) AS fl_dates,
               COUNT(*) FILTER (WHERE date_of_remittance IS NULL) AS fl_date_null,
               COUNT(*) FILTER (WHERE date_of_remittance IS NULL AND financial_year_short = '2025-26') AS fl_date_null_2526,
               COUNT(DISTINCT product_raw) AS fl_product_spellings,
               COUNT(DISTINCT UPPER(TRIM(product_raw))) AS fl_products,
               COUNT(*) FILTER (WHERE NULLIF(TRIM(product_raw), '') IS NOT NULL) AS fl_product_rows,
               COUNT(*) FILTER (WHERE financial_year_short = '2024-25') AS fl_rows_2425,
               COUNT(*) FILTER (WHERE financial_year_short = '2024-25' AND NULLIF(TRIM(product_raw), '') IS NOT NULL) AS fl_product_2425,
               COUNT(*) FILTER (WHERE financial_year_short = '2025-26') AS fl_rows_2526,
               COUNT(*) FILTER (WHERE financial_year_short = '2025-26' AND NULLIF(TRIM(product_raw), '') IS NOT NULL) AS fl_product_2526,
               COUNT(*) FILTER (WHERE entity_type = 'Unresolved') AS fl_unresolved,
               COUNT(DISTINCT village_code) AS fl_village_codes,
               COUNT(DISTINCT lgd_village_name) AS fl_village_names,
               COUNT(DISTINCT bank_name) AS fl_banks,
               COUNT(*) FILTER (WHERE bank_name IS NULL AND ifsc_code IS NOT NULL) AS fl_bank_null_ifsc,
               COUNT(*) FILTER (WHERE ifsc_code = 'SBIN0RRMEGB') AS fl_sponsor_ifsc
        FROM curated.v_focus_legacy""",
    "focus_legacy_groups": """
        SELECT COUNT(*) FILTER (WHERE payments > 1) AS fl_groups_repaid
        FROM (SELECT pg_id, COUNT(*) AS payments FROM curated.v_focus_legacy GROUP BY pg_id) g""",
    "focus_legacy_top": """
        SELECT (SELECT SUM(n) FROM (SELECT COUNT(*) AS n FROM curated.v_focus_legacy
                WHERE date_of_remittance IS NOT NULL GROUP BY date_of_remittance
                ORDER BY n DESC LIMIT 3) d) AS fl_top3_dates_rows,
               (SELECT SUM(n) FROM (SELECT COUNT(*) AS n FROM curated.v_focus_legacy
                WHERE bank_name IS NOT NULL GROUP BY bank_name
                ORDER BY n DESC LIMIT 2) b) AS fl_top2_banks_rows,
               (SELECT COUNT(*) FROM curated.dim_producer_group) AS fl_dim_groups,
               (SELECT COUNT(*) FROM curated.dim_pg_entity_type) AS fl_dim_types""",
    "cm_elevate_legacy": """
        SELECT COUNT(*) AS cl_rows,
               COUNT(*) FILTER (WHERE financial_year_short IS NULL) AS cl_year_null,
               COUNT(*) FILTER (WHERE financial_year_short = '2024-25') AS cl_rows_2425,
               COUNT(*) FILTER (WHERE financial_year_short = '2025-26') AS cl_rows_2526,
               COUNT(*) FILTER (WHERE entity_type = 'Unresolved') AS cl_village_null,
               COUNT(DISTINCT lgd_district) AS cl_districts,
               (SELECT COUNT(*) FROM curated.dim_cm_elevate_disb_scheme) AS cl_schemes,
               (SELECT COUNT(*) FROM (SELECT lgd_village_name FROM curated.v_cm_elevate_disbursement
                 WHERE entity_type <> 'Unresolved' GROUP BY lgd_village_name
                 HAVING COUNT(DISTINCT village_code) > 1) s) AS cl_shared_names
        FROM curated.v_cm_elevate_disbursement""",
    "cmss": """
        SELECT COUNT(*) AS cmss_rows,
               COUNT(*) FILTER (WHERE is_disbursed) AS cmss_paid,
               SUM(amount_disbursed) AS cmss_amount,
               COUNT(DISTINCT member_key) AS cmss_students,
               COUNT(DISTINCT lgd_district) AS cmss_districts,
               COUNT(DISTINCT lgd_block) AS cmss_blocks,
               COUNT(DISTINCT village_code) AS cmss_villages,
               COUNT(DISTINCT ac_name) AS cmss_constituencies,
               COUNT(DISTINCT entity_type) AS cmss_entity_types,
               ARRAY_AGG(DISTINCT financial_year_short) FILTER (WHERE financial_year_short IS NOT NULL) AS cmss_years
        FROM curated.v_cmss
""",
    "homestay": """
        SELECT COUNT(*) AS hs_rows,
               COUNT(DISTINCT member_key) AS hs_applicants,
               COUNT(*) FILTER (WHERE file_status = 'Approved') AS hs_approved,
               COUNT(*) FILTER (WHERE is_upgradation) AS hs_upgradation,
               COUNT(DISTINCT lgd_district) AS hs_districts,
               COUNT(DISTINCT lgd_block) AS hs_blocks,
               COUNT(DISTINCT village_code) FILTER (WHERE entity_type <> 'Unresolved') AS hs_villages,
               COUNT(DISTINCT ac_name) AS hs_constituencies,
               ARRAY_AGG(DISTINCT financial_year_short) FILTER (WHERE financial_year_short IS NOT NULL) AS hs_years
        FROM curated.v_homestay_api""",
}


def _n(v) -> str:
    """12345 -> '12,345' (the prompt's own style)."""
    return f"{int(round(float(v))):,}"


def _pct(part, whole, digits: int = 0) -> str:
    p = 100.0 * float(part) / float(whole)
    return f"{p:.{digits}f}"


def _fy_list(years) -> str:
    """['2022-23', '2025-26'] -> 'FY 2022-23 and FY 2025-26'."""
    fys = [f"FY {y}" for y in sorted(str(y) for y in years or [])]
    if len(fys) <= 1:
        return "".join(fys)
    return ", ".join(fys[:-1]) + " and " + fys[-1]


def _fy_gaps(years) -> str:
    """The financial years missing between the first and last held: ' (no FY 2023-24, FY 2024-25)'."""
    held = sorted(int(str(y)[:4]) for y in years or [] if str(y)[:4].isdecimal())
    if len(held) < 2:
        return ""
    gaps = [f"FY {y}-{(y + 1) % 100:02d}" for y in range(held[0], held[-1]) if y not in held]
    return f" (no {', '.join(gaps)} between)" if gaps else ""


# name -> (default: the figure typed in the rule before 2026-10-29, formatter over the merged row)
FACTS = {
    # Focus Plus
    "fp_rows": ("385,671", lambda v: _n(v["fp_rows"])),
    "fp_lgdblock_null": ("57,649", lambda v: _n(v["fp_lgdblock_null"])),
    "fp_lgdblock_null_pct": ("15", lambda v: _pct(v["fp_lgdblock_null"], v["fp_rows"])),
    "fp_lgdblock_null_cr": ("18.01", lambda v: f"{float(v['fp_lgdblock_null_amt'] or 0) / 1e7:.2f}"),
    "fp_district_null": ("4", lambda v: _n(v["fp_district_null"])),
    "fp_villagename_null": ("0", lambda v: _n(v["fp_villagename_null"])),
    "fp_125k_pct": ("3.2", lambda v: _pct(v["fp_rows_125k"], v["fp_rows"], 1)),
    "fp_rows_93k": ("373,144", lambda v: _n(v["fp_rows_93k"])),
    "fp_members": ("12,527", lambda v: _n(v["fp_members"])),
    "fp_benef": ("105,813", lambda v: _n(v["fp_benef"])),
    "fp_benef_125k": ("12,527", lambda v: _n(v["fp_benef_125k"])),
    "fp_benef_93k": ("93,286", lambda v: _n(v["fp_benef_93k"])),
    "fp_female": ("10,263", lambda v: _n(v["fp_female"])),
    "fp_male": ("2,264", lambda v: _n(v["fp_male"])),
    "fp_benef_2223": ("93,286", lambda v: _n(v["fp_benef_2223"])),
    "fp_benef_2526": ("105,813", lambda v: _n(v["fp_benef_2526"])),
    "fp_benef_yearsum": ("199,099", lambda v: _n(v["fp_benef_2223"] + v["fp_benef_2526"])),
    "fp_recur": ("all 93,286", lambda v: (f"all {_n(v['fp_recur'])}" if v["fp_recur"] == v["fp_benef_2223"]
                                          else f"{_n(v['fp_recur'])} of the {_n(v['fp_benef_2223'])}")),
    "fp_avg": ("11,316", lambda v: _n(float(v["fp_amount"]) / v["fp_benef"])),
    "fp_avg_wgh": ("11,167", lambda v: _n(float(v["fp_wgh_amount"]) / v["fp_wgh_benef"])),
    "fp_myl_lost_pct": ("57", lambda v: _pct(v["fp_myl_lost"] or 0, v["fp_myl_amt"])),
    "fp_ron_lost_pct": ("50", lambda v: _pct(v["fp_ron_lost"] or 0, v["fp_ron_amt"])),
    "fp_law_lost_pct": ("66", lambda v: _pct(v["fp_law_lost"] or 0, v["fp_law_amt"])),
    "fp_years": ("FY 2022-23 and FY 2025-26", lambda v: _fy_list(v["fp_years"])),
    "fp_year_gaps": (" (a three-year gap between)", lambda v: _fy_gaps(v["fp_years"])),
    # PMAY-G
    "pm_rows": ("171,107", lambda v: _n(v["pm_rows"])),
    "pm_placeholder": ("126", lambda v: _n(v["pm_placeholder"])),
    "pm_zero_sanction": ("126", lambda v: _n(v["pm_zero_sanction"])),
    "pm_year_null": ("126", lambda v: _n(v["pm_year_null"])),
    "pm_year_min": ("2017", lambda v: str(v["pm_year_min"])),
    "pm_year_max": ("2023", lambda v: str(v["pm_year_max"])),
    "pm_released_null": ("336", lambda v: _n(v["pm_released_null"])),
    "pm_status_null": ("12", lambda v: _n(v["pm_status_null"])),
    # MGNREGA (the worked "men" example, Ri Bhoi FY 2023-24)
    "mg_rb_persons": ("53,700", lambda v: _n(v["mg_rb_persons"])),
    "mg_rb_women": ("29,942", lambda v: _n(v["mg_rb_women"])),
    "mg_rb_men": ("23,758", lambda v: _n(v["mg_rb_persons"] - v["mg_rb_women"])),
    # CM Elevate
    "cme_records": ("8,867", lambda v: _n(v["cme_records"])),
    "cme_apps": ("8,840", lambda v: _n(v["cme_apps"])),
    "cme_sector": ("38", lambda v: _n(v["cme_sector"])),
    "cme_dup_apps": ("27", lambda v: _n(v["cme_dup_apps"])),
    "cme_dup_split": ("22 Piggery, 5 Poultry", lambda v: v["cme_dup_split"] or "none"),
    "cme_schemes": ("15", lambda v: _n(v["cme_schemes"])),
    "cme_small_schemes": ("Six", lambda v: _n(v["cme_small_schemes"])),
    "cme_prime_pct": ("43", lambda v: _pct(v["cme_prime"], v["cme_apps"])),
    # Focus Legacy
    "fl_rows": ("14,566", lambda v: _n(v["fl_rows"])),
    "fl_groups": ("11,906", lambda v: _n(v["fl_groups"])),
    "fl_names": ("10,678", lambda v: _n(v["fl_names"])),
    "fl_members": ("102,021", lambda v: _n(v["fl_members"])),
    "fl_identity_breaks": ("zero", lambda v: "zero" if not v["fl_identity_breaks"] else _n(v["fl_identity_breaks"])),
    "fl_max_amount": ("950,000", lambda v: _n(v["fl_max_amount"])),
    "fl_groups_repaid": ("2,655", lambda v: _n(v["fl_groups_repaid"])),
    "fl_extra_payments": ("2,663", lambda v: _n(v["fl_rows"] - v["fl_groups"])),
    "fl_stale": ("1,075", lambda v: _n(v["fl_stale_wkh"] + v["fl_stale_wgh"])),
    "fl_stale_wkh": ("990", lambda v: _n(v["fl_stale_wkh"])),
    "fl_stale_wgh": ("85", lambda v: _n(v["fl_stale_wgh"])),
    "fl_date_min": ("2021-08-31", lambda v: str(v["fl_date_min"])[:10]),
    "fl_date_max": ("2026-03-31", lambda v: str(v["fl_date_max"])[:10]),
    "fl_dates": ("30", lambda v: _n(v["fl_dates"])),
    "fl_top3_dates_rows": ("9,193", lambda v: _n(v["fl_top3_dates_rows"])),
    "fl_date_null": ("171", lambda v: _n(v["fl_date_null"])),
    "fl_date_null_2526": ("170", lambda v: _n(v["fl_date_null_2526"])),
    "fl_product_spellings": ("62", lambda v: _n(v["fl_product_spellings"])),
    "fl_products": ("45", lambda v: _n(v["fl_products"])),
    "fl_product_rows": ("3,112", lambda v: _n(v["fl_product_rows"])),
    "fl_product_pct": ("21", lambda v: _pct(v["fl_product_rows"], v["fl_rows"])),
    "fl_product_2425": ("0", lambda v: _n(v["fl_product_2425"])),
    "fl_rows_2425": ("2,653", lambda v: _n(v["fl_rows_2425"])),
    "fl_product_2526": ("8", lambda v: _n(v["fl_product_2526"])),
    "fl_rows_2526": ("8,812", lambda v: _n(v["fl_rows_2526"])),
    "fl_unresolved": ("1,101", lambda v: _n(v["fl_unresolved"])),
    "fl_unresolved_pct": ("7.6", lambda v: _pct(v["fl_unresolved"], v["fl_rows"], 1)),
    "fl_village_codes": ("3,384", lambda v: _n(v["fl_village_codes"])),
    "fl_village_names": ("3,270", lambda v: _n(v["fl_village_names"])),
    "fl_banks": ("13", lambda v: _n(v["fl_banks"])),
    "fl_top2_banks_pct": ("92", lambda v: _pct(v["fl_top2_banks_rows"], v["fl_rows"])),
    "fl_bank_null_ifsc": ("276", lambda v: _n(v["fl_bank_null_ifsc"])),
    "fl_sponsor_ifsc": ("8,328", lambda v: _n(v["fl_sponsor_ifsc"])),
    "fl_dim_groups": ("11,904", lambda v: _n(v["fl_dim_groups"])),
    "fl_dim_types": ("3", lambda v: _n(v["fl_dim_types"])),
    # CM Elevate Legacy
    "cl_rows": ("2,823", lambda v: _n(v["cl_rows"])),
    "cl_schemes": ("13", lambda v: _n(v["cl_schemes"])),
    "cl_year_null": ("395", lambda v: _n(v["cl_year_null"])),
    "cl_rows_2425": ("2,291", lambda v: _n(v["cl_rows_2425"])),
    "cl_rows_2526": ("137", lambda v: _n(v["cl_rows_2526"])),
    "cl_village_null": ("404", lambda v: _n(v["cl_village_null"])),
    "cl_shared_names": ("17", lambda v: _n(v["cl_shared_names"])),
    "cl_districts": ("12", lambda v: _n(v["cl_districts"])),
}


# ── Claims: the rules that state the data's SHAPE in words ──────────────────────────
# "FY 2023-24 IS ABSENT", "onhold is FALSE on every row", "loan_entity holds only 'Bank',
# 'LIFCOM' or NULL" cannot be a [[token]]: when a load breaks one, the rule must be
# rewritten by a person (a wrong automatic rewrite is worse than a loud warning). Each
# claim is checked on every refresh; a broken one is logged at WARNING, sent to
# ALERT_WEBHOOK_URL once, and listed in /metrics (data_facts.broken_claims) until it holds
# again (2026-10-29). name -> (where the rule is, read-only SELECT, check(row) -> problem | None)

def _none_bad(row) -> "str | None":
    """The query's `bad` count is 0, else '<bad> rows (e.g. <seen>)'."""
    bad = int(row.get("bad") or 0)
    if not bad:
        return None
    seen = row.get("seen")
    return f"{bad:,} rows" + (f" (e.g. {', '.join(str(s) for s in list(seen)[:5])})" if seen else "")


def _years_exactly(*want: str):
    def check(row) -> "str | None":
        held = sorted(str(y) for y in (row.get("years") or []))
        if held == sorted(want):
            return None
        extra, missing = sorted(set(held) - set(want)), sorted(set(want) - set(held))
        return ("years held " + ", ".join(held)
                + (f"; new: {', '.join(extra)}" if extra else "") + (f"; gone: {', '.join(missing)}" if missing else ""))
    return check


def _outside(col: str, allowed: "tuple[str, ...]", view: str, expr: "str | None" = None) -> str:
    """bad / seen for values of `col` (or `expr`) outside `allowed` (NULL allowed)."""
    e = expr or col
    lits = ", ".join("'" + a.replace("'", "''") + "'" for a in allowed)
    return (f"SELECT COUNT(*) FILTER (WHERE {col} IS NOT NULL AND {e} NOT IN ({lits})) AS bad, "
            f"ARRAY_AGG(DISTINCT {col}::text) FILTER (WHERE {col} IS NOT NULL AND {e} NOT IN ({lits})) AS seen "
            f"FROM {view}")


CLAIMS = {
    "fp_two_amount_values": (
        "Focus Plus rule 7 / catalogue: only two amounts exist, 5,000 and 2,500",
        "SELECT COUNT(*) FILTER (WHERE amount_disbursed NOT IN (5000, 2500)) AS bad, "
        "ARRAY_AGG(DISTINCT amount_disbursed::text) FILTER (WHERE amount_disbursed NOT IN (5000, 2500)) AS seen "
        "FROM curated.v_focus_plus", _none_bad),
    "fp_amount_not_null": (
        "Focus Plus rule 7: amount_disbursed is NOT NULL (no COALESCE needed)",
        "SELECT COUNT(*) FILTER (WHERE amount_disbursed IS NULL) AS bad FROM curated.v_focus_plus", _none_bad),
    "fp_125k_one_row_per_person": (
        "Focus Plus rule 4: the 12.5K cohort is 1 row per person",
        "SELECT COUNT(*) FILTER (WHERE batch_label = '12.5K') "
        "- COUNT(DISTINCT beneficiary_key) FILTER (WHERE batch_label = '12.5K') AS bad FROM curated.v_focus_plus",
        _none_bad),
    "pm_status_values": (
        "PMAY-G tables: status_name is exactly one of the six stages (or NULL)",
        _outside("status_name", ("Proposed Site", "Existing site(Old House)", "House Sanctioned", "Plinth",
                                 "Roof Cast", "Completed"), "curated.v_pmay"), _none_bad),
    "cme_onhold_false": (
        "CM Elevate rule 3: the onhold column is FALSE on every row (on hold = data_verified)",
        "SELECT COUNT(*) FILTER (WHERE onhold) AS bad FROM curated.v_cm_elevate", _none_bad),
    "cme_withdraw_false": (
        "CM Elevate rule 15 / vocabulary: is_withdraw is FALSE on every row (zero withdrawals)",
        "SELECT COUNT(*) FILTER (WHERE is_withdraw) AS bad FROM curated.v_cm_elevate", _none_bad),
    "cme_file_status_values": (
        "CM Elevate rules 7 / 13: current_file_status holds exactly forward / resubmit / sendback to vdv/citizen",
        _outside("current_file_status", ("forward", "resubmit", "sendback to vdv/citizen"), "curated.v_cm_elevate",
                 "LOWER(current_file_status)"), _none_bad),
    "cme_data_verified_values": (
        "CM Elevate rule 13: data_verified is Valid / On Hold / Invalid / Wrong or NULL",
        _outside("data_verified", ("Valid", "On Hold", "Invalid", "Wrong"), "curated.v_cm_elevate"), _none_bad),
    "cme_sector_values": (
        "CM Elevate rule 9a: sector_id is Title Case Poultry / Piggery / Dairy / Goatery",
        _outside("sector_id", ("Poultry", "Piggery", "Dairy", "Goatery"), "curated.v_cm_elevate"), _none_bad),
    "fl_years": (
        "Focus Legacy rule 7: years are 2021-22, 2022-23, 2024-25, 2025-26; FY 2023-24 is absent",
        "SELECT ARRAY_AGG(DISTINCT financial_year_short) FILTER (WHERE financial_year_short IS NOT NULL) AS years "
        "FROM curated.v_focus_legacy", _years_exactly("2021-22", "2022-23", "2024-25", "2025-26")),
    "fl_entitlement_identity": (
        "Focus Legacy rule 3: amount_disbursed = no_of_pg_members * 5000 on every row",
        "SELECT COUNT(*) FILTER (WHERE amount_disbursed <> no_of_pg_members * 5000) AS bad "
        "FROM curated.v_focus_legacy", _none_bad),
    "fl_bank_current_never_false": (
        "Focus Legacy rule 12: bank_details_current is TRUE or NULL, never FALSE",
        "SELECT COUNT(*) FILTER (WHERE bank_details_current IS FALSE) AS bad FROM curated.v_focus_legacy", _none_bad),
    "fl_products_early_years_full": (
        "Focus Legacy rule 9: product_raw is filled on 100% of FY2021-22 and FY2022-23 rows",
        "SELECT COUNT(*) FILTER (WHERE financial_year_short IN ('2021-22', '2022-23') "
        "AND NULLIF(TRIM(product_raw), '') IS NULL) AS bad FROM curated.v_focus_legacy", _none_bad),
    "cl_years": (
        "CM Elevate Legacy rule 7 / vocabulary: only FY 2024-25 and 2025-26 exist",
        "SELECT ARRAY_AGG(DISTINCT financial_year_short) FILTER (WHERE financial_year_short IS NOT NULL) AS years "
        "FROM curated.v_cm_elevate_disbursement", _years_exactly("2024-25", "2025-26")),
    "cl_loan_entity_values": (
        "CM Elevate Legacy rule 11: loan_entity holds only Bank, LIFCOM or NULL",
        _outside("loan_entity", ("Bank", "LIFCOM"), "curated.v_cm_elevate_disbursement"), _none_bad),
    "cl_desanction_values": (
        "CM Elevate Legacy rule 12: desanctioned_reason_raw is Refused / Duplicate / NULL",
        _outside("desanctioned_reason_raw", ("Refused", "Duplicate"), "curated.v_cm_elevate_disbursement"),
        _none_bad),
    "cl_refused_never_false": (
        "CM Elevate Legacy rule 12: refused_flag_raw is TRUE or NULL, never FALSE",
        "SELECT COUNT(*) FILTER (WHERE refused_flag_raw IS FALSE) AS bad FROM curated.v_cm_elevate_disbursement",
        _none_bad),
}

_current: dict[str, str] = {}
_state: dict = {"as_of": None, "errors": [], "broken": {}}


def value(name: str) -> str:
    """The live figure, or its typed default before the first successful read."""
    return _current.get(name) or FACTS[name][0]


def render(text: str) -> str:
    """Fill every [[name]] token. An unknown name is left as written (a test catches it)."""
    if "[[" not in text:
        return text
    out, i = [], 0
    while True:
        j = text.find("[[", i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        k = text.find("]]", j)
        name = text[j + 2:k] if k > 0 else ""
        if name in FACTS:
            out.append(text[i:j] + value(name))
            i = k + 2
        else:
            out.append(text[i:j + 2])
            i = j + 2


def status() -> dict:
    return {"as_of": _state["as_of"], "facts": len(_current), "errors": list(_state["errors"]),
            "claims": len(CLAIMS),
            "broken_claims": [{"claim": n, "rule": CLAIMS[n][0], "problem": p}
                              for n, p in sorted(_state["broken"].items())]}


async def check_claims() -> dict:
    """Run every claim; return {name: problem} for the broken ones. A newly broken claim is
    logged at WARNING and alerted once; one that holds again is logged at INFO. A claim
    whose query fails is left as it was (an outage is not a data change)."""
    broken = dict(_state["broken"])
    for name, (rule, sql, check) in CLAIMS.items():
        try:
            rows = await fetch_rows_readonly(sql)
            problem = check(rows[0] if rows else {})
        except Exception as e:  # noqa: BLE001
            _state["errors"].append(f"claim {name}: {type(e).__name__}")
            logger.warning("data_facts: claim %s could not be checked", name, exc_info=True)
            continue
        if problem and name not in broken:
            logger.warning("data_facts: RULE NO LONGER TRUE — %s: %s. Rewrite it in app/schema_context.py.",
                           rule, problem)
            _alert(name, rule, problem)
        elif not problem and name in broken:
            logger.info("data_facts: rule holds again — %s", rule)
        if problem:
            broken[name] = problem
        else:
            broken.pop(name, None)
    _state["broken"] = broken
    return broken


def _alert(name: str, rule: str, problem: str) -> None:
    """Counts only (no row data), through the guardrail's ALERT_WEBHOOK_URL sender."""
    import socket

    from app import guardrails
    guardrails._post_alert({"source": "megh-one-ai", "alert": "data_rule_broken", "claim": name,
                            "host": socket.gethostname(), "rule": rule, "problem": problem,
                            "text": f"Megh One AI ({socket.gethostname()}): a data rule in the SQL prompt is no "
                                    f"longer true — {rule}: {problem}"})


async def refresh() -> dict:
    """Run every query (one at a time: the shared DB is short of connections) and
    recompute the figures. A query or formatter that fails keeps its last good figures."""
    merged, errors = {}, []
    for key, sql in _QUERIES.items():
        try:
            rows = await fetch_rows_readonly(sql)
            merged.update(rows[0] if rows else {})
        except Exception as e:  # noqa: BLE001
            errors.append(f"{key}: {type(e).__name__}")
            logger.warning("data_facts: query %s failed", key, exc_info=True)
    fresh = {}
    for name, (_default, fmt) in FACTS.items():
        try:
            fresh[name] = str(fmt(merged))
        except Exception:  # noqa: BLE001 — a missing column, a NULL, a zero divisor
            pass
    changed = {n: (value(n), t) for n, t in fresh.items() if t != value(n)}
    _current.update(fresh)
    _state["errors"] = errors
    if fresh:
        _state["as_of"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if changed:
        logger.info("data_facts: %d figure(s) changed: %s", len(changed),
                    ", ".join(f"{n} {a} -> {b}" for n, (a, b) in sorted(changed.items())))
    return changed


async def refresh_loop() -> None:
    """Started from the app's lifespan: refresh the figures and check the claims now,
    then every REFRESH_SECONDS."""
    while True:
        try:
            await refresh()
            await check_claims()
        except Exception:  # noqa: BLE001
            logger.warning("data_facts: refresh failed", exc_info=True)
        await asyncio.sleep(REFRESH_SECONDS)
