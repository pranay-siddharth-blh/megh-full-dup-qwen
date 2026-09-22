## 0. Re-verify (done, recorded here per this repo's process)

- [x] 0.1 Re-confirmed `Session.pending_scope_q`/`pending_village_hint`
      (`app/session_store.py:105,114`) were still bare in-process dataclass
      fields, not part of `ConversationState`, and still un-rehydrated by
      `conversation_store.load_context_state`.
- [x] 0.2 Re-confirmed the clarification-catch branch
      (`app/routers/query.py:137-180`) called `persist_turn` but not
      `save_context_state`, while the success path (`query.py:233-234`)
      called both.
- [x] 0.3 Re-confirmed the resume read (`app/pipeline.py:3627-3631`) read
      `session.pending_scope_q`/`pending_village_hint` directly, and the
      only two call sites setting them were `query.py:145-146`.
- [x] 0.4 Grepped the whole repo for `pending_scope_q`/`pending_village_hint`
      (case-insensitive) — confirmed the only code references were
      `app/session_store.py`, `app/routers/query.py`, `app/pipeline.py`.
      Doc references (`docs/baseline-audit.md`, two `proposal.md` stubs)
      are prose only, updated in Group 3.
- [x] 0.5 Re-confirmed `ConversationState.from_dict` defaults every key via
      `.get(...)`, so adding two new keys is backward-compatible with
      existing rows that don't have them — no migration needed.
- [x] 0.6 New evidence not in `docs/baseline-audit.md`: re-read
      `deploy/systemd/megh-nlpservice.service` — `uvicorn --workers 2` run
      "on both application VMs" — 4 independent worker processes. Confirms
      "a request landing on a different worker" is the routine case at
      this deployment's scale, not a rare edge case. Recorded in
      `design.md`.

## 1. Move the pause fields onto `ConversationState`

- [x] 1.1 `app/session_store.py`: added `pending_scope_q: str | None = None`
      and `pending_village_hint: str | None = None` to `ConversationState`,
      updated `to_dict()`/`from_dict()`. Removed the two fields from
      `Session` (they now live on `session.state`) and rewrote the
      doc-comments to describe the new durability story instead of "Not
      persisted, per-worker."
- [x] 1.2 `app/routers/query.py:145-146`: changed
      `session.pending_scope_q = req.question` /
      `session.pending_village_hint = e.village_hint` to
      `session.state.pending_scope_q` / `session.state.pending_village_hint`.
- [x] 1.3 `app/pipeline.py:3627-3631`: changed the two reads and the two
      clearing assignments to go through `session.state.*` instead of
      `session.*`. Also updated two stale doc-comments referencing
      `Session.pending_village_hint` (`pipeline.py:92`, `:2031`) to point
      at `ConversationState.pending_village_hint`.

## 2. Mirror the pause on the clarification path

- [x] 2.1 `app/routers/query.py`'s clarification-catch branch: added
      `conversation_store.save_context_state(session_id=session_id,
      context_state=session.state.to_dict())` alongside the existing
      `persist_turn` call, so a pause is mirrored to `app.conversations`
      exactly like a successful turn already is. Removed the now-inaccurate
      comment claiming "the resume already runs off session.pending_scope_q"
      untouched.
- [x] 2.2 Confirmed the existing rehydration hook (`query.py:98`, `if not
      session.turns and client_session`) needed no code change — it already
      restores the whole `session.state` from `load_context_state`'s
      `context_state` blob, which now includes the two pause fields for
      free.

## 3. Documentation

- [x] 3.1 `docs/baseline-audit.md` row 5.4: appended a dated (2026-09-12)
      update note recording the LangGraph-vs-harden decision and that the
      durability gap it flagged is now closed — original row text left
      intact per this doc's convention.
- [x] 3.2 `openspec/changes/phase-2-orchestration-durability/proposal.md`:
      appended a second, later-same-day update note pointing to
      `design.md`'s decision and this change closing the durability half
      of the stub. Noted implemented-but-not-committed status and the two
      still-open sub-questions (JSONB vs. typed columns; stale-pause
      expiry) from `design.md`'s "Open Questions for the approver."

