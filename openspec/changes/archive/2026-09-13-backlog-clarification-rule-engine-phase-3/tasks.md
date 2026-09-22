## 0. Re-verify (done, recorded here per this repo's process)

- [x] 0.1 Re-ran both prior phases' test suites directly rather than
      trusting their `tasks.md` claims: `tests/test_clarification_engine.py`
      and `tests/test_clarification_gate.py` both exit 0. Confirmed
      `app/clarification_engine.py` and its two test files are still
      untracked in git.
- [x] 0.2 Counted every scheme's unwired conditions programmatically
      (loaded `_load_scheme_rules()` per scheme, diffed against
      `ce._MATCHERS` and `ce._COLLISION_CONDITIONS`), not from
      section-header line counts: 341 total, 120 wired, 5 collision-
      covered, 216 genuinely unwired. See proposal.md's table.
- [x] 0.3 Read every existing hardcoded predicate in `app/pipeline.py`
      (`_scheme_clarification`, `_scheme_comparison_clarification`,
      `_unsupported_scheme_clarification`, `_bank_clarification`,
      `_admin_expenditure_clarification`, `_women_share_clarification`,
      `_needs_topn_clarification`, `_needs_scope_clarification`,
      `_region_clarification`, `_needs_year_clarification`, `_needs_
      tranche_clarification`) directly, not from name similarity.
      **Found**: `women_share_requested` is already covered by
      `_women_share_clarification` but missing from
      `_COLLISION_CONDITIONS` — a real gap, harmless today only because no
      matcher for that name exists yet. **Found**: `_needs_year_
      clarification` / `_needs_tranche_clarification` likely overlap
      several "time" section conditions and Focus Plus's "batch duality"
      section, but the condition-by-condition cross-check needed to be
      sure is not done — both categories excluded from this phase's scope
      for that reason. See design.md's "Why this category" section.
