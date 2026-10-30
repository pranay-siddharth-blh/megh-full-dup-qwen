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
12. **"pending"** — superseded on 2026-10-30 by the user's rule (D-B1-CME-01): pending = `data_verified = 'Valid'`
    AND `current_file_status` forward or sendback (`LOWER(...) = 'forward' OR LIKE 'sendback%'`; resubmit out) AND
    `scheme_specific ->> 'file_status' IN ('Pending', 'Send Back')` (7,338 statewide on 2026-10-30); On Hold is not pending. The code is gated on the chatbot's role being able to
    read `scheme_specific` (locked since 2026-10-16; grant requested, KI-624). Until the grant the bot keeps the
    2026-10-26 behaviour (status not recorded; recorded figures given) and the rows below stand as run. Re-pin
    when the grant lands: C01-018 levels 0/1/2/3/4 = 3 / 7,025 / 309 / 0 / 1 (the rule AND the level); C01-019
    SEED 3,146, Piggery 2,430, Poultry 470; C01-020 Ri Bhoi 2,024, West Garo Hills 1,619, East Khasi Hills 986;
    C01-021 = 13, 6, 0, 50, 1, 5, 0, 0, 0, 2, 0, 0 in row order; C01-028 (not recorded) 289 of 306.
13. **CM Elevate × FY / date.** A financial-year or date word pins **CM Elevate Legacy** (dataset choice, user
    decision 2026-10-22, `_cm_elevate_dataset_choice`): only Legacy holds years. So for categories 4, 6, 7-FY, 8 the
    designed outcomes are (a) the no-time-dimension refusal or (b) an answer from CM Elevate Legacy that says so
    (schemes = ["CM Elevate Legacy"] and the word "Legacy" in the answer). Legacy's figures are the CM Elevate
    Legacy sheet's to verify and are not re-verified here.
14. **DB connections.** The app's role (`megh_chatbot`) has a connection cap shared with the parallel Focus Legacy
    session; "too many connections" is treated as transient (runner retries 3×, then once more at the end).
15. **Smoke run** (17 tests, run tag `smoke`) kept in results.csv; superseded by later rows for the same IDs.
16. **Reduced plan (user, ~02:35).** Deadline 7 AM: matrix cut from 18,381 to 4,837 (gen_matrix.py REDUCED block;
    `--full` regenerates the old one, kept as test_matrix_full_v1.csv / matrix_counts_full_v1.txt). Kept IDs are
    unchanged, so results already in results.csv stand. Zero-record villages: 100 spread over the 5,194 (the plan
    says "edge cases", not "every"). Named entities: CM Elevate exposes none, so 5 refusals rather than 20.

## Changes to pass rules / expected values made after seeing a result (each listed, with the reason)
All are in tests/live_cme_uat.py (the pre-worktree harness; uat/run_matrix.py inherited the same rules).
- R1 **Unrequested grand totals removed** (OFF-004, 005, 011; H-D>B, H-B>V, H-DIM, H-REG-ALL). The sheet's
  expected results ask for the breakdown only; every breakdown figure is still checked. Combined totals the sheet
  DOES ask for (OFF-009, 010, 014, 029: "and their combined total") are still required.
- R2 **OFF-018 expected value: `current_level = N`** instead of `On Hold AND current_level = N`. The code and the
  team define "pending at level N" as the applications whose file sits at level N (KI-070, KI-422); my first
  expectation was my own reading, not the app's documented one.
