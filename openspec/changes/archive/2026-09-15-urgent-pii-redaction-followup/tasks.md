## 0. Re-verify (done, recorded here per this repo's process)

- [x] 0.1 Confirmed `scheme_specific` is not PII-only:
      `cmelevate_schema_partitions.yaml:470-488` — ~125 fields total, 8
      blocklisted; `gender_id` and other scheme-specific fields are
      legitimate and actively documented as queryable via `->>` (worked
      example at line 1090-1097). The "blocklist the whole column" fallback
      from the original instruction does not apply — see proposal.md's Why.
- [x] 0.2 Confirmed `scheme_specific` IS included in `curated.v_cm_elevate`
      (absent from the schema doc's `columns_not_in_v_cm_elevate` list at
      line 522-537) — so `SELECT *` on that view does expose it, and must be
      caught by the new Layer 1 check, not left to Layer 2 alone.
- [x] 0.3 Confirmed `app/db.py` registers no `asyncpg` JSON/JSONB type codec
      — a JSONB column returns as a raw Python `str` from `conn.fetch()`,
      which is why Layer 2's existing top-level dict-key strip can't reach
      inside it. This is the precise mechanism of the bypass.
- [x] 0.4 Confirmed `denied_by TEXT` already exists on both
      `app.conversation_turns` and `app.query_audit`
      (`app/appdb.py:117,140`), already read out of `result.get("denied_by")`
      by `conversation_store.persist_turn` (`app/conversation_store.py:48,
      94, 104-105`) — currently only ever set by the hard-denial path
      (`pipeline.py:3226`). No migration needed for Fix #2.

## 1. Fix #1, Layer 1 — container-column exposure check