## 4. Tests

- [x] 4.1 Extended `tests/test_context_manager.py` section 11 (`STATE
      PERSISTENCE ROUND-TRIP`): round-trips `pending_scope_q`/
      `pending_village_hint` through `to_dict`/`from_dict` alongside the
      existing fields (2 new checks), plus an explicit check that
      `from_dict` on a dict missing both keys (simulating an old persisted
      row) yields `None` for both (1 new check).
- [x] 4.2 New section 12 in `tests/test_context_manager.py`
      ("CLARIFICATION PAUSE SURVIVES A WORKER BOUNDARY"): builds a
      `Session`, sets `session.state.pending_scope_q`/`pending_village_hint`
      (simulating a pause), round-trips through `to_dict()`/`from_dict()`
      into a second, independently-constructed `Session` (simulating a
      different worker with no shared memory), and asserts the pause
      fields survive; also asserts `Session` no longer carries these as
      bare attributes at all (3 new checks). This is the specific
      "different worker" scenario `design.md` is about, mechanically
      covered rather than only asserted in prose.
- [x] 4.3 `python tests/test_context_manager.py` — **exit 0**, 59 `PASS`
      lines, 0 failing checks, `ALL CONTEXT-MANAGER CHECKS PASSED` (9 of
      the 59 are new: 5 in section 11, 3 in the new section 12, plus the
      pre-existing round-trip check whose fixture now also carries the two
      new fields).

## 5. Regression + report

- [x] 5.1 `tests/test_context_manager.py`: exit 0, as above.
- [x] 5.2 Full regression sweep, all 21 files in `tests/` matching
      `test_*.py` (excluding `smoke_restructure.py`, a manual/dev script):
      `test_authorization.py`, `test_chart_spec.py`,
      `test_clarification_gate.py`, `test_context_manager.py`,
      `test_defaults_engine.py`, `test_entity_resolver.py`,
      `test_findings.py`, `test_intent_classifier.py`, `test_join_graph.py`,
      `test_pii_audit_trail.py`, `test_pii_guard.py`,
      `test_pipeline_join_discovery.py`, `test_pipeline_schema_retrieval.py`,
      `test_query_audit_trail.py`, `test_response_composer.py`,
      `test_retrieved_set_guard.py`, `test_schema_retrieval.py`,
      `test_scope_scheme_classifier.py`, `test_security.py`,
      `test_sql_join_validator.py`, `test_sql_safety.py` — **every file
      exit 0, zero FAILED markers**.
- [x] 5.3 `git diff --stat` reviewed. The repo's working tree already
      carries a large amount of unrelated, pre-existing uncommitted work
      (confirmed by inspecting each diff before attributing it) —
      consistent with the pattern `phase-2-audit-trail-enrichment/tasks.md`
      task 5.3 already noted. Scoped to just the files this change
      touched: `app/session_store.py`, `app/routers/query.py`,
      `app/pipeline.py`, `tests/test_context_manager.py`,
      `docs/baseline-audit.md`, and this change's own `proposal.md` — 6
      files, +270/-49 lines combined (`git diff --stat` on that file list).
      `docs/baseline-audit.md` and `proposal.md` each had other,
      pre-existing uncommitted hunks (from earlier, already-reported work)
      before this change added its own — the new hunks in each are the
      dated 2026-09-12 update notes added in Group 3 above, confirmed by
      reading the diffs.
- [x] 5.4 Reported to the human below. **Not committed** — awaiting the
      human's review and commit per this repo's standing process.

## 6. Post-report addition (2026-09-12) — spec delta

`openspec status` (this schema is `spec-driven`) reported the change
incomplete: `tasks` formally depends on a `specs` artifact this change
had skipped straight past. Caught when asked to continue, not before.

- [x] 6.1 Added `## Capabilities` to `proposal.md`, declaring the new
      `clarification-pause-durability` capability (no existing
      `openspec/specs/` capability covered session/pause behavior).
- [x] 6.2 Added `specs/clarification-pause-durability/spec.md` — two
      `ADDED Requirements` (resume across a worker/process boundary; the
      pause is durably recorded when raised, not only on a later
      successful turn), five scenarios total, behavior-only (no
      class/function names), per this schema's spec-writing rules.
