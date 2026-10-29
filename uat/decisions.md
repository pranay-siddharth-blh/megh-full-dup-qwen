# Decisions log (CM Elevate exhaustive UAT)

1. **Step 0 split.** The main folder holds two sessions' work; the CM Elevate hunks were applied to `Main` in the
   worktree and the patch was produced from there (`mixed_files.md`). Two hunks were mixed inside one diff hunk
   (c12); only the CM Elevate half was taken.
2. **Dependency.** The CM Elevate twin rewrite used `sql_ast.add_group_columns` (Focus Legacy's, uncommitted). The
   worktree carries a local copy (`_c10_group_by_cols`) so nothing of Focus Legacy is needed.
3. **`.env`.** The worktree has no `.env` (git-ignored). It was COPIED from the main folder unchanged (untracked,
   ignored). Nothing in the main `.env` changed. No config / dependency files changed.
4. **Python.** The main folder's `.venv` interpreter is used read-only with the worktree as the working directory
   (the app is imported from the worktree). No packages installed anywhere.
5. **How questions are run.** In process, through the router's own path (`tests/conversation_harness`
   InProcessDriver: conversation layer -> LangGraph pipeline -> restyle), the same code the server runs. No server
   is started, so nothing listens on any port (8401 untouched; 8412 not needed).
6. **Expected values** are computed by read-only SELECTs at matrix generation and stored in test_matrix.csv; the
   sheet's expected results are rules in words, never numbers, and are not changed.
7. **Clarification pauses.** A pause is answered by tapping the chip a user would (the level / village / district
   the test means; "CM Elevate" on "which scheme?"; "complete list" on "how many results?"). A test whose answer
   needs a chip the bot does not offer fails.
8. **No time dimension.** CM Elevate has no FY, month or date (0 distinct FYs in the DB). Categories 4 (FY / month /
   year-vs-year), 6 (place × FY), 8 (place × date range) and the "dimension × FY" part of 7 are therefore tested as
   the REFUSAL they must produce ("CM Elevate has no date field …", never a number). FYs used in the questions: the
   union of the other schemes' years, 2017-18 … 2025-26.
9. **No named entities.** v_cm_elevate exposes no beneficiary / unit names (request_id only): category 11 is a set
   of name / personal-detail questions that must not return a person's data.
10. **"Every place × dimension value"** (cat 7) uses the place levels region, district, block, constituency × every
    value of the 7 dimensions. Village × every dimension value (2,170 × 37) is NOT generated: category 2 already
    asks every village every metric the sheet asks of a village (count, programme count, status-wise).
11. **Master-list villages with no CM Elevate data** (cat 2 / 14): asked with their block ("<village> village of
    <block> block") so a shared name does not pause; expected 0 stated plainly, no "data not available" wording.
    The 72 `Unresolved` placeholder rows of dim_geography are not villages and are excluded.
12. **"pending"** follows the ingestion team's 2026-10-26 ruling (KI-422): the bot must say the status is not
    recorded and give the recorded figure (on hold; or applications at a level for "pending at level N").
13. **CM Elevate × FY / date.** A financial-year or date word pins **CM Elevate Legacy** (dataset choice, user
    decision 2026-10-22, `_cm_elevate_dataset_choice`): only Legacy holds years. So for categories 4, 6, 7-FY, 8 the
    designed outcomes are (a) the no-time-dimension refusal or (b) an answer from CM Elevate Legacy that says so
    (schemes = ["CM Elevate Legacy"] and the word "Legacy" in the answer). Legacy's figures are the CM Elevate
    Legacy sheet's to verify and are not re-verified here.
14. **DB connections.** The app's role (`megh_chatbot`) has a connection cap shared with the parallel Focus Legacy
    session; "too many connections" is treated as transient (runner retries 3×, then once more at the end).
15. **Smoke run** (17 tests, run tag `smoke`) kept in results.csv; superseded by later rows for the same IDs.