- [x] 1.1 `app/pii_guard.py`: added `_CONTAINER_COLUMNS` map
      (`{"CM Elevate": "scheme_specific"}`) and
      `find_container_exposure(sql, schemes) -> str | None` — returns the
      container column name if `sql` exposes it whole (bare/aliased select,
      or `SELECT *`/`alias.*` while the scheme's container is in scope),
      `None` if the SQL only does scoped `->>`/`->`/`#>`/`#>>` extraction or
      doesn't reference the column at all. `_has_star_select` splits each
      SELECT-list on commas and anchors the star match to a whole token, so
      `SELECT amount * 2 AS x` (multiplication) is not mistaken for a
      wildcard — not in the original instruction, found while implementing.
- [x] 1.2 Wired into `execute_with_repair` (`app/pipeline.py:2756-2765`, next
      to the existing `find_blocked_columns` call before `run_readonly`):
      either check firing logs a warning (column/container name in the log
      only) and raises `_pii_not_available_clarification(schemes)` —
      unexecuted, unrepaired, same as today.
- [x] 1.3 Tests in `tests/test_pii_guard.py` sections 10-14: (a) bare
      `SELECT scheme_specific` rejected; (b) aliased `SELECT scheme_specific
      AS ss` rejected; (c) `SELECT * FROM curated.v_cm_elevate` rejected for
      CM Elevate specifically; (d) regression — the doc's own worked example
      `SELECT scheme_specific ->> 'gender_id' AS gender, COUNT(*) ... GROUP
      BY 1` is NOT rejected, still executes; (e) added beyond the checklist —
      `scheme_specific ->> 'dob'` (a blocklisted key, scoped) is still
      rejected by the pre-existing literal-name scan, proving the new check
      didn't loosen that guarantee.

## 2. Fix #1, Layer 2 — JSON-string/value redaction backstop

- [x] 2.1 `app/pii_guard.py`: `redact_rows` now runs every surviving value
      through `_redact_json_value` — if it's a JSON-object string
      (`json.loads` succeeds and yields a `dict`) or already a `dict`, strip
      any blocklisted key found inside and re-serialize to the same type
      (string stays string via `json.dumps`, dict stays dict). Non-JSON /
      non-dict values, and objects with nothing to strip, pass through
      unchanged (the identical string, to avoid needless re-serialization).
- [x] 2.2 Test (`tests/test_pii_guard.py` section 15): a constructed row
      with a raw JSON string value containing `dob`/`member_id`
      (blocklisted) plus `gender_id`/`village_name` (not) — after
      `redact_rows`, the blocklisted keys are gone from the re-serialized
      string and the other two are unchanged; also confirmed the original
      row's string was not mutated in place.
- [x] 2.3 Integration-style tests (`tests/test_pii_guard.py` sections 16 and
      16b): a fake `run_readonly` returning a `scheme_specific` JSON-string
      value with all 8 blocklisted keys plus `gender_id`/`village_name` —
      confirmed none of the 8 survive at the top level or inside the nested
      JSON, and the two legitimate fields do. Section 16b additionally
      confirms the full `execute_with_repair` path: `SELECT *` on CM Elevate
      is now caught at Layer 1 (1.2) before it would even reach this Layer 2
      backstop.

## 3. Fix #2 — audit trail carries the rule

- [x] 3.1 `app/routers/query.py`: the `ClarificationNeeded` handler now sets
      `out["denied_by"] = e.rule` for every clarification rule (not scoped
      to `pii-column-blocked` only — same one-line change in the one shared
      handler, per proposal.md's note; flag if this is broader than wanted).
- [x] 3.2 Same handler: `_mirror_audit(...)` now receives the real `out`
      dict instead of the truncated `{"route": "clarification"}`.
- [x] 3.3 New `tests/test_pii_audit_trail.py`: via `TestClient(app)` with
      `_identity` overridden and `answer_question` monkeypatched to raise
      `ClarificationNeeded(text, rule="pii-column-blocked")`, captured the
      `result` kwarg `conversation_store.persist_turn` was actually called
      with — confirmed `result["denied_by"] == "pii-column-blocked"` and
      `result["route"] == "clarification"`. Then fed that same `result` dict
      into the real `conversation_store._persist_turn` with
      `app.db.execute`/`fetchval` monkeypatched to capture SQL + bound
      params (no live DB touched) — confirmed `"pii-column-blocked"` is a
      bound parameter in both the `app.conversation_turns` and
      `app.query_audit` INSERTs.

## 4. Regression + report

- [x] 4.1 `tests/test_pii_guard.py`: 39/39 checks PASS (9 pre-existing +
      30 new across sections 10-16b). `tests/test_pii_audit_trail.py` (new):
      9/9 checks PASS. See conversation report for full output.
- [x] 4.2 Full regression sweep, all 11 files in `tests/` (excluding
      `smoke_restructure.py`, a manual/dev script, not an assertion suite):
      `test_chart_spec.py`, `test_context_manager.py`,
      `test_defaults_engine.py`, `test_findings.py`, `test_join_graph.py`,
      `test_pii_audit_trail.py`, `test_pii_guard.py`,
      `test_pipeline_join_discovery.py`, `test_pipeline_schema_retrieval.py`,
      `test_schema_retrieval.py`, `test_security.py` — every file exit 0,
      zero FAILED markers.
- [x] 4.3 `git diff --stat` confirms `app/db.py`, `app/auth.py`,
      `app/deps.py`, `app/appdb.py` (connection/role/schema) have zero diff.
      Files actually touched this change: `app/pii_guard.py` (+93 lines),
      `app/pipeline.py` (+16/-6 in one hunk), `app/routers/query.py`
      (+16/-2 in the two Fix #2 hunks — one unrelated pre-existing
      `SessionOwnershipError` hunk in the same file predates this change,
      confirmed by inspection, not touched by it), `tests/test_pii_guard.py`
      (+124 lines), `tests/test_pii_audit_trail.py` (new, 124 lines),
      `openspec/changes/urgent-pii-redaction-followup/{proposal.md,
      tasks.md}` (new). A large amount of unrelated pre-existing
      uncommitted working-tree diff exists across the repo (config, RAG,
      vectorstore, docs, other openspec changes) from before this session —
      not touched by this change, flagged for the human same as the
      original `urgent-pii-redaction` change flagged its own pre-existing
      `.env.example` noise.
- [x] 4.4 Reported back below — STOPPING here, no commit made. Awaiting
      confirmation.

## 5. Post-review fix (2026-09-12, after go-ahead)

- [x] 5.1 Wrote the missing `specs/` deltas — the change had no `specs/`
      directory at all: `specs/pii-container-column-protection/spec.md`
      (3 ADDED Requirements, 5 scenarios, covering Fix #1's Layer 1 + Layer
      2) and `specs/pii-denial-audit-trail/spec.md` (1 ADDED Requirement,
      2 scenarios, covering Fix #2). `openspec validate
      urgent-pii-redaction-followup --strict` now passes (was failing:
      "Change must have at least one delta").
- [x] 5.2 No code changes made to this change's own files this round —
      the pipeline.py edit made 2026-09-12 (moving the PII checks earlier
      relative to the join validator) belongs to
      `join-graph-post-generation-validation`'s task 5.2, not this change;
      noted here only because it touches the same function
      (`execute_with_repair`). Full regression sweep re-confirmed after
      that edit: all 12 `tests/` files exit 0, including this change's own
      `test_pii_guard.py` (39/39) and `test_pii_audit_trail.py` (9/9).
