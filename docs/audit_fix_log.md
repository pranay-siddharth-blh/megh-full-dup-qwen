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
| G-1 | Fixed (distinct counts across schemes: bars only, no donut / centre total / %; an asked donut is refused with a note) | frontend/src/chat/columns.js (`measureKind`, `dimOf`, `canAdd`), analytics.js (`noAddReason`, `refused`), measureKinds.js; Messages.jsx (note) | UI `G-1 / G-2 / B-2 …` |
| G-2 | Fixed (bars by default for any scheme label) | analytics.js | UI `G-1 / G-2 / B-2 …` |
| G-3 | Fixed (pivot Total down the districts only; no Total across schemes) | Charts.jsx (`PivotGrid` uses `canAdd` / `dimOf`) | UI `G-3 / G-4 …`, `A-4 …` |
| G-4 | Fixed (backend: no `stacked` hint across years for distinct counts and stocks; UI: no stack / Total across years) | c13 `_chart_hint` (app/measure_kinds.py), analytics.js, Charts.jsx | `test_stacked_only_when_the_measure_adds_along_the_series`; UI `G-3 / G-4 …` |
| G-5 | Fixed (no slices, so no shares, for distinct counts across schemes or years) | analytics.js | UI `G-13 / G-5 …` |
| G-7 | Fixed by the rule — charts never add across schemes, so no plain "Total" can appear under the "Combined" text | analytics.js, Charts.jsx | UI `A-4 …` |
| G-8 | Fixed — Needs live check (union and overlap of village codes per scheme; "which villages have both" lists them, village-level RBAC shape) | app/cross_figures.py (`_OVERLAP`, `village_sets`, `_overlap_answer`), c13 `_c13_e12_cross_figures_denial` | `test_villages_in_either_scheme_are_counted_once`, `test_villages_where_both_are_present_are_listed` |
| I-5 | Fixed — Needs live check (via G-8) | app/cross_figures.py | `test_villages_where_both_are_present_are_listed` |
| G-9 | see phase 5 (what each scheme counts, as a detail column) | | |
| G-10 | Needs my decision — counting each producer group's members once changes every Focus Legacy member figure validated in UAT (D-066 definition "SUM(no_of_pg_members)") and needs the live DB to verify | | |
| G-12 | Fixed (the backend sends each scheme's statewide total; the pivot's Total row uses it, "Total (all records)", tooltip "Includes records with no district") | app/cross_figures.py (`_total_cells`), c13 (`column_totals`), Charts.jsx, Messages.jsx | `test_district_table_carries_the_statewide_totals` |
| G-13 | Fixed (no donut / share of villages across years; stacked headline only where a stack is allowed) | analytics.js | UI `G-13 / G-5 …` |
| A-4 | Fixed (never stacked or totalled across a scheme column, backend hint and UI) | c13 `_chart_hint`, analytics.js, Charts.jsx | `test_stacked_only_…` (scheme rows); UI `A-4 …` |
| A-5 | Fixed (two label columns always use the two-dimension chart, whatever the hint) | analytics.js | UI `A-5 …` |
| A-7 | Fixed (a pie of schemes is refused with a one-line note; grouped bars) | analytics.js, Messages.jsx | UI `A-7 …` |
| B-1 | Already fixed (two schemes get "each scheme measures this differently", no "ahead"; frontend/tests/charts.test.js) | | existing |
| B-2 | Fixed | analytics.js | UI `G-1 / G-2 / B-2 …` |
| B-3 | Fixed (districts on the x-axis, no Total / stack / donut across schemes) | analytics.js, Charts.jsx, c13 `_chart_hint` | UI `B-3 …`; `test_stacked_only_…` |
| B-7 | Fixed (person days / job cards / applications go to the per-scheme path, which answers each scheme's own measure) | app/cross_figures.py (`_OTHER_MEASURE`) | `test_person_days_go_to_the_per_scheme_path` |
| B-8 | Fixed (no winner named from raw size; the answer says the schemes measure different things and names measures to compare on) | app/cross_figures.py (`_BETTER`, `Plan.better`) | `test_better_names_no_winner_on_size` |
| B-9 | Fixed (text says "fewer / less than"; the card no longer ranks schemes, B-1) | app/cross_figures.py (`_leader_sentence`) | `test_least_says_fewer` |
| B-10 | Fixed (money per beneficiary sent as `rupees_per_beneficiary`; the card's measure finder picks it — see phase 6) | app/cross_figures.py (`_rows`) | `test_money_per_beneficiary_is_its_own_column` |
| B-12 | Fixed (bars only for money across schemes) | analytics.js | UI `B-12 …` |
| B-13 | Fixed by I-9 (one `value` column plus `measure` when each scheme has its own measure) | c13 `_c13_unify_scheme_rows` | `test_merged_per_scheme_rows_get_one_shape` |
| B-14 | Fixed (vs / versus / difference read like compare) | app/cross_figures.py (`_SUMMARY`) | `test_vs_reads_like_compare` |
| C-6 | Fixed (one shared non-additive list: job cards never stacked across years, backend and UI) | app/measure_kinds.json + .py, frontend/src/chat/measureKinds.js, c13, c12 | `test_stacked_only_…`, `test_frontend_copy_of_the_measure_kinds_matches` |
| D-1 | Fixed (bar by default, no pie / donut for rates) | analytics.js | UI `D-1 / X-5 / D-8 …` |
| D-7 | Fixed (participation / growth / utilisation / efficiency are rates in the shared list) | measure_kinds.json, c12 `_c12s_additive` | `test_measure_kinds`, `test_stacked_only_…` |
| D-8 | Fixed (no pie / donut when any value is negative) | analytics.js | UI `D-1 / X-5 / D-8 …` |
| D-13 | Fixed (max / min in the shared list; never stacked) | measure_kinds.json, c13 | `test_stacked_only_…` |
| J-6 | Partly fixed — the backend no longer sends `stacked` for a ranking (UI ranked list with block as detail: phase 5) | c13 `_chart_hint` | `test_stacked_only_…` (top 5 villages) |
| J-11 | Fixed (year_key + financial_year read as one period in `_chart_hint`) | c13 `_chart_hint` | `test_year_key_and_financial_year_are_one_period` |
| X-5 | Fixed | analytics.js | UI `D-1 / X-5 / D-8 …` |
| C-2 | Fixed (a label with one value goes in the title) | frontend/src/chat/analytics.js (`splitLabels`, `where`) | UI `C-2 …` |
| C-3 | Fixed (two periods: the finer on the x-axis, the coarser as the series) | analytics.js (`grain`) | UI `C-3 …` |
| E-1 | Fixed (a column determined by another is a detail: table and tooltip, never a series) | analytics.js (`splitLabels`, `full`) | UI `E-1 …` |
| E-2 | Fixed (rank / serial never hidden as a twin) | frontend/src/chat/columns.js (`twinColumns`) | UI `E-2 …` |
| E-7 | Fixed (repeated names get their block on the axis: "Mawlai (MYLLIEM)") — asking the SQL for the block in every village ranking is not done | analytics.js | UI `E-7 …` |
| I-7 | Fixed (backend: only the N ranked districts, rank order; UI: ranked bars per scheme) | app/cross_figures.py, analytics.js | `test_top_n_rows_…`; UI `I-8 … (rank column)` |
| I-8 | Fixed (each scheme's own top / bottom list: one ranked chart per scheme and a table Rank · MGNREGA place · value · PMAY-G place · value) | analytics.js (`perScheme`) | UI `I-8 …` (two tests) |
| J-6 | Fixed (backend no stacked hint for a ranking; UI ranked bars, block in the title or as a detail) | c13 `_chart_hint`, analytics.js | `test_stacked_only_…`; UI `J-6 …` |
| G-9 | Fixed (the answer carries what each scheme's figure is — "household-years: households given work, counted once per year worked" — shown under each tile and in bar tooltips; rows keep their shape, as locked by test_cross_figures) | app/cross_figures.py (`measure_notes`), c13, Messages.jsx, Charts.jsx (`cmp-sub`), chat.css | `test_each_scheme_says_what_its_figure_is`; UI `G-9 …` |
| B-11 | Fixed (tile and tooltip say money spent / released / disbursed) | as G-9 | `test_each_scheme_says_what_its_figure_is` |
| X-1 | Fixed (headlines in the column's unit: "₹1,200 crore", never "1.2L") | frontend/src/chat/chartTheme.js (`fmtUnit`, `insightFor` / `insightForSeries` opts), Charts.jsx | UI `X-1 …` |
| C-1 | Fixed (two periods: "Fell 13% from 2023-24 to 2024-25 (−140)", from the earlier year) | analytics.js (`compareVerdict` opts.periods), chartTheme.js (`verdictText`) | UI `C-1 …` |
| C-4 | Fixed (month names are periods) | chartTheme.js (`isMonthLabel`), analytics.js | UI `C-4 / C-10 …` |
| C-8 | Fixed (month / quarter / week numbers are labels; backend and UI) | columns.js (`isLabelCol`), app/measure_kinds.py (`is_label_col`), c13 `_chart_hint` | UI `C-8 …` |
| C-9 | Fixed (quarters are time, in order, no donut) | analytics.js | UI `C-9 …` |
| C-10 | Fixed (months in financial-year order Apr → Mar) | chartTheme.js (`fyMonthIndex`), analytics.js | UI `C-4 / C-10 …` |
| C-11 | Fixed (period series sorted before colouring) | analytics.js (`pivotStacked`) | UI `C-11 …` |
| C-13 | Fixed (every financial year in the span; a missing one is a gap "(no data)") | analytics.js (`withYearGaps`, `fillYearGaps`) | UI `C-13 …` |
| C-14 | Fixed by phase 3 (rates are never stacked; an asked stack is refused with a note) | analytics.js | UI `D-1 / X-5 / D-8 …` |
| C-15 | Fixed (daily / long series: total and peak, not first-vs-last %) | chartTheme.js (`insightFor`) | UI `C-15 …` |
| C-16 | Fixed (titles "Person days by financial year and district"; caption "X-axis: … · Colours: …") | analytics.js (`titleCol`), Charts.jsx | UI `C-16 …` |
| D-2 | Fixed (units read on spaces and "(%)", "(Rs)") | columns.js (`unitOf`, `nameParts`) | UI `D-2 / D-6 …` |
| D-3 | Already fixed (missing values stay null; frontend/tests/charts.test.js) | | existing |
| D-4 | Fixed (gap in points for percentages) | analytics.js, chartTheme.js | UI `D-4 …` |
| D-5 | Fixed (lower-is-better list flips the "ahead" side) | columns.js (`lowerIsBetter`), analytics.js, chartTheme.js | UI `D-5 / D-12 …` |
| D-6 | Fixed (rate / share / ratio are %; 0–1 fractions read ×100; a wage rate stays money) | columns.js (`unitOf`, `fractionPct`), analytics.js | UI `D-2 / D-6 …` |
| D-9 | Fixed (a % trend headline in points) | chartTheme.js | UI `D-9 …` |
| D-10 | Fixed (tile values carry the unit) | Charts.jsx (`CompareCard` unit), analytics.js | UI `D-10 / D-11 …` |
| D-11 | Already fixed (a missing side shows "no figure" now, and no verdict — that was already so) | Charts.jsx | UI `D-10 / D-11 …` |
| D-12 | Fixed (largest lower-is-better figure headlined "Most pending works (lower is better)" in a warning colour) | chartTheme.js, Charts.jsx | UI `D-5 / D-12 …` |
| B-15 | Fixed ("difference" leads with the absolute gap) | analytics.js, chartTheme.js | UI `B-15 …` |
| I-10 | Partly fixed — UI headline "Lowest" for a low-end question; the backend's "312 villages have none, then the lowest non-zero 5" is not done (model-written SQL; see J-7) | analytics.js (`asksLow`), chartTheme.js | UI `I-10 / J-7 …` |
| J-7 | Partly fixed — as I-10 | as I-10 | as I-10 |
| X-6 | Fixed ("N/A", "-" are blanks) | columns.js (`isBlank`), analytics.js | UI `X-6 / X-7 / X-12 …` |
| X-7 | Fixed (Indian grouping read as a number) | columns.js (`isIndianGrouped`) | UI `X-6 / X-7 / X-12 …` |
| X-12 | Fixed (label words only as the whole name or its end; backend mirror) | columns.js (`isLabelCol`), app/measure_kinds.py, c13 | UI `X-6 / X-7 / X-12 …`; `test_label_words_mark_a_label_only_at_the_end`, `test_a_per_year_measure_is_charted` |
| X-13 | Fixed (below 0.01 of the unit, the smaller unit) | columns.js (`formatCell`), chartTheme.js (`fmtUnit`) | UI `X-13 / X-14 …` |
| X-14 | Partly fixed — rupee columns (rs / rupees / ₹) show ₹ in lakh / crore; a money column named with no unit still depends on its name (the backend does not send a unit per column) | columns.js, chartTheme.js | UI `X-13 / X-14 …` |
