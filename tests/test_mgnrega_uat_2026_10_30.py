"""MGNREGA sheet UAT round 2026-10-30 (tests/sheet_runs/mg_uat.py): regression tests for every
defect the live run found. Each test calls the real pipeline function."""
from app import pipeline as p


# ── village code printed with digit grouping ────────────────────────────────
def test_village_code_in_list_answer_is_not_grouped():
    # the statewide "which village generated the highest person-days?" list (DATA-026, all years)
    rows = [{"village_code": 278380, "lgd_village_name": "MAWRYNGKNENG", "person_days": 330624},
            {"village_code": 277391, "lgd_village_name": "JAKREM", "person_days": 299885}]
    out = p._group_result_digits(p._deterministic_answer(rows), rows, ["MGNREGA"])
    assert "278380" in out and "277391" in out
    assert "2,78,380" not in out and "278,380" not in out
    assert "3,30,624" in out            # the figure itself keeps its grouping


def test_village_code_written_by_composer_is_not_grouped():
    # DATA-014 South Tura constituency: "Sangsanggre village, code 9,04,714"
    rows = [{"lgd_village_name": "SANGSANGGRE", "village_code": 904714, "persons_employed": 152,
             "lgd_block": "GAMBEGRE"}]
    for written in ("904,714", "9,04,714"):
        out = p._group_result_digits(f"Sangsanggre village, code {written}, received 152 persons.", rows,
                                     ["MGNREGA"])
        assert "code 904714," in out


def test_figure_equal_to_a_code_keeps_its_grouping():
    # a figure cell with the same value as a code is a figure: left grouped
    rows = [{"village_code": 150000, "person_days": 150000}]
    out = p._group_result_digits("Person days: 1,50,000.", rows, ["MGNREGA"])
    assert "1,50,000" in out


# ── verifier: a ranking of places needs GROUP BY (DATA-024, all years) ──────
_RANK_SQL = ("SELECT lgd_district, ROUND(SUM(total_exp) / 100, 2) AS total_expenditure_crore "
             "FROM curated.v_expenditure GROUP BY lgd_district ORDER BY total_expenditure_crore DESC LIMIT 3")
_RANK_ISSUE = ("Check 3 fails: The SQL uses GROUP BY lgd_district and orders by total_expenditure_crore, but the "
               "question asks for 'the highest expenditure across all financial years' which implies a total "
               "aggregated value across all districts and years, not grouped by district. The query should not "
               "group by lgd_district and should instead return a single row with the total expenditure.")


def test_ranking_question_group_by_complaint_is_discarded():
    q = "Which district had the highest expenditure across all financial years"
    assert p._c11_ranked_levels(q) == {"district"}
    assert p._verifier_total_vs_breakdown_is_false(_RANK_ISSUE, q, _RANK_SQL)


def test_total_question_group_by_complaint_still_stands():
    # no ranking, no breakdown: the verifier's "single total" complaint is kept
    q = "What was the total expenditure in Meghalaya across all financial years"
    assert p._c11_ranked_levels(q) == set()
    assert not p._verifier_total_vs_breakdown_is_false(_RANK_ISSUE, q, _RANK_SQL)


def test_ranking_of_another_level_is_not_excused():
    # ranks blocks, but the SQL groups by district: the complaint is not excused by this rule
    q = "Which block generated the highest expenditure across all financial years"
    assert not p._verifier_total_vs_breakdown_is_false(_RANK_ISSUE, q, _RANK_SQL)


# ── J-10 twins: one row per village, never their sum ────────────────────────
from app import sql_ast  # noqa: E402

_TWIN_SUM = ("SELECT SUM(unskilled_wage_exp) AS unskilled_wage_exp_lakh FROM curated.v_expenditure "
             "WHERE village_code IN (272838, 275151) AND year_key = 2025")
_TWINS = {"village_code_list": [272838, 275151], "year_key": 2025,
          "village_twins": {"272838": "Rangmalgre (Demdema block)", "275151": "Rangmalgre (Resubelpara block)"}}


def test_group_by_village_splits_a_twin_sum():
    # Rangmalgre (Demdema 2.99 lakh + Resubelpara 9.56 lakh) was answered 12.55 lakh
    out = sql_ast.group_by_village(_TWIN_SUM)
    assert {"village_code", "lgd_village_name", "lgd_block"} <= sql_ast.group_by_columns(out)
    assert "village_code IN (272838, 275151)" in out and "year_key = 2025" in out


