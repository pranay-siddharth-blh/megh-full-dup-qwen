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
- **Status:** **Superseded by D-067 (2026-10-24)** on the dev box: embeddings now come from the gateway's
  `qwen3-embedding`. `config.py` still defaults to `local`, which remains the rollback.

### D-005 — Reranker disabled
- **Date:** 2026-08-29 (`config.py`).
- **Decision:** `RERANKER_ENABLED=False`.
- **Reason:** the deployed `qwen3-reranker` inverted relevance on this KB. For example, it ranked
  "where to find info" above "application process" for a "what documents" query.
- **Status:** **Superseded by D-083 (2026-10-29).** The inversion came from sending the bare question; with the
  Qwen3 format the re-ranker runs on every knowledge question and has no off switch.

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
  rules already ran; logged as `pipeline_decision stage=guardrail outcome=error`). **Superseded
  2026-10-29 by D-080:** it now fails closed for abuse only, and counts and alerts on every failure.
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
- **Status:** **Superseded by D-062 (2026-10-22)** — the answer is no longer a fixed table. Detection, the
  place handling (`refine_block`, `refine_constituency`, `years_in_text`) and the twin-village chips stay.
  LIVE-VERIFIED 2026-10-13 (see TESTING.md: sheet + every scheme combination at every level + every village).

### D-045 — Answer, don't ask (ANSWER_DEFAULTS_ENABLED)
- **Date:** 2026-10-14. User decision: "whenever the user asks anything related to the data … you need to give
  the answer" (after a test session where 33 of 45 questions paused).
- **Decision:** a data question that names no area / financial year / Focus Plus tranche is answered for all of
  Meghalaya / all financial years combined / all tranches, by appending exactly the text the matching chip
  appends ("for all of Meghalaya", "across all financial years", "across all tranches"), so the SQL is told the
  scope (the reason the year pause existed: the generator otherwise picked the latest year). A data question that
  names no scheme but asks for a measure several schemes record is answered for each of them (app/cross_scheme.py).
  Stocks (job cards) are pinned to the latest year. Real ambiguity still asks: a name that is several places or
  villages, a bare "Focus", a question with no measure at all.
- **Supersedes:** the 2026-09-09 product decision that a plain PMAY-G question pauses for a FY (pipeline.py
  `_needs_year_clarification` comment). `ANSWER_DEFAULTS_ENABLED=false` restores the pauses.
- **Status:** Active. Live-verified on the user's 45 questions and the hierarchy matrix (TESTING.md).
- **Amended by D-055 (2026-10-19):** an unnamed scheme is no longer answered for every scheme: a new chat asks, a chat with a scheme uses it.
- **Amended by D-053 (2026-10-19):** the year default now applies only when the conversation already carries a year;
  a question with no year anywhere asks which financial year again.
- **Amended by D-056 (2026-10-21):** the area default ("for all of Meghalaya") applies only inside a chat that has
  answered a data question; a new chat asks the district first.

### D-046 — SQL is read and changed on the SQLGlot tree only; no regex on SQL
- **Date:** 2026-10-15. User decision, stated firmly: "completely we need to use SQLGlot … I don't want regex here.
  Single piece of code I don't want."
- **Decision:** every piece of code that reads, checks or changes SQL text works on the parsed tree or token stream
  (SQLGlot, Postgres dialect), through the shared helpers in `app/sql_ast.py` (`sql_guard.py` stays the safety
  check). This covers authorization (`auth.py`), the guards and rewrites in `app/pipeline/common/c10`–`c13` and
  every `app/pipeline/schemes/*.py` file, `_extract_sql` (token stream, no fence regex) and the offline / test
  tools. SQL generation and repair send **no** decoding constraint (the old `guided_regex` is gone;
  `SQL_GUIDED_DECODING_ENABLED` is no longer read). Regex is still used on English text (the officer's question,
  composed answers, verifier complaints, DB error messages, result-row key names): SQLGlot cannot parse English.
- **Why:** text patterns read words inside string literals and comments as columns, missed `UPPER(lgd_district)`,
  saw only the first value of an `IN` list and nothing in an `OR` branch (an authorization bypass, audit
  2026-10-15), and skipped every query that started with `WITH` (the MGNREGA fact fan-out guard).
- **Consequences:** a rewrite that fires regenerates the query in SQLGlot's layout (one line, `CAST(x AS DECIMAL)`
  for `x::numeric`, `FILTER(WHERE`); an unchanged query is returned byte for byte. Unparseable SQL makes inspectors
  answer "not found"; `sql_guard` refuses it at execution, and `auth.authorize` refuses it for a geo-restricted
  user (fail closed).
- **Status:** Active. Never add a regex that touches SQL text.

### D-047 — No regular expressions anywhere in the codebase
- **Date:** 2026-10-15/16. User decision, stated firmly: no regex in the code base "whenever the English text,
  whatever the task". Extends D-046 (SQL on the SQLGlot tree) to everything else.
- **Decision:** no `import re`, no compiled patterns, no `regex` package, no JavaScript regex literals or `RegExp`.
  English text (questions, answers, names, verifier complaints, error messages, row keys) is matched with the
  word-level matcher `app/text_match.py` (W / Seq / Alt / Opt / Gap / Joined / Cap / NotBefore / NotAfter …,
  plus number / year / sentence helpers) or plain string methods; SQL with `app/sql_ast.py`; the frontend with
  string methods. Pattern constants kept their names (now `Matcher` objects with the same `.search` /
  `.finditer` / `.sub` API) so call sites did not change.
- **Status:** Active. Whole-project scan 2026-10-16: no regex in app/, tests/, data/, deploy/ or frontend/src.

### D-048 — Business definitions for gender, people across years, households vs persons
- **Date:** 2026-10-16. Fixes errors.md cases 1–3 (KI-229, KI-035, KI-040) by definition, in the SQL backbone
  (`app/schema_context.py`: shared rules "COUNTING PEOPLE / HOUSEHOLDS ACROSS YEARS" and "GENDER", MGNREGA rules
  6a / 11 / 12, Focus Plus rules 6a / 6b, PMAY-G vocabulary) and in executed few-shots
  (`data/mgnrega/few_shot.yaml`, `data/focus_plus/focusplus_few_shot.yaml`, each run read-only on megh_db
  2026-10-16, results in the YAML comments).
- **Definitions:**
  - **MGNREGA "beneficiaries" = households_employed** (households provided employment — the scheme's own unit, one
    job-card household). persons_employed = individual workers ("people", "workers", gender). *Chosen by Claude
    on the user's instruction to add the definition; KI-040 had asked for an SME decision — confirm with the SME.*
  - **Men (MGNREGA) = SUM(persons_employed) − SUM(women_employment_provided)**, returned with both inputs; women
    are recorded only for FY 2022-23..2024-25 (0 on every 2025-26 row), so men are not derivable for 2025-26.
    A negative result (2 block-years, 390 village-years record women > persons) is a source inconsistency.
  - **Distinct people across years:** never add per-year distinct counts. Focus Plus all-years beneficiaries =
    one COUNT(DISTINCT beneficiary_key) (105,813, not 93,286 + 105,813). MGNREGA has no household / person id,
    so "all years" stays ONE combined figure (the user's 2026-10-13 instruction) but is aliased
    household_years / person_years and called "household-years"; a year-wise split only when asked.
  - **Gender coverage:** MGNREGA women only; Focus Plus gender = 12.5K cohort only (12,527 of 105,813);
    CM Elevate gender_id on every row; PMAY-G, Focus Legacy, CM Elevate Legacy: none.
- **Deterministic layer:** `_mgnrega_people_years_alias` (mgnrega.py, in `_scheme_sql_rewrites`) relabels an
  outer multi-year SUM(households_employed / persons_employed) as household_years / person_years on the SQLGlot
  tree, and `_mgnrega_answer_notes` tells the composer what household-years means. Tests:
  `tests/test_business_definitions.py`. Live 2026-10-16 before the guard: cases 1 and 2 answered correctly
  (23,758; 105,813); case 3 still summed into "beneficiary households" — the reason for the guard.
- **Status:** Active.

### D-049 — Follow the ingestion team's 2026-10-16 database changes from the chatbot side
- **Date:** 2026-10-16. Source: `CHATBOT_DB_CHANGES_2026-10-16.md` (ingestion team). Reply:
  `docs/Chatbot_Answers_to_Ingestion_Team_2026-10-16.md`. **No database change was made.**
- **Catalog, not embeddings.** We do not embed `semantic.v_embedding_documents` or load
  `semantic.v_prompt_bundles`. `app/schema_introspect.py` reads the tables those views are rendered from, and since
  this decision also reads `column_catalog.unit` / `sample_values` (UNIT and VALUES lines), `metric_definitions`
  under its real column names (`metric_key`, `sql_expression`; the old reader printed nothing), `semantic.v_join_rules`
  and `curated.v_data_coverage`. Column notes on `curated.fact_*` tables are no longer prompted (the views carry them).
- **The prompt follows `megh_readonly`'s grants.** Columns that role cannot SELECT (`has_column_privilege`) and the
  three privacy tables are left out of the LIVE SCHEMA block, even while a dev box connects as `postgres`.
- **CM Elevate (user decisions 2026-10-16):** an application is `COUNT(DISTINCT request_id)` for every word
  (8,840, not 8,867 records). `scheme_specific` is locked: sector moves to the `sector_id` column; gender and the
  Approved / Rejected decision are answered "not available" by the measure-not-held pause. **"Pending" stays
  `data_verified = 'On Hold'`**: the user kept the tester-sheet rule over the ingestion team's "can't answer".
- **Deterministic guards** (in `_execute_one_attempt`): a row join of two objects in `v_join_rules` (built-in
  fallback when it is unread) and a read of a role-denied column are rejected and sent back for repair.
  `sql_guard` refuses the three privacy tables (`private_table`).
- **Pools:** `DB_POOL_MIN_SIZE` default 10 → 1, `DB_POOL_IDLE_SECONDS` 120 on both pools: megh_db ran out of its
  100 connections, about 48 of them idle chatbot logins.
- **Status:** Active.

### D-100 — Context frames: the whole window in the snapshot, one checked resolver for a follow-up (2026-11-03)
- **Date:** 2026-11-03. User: "everytime i am asking context … i want permanent solution for this context issue, it
  should have context to all the window … not hard coded … dont create any new problems". Files: NEW
  `app/context_frames.py`; `session_store.py` (`Session.frames`, snapshot key `frames`); `conversation_layer.py`
  (hook inside the `comparison_with_earlier` branch, `clear_context`, idle set-aside / continue); c13 `_update_context`
  (`record`); c14 (two hooks, below; NEW `_c14_frame_gate_miss`; `frame_resolved` kept across the turn_context
  reset, so a resolved comparison is not "(new question)"); `llm.call_rewriter`
  (`guided=`, default None); `config.CONTEXT_FRAMES_ENABLED` (default True); `tests/conftest.py` (off for the other
  suites, as for every extra model call); NEW `tests/test_context_frames_2026_11_03.py`.
- **Context (the user's chat, replayed live on the old code, all reproduced):** Focus Plus total -> "Give a
  district-wise breakup" -> "compare this with spend on Focus scheme" (which-Focus pause, correct) -> "compare this
  with spend on Focus Legacy scheme" = statewide totals (`comparison_with_earlier` carries scheme / place / year
  only, no breakdown) -> "include focus plus also" = the documents' "what is Focus Plus" ("also" is a cue only as the
  first word; no rewrite; the rephraser + intent took a bare scheme name as KNOWLEDGE) -> "i mean compare focus plus
  also" = Focus Plus alone (the model's correct rewrite rejected by provenance: `allowed_schemes` = the previous turn,
  which was that documents answer; `_data_thread_antecedent` skips an aside only for place / year changes). Root
  pattern: ~10 phrase checks each decide "follow-up?", "of which turn?" (always the previous) and "what carries?"
  (scheme / place / year, never the breakdown or measure) for one wording; and `apply_snapshot` keeps only the LAST
  turn, so no worker could see the rest of the chat.
- **Decision:**
  1. **A frame per answered turn** (data / knowledge): the question the pipeline ran + schemes, breakdown level
     (`asked_levels`), place, years. Every frame of the window (`SESSION_MAX_TURNS`) is in the snapshot (D-023).
  2. **The turn a follow-up continues is the latest ANSWERED figure** (deterministic). Pauses, greetings and
     how-it-works asides in between are skipped. A model choice among turns was tried first and picked T1 for "this"
     (replay 2026-11-03), so it is not used. Going back to an older topic stays with topic memory (recall runs first).
  3. **One guided-JSON call to the rewrite model** (the 9B, its existing role — no role moved) with the window's
     frames writes that turn's question with the message's change applied. It runs **only where the existing path
     loses the context, after every precise rule has had its turn** (three hooks):
     a. `comparison_with_earlier` matched (conversation layer): its state-only question dropped the breakdown and
        measure; the frames' question replaces it, the state's question stays when they decline;
     b. c14, `rewrite_followup` gave up (returned the question unchanged: failed, or provenance-rejected against
        the previous turn only) — after the scheme / place / rest-of-schemes swaps and the figure-reference,
        measure, ranking and compare-place rules;
     c. c14, `turn_kind` says FOLLOWUP but no follow-up check fired (the gate miss).
     First built as the FIRST step of the conversation layer: the live harness then showed it pre-empting precise
     rules (P15 constituency place swap, BLH8 "these 126" figure reference, AF02 swap-measure-unavailable pause —
     2026-11-03), so it was moved behind them.
  4. **Deterministic checks**, the pipeline's own readers only (no new word lists): schemes from the message or the
     base turn only (`_exact_schemes`); D-024 provenance (`rewrite_violation`) against the message + base question;
     nothing of the base turn the message leaves alone may be lost (schemes — kept on a one-side comparison, the
     `compare-one-side` cue —, breakdown level, place, years, measure family); no bare "Focus"; the result must be
     STANDALONE.
  5. **Never** for a STANDALONE or VAGUE message (D-061, D-098), a bare "Focus" (CLAUDE.md §4: still asked), a reply
     an open pause understands itself (D-065 / D-098), or an aside about another scheme than the figure
     (`_data_thread_antecedent` decides).
  6. **Any skip, failure, timeout or failed check = the pre-D-100 path, unchanged** (verified by accident on
     2026-11-03: a broken edit raised in every call and every turn answered exactly as before).
- **Amends:** D-022 / D-024 (provenance is kept, applied to the chosen turn instead of always the previous one); D-024's
  rejected "LLM classifier for the follow-up kind, an extra call per turn" does not apply: it is not a classifier
  and runs only on the turns where the existing path already failed.
- **Cost:** one 9B guided call, only on a turn that hits one of the three hooks; every other turn unchanged.
- **Rollback:** `CONTEXT_FRAMES_ENABLED=false` (frames are not recorded; the conversation layer runs as before).
- **The precise rules stay first** (`counterpart_swap`, scheme / place swaps, figure reference, measure change, ...);
  the frames do not replace them. The decision log (`pipeline_decision stage=frame`, and `followup rewrite=
  context-frame-*` / `conversation action=compare-earlier-frame`) shows each hook firing, for measurement.
- **Status:** Active. Verification: see TESTING.md 2026-11-03 (D-100).

