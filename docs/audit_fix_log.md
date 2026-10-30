# Chat UI audit — fix log

Source: *Megh One AI — Chat UI Audit (question scenarios)*, 29 Oct 2026 (195 findings, sections A–K and X).
Branch: `fix/chat-ui-audit`, from `origin/Main` at `1360c3b` (already includes `851143f`).

Second pass (2026-10-29 evening): the user's 12 decisions applied as recommended, and every
"Not done" / "Partly fixed" item finished (`tests/test_chat_ui_audit_more_2026_10_29.py`).

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
| I-6 | Fixed | app/cross_figures.py (`_district_lines`, `_ranks_combined`: one list per scheme unless "combined / together / in total") | `test_a_district_ranking_is_one_list_per_scheme_unless_combined_is_said`, `test_bottom_districts_are_ranked_per_scheme_lowest_first` |
| I-11 | Fixed | app/cross_figures.py (`_YEARLY` instead of `_OTHER_GRAIN` for a district ranking) | wordings table (D7), `test_rank_details_…` |
| I-12 | Fixed | app/cross_figures.py (`Plan.both`, `_rank_parts`) | `test_both_ends_second_place_and_exclusion` |
| I-13 | Fixed — the coded four are ranked together and CM Elevate's own district list (applications, fixed query on v_cm_elevate) is given beside them; CM Elevate Legacy still noted | app/cross_figures.py (`_cm_elevate_ranking`) | tests/test_chat_ui_audit_more_2026_10_29.py: `test_i13_…` — Needs live check |
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
| J-4 | Fixed (user decision 2026-10-29) — a new-chat question that names its scheme is answered for all of Meghalaya (banner and "by district" chip), no district pause; D-089 | c13 `_data_clarification_stage`, pipeline_graph.py (`raw_question` read-only) | test_new_chat_and_scheme_switch (updated), test_year_asked_without_context (updated) |
| J-5 | Fixed (user decision) — one tap: the year (D-053 still asks it; never a silent year), the area defaults statewide when the scheme is named; a question naming no scheme still asks scheme -> district -> year; D-089 | as J-4 | as J-4 |
| J-8 | Already fixed (a ranking is never a donut: `asksRanking`, frontend/tests/charts.test.js) | | existing |
| J-10 | Fixed (user decision) — a name shared by 2–3 villages in different blocks is answered for each, one row per village with its block (SQL told to GROUP BY village and SELECT the block); banner names them with their blocks. More twins still ask; D-089 | c09 (`_TWINS_ANSWERED`, `_TWINS_MAX`), prompt_builder.py, c14 `_banner_place` | tests/test_chat_ui_audit_more_2026_10_29.py: `test_j10_…` — Needs live check (village index) |
| A-1 | Fixed | app/pipeline/common/c13_compose_and_data_stages.py (`_c13_unify_scheme_rows`, run in `_attach_chart_hint`), app/conversation_layer.py (`_year_row`), frontend/src/chat/columns.js (`unifyPeriods`), analytics.js | rows: `test_merged_per_scheme_rows_get_one_shape`, `test_the_chart_hint_step_unifies_the_rows`; UI: `A-1: scheme × year rows with differently named year columns keep the year` |
| A-2 | Fixed (years in one "2023-24" form; missing cells were already null in the UI) | app/conversation_layer.py (`_cl_fy`, `_year_row`) | `test_money_rows_are_one_unit_and_one_year_form`; UI `A-2 …` |
| A-8 | Fixed | frontend/src/chat/columns.js (`fyLabel`, `unifyPeriods`) | UI `A-8: a lone year_key reads as a financial year` |
| A-9 | Fixed (money / amount / released / disbursed / funds / villages read; no measure → a "which figure?" pause with chips) | app/conversation_layer.py (`_YEAR_METRICS`, `_MONEY_LABEL`, `_cl_measure_ask`, `per_year_parts`), app/routers/query.py | `test_money_words_ask_each_schemes_own_money`, `test_no_measure_asks_which_figure` |
| A-10 | Fixed (every money figure converted to ₹ crore from its column's unit, column `money_crore`) | app/conversation_layer.py (`_cl_money_crore`) | `test_money_rows_are_one_unit_and_one_year_form` |
| A-11 | Fixed (each measure asked only of the scheme that holds it; "PMAY-G records no person-days" said) | app/conversation_layer.py, app/routers/query.py (`multi_notes`) | `test_each_measure_goes_to_the_scheme_that_holds_it`, `test_different_measures_share_one_value_column`, `test_scheme_notes_reach_the_answer` |
| A-12 | Fixed (the column matching the asked measure; code / id / lgd / key columns skipped) | app/conversation_layer.py (`_year_row`) | `test_money_rows_are_one_unit_and_one_year_form` |
| A-13 | Fixed — gaps (never 0), each scheme headlined at its own latest year, and a note names the years each scheme does not hold | analytics.js, chartTheme.js | frontend/tests/audit.test.js: `A-13 …` |
| A-14 | Fixed — Needs live check (two or more named years always become `year_key_list` on the cross-scheme path) | app/pipeline/common/c13_compose_and_data_stages.py (`_cross_scheme_scope`) | `test_two_named_years_are_both_read` |
| A-15 | Fixed (annually / yearly / trend / over the years / year on year are per-year words on both paths) | app/conversation_layer.py (`_PER_YEAR_CUE`) | `test_annually_and_yearly_are_per_year_words` |
| A-16 | Fixed — "each year / year wise / annually" over the coded four's beneficiaries / money / villages is cross_figures' per-year mode (every year held); a place, N, rank, relative years or other measures keep the per-scheme split; the lock test updated | cross_figures.py (`plan`), conversation_layer.py (`_cl_cross_by_year`) | test_cross_figures_2026_10_22 (updated), test_chat_ui_audit_rows / reading (updated) |
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
| G-10 | Fixed (user decision: keep the D-066 figure) — the answer says Focus Legacy members are counted once per payment; per-group counting left for the data team | app/cross_figures.py (`_COUNT_NOTE`) | tests/test_chat_ui_audit_more_2026_10_29.py: `test_g10_…` |
| G-12 | Fixed (the backend sends each scheme's statewide total; the pivot's Total row uses it, "Total (all records)", tooltip "Includes records with no district") | app/cross_figures.py (`_total_cells`), c13 (`column_totals`), Charts.jsx, Messages.jsx | `test_district_table_carries_the_statewide_totals` |
| G-13 | Fixed (no donut / share of villages across years; stacked headline only where a stack is allowed) | analytics.js | UI `G-13 / G-5 …` |
| A-4 | Fixed (never stacked or totalled across a scheme column, backend hint and UI) | c13 `_chart_hint`, analytics.js, Charts.jsx | `test_stacked_only_…` (scheme rows); UI `A-4 …` |
| A-5 | Fixed (two label columns always use the two-dimension chart, whatever the hint) | analytics.js | UI `A-5 …` |
| A-7 | Fixed (a pie of schemes is refused with a one-line note; grouped bars) — superseded 2026-10-30 by D-095: a pie the officer names is drawn, with a caveat | analytics.js, Messages.jsx | UI `A-7 …` |
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
| I-10 | Fixed — backend: a low-end ranking that reaches 0 says "312 villages have no beneficiaries (0)" and lists the lowest that have a figure (SQLGlot rewrite of the same query); UI headline "Lowest" | sql_ast.py (`low_end_queries`), c11 (`_c11_zero_ties`), c13 | tests/test_chat_ui_audit_more_2026_10_29.py: `test_i10_…` — Needs live check |
| J-7 | Fixed — as I-10 | as I-10 | as I-10 |
| X-6 | Fixed ("N/A", "-" are blanks) | columns.js (`isBlank`), analytics.js | UI `X-6 / X-7 / X-12 …` |
| X-7 | Fixed (Indian grouping read as a number) | columns.js (`isIndianGrouped`) | UI `X-6 / X-7 / X-12 …` |
| X-12 | Fixed (label words only as the whole name or its end; backend mirror) | columns.js (`isLabelCol`), app/measure_kinds.py, c13 | UI `X-6 / X-7 / X-12 …`; `test_label_words_mark_a_label_only_at_the_end`, `test_a_per_year_measure_is_charted` |
| X-13 | Fixed (below 0.01 of the unit, the smaller unit) | columns.js (`formatCell`), chartTheme.js (`fmtUnit`) | UI `X-13 / X-14 …` |
| X-14 | Fixed — a single-scheme money column with no unit gets one from the scheme's stored unit and the SQL's division ("amount_released" -> "amount_released_rs"); the UI shows ₹ lakh / crore | c13 `_c13_money_units`, sql_ast.py (`select_divisors`) | tests/test_chat_ui_audit_more_2026_10_29.py: `test_x14_…` |
| K-1 | Fixed (leaving a chat stops its answer; a result that lands after a switch is dropped, not shown in the other chat) | frontend/src/chat/App.jsx (`leaveChat`, `chatGenRef`, `setMessagesHere`) | Needs browser check (React state; no Node harness for App.jsx) |
| K-2 | Fixed (client: sign-out stops the answer, clears the screen, new session id; server: a session held by another signed-in user is refused) — since the merge with Main this is Main's CTX-01 check: 403, per worker and against the durable owner (`session_sync.sync_in`) | App.jsx (`handleLogout`), app/routers/query.py | `test_router_refuses_a_session_held_by_another_user` (tests/test_conversation_layer.py, added); browser check |
| K-4 | Fixed (vote keyed on the answer's own content; the server upsert stores the vote's own question and answer) | frontend/src/chat/format.js (`answerKey`), Messages.jsx, app/routers/feedback.py | UI `K-4 …`; `test_feedback_upsert_keeps_the_votes_own_question_and_answer` |
| K-5 | Fixed (year / code / id columns and 13+ digit values written as text; Indian grouping number format) | frontend/src/chat/exporters.js (`sheetXml` textCols, numFmt 164/165), ChatExport.jsx | UI `K-5 …` |
| K-8 | Fixed (delete of the open chat goes through newChat → leaveChat, which stops the run) | App.jsx | browser check |
| K-9 | Fixed (one pending chip slot; the typed draft is not overwritten; cleared by Stop and chat switch) | App.jsx (`pendingAskRef`) | browser check |
| K-10 | Fixed (box limited to 2,000 characters with a count near the end; a validation error's message is shown, not "[object Object]") | App.jsx, api.js (`detailText`), chat.css | browser check |
| K-12 | Fixed (only a 401 / 403 from /api/auth/me drops the token) | api.js (`fetchMe` status), App.jsx | browser check |
| K-13 | Fixed ("degraded" health counts as back) | App.jsx | browser check |
| K-14 | Fixed (refocus only when focus is already in the chat; never on a touch screen) | App.jsx (`refocusComposer`) | browser check |
| K-25 | Fixed (no Regenerate on a local redraw) | App.jsx (`local`) | browser check |
| K-26 | Fixed (a chat switch forgets the stopped question) | App.jsx (`leaveChat`) | browser check |
| K-33 | Fixed (result count only under data answers; no "0ms") | Messages.jsx | browser check |
| K-37 | Fixed (reason + note cut to the server's 1,000 characters) | Messages.jsx | browser check |
| K-38 | Fixed (an earlier year's date names its year) | frontend/src/chat/format.js | browser check |
| E-5 | Fixed (every descending ORDER BY gets NULLS LAST in the SQL rewrite step, on the SQLGlot tree; UI leaves places with no figure out of a ranking and says how many; all missing: says why there is no chart) | app/sql_ast.py (`nulls_last_on_desc`), c11 `_scheme_sql_rewrites`, analytics.js | `test_descending_sorts_put_missing_figures_last`; UI `E-5 …` |
| E-6 | Fixed (a ranking charts its ranking measure only) | analytics.js | UI `E-6 …` |
| X-2 | Fixed (over 25 categories: top / bottom 15 drawn, "Top 15 of 300 shown; the full list is in the table") | analytics.js | UI `X-2 …` |
| X-3 | Fixed (one row with figures in different units stays a record card unless a chart is asked) | analytics.js | UI `X-3 …` |
| X-9 | Fixed (chips and sidebar items reachable with Tab, pressed with Enter / Space; role="button") | Messages.jsx (`askProps`), Sidebar.jsx (`pressable`) | browser check |
| F-5 | Fixed (as X-9) | Messages.jsx | browser check |
| F-1 | Fixed (a "MGNREGA vs PMAY-G" chip shows its full label) | Messages.jsx (`schemeOf`) | browser check |
| F-2 | Fixed (the pair chip asks for the figures the officer named; a question with no figure keeps "difference between") | app/pipeline/common/c04_scheme_listing.py | `test_comparison_pause_chips_ask_for_the_figures` |
| F-3 | Fixed (a failed data answer says "Could not get the figures" with a Try again chip) | Messages.jsx (`AnswerState`) | browser check |
| F-4 | Fixed (no rows: "No records for this question" with "For all financial years" / "For all of Meghalaya" chips) | Messages.jsx (`AnswerState`) | browser check |
| F-9 | Not reproducible offline — runs through the LLM mention extractor and the DB-backed resolver; the out-of-scope guard already refuses unknown places in the branches readable here. Needs a live check: "MGNREGA person days in East Khasi Hils" | | |
| F-11 | Fixed by G-8 (the "villages with both" chip is now answered by the overlap query) — Needs live check | app/cross_figures.py | `test_villages_where_both_are_present_are_listed` |
| H-4 | Fixed (Excel headings = screen headings) | exporters.js (`tableSheet`) | UI `H-4 / H-10 …` |
| H-5 | Fixed (user decision) — "All years (FY 2022-23 to 2025-26)" when no year was used ("All years" for schemes with different spans, nothing for CM Elevate) | c14 `_banner_year` | test_topic_ledger (updated + new cases) |
| H-6 | Fixed (user decision) — the place's type in the banner: "Umling block", "East Khasi Hills district", "… districts" | c14 `_banner_place` | test_topic_ledger, test_cache_hit_context (updated) |
| H-7 | Fixed for the cross-scheme figures path ("MGNREGA (Focus Plus: no data) · …"); the per-scheme model path does not send which schemes returned rows yet | cross_figures (`schemes_with_data`), c13, c14 `_attach_scope_banner` | `test_banner_names_only_the_schemes_with_figures` |
| H-8 | Fixed (user decision) — 3+ consecutive years print as "FY 2017-18 to 2023-24" | c14 `_banner_year` | test_topic_ledger (new case) |
| H-9 | Fixed — the table sheet has the screen's shape (grid, two-way card with the difference, change column); the raw rows on "Qn data" | exportShape.js (new), ChatExport.jsx | frontend/tests/audit.test.js: `H-9 …` |
| H-10 | Fixed ("Answered for: …" above each table sheet; an "Answered for" column on the Conversation sheet) | ChatExport.jsx, exporters.js | UI `H-4 / H-10 …` |
| H-11 | Fixed (a redraw writes no new sheet; its row points to the original sheet) | App.jsx (`redrawOf`), ChatExport.jsx | browser check |
| H-12 | Fixed (text tables become lines in the Answer cell) | exporters.js (`tablesAsLines`) | UI `H-12 …` |
| A-6 | Fixed (one chart per measure, at most 3, the asked one first) | analytics.js (`askedMeasureCols`, `more`), Messages.jsx | UI `A-6 …` |
| B-4 | Fixed (a row of tiles per asked measure) | analytics.js, Messages.jsx | UI `B-4 …` |
| J-9 | Fixed in the UI (a compare card whatever the number of figures, on the asked measure; names with spaces / "(Rs)" read) — the backend still returns the extra PMAY-G figures, which stay in the table | analytics.js (`colParts` = `nameParts`) | UI `J-9 …` |
| C-12 | Fixed (both dimensions above 8 values: a table, one dimension down and one across, with a note) | analytics.js, Messages.jsx | UI `C-12 …` |
| E-3 | Fixed — at the cap the server counts the true total; "The first 1,000 of 1,532 rows are shown" | c11 (`_c11_true_row_count`), c13, conversation_store.py, Charts.jsx (`RowTotal`), Messages.jsx | tests/test_chat_ui_audit_more_2026_10_29.py: `test_e3_…` — Needs live check |
| E-4 | Fixed by X-3 | analytics.js | UI `X-3 …` |
| E-8 | Fixed (a "#" column on ranking tables) | analytics.js (`ranked`), Charts.jsx (`DynTable rank`) | UI `E-8 …` |
| C-5 | Fixed (place names in CAPITALS shown in Title Case; rows unchanged) | columns.js (`placeTitle`, `formatCell`) | UI `C-5 …` |
| X-8 | Fixed (a redraw says it is drawn here and not saved) | App.jsx | browser check |
| X-15 | Fixed (each chart canvas has role="img" and a label from its title and headline; an asked-for chart keeps a "Show the figures as a table" toggle) | Charts.jsx (`ChartCanvas label`), Messages.jsx | browser check |
| X-17 | Fixed (plain sentence, technical text in "(Details: …)") | api.js (`friendlyError`), App.jsx | browser check |
| H-1 | Fixed (one sentence; the rows are the table) | c13 `_geo_lookup_answer` | `test_village_lookup_is_one_sentence_and_the_table` |
| H-3 | Fixed (scope banner, next-step chips and chart hint on the merged per-year answer) | app/conversation_layer.py (`answer_many`) | `test_per_year_answer_gets_the_banner_and_chips` |
| K-3 | Fixed (citations, suggestions, continue offer, timing, translated_from saved with the turn) | app/conversation_store.py | `test_a_reopened_turn_keeps_its_sources_chips_timing_and_chart` |
| C-7 | Fixed (chart_type and chart_wide saved with the turn) | app/conversation_store.py | same test |
| K-7 | Fixed (chats with no turns are not listed or found) | app/conversation_store.py | `test_chats_with_no_turns_are_not_listed` |
| K-11 | Already fixed (the timeout counts only silence; frontend/tests/stream-timeout.test.js) | | existing |
| K-32 | Already fixed (pings restart the silence timer, api.js) | | existing |
| K-15 | Fixed (the glossary / use-case window: role="dialog", focus moved in and kept inside, returned on close, "Close" label; the expand window already was) | Overlays.jsx | browser check |
| K-19 | Fixed (sample asks PMAY-G 2023-24, the last year it holds) | frontend/src/chat/constants.js | browser check |
| K-20 | Fixed (Focus+ card questions name FOCUS+) | constants.js | browser check |
| K-21 | Fixed (Copy answer adds the table, tab-separated) | exporters.js (`rowsAsTsv`), Messages.jsx | UI `K-21 …` |
| K-22 | Fixed (answer-text tables wrap in print) | chat.css | browser / PDF check |
| K-23 | Fixed — more stop words, and a question typed while an answer runs says it stays in the box | stopContinue.js, App.jsx | frontend/tests/audit.test.js: `K-23 …` |
| K-39 | Fixed ("/chart" alone, an unknown language, an unknown command each get a hint) | App.jsx | browser check |
| F-6 | Fixed by J-1 for "last 3 years / this year / last year / current financial year" (read, so no pause and no garbled chip); other unread time phrases still add "for FY …" to the chip | c06 / c09 | `test_a_relative_period_is_never_asked_again` |
| F-10 | Fixed (the answer's year goes into every chip that names no time) | app/followups.py | `test_next_step_chips_keep_the_year_and_never_repeat_the_question` |
| F-12 | Fixed (a chip that adds no word of its own is dropped) | app/followups.py | same test |
| K-17 | Fixed ("Understood as: …" above an answer to a translated question) | Messages.jsx, chat.css | browser check |
| K-27 | Fixed (signed out mid-answer: a bubble with Try again) | App.jsx | browser check |
| K-29 | Fixed (a chat that cannot be replayed starts a new session) | App.jsx | browser check |
| K-30 | Fixed (an older history search answering late is ignored) | App.jsx (`histSeq`) | browser check |
| K-31 | Fixed (editing a question into a command runs it without cutting the chat) | App.jsx | browser check |
| K-40 | Fixed — starting the mic with Khasi / Garo says "Voice input is English only" on every device (and the tooltip) | App.jsx | browser check |
| B-5 | Fixed (user decision) — the dead `isCrossSummary` / `crossSummaryCharts` path deleted; that shape is a side-by-side card | analytics.js, Messages.jsx | test_table_view_2026_10_28 (updated), frontend/tests/audit.test.js: `B-5 …` |
| B-6 | Fixed — the knowledge comparison ("difference between A and B", "compare A and B schemes") offers "Compare beneficiaries / money spent in A and B"; a bare "Compare A and B" is already answered with figures | c04 `_scheme_comparison_answer` | tests/test_chat_ui_audit_more_2026_10_29.py: `test_b6_…` |
| E-9 | Fixed — no change to the model's LIMIT: when places share the last place's figure the answer says "3 villages tie for place 3 with 12 houses; 1 of them is shown" (one COUNT on the same query) | sql_ast.py (`tie_count_query`), c11 (`_c11_tie_note`), c13 | tests/test_chat_ui_audit_more_2026_10_29.py: `test_e9_…` — Needs live check |
| F-7 | Fixed — shared years first; the others "FY 2017-18 (PMAY-G only)"; the card says which years both hold | c06 `_year_clarification` | tests/test_chat_ui_audit_more_2026_10_29.py: `test_f7_…` |
| F-8 | Fixed — "FY 2027-28 has no data yet"; the chips put each held year in place of the bad one ("FY 2025-26 (latest) with FY 2024-25") | c06 `_year_out_of_range_clarification` | tests/test_chat_ui_audit_more_2026_10_29.py: `test_f8_…` |
| K-6 | Fixed (user decision) — Edit / Regenerate send `keep_turns`; the server deletes the replaced turns (audit trail kept) and restores the context saved before them; idempotent | routers/query.py (`keep_turns`, `_replace_turns`), conversation_store.py (`truncate_turns`, `_context_before`), App.jsx, api.js | tests/test_chat_ui_audit_more_2026_10_29.py: `test_truncate_…`, `test_keep_turns_…` |
| K-16 | Fixed (user decision) — "Question language — answers are in English" | LanguageSwitcher.jsx, slashCommands.js | browser check |
| K-18 | Fixed — chip taps are sent as English (already the app's text) | App.jsx (`englishRef`) | browser check |
| K-24 | Fixed — the officer's own words are saved and titled; the translation stays in `rewritten_question` ("Understood as") | routers/query.py | tests/test_chat_ui_audit_more_2026_10_29.py: `test_k24_…` |
| K-28 | Fixed — active and archived chats fetched separately | api.js `listHistory` | browser check |
| K-34 | Fixed — tables read as their cells, rule lines dropped, long answers spoken in pieces of ~220 characters | text.js (`speechText`, `speechChunks`), App.jsx | frontend/tests/audit.test.js: `K-34 …` |
| K-35 | Fixed — a figure before ". " / ", " (or at the end) is bolded | text.js `figureSpans` | frontend/tests/audit.test.js: `K-35 …` |
| K-36 | Fixed — rows without a closing pipe, rows with no leading pipe inside a table, escaped pipes; rows padded / extra cells kept | Markdown.jsx | tests/test_chat_ui_audit_more_2026_10_29.py: `test_k36_…` |
| X-4 | Fixed (user decision) — Line offered only when the x-axis is a period; an existing test updated with approval | analytics.js, Messages.jsx (`periodAxis`) | frontend/tests/charts.test.js (updated), frontend/tests/audit.test.js: `X-4 …` |
| X-10 | Fixed — tokens added once per animation frame; BotMessage / TextMessage memoised (one stable onEdit) | App.jsx, Messages.jsx | browser check |
| X-11 | Fixed — Inter and JetBrains Mono bundled (@fontsource 5.3.0, latin subset); Google Fonts links removed | package.json, main.jsx (chat, admin), index.html, admin.html | vite build; browser check offline |
| X-16 | Fixed (user decision: light-only) — `color-scheme: light` on both apps and `<meta name="color-scheme">` | chat.css, admin.css, index.html, admin.html | browser check |