def test_group_by_village_leaves_a_grouped_or_single_village_query_alone():
    grouped = ("SELECT lgd_village_name, lgd_block, village_code, SUM(h) FROM curated.v_employment "
               "WHERE village_code IN (1, 2) GROUP BY 1, 2, 3")
    assert sql_ast.group_by_village(grouped) == grouped
    aliased = "SELECT village_code AS c, SUM(h) FROM curated.v_employment WHERE village_code IN (1, 2) GROUP BY 1"
    assert sql_ast.group_by_village(aliased) == aliased
    single = "SELECT SUM(h) FROM curated.v_employment WHERE village_code = 5"
    assert sql_ast.group_by_village(single) == single
    by_year = "SELECT year_key, SUM(x) FROM curated.v_employment WHERE village_code IN (1, 2) GROUP BY year_key"
    assert "village_code" in sql_ast.group_by_columns(sql_ast.group_by_village(by_year))


def test_twin_codes_are_pinned_when_the_sql_filters_no_village():
    # MEGAPGRE (three villages): the 30B filtered no code on four attempts (KI-637)
    er = {"resolved": {"village_code_list": [273473, 273920, 275787],
                       "village_twins": {"273473": "a", "273920": "b", "275787": "c"}}}
    out = p._pin_missing_twin_codes(["MGNREGA"], er,
                                    "SELECT SUM(total_exp) AS total_expenditure_lakh FROM curated.v_expenditure")
    assert "village_code IN (273473, 273920, 275787)" in out
    # a text filter on the name, with a district literal beside it: the IN replaces the name, the district goes
    out = p._pin_missing_twin_codes(["MGNREGA"], er, "SELECT SUM(total_exp) AS t FROM curated.v_expenditure "
                                    "WHERE UPPER(lgd_village_name) = 'MEGAPGRE' AND lgd_district = 'WEST GARO HILLS'")
    assert "village_code IN (273473, 273920, 275787)" in out and "WEST GARO HILLS" not in out
    # already filtered by code, or a single village: unchanged
    for s in ("SELECT SUM(total_exp) AS t FROM curated.v_expenditure WHERE village_code IN (273473, 273920, 275787)",
              "SELECT SUM(total_exp) AS t FROM curated.v_expenditure WHERE village_code = 273473"):
        assert p._pin_missing_twin_codes(["MGNREGA"], er, s) == s
    assert p._pin_missing_twin_codes(["MGNREGA"], {"resolved": {"village_code": 273473}},
                                     "SELECT SUM(total_exp) FROM curated.v_expenditure") \
        == "SELECT SUM(total_exp) FROM curated.v_expenditure"


def test_village_grain_money_is_written_in_lakh_not_crore():
    # Anchenggre (three villages) FY 2025-26: 1.60 lakh of materials read "0.02 crore"
    sql = ("SELECT village_code, lgd_block, ROUND(SUM(material_exp) / 100.0, 2) AS material_expenditure_crore "
           "FROM curated.v_expenditure WHERE village_code IN (273508, 273654, 275559) AND year_key = 2025 "
           "GROUP BY village_code, lgd_block ORDER BY material_expenditure_crore DESC")
    er = {"resolved": {"village_code_list": [273508, 273654, 275559], "village_twins": {"273508": "a"}, "year_key": 2025}}
    out = p._mgnrega_village_money_in_lakh("How much was spent on materials in Anchenggre?", ["MGNREGA"], er, sql)
    assert "/ 100" not in out and "crore" not in out.lower()
    assert "ROUND(SUM(material_exp), 2) AS material_expenditure_lakh" in out
    assert "ORDER BY material_expenditure_lakh DESC" in out
    # a single village too (the Kotchugre shape); the officer asking for crore keeps crore; a district is left alone
    one = {"resolved": {"village_code": 272805}}
    assert "crore" not in p._mgnrega_village_money_in_lakh("materials in Kotchugre", ["MGNREGA"], one, sql).lower()
    assert p._mgnrega_village_money_in_lakh("materials in Kotchugre in crore", ["MGNREGA"], one, sql) == sql
    assert p._mgnrega_village_money_in_lakh("materials in Ri Bhoi", ["MGNREGA"], {"resolved": {"district": "RI BHOI"}},
                                            sql) == sql
    assert p._crore_conversion_for_single_village(er, sql)       # the prose-rule guard covers twins as well