### D-099 — CM Elevate: ask which dataset in a new chat; the chosen dataset stays until the user switches (2026-11-03)
- **Date:** 2026-11-03. User requirement ("CM ELEVATE – Dataset Selection and Context Retention: ask users to select
  CM ELEVATE API or Legacy rather than switching automatically; the selected dataset must remain consistent across
  subsequent queries unless the user explicitly requests or confirms a change") and AskUserQuestion answers: "in
  context it should not ask, remaining it should"; a mismatch asks to confirm the switch; buttons "CM Elevate" and
  "CM Elevate Legacy".
- **Decision** (`schemes/cm_elevate.py` `_cm_elevate_dataset_choice`), for a bare "CM Elevate" (or a sub-scheme only):
  1. the chip marker "CM Elevate (applications)" -> applications (a choice made);
  2. **no CM Elevate dataset in the chat yet -> always ask** (`cm-elevate-dataset`, buttons "CM Elevate" /
     "CM Elevate Legacy"), whatever the words — money / sanction / FY words no longer go to Legacy unasked (D-064
     rule 2) and "applications / applicants" no longer go to the applications data unasked (D-090);
  3. **a chat on one dataset keeps it** (`_pin_cm_elevate_dataset` writes it into the question);
  4. a DATA question only the other dataset holds (`_cme_words_dataset`: Legacy's money / sanction / FY words, or the
     applications data's status / pending / level / sector words) -> **asks to switch**
     (`_cm_elevate_switch_pause`, raised in the route stage after DATA is decided, so a how-it-works question is never
     asked): "This chat is on X. This question asks for something only Y holds. Switch to Y, or stay on X?" —
     buttons "Y (switch)" / "X (stay)"; either pick is final for that question, and a switch moves the chat.
  Explicit switches stay as they were ("legacy" after an applications answer, "now give me for cm elevate" after a
  Legacy answer, a question naming CM Elevate Legacy).
- **Replaces** D-064 rules 2-5 (automatic Legacy on financial words, automatic applications on status words) and D-090.
- **Rollback:** restore the D-064 / D-090 body of `_cm_elevate_dataset_choice` (git history, 2026-11-02) and remove the
  route-stage `_cm_elevate_switch_pause` call.

### D-098 — Context memory: typed pause replies, one follow-up decision, the active topic, referenceable figures (2026-11-02)
- **Date:** 2026-11-02. BLH Bot UAT 2026-11-02 (4 of 10 failed on context). User: "for any query it comes it should
  remember the context and also the clarification if user won't click the buttons … it shouldn't be hard-coded …
  just enhance the current context memory".
- **Causes (VERIFIED, each reproduced live on the current code before the change):**
  1. UAT 3 — `_resume_scheme_pause` accepts only ONE bare scheme name; "compare both schemes by district" to the
     which-Focus pause went through untouched, the paused question was cleared, and the reply was rewritten against the
     last answer (Focus Plus only).
  2. UAT 4 — `context_policy.turn_kind` read "show the comparison visually in chart form" as FOLLOWUP (cue
     "compare-one-side") but the rewrite gate (c14, five older predicates) did not; no rewrite, no scheme, "Which
     scheme?". `_chart_view_request` did not know "comparison" / "visually".
  3. UAT 8 — "126 registered with ₹0" lived only in the answer's prose; the rewrite sees the previous question and
     filters (D-022), so "these 126" became all 1,71,107. The explicit question went to `_pmay_facts_query`, which read
     "sanction amount" as the measure and answered the statewide sanctioned total.
  4. UAT 10 — D-061 rule 4 asked "PMAY-G, Focus Legacy or Focus Plus?" whenever two or more single-scheme topics were
     open, even right after a PMAY-G answer (only in a long chat; a short one passed).
- **Decision (each layer generic — no scheme names, no new word lists; values from existing vocabularies, the SQL tree
  and the conversation's own state):**
  1. **Typed pause replies** (`c03 _resume_scheme_pause_typed`, step 0a'): "both / all of them / compare them" takes
     every offered scheme, several named schemes take those, one scheme or side word plus scope ("legacy by
     district") takes it, scope alone ("by district") is merged into the paused question. The scope is read by
     `context_policy.asked_levels`, `extract_year_keys`, `place_mentions`. **Never a guess:** the built question must
     hold every word the reply typed (bar pick / filler words), else the reply goes on untouched as before.
  2. **One follow-up decision:** a reference CUE `turn_kind` found (`cue:*`, `lead*`, not a bare fragment) opens the
     rewrite gate when there is an answered scheme turn (`c14 _c14_cue_followup`).
  3. **Active topic wins (amends D-061 rule 4):** a vague question runs in the topic memory's ACTIVE topic when that
     topic is one of the open single-scheme topics; the picker stays for a chat whose active topic is a comparison
     (or whose active topic the measure excluded). The active topic, not the last turn, so an aside keeps it.
  4. **Figures are referenceable:** `Turn.subsets` (durable snapshot + topic memory) holds each sub-count of a one-row
     result with its condition, read from the SQL tree (`context_manager.result_subsets`: `COUNT(*) FILTER (WHERE
     is_placeholder) AS placeholders` = 126). A follow-up quoting a figure after a pointer word ("these 126",
     `quoted_figures`) is rewritten deterministically (`_c14_figure_reference_question`: the user's words + "(the 126
     placeholders)" + scheme + scope), routed DATA, and the condition travels as the resolved entity
     `subset_condition` (MANDATORY in the SQL prompt). Without a stored condition the answer's own CLAUSE stating the
     figure is used (`figure_clause`; a D-022-style sentence-bounded tier, `answer_figure`).
  5. **Deterministic guards:** the rows of a figure-reference question must add up to the figure
     (`_c17_figure_reference_mismatch`, repair otherwise); `_pmay_facts_query` refuses a question stating a figure
     that is not a year / FY / date / instalment count (`_pmay_stated_condition`).
- **Rejected:** a model-only interpreter (prose rules fail under sampling, CLAUDE.md §5 — the live check showed the 9B
  turning "where" into "how many" and copying the year range); passing whole answer sentences (the year range became a
  filter); a "where / location" word list (user rule: no new lists); keeping D-061 rule 4 as is (user, 2026-11-02).
- **Consequences:** `Turn` and its snapshot carry `subsets` (older snapshots load with `[]`); result dicts of the
  PMAY-G fixed path carry `subsets`; `"subsets"` reaches the API response. Not covered yet: subsets of multi-row
  results (a figure for one row of a table), and "define <measure>" when the documents hold no definition.
- **Status:** Active.

### D-097 — Cross-scheme figures in code for all six schemes, villages and constituencies (2026-10-30)
- **Date:** 2026-10-30. User: "I want 100% UAT in cross scheme test cases also" (`reference_documents/Cross Scheme
  Test Cases.xlsx`, CROSS-1..20 and the generated 8,649-conversation set, last run 2026-10-13 under D-044).
- **Context:** D-066 put beneficiaries / money / village coverage of the four main schemes on fixed queries and kept
  CM Elevate, CM Elevate Legacy, a village and a constituency on the D-062 model path. On the re-run baseline, the
  20 sheet questions gave 3 gateway `ReadTimeout`s (84-121 s) and, on the model path, MGNREGA dropped ("No MGNREGA
  figure could be worked out"), PMAY-G's sanctioned ₹2,222.75 crore as its amount, village counts added across
  schemes ("97 villages across all schemes"), "24 districts" for every scheme and CM Elevate's districts "combined"
  for three named districts — the KI-387..392 defects again, for 41 of the 57 scheme combinations.
- **Decision:** `app/cross_figures.py` covers all six schemes (`SUPPORTED`), one village (`Plan.village`) and one
  constituency (`Plan.ac`), and a block grain ("block-wise", "each block": `Plan.grain`). CM Elevate: applications =
  `COUNT(DISTINCT request_id)`, no money and no financial year (said, never 0; `NO_MONEY` / `NO_YEAR`); CM Elevate
  Legacy: applicants sanctioned = records with `sanctioned_amount > 0` (2,820, the scheme's own rule, KI-166), money
  = `total_disbursement`. Constituency columns: MGNREGA `assembly_constituency_name` on `v_employment`, `ac_name`
  elsewhere (D-096); Focus Plus and CM Elevate do not record one. What c13 `_cross_scheme_gaps` says a scheme cannot
  hold (constituency, year, money) is handed to the plan (`Plan.gaps`) and never queried. "Applications" is a count
  word (no longer B-7's other measure). A combined total or combined district ranking leaves CM Elevate out and says
  so (I-13's rule kept); in every other shape CM Elevate is one of the schemes, ranked by applications in its own
  list. Exclusions still leave the four main schemes (`cross_figures.MAIN`). "Widest coverage across districts" is
  the statewide reach, not a per-district winner (CROSS-13).
- **Not changed:** village / block lists, "top N" villages or blocks, other measures (person days, job cards,
  wages) and several villages at once stay on the D-062 model path.
- **Harness:** `tests/sheet_runs/cross/` re-written for this answer shape (`grade.py` grades the scheme-tagged rows
  and the coded text; `truth.py` carries the D-066 / D-097 measures and the KI-393 geography; the CM Elevate dataset
  of a generated question follows `_cm_elevate_dataset_choice`).
- **Rollback:** `SUPPORTED = MAIN` and the two `village_code` / `assembly_constituency` lines in `plan()` restore D-066.

### D-096 — PMAY-G records the assembly constituency (2026-10-30)
- **Date:** 2026-10-30 (PMAY-G sheet re-test: every constituency failed, KI-445 was waiting for a decision).
- **Evidence (VERIFIED, read-only):** `curated.v_pmay.ac_name` / `ac_number` come from `dim_geography` through the
  house's `geography_key` — the same mapping MGNREGA's constituency uses. Every one of the 1,71,107 rows has one
  (0 NULL), 56 constituencies (the state's 56), 63 (constituency, district) pairs (8 ACs straddle two districts,
  as in MGNREGA). Title Case ('Amlarem'). Amlarem = 2,677 houses / ₹34.79 cr sanctioned, matching the sum of its
  villages.
- **Decision:** PMAY-G is constituency-capable (`scheme_registry.records_constituency=True`; c08
  `_AC_CAPABLE_SCHEMES`, c13 `_CROSS_AC_RECORDED`, `entity_resolver._AC_CONTENTS_SQL`). A constituency question is a
  fixed-query shape (`_pmay_facts_query` dim "ac", `UPPER(ac_name)`), with the Focus Legacy-style model-path pair
  (`_pmay_ac_name_case`, `_pmay_ac_filter_missing`) behind it; the SQL prompt's entity line names `ac_name` on
  `v_pmay` (no join). A constituency narrowed to a district / block (the drill-down overlap) stays on the model path.
- **Not decided here:** Focus Plus (`v_focus_plus.ac_name` exists but is unverified) and CM Elevate in the
  cross-scheme list stay as they were. The user may still want the ingestion team to confirm the PMAY-G mapping; the
  numbers above are the check this session could make.
- **Revert:** set `records_constituency=False` for PMAY-G and remove it from the two lists; the guard test
  `tests/test_scheme_registry_e5_2026_10_27.py` then names every other place.

### D-095 — The chart the officer names is the chart drawn; a comparison is charted by default (2026-10-30)
- **Context:** user rule 2026-10-30: "whatever chart the user asks — bar, pie, line — give it; if they say only
  'compare' or 'chart', give the chart; if a question has no chart, generate one". The UI refused named types the
  figures did not suit (D-088 last line, audit A-7 / G-1), drew two tiles and no chart for a comparison, drew nothing
  for a single figure asked as a chart, and missed "I want only bar".
- **Decision:** (1) a named type is drawn, alone (no switcher), whatever the rows; when the figures do not add up
  (schemes, overlapping counts, rates) or a line joins places, a one-line caveat says what not to read into it. This
  supersedes D-088's "refused … drawn as bars" for NAMED types only; unasked defaults keep D-088 (no misleading pie,
  donut or stack). (2) A comparison (two rows, or one row of figures in one unit with a compare word) shows its tiles
  AND a chart. (3) A single figure asked as a chart is drawn as asked, with breakdown chips. (4) A message of one type
  word and filler ("I want only bar") is a view request. (5) What is drawn is decided by ONE pure function,
  `viewPlan()` in `frontend/src/chat/analytics.js`; `Messages.jsx` renders it, and the unit tests and the live chart
  suite grade the same function.
- **Consequences:** `frontend/tests/chart_requests.test.js` (28 requirement cases); `tests/live_chat_charts.py` +
  `frontend/tests/chart_live_grade.mjs` (live, 29 chats). Three audit tests now assert the caveat instead of the refusal.

### D-094 — Knowledge routing by the question's FORM; multi-part RAG; deterministic related-fact and number backstops (2026-10-29)
- **Date:** 2026-10-29 (knowledge fix prompt `megh_chatbot_knowledge_fix_prompt.md`, KR1-KR13).
- **Decision:**
  1. **Router (KR1):** the existing cue rules + LLM classifier stay (no new classifier stage: D-032/D-036
     forbid behaviour outside stages, CLAUDE.md forbids drive-by rewrites). A rules layer
     `c14 _knowledge_form_question` (`_KF_FORMS`: rate, registration_details, process, distance,
     guaranteed_days, funding_pattern, design_count, launch_admin, loan_or_grant) turns a DATA verdict into
     KNOWLEDGE when the question has a knowledge FORM and no place, year, grouping, ranking, comparison or
     figure word (`_KF_FIGURE_VETO`). Logged as `intent override=knowledge_form form=…`. The classifier
     prompt got 7 few-shot form pairs. The hybrid split (MIXED) accepts a knowledge-form left half; the
     scheme-years shortcut skips launch words; a knowledge-form question naming a scheme overrules a 4B
     scope refusal.
  2. **Retrieval (KR3/KR11/KR12):** `rag.retrieve` also searches each part of a multi-part question
     (`_sub_asks`), a related-facts "facet" query (launch / amount / sub-schemes / documents / eligibility /
     apply), and the English wording of a romanised-Hindi question (`_looks_hinglish` -> `translate.to_english`);
     searches run in parallel; top-n +4 for multi-part; an FAQ entry whose heading asks the same question
     goes first and is labelled OFFICIAL FAQ ANSWER (`_faq_match`).
  3. **Composer (KR3/KR5/KR6):** per-facet related-facts lines, "answer every part, open with what the
     passages say", national vs Meghalaya rules apart, and `scheme_registry.KNOWLEDGE_DISTINCTIONS`
     (what each scheme is beside its namesake) in the naming note and the multi-scheme prompt.
  4. **Deterministic backstops (CLAUDE.md §5 pattern):** `ground_answer` keeps a flagged unit whose numbers
     and ≥80% of its content words are in the passages, and drops a unit with a number in neither the
     passages nor the question; never empties the answer. After composing: the matched FAQ entry's dates /
     numbers (`_with_faq_facts`), the one "Ministry of …" of a launch answer (`_with_related_ministry`) and
     the programme's sub-scheme count (`_with_subscheme_count`, record counts ignored) are appended when
     missing. A sentence never splits after an initial ("Conrad K. Sangma").
  5. **Citations (KR4):** `sources` / `citations` are the pieces the answer's sentences lean on
     (`_supporting_chunks`), not the top pieces retrieved.
  6. **Next steps (KR9):** after a knowledge answer the last chip is one statewide data question
     (`followups._KNOWLEDGE_DATA_NEXT`); a what-is chip is not offered after a definition question.
  7. **Bare "FOCUS" acronym:** "what does FOCUS stand for" reads Focus Legacy (only the original FOCUS
     documents spell the acronym out); every other bare "Focus" still asks (CLAUDE.md §4). Vocabulary
     ("loan") no longer settles a bare Focus.
- **Reason:** live golden suite `tests/live_chat_knowledge.py` 85/108 (78.7%) before; 13 misroutes, 4
  dropped related facts, 1 wrong-scheme answer, 1 wrong FAQ reading. Prose rules alone flipped between
  runs (K5 ministry, K9 "15", CFC date), hence the backstops.
- **Result:** golden 114/114 (100%) in two consecutive runs; RAG eval 188 q correct-or-honest 95.7% ->
  **98.4%** (final run), wrong refusals 0, "not covered" handled 100%; 1.7-2.3 s per answer alone. The question's
  searches run in parallel but at most 6 at a time per worker (`_bounded_search`), with two Qdrant retries.
- **Alternatives:** a separate LLM question-type classifier node returning DATA/KNOWLEDGE/MIXED/... with a
  confidence (the prompt's KR1 suggestion) — not built: an extra 4B call on every turn (E1 measured +2.3 s
  for one), and the form rules + existing classifier already route 100% of the suite.
- **Status:** Active.

### D-093 — One spelling normaliser before routing; the "user's own words" are read with names spelt right (2026-10-29)
- **Date:** 2026-10-29. The user's spelling brief (`megh_chatbot_spelling_fix_prompt.md`, T1-T10, "I want to achieve
  100%"). Live before: 13/25 (`tests/live_chat_spelling.py`): "ribhoy" answered for the chat's East Khasi Hills,
  "fokus plus" / "fokus+" got a picker, a made-up district got the generic "I only know Meghalaya" reply.
- **Decision:**
  - NEW `app/spelling.py`, called first in c14 `_turn_context_stage`. It rewrites a misspelt **scheme**, **district**
    or **block** name to its canonical form, and a misspelt domain word from a closed list ("mony" -> money).
    Matching, best first: exact alias -> same sound (y/i, k/c/q, w/u, ph/f, ee/i, oo/u, h after a consonant and
    doubled letters ignored) -> Damerau-Levenshtein on the sound (1 edit up to 5 letters, 2 up to 10, 3 above),
    same first letter, one clear winner. Acronyms (EKH) only exactly. A spelling the resolver already reads is left
    exactly as typed. A village is written by name only after the word "village" with one clear closest name;
    otherwise `entity_resolver.resolve_village` reads it by sound before its trigram search (a close race keeps
    the pick-list).
  - Names come from the resolver catalogue at run time; the hand-kept part is the data file
    `data/spelling_aliases.yaml` (scheme aliases, bare-"focus" typos, extra district aliases, the closed word list).
  - **`raw_question` (the user's own words) is the spelling-normalised text.** Routing, the turn kind, the vague-topic
    picker and the rephrase checks read it; the transcript keeps what was typed. Before this, "how much mony does
    fokus+ give per houshold" was routed by its typos to the data path.
  - A place the user named that matches nothing (`spelling.unresolved_place`) is never filled from the chat
    (c14 `_same_scheme_context_year`) and is answered "I couldn't find a district / block / place called 'X' in
    Meghalaya. Did you mean …?" (c13 `_c13_unknown_place_pause`, also used by c09 for a made-up name the extractor
    tagged; a real place outside Meghalaya keeps the OutOfScope reply).
  - The topic picker takes only a short reply (5 words or fewer) or its chip as a pick; a longer message is a new
    question (topic_memory `_pick_reply`).
  - Every corrected answer opens "Showing results for **Ri Bhoi** (you typed 'ribhoy')." (`_attach_preface`);
    such answers are kept out of the semantic cache.
- **Alternatives considered:** letting the 9B rephraser fix names (rejected: it already ran, and its rewrite is
  checked against the typed words, so a typo it fixed was rejected as a changed measure); hard-coding the ten strings
  (rejected by the brief); a generic English spell-checker (none installed, and it would "correct" Khasi / Garo names).
- **Consequences:** the "which scheme?" picker puts a clear best guess first (all six stay). The measure-narrowed
  picker (user rule "picker shows only relevant schemes") is unchanged, so not every picker lists all six.
- **Rollback:** in c14 `_turn_context_stage` set `raw_question = question` before the corrections and pass `question`
  (not `_spelt.text`) on; the rest is inert without it.

### D-092 — One money format, one dataset-facts registry, multi-part questions answered in full (2026-10-29)
- **Date:** 2026-10-29. The user's data-accuracy brief (`megh_chatbot_fix_prompt.md`, ten known answers D1-D10,
  root causes RC1-RC8; "fix in general, not these 10").
- **Decision:**
  - **Money (settles KI-449):** ₹, Indian grouping, the exact amount, then "(≈ ₹X crore)" / "(≈ ₹X lakh)"; no ".00";
    a lakh column stays lakh with its crore size. One writer (`_c12_money`) and one pass over every data answer
    (`_c12_normalise_figures`); the unit comes from the column suffix or the dataset registry, never guessed.
  - **Dataset facts registry:** `scheme_registry.DATASETS` (grain, money unit, unit verified, provisional, has dates,
    sub-scheme column, owned tables). Cards and chat read the same flags. Years held stay live (`_SCHEME_DATA_YEARS`).
  - **Caveats are said:** provisional / unverified money and absent years get a visible "Note:" line.
    **Amended 2026-11-03 (user decision):** the provisional / unverified-money Note is removed from chat answers
    ("it is coming for every query"); the absent-year Note stays, and the cards keep their "*".
    Same day: the absent-year Note names the financial years the scheme's data covers ("Note: Focus Plus data
    covers FY …", read live from `_SCHEME_DATA_YEARS`), not the years it lacks; same trigger (all-years answer,
    a gap in the years held). Several schemes over different periods: one Note with every scheme's years.
  - **Superlatives:** the winner plus the next two, written by code; ties said.
  - **Multi-part questions:** a total + a "which … most" run as two questions in the conversation layer and are merged
    in the order asked; PMAY-G "total and completed" adds the breakdown that sums to the total.
  - **Routing:** one named dataset with sub-schemes keeps "which scheme" inside itself.
  - **SQL validation:** an invented constant answer, another scheme's tables and an unordered superlative go to repair.
- **Alternatives considered:** a general LLM sub-ask splitter (rejected: another sampled step before every data
  question); formatting money in the composer prompt only (rejected: CLAUDE.md §5, prose rules fail under sampling).
- **Consequences:** answers are longer for money (exact + size). Tests pinning the old "₹2,185.26 crore" form were
  updated to the new form. Live golden suite `tests/live_chat_golden.py`.

### D-091 — A Devanagari question is translated to English whatever button is selected (2026-10-29)
- **Date:** 2026-10-29. RAG fix report (`megh_rag_fix_report.md`) Issue 9: "मनरेगा क्या है और कितने दिन का काम मिलता है?" got
  "Which scheme is your question about?".
- **Decision:** `translate.script_language` detects Devanagari by its letters; `routers/query._answer` then runs
  `translate.to_english(q, "hi")` before anything else (both endpoints). Switch `TRANSLATE_SCRIPT_ENABLED` (default
  true). `TRANSLATE_ENABLED` (Khasi / Garo buttons, Latin script) stays the user's 2026-10-15 English-only choice.
  The answer is in English (the UI has no Hindi strings).
- **Rollback:** `TRANSLATE_SCRIPT_ENABLED=false`.

### D-090 — "applications / applicants / applied" settle a bare CM Elevate as the applications dataset (2026-10-29)
- **Date:** 2026-10-29. User decision (AskUserQuestion) on RAG fix report Issue 8; narrows D-064 / KI-407 rule 4.
- **Decision:** `_cm_elevate_dataset_choice` (`schemes/cm_elevate.py`), in order: money / sanction / loan words -> Legacy;
  applications-only words -> applications; the chat's thread; NEW `_CME_APPLICATION_WORDS` -> applications; otherwise
  ask. So a new chat's "How many CM Elevate applications are there?" answers 8,921, a Legacy thread keeps Legacy, and
  "CM Elevate records in Ri Bhoi" still asks.
- **Rollback:** remove the `_CME_APPLICATION_WORDS` branch.

### D-089 — Answer with defaults: no place = statewide, no year = all years (new chats too) (2026-10-29)
- **Date:** 2026-10-29. User decision (AskUserQuestion) on RAG fix report Issue 6: all 8 home-screen starter
  questions were stopped by a "which area?" / "which year?" pause. Reverses, for questions that name neither, D-056's
  new-chat district ask and D-053 / D-065's new-chat year ask (and the 2026-10-27 "keep asking" choice).
- **Decision:** NEW setting `NEW_CHAT_ASKS_SCOPE` (default **false**) gates both asks in the clarification gate (c13). The
  ANSWER_DEFAULTS path then appends "for all of Meghalaya" / "across all financial years" and the answer says so.
  "this year" / "current FY" / "the latest year" -> the latest FY the scheme holds (`_C13_THIS_YEAR_CUE`, sets
  `year_key`). A chat's remembered place / year still wins (D-055). Real ambiguity still asks (bare Focus, bare CM
  Elevate with no dataset word, no scheme). A named district / block that resolves to nothing is said plainly with
  district chips (`_c13_unresolved_named_place`, rule `unknown-place`) instead of being defaulted to statewide.
- **Rollback:** `NEW_CHAT_ASKS_SCOPE=true`.

### D-088 — A time budget for SQL repairs; a repeated repair is asked once more (2026-10-29)
- **Date:** 2026-10-29. Open-bug sweep (user: "all open bugs need to be fixed now"); KI-013, KI-003.
- **Decision:** `_repair_sql` (c11, a stage — no graph node changed) starts no repair after
  `REPAIR_TIME_BUDGET_SECONDS` (40) of the request, read from `turn_trace.elapsed()` (the trace now records its start).
  The turn then ends exactly like a spent repair budget ("couldn't build a working query", 200) instead of running into
  the router's 60 s ceiling (504). A repair that returns the failed query unchanged (`_c11_same_sql`, compared on the
  parsed tree) is asked once more with that said; otherwise the next attempt would repeat the identical failure.
- **Not changed:** the repair count (3, D-072), the verifier, the guards.
- **Rollback:** raise `REPAIR_TIME_BUDGET_SECONDS` to 60.

### D-087 — The SQL prompt's data figures are read live from megh_db (`app/data_facts.py`) (2026-10-29)
- **Date:** 2026-10-29. User rule: "the complete project is dynamic" — after the scheme cards (KI-571) and the
  prompt both showed stale figures (CM Elevate "8,867 records", megh_db 8,948; Focus Legacy "11,906" and "~11,904"
  groups, "14,569" and "~14,566" payments in the same block).
- **Decision:** every figure in `schema_context` that states what the data holds today (row / NULL / distinct counts,
  shares, the years held, the Ri Bhoi "men" example) is a `[[name]]` token; `data_facts.FACTS` (89 figures) fills it from
  11 fixed, parameter-free SELECTs over the curated views and dims (never a privacy table), on the read-only pool in a
  READ ONLY transaction. `refresh_loop()` runs from the lifespan now and every 10 min; `build_schema_context` and
  `available_metrics_text` only read the result (no DB wait in a turn). A failed query keeps the last good figures;
  before the first success each token shows the figure typed before (the prompt reads exactly as before). Changes are
  logged (`data_facts: N figure(s) changed`); `/metrics` shows `data_facts` (as_of, errors).
- **Typed on purpose:** dated incident history ("confirmed live 2026-09-13 … dropped 4,670"), figures from outside
  megh_db (requirement workbook 2,847 / 13, client-API drift 89, raw-file "8,436 source rows"), thresholds ("fewer than
  15"), the Focus Legacy name-spelling measurements (5a), and the structural year rules (Focus Legacy rule 7 "FY 2023-24
  is absent", CM Elevate Legacy "only two years") — a new year there needs a person to rewrite the rule.
- **Rollback:** none needed; to freeze, stop the lifespan task (tokens then show the typed defaults).
- **Claims (same day, the follow-up):** the structural rules a number cannot carry are `data_facts.CLAIMS` (17): Focus Plus (two amount values, amount NOT NULL, 12.5K one row per person), PMAY-G (six stage names), CM Elevate (onhold / is_withdraw FALSE on every row; file-status, data_verified and sector value lists), Focus Legacy (the four years with FY 2023-24 absent, the 5,000 identity, bank_details_current never FALSE, products 100% in FY 2021-22/22-23), CM Elevate Legacy (only FY 2024-25 / 2025-26; loan_entity, desanctioned_reason_raw value lists; refused_flag_raw never FALSE). Each is a read-only SELECT + a check, run by `check_claims()` after every refresh. A broken claim is logged at WARNING ("RULE NO LONGER TRUE … Rewrite it in app/schema_context.py"), POSTed once to `ALERT_WEBHOOK_URL` (the guardrail's sender, D-080; counts only) and listed in `/metrics` `data_facts.broken_claims` until it holds again; a failed query leaves the claim as it was. The rule text is NOT rewritten automatically: a person decides the new wording (a wrong automatic rewrite is worse than a loud warning). Live 2026-10-29: 17/17 hold; deliberately wrong expectations were caught (7,392 'Valid' rows, a "new" year, 292,385 ₹2,500 rows).

### D-086 — SQL examples from the reviewed YAML banks again (default `yaml`); `yaml_meaning` added (2026-10-29)
- **Date:** 2026-10-29. RAG plan B5 (Task 13); user decision after the measurement ("yaml").
- **Evidence:** held-out NL->SQL set, 74 q, same code, 0 network errors (results `2026-10-29_1323/1333/1339_b5-*.json`):
  yaml **42/74**, SQL first try 42/43, **1 repair**; yaml_meaning 41/74, 41/42, 4 repairs; qdrant 41/74, 37/42,
  **8 repairs**, 3 verifier rejections; median 11.3 / 10.5 / 8.5 s. Accuracy within noise; meaning ranking changed the
  examples on 30/37 turns with no measurable gain; qdrant's examples are unvalidated (KI-438).
- **Decision:** `SQL_EXAMPLES_SOURCE=yaml` (config default and dev `.env`; deploy `.env` must match). `yaml_meaning`
  (`sql_examples._rank_yaml`) stays available. megh_sql_metadata is then not read for SQL (its view / join notes leave
  the prompt) — reverses the 2026-10-27 evening instruction for the SQL examples only.
- **Rollback:** `SQL_EXAMPLES_SOURCE=qdrant`.

### D-085 — Query plan stage 2a: built during the turn beside the guardrail call; built, measured, OFF by default (2026-10-29)
- **Date:** 2026-10-29. RAG plan E1 stage 2 (the user's go-ahead "do the next step") and E2's "run the guardrail in
  parallel with the plan". Files: `app/query_plan.py` (`start_for_turn`, `cancel_for_turn`, `take_for_turn`,
  `turn_plan`, `shadow(pending=)`), c14 `_guardrail_check(session=)` / `_turn_edge_stage`, c13 `_update_context`,
  `app/config.py` `QUERY_PLAN_IN_TURN`; NEW `tests/test_query_plan_in_turn_2026_10_29.py` (19).
- **Evidence first (D-078's "collect live agreement"):** `logs/query_plan_shadow.jsonl`, 730 turns / 378 distinct
  questions (2026-10-27 19:52 .. 2026-10-29 13:19): intent 718/730 (98.4%), schemes 680/713 (95.4%), place level
  388/394, years 650/657, measure 37/37, top N 10/10; plan p50 766 ms, p90 1,250 ms. Most disagreements are turns
  whose `actual` is empty (fixed-answer paths), not plan errors; real plan misreads: sub-scheme names in `schemes`
  ("CM Elevate Dairy Development"), a comma string instead of a list. Intent splits are debatable ("coverage under
  CM Elevate in Ri Bhoi": plan DATA, pipeline KNOWLEDGE). No model field is read yet: that changes answers and needs
  the held-out NL->SQL set first.
- **Decision:** for a NEW question (not a follow-up, pause reply or canned greeting; only where the guardrail model
  call runs) the plan task starts right before the guardrail model call, kept in `session.turn_context` (in-process,
  never persisted). Nothing awaits it; a guardrail refusal cancels it; the end-of-turn shadow reuses it
  (`plan_from: "turn"`, `plan_question`) instead of a second call, or cancels it when the turn was neither data nor
  knowledge. `turn_plan(session)` is the reader API for stage 2b.
- **Measured live (2026-10-29, VPN, in-process, real gateway + DB; 6 own questions x on/off, alternated):** answers
  identical; plan reused 6/6; but EVERY on-turn was slower: median **11.8 s -> 14.1 s**, and the plan itself
  0.8 s -> 1.5-3.0 s. The two qwen4-deploy calls queue on the gateway rather than overlap (INFERRED).
- **So `QUERY_PLAN_IN_TURN=false` by default** (= stage 1 exactly; pinned by a test). Turn it on only together with
  a stage that reads the plan and drops a classifier call of its own (stage 2b), or after the gateway serves
  concurrent 4B requests in parallel; re-measure with the scratch A/B (`answer_question` on vs off) first.
- **Stage 2b, first field = intent (same day, user: "do the next step"):** c13 `_c13_intent_by_rules(question,
  session)` — after every cue rule, where the last-resort classifier call was, it returns this turn's plan intent
  when the plan was read from the same words and says DATA / KNOWLEDGE (`pipeline_decision stage=intent
  source=query_plan`); OTHER, no plan or other words -> the classifier call as before. The B3 safety net and every
  c14 post-rule still run. c14 passes the session only when a plan exists (so with the flag off the call is byte-for-byte
  the old one). Offline, on the 383 shadow-log questions: only **39 (10%)** reach that call; there the plan matched the
  pipeline 36/36 when it said DATA / KNOWLEDGE (the 3 others were OTHER -> fallback).
- **Held-out NL->SQL set, same code, back to back (`2026-10-29_1355_e1-2b-plan-off`, `_1401_e1-2b-plan-on`):** 42/74
  both, 0 regressions, 0 fixed, identical outcomes; per question median 8.05 s off vs 8.40 s on (mean 8.64 vs 8.99;
  45/74 slower on). Live A/B (8 own questions, half falling past the rules): no clear latency difference (order
  effects dominate); one routing gain — "What about Focus Legacy groups in East Khasi Hills?" got the figures on, the
  "published information does not contain" knowledge reply off.
- **Verdict:** the reader is correct and safe but saves a call on ~10% of turns while the in-turn plan costs ~0.35 s
  on every new turn today, so **`QUERY_PLAN_IN_TURN` stays false**. What would pay: one call reading the guardrail
  verdict AND the plan together (E2 + E1 merged; a safety-behaviour change, needs its own go-ahead and the guardrail
  test suites), or a plan reader that replaces a call made on most turns.
- **Merged guardrail + plan call: measured, NOT built (same day).** Live, sequential, 8 questions x 2: the guardrail
  call median **0.16 s** (mean 0.40 s), the plan call median **0.80 s** (mean 2.31 s). One call returning both must
  write the 9-field plan before the verdict is complete, so the safety check on the critical path would grow from
  ~0.16 s to ~0.8 s on every new question, to save the intent call on ~10% of turns, and it would ask the 4B model
  for two jobs in the safety call. Revisit only if a plan reader replaces calls on most turns.
- **Status:** Active (code present, off). E2's latency goal is NOT met by parallelism on today's gateway.

### D-089 — Chat UI audit product decisions (2026-10-29, user: "use your recommendations")

**DOCUMENTATION CONFLICT — NEEDS VERIFICATION: the merge of PRs #20/#21 (2026-10-29) brought a second D-089 from the chat UI audit branch; both sessions used the same number. Renumber one of them.**
- **Context:** 12 audit findings needed a product decision (KI-574). The user chose the recommended option for each.
- **Decision:**
  1. **J-4 / J-5 (narrows D-056 part 1):** a NEW chat whose question names its own scheme is answered for all of
     Meghalaya (said in the banner, "by district" chip) instead of the district pause. The year is still asked when
     none is given (D-053 / D-065 stand: no silent year), so it costs at most one tap. A question that names no
     scheme still asks scheme -> district -> year. Revert: drop the `_named_schemes` clause in c13
     `_data_clarification_stage`.
  2. **J-10 (KI-126):** a name shared by 2–3 villages in different blocks is answered for each (one row per village,
     with its block; banner names them). More twins still ask.
  3. **G-10:** Focus Legacy members keep the D-066 figure (SUM over payments); the answer says a group paid twice
     counts twice. Counting each group once waits for the data team and a live check.
  4. **H-5 / H-6 / H-8:** the scope banner names the place type ("Umling block"), says "All years (FY … to …)" when
     no year was used, and prints 3+ consecutive years as a span. Topic labels are unchanged.
  5. **B-5:** the dead `isCrossSummary` UI path is deleted.
  6. **K-6:** Edit / Regenerate delete the replaced turns on the server (`keep_turns`; app.query_audit untouched)
     and restore the context saved with the first replaced turn.
  7. **K-16:** the language menu is the "Question language — answers are in English".
  8. **X-4:** Line is offered only when the x-axis is a period.
  9. **X-16:** the app is light-only (`color-scheme: light`); no dark theme.
- **Where:** `docs/audit_fix_log.md` (each ID), `tests/test_chat_ui_audit_more_2026_10_29.py`.

### D-088 — One measure-kind rule for every total, share and stack (2026-10-29)

**DOCUMENTATION CONFLICT — NEEDS VERIFICATION: the merge of PRs #20/#21 (2026-10-29) brought a second D-088 from the chat UI audit branch; both sessions used the same number. Renumber one of them.**
- **Context:** the chat UI audit (section G) found the UI adding overlapping figures in four places (donut centre,
  "% of the total", pivot Total row / column, stacked-bar top) and the backend sending `stacked` for any 2-label,
  1-measure result: "Total 11,000" villages for a state of about 7,000; households + houses added; job cards and
  percentages stacked across years. The frontend and backend kept separate non-additive word lists that disagreed.
- **Decision:** every measure column has a kind read from its name — `rate` (%, average, per, min / max, growth …),
  `stock` (job cards, cumulative), `flow` (money, days, payments) or `distinct` (villages, households, beneficiaries,
  members) — from ONE list, `app/measure_kinds.json`, with a checked copy in `frontend/src/chat/measureKinds.js`
  (`tests/test_chat_ui_audit_totals_2026_10_29.py` fails when they differ). A measure is added only along a dimension
  its kind allows: flow across places and years; distinct and stock across places only; rate never; nothing across
  schemes. The UI (`columns.canAdd` / `dimOf`) and the backend (`measure_kinds.can_add` in `_chart_hint`) apply it.
  A chart type the rule forbids is refused with a one-line note and drawn as bars. **Superseded for a type the
  officer NAMES by D-095 (2026-10-30): it is drawn, with a caveat; defaults are unchanged.**
- **Consequences:** no donut / share / Total across schemes or across years for counts; a stack only where it adds
  honestly. A real union of villages across schemes is computed by `cross_figures` (overlap mode) instead.

### D-084 — Frontend lint and tests: ESLint (with the no-regex rule) + `node --test` (2026-10-29)
- **Date:** 2026-10-29 (E11 UI fixes, KI-570). Files: `frontend/package.json` (`lint`, `test`; dev deps `eslint`
  9.17.0, `@eslint/js` 9.17.0, `eslint-plugin-react` 7.37.2, `eslint-plugin-react-hooks` 5.1.0, `globals` 15.14.0,
  exact pins), NEW `frontend/eslint.config.js`, NEW `frontend/tests/*.test.js`.
- **Context:** the frontend had no linter and no JS test runner (audit 2026-10-23, "Housekeeping"); JS behaviour
  was tested only from Python (`tests/test_table_view_2026_10_28.py`, `test_cross_compare_card_2026_10_22.py`
  bundle the real modules with esbuild and run them in node).
- **Decision:**
  - `npm run lint` = ESLint flat config: `@eslint/js` recommended + React + hooks rules, and `no-restricted-syntax`
    for a regex literal, `new RegExp` and `RegExp()` — the D-046 / D-047 "no regex anywhere" rule is now enforced
    in `src/` and `frontend/tests/`, not only written down.
  - `npm run test` = Node's built-in runner (`node --test "tests/**/*.test.js"`), no extra dependency. Plain
    modules are imported directly; a `.jsx` module is bundled with the esbuild Vite already ships
    (`tests/admin.test.js`).
  - The Python-side frontend tests stay; they remain the pytest gate.
- **Alternatives:** Vitest / Jest (an extra framework and dependency tree for 3 files; Node's runner has mocks
  and fake timers built in).
- **Status:** Active. `npm run lint` 0 problems and `npm test` 13/13 on 2026-10-29.

### D-083 — qwen3-reranker always on; no switch; local jina re-ranker removed (2026-10-29)
- **Date:** 2026-10-29. User rule (stated repeatedly; recorded here so no session or teammate switches it off again).
  Files: `app/llm.py` (`call_reranker`, `_RERANK_*`), `app/rag.py` (`retrieve`, `_rerank`), `app/config.py`
  (`reranker_problem`; `RERANKER_ENABLED`, `RAG_LOCAL_RERANKER`, `RAG_RERANK_CHARS` removed), `app/local_rank.py`
  (keyword vectors only), `app/main.py` (startup ERROR), NEW `tests/test_reranker_always_on_2026_10_29.py`.
- **Context:** `qwen3-reranker` was off from 2026-08-29 (D-005, "inverts relevance"); the local jina cross-encoder
  was on, then off, on 2026-10-15. Every new session read "off" in config and docs and kept it. Probe 2026-10-29
  (VERIFIED, `megh_knowledge`, the 137 `doc` questions of `tests/rag_eval/testset.json`, top 12 from Qdrant; the right
  piece was in the 12 for 133):

  | Order of the 12 | Right piece 1st | In top 3 | In the 8 sent to the composer |
  |---|---|---|---|
  | vector only (before) | 60.2% | 82.7% | 98.5% |
  | reranker, bare question (the D-005 call) | 25.6% | 59.4% | 87.2% |
  | reranker, Qwen3 yes/no format | 55.6% | 83.5% | 95.5% |
  | **reranker (Qwen3 format) fused with vector order, RRF k=60 (chosen)** | **62.4%** | **88.0%** | 97.7% |

  Gateway latency: median 0.1 s, max 0.6 s for 12 pieces; 0 errors in 137 calls. D-005's "inversion" was the bare
  call, not the model.
- **Decision:**
  - every knowledge question is re-ranked by `qwen3-reranker` on the gateway (`rag._rerank`, called from
    `rag.retrieve`, so `answer_from_kb` and `answer_from_kb_multi` both get it). There is **no setting** to turn it
    off: the switches were deleted, and a `.env` that still sets one fails at startup (pydantic "extra inputs").
  - `call_reranker` sends the Qwen3 format (system judge prompt, `<Instruct>` / `<Query>`, `<Document>`).
  - the re-ranker's order is fused with the vector order by rank; it is not used alone (row 3 above loses pieces).
  - `score` stays the meaning (cosine) similarity: `RAG_MIN_SCORE` and the confidence tiers are tuned on it, and the
    deployed re-ranker scores nearly every piece 0.99+ (KI-450). Its score is kept as `rerank_score`.
  - the 4B prompt-scoring fallback inside `call_reranker` is removed. A gateway failure keeps the vector order for that
    question and logs a WARNING; the answer is still given. An empty / `CHANGE_ME` `RERANKER_API_KEY` logs an ERROR at
    startup (`config.reranker_problem`).
  - the local jina re-ranker (`local_rank.rerank`, `RAG_LOCAL_RERANKER`) is removed (user decision).
- **Rejected:** a switch defaulting to on (it is how it got switched off before); the re-ranker's order alone (worse
  than vector order on this KB); using its score as a cut-off (saturated, KI-450); re-ranking the SQL examples from
  `megh_sql_metadata` (not asked; one change at a time).
- **Rule for future sessions:** if the re-ranker misbehaves, **fix it** (call format, deployment, fusion) — do not
  disable it. `tests/test_reranker_always_on_2026_10_29.py` fails if a switch, the local re-ranker, the fallback scorer
  or the bare call comes back.
- **Answer eval (VERIFIED, `tests/rag_eval/run_eval.py`, 188 questions, `megh_knowledge`, 2026-10-29; `results/2026-10-29_d083_*.json`):** vector only -> with the re-ranker: correct 91.5% -> **95.1%**, wrong 3.7% -> **0.6%**, "not covered" handled honestly 91.7% -> **100%**, correct-or-honest 91.5% -> **95.7%**, right piece in top 3 77.4% -> 83.5%, answers with a made-up sentence 14.0% -> 11.8%, 4.2 s -> 3.7 s per question. The judge moves about +/-2 points between runs.
- **Status:** Active. OFFLINE-VERIFIED (tests), LIVE-VERIFIED in-process and over HTTP on :8401 (both knowledge questions called `/rerank`, 200 OK). Supersedes D-005.

### D-082 — Answer formatting: one money formatter, a figure-to-label check, code-written figures per shape (2026-10-29)
- **Date:** 2026-10-29. RAG plan E9 (composer); evidence `new_docs/Composer_Audit_Report_2026-10-27.md`.
  Files: c12 `_c12_money` / `_c12_fmt_value` / `_c12_label_misbinds` (`c12_answer_numbers.py`), c12s `_c12s_e9_body` /
  `_c12s_e9_framing` / `_c12s_e9_frame_default` (`c12_answer_shapes.py`), `compose_response` (c13),
  `app/config.py` `ANSWER_TEMPLATES_ENABLED`, `schemes/mgnrega.py` `_mgnrega_money_units` (KI-448).
- **Context:** of 43 eval answers 15 were clean, all single figures; the multi-row shapes carried the errors the
  number check cannot see (it asks only whether a figure EXISTS in the result): a row's own figure stated as a gap
  (CL-05), a % written as lakh (MG-10), a garbled change (MG-12), names left out (PM-06), lines nobody asked for, and
  three money formats in one answer (PM-10, FP-05).
- **Decision:**
  - **One money formatter** for every figure code writes: ₹, Indian grouping, a `_lakh` / `_cr` column kept in its own
    unit (MGNREGA reads lakh, as the composer copies it), a rupee column as crore / lakh / exact rupees by size, and a
    non-zero amount never "₹0.00 crore" (it drops a unit). Counts keep their grouping: Indian vs Western for counts is
    an open product decision.
  - **Figure-to-label check** beside the number check in `compose_response`: a figure tied to a row name ("Mylliem —
    398,150", "8,215 in FY 2022-23", the only name in its clause) must be that row's; a figure followed by more / less /
    higher / ahead must be a difference; a % never written as ₹ / lakh / crore and money never as %; a figure labelled
    with another measure's words ("41,210 person-days" for households) is wrong. Any hit → the strict retry, then the
    fallback. Narrow on purpose: a figure it cannot tie to one row or measure is left to the number check. Stricter only.
  - **Templates per shape** (`ANSWER_TEMPLATES_ENABLED`, default true): ranking / compare / trend / breakdown answers
    take every figure-bearing line from code. The 9B writes one opening line that may hold no figure (years, the
    query's own literals and the list size excepted) and no verdict word for the shape ("highest" on a lowest-first
    list, "rose" on a trend); otherwise code's own opening line is used. Extras only when asked: a ranking's gap line
    (gap / ahead / how far / compare …), a trend's highest / lowest (peak / highest / lowest …), a split's total
    (total / overall …) and shares (share / % …). Percentages differ in "percentage points". The shaped fallback is the
    same templated answer. The composer still writes the whole answer for single figures, profiles, two-way tables,
    lists, yes / no questions, premise corrections (premise_check's "The question treats …" note), a caller's own
    figures (`extra_numbers`), ROLLUP totals and no-usable-value results. Wording notes ("write lakh", "name places in
    plain words") go to the opening line; a scheme's style shots do not keep the composer.
- **Alternatives:** keep the composer writing figures and add guards only (the audit shows the guards cannot see wrong
  claims); give the composer the template sentences to copy (it re-words them); move the composer to a larger model
  (bigger change; re-measure after this one, audit §5 item 8).
- **Rollback:** `ANSWER_TEMPLATES_ENABLED=false` (the composer writes the whole answer from `_SHAPE_GUIDE`, and the
  shaped fallback is the pre-E9 one). The money formatter and the label check have no flag (stricter only).
- **Not done (KI-449):** the scheme writers (`_fp_rupees`, `_pmay_money`, `_cml_inr`, Focus Legacy's breakdown writer,
  cross_figures) keep their own formats; the shape still measures `metrics[0]` / the ORDER BY key, not the asked measure
  (lane B2 CMP-02).
- **Status:** Active. OFFLINE-VERIFIED (tests/test_answer_format_e9_2026_10_29.py); LIVE-VERIFIED on 12 questions
  in-process (VPN up); the held-out golden set was NOT run (user: at a different time).

### D-081 — Fixed answers authorised where they return; cross_figures from its plan; BOOT_GUARD_ENFORCE (2026-10-29)
- **Date:** 2026-10-29. RAG plan E12 (KI-418..421, gateway CA). Files: c13, `schemes/focus_legacy.py`,
  `schemes/mgnrega.py`, `app/auth.py`, `app/routers/admin.py`, `app/routers/stats.py`, `app/llm.py`, `app/config.py`.
- **Context:** four fixed answers returned before the graph's `authorize` node (KI-419). The lane plan (A1 SEC-03)
  said to authorise `_res["sql"]` for cross_figures. Measured offline with the real functions: that bundle's places
  are bind parameters (`filter_values` sees none) and every statement counts `DISTINCT village_code`, which
  `infer_granularity` reads as village level, so a state officer was refused every statewide comparison and a
  district officer their own district.
- **Decision:**
  - each fixed answer is authorised where it returns, with the existing `_repaired_sql_denial` / `_denied`; behaviour
    stays in the stages (never in a graph node);
  - cross_figures is authorised from its plan, before any query: each place (`plan.districts`, `plan.block`) as a
    resolved entity, and a per-district answer as a `GROUP BY lgd_district` shape (`_c13_e12_cross_figures_denial`);
  - the Focus Legacy group-name SQL names a group, not a place, so it is not authorised; the scheme is checked and
    groups outside the caller's area are dropped;
  - scope fails closed (`scope_from_user`); the admin API refuses unknown values instead of storing them;
  - a missing configured CA file refuses the model client only with `ENV=prod` **and** `BOOT_GUARD_ENFORCE=true`
    (default false). A plain prod check would stop the dev box, which runs with `ENV=prod` and no CA file.
- **Rejected:** authorising the cross_figures SQL text (false denials above); a hard prod-only CA refusal (bricks dev).
- **Rollback:** revert the files above; `BOOT_GUARD_ENFORCE=false` already gives the old CA fallback (now logged CRITICAL).

### D-080 — Guardrail model outage: fail closed for abuse only; count and alert (2026-10-29)
- **Date:** 2026-10-29. RAG plan E2, the "fail closed + alert" half (the "run in parallel with the plan" half: built
  in D-085, measured slower on today's gateway, left off; the word lists are unchanged). Files: `app/guardrails.py` (`_ABUSE_SUSPECT`, `_OutageMonitor` /
  `outage_monitor`, `_outage_verdict`, the `unverified` reply), `app/config.py` (`GUARDRAIL_ALERT_THRESHOLD`,
  `GUARDRAIL_ALERT_WINDOW_SECONDS`), c14 `_turn_edge_stage`, `app/main.py` (`/metrics`, `/health`).
- **Context:** D-040 failed open: during a classifier outage every message went on with only a WARNING log
  (audit 2026-10-23: "the answer goes out unchecked, with no alert"; KI-446).
- **Decision:** when the model cannot judge (exception, timeout or unreadable reply):
  - a message with an abuse word (`_ABUSE_SUSPECT`: violent verbs not aimed at pests / videos, weapons, drugs,
    hacking, sexual words, self-harm, bribery / robbery, "bank account number", jailbreak / SQL words) is refused
    with the `unverified` edge reply ("can't check … right now, try again"). Broad on purpose: "people killed in
    floods" is refused during an outage and answered once the model is back;
  - everything else goes on (layer 1 already ran). Out-of-scope requests are not harmful and fail open;
  - `GUARDRAIL_MODEL_FAIL_CLOSED=true` still refuses every message;
  - the `unverified` reply is `context_dependent`, so it is never written to the shared answer caches.
- **Alert:** `outage_monitor` counts let-through and refused events and errors by kind (per worker), on `/metrics`
  `guardrail` and `/health` `guardrail_model` (visibility only; status unchanged). `GUARDRAIL_ALERT_THRESHOLD`
  failures (3) inside `GUARDRAIL_ALERT_WINDOW_SECONDS` (300) log one ERROR `ALERT guardrail model failing …` line
  per window and a `pipeline_decision stage=guardrail outcome=alert` record. When `ALERT_WEBHOOK_URL` is set
  (blank by default) the same alert is POSTed there as JSON in the background (source, host, counts, a `text` line
  for Slack / Teams; never question text; 5 s timeout; a webhook failure is logged and never reaches the turn).
- **Alternatives:** refuse everything during an outage (the classifier also routes, but a dead guardrail would then
  stop answers even where routing has fallbacks); keep failing open (the audit finding).
- **Rollback:** none needed per flag; to fail open again, revert `_outage_verdict` to return None when the flag is off.
- **Status:** Active. OFFLINE-VERIFIED (gateway stubbed); NOT LIVE-VERIFIED (needs a real outage).

### D-079 — One scheme registry; the other registries are guarded against drift (2026-10-27)
- **Date:** 2026-10-27. RAG plan E5; user decision "Registry + drift guard" (not a full migration).
- **Context:** scheme names appear in ~124 places across 31 files (mapped by a scan for lines naming four or more
  schemes); the SCHEMES.md "Adding a scheme" list (2026-09-26) had stale paths (`app/pipeline.py`,
  `web/ai_query.html`) and missed the newer registries.
- **Decision:** `app/scheme_registry.py` (data only) holds name, subject area, KB folder / tag, main view, document
  label and constituency capability per scheme. Pure name lists read it (auth roles, c01 `_ALL_SCHEMES`,
  `query_plan.SCHEMES`, `metric_catalog.SUBJECT_TO_SCHEME`; identical values). Matchers, fuzzy aliases, the Focus /
  CM Elevate collision rules and prose stay where they are (each guards a reported failure) and are checked against
  the registry by `tests/test_scheme_registry_e5_2026_10_27.py` (16 registries).
- **Found:** c13 `_CROSS_AC_RECORDED` omits CM Elevate while c08 `_AC_CAPABLE_SCHEMES` includes it, and every view now
  carries `ac_name` (KI-445) — pinned in the guard, not changed.
- **Rollback:** the four lists back to literals (the guard still passes).

### D-078 — The query plan (E1), stage 1: built and logged in shadow, read by nothing (2026-10-27)
- **Date:** 2026-10-27. RAG plan E1; user: start Task 8 in shadow mode first.
- **Decision:** `app/query_plan.py`. After each data / knowledge turn, `_update_context` (c13, a stage function — no
  graph node changed) schedules a background task: one guided-JSON call to the classifier model (qwen4-deploy;
  enums from the six schemes and the metric catalogue keys) reads the standalone question into {intent, schemes,
  measure, place_level, place_name, group_by, all_years, shape, order}; `normalise` then fills, deterministically,
  the years (FY forms + stated spans), the top-N (KI-412 reader), the measure (catalogue literal match when it names
  one) and the area level (the resolver's place index). One JSON line per turn to `logs/query_plan_shadow.jsonl`
  with the pipeline's own decision (`actual`) and per-field agreement (`compare`). Runs after the answer, so it adds
  no wait. `QUERY_PLAN_SHADOW` (default on; off in unit tests).
- **Evidence:** `tests/query_plan/run_eval.py` (25 questions, 23 answered): the model alone mis-read the measure 3/10
  and the area 7/16 (it took "by district" / "top 5 blocks" for the area); with the deterministic fields **79/79**
  field comparisons agree.
- **Stage 2a done 2026-10-29 (D-085):** agreement measured over 730 live turns; the in-turn plan is built and
  tested but OFF (it slowed turns). Stage 2b (a stage reads one field) not started.
- **Next stages (each needs the user's go-ahead):** collect live agreement over real turns; then let one stage read
  one plan field at a time (e.g. top-N, years), keeping the old path as fallback.
- **Rollback:** `QUERY_PLAN_SHADOW=false`.

### D-077 — Retrieval scores only overturn a clear DATA misroute (2026-10-27)
- **Date:** 2026-10-27. RAG plan B3 / E4 tie-break; Task 7 of the handover work.
- **Evidence:** `tests/intent_scores/run_eval.py` + `labels.json` (70 own questions, 35 DATA / 35 KNOWLEDGE, incl. the
  KI-367 / KI-396 / KI-290 / KI-404 wordings), live. Today's rules + 4B: **67/70**. Scores alone (example − KB score
  >= t → DATA, best t): **57/70** — worse, so they cannot replace the rules. The 3 misroutes were DATA verdicts from
  the "how many" / "job card" / "wage" cues; two have the knowledge passage clearly closer (−0.175, −0.221); every real
  data question has the example ahead (≥ +0.021).
- **Decision:** after the rules, a DATA verdict for a question naming no place, year, ranking or breakdown (a figure
  question never pays the extra embedding call) becomes KNOWLEDGE when KB − example ≥ 0.10. Any failure keeps DATA.
  Result **69/70**, no DATA question changed. `INTENT_SCORE_TIEBREAK` (default on; off in unit tests).
- **Not done:** the plan's "ask on a tie" chips (figures or how it works?) — the remaining miss ("What is the wage rate
  under MGNREGA in Meghalaya?", +0.006) is such a tie; it changes the chat flow, so it is the user's call.
- **Rollback:** `INTENT_SCORE_TIEBREAK=false`.

### D-076 — Metric matching by meaning only logs; people approve exact synonyms (2026-10-27)
- **Date:** 2026-10-27. RAG plan B1; user decision after the measurement below ("Shadow log + synonym review").
- **Context:** `tests/metric_meaning/run_eval.py` (labels: 34 own paraphrases + 17 wordings for measures the catalogue
  does NOT hold; qwen3-embedding 1024). Wordings that must not match score as high as true paraphrases: "administrative
  expenditure" -> total expenditure 0.873 / margin 0.119, "wage rate" -> wage share 0.902 / 0.154, while "funds utilised"
  -> total expenditure is 0.745 / 0.018. No cosine threshold separates them, so a meaning match would state a wrong
  figure (the KI-435 failure).
- **Decision:** a meaning match never answers. An unmatched measure wording is logged with its nearest measure
  (`metric_catalog.meaning_shadow`, background task, `logs/metric_meaning_shadow.jsonl`); a person reviews
  (`tests/metric_meaning/review.py`) and adds approved wordings to `data/metric_catalog_synonyms.yaml` (exact phrases,
  merged at startup; also sent to the ingestion team for semantic.metric_definitions). Answering still needs the
  (measure, shape) pair in `metric_catalog_verified.yaml`.
- **Rejected:** answering from a meaning match (wrong figures above); a confirm chip "Did you mean …?" (extra tap,
  and the nearest candidate is often wrong); answering only when every word is covered (residual risk).
- **Rollback:** `METRIC_MEANING_SHADOW=false`; empty the synonyms file.

### D-075 — A new question that repeats the chat's measure keeps the chat's year (2026-10-27)
- **Date:** 2026-10-27. User decisions on the RAG-plan handover: U5 "when a follow-up names no year, keep the
  previous year"; then, shown the clash with D-061/D-065, "keep the year if same measure".
- **Context:** KI-406, live scenario U1 (the user's UI chat of 2026-10-18): "Total MGNREGA person-days in 2023-24" ->
  "What is the total beneficiaries?" (kept FY 2023-24) -> "What is the total beneficiaries manraya?". "manraya" is the
  spoken MGNREGA, so the turn names its scheme and measure, reads STANDALONE (D-061), inherits nothing and is asked
  the year (D-065).
- **Decision:** `_same_scheme_context_year` (c14): a STANDALONE question whose only scheme is the chat's own and whose
  measure (`context_manager.detect_metric`) equals the chat's last measure (`state.metric`) keeps the chat's **year**
  (or all-years) and **never its place**. Logged `inherited="same-measure-year"`. Any other standalone question is
  unchanged: D-061's founding case (person-days, then "Which district has the highest beneficiaries in MGNREGA?")
  still inherits nothing and is asked the year.
- **Rejected:** keeping the year for every same-scheme standalone question (reverses the user's D-061 complaint);
  leaving it to the year ask (against U5 and "one chat never re-asks").
- **Evidence:** `tests/test_same_measure_year_ki406_2026_10_27.py` (7, incl. one through the graph); D-061/D-065 tests
  unchanged and green; live `--only F,U1` 11/11 (was 9/11).
- **Rollback:** remove the `year_only` branch in `_same_scheme_context_year`.

### D-074 — Qdrant on the data box; only megh_knowledge and megh_sql_metadata, read-only (2026-10-27)
- **Date:** 2026-10-27. Source: user — "use the Qdrant at http://10.48.242.4:6333 … only meghoneai [= megh_knowledge,
  confirmed] and megh_sql_metadata, these two collections in the entire project"; then four answers: megh_knowledge;
  read-only; conversation memory off; SQL examples behind `SQL_EXAMPLES_SOURCE=yaml|qdrant`, default yaml, with an
  evaluation script, logic in the stage function, no graph node changed.
- **Context:** both collections were loaded on 2026-10-27 by another pipeline (1024-dim, qwen3-embedding scale; payload
  indexes on `kind`, `scheme`, ids). megh_knowledge: 207 `knowledge_chunk` points, `scheme` a LIST, `source_file` /
  `section` instead of `doc` / `heading`, no BM25 vector, CM Elevate Legacy under its own tag. megh_sql_metadata: 133
  `example` + 12 `view` + 16 `join` points, every example `validated: false`. Pointing the old code at megh_knowledge
  would have DELETED it on the first start (kb_ingest rebuilds a collection without the BM25 vector).
- **Decision:**
  - `QDRANT_URL=http://10.48.242.4:6333`, `QDRANT_COLLECTION=megh_knowledge`, new `QDRANT_KB_READ_ONLY` (default true):
    `kb_ingest.ingest_kb` returns "read-only collection" before any check; `vectorstore.recreate_collection` / `upsert`
    raise `ReadOnlyCollectionError`.
  - `vectorstore.piece()` reads both payload shapes; the scheme filter is `MatchAny`; "CM Elevate" also matches
    "CM Elevate Legacy" (the KB alias `rag.kb_scheme` is unchanged). `rag._kb_texts_by_scheme` reads list tags.
  - `RAG_HYBRID_ENABLED=false` in `.env` (no BM25 vector; search was already falling back to meaning-only).
  - `CONTEXT_SEMANTIC_MEMORY_ENABLED` default false, `CONTEXT_MEMORY_PURGE_ALSO` empty: memory needs its own
    collection. Conversation context still comes from Postgres (D-023).
  - **Extended 2026-10-27 evening (user: "use the entire things … in both collections for the entire application"):**
    default and `.env` -> `qdrant`. Its `kind=view` / `kind=join` points go into the SQL prompt (optional
    `sql_metadata` section, scoped to the schemes in play), example `notes` become `Note:` lines, and megh_knowledge's
    `doc_title` is the citation title. `tests/conftest.py` pins `yaml` for the unit suite.
  - `SQL_EXAMPLES_SOURCE` (default `yaml` until that extension), `SQL_EXAMPLES_COLLECTION=megh_sql_metadata`: with `qdrant`,
    `_data_sql_stage` calls `sql_examples.prefetch` (one embedding of the few-shot ranking text, one filtered search per
    scheme, 4 s budget) and `prompt_builder._fewshot_examples` uses the result per scheme. A two-scheme example is shown
    only in a prompt holding both schemes (never in one half of a per-scheme cross question, D-062), and once.
    Any failure or empty result keeps that scheme on its YAML bank. `build_sql_prompt` stays synchronous.
- **Alternatives rejected:** copying megh_knowledge into an app-owned collection (a third collection, against the
  instruction); letting the app rebuild megh_knowledge from `data/incoming/` (deletes the other pipeline's data);
  switching SQL examples straight to Qdrant (no accuracy evidence yet; the examples are unvalidated).
- **Evidence:** live 2026-10-27: knowledge retrieval for all six schemes (top cosine 0.72-0.79, 8 pieces, citations
  right), "What is SECC?" -> PMAY-G, ingest skipped, writes refused; Qdrant examples fetched in ~0.2 s, cross examples
  scoped. `tests/test_qdrant_two_collections_2026_10_27.py` (12 tests). Accuracy of `qdrant` vs `yaml`:
  `tests/nl2sql_eval/compare_examples_source.py` (not yet run — see TESTING.md).
- **Status:** Active. Rollback: `.env` back to the D-067 server/collections, `QDRANT_KB_READ_ONLY=false`,
  `CONTEXT_SEMANTIC_MEMORY_ENABLED=true`.

### D-073 — Generated SQL runs through `semantic.run_query` on the `megh_chatbot` login (2026-10-27)
- **Date:** 2026-10-27. DB team's reply (megh_chatbot password, run_query `columns`, exact decimals); user: "check with the
  changes we need to do. And make it".
- **Decision:** `CHATBOT_DATABASE_URL` set -> `run_readonly` sends every guarded statement to `semantic.run_query` on a third
  pool (4 per worker; the login's own cap 20). Fixed queries and catalog reads stay on megh_readonly (the team's rule).
  Row values are restored to asyncpg's types — the answer checks treat Decimal / int / float differently — from run_query's
  `types` if the team adds it (asked), else by describing the statement on megh_readonly (prepare = parse, no execution).
  Refusals map onto the existing errors (AI_PIPELINE §execute step 4); the repair loop is unchanged (D-072).
- **Rejected:** reading JSON numbers as-is (SUM(bigint) would become int instead of Decimal); a second run of the query for
  `pg_typeof` (double cost).
- **Evidence:** 584 recent generated statements: 582 identical rows + types, 2 same rows other order (no ORDER BY);
  tests `tests/test_run_query_path_2026_10_27.py`.
- **Rollback:** blank `CHATBOT_DATABASE_URL` and restart.
- **Update (team's second reply, same day):** run_query now returns `types` (base names: `numeric`, `bigint`,
  `character varying`, `double precision`, `timestamp with time zone`, arrays as `numeric[]`), also with no rows — used
  directly, so the describe step on megh_readonly now runs only if `types` is ever missing. Up to 3 repairs is accepted by
  the team (every attempt goes through run_query — it does, each repair calls run_readonly). Every connection now sets
  `application_name` = `DB_APPLICATION_NAME:<pool>` (`megh-chatbot-v2:app|readonly|chatbot|checkpointer`) so the team
  can tell builds apart in pg_stat_activity.
- **Status:** Active.

### D-072 — The DB team's plan check before each generated query; server limits end as "narrower question" (2026-10-27)
- **Date:** 2026-10-27. The DB team's note "Database Changes and Next Actions for the Chatbot Team"; user: "fix the
  issues raised because of the data changes … don't create new problems".
- **Decision:** (1) call `semantic.check_query` as megh_readonly before `run_readonly` in `_execute_one_attempt`; act only on
  `row_join` (repair). Fail-open, never opens a pool, `SQL_DB_PRECHECK` switch. (2) 57014 / 53400 from megh_readonly become
  `QueryTooHeavyError(TimeoutError)`, so they end like our own timeout. (3) The repair loop is NOT changed (the team asks
  for no retry on timeouts / 42501 and at most 2 repairs): a timeout was repaired into a working query on 2026-10-18 and no
  42501 was ever logged; the 3-vs-2 question was sent to the team. (4) System-information functions refused by name and
  prefix, not a full allow-list (it would refuse ordinary functions the model has not used yet).
- **Not done (waiting on the team / the user):** `megh_chatbot` + `semantic.run_query` (JSON rows, no `$1` parameters),
  `megh_app`, audit retention (KI-430).
- **Evidence:** report `new_docs/DB_Changes_Impact_Report_2026-10-27.md`; tests `tests/test_db_changes_2026_10_27.py`.
- **Status:** Active.

### D-071 — The data team's metric catalogue answers plain measure questions (2026-10-26)
- **Date:** 2026-10-26. RAG plan B1 (metric / synonym detection) and A2 (same meaning, same answer). User: "implement all
  the parts one by one … don't create new problems, don't change any other code".
- **Context:** the model wrote its own SQL for every wording, so "spend", "outlay" and "money spent" could read different
  figures, and a wording could be misread. `semantic.metric_definitions` (ingestion team) already holds 62 named measures
  with their SQL expression, view, unit and synonyms.
- **Decision:** `app/metric_catalog.py` loads the 39 measures of the six schemes at startup; `c16_metric_catalog.py` uses
  one as a parameter-bound fixed query (read-only pool) when a question names exactly one measure and asks nothing else
  (scheme, resolved place, year and grammar only), with only district / block / village / year filters, in one of four
  shapes: total, breakdown (district / block / year), ranking (top / bottom N), compare (named places or years). It is the
  LAST fixed query, so every existing one keeps priority. It answers only for a (measure, shape) listed in
  `data/metric_catalog_verified.yaml` with live evidence; everything else is logged ("shadow") and goes to the model path.
  `METRIC_CATALOG_MODE` off / shadow / on (default on).
- **Not used:** the catalogue's free-text `filters_required` notes are not parsed; what they demand was reviewed by hand
  into the verified file (`single_year`; `no_block_level: Focus Plus`). PMAY "Filter WHERE NOT is_placeholder" is not
  applied: the expressions count every house, which is what the current answers (D-060) give. cmss, homestay_legacy and
  nrlm are not schemes here.
- **Evidence (live, 2026-10-26, `tests/metric_catalog_eval.py`, 312 questions):** shadow run — 207 questions built a
  catalogue query; per (measure, shape) 105 of 111 pairs agreed with the current answer on every question; the 6 others
  were wordings the model reads as another measure ("sanctions" = amount, "coverage", "remittances", "payments made" ranked
  by amount), one model error (compared SANCTIONED beneficiaries when PAID were asked), and Focus Plus payments by
  `district_name_raw`. Verified: total 28, breakdown 25, ranking 28, compare 23 (Focus Plus women left out: FY 2022-23
  holds no gender, so 0 = 0 proves nothing). "On" run — the catalogue answered 183 of 312; all 183 returned the catalogue
  figure and every total stated it. Golden set 42/74, 0 regressions; live context 103/107 (unchanged); known answers
  13/14 in-process (the 14th is the D-064 ask); pytest 3,829 / 0.
- **Tests:** `tests/test_metric_catalog_2026_10_26.py`; live: `tests/metric_catalog_eval.py`.
- **Status:** Active.
- **Update 2026-10-29 (RAG plan E7, Task 10):** the matched measure's own catalogue words no longer count as
  "asks more" (`_c16_measure_vocabulary`); re-measured all 39 measures (312 questions, shadow, 0 network errors):
  210 built, 191 agree, every one of the 19 differences explained (KI-424 wording, model failures, unit-only
  crore vs lakh, KI-426 column, model counting all beneficiaries as paid); 5 pairs added (verified 104 -> 109).
  Focus Plus women beneficiaries stay off (0 = 0, no gender data in FY 2022-23).

### D-070 — A call without a session id gets its own conversation (2026-10-26)
- **Date:** 2026-10-26. RAG plan E3; user: "solve option one … a better solution … don't disturb any other thing".
- **Context:** every session-less API call by one user on one day shared `day-<user>-<date>`, so an unrelated question was
  read as a follow-up of the previous one (scheme, place and year leaked). The bucket existed so scripts would not create a
  history row per question.
- **Decision:** `routers/query._session_id` gives such a call `api-<random>`: fresh context, saved like any conversation
  (so the returned `session_id` continues it on any worker, including a clarification reply), and left out of the user's
  own history list and search (`conversation_store.list_my_conversations` / `search_my_conversations`); admin views and
  the audit keep it. The id is computed once per request (the stream's stop handler asked again and would have got a
  different id). No-user calls keep `one-<random>`.
- **Evidence (live, 2026-10-26):** "MGNREGA person-days FY 2024-25 for all of Meghalaya" then "and in Ri Bhoi?" without
  an id -> a new conversation asking "Which scheme?" (before: a silent follow-up); with the returned id -> 928,817
  (MGNREGA, Ri Bhoi, FY 2024-25); no `api-` chat in the history list. pytest 3,805 / 0; scripts 14/14.
- **Tests:** `tests/test_session_less_calls_2026_10_26.py`.
- **Status:** Active.

### D-069 — Follow the ingestion team's 15-24 Oct database changes (2026-10-26)
- **Date:** 2026-10-26. Source: `CHATBOT_DB_CHANGES_2026-10-26.md` (ingestion team; replaces their 16 Oct note). Reply:
  `docs/Chatbot_Answers_to_Ingestion_Team_2026-10-26.md`. User: map to the current columns without creating new problems.
- **Checked live first** (read-only): `member_key` = the same 12,527 people as the old `member_id` (NULL on the 93K batch);
  `region` on 11 views (Ri Bhoi in Khasi); CM Elevate `current_file_status` = forward / resubmit / sendback, `data_verified`
  = Valid / On Hold / Invalid / Wrong; applications = distinct `request_id` (8,840).
- **Decision:** `member_id` -> `member_key` wherever it names the view column (`app/schema_context.py`, `data/focus_plus/*`;
  rule identifiers and the fact table's own column untouched; CM Elevate's `scheme_specific ->> 'member_id'` is a different
  thing and is asked about). Six few-shot `CASE … END AS region` -> `region_group`; c11 `_region_alias_not_the_column`
  renames a computed `region` in live SQL. The resolver's grouping (Ri Bhoi separate) is kept until the owners decide.
  No change for action 1 (the catalog tables are read live, not the documents) or action 3 (no rule uses the absent
  literals). `megh_readonly` waits for its credential (KI-304).
- **Evidence:** `check_fewshots.py` 0 errors in the prompt pool (was 7); pytest 3,784 / 0; known answers 7/12 exact, the
  other 5 explained (rounding KI-417, D-064 dataset ask, records vs distinct applications — question 1 to the team).
- **Extended 2026-10-26, after the team's answers (`ANSWERS_TO_CHATBOT_TEAM_2026-10-26.md`); user: "implement step 2 and
  step 3 … make everything change":**
  - **megh_readonly in use (dev box).** `.env` key was `DATABASE_URL_READONLY` (ignored) -> renamed `READONLY_DATABASE_URL`;
    `READONLY_DB_ALLOW_SUPERUSER=False`. Startup: "read-only pool ready as 'megh_readonly' (min=1 max=4)". Pools per worker
    4 + 4 + 2 = 10, so 2 workers = 20 (the team's limit). c11 `_star_without_hidden_columns` expands `SELECT *` on a table
    with columns the role cannot read to the readable columns (live schema), so it is not refused.
  - **Applications = distinct `request_id`** everywhere (already enforced by c11; the team's corrected figures 8,837 / 903
    match). The 4 in-prompt CM Elevate examples that read `scheme_specific ->> 'sector_id'` now read the plain `sector_id`
    and count distinct applications; the resolver's `scheme_specific ->> 'member_id'` pointer is removed.
  - **Region (team answer 2): Ri Bhoi is in Khasi** (LGD master). All six resolver files, the default-rule texts, the SQL
    prompt's geography rule and the six region examples (now `SELECT region … GROUP BY region`) follow it. A Khasi answer
    adds one line ("Khasi Hills here includes Ri Bhoi district …", c13 `_data_guarantees_stage`, label derived from the
    data, not hard-coded); "Ri Bhoi" alone stays the district. This retires the four-group version.
  - **"Pending" is not "on hold" (team answer 3).** A CM Elevate question with a workflow word (pending / approved /
    rejected / sent back) and no recorded field (on hold, verification, forward, resubmit, level) gets a fixed answer:
    not recorded, then the recorded figures, labelled (`cme-sector-workflow`, `_cme_workflow_query`). Replaces the
    2026-10-16 "pending = On Hold" reading for these questions.
  - **KI-417:** crore / lakh money is shown to the composer at 2 decimals (`_money_rounded_for_display`); display only.
- **Team's reply to the evening update (2026-10-26):** the Khasi note now says "as in the department's district-to-region
  list" (the national LGD directory has no regions); `schema_introspect` reads the catalog through `db.fetch_rows_readonly`
  (megh_readonly, READ ONLY transaction), so the prompt lists exactly what generated SQL can read — identical counts to the
  superuser load (29 tables, 62 metrics, 543 column notes, 46 live tables, 44 FKs), hidden columns absent. The pending
  answer is computed per question (no fixed CM Elevate figure in any answer; the `*_default_rules.yaml` /
  `*_response_template.yaml` texts are not loaded by the app). `sector_id` is never used for a programme question.
- **megh_app readiness (team's reply to the late update, 2026-10-26):** the 12 unused `*_default_rules.yaml` /
  `*_response_template.yaml` files are marked "NOT LOADED BY THE APP" (a test fails if app code reads them). Before
  `DATABASE_URL` moves to `megh_app`: no fixed query hits a hidden column or `SELECT *` on a hidden-column table (static
  scan + live run of startup loads and 9 fixed-query questions with curated reads as megh_readonly: 0 permission denied);
  app SQL is schema-qualified (`app.*`); app queries stop at 15 s (< megh_app's 60 s). Connections: 4 + 2 (checkpointer)
  = 6 per worker -> dev 6 + deploy 24 = 30 > the team's cap of 20 — asked them to raise it to 30.
- **Connection caps agreed (2026-10-26 night):** megh_app 30 (6 per worker x 5), megh_readonly 20 (4 x 5); both hard —
  any new worker, VM or larger pool is agreed with the ingestion team first. The old build (Docker `megh-nlp`, very likely
  `172.18.0.2`) is stopped at switch-over.
- **Status:** Active.

### D-068 — A stated scope is never asked for; "FY24" = FY 2023-24 (2026-10-24)
- **Date:** 2026-10-24. User: make different wordings of the same question give the same answer (RAG plan A2,
  C1), without creating problems. The user picked "answer with a stated default" (option A) first; the code
  history showed A had been tried (D-045, 2026-10-14) and reversed by the user (D-053, D-056, D-065: "if nothing is
  there you need to ask"), so A was NOT re-applied. The gap was in reading the scope, not in the policy.
- **Decision:**
  - A question that states its scope in any wording is never asked for it: new phrasings in
    `_STATED_ALL_YEARS_CUE` (year gate only), `_EXPLICIT_STATEWIDE` and `_HAS_BREAKDOWN` (scope gate). A question
    that states nothing is still asked, in D-056's order (district, then year). The ask flow is unchanged (a
    combined district + year ask was rejected: it breaks D-056 and an "all of Meghalaya, all years" chip would
    bring back the D-053 household-years figure).
  - `_STATED_ALL_YEARS_CUE` is kept out of `_ALL_YEARS_CUE` on purpose: the SQL verifier skips its mandatory-year
    check on `_ALL_YEARS_CUE`, and "altogether in FY 2024-25" must keep that check.
  - "FY<yy>" is the financial year ENDING in 20<yy> (FY24 = FY 2023-24), as every SME catalogue reads it
    (`focusplus_entity_resolver.yaml` FY23 = 2022-23; CM Elevate Legacy FY25 = 2024-25). It was 2000 + yy.
    "FY 23-24" stays the range starting 2023. A bare 1-2 digit extractor year is read from the question.
- **Evidence:** held-out NL->SQL set 40/74 -> 42/74 (MG-11, PM-13, CL-03 fixed; PM-04's flip is identical on the
  original code, KI-411); live: "FY24", "FY 24", "FY 23-24" all -> 8,996.36 lakh (FY 2023-24); "altogether"
  answered across all years, not asked. pytest 3,698 / 0; scripts 14/14; live context 103/107 (unchanged).
- **Where:** `c05_clarifications.py`, `c06_years_tranches.py`, `c07_mentions._parse_year_key`,
  `c09_resolve_entities.py`; tests `tests/test_stated_scope_2026_10_24.py` (wordings are our own, never the
  held-out questions).
- **Extended 2026-10-26 (user screenshot: a follow-up "give me FY 25" answered for FY 2022-23):** four year readers each
  knew a different subset of forms, so a year the extractor dropped was lost in some places only. ONE short-form reader,
  `context_policy.short_fy_tokens` ("FY 25", "FY25", "FY'25", "FY 23-24", "in 23-24"), now feeds `extract_year_keys` (~25
  callers: follow-up kinds, the rewrite check, the rephrase guard, the cache key), the pipeline's year-gap guard
  (`_c06_all_year_tokens`) and the year back-fill (`_backfill_explicit_year`). The rewrite check (`rewrite_violation`)
  also requires the follow-up's OWN year to survive ("FY20?" was rewritten to the previous FY 2022-23); a second year
  may still be added. The edge filter accepts "FY'25". The extractor's year is still never overridden
  (`test_backfill_never_overrides_the_extractor`): every failure seen was a DROPPED year, never a wrong one.
  Live: 81/81 two-turn chats (FY18-FY26 × "give me FY nn" / "FYnn?" / "FY'nn" × MGNREGA, PMAY-G, Focus Legacy) give the
  typed year, or the "data is available only for …" reply where the scheme has none.
- **Status:** Active.

### D-067 — Embeddings from the gateway's qwen3-embedding (1024-dim), in new collections (2026-10-24)
- **Date:** 2026-10-24. User: check whether the `.env` embedding model gives 1024 dimensions and works, then
  switch to it without breaking the project.
- **Measured (VERIFIED, live):** `qwen3-embedding` is listed by the gateway `/models` and `POST /openai/v1/embeddings`
  returns 1024-dim vectors (Qwen3-Embedding-0.6B size). Passing `dimensions=1024` returns HTTP 500, so the app never
  sends it. The old `.env` `EMBEDDING_BASE_URL=…/openai/v1/completions` gave 404 (the code appends `/embeddings`);
  it is now `https://10.48.242.4/openai/v1`.
- **Decision (`.env` only; `config.py` defaults stay `local`, which is the rollback):**
  - `EMBEDDING_PROVIDER=gateway` — the KB, the semantic cache and conversation memory all embed via the gateway.
  - New collections, because a 1024-dim query cannot search a 384-dim collection and `ingest_kb` checks only point
    count, schemes and the BM25 vector, never the vector size: `QDRANT_COLLECTION=megh_scheme_kb_v4` (built
    2026-10-24 by `ingest_kb`: 201 points, 1024-dim, BM25 keyword vector) and
    `CONTEXT_MEMORY_COLLECTION=megh_conversation_memory_1024` (created on first use). The 384-dim
    `megh_scheme_kb_v3` and `megh_conversation_memory` are left untouched for rollback.
  - Cut-offs re-tuned to the qwen3 cosine scale, which runs ~0.1-0.15 lower than bge-small (answerable questions'
    median top score 0.69 vs 0.78): `RAG_MEDIUM_CONFIDENCE` 0.55 → **0.35**, `CONTEXT_MEMORY_MIN_SCORE` 0.55 →
    **0.45**. `RAG_HIGH_CONFIDENCE` 0.84, `RAG_MIN_SCORE` 0.30 and `SEMANTIC_CACHE_THRESHOLD` 0.93 kept (fewer verbatim
    and fewer cache hits is the safe direction).
- **Evidence (`tests/rag_eval/run_eval.py`, 188 questions, same day; the judge moves ±2 points):**

  | Run | correct | wrong | wrongly "not covered" | not-covered handled | made-up answers | correct-or-honest |
  |---|---|---|---|---|---|---|
  | v3 bge-small 384 | 91.5 | 3.7 | 0.0 | 95.8 | 17.1 | 92.0 |
  | v4 qwen3, MEDIUM 0.55 | 90.9 | 2.4 | 3.7 | 95.8 | 8.8 | 91.5 |
  | v4 qwen3, MEDIUM 0.45 | 92.1 | 3.0 | 1.2 | 91.7 | 12.8 | 92.0 |
  | **v4 qwen3, MEDIUM 0.35** | 92.1 | 4.3 | 0.0 | 91.7 | 13.9 | **92.0** |

  At 0.55 six short questions ("How do I apply?", "docuements required?") were refused that bge-small answered.
  Retrieval rank is a little better on qwen3 (hit@1 48.8-50.6 vs 47.0, MRR 0.637-0.646 vs 0.621).
- **Found while checking:** the semantic cache's scope check missed words that flip the answer (KI-401, fixed the same
  day in `semantic_cache.scope_signature`).
- **Consequences:** knowledge answers, chat memory and the semantic cache now need the gateway (and the VPN); each
  fails soft (KB "not covered", memory empty, cache miss). No CPU embedding load on the workers. Chat recall starts
  empty in the new memory collection. TLS to the gateway is still `verify=False` (CA file missing, D-010 / KI-015).
  The deploy VMs need the same `.env` lines.
- **Rollback:** `EMBEDDING_PROVIDER=local`, `QDRANT_COLLECTION=megh_scheme_kb_v3`, remove
  `CONTEXT_MEMORY_COLLECTION` and the two re-tuned cut-offs (back to 0.55 / 0.55), restart.
- **Completed the same day (2026-10-24 evening, user: "change all to 1024 … don't create any problems"):**
  - Backup first: snapshots of our 7 `megh_*` collections downloaded OUTSIDE the repo
    (`C:\Users\rohit\Downloads\qdrant_backup_2026-10-24\`, `MANIFEST.txt` has point counts). The memory snapshot holds
    officers' chats: never commit or share it.
  - Vector-size guard (KI-402): `kb_ingest.ingest_kb` rebuilds a KB collection whose size differs from the model's
    (`vectorstore.collection_dim` / `vector_size`, `kb_ingest._embedding_dim`); unknown size keeps the old skip.
    `conversation_memory._ensure_collection` never writes into or deletes a memory collection of another size: memory
    goes off with one ERROR.
  - Retention for both memory collections (KI-403): NEW `CONTEXT_MEMORY_PURGE_ALSO` (default both names) — the
    384-dim rollback copy still loses chats after 30 days.
  - Recall carried over: NEW `deploy/migrate_conversation_memory.py` re-embedded all 12,046 in-window turns (same ids
    and payloads; the source only read) into `megh_conversation_memory_1024`. Self-recall 20/20 sampled.
  - :8401 restarted from `.venv` with the 1024 settings (the earlier "system Python" note was wrong: the `.venv`
    launcher on Windows runs the base interpreter as a child process).
  - `config.py` defaults stay `local` / `megh_scheme_kb_v3` / 0.55 on purpose: they are the rollback.
  - Memory cut-off checked: on 50 real turns with older turns in their session, 384 at 0.55 and 1024 at 0.45 made the
    same use/skip decision 49/50 (used 43 vs 44 times).
  - Memory search made exact with payload indexes (KI-408): 60/60 equal to exact, 0 usable turns missed, same latency.
- **Status:** Active (dev box, live). Deploy VMs: PLANNED (copy the `.env` lines, restart, run the migration script).

### D-066 — Cross-scheme figures of the four main schemes are worked out in code (2026-10-22)
- **Date:** 2026-10-22 night. User: "fix these immediately", on `Cross_Scheme_Issues_and_Solutions_2026-10-22.md`
  (the 60-case UAT sheet `raw_uc/cross_scheme.xlsx`, re-test 20/60, KI-387..393).
- **Context:** under D-062 every scheme's figure was right somewhere, but the model never added, ranked or
  compared across schemes (combined totals, district rankings, winner / second per district, "districts where
  X > Y"), ignored "excluding", dropped MGNREGA in district answers, gave PMAY-G's sanctioned amount and FOCUS's
  producer groups as the headline figures, copied one scheme's average onto another and cut FOCUS to its
  village-mapped rows.
- **Decision:** `app/cross_figures.py`. When a cross-scheme question is about **beneficiaries, money or village
  coverage** of **MGNREGA, PMAY-G, Focus Plus and / or Focus Legacy** — statewide, for a district / districts / a
  block, or per district, optionally one financial year — each scheme's figures come from a fixed,
  parameter-bound query, the combine step (total, district ranking, winner, second, condition, per beneficiary,
  ranking on several measures) runs in Python and the answer is written in code (`cross_figures.plan` /
  `answer`, called from c13 `_cross_scheme_scope`). Everything else keeps the D-062 model path: village or
  block lists, "top N" of villages / blocks, year-by-year, other measures, a village or constituency place,
  CM Elevate / CM Elevate Legacy.
  - Measures: MGNREGA households given work (household-years, every FY added) and `total_exp` lakh / 100;
    PMAY-G houses and amount RELEASED (sanctioned beside it); Focus Plus distinct beneficiaries; Focus Legacy
    members with PGs beside them; villages = distinct codes, 'Unresolved' rows out of the village count only.
  - Geography: Focus Plus by its source district / block names (`district_name_raw` / `block_name_raw` = the
    raw file); every other scheme by LGD. Totals of a per-district table come from the statewide query.
  - Combined totals are given when asked ("combined", "together", "in total", "total … across / under"); a
    count total says it adds different things. This replaces D-044 / D-062's "never add figures of different
    schemes" for an explicit request only.
  - Format: Indian grouping (18,73,378), ₹ crore, ₹ lakh below one crore.
  - Exclusions ("excluding / leaving out / except / other than / apart from / not counting" + scheme names) are
    read before scheme detection (c13 `_cross_exclusions`); excluding CM-ELEVATE drops both CM Elevate
    datasets; with no names left the four main schemes minus the excluded are compared. c14 route keeps a
    cross-scheme figure question DATA (`_cross_figures_question`). A bare FOCUS with no Focus+ beside it asks
    which Focus (CLAUDE.md §4), instead of being dropped.
- **Relation to D-062:** D-062 removed a fixed template because it answered every question with one card; here
  only the shapes the code fully expresses are answered in code, and the answer follows the shape asked (a
  condition list, a ranking, a per-district winner, a per-beneficiary order). The user's D-062 case ("top ten
  highest villages in Mgnrega and pmay") still goes to the model (pinned in `tests/test_cross_figures_2026_10_22.py`).
- **Rejected:** a regex exclusion parser as the issues document suggested (D-046 / D-047: word matcher only); the
  ingestion-side catalogue changes in the same document (megh-ingestion owns `semantic.*` and `curated.*`).
- **Trade-off:** answers to these shapes are fixed text, not composed; a new measure needs code.
- **Tests:** `tests/test_cross_figures_2026_10_22.py` (39); live: the 60 UAT questions, 4 runs.

### D-065 — A pause reply keeps the typed question's kind; a new question with no year is asked (2026-10-22)
- **Date:** 2026-10-22, user report on a live chat: "How many CM Elevate Legacy records …" (all years) → "What is
  the total disbursement amount for mairang?" → place chips → whole-or-part chips → answered "₹22.49 crore …
  FY 2025-26 (new question)". User: "previous query, it is taking all financial years … why are you blindly giving
  2025-26? … you need to take previous context or you need to ask … which year you want to choose".
- **Why:** (1) the typed question names no scheme, so D-061 reads it VAGUE (one open topic → the chat's scope,
  all years). Its chips append "under CM Elevate Legacy, the assembly constituency …", and the long chip text was
  classified again on its own words → STANDALONE → no inherited year → (2) the D-061 latest-FY default.
  (The ₹22.49 crore itself was the statewide FY 2025-26 total with the constituency filter dropped — KI-381.)
- **Decision:**
  1. A pause remembers the kind of the question that paused (`Session.pending_turn_kind`, in the durable snapshot,
     set by `routers/query.remember_pause` from `turn_context["turn_kind"]`). A reply that resumes it — a scope merge,
     a typed pick, or a tapped chip of any length — runs as that kind (`turn_context["resumed_turn_kind"]`, the
     follow-up stage's `_tk`; `_same_scheme_context_year(kind=…)`). A chain of pauses keeps the typed kind. The
     which-topic pause is not asked again on a resumed turn.
  2. **Supersedes D-061's latest-FY default** (the open question left with the user): a STANDALONE question with no
     year of its own inside a chat is **asked** the year with the chips (c13 `_data_clarification_stage`), like a new
     chat (D-053). Its banner still says "(new question)". A follow-up / vague question keeps the chat's year.
- **Not changed:** what counts as standalone / follow-up / vague (D-061 `turn_kind`), the new-chat order (D-056 §1).
- **Tests:** `tests/test_new_vs_followup_2026_10_22.py` (D-065 block), harness `new_vs_followup_2026_10_22.yaml`
  (`NQ_D065_*`; NQ01/07/08/09/11/12 now answer a year pause).

### D-064 — A bare "CM Elevate": financial words go to Legacy, anything else asks (2026-10-22)
- **Date:** 2026-10-22, user decision after the CM Elevate Legacy sheet re-test
  (`new_docs/CM_Elevate_Legacy_Test_Report_2026-10-22.md`): "if we ask any financial data, it should directly redirect
  to CM Elevate Legacy … if it just mentions applications, how many applications, it can ask whether CM Elevate
  applications or CM Elevate Legacy … you can select and it should generate the answer from that".
- **Why:** under the 2026-10-19 rule ("applications" = the applications dataset; money words = ask) the sheet's
  "CM-ELEVATE applications … sanctioned" questions were answered from the applications data, which holds no sanction:
  "80.63% sanctioned" (true 99.89%), "8,840 not sanctioned" (true 3), "West Garo Hills 1,733 sanctioned" (true 493),
  and, on an applications thread, "8,840 applications have been sanctioned" (true 2,820). Plain "applications"
  questions were answered 8,840 for a Legacy 2,823 without asking.
- **Decision** (`app/pipeline/schemes/cm_elevate.py`, `_cm_elevate_dataset_choice`), for a question naming a bare
  "CM Elevate" or only a CM Elevate sub-scheme (piggery, dairy … — in both datasets; `_names_cm_elevate`):
  1. the dataset chip's marker **"CM Elevate (applications)"** → applications (the user chose it);
  2. **financial words** (`_CMELEVATELEGACY_FORCING` / `_ONLY_TERMS`: money, sanction, subsidy, loan, lender, LIFCOM,
     disbursement, a specific FY, expenditure / spent) → **CM Elevate Legacy, never asked**, the thread included.
     "across all financial years" is scope wording, not a financial word (`_CME_ALL_YEARS_SCOPE`);
  3. words only the applications dataset holds (on hold, verification, status, pending, level N, sent back, sector,
     gender, SEED / Green Taxi / Cinema …) → applications (Legacy cannot answer them);
  4. otherwise the thread's dataset;
  5. otherwise a data question **asks** "CM Elevate (applications) or CM Elevate Legacy?" (rule `cm-elevate-dataset`)
     — "applications", "applicants", "how many …", "by district".
- **Chip marker:** the applications chip and the thread pin write "CM Elevate (applications)"; a typed "CM Elevate
  applications" is NOT the chip (the rephrase model spells a typed "CM-ELEVATE applications" that way). The data stage
  reads the question **before** the rephrase (`pre_rephrase_question`, c13). For a sub-scheme question the dataset is
  appended ("… under CM Elevate Legacy") so a chip never repeats its question (`_cme_name_dataset`).
- **Supersedes:** the 2026-10-19 rule (code comment, no D-entry) and the 2026-10-12 default to Legacy (KI-273).
- **Tests:** `tests/test_cm_elevate_legacy.py` (§2), `tests/test_cmelevate_legacy_sheet_fixes.py`; graph fixtures in
  `tests/test_pipeline_graph.py` name the dataset ("CM Elevate (applications)"); harness `AC04` / `AC04b` / `AC04c`,
  `P5`, `AF11`, `AB03` updated.
- **Status:** Active.

### D-063 — A data answer takes the question's shape; derived figures are computed in code (2026-10-22)
- **Date:** 2026-10-22. User report: "if I ask top 10, top 5 or compare, different things, you need to give
  different answers … the template should be same [the UI], but LLM needs to give different answers" (KI-377).
- **Context:** one composer prompt for every result ("one to three plain sentences; the first sentence must say what
  the figure counts … scheme … area … period"), temperature 0, and one number-check fallback (`_framed_fallback`:
  "Under X, … here are the N results:") gave a ranking, a comparison and a trend the same form. A composed gap or %
  change was a number in no row, so it failed `_answer_numbers_faithful` and fell back to that same dump.
- **Decision:** `app/pipeline/common/c12_answer_shapes.py` (loaded after c12, before c13):
  1. `_answer_shape(question, sql, rows)` — deterministic: `ranking` = the outer ORDER BY's first key is a result
     measure (SQLGlot: column, alias, aggregate or ordinal) and there is a LIMIT < 200 or a rank word, and no period
     label varies; `trend` = a period label (year / fy / month / quarter part; financial_year + year_key count as one)
     over ≥ 3 rows; `compare` = 2 rows, or ≤ 3 with a compare word (beats an ordered + limited SQL); `breakdown` =
     other one-label splits; `cross_tab` = two varying labels; `list` = no measure; `profile` / `single_value` = one
     row. `yes_no` = the question opens with an auxiliary verb. Rows of several schemes -> None (D-062 path).
  2. `_shape_facts` — the figures the shape needs, computed from every row and added to the faithfulness whitelist:
     #1 / #2 / last and the gaps, the ratio, the share of the ranked total; each side, difference and % for a
     comparison; first -> last change and %, peak, lowest and "rose every period / mixed" for a trend; total and
     shares for a breakdown. Rates / averages / percentages (`pct`, `rate`, `avg`, `per` …) are never summed.
  3. `_SHAPE_GUIDE` — per-shape instructions + one worked example ("layout only — never copy its numbers"), in the
     prompt as "Answer shape —"; a lowest-first ranking is told never to say "leads". A breakdown's rows reach the
     composer largest first (`_breakdown_preview`; the table keeps the query's order).
  4. `_shaped_fallback` — the deterministic answer in the same shape (numbered ranked list, verdict + difference,
     first-to-last + peak + list, total + largest / smallest + list), tried before `_framed_fallback`.
- **Kept:** the single-figure prompt text (2026-10-18 briefing-line rule), every faithfulness / hedge / list-size
  check (the whitelist only gains code-computed figures), temperature 0 (variety comes from the shape, the same
  question still gets the same answer), `_finish_answer` and the scheme guarantees, the UI layout.
- **Rejected:** raising the composer temperature (variety without fitting the question, and less repeatable);
  letting the composer compute gaps / percentages (prose rules fail under sampling, CLAUDE.md §5).
- **Not yet (phase 2):** the fixed per-scheme answers that skip the composer (PMAY-G `_pmay_facts_answer`, MGNREGA
  job cards / combined facts / wage-material / breakdown, Focus Legacy breakdown / group list, CM Elevate sectors).
- **Status:** Active. LIVE-VERIFIED 2026-10-22 (TESTING.md). Offline `tests/test_answer_shapes_2026_10_22.py`.

### D-062 — Cross-scheme questions are answered by the model, one query per scheme (2026-10-22)
- **Date:** 2026-10-22. User report: "I have a query. Breakdown into I want top ten highest villages in Mgnrega and
  pmay" got the statewide totals card ("Cross-scheme comparison — Meghalaya, all financial years"), the same card as
  "Compare MGNREGA and PMAY-G spending". User decision: "no template … based on the user query … all possibilities",
  for cross-scheme questions.
- **Context:** D-044's fixed table (`cross_scheme.plan` + `answer`) could express only count / money / coverage, a
  ranking sentence, and grouping by nothing / district / block. "Top N", villages, a block ranking ("top 5 blocks")
  and any other shape were dropped silently, so different questions got the same card (KI-374).
- **Decision:** a question `cross_scheme.detect` claims runs through the normal DATA path on the KI-011 per-scheme
  machinery, always (not only when the prompt is over budget):
  1. `_cross_scheme_scope` (clarification_gate): the D-044 place handling (urban blocks, Shillong constituencies,
     "FY2022-23"), twin-village chips, no area / year pause ("for all of Meghalaya", "across all financial years" =
     each scheme's own years).
  2. `_cross_scheme_gaps`: what a scheme's data cannot hold is SAID, never queried — a constituency (only MGNREGA,
     Focus Legacy, CM Elevate Legacy record one), a financial year it has no data for (years listed: Focus Legacy has
     no FY 2023-24), CM Elevate for a money-only question.
  3. `_cross_scheme_subquestion`: the rewrite model (9B, `call_rewriter`) writes one self-contained question per
     scheme ("Which are the top ten highest villages in PMAY-G across all financial years?"), checked by
     `_cross_subquestion_violation` (names only that scheme; same districts / blocks, years, numbers); else the
     deterministic fallback `_cross_scheme_base_question` (every scheme name -> that scheme, repeats folded).
  4. `generate_sql` per scheme with that scheme's own prompt / few-shots; `_data_per_scheme_rows` runs each through
     its own rewrites, guards, verifier and repairs; rows tagged `scheme`. The fixed single-scheme queries
     (`_data_deterministic_stage`) are skipped.
  5. `compose_response` writes one answer (all its faithfulness checks), with cross notes (answer exactly the
     shape asked, every row of each list, what each figure counts, PMAY-G released vs sanctioned). Guards after it:
     every scheme with rows must be in the answer (`_cross_schemes_left_out` -> one retry -> `_cross_scheme_sections`),
     the list-size check counts each scheme's list, each list given in full (`_cross_scheme_complete_lists`, up to
     25 rows), money in each scheme's unit (`_cross_scheme_answer_units`), and a line for every scheme with no
     figure added in code (`_cross_scheme_no_figure_lines`; told to the composer it set off the hedge check).
  "Which scheme paid the most?" (`_wants_cross_scheme_money_ranking`) is the same path over every scheme with money;
  `_cross_scheme_money_answer` / `_CROSS_SCHEME_MONEY_SQL` are removed.
- **Kept from D-044:** never add figures of different schemes (composer note + faithfulness check: a sum is in no row);
  each scheme in its own unit; places resolved against all six schemes.
- **Rejected:** extending the template with a village grain and a top N (still one fixed shape per new question
  type); one SQL over several schemas (KI-280: 18/20 paused, 2 wrong).
- **Trade-off:** NL->SQL per scheme is sampled. The measure a vague word maps to is the scheme's own model's choice
  ("highest villages" -> person-days for MGNREGA, sanctioned amount or houses for PMAY-G); the composer names it.
  Latency ~10-25 s for two schemes, ~25-40 s for six (one 9B call and one 30B SQL call per scheme, in parallel).
- **Status:** Active. LIVE-VERIFIED 2026-10-22 (TESTING.md). Offline `tests/test_cross_scheme_llm_2026_10_22.py`.

### D-061 — New question = new answer: a self-sufficient question inherits nothing (2026-10-22)
- **Date:** 2026-10-22. User addendum "Context Memory: New Question = New Answer" (addendum to the Context Memory
  Solution Proposal v1.0), with the instruction to cover every scenario, not only follow-ups. Reported: after
  "MGNREGA person-days in East Khasi Hills in 2022-23", "Which district has the highest beneficiaries in MGNREGA?"
  was answered inside East Khasi Hills and FY 2022-23.
- **Cause (VERIFIED):** (1) `is_scopeless_followup` read a question naming the chat's own scheme plus a measure as a
  follow-up (rule from 2026-10-18), so it was rewritten in the old scope; (2) any new question inherited the chat's
  place and year (D-056 §2, `_same_scheme_context_year`); (3) the place kept was the very level being ranked.
- **Decision (the question wins; memory only fills the gaps a question leaves on purpose):**
  1. `context_policy.turn_kind(question)` decides, deterministically and without reading the chat:
     **FOLLOWUP** = a reference cue ("it", "there", "same", "this/that" as pointers, "compare this", "what about",
     a leading "and/also", Hinglish "dobara / wahi / uska / pehle") or a fragment without a measure ("2023-24?",
     "Mawphlang?", "Which block is highest?"); **STANDALONE** = the stranger test: its own measure AND its own
     scheme — named, or pinned by the measure when the question also names its own year or place
     ("person-days in 2023-24"); **VAGUE** = a measure with no scheme named ("how many beneficiaries?",
     "how many job cards?"). Out of scope, reset, correction and "go back to …" are decided before it, unchanged.
  2. STANDALONE is never rewritten (follow-up stage) and inherits NOTHING: statewide unless it names a place; its
     own year, else the default rule = the scheme's latest FY in the data (**superseded by D-065: the year is asked**) (`_SCHEME_DATA_YEARS[s][-1]`, c13; not
     cached, `answer_defaults`); several schemes with no year still get the year chips. A NEW chat is unchanged
     (D-056 §1 asks scheme -> district -> year). The banner says "(new question)".
  3. FOLLOWUP inherits only what it leaves out (unchanged machinery: merge plan, rewrite, `prior_resolved`).
  4. VAGUE with ONE open topic runs in it (unchanged); with two or more single-scheme topics it asks, one chip per
     topic ("Go back to MGNREGA: how many beneficiaries?" — a topic switch, rule `topic-ambiguous`); never a
     default scheme. A measure that pins a scheme only offers that scheme's topic.
  5. Slot-conflict guard: the level a question asks ABOUT (`context_policy.asked_levels`: "which X", "top N X",
     "by / each / per X", "X-wise", superlative + X) and every level below it are never inherited as its filter;
     the parent is kept ("which block" keeps the district).
  6. Trace: `log_decision("turn_kind", kind, reasons, asked)`; `turn_context["turn_kind"]`, `["new_question"]`.
- **Deliberately not changed:** `continuation_signals` (it decides whether a message is on-topic at all, for the
  edge whitelist — not whether it inherits); the idle window stays 8 h (D-055) with its existing "Continue with …"
  chip — the addendum's "30 min" row is one config value (`CONTEXT_IDLE_EXPIRY_SECONDS`) if wanted.
- **Supersedes / amends:** D-056 §2 for self-sufficient questions (a measure with no named scheme, or a reference,
  still carries the chat's scope); the 2026-10-18 same-scheme rule in `is_scopeless_followup`; KI-331's "a new
  same-scheme question keeps the chat's year" (now: its own year, else the latest FY).
- **Where:** `app/context_policy.py` (`turn_kind`, `asked_levels`, `TurnKind`); `c01 is_scopeless_followup`;
  `c14 _turn_followup_stage`, `_vague_topic_clarification`, `_same_scheme_context_year`, `_c14_kept_place_fields`,
  `_attach_scope_banner`; `c13 _data_clarification_stage` (latest-FY default); `pipeline_graph._data` (`turn_kind`,
  read-only).
- **Tests:** `tests/test_new_vs_followup_2026_10_22.py`; harness `scenarios/new_vs_followup_2026_10_22.yaml` (every
  row of the addendum's §5 plus permutations); N3 / C_backward_restore / F3 re-specified.
- **Status:** Active.

### D-060 — PMAY-G: the 126 zero-sanction registrations are beneficiaries (2026-10-22)
**Status:** Active. **Source:** user instruction 2026-10-22 ("126 rows sanctioned amount 0 is also considered as
beneficiaries"), after the PMAY-G sheet re-test (`new_docs/PMAY-G_Test_Report_2026-10-22.md`). Closes the open
product decision KI-127.

**Decision.** Every PMAY-G beneficiary / house / registration count includes the 126 `is_placeholder` rows of
`curated.v_pmay` (sanctioned ₹0, no year, no sanction number, nothing released; statuses: 73 "Existing site(Old
House)", 40 "Proposed Site", 1 "Plinth", 12 blank; 72 real villages in 7 districts). Statewide all-years
beneficiaries are **171,107** (was 170,981). Consequences, chosen so the figures add up:
- not completed, "not received any amount", the status breakdown (their own statuses + "no status recorded") and the
  completion-rate denominator include them;
- "received the full sanctioned amount" and "full amount but house not completed" need `sanctioned_amount > 0`
  (₹0 released of ₹0 is not a full release); partial release is unaffected;
- money sums, the release % (already over `sanctioned_amount > 0`), unique sanction numbers and every
  year / date figure are unchanged (the rows carry no year, date or sanction number);
- the answer says how many of the count have ₹0 sanctioned ("… (including 40 registered with a sanctioned amount
  of ₹0 and no house sanctioned yet)");
- NOT changed: "houses sanctioned" measures (cross-scheme `cross_scheme.py` village coverage, the cross-scheme
  "houses sanctioned" prompt examples) keep `NOT is_placeholder` — these rows have no sanctioned house.
- **Amended 2026-10-23 (user: "houses sanctioned is 170981 … should be 171107 … change the UI also"):** the welcome
  card "Houses sanctioned" (`app/routers/stats.py` `_SQL["pmay_g"]`) counts every row = **1,71,107** (completed
  1,29,941 and funds released unchanged; live-checked). `cross_figures.py` already counted every record. The
  schema_context cross-scheme examples that still write `WHERE NOT is_placeholder` for "houses sanctioned" are
  overridden by the `_pmay_count_placeholders` guard on counts; aligning their text is open (KI-398).

**Where.** Fixed path `_pmay_facts_query` / `_pmay_lines` (pmay_g.py); model path: prompt `_PMAY_RULES` 1 and the
cross-scheme beneficiary example (schema_context.py) + deterministic guard `_pmay_count_placeholders` in
`_scheme_sql_rewrites` (drops `NOT is_placeholder`, kept on a release-vs-sanction comparison or an AVG); the c11
village-ranking guard no longer demands the exclusion on `v_pmay`. Replaces the 30 Sep "state both figures" answer
(`_pmay_attach_placeholders`, removed).

### D-059 — The level of a place comes from the database (place gazetteer, `PLACE_GAZETTEER`) (2026-10-21)
- **Context:** user report 2026-10-21, "How many job cards in Mawphlang?" — "a bare village name is not recognised;
  only '<name> village' works; the level must be decided by our database, not by a keyword". Diagnosis (live,
  through the graph): on the D-058 code, bare villages already resolved (Ambare Ading, Ladmawphlang, PMAY-G too), and
  MAWPHLANG is a block + constituency 24 with NO village of that name, so its "block or constituency?" question is
  right. What failed was the level decision: (1) an exact village with no rows in the asking scheme (CM Elevate
  "Ladmawphlang") was offered the look-alike MAWPHLANG block / constituency, because exactness was checked against
  the scheme's own village list only; (2) a typo ("Ladmawplang") was asked "block, constituency or village
  Ladmawplang?" (each fuzzy level judged alone; the chip echoed the typo), then "which of 3 villages?"; (3) the
  chat's remembered place was not used ("what about Mawlai?" after West Khasi Hills was swapped to the Mawlai BLOCK
  of East Khasi Hills; after Shallang block the rewrite model wrote "Mawlai block"); (4) the ordinary word "centre"
  was a village. The extraction prompt never says when a name is a village ("tag an ambiguous bare name as block").
- **Decision (all behind `settings.PLACE_GAZETTEER`, default on; off = D-058):**
  1. The `entity_resolver` village index (D-058) is the gazetteer — no second module: it also holds each village's
     `(village_code, BLOCK, DISTRICT)` (`village_places`) and the villages each scheme has rows for
     (`village_scheme_data`, from `v_employment` + `v_expenditure`, `v_pmay`, `v_focus_plus`, `v_cm_elevate`,
     `v_focus_legacy`; CM Elevate Legacy has no `village_code` = unknown, never filters). `match_places(question)`
     lists every place with all its database levels; exact names first (longest, non-overlapping), then a misspelt
     village among the left-over words (`village_fuzzy`: ratio-searched, WRatio >= 90 AND ratio >= 85 — WRatio alone
     scores "MAWPHLANG" inside "MISSION MAWPHLANG" at 95), skipping ordinary words (`_is_known_word`), numbers and
     years. p95 1.8 ms on the live index.
  2. An exact village name anywhere in Meghalaya is never offered a look-alike block / constituency. A typo goes to a
     village only when it is >= 90 and leads every look-alike level, and every other look-alike village, by
     `_VILLAGE_FUZZY_LEAD` = 12 points ("malwai" still asks: Mawlwai leads the Mawlai block by 9 — the 2026-09-15 bug).
  3. The level question is narrowed, in order, by: a stated level word (unchanged), the chat's remembered block (a
     same-name village inside it -> the village; the block itself -> the block), the remembered district (the one
     reading inside it), the asking scheme (a village it has no rows for drops out when another reading remains).
     One reading left -> taken silently by resolving its own chip question (c09 `_c09_gazetteer_settle`); 2+ -> the
     existing `entity-ambiguous` pause, whose chips now say where each reading lies ("The Mawlai village (Shallang
     block, West Khasi Hills)"). None of these rules ever adds a reading. The c01 place swap uses the same rule.
  4. The entity extractor is told the places the lookup found (`_c07_places_hint`); a name listed only as a village
     goes in "village". Invented names are already dropped (`_mention_in_question`).
  6. **User rule, 2026-10-21 19:50 (KI-348): "if the name is a block go to block, a village go to village, a
     constituency go to constituency; if the same name is at several levels, ask — for the complete hierarchy; do
     not hard-code anything."** So a level the text states counts only for a name the database holds at that level
     (an explicit "not the block" choice is still honoured); a chip's level tail is never carried to the next
     question; a district named with a finer place is the context that settles it; a reading the scheme has no data
     for (constituency under PMAY-G) drops out and the one left is used. Verified by a sweep built from the
     database (`tests/live_place_hierarchy_sweep.py`: every block, every constituency, every multi-level name and a
     seeded village sample, per scheme).
  5. NOT changed: the route node's village-NAME search (`_village_name_search`, "how many villages are named X")
     keeps its "village(s) named / containing" trigger — it answers a name search, not data for a place; tying it to
     every village match would hijack ordinary data questions.
- **Status:** Active.

### D-058 — A place is a place without its level word; the level question only for the SAME name (2026-10-21)
- **Context:** user report 2026-10-21 (KI-340): "in ambare ading" after a PMAY-G East Garo Hills answer was declined
  as off-topic; "in ambare ading village" was answered. The user's rule: the bot must recognise a village, block or
  assembly constituency named bare — in a follow-up or a new question, in every scheme — and ask only when the same
  name exists at more than one level. Live probes also showed the level question firing on look-alikes
  ("Mendipathar" -> the village "Mendipathar - Ward No.10", "Dambo Rongjeng" -> "DAMBO RONGDENG", "WAPUNG" ->
  "WAPUNG SKUR", "Sohra" -> "Sohrarim"), and the rewrite model mangling bare names.
- **Decision:**
  1. `entity_resolver` holds every village name and alias of `curated.dim_geography` (+ `dim_geography_alias`) in
     memory with its districts (9,431 distinct names; `load_village_names` at startup, lazily in the c14 context stage, retried
     at most once a minute). `place_mentions` reads districts, blocks, constituencies and villages, longest name first
     ("Lower Damalgre" is the village, not the Damalgre block). It is RECOGNITION only: which level a name means stays
     with the resolver.
  2. A place at any level is a continuation signal ("place"), passes the edge whitelist, and a short place message
     (<= 6 words) overrules a guardrail scope verdict.
  3. A follow-up that is only a village, a constituency or a block of another district is rewritten deterministically
     (c01 `_place_swap_rewrite`): the previous DATA question with its place swapped; the level word is added only when
     the name has exactly one level; the chat's district stays when the village / block lies in it; "statewide" goes.
     Districts and same-district blocks stay with the model rewrite (D-056, tested). The model rewrite is rejected if
     it drops a typed place or respells a typed village (a near-copy is put back as typed).
  4. The level question (`collides_across_dimensions`, both c09 block-branch gates) counts a village reading only when
     a village of EXACTLY that name exists, and a fuzzy catalogue level only when no level matched exactly. A typo that
     matches nothing exactly ("malwai") keeps the old fuzzy behaviour. Without the index, the old reading stands.
- **Changes the 2026-09-15 Sohra rule (`tests/test_admin_level_collision.py`):** a bare "Sohra" is now answered as the
  constituency (no village is named Sohra) instead of asking "constituency or the village Sohrarim?". The offline test
  keeps passing because it runs without the index.
- **Status:** Active.

### D-057 — The year in an answer is the year asked, and the year the SQL read (2026-10-21)
- **Date:** 2026-10-21. User decision, after the MGNREGA sheet report (DATA-007: 24 of 24 job-card answers said
  "across all financial years" over SQL pinned to `year_key = 2025`): "which year we asked, the answer should come
  accordingly … if I ask all years you need to give all years; don't take 2025-26 for all years … if no year is
  mentioned, take the previous one from context memory, but don't give blindly … whatever you generate in the SQL
  query, that you need to give in the composer layer."
- **Decision:**
  - A year asked -> that year, in the SQL and in the answer. No year -> the chat's year (context memory); no year
    there either -> the year pause (D-053). Job cards are no longer exempt from that pause.
  - All years -> all years. For job cards (a running total, KI-293) that is one figure per year, never a sum and
    never the latest year in its place; the all-years chip reads "Every financial year (one figure each)".
  - The period an answer states is the one the SQL read: the composer and the closing scope line are given the
    single year the query's WHERE pins (`_entities_with_sql_year`), and a place known only by its code is never
    called statewide.
- **Implementation:** `_mgnrega_job_cards_query` / `_mgnrega_job_cards_answer` (deterministic, parameter-bound,
  `/* mg-job-cards */`, answer written from the rows); `_mgnrega_job_cards_latest_year` pins the resolved year and
  falls back to the latest year only when no year exists anywhere; the c11 stock guard asks for one row per year on
  an all-years question; `few_shot.yaml` and `schema_context` rule 3 no longer teach `year_key = 2025` for a question
  with no year. KI-336.
- **Status:** Active.

### D-056 — New chat asks scheme -> district -> year; a chat with a scope carries it to any scheme (2026-10-21)
- **Date:** 2026-10-21. User decision, stated firmly after a live chat: "if a new chat is open, you need to give
  follow-up questions [scheme, then district, then year] if there is nothing in context memory. If there is context
  memory, you need to carry it forward; whatever new fields the user gives, update those." Live: "how many households"
  -> scheme chips -> "for MGNREGA" asked only the YEAR (the district was silently all of Meghalaya, D-045); after
  "MGNREGA · West Garo Hills · FY 2022-23", "how many households for PMAY-G" asked the year again and dropped the district.
- **Decision:**
  1. **New chat** (no answered data turn: `session.state` has no scheme / comparison, `_chat_has_data_scope`): a data
     question that names no place and no statewide / breakdown words gets the district pause
     (`scope-not-specified`, area-only wording, district chips + "All of Meghalaya") BEFORE the year pause, even when
     it names a year. Order: scheme (`_data_scheme_stage`) -> district -> year (D-053). A district-restricted officer
     (`scope.geo_restricted`) is not asked (auth scopes them). A chat that has answered keeps D-045's statewide default.
  2. **Chat with a scope**: a new (not rewritten) question about ANY one scheme inherits, as the resolver's
     `prior_resolved` fallback, the chat's year (only if the target scheme holds that FY, else the year chips ask;
     never for CM Elevate) and its place (no "there" needed any more — amends KI-331). Words the user types replace
     only what they name: a year of their own replaces the year; a place they name wins in the resolver; "all of
     Meghalaya" / "statewide" / "by district" / "top districts" / "compare" drop the place; "by block / village"
     keeps the district only. Another scheme's district / block are re-read in that scheme's catalogue
     (`scan_dimension`); a village carries only as its LGD code. A comparison of several schemes carries nothing.
  3. The resolver never carries an old block / village under a different district, and fills `display` for what it
     carries (the closing scope sentence called a West Garo Hills figure "statewide" otherwise).
- **Where:** `c13 _chat_has_data_scope` + `_data_clarification_stage`; `pipeline_graph._data` (`chat_has_scope`,
  read-only); `c05 _scope_clarification(area_only=)`; `c14 _same_scheme_context_year`, `_c14_context_target_scheme`,
  `_c14_place_in_scheme`, `_c14_kept_place_fields`; `c09` prior_resolved fallback.
- **Tests:** `tests/test_new_chat_and_scheme_switch_2026_10_21.py`; harness `scenarios/user_reported_2026_10_21.yaml`.
- **Amends:** D-045 (area default now only inside a chat with a scope), D-053 (the district is asked before the year),
  D-055 / KI-331 (place no longer needs a reference word; carries across schemes).
- **Status:** Active. Live-verified through the HTTP API on :8401. **§2 amended by D-061 (2026-10-22):** a
  self-sufficient question (own scheme + own measure, no reference cue) inherits nothing.

### D-053 — Ask the financial year when neither the question nor the context has one (2026-10-19)
- **Date:** 2026-10-19 (user decision, evening of 2026-10-18): "if context remembering is there you don't give the
  follow-up question; if nothing is there you need to ask the user". Live: "total benifishjeries for MGNREGA" on a fresh
  thread was answered as 1,494,437 household-years across every year without asking.
- **Decision:** with `ANSWER_DEFAULTS_ENABLED` on, the "across all financial years" default (D-045) applies only when the
  turn already carries a year: in its text, in its resolved entities, or in `prior_resolved` (`year_key`, `year_key_list`,
  `year_all` — a follow-up inherits the previous turn's year through the rewrite and the resolver seed). A metric /
  breakdown question with no year anywhere pauses with the FY chips (`_year_clarification`, rule `year-not-specified`);
  the chips resume with "for FY …" / "across all financial years", so the resumed turn cannot be asked again. The area
  default ("for all of Meghalaya"), the tranche default, job-card stocks (latest year), time-series and "which year"
  questions and schemes without a time dimension (CM Elevate) are unchanged.
- **Where:** `app/pipeline/common/c13_compose_and_data_stages.py` `_data_clarification_stage` (`_ask_year`);
  `tests/test_year_asked_without_context_2026_10_19.py`.
- **Extended 2026-10-19 (KI-331):** "the conversation already carries a year" also covers a new question that names the thread's same one scheme and no year of its own; it inherits the thread's year or all-years choice.
- **Status:** Active. Unit-tested; live check in HANDOFF/TESTING.

### D-055 — One chat never re-asks what it knows; only a new chat asks the scheme (2026-10-19)
- **Date:** 2026-10-19 (user): "If we are in one chat, there is no possibility to lose the context memory. If you go new chat,
  then only you need to ask which scheme, if scheme is not mentioned." Also: idle window 8 hours (D-051 amended).
- **Decision:** a data question that names no scheme and whose words pin none (MAIN_Contex.pdf §9.4) uses the chat's active
  scheme (`_chat_active_scheme`: the structured state, else the last single-scheme turn) and is never asked "which scheme?"
  inside a chat. A NEW chat with such a question asks "which scheme?" (chips); the reply is remembered. This **replaces D-045's
  answer-for-every-scheme default for an unnamed scheme**; explicit cross-scheme questions ("compare schemes", "in both
  schemes") are still answered side by side. Words that pin one scheme ("person-days", MGNREGA's "expenditure") are used
  without asking, as before.
- **Also (same day):** a new same-scheme question keeps the chat's year, and its place when it points at it ("there",
  "that district") — KI-331; a follow-up that only names a new measure is rewritten deterministically so the old measure does
  not leak — KI-334; a bare "CM Elevate" named as a switch after a Legacy answer goes to the applications dataset — KI-330.
- **Where:** `c13 _data_scheme_stage` / `_chat_active_scheme`, `pipeline_graph._data` (passes the session's scheme, read-only),
  `c14 _same_scheme_context_year`, `_pure_measure_change`; harness `scenarios/user_reported_2026_10_19.yaml`.
- **Status:** Active.

### D-054 — Every data answer reads as a briefing line (2026-10-19)
- **Context:** the officer's screenshot (2026-10-18) showed "1,494,437 household years." as the whole answer; "household
  years: 1,494,437; person years: 1,865,234; financial years: 4." and "Total MGNREGA person-days in FY 2023-24 is 27264054."
  were other live shapes. The first two are the deterministic fallback (`_deterministic_answer`), shown whenever the
  composer's sentence fails the number check; the third is a composer sentence with no grouping and no scope words.
- **Decision:** (1) the fallback is framed — `_framed_fallback(rows, schemes, entities)` (c12) writes "Under <scheme>,
  <period> in <place>, the recorded total is <value> <what it counts in plain words>." with a human label per column
  (`_HUMAN_METRIC`; money keeps its unit) and a caveat where the measure needs one (household-years / person-years are not
  distinct households / persons); a multi-row fallback keeps its list under the same framing line. `_deterministic_answer`
  itself is unchanged (other callers and tests pin it; `_is_fallback_answer` recognises both forms). (2) Every DATA answer,
  whichever path wrote it (composer, a scheme's deterministic facts, a fixed query), goes through `_finish_answer` from
  the finalize node (`_finish_data_result`): result figures of four or more digits get thousands separators (never a
  year-like value), and a single-figure answer that names neither the scheme nor the area gets one closing scope sentence
  ("This is the PMAY-G figure for Ri Bhoi district, FY 2023-24."); an answer that already names both is left alone.
  (3) The composer prompt states the format rule (first sentence: what the figure counts, scheme, area, period;
  thousands separators) — a prose rule alone is not relied on (CLAUDE.md §5).
- **Alternatives rejected:** rewriting the scheme deterministic sentences one by one (the finalize pass covers them all);
  letting the composer re-try until it names the scope (sampled, and the fallback would still be bare).
- **Consequences:** `compose_response` returns through `_finish_answer`; `pipeline_graph.node_finalize` calls
  `_finish_data_result`; `tests/test_pipeline_graph.py` compares the start of a stubbed answer. Tests
  `tests/test_answer_framing_2026_10_18.py`.
- **Amended by D-055 (2026-10-19):** the closing scope sentence names only what the sentence left out ("This is
  the MGNREGA figure." when the place and the year are already said), not the place and year a second time.
- **Status:** Active.

### D-055 — Conversational layer: facts from rules, words around them (2026-10-19)
- **Context:** `documents/Megh_One_AI_Conversational_Memory_Approach.pdf` (v1.0). A live run of its own conversations
  (Sections 2, 8, 13) found: "go back to the first one" answered from the knowledge base; "I'm Ravi" refused as
  off-topic; "which districts can I see?" asked "which scheme?"; "which years for MGNREGA?" got the capability
  paragraph; the scheme list offered MGNREGA-only chips; no reference to the earlier figure; no "You're welcome" /
  greeting back on a mixed message; the out-of-scope reply carried "I'm Megh One AI…" after its steer-back and a
  second tangent steered back again; the first "hi" did not introduce the assistant.
- **Decision:** keep the existing graph and the composer's number checks (the PDF's writer + fact guard already
  exist as the 9B composer + `compose_response` faithfulness checks); add the conversational parts as deterministic
  wording around result values, no new model call:
  `topic_memory.parse_backward` (a bare ordinal after "go back to"); `conversation_replies` (name kept for the
  chat, `mem["user_name"]`; first greeting introduces once; one steer-back per run of asides, `replies._last_kind`,
  cleared by any answered turn; thanks offers chips, a second thanks in a row just "Happy to help!"); c15
  `_coverage_answer` (edge stage, after the meta answers: year registry `_SCHEME_DATA_YEARS`, the officer's own
  districts / blocks), `_attach_conversational_touches` (finalize: greeting back / "You're welcome", and "That's
  down from X in FY … (about N% lower)" when the same figure — column, scheme, every other scope value — was
  answered for another year in this chat; values and the percentage come from the result rows, `mem["headlines"]`);
  c04 scheme list with one chip per scheme (`keep_follow_ups`).
- **Not done (left as the PDF's later phases):** Khasi / Garo / Hindi reply templates, voice variant, Indian number
  format (lakh / crore display of counts), tone rubric / LLM judge, `declined` chip tracking.
- **Consequences:** answers carrying a callback or the user's name are `context_dependent` (never cached). Tests
  `tests/test_conversational_approach_2026_10_19.py`; harness `scenarios/conversational_approach.yaml`.
- **Status:** Active.

### D-052 — Conversation about the conversation: meta turns answered from the previous turn (2026-10-18)
- **Context:** a live probe of a natural conversation (user request, 2026-10-18) found that messages ABOUT the
  previous answer were read as new questions: "why are you not giving me district wise?" went to the reference
  documents, "that's wrong, I asked for completed houses" lost the year, "can you explain this number?" got "the
  documents do not contain…", "what did you just tell me?" / "you are not understanding me" were bounced as
  off-topic, "what should I ask next?" / "I don't understand" got "Sorry, I didn't quite catch that", and
  "thank you, it is very helpful" re-ran the last data question.
- **Decision:** one deterministic reader of such messages, `app/pipeline/common/c15_conversation_meta.py`
  (`_meta_kind`, word lists on `app/text_match`, no model), with six kinds. Four are answered from the previous
  turn in the edge stage, before the edge banks (`_conversation_meta_answer`, step 0-b of `_turn_edge_stage`):
  **recap** (the last answer again, with its scope), **explain** (the 9B — the rewrite/composer model of the role
  map — explains the figure in plain words, grounded: every number it says must already be in the previous
  question, answer or rows, else a deterministic fallback), **misread** (an apology that quotes what was
  understood and asks for scheme / place / year, rotating wording), **suggest** (next questions for the topic: the
  breakdown and comparison the last data answer allows, then the scheme's starters). Two change the question in
  the follow-up stage (step 0h, `_meta_question`): **correction** drops the complaint lead ("that's wrong, I asked
  for") and runs the rest as the follow-up it is; **breakdown** runs the previous question "by district / block /
  village" with no model call. Both open the answer with an apology (`session.turn_context["answer_preface"]`,
  `_attach_preface` in the finalize node; the preface carries no figures). Every meta reply is an aside
  (`topic_memory` "aside", as a greeting is), so the topic continues; it is `context_dependent` (never cached).
  A message that brings a scheme, place, year or measure of its own is never meta ("explain the MGNREGA wage
  rate" is a question). Same probe, same day: `_THANKS_LEAD` reads "thank you …" as one lead, `_DOMAIN_WORDS`
  gains "farmer", `_FIGURE_SUMMARY_MATCH` gains "going on" / overview / situation / progress (a place "overview"
  is a figures question).
- **Same decision, same probe:** a place overview ("tell me what is going on in my block", "overview of Ri Bhoi", "how is
  East Khasi Hills doing") with ONE scheme and ONE district / block and no measure of its own becomes that scheme's
  headline question (`_overview_question`, route stage step 1i, intent DATA, no classifier call): MGNREGA "Compare
  expenditure and person-days in <place>" (the two-CTE path), PMAY-G "house status in <place>" (the deterministic facts),
  one query for the others; the answer opens "Here's an overview of <place> under <scheme>:". Free-form SQL for "going
  on" had failed every repair. "Compare with last year" with NO year in play (an all-years answer) asks which year, with
  the scheme's FYs as chips (`_relative_year_clarification`, follow-up stage step 0i, rule `year-not-specified`) — with a
  year in play `substitute_references` counts back as before. "Why is it so low?" after a figure gets **reason**: the
  records hold the figures, not the reasons, plus chips that are concrete single-measure comparisons (a chip is sent as
  the message, so it must be a question the pipeline answers as typed; MGNREGA's two-fact shapes are avoided, KI-311).
  `looks_like_followup` ignores an opening filler ("okay give me for East Khasi Hills" is "give me for …").
- **Addendum (same day, user report "out of scope is not working"; KI-316).** Every scenario of the context-memory review
  (A forward, B out-of-context incl. the B5 leak and the cached / streamed path, C backward, D general, E hierarchy, plus a harmful
  refusal and a denied follow-up) was run through the HTTP API against the running server. Three gaps, all fixed deterministically:
  (1) a harmful refusal is an aside like any out-of-scope message (`restyle` sets the topic-memory aside for every kind; the
  refusal text stays firm, no chips); (2) a denied follow-up is an aside (`resume_after_small_talk` puts the topic back); (3)
  roll-up: `_rollup_question` (follow-up stage 0h') turns "back to the district level" / "whole district" / "statewide" into
  the topic's last AGGREGATE question with the place swapped (block -> `entity_resolver.block_parent_district`, village -> block,
  -> "all of Meghalaya"), skipping breakdown-shaped questions ("which villages ...", "by block") and reading them from the
  durable topic ledger, because on the server `session.turns` holds only the last turn after the per-request rehydration. It
  carries a `MergePlan` that CLEARs the levels rolled past, so `prior_resolved` cannot put the block back (the mechanism that had
  labelled a block figure as the district). Permissions are untouched: the rolled-up question is re-authorised like any other.
- **Addendum (same day, user screenshot; KI-320).** "compare with pmay" after a single-scheme figure is a cross-scheme
  comparison in the SAME scope, never a swap to the other scheme: `_compare_with_scheme_question` (follow-up stage 0h'')
  builds "Compare <prev scheme> and <named scheme> in <place> in <FY>" from the previous turn's resolved entities and hands
  it to the deterministic cross-scheme path (D-044). The measure is deliberately left out: person-days are MGNREGA's alone,
  so the table shows each scheme's own headline count and amount, and says "no data for FY …" where a scheme lacks the year.
- **Alternatives rejected:** a model classifier for these messages (a 4B call on every turn, and a sampled
  decision on whether to re-run SQL); answering "explain" from the reference documents (they describe rules, not
  the figure); a free-text apology written by the model (the apology is a template so it can never carry a number).
- **Consequences:** `routers.query` unchanged; the graph gains one call in `node_finalize` (`_attach_preface`);
  `_PIPELINE_FILES` gains `common/c15_conversation_meta` after c14 (functions only, called at run time).
  Tests `tests/test_conversation_meta_2026_10_18.py`. Live results in TESTING.md.
- **Status:** Active.

### D-051 — Longer conversation memory: 50 turns, 20 questions per topic, 4-hour idle window
- **Date:** 2026-10-18. **User decision** (asked: "why only 8 turns? I want more, and a longer session window").
- `SESSION_MAX_TURNS` 8 -> **50** (turns per session; the durable snapshot now carries as many questions);
  `CONTEXT_LEDGER_PER_TOPIC` 6 -> **20** (up to 8 x 20 = 160 restorable questions); `CONTEXT_IDLE_EXPIRY_SECONDS`
  and `SESSION_TTL_SECONDS` 1800 -> **14400** (4 h). A stopped question now lives as long as the idle window.
  `.env` set the old values explicitly (`SESSION_TTL_SECONDS=1800`, `SESSION_MAX_TURNS=8`); updated locally —
  **every deploy's `.env` must be changed too**, or it keeps 30 min / 8 turns.
- Cost: no prompt grows (every prompt use of the turns is capped: last 4 / last 8, structured context D-022).
  The snapshot JSONB grows (ledger up to ~160 entries, answers cut to 300 chars: ~150-200 KB worst case); the
  in-process session holds up to 50 full turns (bounded by SESSION_MAX 5000 sessions per worker, oldest first).
- Still bounded: MAX_TOPICS 8, 5 recent questions per topic record, rolling summary every 4 turns.
- **Status:** Active.

- **Amended 2026-10-19 (user):** the idle window is 8 hours (`CONTEXT_IDLE_EXPIRY_SECONDS` = `SESSION_TTL_SECONDS` = 28800);
  turns stay 50 and the ledger 20 per topic. Every deploy `.env` must carry `SESSION_TTL_SECONDS=28800`.

### D-050 — Backward context memory: a per-topic question ledger inside the context stage
- **Date:** 2026-10-18. Source: `documents/MAIN_Contex.pdf` (Context Memory solution proposal v1.0, Phase 3;
  WI-7 / WI-8 / S1 / S4 of `documents/Context_Memory_Forward_Backward_Review_v3.docx`).
- **What:** each topic in `session.topics` keeps a ledger of its last `CONTEXT_LEDGER_PER_TOPIC` (6) questions,
  each with the ConversationState it ran in and a session-wide number. `topic_memory.resolve_turn` restores an
  earlier question by order ("the first question", "question 3"), by content (place 3 / year 2 / words of the
  question 1; a named scheme narrows to its topic; a different year rules an entry out), asks with chips
  (`ledger-ambiguous`) when several are within 80% of the best, and answers "what did we discuss?" (an aside:
  the topic carries on after it). Flag `BACKWARD_RESOLVER_ENABLED`.
- **Deviation from the proposal:** the proposal draws four new graph nodes (load_context, classify_turn,
  resolve_backward, resolve_reference). The project rule is "change behaviour in a stage, never in a graph node"
  (D-032, D-036) and the existing context stage already runs topic memory first, so the resolver lives there and
  the graph keeps its 22 nodes. Storage likewise stays the existing snapshot (`app.conversations.context_state`
  via `Session.to_snapshot`, D-023): the ledger is part of `topics`, answers cut to 300 characters.
- **A ledger entry holds a scope, never a figure to repeat:** going back re-runs the question in the restored
  scope, so a data refresh can never surface a stale number.
- "The previous / earlier question" keeps its old meaning (the previous TOPIC); only numbered ordinals mean a
  question.
- **Phase 4 (same day): constrained model pick.** A message with a backward cue that the rules place nowhere
  ("that employment figure you gave earlier") goes to the REWRITE model (9B — "follow-up resolution" in the
  user's fixed role map, not the 4B), with the last 3 turns and the numbered ledger. It answers one id, NONE or
  ASK; any other text is ASK (or NONE with a single question). It never writes a scheme, place or year. One call,
  only on such turns, `LLM_REFERENCE_TIMEOUT_SECONDS` 8; a failed call runs the turn as before. Called from the
  context stage right after `resolve_turn` (`topic_memory.resolve_reference`). Flag `LLM_REFERENCE_ENABLED`.
- **Phase 5:** setting a place level clears the levels below it, deterministically in
  `context_manager.update_state` (a new district drops the old block / village even when the merge plan said
  nothing). Permissions need no new code: a restore re-runs the question through the graph's `authorize` node,
  and a denied turn is never stored in the state or the ledger.
- **Phase 6:** scope banner — `pipeline._attach_scope_banner` (finalize node) sets `scope_banner` on every DATA
  answer from the result's own schemes and resolved entities, "(from earlier)" on a restored turn; the UI shows
  it above the answer and a reopened thread redraws it. "Continue with …?" — an idle expiry sets the context
  aside (`Session.expired_ctx`, durable); the first reply carries `continue_offer`; tapping it restores state,
  topics and last turn; any other message drops it.
- **Stop, then "continue" (user request, same day):** when the streamed turn is cancelled (Stop button, or "stop"
  typed in the box — the chat UI stops the running answer itself), `routers.query._remember_stopped` keeps the
  question on the session (`Session.stopped_ctx`, durable, saved in the background). The next "continue" /
  "resume" / "go on" (`conversation_layer.is_continue_request`) runs that question through the whole layer as if
  just typed, never cached; any other message drops it; older than 30 min is not continued. A "stop" with nothing
  running gets a short reply (`nothing_running`). The UI also re-asks at once from its own memory of the stopped
  question (`frontend/src/chat/stopContinue.js`, same word lists).
- **Mid-sentence comparison (evening, live probe V4):** "compare this with the MGNREGA figure you showed" /
  "how does this compare to MGNREGA?" becomes the pipeline's own two-scheme comparison for the active scope
  (`conversation_layer.comparison_with_earlier` -> "Compare PMAY-G and MGNREGA in East Khasi Hills in FY 2022-23",
  answered by app/cross_scheme.py, D-044). Deterministic, from the state; never cached. Only one other scheme may be
  named, and it must differ from the active one (CM Elevate family = one scheme).
- **Also fixed the same evening:** KI-314 (snapshot load / save retried once), KI-319 (a cache-served answer updates
  the state and carries the banner), and the "Continue with …" acknowledgement is an aside so the follow-up right
  after the tap keeps the restored turn as antecedent (browser check with a 60 s idle window).
- **Not built:** WI-9 (Qdrant search over archived turns on history cues — the 8 × 20 ledger covers a session).
- **Status:** Active.

## Parallel lanes (2026-10-28), temporary, folded in at final integration

### Lane A1 · Platform & security (KI-450 to KI-479)
- Progress: not started
<!-- end lane A1 -->

### Lane A2 · Conversation & frontend (KI-480 to KI-509)
- Progress: five entries below (2026-10-29); the integrator numbers them from D-074 on.

#### D-A2-CTX-09 — Conversation rulebook v1 (PROPOSED: awaiting the user's sign-off)
- **What:** one page for the rules already decided one at a time. No rule is new; the examples are the tests'.
  1. **A new chat asks what it cannot know** (D-056 §1): scheme → district → year. "What was the total Focus Legacy
     amount in FY 2024-25?" in a new chat asks the area (`scope-not-specified`, chips + "All of Meghalaya").
  2. **A self-sufficient question inherits nothing** (D-061): "Which district has the highest beneficiaries in
     MGNREGA?" after an East Khasi Hills answer is statewide.
  3. **…and is asked the year when it names none** (D-065): the year chips, never a silent latest year.
  4. **…unless it repeats the chat's measure on the chat's scheme** (D-075): it keeps the chat's year, never its
     place ("What is the total beneficiaries manraya?" after "… beneficiaries" in FY 2023-24).
  5. **A follow-up inherits only what it leaves out** (D-022/D-024): "What about FY 2023-24?" keeps scheme and place.
  6. **A bare "CM Elevate"**: money words → CM Elevate Legacy; applications-only words → applications; otherwise
     ask (D-064). "How many CM Elevate applicants are there?" asks (`cm-elevate-dataset`).
  7. **A bare "Focus"** always asks which Focus (CLAUDE.md §4).
- **For sign-off — wordings where the eval expected an answer and the rules ask:** "currently" (FP-03), "statewide"
  (FP-06), "across Meghalaya" (FP-10), "Meghalaya Rural Bank accounts" (FL-03). Should these words count as "all of
  Meghalaya" / "latest year" instead of asking? Until decided, the eval scores those pauses as `expected_pause`.
- **Eval:** `questions.yaml` `expect_pause: <rule>` on the 31 items the rules pause; `compare.pause_verdict`; an
  expected pause is reported on its own and left out of the accuracy denominator; any other pause is a miss.

#### D-A2-CTX-01 — A conversation belongs to its owner; one turn at a time per conversation
- **Decision:** a request for another user's session id gets 403 (this worker's copy by login, the durable row by
  app.users id; SQL backstop `user_id IS NOT DISTINCT FROM EXCLUDED.user_id` in both upserts). Unknown owners are
  not checked (dev, old rows). The router runs one turn per conversation at a time on a worker (`_TURN_LOCKS`, a
  wrapper keeping the name `_answer`); the graph's own lock is not reused (not re-entrant). A failed or stopped turn
  restores the session as the turn found it (a JSON copy taken after sync_in, before the conversation layer).
- **Rejected (the audit's own "don't"):** user-namespaced graph thread ids (orphans paused runs at deploy); 409 +
  client retry; a request-id dedup table.

#### D-A2-CTX-04 — Retention is opt-in; the audit has its own period
- **Decision:** `CONVERSATION_RETENTION_DAYS` and `QUERY_AUDIT_RETENTION_DAYS`, both 0 (= keep) until the user picks
  the periods; purged daily by the existing `conversation_memory.purge_loop`. The query audit is the compliance
  trail (delete_conversation never touches it), so it is NOT tied to the conversation period, unlike the lane plan's
  single setting. Deleting a chat also deletes its Qdrant memory (filter always names session AND owner), its paused
  run and this worker's Session.

#### D-A2-CTX-08 — The decision log keeps its no-text promise at the source
- **Decision:** `context_budget.log_decision` logs any text value under `question` / `prompt` / `answer` /
  `result` as `{"sha256": 12 hex, "chars": n}`. Instead of editing the seven call sites (the lane plan's version):
  covers future call sites too and leaves lane B2's conversation_layer / c14 lines untouched.

#### D-A2-CTX-07 — Two follow-up shapes are rewritten deterministically
- **Decision:** a breakdown-only message after a STATEWIDE answer → the previous question by that dimension; "compare
  … with <place>" (one new place, the previous place's own level, nothing else changed) → the previous question for
  both places. **Why it does not conflict with D-056:** D-056 leaves a place SWAP ("what about Ri Bhoi?") to the
  model; these need an explicit breakdown or compare cue and change nothing but the dimension / the added place.
  KI-416 is not touched: the rewrite guard already refuses the measure switch (SQL generation, lane B1).
#### D-A2-REPORT — Two continuations the test team expected (2026-10-29; for the user's review)
- **After a knowledge aside, a measure-only question keeps the chat's data scope** when the chat is on that scheme
  (it used to get the scheme alone and run as a new question). A chat that opened with the knowledge question, or an
  aside about another scheme, is unchanged.
- **A block of the chat's own district keeps the chat's year** (D-061 treats it as a new question; D-075 kept the year
  only for the same measure). The place is the question's own, as in D-075. A block elsewhere, or another scheme, is
  still a new question.
- Both extend D-061 / D-075 narrowly; neither changes what counts as standalone. Tests:
  `tests/test_test_team_report_2026_10_29.py`.
- **2026-10-30 update — D-A2-CTX-09 is SUPERSEDED in part.** D-089 (user, 2026-10-29: a new chat answers with
  defaults, no place = statewide, no year = all years; `NEW_CHAT_ASKS_SCOPE=false`) replaces its rules 1 and 3 (a new
  chat asks the place / the year), and D-090 (user: "applications / applicants / applied" settle a bare CM Elevate as the
  applications dataset) replaces its rule 6 for those words. Rules 2, 4, 5, 7 stand. The eval's `expect_pause` flags
  are now mostly inert (those items are answered, and an answered item is scored normally).
- **DOCUMENTATION CONFLICT — NEEDS VERIFICATION** (not this lane's entries): DECISIONS.md has TWO "D-089" headings
  (answer with defaults; chat UI audit product decisions) and TWO "D-088" headings (SQL repair time budget; one
  measure-kind rule). The integrator must renumber one of each pair and fix the references.
<!-- end lane A2 -->

### Lane B1 · NL to SQL, schemes & evaluation (KI-510 to KI-539)
- Progress: one entry below (2026-10-30); the integrator numbers it from D-095 on.

#### D-B1-CME-01 — CM Elevate "pending" = Valid → file_status Pending / Send Back (user decision 2026-10-30; gated on the scheme_specific grant)
- **Date:** 2026-10-30 (`app/pipeline/schemes/cm_elevate.py`, `app/schema_introspect.py`,
  `app/schema_context.py`, `app/data_facts.py`, `data/cm_elevate/*.yaml`; supersedes the KI-074 reading of D-027).
- **Decision (the user's words, 2026-10-30):** a pending CM Elevate application is one whose data was verified
  **Valid**, and whose file status is **Pending or Send Back**: `data_verified = 'Valid' AND scheme_specific ->>
  'file_status' IN ('Pending', 'Send Back')`. (The day's statements moved: first forward-only, then forward-or-sendback
  in `current_file_status`, finally — with the valid-by-default rule below — `file_status` alone on valid
  applications.) Every other state — Invalid / Wrong / On Hold, resubmit, Rejected / Approved — is reported only
  when the user names it. Live on 2026-10-30: **7,341** pending of 7,371 valid applications (8,921 in all); the old
  On Hold reading gave 911.
- **Blocker and gate:** `file_status` exists only inside `curated.v_cm_elevate.scheme_specific` (jsonb), which
  the ingestion team locked from `megh_readonly` on 2026-10-16; `semantic.run_query` (SECURITY DEFINER, owner
  `megh_query_runner`) is refused on it too, and there is no plain `file_status` column. So the rule is
  **gated** on `schema_introspect.cme_file_status_readable()` (scheme_specific present in the live columns the
  read-only role may SELECT). While locked, every pending path keeps the 2026-10-26 behaviour ("not recorded" +
  the recorded figures) and the prompt states the rule and says the count is not available. The grant has been
  requested from the DB team (KI-624); the moment it lands the funnel answers take over without a deploy.
- **What changes when the gate opens:**
  - `_cme_workflow_query` adds `pending` (the funnel) and `sent_back` (file_status Send Back) columns, first after
    the group so a ranking orders by pending; `_cme_pending_answer` states the count, the rule and the figures
    the rule leaves out ("available on request").
  - `_cme_sector_query` "pending in each sector" counts the funnel per sector.
  - `_cm_elevate_pending_funnel` (new, in `execute_with_repair` after the level guards): a plain "pending"
    that the model wrote as `data_verified = 'On Hold'` becomes the funnel (WHERE or FILTER); a plain query with
    no status test gets the funnel AND-ed in. An explicit "on hold" or another named state is left alone.
  - `_cm_elevate_pending_without_level` and `_cm_elevate_decision_status_column` resolve to the funnel instead
    of On Hold (`_cme_pending_target()`); `_cme_level_pending_wording` (KI-422) stops removing the word.
  - schema_context rule 9 and the pending vocabulary switch to the open text; `[[cme_pending]]` is a live token.
  - "pending at level N" = the rule AND the level (309 at level 2, not 310; 3 at level 0).
- **Refinement (same day, user):**
  - **"On hold" questions follow the same rule** (they are pending questions) and **never read `data_verified`**;
    `data_verified = 'On Hold'` answers only an explicit verification-outcome question. While locked, pending and
    on-hold questions both get "not available" + the rule + the recorded workflow figures (applications;
    forward / resubmit / sendback) — the On Hold figure is not offered, and no guard falls back to it.
  - **Level-wise = the rule by `current_level`**: "pending at level N" filters it (the fixed query, or the model SQL
    plus the guard), "level-wise pending" groups by it with the rule inside the COUNT's FILTER so an empty level
    still shows 0.
  - **Every CM Elevate application count is valid-only by default** (`applications_default` in the same YAML):
    `_cm_elevate_valid_default` adds `data_verified = 'Valid'` to any count over `v_cm_elevate` that has no test of
    that column (WHERE of a simple query; a Valid-only subquery for any other shape), and the fixed queries carry it.
    A question that names a verification state is answered as asked; one that asks for all applications
    (`_cm_elevate_all_applications`) gets every application and a single total split by `verification_states`
    plus not recorded. Answers say "valid applications" when the default applied.
  - **Nothing hard-coded**: the rule's steps live in `cmelevate_pending_rule.yaml` and are
    read at runtime by `app/cme_pending_rule.py` (re-read on change), which builds the SQL condition, the answer
    sentence, the prompt lines and the gate (every column the rule needs must be readable — so a plain
    `file_status` column, if the DB team adds one, opens the gate by editing the YAML alone). The typed-in
    `[[cme_pending]]` figure was removed; counts come only from the database at question time.
- **Alternatives rejected:**
  - Waiting for the grant before writing anything: the rule would then land untested under deadline.
  - Valid + forward only as an interim (7,386): silently includes the 51 Rejected files.
  - Changing the UAT matrix now: the harness runs as the chatbot's roles and cannot run the truth SQL; the
    rows are re-pinned when the grant lands (uat/decisions.md §12 lists the values).
- **Status:** Implemented, gated; tests `tests/test_cme_pending_funnel_2026_10_30.py`. Open: approved /
  rejected still take the measure-not-held pause (`_MEASURE_HOLDERS`); once the grant lands they can answer
  from `file_status` ('Rejected' 62 today, no 'Approved' row).
<!-- end lane B1 -->

### Lane B2 · Answers & knowledge base (KI-540 to KI-569)
- Progress: not started
<!-- end lane B2 -->