- [x] 0.4 Confirmed all 25 conditions in this phase's proposed scope are
      scheme-unique (no name shared verbatim across more than one
      scheme's YAML) — no scheme-agnostic heuristic needed, unlike
      Phases 1-2's shared names.
- [x] 0.5 Confirmed CM Elevate's `gender_breakdown_requested` (in the same
      section as this phase's CM Elevate scope) carries its own YAML note
      "NOT A REFUSAL — this is answerable" — excluded from scope, same
      treatment as Phase 1's `villages_without_houses_requested`.

## 1. Decision gate — human approval required before any code

- [x] 1.1 **Approve or reject `design.md`'s recommendation**: wire the 25
      nominal "measures/fields that exist but must not be reported as
      asked" conditions across all four schemes (see proposal.md's table),
      deferring "time", Focus Plus's "batch duality", and every other
      remaining category to future proposals. Record the decision and who
      made it here.
      **Approved as scoped** — harshavardhan.p@simaxsystems.com, 2026-09-13
      ("any features pending 5.1, 5.2 and 5.3 complete it here").
- [x] 1.2 **Approve the `women_share_requested` collision-set correction**
      (add it to `ce._COLLISION_CONDITIONS`, do not wire a matcher for it)
      as part of this phase. Record here.
      **Approved** — harshavardhan.p@simaxsystems.com, 2026-09-13, same
      instruction as 1.1.
- [x] 1.3 **Assign a reviewer for the new matcher regexes** (same question
      Phase 1's task 1.2 and Phase 2 inherited) — same SME pool that
      authored the YAML, or a different one. Record here.
      **Decision: same SME pool that authored the YAML**, matching Phase
      1/2's own decision — no separate instruction given, carried forward
      as the standing default for this module.

## 2. Matcher authoring — the "measures/fields that exist" category

- [x] 2.1 Added `women_share_requested` to `ce._COLLISION_CONDITIONS` in
      `app/clarification_engine.py`, with a comment explaining the gap
      found in task 0.3.
- [x] 2.2 Authored matcher functions for 20 of the 25 nominal conditions
      (MGNREGA 3, PMAY-G 7, Focus Plus 2, CM Elevate 8), appended to the
      existing `_MATCHERS` registry.
      **Five additional exclusions found during authoring, beyond the
      scope already fixed in proposal.md** — same "found during authoring,
      not before" standard as every prior phase:
      - PMAY-G `fuzzy_village_precision_warning`: its real trigger is "a
        village-level breakdown was requested," not a specific misreading
        phrase — one of PMAY-G's single most common legitimate query
        shapes, same over-fire risk class Phase 2 already rejected for a
        different condition.
      - PMAY-G `singleton_category_focus`: any phrasing that would trigger
        it also contains "woman," which the already-shipped, earlier-in-
        file-order Phase 1 `gender_column_requested` matches first —
        structurally unreachable without editing already-archived Phase 1
        code, out of scope for a purely-additive phase.
      - Focus Plus `standard_payment_reading_unclear` and `average_payment_
        requested`: both ask about "the payment" with no tranche named —
        already trips `app/pipeline.py`'s `_needs_tranche_clarification`
        (its `_METRIC_OR_BREAKDOWN_CUE` includes `payments?`) before this
        engine would ever see a resolved state specific enough to add
        anything. Same "batch duality" adjacency risk design.md already
        excluded a whole section for, found here to extend to two "money"
        section conditions too.
      - CM Elevate `application_count_offered_as_money_proxy`: its own
        YAML note calls it "a backstop for any_money_amount_requested" for
        when a money intent "survives the earlier gates" — by definition a
        phrasing the already-broad `any_money_amount_requested` regex does
        NOT catch, and no precise trigger for "money intent, unspecified
        form" could be authored with reasonable confidence.
      **Effective wired count: 20, not 25** — recorded here, not shipped
      silently. See `app/clarification_engine.py`'s Phase 3 section
      comment for the full trail.
      **One real ordering conflict found and fixed during testing, not
      before**: the new `completion_rate_across_mixed_years` (PMAY-G) sits
      earlier in `pmay_classification_rules.yaml`'s file order than the
      already-shipped Phase 2 `rate_vs_count_unclear`, and both match the
      exact example question Phase 2's own test used ("What is the
      completion rate for PMAY-G?"). Per first-match-wins file order this
      is the SME-authored YAML's own intent, not a bug — fixed by changing
      Phase 2's test example to a different bare "rate" noun ("success
      rate") that still exercises `rate_vs_count_unclear`'s own behavior
      without touching the unrelated new condition. `_needs_year_
      clarification` / `_needs_tranche_clarification` overlap risk (task
      0.3) was re-checked per matcher via both direct inspection and live
      execution with realistic `resolved` state (e.g. `{"year_key":
      "2023-24"}`) for the two conditions that read `resolved.get(
      "year_key")` (`women_metric_in_2025_26`, `completion_rate_across_
      mixed_years`) — both correctly stand down once a year is actually
      resolved.
- [x] 2.3 Extended `tests/test_clarification_engine.py`: section 10 (one
      positive case per new condition, asserting the scheme's own question
      text), section 11 (resolved-state sensitivity for the two year-aware
      conditions, plus legitimate-reading negative cases per scheme),
      section 12 (the `women_share_requested` collision-set correction,
      asserted directly — not just documented), section 13 (all five
      Phase 3 deliberate exclusions above, plus `gender_breakdown_
      requested`, confirmed to have no matcher entry). Also fixed two
      assertions left stale by adding a third phase: section 1's Phase-1-
      only coverage check now also excludes `_PHASE3_NAMES` (it previously
      excluded only `_PHASE2_NAMES`), and section 7's hardcoded "total
      registry size = 93" check was loosened to `>= 93` since the exact
      total is now re-asserted, phase-3-inclusive, in section 10.
- [x] 2.4 Ran the extended suite: exit 0, **315 `PASS` lines** (up from
      256 before this phase), `ALL CLARIFICATION-ENGINE CHECKS PASSED`.

## 3. Regression + report

- [x] 3.1 Full regression sweep, all 28 files under `tests/` matching
      `test_*.py` (excluding `smoke_restructure.py`) — every file exit 0,
      zero FAILED markers.
- [x] 3.2 `git status` confirms only `app/clarification_engine.py` and
      `tests/test_clarification_engine.py` changed by this task group
      (both remain untracked new files, as before this phase).
- [x] 3.3 Reported to the human below. Deviations from proposal.md's exact
      scope: 20 unique matchers wired, not 25 (five additional exclusions
      found during authoring, see task 2.2); one test-only fix to a Phase
      2 example question that a new, correctly-earlier-ordered Phase 3
      condition now also matches. All recorded with reasons, not silent.
      **Not committed** — awaiting the human's review and commit per this
      repo's standing process.

## 4. Explicitly deferred (separate future approval, not part of this phase)

- "Time" category, all four schemes — needs the `_needs_year_
  clarification` / `_needs_tranche_clarification` cross-check design.md
  declines to do here.
- Focus Plus's "the batch duality" section — same cross-check dependency.
- "Geography", "identifiers and values", "shape of the answer", "data
  quality", CM Elevate's "WHICH SCHEME" and "THE REQUIREMENT WORKBOOK
  DESCRIBES A DIFFERENT DATASET" sections, and CM Elevate's remaining
  "cannot answer" subsections (identity/personal fields, attributes not
  collected, scope of the data, cross-scheme).
- Migrating the ~7 pre-existing hardcoded predicates onto the matcher
  registry.