def test_twins_verifier_complaints_are_discarded_only_for_the_per_village_query():
    sql = sql_ast.group_by_village(_TWIN_SUM)
    r = dict(_TWINS)
    assert p._verifier_twins_complaint_is_false(
        "Check 2: 'Rangmalgre' should map to one specific village_code, not a list of two", r, sql)
    assert p._verifier_twins_complaint_is_false("Check 3: GROUP BY village_code should be a single total", r, sql)
    # one twin missing from the filter: the complaint stands
    assert not p._verifier_twins_complaint_is_false("Check 3: should be a single total", r,
                                                    sql.replace("272838, ", ""))
    # a complaint about something else stands
    assert not p._verifier_twins_complaint_is_false("Check 1: wrong metric column", r, sql)
    # no twins resolved: never applies
    assert not p._verifier_twins_complaint_is_false("Check 3: single total", {"village_code": 272838}, sql)


import asyncio  # noqa: E402

_RANGSAGRE = {"village_code_list": [272913, 273138, 273664], "year_key": 2023,
              "village_twins": {"272913": "Rangsagre (Selsella block)", "273138": "Rangsagre (Dadenggiri block)",
                                "273664": "Rangsagre (Rerapara block)"}}


def test_twin_det_builds_the_single_area_query_once_per_twin():
    sql, params, shown, meta = p._mgnrega_twin_det(
        "Was more spent on wages or materials in Rangsagre during FY 2023-24?", ["MGNREGA"], _RANGSAGRE)
    assert meta["kind"] == "_mgnrega_wage_material_query" and list(meta["twins"]) == ["272913", "273138", "273664"]
    assert params[meta["code_slot"]] == 272913 and 2023 in params
    assert "village_code = $" in sql and "GROUP BY" not in sql          # the single-area query, parameter-bound
    assert "village_code IN (272913, 273138, 273664)" in shown           # the display SQL names every twin
    # the other shapes go through the same wrapper
    for q, kind in [("Give me the expenditure breakdown for Rangsagre during 2023-24.", "_mgnrega_breakdown_query"),
                    ("How much was spent and how many person-days were generated in Rangsagre during 2023-24?",
                     "_mgnrega_combined_facts_query"),
                    ("How many job cards were issued in Rangsagre during 2023-24?", "_mgnrega_job_cards_query"),
                    ("What was the administrative expenditure in Rangsagre during 2023-24?",
                     "_mgnrega_admin_expenditure_query")]:
        det = p._mgnrega_twin_det(q, ["MGNREGA"], _RANGSAGRE)
        assert det is not None and det[3]["kind"] == kind, q
    # no twins, or a question no fixed query fits: None
    assert p._mgnrega_twin_det("Was more spent on wages or materials in Jakrem?", ["MGNREGA"],
                               {"village_code": 277391}) is None
    assert p._mgnrega_twin_det("How many households received employment in Rangsagre?", ["MGNREGA"],
                               _RANGSAGRE) is None


def test_twins_answer_is_one_verdict_per_village():
    _sql, _params, _shown, meta = p._mgnrega_twin_det(
        "Was more spent on wages or materials in Rangsagre during FY 2023-24?", ["MGNREGA"], _RANGSAGRE)
    rows = [{"village_code": 272913, "twin_village": "Rangsagre (Selsella block)",
             "wage_exp_lakh": 5.1, "material_exp_lakh": 7.2, "source_rows": 1},
            {"village_code": 273138, "twin_village": "Rangsagre (Dadenggiri block)",
             "wage_exp_lakh": 13.62, "material_exp_lakh": 3.0, "source_rows": 1},
            {"village_code": 273664, "twin_village": "Rangsagre (Rerapara block)",
             "wage_exp_lakh": None, "material_exp_lakh": None, "source_rows": 0}]
    out = asyncio.run(p._mgnrega_twins_answer(_sql, rows, {"year": "FY 2023-24"}, meta))
    assert "3 villages share this name" in out
    assert "More was spent on materials than on wages in Rangsagre (Selsella block)" in out
    assert "More was spent on wages than on materials in Rangsagre (Dadenggiri block)" in out
    assert "No MGNREGA wage or material expenditure is recorded for Rangsagre (Rerapara block)" in out


