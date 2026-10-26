"""DATA-014 (MGNREGA sheet, run 2026-10-21): "Which villages in <AC> constituency
received employment during <FY>?" intermittently ended in "couldn't build a
working query". The first SQL read curated.v_employment but lacked the
'Unresolved' filter; the c11 guard sent it to repair; the repair model moved
it to curated.fact_mgnrega_employment, which has no place columns, and failed
"column f.lgd_village_name does not exist" on every attempt."""
from app import pipeline as p

Q = "Which villages in Mawryngkneng constituency received employment during 2025-26?"

# the repaired SQL from the failing live trace (MAWRYNGKNENG, FY 2025-26)
DRIFTED = ("SELECT f.lgd_village_name, f.village_code, SUM(f.persons_employed) AS persons_employed "
           "FROM curated.fact_mgnrega_employment AS f WHERE f.year_key = 2025 "
           "AND UPPER(f.assembly_constituency_name) = UPPER('MAWRYNGKNENG') AND f.entity_type <> 'Unresolved' "
           "GROUP BY f.lgd_village_name, f.village_code HAVING SUM(f.persons_employed) > 0 "
           "ORDER BY persons_employed DESC")
# the first SQL of the same trace
FIRST = ("SELECT f.lgd_village_name, f.village_code, SUM(f.persons_employed) AS persons_employed "
         "FROM curated.v_employment AS f WHERE f.year_key = 2025 "
         "AND UPPER(f.assembly_constituency_name) = UPPER('MAWRYNGKNENG') "
         "GROUP BY f.lgd_village_name, f.village_code HAVING SUM(f.persons_employed) > 0 "
         "ORDER BY persons_employed DESC")


def test_fact_table_read_for_place_columns_goes_back_to_the_view():
    out = p._mgnrega_fact_to_view(["MGNREGA"], DRIFTED)
    assert p.sql_ast.tables(out) == {"v_employment"}
    assert "fact_mgnrega_employment" not in out


def test_expenditure_fact_goes_to_its_view():
    sql = "SELECT lgd_block, SUM(total_exp) FROM curated.fact_mgnrega_expenditure GROUP BY lgd_block"
    assert p.sql_ast.tables(p._mgnrega_fact_to_view(["MGNREGA"], sql)) == {"v_expenditure"}


def test_fact_queries_that_need_the_fact_are_left_alone():
    plain = "SELECT SUM(person_days) FROM curated.fact_mgnrega_employment WHERE year_key = 2023"
    assert p._mgnrega_fact_to_view(["MGNREGA"], plain) == plain           # no view-only column
    fact_only = "SELECT lgd_district, SUM(benefit_to_households) FROM curated.fact_mgnrega_employment GROUP BY 1"
    assert p._mgnrega_fact_to_view(["MGNREGA"], fact_only) == fact_only   # benefit_to_households is not on the view
    joined = ("SELECT g.lgd_district, SUM(f.person_days) FROM curated.fact_mgnrega_employment f "
              "JOIN curated.dim_geography g ON g.geography_key = f.geography_key GROUP BY 1")
    assert p._mgnrega_fact_to_view(["MGNREGA"], joined) == joined         # a join supplies the names
    assert p._mgnrega_fact_to_view(["PMAY-G"], DRIFTED) == DRIFTED


def test_village_ranking_gets_the_placeholder_filter_without_a_repair():
    out = p._mgnrega_village_rank_placeholders(Q, ["MGNREGA"], FIRST)
    assert "entity_type <> 'Unresolved'" in out
    assert p._vr_mentions_unresolved(out)                                  # the c11 guard is now satisfied
    assert p._mgnrega_village_rank_placeholders(Q, ["MGNREGA"], out) == out   # idempotent


def test_placeholder_rewrite_only_for_a_village_ranking_on_one_mgnrega_view():
    assert p._mgnrega_village_rank_placeholders("total person-days in Mawryngkneng", ["MGNREGA"], FIRST) == FIRST
    assert p._mgnrega_village_rank_placeholders(Q, ["PMAY-G"], FIRST) == FIRST
    cte = "WITH x AS (" + FIRST + ") SELECT * FROM x ORDER BY 3 DESC"
    assert p._mgnrega_village_rank_placeholders(Q, ["MGNREGA"], cte) == cte


