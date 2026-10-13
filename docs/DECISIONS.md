# Technical Decisions

*Read this before proposing an architectural replacement. It lists only decisions traceable to
code comments, commits or project docs; the source is cited on each entry. Dates are those
recorded in the source. "≤ date" means the decision predates that commit, but its exact date is
not recorded.*

*Status: **Active** · **Superseded** · **Accepted risk**.*

---

### D-001 — One FastAPI service, scheme selection inside the pipeline
- **Date:** ≤ 2026-08-31 (README; the earliest commit is `e143c1c`).
- **Decision:** a single service (`app.main:app`) handles every scheme. The earlier per-scheme
  services (`unified-data`, `cm-elevate`, `focus`) and the gateway were removed.
- **Reason:** a single deploy unit, and schemes are chosen per question (including
  cross-scheme questions), not per URL.
- **Alternatives:** per-scheme microservices behind a gateway (the predecessor design).
- **Consequences:** schemes are hand-registered in about 14 places (see SCHEMES.md), and
  `pipeline.py` has grown to about 15,000 lines (2026-10-02; about 8,400 when this was first recorded).
- **Status:** Active.

### D-002 — No LLM or ORM framework
- **Date:** ≤ 2026-08-31 (code; TECHNICAL_BRIEF §0).
- **Decision:** raw `httpx` calls to an OpenAI-compatible API, raw `asyncpg`, and
  `qdrant-client`. No LangChain, LlamaIndex or SQLAlchemy.
- **Reason (INFERRED):** full control over prompts and the vLLM-specific fields
  (`guided_json`, `guided_regex`, `enable_thinking`).
- **Consequences:** every model call and every query is hand-written.
- **Status:** Active.

### D-003 — Model role split
- **Date:** 2026-09-10 (`config.py` comments; `docs/INFERENCE_REQUIREMENTS.md` Task 6).
- **Decision:**
  - `qwen-model` (30B coder): SQL generation **only**;
  - `qwen4-deploy` (Qwen3-4B): classifier (intent, scheme, entity spans, follow-up rewrite)
    **and** SQL verifier;
  - `qwen35-9b`: composition only.
- **Reason:** keep the scarce 30B's batch free for SQL, and stop composition queueing behind
  the frequent small classify calls.
- **Alternatives:**
  - the classifier on the 9B (until 2026-09-10);
  - the classifier on the 30B (before that).
- **Consequences:** the 4B carries both classify and verify traffic, so its queue depth needs
  watching. Classifier accuracy against the 9B baseline was to be validated; whether it was is
  UNKNOWN.
- **Status:** Active.

### D-004 — Local CPU embeddings (fastembed bge-small)
- **Date:** ≤ 2026-08-31 (present in the first commit `e143c1c`; the exact date is not recorded).
- **Decision:** `EMBEDDING_PROVIDER=local` (`BAAI/bge-small-en-v1.5`, 384-dim), for the KB, the
  semantic cache and conversation memory.
- **Reason:** the gateway had no embedding model deployed.
- **Consequences:** CPU load on the app workers. RAG thresholds are tuned to the bge-small
  cosine scale (HIGH 0.84, MEDIUM 0.55).
- **Status:** Active. Switch to `gateway` once `qwen3-embedding` is serving; this needs a KB
  rebuild and re-tuned thresholds.

### D-005 — Reranker disabled
- **Date:** 2026-08-29 (`config.py`).
- **Decision:** `RERANKER_ENABLED=False`.
- **Reason:** the deployed `qwen3-reranker` inverted relevance on this KB. For example, it ranked
  "where to find info" above "application process" for a "what documents" query.
- **Status:** Active until the reranker deployment is fixed.

### D-006 — LLM semantic verifier after the regex guards, failure-open
- **Date:** 2026-09-10/11 (commit `7ad882f`; `config.py`).
- **Decision:** a 4B "does this SQL answer the question?" check runs after the free regex guards
  and before execution. Any verifier failure means "no issue".
- **Reason:** it catches wrong-but-valid SQL in shapes no guard knows yet. A verifier outage
  must never block an answer.
- **Consequences:** false positives (KI-002), handled with calibration examples and 8
  suppression filters.
- **Status:** Active.

### D-007 — Prose rule + few-shot + deterministic guard for every wrong-number bug
- **Date:** convention visible in many incident comments, 2026-09-10 → 2026-09-25 (INFERRED).
- **Decision:** a known bad SQL or answer shape is caught **in code**:
  - `execute_with_repair` guards;
  - `compose_response` faithfulness checks;
  - exact re-queries (`_cm_legacy_exact_totals`);
  - deterministic answers.

  A prompt rule is never relied on alone.
- **Reason:** prose rules repeatedly failed under sampling. Examples:
  - the MGNREGA join fan-out;
  - the AC + invented block filter;
  - CM Elevate Legacy rounded sums, which failed 3 times.
- **Status:** Active.

### D-008 — Ask, don't guess
- **Date:** ≤ 2026-08-31 (`SCOPE_CLARIFY_ENABLED` etc. are in the first commit `e143c1c`).
- **Decision:** pause with one-tap chips when the scheme, top-N, scope, year, tranche or place
  level is missing or ambiguous.
- **Reason:** a silent default ("both schemes", "top 10", "all years") gives confident answers
  to the wrong question.
- **Consequences:** a high clarification rate, and loop risk (KI-001). Each gate has an off
  switch.
- **Status:** Active.

### D-009 — Scheme-name collisions: ask for Focus, pin for CM Elevate
- **Date:** Focus 2026-09-22; CM Elevate 2026-09-24 (commit `7064ab6`).
- **Evidence:** the code comments at `_is_ambiguous_focus` / `_pin_cm_elevate_dataset`, and `focuslegacy_entity_resolver.yaml` `scheme.disambiguation`. The user's confirmation of the CM Elevate choice comes from a session note and is **not recorded in the repo**.
- **Decision:**
  - A bare "Focus" → a two-way ask.
  - A bare "CM Elevate" → pinned by money/FY/lender words to Legacy, otherwise CM Elevate.
- **Reason:**
  - Focus Plus and Focus Legacy share no key and have different grains, so guessing answers from
    a partition that cannot answer.
  - For CM Elevate, pinning keeps the existing flows unchanged.
- **Status:** Active.

### D-010 — Gateway TLS: CA bundle if present, else `verify=False`
- **Date:** 2026-09-13 (commit `5c5a100`).
- **Decision:** `llm._get_ssl_verify` falls back to `verify=False` when no bundle is found.
- **Reason:** the internal gateway uses a self-signed "Enlight AIOps" CA.
- **Status:** Accepted risk (KI-015).

### D-011 — Live schema introspection alongside hand-written rules
- **Date:** 2026-08-29, per the earlier `DATA_MODEL.md` ("Since 2026-08-29"). `_live_schema_block` is in the first commit `e143c1c` (2026-08-31).
- **Decision:** the SQL prompt carries the real columns and FKs read at startup
  (`schema_introspect`). The hand-written `schema_context.py` stays the source of the **hazard
  rules**, which cannot be introspected.
- **Consequences:** if the startup read fails, the prompt silently falls back to the hand-written
  text only.
- **Status:** Active.

### D-012 — Few-shot ranking: lexical IDF, per scheme
- **Date:** 2026-09-23 (`annotations.py`; `test_fewshot_ranking.py`).
- **Decision:**
  - IDF-weighted token overlap within each scheme's pool;
  - tokens in ≥25% of the pool weighted 0.05;
  - top 5 per scheme.