def test_catalogue_twins_answer_names_a_twin_with_no_record():
    meta = {"kind": "_metric_catalog_query", "code_slot": 0,
            "twins": {"276670": "Mawpon (Rambrai block)", "276450": "Mawpon (Mawshynrut block)",
                      "276941": "Mawpon (Mawthadraishan block)"}}
    rows = [{"employment_generated": None, "village_code": 276670, "twin_village": "Mawpon (Rambrai block)"},
            {"employment_generated": 3910, "village_code": 276450, "twin_village": "Mawpon (Mawshynrut block)"},
            {"employment_generated": 2999, "village_code": 276941, "twin_village": "Mawpon (Mawthadraishan block)"}]
    out = asyncio.run(p._mgnrega_twins_answer("/* metric:x */ SELECT 1", rows, {"year": "FY 2022-23"}, meta))
    assert "No MGNREGA record is held for Mawpon (Rambrai block) in FY 2022-23." in out
    assert "3,910" in out and "2,999" in out and "276670" not in out


def test_model_path_names_a_twin_with_no_row():
    result = {"route": "data", "schemes": ["MGNREGA"], "answer": "Chigitchakgiri recorded 38 women employed in "
              "FY 2022-23 across the Chokpot and Gasuapara blocks.",
              "resolved_entities": {"village_code_list": [272988, 275804, 275947], "year_key": 2022,
                                    "village_twins": {"272988": "Chigitchakgiri (Selsella block)",
                                                      "275804": "Chigitchakgiri (Chokpot block)",
                                                      "275947": "Chigitchakgiri (Gasuapara block)"}},
              "rows": [{"village_code": 275804, "lgd_block": "CHOKPOT", "women_employed": 30},
                       {"village_code": 275947, "lgd_block": "GASUAPARA", "women_employed": 8}]}
    p._finish_data_result(result)
    assert "No record in FY 2022-23 for Chigitchakgiri (Selsella block)." in result["answer"]
    # every twin present: nothing added
    result2 = dict(result, answer="x", rows=result["rows"] + [{"village_code": 272988, "women_employed": 0}])
    p._finish_data_result(result2)
    assert "No record" not in result2["answer"]
    # another scheme's twins (PMAY-G writes its own per-twin rows, D-096): left alone
    result3 = dict(result, answer="x", schemes=["PMAY-G"])
    p._finish_data_result(result3)
    assert "No record" not in result3["answer"]
    # rows grouped by name and block, no code (Balsrigittim, all-villages run): the twin is known by its block
    result4 = {"route": "data", "schemes": ["MGNREGA"], "answer": "Women employed in Balsrigittim, Resubelpara: 12.",
               "resolved_entities": {"village_code_list": [274838, 275150], "year_key": 2024,
                                     "village_twins": {"274838": "Balsrigittim (Dambo Rongjeng block)",
                                                       "275150": "Balsrigittim (Resubelpara block)"}},
               "rows": [{"lgd_village_name": "BALSRIGITTIM", "lgd_block": "RESUBELPARA", "women_employed": 12}]}
    p._finish_data_result(result4)
    assert "No record in FY 2024-25 for Balsrigittim (Dambo Rongjeng block)." in result4["answer"]
    assert "Resubelpara block)" not in result4["answer"].split("No record")[1]
    # the scope banner naming both twins does not count as having said "no record" (live 2026-10-30)
    result5 = dict(result4, answer="Under MGNREGA, in FY 2024-25 in Balsrigittim (Dambo Rongjeng block), Balsrigittim "
                   "(Resubelpara block) village, the records show 18 women employed.",
                   rows=[{"village_code": 275150, "lgd_block": "RESUBELPARA", "women_employment_provided": 18}])
    p._finish_data_result(result5)
    assert result5["answer"].count("No record") == 1 and "Dambo Rongjeng block)." in result5["answer"]
    p._finish_data_result(result5)                                   # idempotent: a second pass adds nothing
    assert result5["answer"].count("No record") == 1


def test_group_by_village_adds_the_code_to_a_name_and_block_grouping():
    # Bawegre: grouped by name and block, no code — nothing could tie a row to its twin
    sql = ("SELECT lgd_village_name, lgd_block, SUM(semi_skilled_wage_exp) AS semi_skilled_wage_exp_lakh "
           "FROM curated.v_expenditure WHERE village_code IN (273459, 275371) AND year_key = 2024 "
           "GROUP BY lgd_village_name, lgd_block")
    out = sql_ast.group_by_village(sql)
    assert "village_code" in sql_ast.group_by_columns(out) and out.startswith("SELECT village_code, lgd_village_name")
    # already carrying the code: unchanged
    assert sql_ast.group_by_village(out) == out


