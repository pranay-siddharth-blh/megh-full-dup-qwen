## 0. Re-verify (done, recorded here per this repo's process)

- [x] 0.1 Re-counted the "which measure" / ambiguous-vocabulary category
      condition-by-condition (not just header counts) across all four
      schemes: MGNREGA 9, PMAY-G 11, Focus Plus 10 ("terms that look
      answerable but mean several things"), CM Elevate 10 (literal
      "6. WHICH MEASURE" section) = 40 nominal, 31 unique names after
      shared-name savings.
- [x] 0.2 Read `_needs_topn_clarification`/`_needs_scope_clarification`/
      etc. directly — confirmed none of these 31 conditions collide with
      what they check (topn asks "how many", these ask "ranked/trended
      by WHAT measure" — a distinct, later question in the same turn).
- [x] 0.3 Confirmed `vague_qualifier`'s `{value}` placeholder cannot be
      filled by the current `(question, resolved) -> bool` matcher
      contract — no mechanism to pass the matched term back for
      interpolation. Excluded, all 4 schemes (see design.md).

## 1. Matcher authoring — the "which measure" category

- [x] 1.1 Authored 27 unique matcher functions (33 nominal instances)
      in `app/clarification_engine.py`, appended to the existing
      `_MATCHERS` registry.
      **Three additional exclusions found during authoring, beyond
      `vague_qualifier`**: `ambiguous_expenditure_component` (MGNREGA),
      `sanctioned_reading_unclear` (PMAY-G), `amount_reading_unclear`
      (Focus Plus) each key on that scheme's single flagship default
      query term ("expenditure", "sanctioned", "amount"). Direct
      evidence: this session's own Phase 1 code comment on
      `_TARGET_ALLOCATION_BUDGET` already states "bare 'sanctioned' is
      NOT matched — 'houses sanctioned' is a legitimate, answerable
      PMAY-G metric." Firing on every bare mention would demand a
      clarification on the most common query shape in three of the four
      schemes. Recorded in design.md's Findings, not silently dropped.
      Effective authored surface: 30 nominal / 27 unique, not 33/31 as
      design.md's original recommendation stated before this correction
      (design.md was updated in place to reflect this before code was
      written).
- [x] 1.2 Documented shared-name side effects: the four intentionally-
      shared names (`missing_metric_for_ranking`, `missing_metric_for_
      trend`, `ambiguous_count_subject`, `rate_vs_count_unclear`) use a
      conservative, scheme-agnostic union heuristic (broad metric/
      subject-noun list) since a matcher does not know which scheme
      invoked it. **Found during authoring, not anticipated in design**:
      two more names (`share_denominator_missing`, `ambiguous_average_
      denominator`), designed as CM-Elevate-unique, turned out to also
      be authored (correctly, with their own scheme-appropriate wording)
      in MGNREGA/PMAY-G/Focus Plus's own "shape of the answer" sections
      — outside this phase's stated "which measure" scope. Fixed by
      widening both matchers' "already-qualified" regex to the union of
      all four schemes' valid denominator phrasings (e.g. "per
      household"/"state total" for MGNREGA, not just CM Elevate's own
      four words) — verified by a dedicated negative-case test (task
      2.1) proving each scheme's own valid phrasing does NOT false-fire.
- [x] 1.3 **Real regression found and fixed during testing, not before**:
      the initial `beneficiary_reading_unclear` (Focus Plus) matcher
      fired on any bare mention of "beneficiary", which shadowed
      Phase 1's `below_village_geography_requested` for a geography
      question that happens to mention "beneficiary" incidentally
      ("Which ward is this beneficiary from?"). Narrowed to require an
      aggregate/count framing ("how many beneficiaries", "beneficiary
      count") — re-ran the full suite after the fix to confirm the
      Phase 1 test this had broken passes again.
- [x] 1.4 **Two ordering conflicts found and fixed during testing**:
      (a) `ambiguous_count_subject`'s subject-noun list was missing
      "applicants"/"farmers", causing it to incorrectly shadow CM
      Elevate's `applicant_type_scope_unclear` and Focus Plus's
      `farmers_vs_beneficiaries` for questions naming those subjects —
      fixed by extending the noun list. (b) The shared `missing_metric_
      for_ranking` shadowed CM Elevate's more specific `biggest_scheme_
      ambiguous` for "biggest scheme" phrasing (both fire on "biggest"
      as a ranking cue) — fixed by having the shared matcher explicitly
      defer when the more specific condition's own pattern matches,
      same technique as Phase 1's CM Elevate money/time ordering fixes.

## 2. Tests

- [x] 2.1 Extended `tests/test_clarification_engine.py`: section 7 (one
      positive case per new condition, asserting the scheme's own
      question text), section 8 (explicit tests for the share_
      denominator_missing/ambiguous_average_denominator side effect
      across all 4 schemes, PLUS negative cases proving each scheme's
      own already-qualified phrasing does not false-fire — this is the
      test that caught finding 1.2's precision bug), section 9
      (confirms all four deliberate exclusions have no matcher entry,
      and that each scheme's flagship-default-term question still
      answers without a clarification).
- [x] 2.2 Ran the extended suite plus the full regression sweep:
      `tests/test_clarification_engine.py` exit 0, 256 `PASS` lines
      (up from 177 before this phase), `ALL CLARIFICATION-ENGINE CHECKS
      PASSED`. One real regression (task 1.3) and two ordering conflicts
      (task 1.4) were found and fixed via this run before reaching a
      clean pass — not assumed correct on first write.

## 3. Documentation

- [x] 3.1 No `docs/baseline-audit.md` row change needed — Phase 1's row
      38 update already covers the mechanism generally; this phase is
      additive matcher coverage under the same mechanism, not a new
      finding about it.

## 4. Regression + report

- [x] 4.1 Full regression sweep, all 22 files under `tests/` matching
      `test_*.py` (excluding `smoke_restructure.py`) — every file exit
      0, zero FAILED markers.
- [x] 4.2 `git diff --stat` / `git status` confirms only
      `app/clarification_engine.py` and `tests/test_clarification_
      engine.py` changed by this task (both untracked new files;
      `app/db.py`/`app/appdb.py` show pre-existing diffs that predate
      this session, confirmed unrelated by inspection; `app/auth.py`/
      `app/deps.py` fully untouched).
- [x] 4.3 Reported to the human below. Deviations from design.md's
      original recommendation: 3 additional exclusions found during
      authoring (flagship-default-term risk), 1 real regression and 2
      ordering conflicts found and fixed during testing — all recorded
      with reasons above, not silent. Same AUTHORED-PENDING-SME-REVIEW
      caveat as Phase 1 applies to everything wired here. **Not
      committed** — awaiting the human's review and commit per this
      repo's standing process.