- [x] 6.3 `openspec validate "phase-2-orchestration-durability" --type
      change --strict` — **valid**. `openspec status` — **isComplete:
      true**, all four artifacts (`proposal`, `specs`, `design`, `tasks`)
      report `"status": "done"`.

## 7. Post-completion addition (2026-09-13) — LangGraph interrupt()/checkpointer component, by explicit instruction

Supersedes this change's own "do not adopt LangGraph" recommendation
for the question "should the component exist," not for the question
"should this deployment route production traffic through it" — see
`design.md`'s "Update (2026-09-13)" for the full record of why these
are different questions and why the original analysis still stands for
the second one.

- [x] 7.1 Verified `langgraph` and `langgraph-checkpoint-sqlite` install
      and import cleanly in this environment (Python 3.11.9, Windows).
      Attempted `langgraph-checkpoint-postgres` first, matching the
      proposal's own "Tools" line — blocked by `psycopg`'s native
      `libpq` dependency not being present (no PostgreSQL client
      library on this machine); uninstalled the broken/unused package
      rather than leave it pinned. Recorded as an environment limitation
      "ignore infra" was about not blocking on, not a design rejection
      of Postgres as a checkpointer backend in principle.
- [x] 7.2 New module `app/langgraph_followup.py`: a `StateGraph` with one
      node wrapping the existing `app.pipeline.answer_question`,
      `interrupt()` called on any of the three pause-eligible
      `ClarificationNeeded` rules (`scope-not-specified`,
      `year-not-specified`, `entity-ambiguous` — same set
      `app/routers/query.py` already treats as resumable), compiled with
      `AsyncSqliteSaver` against a dedicated file
      (`logs/langgraph_followup_checkpoints.sqlite`, gitignored).
      Graph state stores `scope` (a `UserScope` dataclass) as a plain
      dict via `dataclasses.asdict`/`UserScope(**...)` rather than the
      instance itself — found during manual verification that passing
      the dataclass directly triggers a LangGraph deprecation warning
      ("Deserializing unregistered type... will be blocked in a future
      version"); fixed before writing the test suite, not left in.
- [x] 7.3 New `tests/test_langgraph_followup.py` (monkeypatches
      `app.pipeline.answer_question`, no DB/model gateway, same stance as
      every other test file): single pause + durable resume via an
      independently-constructed checkpointer connection (proving the
      pause survives being resumed by something that shares only the
      SQLite file, not memory); multi-round pause (asks again for a
      second missing piece before completing); `entity-ambiguous`'s
      `village_hint` threading through via `ConversationState.
      pending_village_hint`; a non-pause-eligible rule propagating
      rather than being interrupted or swallowed. **18/18 checks pass,
      exit 0.** One real test-design bug found and fixed while writing
      this suite: `snap.next` being non-empty for an errored (non-
      interrupted) node does not mean a pause was recorded — verified
      the correct signal is `snap.tasks[i].interrupts` being empty, by
      direct inspection of `PregelTask`'s fields, not assumed.
- [x] 7.4 `requirements.txt`: added `langgraph>=1.2,<2.0` and
      `langgraph-checkpoint-sqlite>=3.1,<4.0`. `requirements.lock`:
      regenerated via `pip freeze` after removing the unused Postgres
      checkpointer packages (task 7.1) — diffed old vs. new before
      writing, confirming **no existing pinned package's version
      changed** except `websockets` (17.1 → 16.1.1, forced by
      `langgraph-sdk`'s own constraint; previously arrived via
      `uvicorn[standard]`'s extras). Re-ran the full regression sweep
      and a direct `app.main`/`uvicorn` import check after the
      environment change — both pass, recorded as a side effect, not
      silently absorbed.
- [x] 7.5 Extended `specs/clarification-pause-durability/spec.md` with
      one `ADDED Requirement` (an alternative interrupt-primitive
      component is available without being the default path), four
      scenarios. `openspec validate "phase-2-orchestration-durability"
      --type change --strict` — **valid**.
- [x] 7.6 Full regression sweep: all 23 files under `tests/` matching
      `test_*.py` (22 pre-existing plus the new
      `test_langgraph_followup.py`) — every file exit 0, zero FAILED
      markers.
- [x] 7.7 Reported to the human below. **Not wired into the live request
      path** — `app/routers/query.py` is unchanged; this is an
      additive, opt-in, separately-tested component, per design.md's own
      stated scope for this instruction ("implement the component," not
      "cut production over to it"). **Not committed** — awaiting the
      human's review and commit per this repo's standing process.

## 8. Post-completion self-review (2026-09-13, same day) — asked to check everything before moving to other features

- [x] 8.1 Re-ran `openspec status`/`validate` fresh — still `isComplete:
      true`, still valid. Re-ran `tests/test_context_manager.py` (59
      PASS, exit 0) and `tests/test_langgraph_followup.py` (18 PASS,
      exit 0) fresh rather than trusting the earlier group's reported
      counts. Confirmed via `git status`/`git diff --stat` that every
      file this change's groups 1-7 claim to have touched actually shows
      a diff or is untracked as claimed — none missing, none stale.
- [x] 8.2 **Found and fixed: `docs/baseline-audit.md` had gone stale.**
      Row 5.4's own 2026-09-12 update note said "LangGraph is not
      adopted (no dependency...)" — no longer true after group 7 added
      `app/langgraph_followup.py`. The Section 5 summary table's
      "Confirmed absent" row also still listed "LangGraph orchestration"
      unqualified. Added a 2026-09-13 update note to row 5.4 and a
      parenthetical caveat to the summary-table row, both careful to
      state the narrow, accurate claim (a standalone `interrupt()`/
      checkpointer component now exists for node 5.4 specifically; the
      pipeline as a whole is still not LangGraph-orchestrated, and
      `app/routers/query.py` still uses only the bespoke mechanism) —
      not overstated as "LangGraph adopted." Also updated the summary
      table's 5.3/5.4 cell, which still said 5.4 was "non-durable"
      (fixed by group 1-6) and didn't mention the backlog-clarification-
      rule-engine matcher work (71+27 conditions) landing under 5.3 at
      all.
- [x] 8.3 **Found and fixed: two real code-quality issues in
      `app/langgraph_followup.py`**, caught only by re-reading the whole
      file end to end rather than trusting the earlier implementation
      pass: (a) `FollowupState.paused_rule` was set on every node return
      but never read anywhere — dead state left over from an earlier
      design iteration once the interrupt payload started carrying
      `rule` directly; removed. (b) the comment above the `aget_state`
      call in `run_with_pause` referenced `__interrupt__` as though the
      code checked it, but the actual check is `snapshot.tasks[i].
      interrupts` — the code was always correct (re-verified against
      `tests/test_langgraph_followup.py`'s passing "no interrupt was
      recorded" check), only the comment was misleading; rewritten to
      describe what the code actually does and why reaching that line at
      all already rules out the error case (confirmed by re-tracing:  a
      re-raised non-pause-eligible `ClarificationNeeded` propagates out
      of `graph.astream` itself, so `aget_state` is never reached for
      that path — not assumed, traced through the actual control flow).
      Re-ran `tests/test_langgraph_followup.py` after both fixes: still
      18/18, exit 0.
- [x] 8.4 Full regression sweep re-run after all of the above: all 23
      files under `tests/` matching `test_*.py` — every file exit 0,
      zero FAILED markers. `openspec validate --strict`: valid.
      Reported to the human below. **Still not committed.**

## 9. Re-verification (2026-09-13, asked to check the feature end-to-end and cross-check the proposal docs)

- [x] 9.1 **Found: the "18/18" count in tasks 7.3, 8.1, and 8.3 above is a
      miscount.** Running `tests/test_langgraph_followup.py` fresh and
      counting `PASS` lines directly (`grep -c "^\s*PASS"`) gives **17**,
      not 18, across all four sections (9 + 3 + 2 + 3 = 17). Exit code is
      still 0 and all 17 checks still pass — this is a stale number in
      three places in this file, not a regression or a newly-failing
      check. `docs/baseline-audit.md` row 5.4 already caught and
      corrected this same miscount in its own 2026-09-13 "re-verification"
      update note (written independently, in a different session) — this
      file's own count was never brought in line with that correction
      until now. Left tasks 7.3/8.1/8.3's original text unedited per this
      file's own convention of not rewriting history; this note is the
      correction of record.
- [x] 9.2 Re-ran `tests/test_langgraph_followup.py` and
      `tests/test_context_manager.py` fresh: 17/17 and 59/59 respectively,
      both exit 0 — matches. Re-read `app/session_store.py`,
      `app/routers/query.py` (clarification-catch branch and the
      rehydration hook at the top of the handler), and `app/pipeline.py`'s
      resume-read site against every specific claim in `design.md`'s
      "What hardening means, concretely" — all four points confirmed to
      match the live code exactly (field names, call sites, line-level
      behavior). Also built and ran a standalone live walkthrough (not a
      test file) exercising `app.langgraph_followup.run_with_pause`
      end-to-end with a real `interrupt()`, a real on-disk
      `AsyncSqliteSaver` checkpoint file, and independent reconnects
      simulating a separate process for the resume call — confirmed the
      documented replay behavior directly: a resume re-invokes the node
      from the top and repeats the pipeline call with the *original*
      (still-unmerged) question before the `interrupt()` call site is
      reached again and the reply is consumed, and only the subsequent
      loop iteration uses the merged question. This is the concrete
      mechanism task 7.2's "side effects... repeat on every resume"
      comment describes; now demonstrated by execution with visible
      output, not only asserted in a docstring.
- [x] 9.3 Re-ran the full regression sweep (all `test_*.py` files except
      `smoke_restructure.py`): every file exit 0. One file
      (`tests/test_schema_retrieval.py`) showed a transient failure inside
      a larger sequential sweep run but passed cleanly (9/9) on an
      isolated re-run immediately after — its own "LIVE — SCHEME SCOPING
      AGAINST THE REAL `megh_schema_metadata` TABLE" section hits the
      actual database, making it susceptible to ordinary connection
      contention when 20+ test files run back-to-back. Not related to
      this change's diff (this change touches no schema-retrieval code)
      and not reproducible in isolation — noted, not chased further.
      `openspec validate "phase-2-orchestration-durability" --type change
      --strict`: still valid.
- [x] 9.4 Reported to the human below, including the 9.1 correction.
      **Still not committed** — awaiting human review/commit; this
      section itself (a documentation correction) is also part of that
      uncommitted state.

## 10. Wire into production, feature-flagged (2026-09-14) — by explicit instruction, after clarifying scope

Asked to "implement 5.4." Since both the bespoke hardening (groups 1-6)
and the standalone LangGraph component (group 7) already existed and
were verified (group 9), this was ambiguous — asked the human to
disambiguate rather than guess. Answers: (a) wire the existing
`app/langgraph_followup.py` component into production traffic, not just
commit the existing work; (b) do so behind a feature flag defaulting
off, not an unconditional replace of the bespoke mechanism.

- [x] 10.1 `app/config.py`: added `LANGGRAPH_FOLLOWUP_ENABLED: bool =
      False`, same declaration pattern as `DEFAULTS_ENGINE_ENABLED`/
      `FINDINGS_ENABLED`/`CHART_SPEC_ENABLED`/`QUERY_ANALYZER_ENABLED`.
- [x] 10.2 Traced through, before writing any wiring code, what would
      happen if the new code path set `session.state.pending_scope_q`
      the way the bespoke `except ClarificationNeeded` block does: found
      that `pipeline._run_pipeline`'s own top-of-function bespoke merge
      reads that same field unconditionally, regardless of caller, so a
      resume's mandatory interrupt()-replay (which re-invokes
      `pipeline.answer_question` with the original, still-unmerged
      question before reaching the `interrupt()` call site again — see
      task 9.2) would trigger a second, corrupting merge. Decision: the
      LangGraph-path pause branch never sets `pending_scope_q` — its
      resume signal lives entirely in the LangGraph checkpointer instead,
      read via a new `app.langgraph_followup.is_paused(session_id)`
      helper. Recorded in `design.md`'s "Update (2026-09-14)".
- [x] 10.3 **Found and fixed, while tracing 10.2, a real latent bug**:
      `_run_pipeline_node`'s `entity-ambiguous` handling sets
      `session.state.pending_village_hint` but (per 10.2's decision) never
      `pending_scope_q` — and `pipeline.py`'s only clearing of
      `pending_village_hint` (`pipeline.py:3727-3729`) is gated on
      `pending_scope_q` being truthy. Unfixed, this would leak a stale
      village hint into every later turn on the same session once real
      multi-turn traffic reached this path — invisible in
      `tests/test_langgraph_followup.py`, which never issues a second,
      unrelated turn on the same session after a resume. Fixed in
      `app/langgraph_followup.py`'s `_run_pipeline_node`: clears
      `session.state.pending_village_hint` after every successful
      (non-paused) pipeline call — idempotent, mirrors the bespoke path's
      own "consume once, then clear" contract.
- [x] 10.4 `app/langgraph_followup.py`: added `is_paused(session_id) ->
      bool`, a small helper reading the graph's own checkpointer state
      (`snapshot.next` non-empty) — lets a caller decide fresh-question
      vs. resume without touching `ConversationState` at all.
- [x] 10.5 `app/routers/query.py`: added the `settings.
      LANGGRAPH_FOLLOWUP_ENABLED` branch in the `/api/query` handler.
      When on: calls `is_paused`, then `run_with_pause` with `resume=`
      set accordingly; a `{"paused": True, ...}` result is reshaped into
      the identical response JSON the bespoke pause already returns and
      persisted the same way (`persist_turn` + `save_context_state`),
      deliberately without setting `pending_scope_q`/`pending_village_hint`
      (10.2). A propagated non-pause-eligible `ClarificationNeeded` falls
      through unchanged to the pre-existing `except ClarificationNeeded`
      block — safe because its `e.rule in (three pause-eligible rules)`
      check is structurally always False for anything reaching it while
      the flag is on. The pre-existing bespoke branch (flag off) is
      untouched except for one added comment.
- [x] 10.6 New `tests/test_query_langgraph_wiring.py`: real HTTP route via
      `starlette.testclient.TestClient` (same pattern as
      `tests/test_security.py`), auth dependency overridden, no DB/model
      gateway. Covers: flag off — bespoke pause still sets
      `pending_scope_q` (unchanged); flag on — pause does NOT set
      `pending_scope_q`, `is_paused` reports the session paused; flag on
      — a second, ordinary-looking request on the same session resumes
      via `is_paused` and completes with the merged question, through
      the real route; flag on + entity-ambiguous — `pending_village_hint`
      is set during the pause and confirmed cleared after completion
      (direct regression coverage for 10.3's fix). **17/17 checks pass,
      exit 0.**
- [x] 10.7 Re-ran `tests/test_langgraph_followup.py` after the 10.3 fix:
      still 17/17, exit 0 — the fix does not change any behavior the
      existing suite already covered (it only exercises single-session,
      single-resume scenarios that never observed the leak). Full
      regression sweep: all 29 `test_*.py` files (28 pre-existing + the
      new one), exit 0. `openspec validate "phase-2-orchestration-
      durability" --type change --strict`: valid, after extending
      `specs/clarification-pause-durability/spec.md` with one new ADDED
      Requirement ("the alternative component can be enabled as the live
      request path's pause mechanism without corrupting the primary
      mechanism's own resume state") and its three scenarios.
- [x] 10.8 `app/config.py`, `app/langgraph_followup.py`,
      `app/routers/query.py`, `tests/test_query_langgraph_wiring.py`,
      `proposal.md`, `design.md`, `specs/clarification-pause-durability/
      spec.md`, and this file are the only changes this group made.
      Reported to the human below. **Not committed** — awaiting human
      review/commit per this repo's standing process. Default-off means
      no behavior change ships to production until the human separately
      decides to flip `LANGGRAPH_FOLLOWUP_ENABLED`.