def test_a_twin_row_whose_figure_the_composer_dropped_is_appended():
    result = {"route": "data", "schemes": ["MGNREGA"],
              "answer": "Semi-skilled wages in Bawegre (Rongram block) during FY 2024-25 totalled ₹0.32 lakh.",
              "resolved_entities": {"village_code_list": [273459, 275371], "year_key": 2024,
                                    "village_twins": {"273459": "Bawegre (Rongram block)", "275371": "Bawegre (Samanda block)"}},
              "rows": [{"semi_skilled_wage_exp_lakh": 0.32, "lgd_block": "RONGRAM", "lgd_village_name": "BAWEGRE"},
                       {"semi_skilled_wage_exp_lakh": 0.63, "lgd_block": "SAMANDA", "lgd_village_name": "BAWEGRE"}]}
    p._finish_data_result(result)
    assert "Bawegre (Samanda block): ₹0.63 lakh" in result["answer"]
    assert "No record" not in result["answer"]
    before = result["answer"]
    p._finish_data_result(result)                        # idempotent
    assert result["answer"] == before


def test_framed_fallback_never_lists_a_code_as_a_figure():
    rows = [{"village_code": 275150, "lgd_village_name": "BALSRIGITTIM", "lgd_block": "RESUBELPARA",
             "women_employment_provided": 18}]
    out = p._framed_fallback(rows, ["MGNREGA"], {"village": "Balsrigittim (Resubelpara block)", "year": "FY 2024-25"})
    assert "275150" not in out and "18 women provided employment" in out
    assert "person-days" not in out                      # a count of women, not person-days (rule 6a)


# ── spelling: a block near miss inside a longer exact village name is left alone ──
def test_block_sound_hit_inside_an_exact_village_name_is_not_rewritten(monkeypatch):
    from app import entity_resolver as er, spelling
    monkeypatch.setattr(er, "_village_names", {"RONGARE ADING": frozenset({"WEST GARO HILLS"})})   # index keys: folded upper words
    toks = spelling.tokens("How many households received employment in RONGARE ADING during 2024-25?")
    i = next(k for k, t in enumerate(toks) if t.raw == "RONGARE")
    assert spelling._inside_village_name(toks, i, i + 1)             # "RONGARE" is part of "RONGARE ADING"
    assert not spelling._inside_village_name(toks, i, i + 2)         # the whole name is not inside a longer one
    toks2 = spelling.tokens("How many households received employment in Rongare during 2024-25?")
    j = next(k for k, t in enumerate(toks2) if t.raw == "Rongare")
    assert not spelling._inside_village_name(toks2, j, j + 1)        # a bare near miss may still be corrected
    out = spelling.normalise("How many households received employment in RONGARE ADING during 2024-25?")
    assert "RONGARE ADING" in out.text and "Rongara" not in out.text


# ── a "> 0" HAVING is not an unasked threshold (KI-641) ─────────────────────
_AC_LIST_SQL = ("SELECT lgd_village_name, village_code, SUM(persons_employed) AS persons_employed "
                "FROM curated.v_employment WHERE UPPER(assembly_constituency_name) = UPPER('AMLAREM') "
                "GROUP BY lgd_village_name, village_code HAVING SUM(persons_employed) > 0 "
                "ORDER BY persons_employed DESC LIMIT 100")


def test_positive_having_survives_the_unasked_threshold_rewrite():
    q = "Which villages in Amlarem constituency received employment across all financial years"
    out = p._unasked_having_threshold(q, _AC_LIST_SQL)
    assert p._mg_keeps_positive_only(out)
    assert p._mgnrega_village_list_issue(q, ["MGNREGA"], out) is None       # the list guard is satisfied
    # an invented cut-off is still dropped (T13.3)
    low = _AC_LIST_SQL.replace("> 0", "< 10")
    assert "HAVING" not in p._unasked_having_threshold("Are there constituencies where employment is very low?", low)