- **Reason:** raw overlap ranked the scheme's own name highest, so breakdown questions retrieved
  bare-SUM examples (8 of 12 breakdown questions had no right-shaped exemplar before the change,
  0 of 12 after).
- **Alternatives:** embedding similarity (not adopted).
- **Status:** Active.

### D-013 — CM Elevate Legacy shares CM Elevate's knowledge base
- **Date:** 2026-09-24.
- **Evidence:** `rag._KB_SCHEME_ALIAS` and its comment. The user's confirmation comes from a session note and is not recorded in the repo.
- **Reason:** they are one programme, and Legacy has no reference docs of its own.
- **Status:** Active.

### D-014 — Stateless JWT auth; department = tenant
- **Date:** ≤ 2026-08-31 (`security.py`, the earlier ARCHITECTURE doc).
- **Decision:**
  - HS256 self-contained JWTs (12 h);
  - PBKDF2 passwords;
  - authorization checks run on the **generated SQL** before execution;
  - admin roles bypass the scope checks but stay tenant-scoped.
- **Consequences:** no token revocation (KI-016); regex-based SQL inspection (KI-007).
- **Status:** Active.

### D-015 — The service boots degraded rather than failing
- **Date:** ≤ 2026-08-31 (`main._try`, `db.init_pool`).
- **Decision:** DB, Qdrant, schema-catalogue and KB failures at startup are logged, and the app
  still serves traffic (`/health` reports `degraded`).
- **Status:** Active.

### D-016 — Data-load defects are fixed by the ingestion team, not patched in the bot
- **Date:** 2026-09-25.
- **Evidence:** `docs/CM_Elevate_Legacy_DB_Issues.md` ("Fixing both in the load makes all 16 match the raw file with no change to the bot"), `docs/Focus_Legacy_DB_Issues.md` and `docs/Focus_Legacy_Fix_Verification.md`. The user's explicit instruction to that effect is from a session note and is **not recorded in the repo**.
- **Decision:** when the bot's SQL is right but `curated` data is wrong, write a
  `docs/<Scheme>_DB_Issues.md` for `megh-ingestion` and do not work around it in prompts.
- **Exception:** column mappings made necessary by a DB change (e.g. `_focus_legacy_geo_columns`).
- **Status:** Active.

### D-017 — The composer may only state numbers present in the result
- **Date:** ≤ 2026-08-31 (`_answer_numbers_faithful` is in the first commit `e143c1c`).
- **Decision:** a numeric-faithfulness check, a metric-coverage check and a hedge check. On
  failure: one strict retry, then a deterministic sentence.
- **Reason:** a misquoted number on a government dashboard is unacceptable.
- **Status:** Active.

### D-018 — Year gaps are reported alongside the answer, not turned into a pause
- **Date:** 2026-09-23 (`_apply_year_gap`; `test_year_gap_*.py`).
- **Decision:**
  - A question naming an absent year plus a valid one is answered for the valid year, with a
    note.
  - A comparison substitutes the nearest year that has data.
  - Only questions naming absent years alone get the pause.
- **Reason:** the SME response contract says so (`fy_gap_note`).
- **Status:** Active.

### D-019 — Voice input: vocabulary prompt on, echo and no-speech guard, system default mic
- **Date:** 2026-09-25 (`config.ASR_PROMPT`, `asr_guard.py`).
- **Decision:**
  - send a short vocabulary prompt (schemes + 12 districts + a digits example);
  - treat a verbatim prompt echo or a stock phrase ("Okay.") as no speech;
  - do not gate on an energy VAD;
  - no in-page mic picker (the user rejected it; from a session note, not recorded in the repo);
  - refuse clips shorter than 1 s client-side.
- **Reason:** measured transcription errors on district names, and hallucinated text on silent
  clips.
- **Status:** Active.

### D-020 — CSP keeps `'unsafe-inline'`
- **Date:** ≤ 2026-08-31 (`config.CSP_ENFORCE` is in the first commit `e143c1c`; `docs/SECURITY.md`).
- **Reason:** the served HTML uses inline scripts, styles and about 30 `onclick` handlers.
  Tightening needs the JS externalised first.
- **Status:** Accepted risk.

### D-021 — Vanilla HTML/JS UI served by the API
- **Date:** ≤ 2026-08-31 (`web/`, `main.py`).
- **Decision:** there is no frontend build. `web/*.html` is served by FastAPI with
  `Cache-Control: no-cache`, because a stale cached page once shipped old voice-input code.
- **Status:** Active.

### D-022 — Follow-up context from structured state, not an answer slice
- **Date:** 2026-09-26 (`context_manager.build_rewrite_evidence`, `pipeline._build_rewrite_prompt`,
  `pipeline._rewrite_provenance_violation`, `tests/test_context_semantic_state.py`).
- **Decision:**
  - The follow-up rewrite gets the previous turn as **tiers**:
    - `PREVIOUS filters`, the schemes plus resolved entities, always;
    - `PREVIOUS result`, a deterministic row summary, only when the follow-up points into the
      result;
    - a sentence-bounded answer excerpt, only when it points into a knowledge answer.
    These replace the fixed `prev.answer[:300]`.
  - A rewrite that names a scheme, district or block that no permitted source contains is
    discarded, and the original fragment goes on.
  - `update_state` does not commit a failed DATA turn.
  - Prompt budgets are **log-and-warn only**.
- **Reason:**
  - The slice carried names the follow-up never referred to. Measured: a long answer's slice
    put 4 unrelated block names into a metric-only follow-up, and the prompt allowed the model
    to use them.
  - The slice also cut off anything past character 300.
  - The previous turn's scope already exists as structured data.
  - Pruning SQL-prompt sections to fit a budget would trade a visible failure for a silent
    wrong number.
- **Alternatives rejected:**
  - A larger slice or a larger context window: more contamination, not less.
  - An LLM summary of the answer: an extra 4B call per turn, and critical fields would depend
    on generated text.
  - Retrying the rewrite on a provenance violation: an extra model call. The fragment plus
    `prior_resolved` already carries the scope deterministically.
- **Consequences:**
  - Follow-ups that point into the result ("the top one") depend on the cue regex
    `references_previous_result`.
  - Villages and years are not provenance-checked (KI-029).
- **Status:** Active.

### D-023 — Shared conversation state in Postgres, not Redis
- **Date:** 2026-09-26 (`app/session_sync.py`, `conversation_store.save_session_state`,
  `Session.to_snapshot/apply_snapshot`).
- **Decision:** every request reads, and after answering writes, a versioned snapshot in the
  existing `app.conversations.context_state` JSONB column. The write is awaited, with a 1 s
  bound. A stale concurrent write is refused rather than overwriting a newer one.
- **Reason:**
  - The deploy has 4 workers and no stickiness, so the per-worker `SessionStore` lost follow-up
    antecedents and pending clarifications (KI-028, KI-001).
  - `app.conversations` already exists wherever the app can answer at all.
- **Alternatives rejected:**
  - Redis: optional and best-effort in this codebase, unset in dev, and a second store to keep
    consistent.
  - Sticky sessions in nginx: fixes routing, not restarts.
  - Reloading only when the local copy was empty (the old rule): a worker with an older copy
    kept using it.