- R3 **Village lists exclude `entity_type = 'Unresolved'`** (OFF-026, H-B>V): the documented rule ("exclude
  'Unresolved' only for village counts"); my first truth excluded only the literal name 'Unresolved'.
- R4 **Shared-name villages (OFF-003 shared, C03 alone): each twin's count expected**, not one village: the J-10
  design answers up to three same-name villages in different blocks each with its block.
- R5 **Tura Municipal Board = both stored spellings (105)**: one place to a user.
- R6 **Generic chip taps**: "CM Elevate" on "which scheme?", "complete list" on "how many results?" — what a user
  does with the designed pause (decision 7). The bot still has to answer correctly after the tap.
- R7 **no_time accepts a labelled CM Elevate Legacy answer** (decision 13) — added after C04-FY-2024-25 was answered
  from Legacy. Reason: the dataset-choice rule (user decision 2026-10-22) routes any financial-year question to
  Legacy, the only CM Elevate dataset with years; the answer names Legacy.
- R8 **Region questions tap only a "region" chip** (never a district chip), so a pause that offers districts fails.
No other rule was loosened; numbers are always compared exactly (Indian or plain grouping).
17. **C03 "alone" tests tap "village"** (generator fix, 02:59): a shared village name that is also a block /
    constituency (MAWHATI) pauses "block, constituency or village?" by design; decision 7 already says a pause is
    answered with the chip the test means (here the village). The generator had left `pick` empty for this group.
    Only the `pick` column changed; IDs and expected values are identical.
18. **C12 follow-up turn 3 is disputed (D2)**, not fixed: see disputed.md.
19. **Village tests tap the village chip first** (runner/generator fix, 03:31): `pick` entries may name several parts
    ("village&batabari" = a chip whose label holds both). C02 / C03-with-block / C14 picks are now
    ["village&<block>", "village", "<block>", "<district>"]; before, "<block>" came first and, for a village named like
    its block (BATABARI, RERAPARA), tapped the BLOCK chip — the opposite of what the test means (decision 7). Only the
    `pick` column changed (2,401 rows); IDs and expected values are identical.
20. **Final runs.** Code frozen at d348482; full re-run `final4` 04:51-06:05: 4,837/4,837 executed, 0 errors,
    0 DB write attempts. Earlier `final`/`final2`/`final3` were stopped and restarted after a fix each (no partial
    run is counted). Two CM Elevate failures of final4 (O1, O2) were then fixed in 8b8f2f0 and verified with a
    regression pass of the affected categories (C01 + C03, run `regress5`) and the full unit suite (5,131 passed).
    The other 14 categories' final results are from final4 on d348482; 8b8f2f0 changes only the CM Elevate SQL
    pass (verification split, twin LIMIT) and one answer guarantee, which those categories also go through — a
    further full re-run on 8b8f2f0 was not possible before 7 AM.
21. **Last fix** c206e1f (district / block literal beside a list of village codes, C03-ALONE-mawlieh, found by the
    C01 + C03 regression on 8b8f2f0): C03 re-run in full on c206e1f (`regress6`, 192/192); full unit suite re-run.
    Final code = c206e1f. Results per category: C01 from `regress5` (8b8f2f0), C03 from `regress6` (c206e1f), all
    other categories from `final4` (d348482).

## 22. User instruction 2026-10-30 ~09:35 — "do whatever you want … fix all the issues … make UAT 100 percent"
Read as authority to settle D1–D4 and to apply the shared-code fixes N1/N3/N4 ON THIS BRANCH ONLY (main, DB,
port 8401 and the Focus Legacy worktree still untouched). Each choice and why:
- **D1 → code (882879d, CM Elevate only).** D-090 (2026-10-29) is the later user decision and says application
  words mean the applications dataset unless MONEY words are present; a year is not money. So "applications /
  applicants / applied" + a financial year + no money word stays on CM Elevate (applications) and gets the
  no-date reply. A year with any money word, or "Legacy", or a Legacy thread, still goes to Legacy (probed:
  "total CM Elevate disbursement in FY 2024-25" -> ₹59.82 crore from Legacy). Test expectation unchanged.
- **D2 → test expectation corrected (gen_matrix.py).** Turn 3 ("their file status", "break the applicants down")
  follows turn 2 ("how many of them are on hold?"); the bot keeps the on-hold group and its figures match SQL
  exactly (disputed.md D2). The test's all-applicants reading was the weaker one; T3 now expects
  `data_verified = 'On Hold'` figures. Only the 20 C12 rows changed.
- **D3 → pass rule R9 (run_matrix.py NAME_OK).** "does not contain" / "isn't part of" are refusals; the reply
  holds no personal data (no such column exists). Added to the refusal phrases. This widens a rule after
  seeing a result — listed here as required.
- **D4 → generator (gen_matrix.py).** A zero-record village whose exact name is shared with another village in
  the SAME block cannot be singled out in words, so it is no longer drawn as a C14 zero test. 96 C14-ZERO picks
  shifted (spread over a 5,102 list instead of 5,194); TOTAL stays 4,837.
- **N1, N4 → shared code (7f9d8f7, app/spelling.py + entity_resolver.is_stored_village_name).** Exact ward /
  village names are left whole by the spelling pre-pass; a stored one-word village name the index leaves out
  (CENTRE) is not "corrected" by sound; "account" / "trace" are never typos.
- **N3 → shared code (4bf022f, app/guardrails.py).** Account / Aadhaar / IFSC / PAN / passport NUMBERS of
  applicants or beneficiaries are refused as personal records. Probed: "How many bank accounts were opened
  under PMJDY?" and "Which bank account receives the subsidy?" are not refused.
- These shared changes reach every scheme: the full unit suite is re-run on them (result in sheet_summary /
  final report). They are on branch uat-cm-elevate-exhaustive only; merging is the user's call.
23. **Sheet cases OFF-008 and OFF-030 put back** (user 2026-10-30 ~10:45: "how many [sheet use cases] are working").
    The 02:35 reduced plan kept only the village applicant count (OFF-003) from C02, so OFF-008 (programme x
    village) and OFF-030 (status-wise counts for a programme in a village) had no test. Added: each on the first
    village of every block. The matrix total grows accordingly; matrix_counts.txt regenerated.
24. **11:15 — finish in 15–20 minutes, crucial tests only, no loosening.** `final5` (full re-run on 882879d…1f1ab9c)
    was stopped at 2,076 / 4,837 (2,075 pass; the 1 fail was East Shillong, fixed by 176fe54 / 2952b14). Instead of
    the remaining ~3,000 (≈90 min), a risk-based set of 555 runs on the final code (`final6b`): every constituency
    test (resolver change), the new OFF-008 / OFF-030 tests, a geographic spread of 100 villages + 20 wards +
    CENTRE VILLAGE, FY questions at every level (region / district / block / constituency), all 20 follow-up chats,
    50 zero / invalid places, the 5 personal-data cases and the 20 rewordings. Then `final7` re-runs the 221
    constituency tests on 2952b14 (the supplement refactor). Tests not in these runs keep their latest earlier
    result (final4 / regress5 / regress6 / final5); the report's Summary names the run of every row.
    Shared-code change in 2952b14 (entity_resolver `<dim>_supplement`): full unit suite + 14 scripts re-run.
25. **12:10 — stale rows found by the tally.** With the latest row per test, 336 C06-CON (constituency x FY) tests
    still showed final4's Legacy pause: `final5` was stopped (decision 24) before its C06 constituency block, and
    `final6b` sampled only 12 of them. Likewise 4 ward villages (C02-CNT-3358 / 71065 / 71066 / 278328) had only
    pre-fix rows, and 67 C14-ZERO villages added by the D4 regeneration had never run. `final10` re-runs exactly
    these 407 on the final code (2edd11a). No result is reported from a run older than the fix it depends on:
    the report's "Run of each result" table and every row's Run column show where each figure comes from.
26. **12:15 — another session is editing this worktree.** `git status` showed uncommitted changes not made here
    (app/pipeline/schemes/cm_elevate.py at 12:08, a new tests/test_cme_pending_funnel_2026_10_30.py at 12:09,
    app/data_facts.py, app/schema_context.py, app/schema_introspect.py, c11, three CM Elevate YAMLs, docs) — the
    "pending funnel" work. Not touched, not committed, not reverted. Consequences handled:
    - the unit suite run at 12:04–12:08 in this folder (32 failures, all in that in-progress work) is NOT the
      figure reported; the suite is re-run in a clean detached checkout of the final commit
      (`../meghoneai-uat-cm-elevate-clean`, nothing uncommitted);
    - `final10` (12:09–12:19, 406/407 on the 407 stale rows) may have imported the foreign cm_elevate.py, so the
      same 407 are re-run there as `final11` on commit 9253603 and merged into results.csv (uat/merge_results.py);
      `final11` rows are the ones reported for those tests;
    - every other reported row (final4 / final5 / final6b / final8 / final9) ran before 12:08.
    One more fix on the way: C02-CNT-278328 "POMLAKRAI RNGI SHYLLONG" (exact village name ending on a word the
    pre-pass corrects) — 9253603, spelling.py, shared. Commits only ever `git add` this session's own files.
27. **12:31 — final tally.** results.csv holds a result for every one of the 4,959 matrix IDs (= matrix_counts.txt
    TOTAL): 4,959 Pass, 0 Fail, 0 Error, 0 disputed, 0 needs-review; all 30 sheet cases working; db_write_attempts
    0 in every run. Final commit 9253603. Unit suite on it (clean checkout): 5,131 passed, 0 failed, 14/14 scripts.
    Run of each row: final11 407 (clean checkout, 9253603), final9 1 (2edd11a), final8 237 (67a3ac0), final6b 317
    (176fe54), final5 1,820 (1f1ab9c), final4 2,177 (d348482, 04:51–06:05). The final4 rows were not re-run after
    the later commits; `final12` re-runs exactly those 2,177 on the clean checkout as a confirmation (decision 24
    chose the crucial set for the 11:15 deadline).
28. **13:06 — confirmation run done.** `final12` (clean checkout, commit 9253603): 2,177 / 2,177 pass, 0 errors, 0 DB
    writes. Every one of the 4,959 results now comes from a run on 1f1ab9c or later (final5 1,820; final6b 317;
    final8 237; final9 1; final11 407; final12 2,177); no row older than the fixes it depends on remains.