# ── a "which villages" list is one row per village (KI-642) ─────────────────
def test_raw_row_village_list_becomes_one_row_per_village():
    q = "Which villages in Raksamgre constituency received employment during FY 2023-24?"
    sql = ("SELECT lgd_village_name, village_code FROM curated.v_employment WHERE (UPPER(assembly_constituency_name) "
           "= UPPER('RAKSAMGRE') AND year_key = 2023) AND entity_type <> 'Unresolved' AND persons_employed > 0 "
           "ORDER BY households_employed DESC NULLS LAST")
    assert p._mgnrega_village_list_issue(q, ["MGNREGA"], sql)          # the prose-rule guard names the defect
    out = p._mgnrega_village_list_one_row_each(q, ["MGNREGA"], sql)
    assert {"lgd_village_name", "village_code", "lgd_block"} <= sql_ast.group_by_columns(out)
    assert "HAVING SUM(persons_employed) > 0" in out and "persons_employed > 0 ORDER" not in out
    assert "SUM(households_employed) AS households_employed" in out and "ORDER BY households_employed DESC" in out
    assert "UPPER('RAKSAMGRE')" in out and "year_key = 2023" in out    # every filter kept
    assert p._mgnrega_village_list_issue(q, ["MGNREGA"], out) is None
    # already grouped: unchanged
    grouped = ("SELECT lgd_village_name, village_code, SUM(persons_employed) AS persons_employed FROM curated.v_employment "
               "WHERE year_key = 2023 GROUP BY lgd_village_name, village_code HAVING SUM(persons_employed) > 0")
    assert p._mgnrega_village_list_one_row_each(q, ["MGNREGA"], grouped) == grouped


# ── no year asked: no invented year filter (KI-643) ─────────────────────────
def test_all_years_question_loses_the_models_year_filter():
    q = "What was the average number of person-days per employment household in Meghalaya across all financial years"
    sql = ("SELECT ROUND(SUM(person_days)::numeric / NULLIF(SUM(households_employed), 0), 2) AS avg_person_days_per_household "
           "FROM curated.v_employment WHERE year_key IN (2022, 2023, 2024)")
    out = p._mgnrega_all_years_no_year_filter(q, ["MGNREGA"], {}, sql)
    assert "year_key" not in out and "SUM(person_days)" in out
    # a year the user named, or resolved, stays
    assert p._mgnrega_all_years_no_year_filter("… in Meghalaya during 2023-24", ["MGNREGA"], {"year_key": 2023},
                                               sql.replace("IN (2022, 2023, 2024)", "= 2023")) == \
        sql.replace("IN (2022, 2023, 2024)", "= 2023")
    # women (FY 2025-26 unrecorded) and job cards (a stock) keep their own year rules
    women = sql.replace("SUM(person_days)", "SUM(women_employment_provided)")
    assert p._mgnrega_all_years_no_year_filter(q, ["MGNREGA"], {}, women) == women
    jc = "SELECT SUM(job_cards_issued_total) FROM curated.v_employment WHERE year_key = 2025"
    assert p._mgnrega_all_years_no_year_filter("How many job cards were issued in Meghalaya", ["MGNREGA"], {}, jc) == jc
    # a district filter beside the year filter is kept
    both = sql.replace("WHERE year_key IN (2022, 2023, 2024)", "WHERE lgd_district = 'RI BHOI' AND year_key IN (2022, 2023, 2024)")
    out2 = p._mgnrega_all_years_no_year_filter(q, ["MGNREGA"], {"district": "RI BHOI"}, both)
    assert "lgd_district = 'RI BHOI'" in out2 and "year_key" not in out2


def test_a_word_of_an_exact_village_name_is_not_spell_corrected(monkeypatch):
    # "nongwar pyndeng" (276545) became "nongwar pending" and was answered as another village
    # (all-villages run 2026-10-30, before the PMAY-G session's _village_span_end, KI-631)
    from app import entity_resolver as er, spelling
    monkeypatch.setattr(er, "_village_names", {"NONGWAR PYNDENG": frozenset({"WEST KHASI HILLS"}),
                                               "PYNDENG SHALLANG": frozenset({"WEST KHASI HILLS"})})
    for q in ("How many person-days were generated in nongwar pyndeng during 2023-24?",
              "How many person-days were generated in NONGWAR PYNDENG?",
              "How many job cards were issued in pyndeng shallang during 2022-23?"):   # was the Shallang block
        out = spelling.normalise(q)
        assert "pending" not in out.text and out.corrections == [], out


# ── rephraser may not bring in "scheme(s)" ──────────────────────────────────
def test_rephrase_may_not_add_the_word_schemes():
    orig = "What was the total expenditure in JIGABARI during 2025-2026?"
    assert p._rephrase_violation(orig, "What was the total expenditure under the available schemes in JIGABARI "
                                       "during FY 2025-2026?") == "scheme"
    assert p._rephrase_violation(orig, "What was the total expenditure in JIGABARI during FY 2025-26?") is None