- **Consequences:**
  - +1 SELECT and +1 UPSERT per request.
  - With the DB down, a request degrades to the local copy.
  - `maybe_update_summary` no longer writes by itself.
- **Status:** Active (offline- and live-verified 2026-09-26; DB sync measured at ~50 ms p50 each way).

### D-024 — Field-level merge policy and provenance for follow-ups
- **Date:** 2026-09-26 (`app/context_policy.py`).
- **Decision:**
  - Each field (scheme, district, block, village, year, category, metric, group_by) gets
    KEEP / REPLACE / CLEAR / REQUIRE_CLARIFICATION from deterministic scanners.
  - The follow-up kind picks the rewrite's context layers.
  - `prior_resolved` loses every field that is replaced, cleared or not pinned.
  - Every committed value carries a provenance source, and `model_inference` values are not
    inherited.
  - The rewrite is checked field by field.
- **Reason:**
  - A blanket "inherit what the question doesn't mention" kept a district under "by district"
    and a block under a new district.
  - One rewrite rule for all fields could not tell a user's explicit year change from a
    contaminated one.
- **Alternatives rejected:**
  - An LLM classifier for the follow-up kind: an extra call per turn, for signals the existing
    vocabularies already give.
  - Per-scheme policies: they would have to grow with every scheme. The policy is keyed by field.
- **Status:** Active. Live 2026-09-26: 43/43 scenario checks, against 39/43 for the old path.

### D-025 — MGNREGA: report admin expenditure with a caveat; build the two fixed-shape queries in code
- **Date:** 2026-09-26 (`app/pipeline.py`; MGNREGA use-case QA, KI-041 to KI-048).
- **Decision:**
  - **Administrative expenditure (MGNREGA only):** answer with the recorded
    `SUM(admin_total_exp)` for the asked area and year. The "never populated at source" caveat
    and the live statewide non-zero count are **always** attached. PMAY-G and the multi-scheme
    wording still refuse.
  - **"Spent AND person-days/employment" for one area (MGNREGA only):** the SQL is built by
    `_mgnrega_combined_facts_query` from the resolved filters and runs with parameters bound.
    There is no 30B call, no repair and no verifier.
  - **Scope:** every change is gated on MGNREGA. The user asked that other schemes stay
    unchanged. That includes the negated-level fix (KI-041), although the same chip text
    affects the other schemes.
- **Reason:**
  - Use case DATA-013 expects the figure. The 2026-09-17 refusal existed because a bare
    "0.00" reads as a measured finding, and the caveat addresses exactly that.
  - The combined query has one correct shape. The model path failed 4 of 5 times, and the 4B
    verifier falsely flagged the correct CTE rewrite as a prohibited join.
- **Alternatives rejected:**
  - Keep refusing admin expenditure: it fails the SME use case.
  - Another few-shot plus a verifier filter for the combined query: that is still sampled,
    and CLAUDE.md §5 says prose rules have repeatedly failed.
- **Status:** Active. Live 2026-09-26: 43/43 MGNREGA use-case queries.

### D-026 — Focus Plus: deterministic answer guarantees; three general fixes applied to every scheme
- **Date:** 2026-09-27 (`app/pipeline.py`, `app/routers/query.py`; Focus Plus use-case QA,
  KI-060 to KI-064, KI-066, KI-067).
- **Decision:**
  - **Focus Plus only** (`schemes == ["Focus Plus"]`): `_focusplus_answer_guarantees` runs after
    the composer. It adds shares, the comparison difference and higher side, a complete named
    list, and rupee formatting (AI_PIPELINE §2.9, step 3).
  - A single-count share is computed by a **parameter-bound recount**. It is stated only when
    the recount reproduces the bot's own figure, so it cannot describe a different population
    than the number beside it.
  - **General, all schemes** (each changes only something that was plainly broken):
    1. `_fix_digit_grouping` re-groups a mis-grouped figure whose digits are a result value;
    2. numbers inside the SQL's own quoted literals are not misquotes;
    3. a pause reply that pauses again is remembered as the full resumed question
       (`pause_question`).

    The bank pause gains chips, and the Focus Legacy bank `KeyError` is fixed.
- **Reason:**
  - The composer stated every figure correctly but omitted what the use cases require.
    CLAUDE.md §5: prose rules fail under sampling, so the guarantee is deterministic.
  - The general fixes are not scheme behaviour: a garbled number, a label read as a figure,
    and a lost question are wrong in every scheme, and each fix has a guard that leaves valid
    text alone (4+ digits and a data value; a literal only; the resumed question falls back to
    the raw one).
- **Alternatives rejected:**
  - Prompt rules for percentages or differences: these are sampled, the pattern that already
    failed.
  - Adding a share column to `rows`: the chart renderer would plot it as a second series.
  - Hard-coding the 12.5K cohort size (12,527): the denominator depends on the area and year
    asked.
- **Status:** Active. Live 2026-09-27: 30/30 use cases on 2 of 2 fresh runs; the typed bank
  flow was checked live through three pauses; live context suite 43/43.

### D-027 — CM Elevate: deterministic SQL guards and answer guarantees; both readings of "pending"
- **Date:** 2026-09-27 (`app/pipeline.py`, `app/schema_context.py`; CM Elevate use-case QA,
  KI-068 to KI-075).
- **Decision:**
  - **CM Elevate only** (`schemes == ["CM Elevate"]`):
    - five SQL rewrites in `execute_with_repair`: the programme split, zero-count sectors,
      pending at a level, a plain "pending" never becoming a level filter, and decision states
      on `file_status`;
    - `_cm_elevate_answer_guarantees` after the composer (AI_PIPELINE §2.8 and §2.9 step 3).
  - The Unresolved guard now also covers CM Elevate (`_UNRESOLVED_PLACEHOLDER_SCHEMES`).
  - "PRIME SEED" is a CM Elevate-only term. A bare "seed" is not, because Focus Legacy says
    "seed money".
  - **KI-074 interim:** "pending" stays `data_verified = 'On Hold'` (the SME rule), unchanged.
    A single-figure pending answer also states the `file_status = 'Pending'` count from the same
    query, so neither reading is hidden. Approved and rejected become answerable from
    `file_status`.
- **Reason:** every failure had correct rows or an unambiguous SQL fix, and each prose rule
  (schema_context rules 4, 5, 13 and 14) had already been in the prompt. CLAUDE.md §5 calls
  for a deterministic guard. The "pending" meaning is a product decision, so the interim shows
  both readings instead of silently switching the figure.
- **Alternatives rejected:**
  - New few-shots in `cmelevate_few_shot.yaml`: HANDOFF lists `data/<scheme>/*.yaml` as
    do-not-change, and few-shots are sampled.
  - Redefining "pending" as `file_status`: it would change every existing pendency answer
    without a product decision.
  - Making the guarantees scheme-agnostic: other schemes have not been QA'd against them.
- **Status:** Active. Live 2026-09-27: 55/55 questions (30/30 use cases) on 2 of 2 fresh runs;
  11 reworded probes gave 10 correct and 1 pre-existing intent flake (KI-076); context suite
  43/43. **Revisit KI-074** when the product owner decides.

- **Amendment 2026-09-28:** KI-074 decided by the product owner — "pending" = `data_verified = 'On Hold'` only; the interim file-status line was removed. CM Elevate also joined the village-grained guards (D-028 / D-029 pattern) after its all-villages run; final 7,364 / 7,364.