# ── DATA-016: a households / persons count read as a village count ─────────
# live SQL for "How many households received employment in Amlarem during 23-24?"
# after the block chip (2026-10-21): 79 villages answered for 6,917 households
VILLAGE_COUNT = ("SELECT COUNT(DISTINCT village_code) AS employment_villages FROM curated.v_employment "
                 "WHERE lgd_block = 'AMLAREM' AND year_key = 2023 AND households_employed > 0 LIMIT 1")
HH_Q = "How many households received employment in Amlarem during 23-24, the block, not another area type"


def test_households_count_read_as_villages_becomes_the_households_sum():
    out = p._mgnrega_unit_count_not_villages(HH_Q, ["MGNREGA"], VILLAGE_COUNT)
    assert "SUM(households_employed)" in out
    assert "COUNT(DISTINCT village_code)" not in out and "households_employed > 0" not in out
    assert "lgd_block = 'AMLAREM'" in out and "year_key = 2023" in out


def test_persons_count_read_as_villages_becomes_the_persons_sum():
    sql = VILLAGE_COUNT.replace("households_employed", "persons_employed")
    out = p._mgnrega_unit_count_not_villages("How many persons received employment in Amlarem during 23-24?",
                                             ["MGNREGA"], sql)
    assert "SUM(persons_employed)" in out and "COUNT(DISTINCT" not in out


def test_per_district_households_keep_their_grouping():
    sql = ("SELECT lgd_district, COUNT(DISTINCT village_code) AS v FROM curated.v_employment "
           "WHERE households_employed > 0 GROUP BY lgd_district")
    out = p._mgnrega_unit_count_not_villages("How many households received employment in each district?",
                                             ["MGNREGA"], sql)
    assert "SUM(households_employed)" in out and "GROUP BY lgd_district" in out


def test_real_village_counts_and_other_measures_are_left_alone():
    for q in ("How many villages received employment in Amlarem?",
              "Which villages in Amlarem had households employed?",
              "How many households completed 100 days in Amlarem?",
              "What percentage of households were women in Amlarem?"):
        assert p._mgnrega_unit_count_not_villages(q, ["MGNREGA"], VILLAGE_COUNT) == VILLAGE_COUNT
    ok = "SELECT SUM(households_employed) AS h FROM curated.v_employment WHERE lgd_block = 'X'"
    assert p._mgnrega_unit_count_not_villages(HH_Q, ["MGNREGA"], ok) == ok
    assert p._mgnrega_unit_count_not_villages(HH_Q, ["PMAY-G"], VILLAGE_COUNT) == VILLAGE_COUNT


# ── DATA-016 / DATA-003: entity_type = 'Block' matched no MGNREGA row ──────
# live SQL after the block chip ("…, the block, not another area type"), 2026-10-21
LEVEL = ("SELECT SUM(households_employed) AS households_employed FROM curated.v_employment "
         "WHERE lgd_block = 'AMLAREM' AND year_key = 2023 AND entity_type = 'Block' LIMIT 1")


def test_area_level_entity_type_filter_is_dropped():
    out = p._mgnrega_drop_area_level_entity_type(["MGNREGA"], LEVEL)
    assert "entity_type" not in out
    assert "lgd_block = 'AMLAREM'" in out and "year_key = 2023" in out
    exp_sql = ("SELECT ROUND(SUM(total_exp) / 100.0, 2) AS c FROM curated.v_expenditure "
               "WHERE lgd_block = 'BAJENGDOBA' AND year_key = 2025 AND entity_type = 'Block'")
    assert "entity_type" not in p._mgnrega_drop_area_level_entity_type(["MGNREGA"], exp_sql)


def test_row_type_filters_are_kept():
    for cond in ("entity_type <> 'Unresolved'", "entity_type = 'Village'"):
        sql = f"SELECT COUNT(DISTINCT village_code) FROM curated.v_employment WHERE {cond}"
        assert p._mgnrega_drop_area_level_entity_type(["MGNREGA"], sql) == sql
    assert p._mgnrega_drop_area_level_entity_type(["Focus Plus"], LEVEL) == LEVEL
    pmay = "SELECT COUNT(*) FROM curated.v_pmay WHERE entity_type = 'Block'"
    assert p._mgnrega_drop_area_level_entity_type(["MGNREGA"], pmay) == pmay
