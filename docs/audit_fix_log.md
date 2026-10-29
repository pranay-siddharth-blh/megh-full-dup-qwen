# Chat UI audit — fix log

Source: *Megh One AI — Chat UI Audit (question scenarios)*, 29 Oct 2026 (195 findings, sections A–K and X).
Branch: `fix/chat-ui-audit`, from `origin/Main` at `1360c3b` (already includes `851143f`).

Statuses: **Fixed** · **Partly fixed** (what is left is said) · **Already fixed** (current code already does
what the audit asks) · **Not reproducible** · **Needs my decision** (a product decision; options in the final
report) · **Needs live check** (fixed in code, but only a live DB / browser run can confirm).

Test files added: `tests/test_chat_ui_audit_reading_2026_10_29.py` (sections I, J — planner, per-year
rewrite, year readers), `tests/test_chat_ui_audit_rows_2026_10_29.py` (section A — one row shape),
`frontend/tests/audit.test.js` (UI, real `buildAnalytics`).

| ID | Status | Files changed | Test added |
|---|---|---|---|
| I-1 | Fixed | app/cross_figures.py (`rank_ask`, `_top_n`, `plan`) | test_chat_ui_audit_reading: `test_cross_scheme_wordings_are_read_at_the_right_level` (D2–D5, D11, D17, A2, N2, N29), `test_bottom_districts_are_ranked_per_scheme_lowest_first` |
| I-2 | Fixed | app/conversation_layer.py (`per_year_plan`, `_cl_carries_scope`, `_cl_one_scheme_question`) | `test_per_year_questions_keep_their_place_and_ranking` (Y2, Y3, Y6) |
| I-3 | Fixed | app/cross_figures.py (`rank_ask`: "lowest block" → per-scheme path) | wordings table (B2) |
| I-4 | Fixed | app/cross_figures.py (`rank_ask`: rank districts, worst / weakest performing, districts ranked by) | wordings table (D8, D15, D16, N17, N24) |
| I-5 | see G-8 | | |
| I-6 | Fixed | app/cross_figures.py (`_district_lines`, `_ranks_combined`: one list per scheme unless "combined / together / in total") | `test_a_district_ranking_is_one_list_per_scheme_unless_combined_is_said`, `test_bottom_districts_are_ranked_per_scheme_lowest_first` |
| I-7 | Fixed (backend rows; chart in phase 4/5) | app/cross_figures.py (`_rows`, `ranked_districts`) | `test_top_n_rows_are_only_the_n_ranked_districts` |
| I-11 | Fixed | app/cross_figures.py (`_YEARLY` instead of `_OTHER_GRAIN` for a district ranking) | wordings table (D7), `test_rank_details_…` |
| I-12 | Fixed | app/cross_figures.py (`Plan.both`, `_rank_parts`) | `test_both_ends_second_place_and_exclusion` |
| I-13 | Partly fixed — the four coded schemes are ranked and the answer says CM Elevate is not in it; CM Elevate's own list beside them still needs its own question | app/cross_figures.py (`Plan.left_out`) | `test_all_schemes_ranks_the_coded_four_and_says_cm_elevate_is_out` |
| I-14 | Fixed | app/cross_figures.py (`rank_ask`, `Plan.nth`) | wordings table (N1, N4, N6, N10, N11, N18), `test_both_ends_second_place_and_exclusion` |
| I-15 | Fixed | app/cross_figures.py (`rank_ask`: "least performing blocks" → per-scheme path) | wordings table (N5) |
| I-16 | Fixed | app/cross_figures.py (`_level`: singular and one-letter-off "district") | wordings table (N7, N9, N12) |
| I-17 | Already fixed on the pipeline path (`_correct_scheme_spelling`, c14:207, corrects "mgnerga" before routing); fixed on the per-year path, which read the raw text | app/conversation_layer.py (`per_year_plan`) | `test_per_year_questions_keep_their_place_and_ranking` (mgnerga) |
| I-18 | Fixed | app/cross_figures.py (`sabse jyada / zyada / kam`, `kis / kaun sa district`) | wordings table (N13, N14) |
| I-19 | Fixed (when the resolver resolves the excluded place; otherwise the answer says it was not applied) | app/cross_figures.py (`_excluded_places`, `Plan.exclude`) | `test_both_ends_second_place_and_exclusion` |
| I-20 | Fixed | app/cross_figures.py (condition + top N ranked by the gap) | `test_condition_with_top_n_ranks_by_the_gap` |
| I-21 | Fixed | app/cross_figures.py (`first = "avg"`, `value` / `fmt` for money per head) | `test_per_head_ranking_is_on_money_per_beneficiary` |
| A-3 | Fixed | app/conversation_layer.py (`_cl_year_phrase`) | `test_per_year_questions_keep_the_asked_years` |
| G-6 | Fixed (villages never added across schemes in a ranking) | app/cross_figures.py | `test_villages_are_never_added_across_schemes` |
| G-11 | Fixed (combined money ranking names the money kinds) | app/cross_figures.py | `test_a_combined_ranking_says_the_counts_and_money_differ` |
| J-1 | Fixed | app/pipeline/common/c06_years_tranches.py (`_relative_years`), c09_resolve_entities.py | `test_relative_periods_are_read_against_the_years_held`, `test_this_year_says_when_the_year_has_no_data`, `test_a_relative_period_is_never_asked_again` |
| J-2 | Fixed (the dash case left after KI-427) | app/pipeline/common/c09_resolve_entities.py (`_c09_stated_year_span`) | `test_a_dash_between_two_years_is_a_span` |
| J-3 | Fixed (one rule: Focus's money / member words now count as a measure, so every scheme asks alike) | app/pipeline/common/c06_years_tranches.py (`_METRIC_OR_BREAKDOWN_CUE`) | `test_one_year_rule_for_every_scheme` |
| J-4 | Needs my decision (contradicts D-053 / D-056: a new chat asks the area first) | | |
| J-5 | Needs my decision (product decision listed by the audit) | | |
| J-8 | Already fixed (a ranking is never a donut: `asksRanking`, frontend/tests/charts.test.js) | | existing |
| J-10 | Needs my decision (KI-126, product decision) | | |
| A-1 | Fixed | app/pipeline/common/c13_compose_and_data_stages.py (`_c13_unify_scheme_rows`, run in `_attach_chart_hint`), app/conversation_layer.py (`_year_row`), frontend/src/chat/columns.js (`unifyPeriods`), analytics.js | rows: `test_merged_per_scheme_rows_get_one_shape`, `test_the_chart_hint_step_unifies_the_rows`; UI: `A-1: scheme × year rows with differently named year columns keep the year` |
| A-2 | Fixed (years in one "2023-24" form; missing cells were already null in the UI) | app/conversation_layer.py (`_cl_fy`, `_year_row`) | `test_money_rows_are_one_unit_and_one_year_form`; UI `A-2 …` |
| A-8 | Fixed | frontend/src/chat/columns.js (`fyLabel`, `unifyPeriods`) | UI `A-8: a lone year_key reads as a financial year` |
| A-9 | Fixed (money / amount / released / disbursed / funds / villages read; no measure → a "which figure?" pause with chips) | app/conversation_layer.py (`_YEAR_METRICS`, `_MONEY_LABEL`, `_cl_measure_ask`, `per_year_parts`), app/routers/query.py | `test_money_words_ask_each_schemes_own_money`, `test_no_measure_asks_which_figure` |
| A-10 | Fixed (every money figure converted to ₹ crore from its column's unit, column `money_crore`) | app/conversation_layer.py (`_cl_money_crore`) | `test_money_rows_are_one_unit_and_one_year_form` |
| A-11 | Fixed (each measure asked only of the scheme that holds it; "PMAY-G records no person-days" said) | app/conversation_layer.py, app/routers/query.py (`multi_notes`) | `test_each_measure_goes_to_the_scheme_that_holds_it`, `test_different_measures_share_one_value_column`, `test_scheme_notes_reach_the_answer` |
| A-12 | Fixed (the column matching the asked measure; code / id / lgd / key columns skipped) | app/conversation_layer.py (`_year_row`) | `test_money_rows_are_one_unit_and_one_year_form` |
| A-13 | Partly fixed — no-data years are gaps (already) and each scheme is headlined at its own latest year; shading the years a scheme does not hold is not done | frontend/src/chat/chartTheme.js (`insightForSeries`) | UI `A-13 …` |
| A-14 | Fixed — Needs live check (two or more named years always become `year_key_list` on the cross-scheme path) | app/pipeline/common/c13_compose_and_data_stages.py (`_cross_scheme_scope`) | `test_two_named_years_are_both_read` |
| A-15 | Fixed (annually / yearly / trend / over the years / year on year are per-year words on both paths) | app/conversation_layer.py (`_PER_YEAR_CUE`) | `test_annually_and_yearly_are_per_year_words` |
| A-16 | Partly fixed — a stated span or list of years over beneficiaries / money / villages of the four coded schemes is now one fixed query per scheme grouped by year (`op="by_year"`). "Each year / year wise" wordings stay on `per_year_plan` → `answer_many` (now one row shape): an existing test (`test_other_shapes_stay_on_the_model_path`, "year by year") locks them off this module | app/cross_figures.py (`scheme_figures(by_year=…)`, `_year_lines`, `_rows`) | `test_a_stated_span_is_one_fixed_query_per_scheme_by_year` |
| A-17 | Fixed (the answer says why CM Elevate Legacy is used) | app/conversation_layer.py (`_CL_LEGACY_NOTE`) | `test_rows_with_no_year_leave_the_chart_and_failure_is_marked` |
| A-18 | Fixed (the years used are in the first line: by-year header "FY 2022-23 to FY 2025-26 (4 years)", relative periods' label) | app/cross_figures.py, c06 `_relative_years` | `test_a_stated_span_is_one_fixed_query_per_scheme_by_year` |
| I-9 | Fixed (place columns renamed to one name per level; one `value` + `measure` when each scheme has its own measure) | c13 `_c13_unify_scheme_rows`, conversation_layer `answer_many` | `test_merged_per_scheme_rows_get_one_shape`, `test_different_measures_share_one_value_column` |
| H-2 | Fixed (backend: `answer_failed` + low confidence when nothing came back; rows with no year left out of the chart and said) — UI Retry is F-3 | app/conversation_layer.py | `test_rows_with_no_year_leave_the_chart_and_failure_is_marked` |