- **Amendment 2026-09-28 (2):** CM Elevate "status" = `current_file_status` (product owner, from the testers' 22 Sep sheet). Pending stays On Hold; nothing else changed.

### D-028 — Village-grained guards apply to MGNREGA and Focus Plus, not MGNREGA alone
- **Date:** 2026-09-27 (`app/pipeline.py`; Focus Plus all-blocks / all-villages run, KI-079 to
  KI-083).
- **Decision:**
  - The single-village guards built in the MGNREGA all-villages QA (KI-049 to KI-059) are gated
    on `_village_scheme(schemes)`: exactly one scheme, and it is MGNREGA or Focus Plus. Those are
    the two facts that carry `village_code` on every row.
  - Focus Plus adds three things of its own:
    - `_focusplus_narrow_village`: prefer villages that hold Focus Plus data;
    - `_focusplus_pin_village_where`: rebuild a single-village WHERE on the resolved code;
    - `_focusplus_alias_district_collision`: a district HQ alias that is also a village is
      asked about.
  - The twin-village "(LGD code)" chip tag applies to both schemes and fires only on a real
    same-name, same-block pair.
  - Other schemes (CM Elevate, Focus Legacy, CM Elevate Legacy) are unchanged. PMAY-G joined the
    gate on 2026-09-28 (D-029, KI-096).
- **Reason:** the Focus Plus run failed on exactly the shapes those guards fix (52/301 before);
  duplicating them per scheme would drift. `collides_across_dimensions` keeps its "a district hit
  settles it" rule because MGNREGA's 13,298/13,298 run depends on it; the alias case is handled
  in the Focus Plus flow only.
- **Alternatives rejected:**
  - Copying the MGNREGA functions for Focus Plus: two copies drift apart.
  - Relaxing the district rule in `entity_resolver`: it would change MGNREGA and every other
    scheme.
  - Prompt rules for the 30B: the model wrote block/district filters beside the resolved code on
    most tries.
- **Status:** Active. Live 2026-09-27:
  - Focus Plus blocks 204/204 and villages 7,026/7,026, with a confirmation pass of 204/204 and
    1,000/1,000;
  - MGNREGA regression sample 448/448 and 300/300.

### D-029 — PMAY-G: fixed-shape questions answered by a deterministic facts path; PMAY-G joins the village gate
- **Date:** 2026-09-28 (`app/pipeline.py`, `app/entity_resolver.py`, `app/premise_check.py`,
  `app/schema_context.py`, `data/pmay/pmay_few_shot.yaml`, `data/pmay/pmay_entity_resolver.yaml`;
  PMAY-G use-case QA and all-blocks / all-villages run, KI-089 to KI-097).
- **Decision:**
  - `_pmay_facts_query` recognises the use-case shapes (houses / beneficiaries, sanctioned,
    released, remaining, completed, incomplete, stage breakdown, full / partial / no release,
    fully paid but incomplete, unique sanction numbers, completion %, release %, financial
    summary, performance, A-vs-B comparison) for one village / block / district / the state or a
    list of named areas, optionally in one FY or on one date. It builds ONE parameter-bound
    query over `curated.v_pmay` and `_pmay_facts_answer` writes the answer in code (exact ₹ with
    Indian grouping plus lakh / crore; differences and the higher area for comparisons). No SQL
    model, no composer. It runs after the scope / year gates, and authorisation runs on its SQL.
  - Everything else (rankings, "each district", trends, allotment, instalments, averages, lists,
    "in progress", villages counted) stays on the model path, which gains
    `_pmay_sql_issue` (per-year GROUP BY on a whole-period question; AVG-based utilisation),
    `_pmay_comparison_limit` (LIMIT 1 on N named areas), prompt rules 7–9 and three few-shots,
    and `_pmay_rupee_format` (bare rupee cells → ₹ lakh / crore).
  - An area with no rows falls back to the model path (a misspelt place can never read as a
    zero), except a village resolved by LGD code, which gets a stated zero
    (`_pmay_no_houses_answer`).
  - PMAY-G joins `_village_scheme` / `_VILLAGE_FACT_SCHEMES` (D-028): `_pmay_village_names`
    narrows village resolution to villages PMAY-G holds, the chip / level / longest-name guards
    and the alias-district check apply, and MANIPUR / BURMA are villages.
- **Reason:** the 30B failed 11 of 28 use cases on sampling alone (per-year GROUP BY, AVG rates,
  LIMIT 1, dropped parts, 2-decimal crore), and two of those flipped between identical runs. The
  shapes are closed and one view answers all of them, the same situation as D-025 (MGNREGA fixed
  shapes). The village failures (727 / 5,120) were the exact shapes D-028 fixed for Focus Plus.
- **Alternatives rejected:**
  - Prompt rules alone: the project rule is that prose fails under sampling (CLAUDE.md §5).
  - Post-composition patching of the model's answer (as `_focusplus_answer_guarantees`): the
    per-year SQL returns the wrong rows, so there is nothing correct to patch from.
  - A PMAY-only copy of the village guards: copies drift (D-028).
- **Status:** Active. See TESTING.md for the live numbers.


### D-030 — Context relevance gate and a deterministic semantic contract before SQL runs
- **Date:** 2026-09-29 (`app/context_policy.py`, `app/pipeline.py`, `app/edge.py`,
  `app/entity_resolver.py`, `app/premise_check.py`, `app/context_manager.py`,
  `app/session_store.py`, `app/context_budget.py`; KI-030, KI-032, KI-034, KI-130 to KI-135).
- **Decision:**
  - A previous answer is context only for a message that shares something with it
    (`context_policy.continuation_signals`). Without a signal, the edge whitelist applies and no
    follow-up rewrite runs. The existing merge plan (D-022) is unchanged and runs only after
    this gate.
  - The contract between entity resolution and SQL is enforced in code, not only in the prompt:
    resolved district / block / comparison list / year and a stated Focus Plus payment amount
    must be in the SQL (`_resolved_scope_missing`, `_focusplus_stated_amount_missing`), or the
    existing repair loop runs. These sit before the 4B verifier.
  - An input the system cannot pin is asked about, never dropped: a letter-swapped district
    acronym, a Focus Plus amount it never pays, a bare "which one?".
  - Name searches are answered before entity resolution (`_village_name_search_answer`).
  - Every such decision logs one `pipeline_decision` line (labels only, no text).
- **Reason:** each reported failure was an input silently dropped or silently inherited, and
  the project rule is that prose rules fail under sampling (CLAUDE.md §5). Every check is
  deterministic, adds under 1 ms per turn (measured), and makes no model call.
- **Alternatives rejected:**
  - A 4B "is this related?" classifier call: an extra model call on every turn, and it is the
    same model whose rewrite glued the scheme on.
  - A full JSON semantic contract generated by a model and SQL parsed against it: a rewrite of
    working code (CLAUDE.md §4). The resolved-entities dict already is the contract; what was
    missing was enforcement.
  - Adding "WHK" as an alias: not in any SME catalogue (CLAUDE.md: never invent aliases).
  - A stated-amount guard for every scheme: only Focus Plus has SME-confirmed per-row amounts.
- **Amendment (same day, live):** the thread a follow-up continues is chosen per follow-up
  (`_followup_thread_state`, `_data_thread_antecedent`), never by wiping state on a knowledge
  turn: a wipe broke the pinned rule that a knowledge digression does not overwrite the DATA
  thread (`tests/test_context_manager.py` §6), while the per-follow-up rule satisfies both it and
  the reported "what is focus" conversation. Scheme vocabulary in the follow-up outranks the
  antecedent; a bare "Focus" is never given to the model rewrite.
- **Status:** Active. Live-verified 2026-09-29 (see TESTING.md).

### D-031 — Focus Legacy per-place breakdowns are written from the rows, not composed
- **Date:** 2026-09-29 (`app/pipeline.py`: `_focus_legacy_breakdown_answer`,
  `_focus_legacy_unplaced_row`, `_focus_legacy_answer_guarantees`; KI-145, KI-147, KI-150).
- **Decision:** a Focus Legacy result with one place column (district, block, village or
  constituency, aliases accepted) plus 1-3 numeric columns and at most 100 rows is answered by a
  fixed template: one line per place, the sum across the places, and the records with no place
  recorded (read from the data by re-running the query without the model's `IS NOT NULL`). A
  `LIMIT`-cut top-N list gets no total. The composer is not called for these shapes. Other shapes
  still go to the composer, followed by the month / rupee guarantees.
- **Reason:** the answer is fully determined by the rows. In the all-districts run the composer
  dropped the per-block counts for one district and called 5 blocks "5 producer groups" for another,
  which no prose rule reliably prevents (CLAUDE.md §5). Sums are exact because every pg_id
  sits in exactly one district, block and village (verified 2026-09-29: 0 groups span two).
- **Alternatives rejected:** a composer note (already tried for the no-block figure; written in
  words or dropped); a per-row faithfulness check with retry (adds a model call and still cannot
  catch a correct number attached to the wrong noun).
- **Revisit if:** a reload lets one pg_id span two places — the "together" sum would then over-count.

### D-032 — LangGraph as an opt-in orchestrator over the same stage functions
- **Date:** 2026-10-02 (`app/pipeline_graph.py`; `tests/test_pipeline_graph.py`; docs
  `LANGGRAPH_ARCHITECTURE.md`, `CONTEXT_AND_LANGGRAPH.md`, `LANGGRAPH_PAUSE_RESUME.md`,
  `LANGGRAPH_MIGRATION.md`, `MEGHALAYA_LANGGRAPH_ARCHITECTURE.md`).
- **Decision:**
  - `_run_pipeline`, `_answer_data` and `execute_with_repair` are split, verbatim, into stage
    functions (`_turn_*_stage`, `_data_*_stage`, `_scheme_sql_rewrites`, `_execute_one_attempt`,
    `_repair_sql`, `_data_path_error_result`). The sequential path is now a driver over them, with
    behaviour unchanged (the full suite gives the same result before and after the split).
  - A 21-node LangGraph graph runs the same stages: explicit SQL repair loop, pauses as
    `interrupt()` in a separate `pause_gate`, a checkpoint under `thread_id = session_id`
    (SQLite by default; Postgres optional and unverified), and per-node shape-only logs.
  - **Off by default** (`PIPELINE_GRAPH_ENABLED=false`, `PIPELINE_GRAPH_CANARY_PERCENT=0`).
    `answer_question` is the only switch point; the router is unchanged.
  - The Session snapshot (D-023) stays the source of truth for conversation context and the
    pending pause. The checkpoint holds only the paused execution, and correctness never depends
    on it.
- **Reason:** the user asked for LangGraph orchestration, checkpointable pauses and node-by-node
  diagnosis, without a second pipeline and without changing behaviour. This amends D-002
  ("no LLM framework") for orchestration only: no LangChain model, prompt or retriever
  abstractions are used, and every model call is still the raw `httpx` call in `llm.py`.
- **Alternatives rejected:**
  - wrapping only the DATA route (the guide's design): the context window, edge layer and most
    pauses would stay outside the graph;
  - a graph with its own nodes' logic: it would drift from the sequential path;
  - a router-level "does the reply continue the pause?" check: it would duplicate step 0a;
  - nodes for a query analyzer, schema retrieval, findings or charts: none exist in this codebase.
- **Consequences:**
  - New dependencies: `langgraph`, `langgraph-checkpoint-sqlite`, `langchain-core`, `langsmith`
    (tracing off unless `LANGSMITH_TRACING` is set). `langgraph-sdk` pins `websockets<17`
    (downgraded 17.1 → 16.1.1; unused by this app, `pip check` is clean).
  - Stage boundaries are now an API between the two orchestrators: a new step goes into a stage.
  - A source-pin test moved from `_answer_data` to `_data_clarification_stage`.
- **Status:** Active, opt-in. Not live-verified (VPN down 2026-10-02); see
  `LANGGRAPH_MIGRATION.md` for the rollout gates.

### D-033 — Re-authorize every repaired SQL query
- **Date:** 2026-10-02 (`pipeline._repaired_sql_denial`, `RepairedSQLDenied`, `execute_with_repair(scope=…)`,
  `pipeline_graph.node_execute_attempt`; KI-183).
- **Decision:** the up to `MAX_SQL_REPAIRS` queries the repair model writes each pass the same
  `auth.authorize(scope, schemes, resolved_entities, sql)` as the first query, after the deterministic
  rewrites and before execution. A denial ends the turn with the standard `_denied` result. The first
  query's check is unchanged (`_data_authorize_stage`).
- **Reason:** authorization ran on the generated SQL only; a repair that added a district / block
  literal or a finer GROUP BY than the first query reached the database without a scope check for a
  capped role. The user asked for all open issues to be fixed (2026-10-02).
- **Consequences:** a capped officer whose question needs a repair can now get a denial where the
  repaired SQL exceeds the posting (correct). Admin roles are unaffected (`is_admin` bypass).
  No extra model or DB call: `authorize` is a local regex check.
- **Status:** Active on both orchestrators.


### D-034 — Every single-village question is pinned to its resolved `village_code`
- **Date:** 2026-10-02 (all-blocks / all-villages runs for all six schemes; KI-188 to KI-197).
- **Decision:**
  - Focus Legacy and CM Elevate Legacy join the village gate. `_VILLAGE_NARROW_SCHEMES` now holds
    Focus Plus, PMAY-G, CM Elevate, Focus Legacy and CM Elevate Legacy (MGNREGA keeps its own path).
  - When ONE village is resolved, the SQL must filter that `village_code`. Every scheme gets a
    deterministic rewrite on a simple one-SELECT query:
    - no village filter → the code is added (`_pin_missing_village_code`);
    - the village named only by text → that condition becomes the code (`_village_name_cond_to_code`);
    - a block / district literal beside the code is dropped (`_mgnrega_drop_geo_beside_village`,
      `_drop_geo_beside_pinned_village`).
  - Anything more complex (a join, a CTE, a subquery, two villages) is left to the guard and the repair.
- **Reason:** the 30B generator dropped the village, wrote its name into the district or programme
  column, or truncated it ("TEPORPARA ( UPPER )" → 'TEPORPARA'). Each answered a wrong figure
  silently. Prose rules had not held (CLAUDE.md §5), and every curated view carries `village_code`.
- **Consequences:** a village figure is exact by construction for the common query shape. A user
  who really wants a district-wide figure must not name a village. Two-village comparisons keep
  the generator's SQL.
- **Status:** Active on both orchestrators.

### D-035 — CM Elevate (applications) answers assembly-constituency questions
- **Date:** 2026-10-06 (six-scheme tester sheet run; KI-210).
- **Decision:** `CM Elevate` joins `_AC_CAPABLE_SCHEMES`. A constituency is reached the same way as
  CM Elevate Legacy: `curated.v_cm_elevate v JOIN curated.dim_geography g ON g.geography_key =
  v.geography_key`, filter `UPPER(g.ac_name)`, applicants counted `COUNT(DISTINCT v.request_id)`.
  The area-type chip now offers "assembly constituency" for a CM Elevate place name that is one.
- **Reason:** the earlier comment ("PMAY-G, Focus Plus and CM Elevate have no route to it") was wrong
  for CM Elevate: every v_cm_elevate row carries geography_key (417 applications join to the
  Umsning AC). "How many CM-ELEVATE applications are mapped to Umsning?" offered only block or
  village and answered the block.
- **Consequences:** prompt line in `prompt_builder._entities_block`, a note in the CM ELEVATE TABLES
  schema text, `_cm_legacy_qualify_shared_geo_cols` also qualifies v_cm_elevate's place columns
  after the join; `entity_resolver._AC_CONTENTS_SQL` / `AC_CONTENTS_SOURCE` give the constituency
  drill-down CM Elevate's own villages. `tests/test_ac_focus_legacy.py` / `test_ac_flow_focus_legacy.py` updated.
  PMAY-G and Focus Plus still refuse (no geography_key route documented for them).
- **Status:** Active on both orchestrators.

### D-036 — LangGraph is the only orchestrator; the sequential driver is removed
- **Date:** 2026-10-06 (`app/pipeline.py`, `app/pipeline_graph.py`, `app/main.py`, `app/config.py`,
  `.env` / `.env.example`, `Dockerfile`, `docker-compose.yml`; `tests/_graph_turn.py`,
  `tests/test_pipeline_graph.py` and the eight test files that drove `_run_pipeline`).
- **Decision:** the user asked for LangGraph only: "no backup, nothing".
  - Removed: `_run_pipeline`, `_answer_data`, `execute_with_repair`, `RepairedSQLDenied`,
    `_pipeline_graph_selected`, and the `PIPELINE_GRAPH_ENABLED` / `PIPELINE_GRAPH_CANARY_PERCENT`
    settings. `answer_question` always calls `pipeline_graph.answer_question_via_graph`;
    `main.py` always starts the pause sweeper and always reports `components.pipeline_graph`.
  - Kept: every stage function (the graph's nodes call them) and the whole conversation-context layer
    for all six schemes, which runs inside the graph (`context`, `followup`, `data_context`,
    `context_update`).
  - Tests: `tests/_graph_turn.py` (`graph_turn`, `stub_data_path`) replaces direct `_run_pipeline`
    calls; a stubbed DATA path now plugs into the `scope_scheme` stage. `test_pipeline_graph.py` no
    longer compares two orchestrators: each conversation runs twice on the graph and must repeat
    exactly, with call counts asserted. `test_the_graph_is_the_only_orchestrator` keeps the removed
    names and settings out.
- **Reason:** one orchestrator, one code path to read, test and debug.
- **Consequences:**
  - No configuration rollback: going back means restoring the removed code from version control.
  - The extra-forbidding settings loader rejects the removed keys, so they had to leave `.env` too:
    any other `.env` (the VMs) must drop `PIPELINE_GRAPH_ENABLED` / `PIPELINE_GRAPH_CANARY_PERCENT`
    before the new code starts, or startup fails with "Extra inputs are not permitted".
  - Supersedes the "opt-in" and rollback parts of D-032 and rollout gates G5 / G8
    (`LANGGRAPH_MIGRATION.md`).
- **Status:** Active. pytest 1,583 passed, 0 failed; scripts 14/14; live conversation (data,
  follow-up, knowledge, pause and resume) correct on the graph.

### D-037 — A query rephraser node cleans messy new questions before routing
- **Date:** 2026-10-07 (`app/pipeline.py` `_turn_rephrase_stage`, `rephrase_question`,
  `_needs_rephrase`, `_rephrase_violation`; `app/prompt_builder.py` `build_rephrase_prompt`;
  `app/llm.py` `call_rephraser`; `app/pipeline_graph.py` `node_rephrase`; `app/config.py`
  `QUERY_REPHRASE_*`; `tests/test_query_rephraser.py`).
- **Decision:** a 22nd graph node, `rephrase`, between `followup` and `route`. A messy NEW question
  (typos, Hinglish, voice-to-text, no question shape) is rewritten by the classifier model into one
  clean English question, which every later stage reads. Skipped for follow-ups (already rewritten),
  pause replies (must reach the merge as typed), clean questions and over-long text, so most turns
  make no extra model call.
- **Guard:** `_rephrase_violation` rejects a rewrite that adds, drops or changes a scheme, a place
  (canonical), a year, a number, a measure (`_MEASURE_HOLDERS`), a metric family or category, or any
  name / unknown word the user typed, or that is not a usable question. Hinglish is glossed for the
  check only. A rejected, failed or slow rewrite keeps the original question; the node never answers
  and never pauses.
- **Reason:** only follow-ups were ever rewritten; a messy new question reached the classifiers, the
  entity extractor and the SQL generator as typed.
- **Consequences:** +1 classifier call (about 150–200 ms) on messy turns only. A paused rephrased
  turn is remembered as the clean question (`turn_context["standalone_question"]`).
- **Status:** Active.

### D-038 — The UI is a React app (frontend/), replacing the vanilla HTML pages
- **Date:** 2026-10-07 (`frontend/` new; `web/ai_query.html`, `web/admin.html`, `web/vendor/`
  removed; `app/main.py` serves `web/app/index.html` and `web/app/admin.html`).
- **Decision:** the user asked for the whole front end in React.js with every existing function
  kept and connected to the same backend. React 18 + Vite; the chat console (`src/chat`) and the
  admin console (`src/admin`) are two entry pages of one build. The CSS is the original, copied
  verbatim, and the markup keeps the original class names, so the look is unchanged. Chart.js
  4.4.1 now comes from npm (bundled) instead of `web/vendor/`.
- **Kept:** every API call and its contract, the JWT keys (`megh_jwt`, `megh_admin_jwt`), the
  session id (`focusSessionId`), the sign-in gate and splash, history (pin, archive with undo,
  rename, delete, search), thread replay with charts, the scheme carousel, voice input (WAV
  conversion, silence and too-short guards, `no_speech`), the rail (Ctrl+B), the mobile drawer,
  language tabs, glossary, use cases, the admin console's five tabs.
- **Changed on purpose:** the admin sign-in no longer prints the seeded super-admin password
  (CLAUDE.md §6 forbids repeating it). Charts are created on their own canvas (React ref), so the
  2026-09-18 replay-chart id bug cannot recur by construction.
- **Consequences:** a build step. `npm run build` in `frontend/` must run after any UI change; the
  output `web/app/` is kept in the repo so deploys need no Node. `tests/test_asr_transcribe.py`,
  `test_history_charts.py` and `test_ac_full_results.py` now read the React source. CLAUDE.md's
  "No React" rule is superseded.
- **Status:** Active. Browser test (headless Chrome, scratchpad `uitest/ui_test.mjs`): 53/53
  checks; real backend sign-in errors verified; signed-in flows verified with stand-in replies.

### D-039 — Answers stream to the chat UI, with live progress steps, Stop and Regenerate
- **Date:** 2026-10-07 (`app/turn_events.py` new; `app/routers/query.py` `query_stream`, `_answer`,
  `QueryRequest.skip_cache`; `app/llm.py` `stream_model`, `call_response_composer`;
  `app/pipeline_graph.py` `_observed`; `app/config.py` `STREAM_COMPOSER_ENABLED`,
  `STREAM_PING_SECONDS`; `frontend/src/chat/api.js` `streamNLPResponse`, `App.jsx`, `Messages.jsx`;
  `deploy/nginx/nginx-megh-langgraph.conf`; `tests/test_query_stream.py`).
- **Decision:** the user asked for four UI improvements: streaming answers, live progress steps,
  a Stop button and Regenerate / Retry. This supersedes CLAUDE.md's "No WebSocket, no streaming"
  rule for the chat answer (still no WebSocket).
  - `POST /api/query/stream` runs the SAME turn as `/api/query` (the body moved verbatim into
    `_answer`) and sends Server-Sent Events: `step` (a graph node started, from `_observed`),
    `draft_reset` / `token` (the composer's text as the model writes it), then `done` with exactly
    the `/api/query` result, or `error` with the status `/api/query` would have raised.
  - The composer streams only when a live client is bound (`turn_events`, a ContextVar). Every
    other caller (`/api/query`, tests, scripts, harnesses) makes the unchanged, non-streamed call.
  - **The streamed text is a draft, never the answer.** Number faithfulness, the strict retry,
    the per-scheme guarantees and the deterministic rewrites still run on the full text; `done`
    carries the checked answer and the UI replaces the draft with it. A strict retry sends
    `draft_reset` and streams again. The draft is shown muted with a cursor until `done`.
  - Stop aborts the request; the server sees the disconnect and cancels the turn (no turn is
    saved). `skip_cache: true` (Regenerate, and Retry after an error or Stop) answers afresh and
    writes the fresh answer back over the cached one.
- **Fallbacks:** a stream that fails before any token falls back to the plain composer call;
  a client that gets 404/405 or a network error before the first event falls back to
  `/api/query`. `STREAM_COMPOSER_ENABLED=false` keeps the progress steps but sends the answer only
  when complete.
- **Reason:** answers take 2–3 s (up to 75 s at worst) with no sign of progress; officers could not
  stop a wrong question or get a fresh answer when one looked wrong.
- **Consequences:** a composer call holds its gateway slot for the length of the stream (as before:
  the slot was held for the whole round trip). A draft figure that a guard later corrects is
  visible for a moment before `done` replaces it; it is styled as provisional. The earlier
  version of this app made the same draft-then-replace choice (outer repo, `dde9337`).
  nginx: `/api/query/stream` has its own unbuffered location; the app also sends
  `X-Accel-Buffering: no`. Regenerate appears on the latest answer only, and a regenerated
  question is saved as a new turn, so a replayed thread shows it twice.
- **Status:** Active. OFFLINE-VERIFIED (tests with the gateway and pipeline stubbed); not yet run
  against the live gateway (VPN).

### D-040 — Input guardrails: rules plus a model check, before any routing
- **Date:** 2026-10-08 (`app/guardrails.py` new; `app/edge.py` `detect_harmful`, `guardrail_reply`;
  `app/pipeline.py` `_turn_edge_stage`, `_needs_model_guard`; `app/config.py` `GUARDRAIL_MODEL_*`;
  `tests/conftest.py`; `tests/test_guardrails.py`).
- **Decision:** every question passes two guardrail layers at the top of the edge stage, before
  the scheme pick, recommendation, routing or any pause (KI-218).
  - **Rules** (deterministic, no model call) for ten categories: self-harm (a supportive reply
    with Tele-MANAS 14416 and 112, never a refusal), violence, weapons, sexual content, hate,
    drugs, hacking, a private person's identifiers, manipulation (prompt injection, SQL
    statements), plus the existing illegal-request bank (`harmful`). Phrased on intent and target,
    so questions about the same subjects pass ("people killed in floods", "how to kill pests").
    Run on the typed text and on the routed one (a pause merge or rewrite can assemble a
    harmful sentence). `edge.detect_harmful` runs them, so `detect_edge_case` and the pause-reply
    bail check see them too.
  - **Model** (`guardrails.check_model`): one classifier-model call on the typed text that judges
    meaning, so wording, misspelling, speech transcription and Khasi / Garo / Hindi phrasings no
    rule lists are still caught. The message is fenced as data inside the prompt. Skipped for a
    pause reply and for a canned conversational turn ("hi", "thanks").
- **Fallbacks:** the model check fails OPEN on a gateway error, timeout or unusable reply (the
  rules already ran; logged as `pipeline_decision stage=guardrail outcome=error`).
  `GUARDRAIL_MODEL_FAIL_CLOSED=true` refuses instead. `GUARDRAIL_MODEL_ENABLED=false` keeps the
  rules only.
- **Reason:** a single word list only moves the gap; the reported question was missed because one
  verb was not listed.
- **Consequences:** one extra classifier call (max 40 output tokens, 6 s timeout) on every new
  question. A model false positive refuses a legitimate question; the prompt lists what is SAFE
  (statistics about harm, fraud detection, farming) to keep that rare. Guardrail decisions are
  logged with category and layer only, never the question text. Output (the composed answer) is
  not checked; the input check is what stops a harmful request reaching the composer.
- **Status:** Active. OFFLINE-VERIFIED (rules replayed over 3,033 audited questions: 9 blocked, all
  violent; model layer tested with the gateway stubbed); not yet run against the live gateway.

### D-041 — Out-of-scope requests are refused even when they name a scheme
- **Date:** 2026-10-08 (`app/guardrails.py` `check_scope_rules`, `_SCOPE_RULES`, scope replies,
  the model prompt's OUT_OF_SCOPE verdict; `app/pipeline.py` `_guardrail_check`, `_GENERIC_EDGE`;
  `tests/test_guardrails.py`).
- **Decision:** a request that is not harmful but is not this assistant's job is refused with a
  plain "Sorry, I can't help with that — it's outside what I'm allowed to do", what it does not do,
  and what it does (official figures and scheme information, with two example questions). This
  holds EVEN WHEN the request is wrapped in scheme words ("write an Instagram post on MGNREGA
  expenditure"), which the edge whitelist used to let through on the scheme word (KI-219).
  Seven categories: `scope_content` (posts, captions, hashtags, essays, poems, letters,
  presentations), `scope_code`, `scope_task` (booking, buying, applying or filling forms for the
  user, approving or releasing money), `scope_politics`, `scope_academic`, `scope_advice`
  (medical, legal), `scope_general`.
  - Rules (`check_scope_rules`) are phrased on the TASK, never on a data word: "give me CM Elevate
    applications", "village code", "MGNREGA programme", "translate the answer into Khasi",
    "summary of PMAY-G progress" all pass.
  - The guardrail model call (D-040) now also returns OUT_OF_SCOPE with a category; no second
    call. Its prompt lists what is in scope (figures, how schemes work, scheme fit, follow-ups and
    formatting, greetings) and says "when unsure, SAFE".
  - A scope verdict replaces only edge's generic off-topic reply; edge's specific replies
    (out-of-area, money advice, a loan request, capability) stand. A harm verdict always wins.
  - Harm replies now open "I can't help with that — it goes against the rules I follow."
- **Consequences:** a model false positive refuses an in-scope question with a polite reply; the
  rules replayed over the 3,033 audited questions blocked 2 more (both "give me python code").
- **Status:** Active. OFFLINE-VERIFIED (gateway stubbed); not yet run against the live gateway.

### D-042 — The backend sends a chart hint; charts and tables expand full screen
- **Date:** 2026-10-08 (`app/pipeline.py` `_chart_hint`, `_attach_chart_hint`; `app/pipeline_graph.py`
  `node_finalize`; `frontend/src/chat/analytics.js`; `frontend/src/chat/components/Charts.jsx`,
  `Messages.jsx`; `frontend/src/styles/chat.css`; `tests/test_chart_hint.py`).
- **Decision:** charts stay client-side (Chart.js 4.4.1, rows from `data`), and the backend now
  sets `chart_type` on a DATA result in the finalize node (KI-220):
  - words the user typed or the rewrite kept win: pie, donut, stacked, grouped / side by side,
    line chart / over the years, bar chart / histogram;
  - otherwise the rows decide: one row with two or more figures -> `kpi_bar`; two label columns
    and one additive measure with at most 8 series -> `stacked`; else no hint (the UI's own rule:
    line for time, donut for six rows or fewer, bar otherwise).
  - Numbers that are labels (year_key, codes, ids) are never charted as measures, on both sides.
- **UI:** a real Pie type next to Bar / Donut / Line. Every chart and table card has an Expand
  button that opens it full screen (Esc / backdrop closes; focus returns). An expanded chart uses
  the full labels; an expanded bar chart with more than 12 categories turns horizontal and grows
  24 px per category, so 100+ villages are readable. An expanded table has search and sortable
  columns, and the row count shows above every table.
- **Consequences:** frontend-only for Expand; `web/app/` was rebuilt (`npm run build`). The
  follow-up "show that as a pie chart" gets the pie only if the follow-up rewrite re-runs the
  previous query; untested against the live pipeline.
- **Status:** Active. OFFLINE-VERIFIED (pytest for the hint; a Node check of analytics.js; build
  passes); not yet checked in a browser.

### D-043 — A conversation layer in the router, around the pipeline (not inside it)
- **Date:** 2026-10-08 (`app/conversation_layer.py` new; `app/routers/query.py` one call in `_answer`
  plus the topic-switch line in `is_cacheable`; `app/session_store.py` `topics` and `context_at` in
  the snapshot; `app/config.py` `CONVERSATION_LAYER_ENABLED`, `CONTEXT_IDLE_EXPIRY_SECONDS`;
  `app/topic_memory.py` kept as written earlier the same day; `tests/test_conversation_layer.py`).
- **Context:** a conversational-feature spec asked for follow-ups, topic switch and return, reset,
  expiry and clarification resume, with the pipeline, the LangGraph graph and the database left
  unchanged. Most of it already existed (follow-up rewrite D-022, structured state, scheme swap
  KI-180, pause resume, edge greetings, topic memory). Missing: reset, idle expiry, plain-words
  returns, topic memory across workers, and a measure after a knowledge answer (KI-222).
- **Decision:** one module that runs in `routers.query._answer` after `session_sync.sync_in` and
  before the caches, and hands the pipeline a question (or answers itself, for a bare reset):
  1. idle expiry: older than `CONTEXT_IDLE_EXPIRY_SECONDS` (1800, the same as the in-process
     session) -> state, turns, summary, pending pause and topics cleared, and a paused LangGraph
     run for the thread deleted. Chat history is never touched. `context_at` 0 (older snapshot)
     never expires;
  2. reset ("start a new topic", "forget the previous question", "let's start again") -> the same
     clearing; bare = a short edge acknowledgement (`edge_type` `context_reset`), with a question =
     only the question runs;
  3. plain-words return ("what was the PMAY-G information again?", "remind me about PMAY-G") to a
     topic this chat already holds and is not on -> `"Go back to PMAY-G, <its last question>"`,
     which topic_memory restores. "What about PMAY-G?" stays the existing scheme swap;
  4. a measure-only question after a single-scheme KNOWLEDGE answer -> the pipeline's own
     `_measure_after_knowledge` rewrite (KI-222).
  A turn the layer answered or rewrote is not cached. The question the pipeline ran (not the raw
  text) is what the router records as the follow-up antecedent and as a pause's question; for an
  untouched turn they are the same string.
- **Rejected:** a new graph node (CLAUDE.md: change behaviour in a stage, never a graph node, and
  the spec forbade changing the graph); fixing KI-222 inside `pipeline.py` (outside the approved
  edit list; noted as the in-pipeline alternative).
- **Status:** Active. LIVE-VERIFIED 2026-10-08 (15 multi-turn scenarios through `_answer` with the
  live gateway and DB); pytest 1,926 passed, 0 failed; scripts 14/14.

### D-044 — Cross-scheme comparisons are answered deterministically (`app/cross_scheme.py`)
- **Date:** 2026-10-13 (Cross Scheme Test Cases sheet session; `app/cross_scheme.py` new;
  `app/pipeline.py` hooks in `_data_scheme_stage`, `_data_entity_stage`,
  `_data_clarification_stage`; `app/pipeline_graph.py` DATA keys `cross`, `pre_rephrase_question`;
  `tests/test_cross_scheme_sheet_fixes.py`; live harness `tests/sheet_runs/cross/`).
- **Context:** a question comparing two or more schemes went to the SQL generator with every named
  scheme's schema. On the testers' 20 cases it paused 18 times and answered 2 wrongly (KI-280):
  several figures of different kinds in one answer is exactly where the generator and the composer
  misattribute numbers, and DATA_MODEL forbids adding the schemes' different measures together.
- **Decision:** detect a comparison (2+ named schemes, or "which / each / all schemes" with a
  figure, ranking or compare word) and answer it from fixed, parameter-bound SQL, one query per
  scheme and measure, each scheme by the rule its own single-scheme answer uses:
  MGNREGA `SUM(persons_employed)` / `SUM(total_exp)` (lakh); PMAY-G `COUNT(*)` not placeholder /
  `SUM(amount_released)`; Focus Plus `COUNT(DISTINCT beneficiary_key)` / `SUM(amount_disbursed)`;
  Focus Legacy `SUM(no_of_pg_members)` (+ producer groups) / `SUM(amount_disbursed)`; CM Elevate
  `COUNT(DISTINCT request_id)`, no money, no year; CM Elevate Legacy `COUNT(*)` /
  `SUM(total_disbursement)`. The answer is a table built from the rows (never composed by a model):
  per scheme, or per district / block, with what each figure counts, each scheme's years, "no data
  for FY …" / "not recorded by constituency" / "no money recorded" instead of a zero, rankings,
  the leading scheme per district and the top district per scheme. Nothing is summed across
  schemes. No year means each scheme's whole data window (no merged-FY pause); no place means
  statewide (no area pause). The SQL is authorized (`auth.authorize`) on a literal copy.
- **Rejected:** more prompt rules / few-shots for the generator (prose rules fail under sampling,
  CLAUDE.md §5); answering through `v_cross_scheme_money_district_year` (MGNREGA and PMAY-G only,
  district grain).
- **Status:** Active. LIVE-VERIFIED 2026-10-13 (see TESTING.md: sheet + every scheme combination
  at every level + every village).
