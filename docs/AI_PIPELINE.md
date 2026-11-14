# AI Pipeline — Megh One AI

*Reconciled against the code on 2026-09-26 (commit `7064ab6`). Function names are exact; line
numbers are omitted on purpose because `pipeline.py` moves constantly. Use Grep to find a
function.*
*Labels: **VERIFIED** (code, config or test) · **INFERRED** · **UNKNOWN — NEEDS VERIFICATION** · **PLANNED**.*

Source of truth: [app/pipeline.py](../app/pipeline.py), [app/prompt_builder.py](../app/prompt_builder.py),
[app/llm.py](../app/llm.py), [app/rag.py](../app/rag.py), [app/config.py](../app/config.py).

---

## 0. Model roster and timeouts (VERIFIED: `config.py`, `llm.py`)

| Role | Setting | Model (served name) | Timeout | max_tokens | Guided decoding |
|---|---|---|---|---|---|
| Classifier (intent, scheme, entity spans, follow-up rewrite, summary) | `CLASSIFIER_MODEL` | `qwen4-deploy` (Qwen3-4B-Instruct) | 30 s | 200 | `guided_json` |
| SQL generation + repair | `SQL_GENERATION_MODEL` | `qwen-model` (Qwen3-Coder-30B FP8) | 30 s | 1024 | none (no decoding constraint since 2026-10-15, D-046) |
| SQL semantic verifier | `SQL_VERIFY_MODEL` | `qwen4-deploy` | 15 s | 200 | `guided_json` |
| Answer composer (DATA + RAG) | `RESPONSE_MODEL` | `qwen35-9b` | 20 s | 800 | none |
| Embeddings | `EMBEDDING_PROVIDER=gateway` (`.env`, D-067, 2026-10-24; `config.py` default and rollback: `local` = fastembed `BAAI/bge-small-en-v1.5`, 384-dim, CPU) | `qwen3-embedding` (1024-dim) at `EMBEDDING_BASE_URL=…/openai/v1` + `/embeddings` | 30 s | – | – |
| Reranker (every knowledge question, **always on, no switch**, D-083) | `RERANKER_MODEL` via `llm.call_reranker` (`/rerank`) | `qwen3-reranker`, Qwen3 yes/no format; order fused with the vector order | 30 s | – | – |
| ASR | `ASR_MODEL` | `qwen3-asr` | 60 s | – | `prompt` = `ASR_PROMPT` vocabulary hint |
| Backward reference pick (topic ledger, D-050, 2026-10-18; role tag `reference`) | `REWRITE_MODEL` via `llm.call_rewriter` | `qwen35-9b` | `LLM_REFERENCE_TIMEOUT_SECONDS` 8 s | 8 | none — the output must be a listed ledger id / NONE / ASK, anything else is ASK |

DOCUMENTATION CONFLICT — NEEDS VERIFICATION (noted 2026-10-18): the user's fixed role map (2026-10-15) puts
follow-up rewrite + summary on the 9B (`REWRITE_MODEL`) and the SQL verifier on the 30B coder; the classifier
and verifier rows above still say `qwen4-deploy`. Check `app/config.py` / `app/llm.py` and fix this table.

- **Temperature and message shape:**
  - All temperatures are 0.0.
  - Every chat call sends **one `user` message, with no system prompt**.
  - Every call sets `chat_template_kwargs.enable_thinking=False`.
- **Retries** (all VERIFIED). The complete list:
  1. **`call_model`:** guided→unguided, once, on HTTP 400/404/422. There is **no retry on a
     timeout or a 5xx**.
  2. **SQL:** up to 3 repair calls (§2.8).
  3. **DATA composer:** one strict retry on a misquoted or dropped number (§2.9).
  4. **RAG composer:** one retry when the first answer is an outright refusal (§4).
- **Concurrency:**
  - Every call waits on the per-worker semaphore (`MODEL_MAX_CONCURRENCY=24`).
  - A wait longer than 20 s raises `ModelBusyError`, which the router turns into a 503.
- **Request ceiling:** `REQUEST_TIMEOUT_SECONDS=60` covers the whole `answer_question` call.
- **Dead setting:** `SQL_GENERATION_MAX_RETRIES=1` is never read. The repair budget is hardcoded
  as `max_repairs=3` (KI-008).

---

## 1. Top-level control flow — `_run_pipeline(question, session, scope)` (VERIFIED)

Called by `answer_question`, which then runs `_attach_followups`, `context_manager.update_state`
and `maybe_update_summary` (`_update_context`), all best-effort.

**Stages (2026-10-02, D-032).** The steps below are grouped, verbatim, into stage functions, run
in order by the sequential driver `_run_pipeline`, or as nodes by the LangGraph orchestrator (§8):
- `_turn_context_stage`: a–c'';
- `_turn_edge_stage`: d–g;
- `_turn_followup_stage`: reference substitution, rewrite, edge re-check, hints;
- `_turn_route_stage`: not-held checks, village search, intent;
- `_turn_knowledge_stage`: the KNOWLEDGE route;
- `_turn_data_context_stage`: `prior_resolved`.

The DATA path (§2) is `_data_scheme_stage` → `_data_entity_stage` →
`_data_clarification_stage` → `_data_deterministic_stage` → `_data_sql_stage` →
`_data_authorize_stage` → execution → `_data_post_rows_stage` → `_data_compose_stage` →
`_data_guarantees_stage` → `_data_assemble`. Change behaviour inside a stage, never in a graph
node. The order matters: many steps exist to run
*before* a later step that would otherwise misroute.

| # | Step | Function(s) | Model? | Returns early with |
|---|---|---|---|---|
| a0 | **Spelling normaliser** (D-093, 2026-10-29): misspelt scheme / district / block names and closed-list domain words written canonically ("ribhoy" -> Ri Bhoi, "fokus+" -> Focus Plus, "mony" -> money); `raw_question` becomes the normalised text; the corrections go to `turn_context["spelling"]` / `["spelling_note"]` (§2.9g) | `spelling.normalise` | – | – |
| a | Spelling fix of scheme names | `_correct_scheme_spelling` | – | – |
| b | Pin bare "CM Elevate" (or a lone CM Elevate sub-scheme) to a dataset — D-064: financial words → "CM Elevate Legacy" (thread included); the thread's dataset; otherwise left for the data stage's "CM Elevate (applications) or CM Elevate Legacy?" pause, which reads `pre_rephrase_question` (c13) | `_pin_cm_elevate_dataset`, `_cm_elevate_dataset_choice` | – | – |
| c | **Resume a paused clarification**: merge `"<paused q>, <reply>"` unless the reply is a chip (full question), conversational, or a new question (`_reply_abandons_scope_pause`) | reads `session.pending_scope_q` | – | – |
| c' | **Resume a scheme pause** (`SCHEME_PAUSE_RULES`): a typed scheme name becomes that chip's question; anything else passes through unchanged (§5.2) | `_resume_scheme_pause`, reads `pending_scope_rule/options` | – | – |
| c'' | **Continuation gate** (2026-09-29, KI-130): does the message share anything with the previous turn? `has_context` = antecedent AND a signal (or a pause resume). Without one: edge whitelist applies, no rewrite, no KNOWLEDGE scheme fallback (§5.7) | `context_policy.continuation_signals` | – | – |
| d | Harmful-request refusal; guardrail rules, scope rules, then the guardrail model (D-040 / D-041). Model down (error, timeout, unreadable reply): a message with an abuse word gets the `unverified` reply (not cached), the rest go on; counted and alerted (`outage_monitor`, D-080, 2026-10-29) | `edge.detect_harmful`, c14 `_guardrail_check`, `guardrails.check_model` | **4B** (guardrail) | `edge` |
| e | "What is EKH?" district/block definition | `_geo_definition_answer` | – | `knowledge` |
| f | Why-choice, scheme fit, recommendation, pick, listing, comparison | `_why_choice_answer`, `_scheme_fit_check_answer`, `_scheme_recommendation_answer`, `_scheme_pick_answer`, `_scheme_listing_answer`, `_scheme_comparison_answer` | – | `knowledge`/`edge` |
| g | **Edge layer** (skipped on a resume). Includes `personal_request` ("give me five thousand loan", KI-131) | `edge.detect_edge_case(q, has_context)` | – | `edge` |
| h | Deterministic references ("previous year", "the former") | `context_manager.substitute_references` | – | clarification if ambiguous |
| i | **Follow-up rewrite** when `looks_like_followup` and the previous turn was `data`/`knowledge`. Structured previous-turn evidence plus a provenance check (§5.1) | `context_manager.build_followup_context` → `rewrite_followup` | **4B** (+ optional Qdrant memory) | `edge` "confused" if there is no antecedent and a bare pronoun |
| j | Edge re-check on the rewrite; inject the session's scheme hint | `edge.detect_edge_case`, `context_manager.inject_scheme_hint` | – | `edge` |
| k | Pre-route refusals: bank details, admin expenditure, unsupported named scheme | `_bank_clarification`, `_admin_expenditure_clarification`, `_unsupported_scheme_clarification` | – | clarification |
| k' | **Village name search** ("how many villages are named X?", "which villages contain X in their name?"), before routing and before any entity is resolved (KI-135) | `_village_name_search_answer` (scheme catalogue or `dim_geography`, parameter-bound) | – | `data` |
| l | **Intent** | `classify_intent` (regex fast path; since 2026-09-28 also `_APPLICANT_PLACE_CUE`: an applicant / application noun scoped to a place → DATA unless a knowledge word is present, KI-076; since 2026-10-27 `_PROCESS_QUESTION_CUE`: "how does / is <X> work / get issued / released …", "process / procedure / steps for" → KNOWLEDGE unless it says "how many / how much" or names a year, KI-404; since 2026-10-27 the **B3 safety net** (D-077): a DATA verdict for a question with no place, year, ranking or breakdown becomes KNOWLEDGE when the top megh_knowledge passage beats the top megh_sql_metadata worked example by >= 0.10, `INTENT_SCORE_TIEBREAK`) | regex fast path, else **4B** | – |
| m | KNOWLEDGE → RAG (§4) | `rag.answer_from_kb` / `answer_from_kb_multi` | embed + **9B** | `knowledge` |
| n | DATA → `_answer_data` (§2) | | several | `data` / `denied` / clarification |
| o | Exceptions from DATA | see §3.4 | | |

**Clarification (Flow B)** is an exception, not a return value: `raise ClarificationNeeded(question, options, rule)`.
1. The router turns it into `route:"clarification"` with one-tap `options`.
2. For the rules `scope-not-specified`, `year-not-specified`, `entity-ambiguous` and
   `ranking-count-not-specified`, the router stores `session.pending_scope_q` (and
   `pending_village_hint`, `pending_scope_rule`) **in process**. For `scheme-not-specified` and
   `focus-scheme-ambiguous` it also stores the options, and those resume at step c' instead
   (§5.2).
3. On the next turn, step **c** merges the reply into the paused question and runs `_answer_data`
   with `skip_scope_clarify=True`, so the same gate cannot re-ask.
4. If a chip sends a full rewritten question, it passes through unmerged.
5. **This state is not persisted**, so a resume that lands on another worker is lost (KI-001).
6. `scope-not-specified` (`_scope_clarification`) offers one chip per district plus a last
   **"All of Meghalaya"** chip (area only, since 2026-09-26; it was "All of Meghalaya, all
   years"). Picking it leaves the year open, so `year-not-specified` asks for the FY next, the
   same as a district chip. VERIFIED.
7. **D-056 (2026-10-21), the ask order and the carry-forward.** A NEW chat (`c13 _chat_has_data_scope`: no
   answered data turn in `session.state`) asks what it does not know in order: scheme (`_data_scheme_stage`) ->
   district (`_scope_clarification(area_only=True)`, also when the question names a year) -> year (D-053). Inside a
   chat with a scope nothing is re-asked: `c14 _same_scheme_context_year` (data_context stage) seeds
   `prior_resolved` for a new, not-rewritten question on ANY one scheme with the chat's year (if that scheme holds
   it) and place (re-read in that scheme's catalogue; dropped by "all of Meghalaya" / "by district"; district only
   for "by block"). The resolver's fallback (c09) never puts an old block under a new district and fills `display`
   for what it carries. VERIFIED (tests + live harness N1-N3).
8. **KI-351 (2026-10-21).** An `entity-ambiguous` village pause ("“Kotchugre” corresponds to more than one
   village") answered with ANOTHER place (not the paused name, not one of its blocks / districts, not a district)
   is the paused question asked for that place (`c14 _c14_pause_place_switch` -> `_place_swap_rewrite`), not a
   fragment merged with the old village hint. A "go back to …" restore records the question it ran as the turn's
   `rewritten_question` (`_mark_context_dependent`), so the next follow-up builds on it. VERIFIED (tests + live).
9. **KI-366 (2026-10-22), a follow-up that RANKS a place level.** "Which block has highest number of households?",
   "top 3 blocks by …", "blocks with the lowest …", "most … in which block?", "rank the blocks" ask across every place
   at that level: `context_policy._RANK_OVER_GEO_MATCH` CLEARs that level and the finer ones in the merge plan
   (reason "ranks the <level>s"), so the old block is not in `prior_resolved`; the coarser place is kept (D-056, as
   "by block"); a district ranking carries no place. When the ranking also names its own measure, the rewrite is
   deterministic (`c14 _ranking_followup_question`, log `rewrite="deterministic-ranking"`): the user's words + the
   chat's scheme + the place above the ranked level + the chat's year (not when the question names a year / place of
   its own, another scheme or points back with "those / it"). Otherwise the model rewrite runs. VERIFIED (tests + live).

Rules raised in code (VERIFIED by grep): `scheme-not-specified`, `focus-scheme-ambiguous`,
`cm-scheme-group-ambiguous`, `sericulture-spelling-ambiguous`, `ranking-count-not-specified`,
`region-needs-district`, `scope-not-specified`, `year-not-specified`, `year-out-of-range`,
`no-time-dimension`, `tranche-not-specified`, `entity-ambiguous`, `ac-narrow-scope`,
`column-not-held`, `scheme-not-available`, `scheme-comparison-not-specified`,
`recommendation-needs-profile`, and since 2026-09-29 `reference-ambiguous` (a bare "which
one?"; not remembered) and `amount-not-held` (a Focus Plus amount it never pays). The WHK
near-miss pause uses `entity-ambiguous`.

---

## 2. DATA path — `_answer_data(question, scope, skip_scope_clarify, prior_resolved, village_hint)` (VERIFIED)

### 2.1 Pre-classification gates (no model call)
In order:
1. `_unsupported_scheme_named` → a clarification naming the scheme we don't hold.
0a. `_geo_lookup_answer` → "village code of X" / "which block is X in": every village of that name from
   `dim_geography` (also on the KNOWLEDGE path). **Returns.**
1a. `cross_scheme.detect` (on `pre_rephrase_question`) → a comparison of 2+ schemes, or "which /
   each / all schemes" with a figure, ranking or compare word. Sets `d["cross"]` and skips the
   rest of this list; the entity stage then resolves against all six schemes, and
   `_data_clarification_stage` runs `_cross_scheme_scope` instead of the scope / year gates (no
   pause; "for all of Meghalaya" / "across all financial years"). The question is then answered
   like any data question, **one model-written query per scheme** (D-062, 2026-10-22; replaced the
   D-044 fixed table): `_cross_scheme_gaps` (not held: constituency / year / CM Elevate money) ->
   `_cross_scheme_subquestion` (9B one-scheme question, checked; fallback `_cross_scheme_base_question`)
   -> `_per_scheme_generate` / `_data_per_scheme_rows` (each scheme's own prompt, guards, verifier,
   repairs; the fixed deterministic queries are skipped) -> `compose_response` with cross notes ->
   `_cross_schemes_left_out` retry / sections, `_cross_scheme_complete_lists`, `_cross_scheme_answer_units`,
   `_cross_scheme_no_figure_lines` (guarantees stage).
   **D-066 (2026-10-22 night):** exclusions are read first (`_cross_exclusions`: "excluding / leaving out /
   except …" + scheme names are removed from the text; excluding CM-ELEVATE drops both datasets; no names left ->
   MGNREGA, PMAY-G, Focus Plus, Focus Legacy minus the excluded). A bare FOCUS with no Focus+ beside it asks
   which Focus. In `_cross_scheme_scope`, `cross_figures.plan` takes beneficiaries / money / village coverage of
   the four main schemes (state, district(s), block, per district, one FY) and `cross_figures.answer` returns
   the answer written in code from fixed parameter-bound queries, the combine step in Python (combined total,
   district ranking, winner / second per district, districts where X > Y, per beneficiary). PMAY-G money =
   released; FOCUS = members; 'Unresolved' out of village counts only; Focus Plus by `district_name_raw` /
   `block_name_raw`. Village / block lists, top N of villages or blocks, years, other measures, CM Elevate:
   the model path above. The route stage keeps such questions DATA (`_cross_figures_question`).
   **D-097 (2026-10-30, Cross Scheme sheet re-run):** the coded path covers **all six schemes**, **one village**
   (`Plan.village`, each scheme's own village filter from `cross_scheme.SPECS`), **one constituency** (`Plan.ac`:
   MGNREGA `assembly_constituency_name` on `v_employment`, `ac_name` on every other view; Focus Plus and CM Elevate
   record none) and a **block grain** ("block-wise", "each block": `Plan.grain`). CM Elevate = applications
   (`COUNT(DISTINCT request_id)`), no money and no financial year (`NO_MONEY` / `NO_YEAR`, said, never 0); CM Elevate
   Legacy = applicants sanctioned (`sanctioned_amount > 0`, 2,820) and `total_disbursement`. What `_cross_scheme_gaps`
   says a scheme cannot hold is handed to the plan (`Plan.gaps`) and never queried. "Applications" is a count word.
   A combined total / combined district ranking leaves CM Elevate out and says so (I-13); elsewhere CM Elevate is
   ranked by applications in its own list. "Widest coverage across districts" is the statewide reach. Still on the
   model path: village / block lists, top-N villages or blocks, other measures, several villages at once. Before
   this, 41 of the 57 scheme combinations and every village / constituency question took the model path, where the
   20 sheet questions gave 3 gateway timeouts and 15 wrong or incomplete answers (KI-644, KI-645).
   **Only what was asked (KI-437, 2026-10-27):** the answer and the table carry the measures `plan` read
   (count / money / villages), the count in one `beneficiaries` column for every scheme; PMAY-G completed
   houses and FOCUS producer groups only when the question names them or is a broad ask (performance;
   overview / summary / compare with no measure). The UI's two-way card compares the measure the question
   names (`analytics.js` `askedMeasureCol`).
2. `_wants_cross_scheme_money_ranking` → a cross-scheme question over every scheme that records
   money (all but CM Elevate), same path as 1a (D-062).
3. `_is_ambiguous_focus` → the "which Focus?" two-way ask.
4. `_needs_scheme_clarification` (`SCHEME_CLARIFY_ENABLED`) → the which-scheme chips on a new chat; a chat
   on a scheme uses it (D-055; the old `cross_scheme.unnamed_schemes` default had no caller and was removed
   2026-10-22). In `_data_clarification_stage`, with ANSWER_DEFAULTS_ENABLED (D-045) the scope,
   year and tranche pauses become the chip text appended ("for all of Meghalaya", "across all financial years",
   "across all tranches"); job-card questions get no year default (stock pinned by
   `_mgnrega_job_cards_latest_year`).
4b. **CM Elevate workflow statuses (D-069, 2026-10-26):** pending / approved / rejected / sent back are not in the data
   (ingestion team). `_cme_workflow_query` (via `_cme_sector_query`) answers "not recorded" plus the recorded figures
   (on hold at verification, each file status; distinct applications) with the question's place and programme;
   a recorded field (on hold, verification, forward, resubmit, level) keeps the model path.
4c. **Regions (D-069):** Khasi includes Ri Bhoi (LGD master, the views' `region` column); `_data_guarantees_stage` adds
   "Khasi Hills here includes Ri Bhoi district …" to the answer. SQL rewrites: `_region_alias_not_the_column`,
   `_star_without_hidden_columns` (megh_readonly's hidden columns). Composer rows: crore / lakh at 2 decimals
   (`_money_rounded_for_display`, KI-417). The catalog the SQL prompt is built from is read as megh_readonly
   (`db.fetch_rows_readonly` in `schema_introspect`), so it lists only what generated SQL can read.
5. `_needs_topn_clarification` (`TOPN_CLARIFY_ENABLED`) → the Top 3/5/10/all chips. It reads the digits
   `_normalize_rank_counts` wrote, so "five highest" is no longer asked. The stated count is then the
   SQL's outer LIMIT: `_stated_rank_count_limit` (c11 `_scheme_sql_rewrites`, after `_pmay_comparison_limit`)
   sets it deterministically when exactly one count is stated (`_requested_rank_count`) and the query is a
   single ranked SELECT (ORDER BY) with no window function, no UNION, no OFFSET, and the question is not
   per-group ("in each district", "district-wise") or two-way ("top 5 and bottom 5").

### 2.2 Scheme classification — `classify_scheme`
- **Source:** `pipeline.py`. **Input:** the question. **Output:** `list[str]` of canonical
  scheme names.
- **Order:**
  1. The deterministic `_shortcut_scheme` (named schemes and scheme-only vocabulary).
  2. Otherwise the **4B** with the `SCHEME_CATALOG` descriptions and `guided_json`.
- **Failure:** unusable output → **returns every scheme** (KI-011).
- **Overrides after classification:**
  - A producer-group name question that names no scheme → `["Focus Legacy"]`.
  - For Focus Legacy, `_focus_legacy_pg_name_answer` answers group-name lookups
    **deterministically** (whole-word match, then prefix match) and returns. Since 2026-09-29
    (KI-149) `_PG_NAMED_ENTITY` accepts any non-space name word, `_pg_rest_is_place` decides
    whether words after the name are a place, and a size question whose name holds a place word
    but no group word comes back as `size?` — answered only when a group has exactly that name.
  - An assembly constituency alone no longer pins MGNREGA (`_mgnrega_terms`, KI-148); with no
    scheme implied, `_scheme_clarification` offers only the three AC-capable schemes.
  - Edge (`edge.detect_edge_case`, step 0b): a labelled producer-group name is masked from the
    out-of-area test (`_mask_group_name`, KI-152), so "Rakkam China Banana Group" is not refused.
  - Resolution, explicit "X village": the whole `_VILLAGE_PHRASE_MATCH` phrase from the text
    replaces an extractor fragment when the DB holds it exactly (KI-153; all village schemes).
  - Focus Legacy id/name-only group lists are written by `_focus_legacy_group_list_answer`
    (KI-154, D-031).
  - Village-disambiguation chips are pinned for Focus Legacy too (`_mgnrega_village_chip_pin`,
    KI-156), including after a later year chip (`_CHIP_TAIL_PARSE_MATCH` allows the period tail).
  - Group-name lookup (`_focus_legacy_pg_name_answer`) searches current names AND earlier spellings
    (`curated.v_focus_legacy_pg_search`, `NOT is_current`) in one pass, compares with "_" as a
    space, and keeps non-ASCII letters (KI-020, KI-155, KI-158). A "Focus" inside a group name
    does not raise "which Focus?" (`_pg_focus_group_name`, KI-157).
  - Focus Legacy village candidates: `_fl_expand_twins` adds same-block twins holding Focus
    Legacy groups, `_fl_rank_villages` lists villages with Focus Legacy rows first, twins get
    LGD-coded chips (KI-160, KI-163). Region questions stand down once a village is resolved
    (Focus Legacy in `_mg_place_settled`, KI-162).
  - SQL guards in `execute_with_repair` (Focus Legacy): `_focus_legacy_village_code_only` drops
    block/district literals beside a resolved village_code (KI-159);
    `_focus_legacy_date_trunc_as_date` casts `DATE_TRUNC(...)` to `::date` so months are not
    shifted by the IST→UTC conversion (KI-164). The verifier's "district dropped" complaint beside
    a pinned village_code is discarded (`_verifier_village_code_complaint_is_false`, KI-161).
  - For CM Elevate Legacy, `_cm_legacy_not_held` raises a "not held" explanation.

### 2.3 Entity resolution — `resolve_entities(question, schemes, prior_resolved, village_hint)`
- **Source:** `pipeline.py` + `entity_resolver.py`.
- **Output:**
  - `{"resolved": {...}}`: SQL-ready values (e.g. `district: 'EAST KHASI HILLS'`,
    `village_code`, `year_key`, `assembly_constituency`, `tranche`, `district_list`, …);
  - `"display"`, `"notes"`;
  - optionally `"question"`, a year-gap rewrite that replaces the question downstream.
- **Steps:**
  0. **Relative years (C1, KI-592, 2026-10-29):** before `resolve_entities`, `_data_entity_stage` runs
     `_c06_relative_year_rewrite`: "this / current / latest year" -> the latest FY the scheme holds
     (`_SCHEME_DATA_YEARS`, from megh_db), "last / previous / prior (financial) year" -> the one before,
     "last / past N years" -> "from FY a to FY b" (the span reader then lists every year). A composer
     note says which FY. Not for cross-scheme questions, a question that also names a year, or "next year".
     The premise check blanks FY tokens like dates (KI-593).
  1. **Year guards:** `_out_of_range_year_in`, `_years_in_question` and `_apply_year_gap`.
     - If only unavailable years are named → a `year-out-of-range` pause.
     - A comparison that names one absent year → the absent year is **substituted** with the
       nearest year that has data.
     - An end of a stated span ("from 2021-22 to 2024-25") the scheme lacks → moved to the nearest held
       year **inside** the span (KI-427, 2026-10-27); stripping it left "from to 2024-25".
     - Otherwise the absent year is stripped, and a note says so.
  2. **Span extraction:** `extract_entity_mentions` (**4B**, `guided_json`). It returns verbatim
     `district/block/village/year/assembly_constituency/blocks/districts` spans. Spans not found
     in the question are dropped (`_mention_in_question`), and so are producer-group names
     (`_drop_producer_group_names`).
  3. **Deterministic resolution** per dimension, via `entity_resolver.resolve_dimension`:
     - district, block, year, tranche and sub-scheme come from the per-scheme YAML catalogue
       (exact → alias → fuzzy, with blocked pairs), plus a cross-scheme fallback;
     - villages come from `resolve_village` [DB]: exact match on name or alias, else `pg_trgm`
       `similarity > 0.4`, and duplicates are collapsed by activity counts across the 7 views.
  4. **Collisions:**
     - a name that is several levels at once (`collides_across_dimensions`) → an
       `entity-ambiguous` chip set;
     - the assembly-constituency arm is kept only for `_AC_CAPABLE_SCHEMES = ("MGNREGA",
       "Focus Legacy", "CM Elevate Legacy", "CM Elevate", "PMAY-G")` (PMAY-G since D-096, 2026-10-30:
       `v_pmay.ac_name`). The whole-or-part drill-down reads the asking
       scheme's own rows (`constituency_contents(ac, scheme)`, KI-146).
     - **MGNREGA only (2026-09-26, KI-041):** `_explicit_level_in(question, schemes)` ignores
       a NEGATED level (`_NEGATED_LEVEL_MATCH`, "not the village").
       - The block/village chip sends "…, the block, not the village". The finest-first
         detector used to read that as "village", so MAWKYRWAT resolved to its village
         (273 households) instead of the block (11,590).
       - Other schemes keep the old reading, because the user asked they stay unchanged.
         The same chip text is generated for them, so the bug remains there.
     - **MGNREGA only (KI-042):** a district mention that is not a district or a village, but
       is EXACTLY an MGNREGA assembly-constituency name (`_mgnrega_ac_reading`), is re-read as
       the constituency before `OutOfScope`. An example is "SOUTH TURA": with only one reading,
       the collision gate stays silent.
- **MGNREGA village and block resolution hardening (2026-09-26, all-blocks / all-villages run;
  VERIFIED live).** These run in this order inside `resolve_entities`:
  1. **Village-chip resume.** When `village_hint` is set and the question ends with the chip
     tail ", <BLOCK> block, <DISTRICT>":
     - the tail's "block" is not a stated level;
     - `_mgnrega_village_chip_pin` pins the single village from the chip text (the name in the
       stem, looked up in `dim_geography` within that block and district);
     - only `village_code` goes to SQL;
     - the collision gate is skipped (`_chip_pinned`).
  2. **Truncated qualified names.** A longer exact village name in the question replaces the
     extracted mention ("JONGCHIPARA (NOKAT)").
  3. **Bare block or AC names tagged as a village.** `_mgnrega_admin_reading_of_village_mention`
     re-reads the name as the block or the AC, or asks which one when it is both. It runs only
     when the name is not an exact village name. It is needed because the collision gate ends on
     a district hit, and a block named after its district HQ town (MAIRANG, MAWKYRWAT) counts as
     one.
  4. **Chip caps.** Village chip lists show up to 10 names for MGNREGA (`_vcap`).
  5. **Special-word and punctuated names** (KI-057, KI-058):
     - a level word inside an exact village name ("BLOCK CAMPUS") is not a stated level;
     - `_mgnrega_longest_village_in` finds "&" / "INCL" / qualified names whole;
     - a village the extractor put in the block slot moves to the village slot;
     - `_resolve_village_for` prefers a village's own exact name over alias hits and drops
       "Unresolved" placeholders.
- **Before routing (MGNREGA or unscoped questions).** `_mgnrega_village_not_out_of_area`
  overrides the edge out-of-area refusal when an exact village name carries the place word
  (COAL INDIA COLONY). A bare MANIPUR / BURMA asks "village or the place outside Meghalaya?".
- **In `_answer_data`,** scheme detection runs on `_mask_scheme_words_in_village_name(question)`,
  so a village called "UMRAN DAIRY" is not read as the CM Elevate dairy scheme.
- In `_answer_data`, the Garo/Khasi range prompt is skipped once a village, block or AC is
  resolved (`_mg_place_settled`).
- **MGNREGA women employment (2026-09-27, KI-077).** FY 2025-26 women data is unrecorded at
  source, and that is handled as follows:
  - The FY pause also fires for percentage, share and women questions. Women questions offer
    only the years that carry women data (`_mgnrega_year_women`, read live).
  - A single-area women count or share is a deterministic query over the recorded years
    (`_mgnrega_women_query`). The answer is guaranteed to state the years it covers.
  - Explicit FY 2025-26 gets "not recorded" plus the latest year's figure.
  - Generator SQL is restricted to the recorded years when it reads women data with no
    `year_key` (`_mgnrega_women_years_only`, in `execute_with_repair`).
- **Calendar dates are not financial years (2026-09-27, KI-078).** "sanctioned on 2017-11-28" is
  a date filter:
  - `_EXPLICIT_FY_RANGE_MATCH` (the FY back-fill) skips an `NNNN-NN` that continues as a date;
  - `premise_check.extract_premises` blanks full dates, so their parts are never "assumed
    figures";
  - a full date satisfies the scope gate (`_CALENDAR_DATE_MATCH` in `_needs_scope_clarification`).
- **Failure behaviour:**
  - `ClarificationNeeded` when a name is ambiguous;
  - `OutOfScope` when a place is outside Meghalaya (`OUT_OF_SCOPE_GUARD_ENABLED`);
  - otherwise a not-found note is added.

#### Village-grained schemes (all six since 2026-10-02, D-034) — VERIFIED 2026-10-02
`_village_scheme(schemes)` is set when the question is about MGNREGA (first scheme), or about exactly
one of Focus Plus, PMAY-G, CM Elevate, Focus Legacy or CM Elevate Legacy (`_VILLAGE_NARROW_SCHEMES`;
the two Legacy schemes joined 2026-10-02, KI-190, with `_focus_legacy_village_names` /
`_cm_legacy_village_names` in `_scheme_village_names`).
Those are the facts with `village_code` on every row. It turns on these guards, which were
MGNREGA-only until the Focus Plus all-villages run (D-028, KI-079 to KI-083):
- the negated-level chip reading and the chip-tail level fix;
- the chip pin: `_mgnrega_village_chip_pin` reads the chip's own ", X block, DISTRICT" tail, or its
  "(LGD code)";
- the level-word-in-name fix;
- the whole-name village lookup: `_mgnrega_longest_village_in(q, scheme)`, over `v_employment` /
  `v_expenditure` or `_focusplus_village_names()` (`v_focus_plus`);
- the truncated-mention widening, the admin re-read, the "Unresolved" placeholder drop, and 10
  chips instead of 5.

Focus Plus only:
- `_focusplus_narrow_village` prefers villages that hold Focus Plus data;
- `_focusplus_alias_district_collision` asks when a district HQ alias ("BAGHMARA") is also a
  village;
- "Nan" resolves as the stored blank-block value.

Twin villages (same name, same block): the label and the chip question carry "(LGD code)"
(`_village_code_tag`).

SQL side (`execute_with_repair`, every attempt): MGNREGA uses `_mgnrega_pin_village_code` and
`_mgnrega_drop_geo_beside_village`. Focus Plus uses `_focusplus_pin_village_where`, which rebuilds
the WHERE of a single-SELECT query around the one resolved `village_code`:
- it drops every place condition (block_name_raw, lgd_*, district_name_raw, lgd_village_name,
  entity_type);
- it keeps the year, tranche and status conditions;
- it adds the code when the WHERE was missing it.
- it drops a condition whose literal is a Focus Plus block or district name, whatever the column
  (`tranche_label ILIKE '%GASUAPARA%'`);
- it replaces a `geography_key IN (SELECT …)` subquery with the code.

In `compose_response`, a Focus Plus single-figure result must be stated in the answer. The
misquote check skips whole numbers under 100, so "1" for 11 had passed. The fallback is a strict
retry, then the deterministic answer.

**CM Elevate additions (2026-09-28, all-blocks / all-villages run, KI-106 to KI-110):**
- CM Elevate is a village-grained scheme: `_VILLAGE_FACT_SCHEMES` and `_VILLAGE_NARROW_SCHEMES`
  include it, so `_village_scheme(["CM Elevate"])` turns on every guard above.
  - Its village catalogue is `_cm_elevate_village_names()` (`v_cm_elevate`, "Unresolved" rows
    excluded).
  - `_focusplus_narrow_village`, the alias-district collision and the village-beside-block step
    (`_pmay_village_beside_block(..., scheme)`) run for it.
- `_focusplus_pin_village_where` runs for `["Focus Plus"]` and `["CM Elevate"]`
  (`_PIN_VILLAGE_WHERE_SCHEMES`). Since KI-108 it:
  - finds the query's own WHERE with `_top_level_where_span`, never one inside
    `COUNT(*) FILTER (WHERE …)`;
  - splits conditions on AND outside string literals, so "…Empowerment and Development (SEED)"
    survives.
- **Block spelling (KI-107):** at the end of `resolve_entities`, `_cm_elevate_blocks_to_data`
  rewrites a resolved block to the `lgd_block` spelling `v_cm_elevate` stores, loaded live by
  `_cm_elevate_block_names`.
  - "X Municipal Board / Town Committee / MB / TC" → the urban body.
  - A name the data does not store → the same letters (RI-MULIANG → RI MULIANG), else X's only
    urban body (JOWAI → JOWAI-MUNICIPAL BOARD).
  - A rural block the data holds is kept (BAGHMARA).
  - Focus Plus uses the same rules on its `block_name_raw` names, and the early urban-body step in
    `resolve_entities` runs for CM Elevate, CM Elevate Legacy and Focus Plus on the district, village, block and
    constituency slots, before the level / constituency pauses (KI-361, 2026-10-22). A mistyped Focus Plus block
    literal ('SHILLONG-MUNICIPAL_BOARD') is snapped to the one raw block with the same letters in
    `_focusplus_lgd_only_block`, before its lgd_block fallback.
- The one-figure rule in `compose_response` applies to `_ONE_FIGURE_SCHEMES` = Focus Plus and CM
  Elevate (KI-109). The Garo/Khasi range check is skipped once a CM Elevate village or block is
  resolved (KI-110).
- **Urban bodies (KI-113):**
  - At the start of `resolve_entities`, a mention written as an urban local body ("Jowai-municipal
    Board", "Nongpoh TC") is moved to the block slot as the stored `"<TOWN>-MUNICIPAL BOARD"` /
    `"-TOWN COMMITTEE"` block, and both block-vs-village gates leave it alone.
  - An unresolvable district or block mention is checked with `_cm_elevate_block_from_mention`
    before `OutOfScope`.
  - In the collision gate, a name the data stores as a block (`Mawhati`, `Siju`) is always a
    block reading, so the chips offer it.
  - The block spelling step now also runs BEFORE the village-beside-block step, whose block set
    includes the stored spellings, so "<village>, Nongpoh-town Committee block" is the village.
- **SQL guards added to `execute_with_repair`:**
  - `_cm_elevate_fix_literals` (KI-112) snaps a programme / block / district literal that
    matches no stored value to the one stored value it clearly names.
  - `_cm_elevate_sector_all_programmes` (KI-111) drops an invented programme filter (and its
    grouping) from a sector question that names no programme.
- **Village chip pin (KI-114):** `_mgnrega_village_chip_pin(question, scheme)` keeps the
  same-block twin the asking scheme holds (MGNREGA passes its scheme and is unaffected).
- **Status = current_file_status (KI-123, product decision 2026-09-28):** schema_context rule 13 and the
  vocabulary now send "status" / "status distribution" / "status-wise" / "application status" to
  `current_file_status`, merging the send-back spellings. Two few-shots were rewritten to match.
  `_cm_elevate_status_is_file_status` (in `execute_with_repair`) rewrites a `data_verified` GROUP BY to that
  expression for a plain status question. Verification / pending / on hold / approved / rejected / withdrawn
  wording keeps its column.
- **Verifier (KI-115):** `_verifier_scheme_specific_complaint_is_false` also discards a check-2
  complaint about a live `scheme_specific` key when the SQL already filters every resolved
  place.

**PMAY-G additions (2026-09-28):**
- `resolve_house_status` matches a stage phrase containing "sanctioned" only in order, as a
  phrase, and never as "sanctioned amount / money / funds" (KI-091: "received only part of their
  sanctioned amount" had resolved to House Sanctioned).
- PMAY-G is a village-grained scheme (`_village_scheme`, D-029): village resolution prefers the
  villages in `v_pmay` (`_pmay_village_names`), and the chip / level / longest-name guards apply.
- `_has_block_word` accepts "blocks" ("compare X and Y blocks" no longer asks block or village).
- **Village beside its block (KI-098, user report):** at the end of `resolve_entities`, when no village
  was resolved but a block / district was (in any slot, or in an explicit ", <X> block, <DISTRICT>"
  tail read from the text), `_pmay_village_beside_block` looks for an exact PMAY-G village name
  outside the block / district mention and inside that block; if exactly one, `village_code` replaces
  the block / district. One mention written "X block" stays the block (the 2026-09-18 rule).
- **Full scenario run (KI-099 to KI-105):** the hill-range check is skipped once a PMAY-G village / block is resolved
  (`_mg_place_settled`); stage phrases with old / house / site / new / sanctioned match only as a phrase; ", X block" is
  read anywhere in the text; a village that is only the stated block's namesake yields to the longer exact name;
  `_pmay_two_villages` turns "A or B" into a village list; model-path answers get `_pmay_fy_labels` (year_key → FY) and
  `_pmay_crore_to_rupees` (no 2-decimal crore; exact rupees, formatted by `_pmay_rupee_format`).
- **Bare year (KI-125, revised 2026-09-29):** a plain four-digit year (`_PMAY_BARE_YEAR_RE`; not "FY 2017" or
  "2017-18") is the CALENDAR year: the data path runs `_pmay_facts_query(..., calendar_year=y)`
  (sanction_date 1 Jan – 31 Dec) and returns ITS answer, result table and SQL; the FY y-(y+1) figures
  follow as a one-line note. An explicit FY is unchanged. A year is never dropped.
- **Only what was asked (KI-128):** summaries list exactly the use-case figures (financial summary = sanctioned,
  released, remaining; performance = beneficiaries, sanctioned, released, completed); single figures carry no side
  details. For a rewritten follow-up, `_run_pipeline` sets `_PMAY_TYPED_TURN` to the typed text and
  `_pmay_facts_query` keeps only the figures the user typed when they are a subset of the rewrite's (a typed
  follow-up with no figure, e.g. 'and in East Khasi Hills?', keeps the rewrite's).
- **Result table (KI-129):** the facts path returns `_pmay_display_rows` (place + asked figures, readable
  column names) as `rows` / `data`, not its 30-column working row.

### 2.4 Post-resolution gates
1. **Region:** `detect_region` handles "Garo Hills", which is a range, not a district. It either
   expands to the range's districts or asks (`region-needs-district`).
2. **Focus Plus overall summary:** `_focusplus_wants_overall_summary` → a deterministic answer.
3. **Scope gate:** `_needs_scope_clarification` fires on an aggregate with no place **and** no
   year. It is skipped on a resume.
4. **Year gate:** `_needs_year_clarification` fires when the place is fixed but the year isn't.
   The chips come from `_SCHEME_DATA_YEARS`, which `refresh_scheme_years` refreshes from the DB
   at startup.
   - **A stated scope is never asked for (D-068, 2026-10-24).** The year gate also reads
     `_STATED_ALL_YEARS_CUE` ("all <word> years", "altogether", "lifetime", "since the start", "for the
     whole period"); that cue is deliberately NOT in `_ALL_YEARS_CUE`, which the SQL verifier uses to drop
     its mandatory-year check. Not asked, the question gets the standard "across all financial years".
     The scope gate's `_EXPLICIT_STATEWIDE` reads "altogether", "whole / entire state", "for the state",
     "state as a whole"; `_HAS_BREAKDOWN` reads "which / what <districts|blocks|villages…>" and
     "list / name the <places>". A question that states nothing is still asked (D-053 / D-056).
   - **Financial-year forms (D-068):** `_parse_year_key` reads "FY24" / "FY'24" / "FY 24" as FY 2023-24
     (the year ending March 2024, as every SME catalogue does); "FY 23-24" stays the range starting 2023.
     When the extractor returns only the digits ("24"), `resolve_entities` reads the year from the
     question's own wording.
   - **One short-form reader (KI-414, 2026-10-26):** `context_policy.short_fy_tokens` ("FY 25", "FY25",
     "FY'25", "FY 23-24", "in 23-24") feeds `extract_year_keys`, the year-gap guard (`_c06_all_year_tokens`)
     and the year back-fill (`_backfill_explicit_year`), so a year the extractor drops is still read, and a
     year the scheme lacks gets the "data is available only for …" reply. `rewrite_violation` refuses a
     follow-up rewrite that loses the user's own year.
   - **The SQL and repair prompts see the full form (KI-431, 2026-10-27):** `generate_sql` and `_repair_sql`
     pass the question through `context_policy.expand_short_fy` ("FY23" -> "FY 2022-23"); the model had read
     "FY 23" as `year_key = 2023`. The year guard names a wrong year_key it finds (`_vr_year_key_literals`)
     instead of saying the query has no year filter.
5. **Tranche gate:** `_needs_tranche_clarification` (Focus Plus only).
6. **Tranche conflict:** `_person_level_tranche_conflict` (Focus Plus; person-level columns exist
   only on Tranch 4) → a deterministic explanation.

### 2.4a PMAY-G deterministic facts path (2026-09-28, D-029, KI-089 to KI-097)
Runs after the gates in §2.4, before SQL generation, only for `schemes == ["PMAY-G"]`:
1. `_pmay_facts_query(question, schemes, resolved, notes)` returns None unless every resolved
   key is one it handles (`_PMAY_DET_KEYS`), the question is one of the fixed shapes
   (`_pmay_metrics`; `_PMAY_DET_EXCLUDE_MATCH` sends rankings, "each", trends, allotment,
   instalments, averages, lists and "in progress" to the model path) and, for a statewide answer,
   no place was left unresolved (`_PMAY_UNSETTLED_PLACE_MATCH`, resolver notes).
2. The query is parameter-bound over `curated.v_pmay` (every row — the 126 zero-sanction
   registrations are beneficiaries, D-060; `COALESCE(amount_released, 0)` — 336 houses have a NULL
   release), one row per named area: houses (+ how many are zero-sanction, stated in the answer),
   sanctioned, released, stage counts, full (`sanctioned_amount > 0`) / partial / no release,
   fully-paid-but-incomplete (+ stage split), unique sanction numbers. A date (`_pmay_date`: ISO,
   dd/mm/yyyy, written) or `year_key` filters it.
3. `_pmay_facts_answer` writes the answer: exact ₹ with Indian grouping plus lakh / crore
   (`_pmay_money`); for 2 areas the higher one and the difference per metric; for more, the
   highest. An area with no houses returns None → model path, except a village resolved by code
   → `_pmay_no_houses_answer` (a stated zero).
4. The result is returned with `sql` = the literal-substituted query, like the MGNREGA fixed shapes.
5. "Financial summary" / "(overall) performance" are NOT a place overview (KI-356): c15
   `_overview_question` skips a PMAY-G question when `_pmay_named_summary` matches, so it reaches
   this path with its own words (and its "till date") instead of "PMAY-G house status in <place>".

Model-path PMAY-G guards: `_pmay_count_placeholders` (rewrite, D-060: drops the model's `NOT is_placeholder`
except on a release-vs-sanction comparison or an AVG), `_pmay_sql_issue` (repair) and `_pmay_comparison_limit` (rewrite) in
`execute_with_repair`; `_pmay_rupee_format` after the composer; `_PMAY_RULES` 7–9 and three
few-shots in `pmay_few_shot.yaml`.

### 2.4b Metric catalogue fixed query (2026-10-26, D-071; LIVE-VERIFIED)

The data team's `semantic.metric_definitions` (62 measures; 39 for the six schemes, all 39 loaded) is loaded at
startup by `app/metric_catalog.py` (`METRIC_CATALOG_MODE`: off / shadow / **on**, default on). Code:
`app/metric_catalog.py` (load, match, build) and `app/pipeline/common/c16_metric_catalog.py` (the decision).

- **Where:** the LAST entry of the fixed-query chain in `_data_prepare_stage` (c13, `_mg_det = … or
  _metric_catalog_query(...)`). Every existing fixed query (PMAY-G facts, MGNREGA job cards / combined / breakdown /
  wage-material, CM Elevate sector, Focus Plus cohort, Focus Legacy duplicates / FY compare) keeps priority.
- **Match (`metric_catalog.match`):** the measure's synonyms and display name (scheme words stripped, plural-blind,
  helper verbs the rephraser adds such as "were" skipped). Longest phrase wins; two measures or a phrase two measures share
  -> no match.
- **Asks nothing else (`_c16_extra_words`):** every other word must be the scheme name, a resolved place, a year or
  question grammar (`_C16_GRAMMAR`, plus the shape's own words). "wage expenditure" -> "wage" is extra -> model path.
  **E7 (2026-10-29):** plus the MATCHED measure's own vocabulary (`_c16_measure_vocabulary`: its catalogue phrases and
  display name, stemmed): "person days generated" builds ("generated" is the measure's "employment generated");
  "job cards issued" (not the stock's word) and another measure's words still go to the model path.
- **Filters (`_c16_filters`):** only district / block / village / year (and their lists). Any other resolved filter
  (constituency, region, status, gender …) -> model path.
- **Shapes (`_c16_shape`):** `total`; `breakdown` by district / block / year (`_c02_breakdowns`); `ranking`
  (`_RANKING_CUE`, one direction, count from `_requested_rank_count`, 1 for a singular "which district"; plural with no
  count -> model path, the "top how many" pause owns it); `compare` (a place list, or several years).
- **Years:** a measure in the verified file's `single_year` (job cards, households / persons employed, 100 days) is built
  only for exactly one year or per year. No year and no all-years cue -> not built (the year pause asks first).
- **Gate:** the query answers only when the measure is listed for that shape in `data/metric_catalog_verified.yaml`
  (evidence from `tests/metric_catalog_eval.py`), and not when the question named it only by an `except_words` wording.
  Focus Plus has no block-level catalogue query (`no_block_level`: its blocks are on `block_name_raw`). Everything else
  is logged (`metric catalogue (shadow): …`) and answered by the model path.
- **B1 meaning shadow (2026-10-27, D-076):** a single-scheme question whose words name NO catalogue measure records its
  measure wording (the words left after scheme / place / year / grammar / shape words, ≤ 6) and the nearest measure by
  embedding to `logs/metric_meaning_shadow.jsonl` (`metric_catalog.meaning_shadow`, a background task: no added wait,
  never used to answer; `METRIC_MEANING_SHADOW`). `tests/metric_meaning/review.py` lists them; a person approves a
  wording into `data/metric_catalog_synonyms.yaml`, loaded at startup as an exact phrase like the data team's synonyms.
- **Query:** `/* metric:<key> <shape> */ SELECT <expression> AS <alias> FROM <base view> WHERE … [GROUP BY …]`, values
  bound as parameters, run on the READ-ONLY pool (`_data_deterministic_rows` -> `db.fetch_rows_readonly`). Units follow
  the SQL prompt: lakh -> `_lakh`, rupees -> crore `_cr`, percent -> `_pct`. Place groupings leave out NULL places.
  The rows go to `compose_response` as usual (every faithfulness check runs). `authorize` still checks the SQL.

### 2.5 Prompt assembly — `prompt_builder.build_sql_prompt(question, schemes, entity_result)`
The prompt is concatenated in this order:

```
build_schema_context(schemes)       # schema_context.py: _PREAMBLE, _SHARED_TABLES, per-scheme
                                    #   (_X_TABLES, _X_RULES, _X_VOCAB), _CROSS_SCHEME if >1 scheme,
                                    #   _SHARED_RULES, _CLOSING; [[name]] data figures filled live
                                    #   by data_facts.render (D-087, refreshed every 10 min)
_live_schema_block(schemes)         # schema_introspect: real columns + real FKs from megh_db
schema_introspect.catalog_block()   # semantic.table_catalog / glossary / metric_definitions (metric_key,
                                    #   sql_expression) / column notes + UNIT + VALUES lists (D-049);
                                    #   LIVE SCHEMA hides privacy tables and megh_readonly-denied columns
_prohibited_block(schemes)          # annotations: PROHIBITED JOINS from *_foreign_key_augmentation.yaml
_fewshot_block(...)                 # top_k=5 examples PER SCHEME (incl. UNANSWERABLE, sql=null)
_common_mistakes_block(schemes)     # WRONG → RIGHT shapes
_entities_block(entity_result, …)   # "RESOLVED ENTITIES — MANDATORY" + "NOT FOUND" lines
"The user's question is about: …"
'Question: "…"\nSQL:'
```

- **Few-shot ranking:** `annotations.few_shot_examples` ranks lexically by IDF. Tokens found in
  ≥25% of a scheme's pool are weighted 0.05. The ranking text is expanded with the resolved names
  (`_fewshot_ranking_text`).
- **Pool files:** `data/<scheme>/*few_shot*.yaml`. CM Elevate Legacy uses
  `cmelevatelegacy_prompt_few_shots.yaml`.
- **Example source switch (D-074 -> D-086):** `SQL_EXAMPLES_SOURCE=yaml` (the pool files above) is the default since
  2026-10-29 (D-086). `qdrant` was the default 2026-10-27 evening -> 2026-10-29 (user: use everything in both
  collections); the B5 measurement showed it needing 8 repairs vs 1 for yaml at the same accuracy.
  - **`yaml_meaning` (B5, 2026-10-29; not the default until measured):** the reviewed YAML banks ranked by meaning —
    one embedding of the ranking text per data question, cosine against each example's question and `variants`
    (`sql_examples._rank_yaml`, via `annotations.few_shot_examples(rank=…)`, refusal factor and cap unchanged). Each
    bank is embedded once per process in the background; until then the turn keeps the word ranking. No views / joins.
  - **Views and joins:** `qdrant` also reads megh_sql_metadata's 12 `kind=view` and 16 `kind=join` points (whole, cached
    10 min). `prompt_builder._sql_metadata_block` adds their `prompt_text` as the optional `sql_metadata` section
    (priority 5, the first to shrink). Views come first, then joins. A one-scheme prompt gets only that scheme's
    views; a join or cross view needs every scheme it names in the prompt. Under budget pressure it keeps the joins,
    then drops the section. Measured live: MGNREGA prompt 8.6K tokens with 3 views; MGNREGA + PMAY-G 13.5K (views
    dropped, joins kept).
  - **Notes:** an example's `notes` go into the prompt as a `Note:` line. With `qdrant`, `_data_sql_stage` calls `sql_examples.prefetch(_fewshot_ranking_text(..), schemes)`
  before generation. That is one `qwen3-embedding` call plus one search per scheme in `megh_sql_metadata`
  (`kind=example`), within `SQL_EXAMPLES_TIMEOUT_SECONDS=4`. `prompt_builder._fewshot_examples` then takes
  those per scheme, top 5 by meaning:
  - a two-scheme example is used only when both schemes are in the prompt (never in one half of a per-scheme
    cross question), and only once;
  - a failure, timeout or empty result keeps that scheme on YAML.

  Not on any graph node: the search runs inside the stage, and `build_sql_prompt` stays synchronous.
  The repair prompt carries no examples either way. All Qdrant examples are `validated: false` (KI-438).
- **Size:** measured offline 2026-09-24 without the live block (TECHNICAL_BRIEF §2.2): about
  3–7K tokens for one scheme and about 32K tokens for all six.
- **If the live schema load failed at startup**, `_live_schema_block` is empty and the prompt
  falls back to the hand-written text. The live block, the catalogue and the year list are
  loaded only at startup (DATA_MODEL §6).
- **Prompt injection (VERIFIED behaviour, risk INFERRED):**
  - The user's question is inserted verbatim into the classifier, SQL, verifier and composer
    prompts.
  - There is no instruction-stripping or input classifier. The edge layer only blocks off-topic
    and harmful *topics*.
  - A question engineered to make the generator emit a `SELECT` against `app.*` or a privacy
    table would pass `run_readonly`, and `authorize()` checks only
    scheme/geography/granularity.
  - The rows are returned to the client in `data`. See KI-004.

### 2.6 SQL generation — `generate_sql(question, schemes, entity_result)`
1. Call the **30B** (no decoding constraint; the old `guided_regex` was removed, D-046).
2. `_extract_sql` strips code fences and prose on the SQLGlot token stream (no regex).
3. `_focusplus_single_district_beneficiary_guard` post-processes the result.

**MGNREGA deterministic queries (2026-09-26, VERIFIED live).** For two MGNREGA shapes,
`_answer_data` skips the generator, the repair loop and the verifier. It builds the SQL from the
resolved single-valued filters (village_code, block, district, year_key) and runs it with
parameters bound, through `db.fetch_rows`. Authorization still runs, on a literal display copy of
the SQL.
- `_mgnrega_combined_facts_query`: "expenditure/spent AND person-days/employment" for one area.
  The query is one CTE per fact joined by `CROSS JOIN`, not the fan-out join.
  - Before this, the 30B wrote the join. The 4B verifier then flagged the correct two-CTE
    rewrite as a "prohibited join", and the repair moved to `v_district_year_summary`, which
    has no village or block column.
  - The result was a KB fallback (DATA-028) or "couldn't build a query" (DATA-029, 4 runs of 5).
  - Rankings, breakdowns, components (wages/material), ratios and constituencies stay with the
    generator (`_MG_COMBINED_EXCLUDE_MATCH`).
- `_mgnrega_admin_expenditure_query`: `SUM(admin_total_exp)`, answered by
  `_mgnrega_admin_expenditure_answer`. That answer states the recorded figure plus the
  "never populated at source" caveat, with the statewide non-zero count read live (D-025).
  - The pre-routing gate 1d now refuses only when the question is not MGNREGA.
  - PMAY-G and the multi-scheme wording are unchanged.

**Guards added 2026-10-14 (VERIFIED live, hierarchy matrix):**
- rewrite `_mgnrega_job_cards_latest_year` (SUM of job cards with no year filter → the resolved year; an all-years
  question is left to the stock guard, which asks for one row per `year_key`; `year_key = MAX` only when no year
  exists anywhere — D-057, 2026-10-21); the verifier's complaint about that pin is discarded;
- **2026-10-21 (KI-338):** rewrites `_mgnrega_unit_count_not_villages` (a households / persons count that names no
  village, read as `COUNT(DISTINCT village_code)`, becomes `SUM(households_employed | persons_employed)` with the
  `> 0` filter dropped) and `_mgnrega_drop_area_level_entity_type` (`entity_type` on the MGNREGA views is the row
  type, always 'Village'; an `entity_type = 'Block' / 'District' / …` filter matched nothing and is dropped);
  schema rule 4a says the same;
- **2026-10-21 (KI-337):** rewrites `_mgnrega_fact_to_view` (a one-table read of `fact_mgnrega_*` naming a view-only
  column — `lgd_*`, `village_code`, `entity_type`, FY labels — and no fact-only one is moved to its view; the repair
  model drifted to the fact table and failed "column f.lgd_village_name does not exist" on every attempt) and
  `_mgnrega_village_rank_placeholders` (an MGNREGA village ranking on one view gets `entity_type <> 'Unresolved'` in
  code, so the placeholder guard no longer needs a repair round trip);
- **2026-10-21 (D-057, KI-336):** one area's job cards are a deterministic query (`_mgnrega_job_cards_query`,
  `/* mg-job-cards */`, the year(s) asked or one row per year) answered by `_mgnrega_job_cards_answer` from the
  rows; job cards now take the year pause / the chat's year like every measure (chip "Every financial year (one
  figure each)"). The composer is handed the single year the SQL's WHERE pins (`_entities_with_sql_year`), so the
  answer's period is the query's; the prompt says "across all financial years" only when no year is pinned.
  `_finish_data_result` never calls a place known only by its code (`village_code`, lists) statewide;
- `_execute_one_attempt` sends back: an all-years question split by financial year alone
  (`_vr_grouped_by_year_only`: every GROUP BY expression a year column, so `year_key, financial_year_short` counts — KI-411, 2026-10-27; unless `_YEAR_SPLIT_ASKED`); an MGNREGA expenditure component named but its
  column not read (`_MGNREGA_EXP_COMPONENTS`); a village ranking without the "Unresolved" filter;
- `classify_intent`: a measure followed by "in <place> block/village/district/constituency" is DATA;
- `guardrails._DATA_QUESTION` overrules an OUT_OF_SCOPE model verdict for a plain or terse data question;
- c14 `_overrules_scope_verdict`: a Focus Plus batch ("12.5K", "12.5 K", "93K") with a status-breakdown shape, or named
  a batch / cohort with a measure word, overrules a scope verdict; the edge whitelist knows the batch labels,
  "tranch" and "break down" (KI-360, 2026-10-22);
- `_correct_fy_spacing` ("FY2022-23" → "FY 2022-23", "for the state" → "for Meghalaya") before routing;
- `_normalize_rank_counts` (c02, run right after it at c14 `_turn_*` line ~206; `raw_question` keeps the typed words):
  a ranking count written as a word becomes digits, in a ranking position only — "five highest" → "5 highest",
  "top ten" → "top 10", "twenty-five" → 25, "which three blocks" → "which 3 blocks". Left alone: ordinals
  ("fifth highest"), time spans ("last five years"), "the first one", "which one", "the two schemes"
  (RAG plan C2, 2026-10-26);
- `_RELATIVE_THAT` ("households that completed …" is not a reference to an earlier answer);
- `_data_entity_stage`: a chip resume ("…, X block, DISTRICT") is pinned deterministically for every scheme.

### 2.7 Authorization — `auth.authorize(scope, schemes, resolved_entities, sql)`
- Runs only when `AUTH_ENABLED` and a scope is present.
- Checks scheme, geography and granularity on the SQLGlot tree (`app/sql_ast.py`): every district/block value the
  query filters on, including `UPPER(col)`, every `IN` value and `OR` branches. Unparseable SQL is refused for a
  geo-restricted user (D-046, KI-303).
- A deny returns `route:"denied"` and **no SQL runs**.
- **Fixed answers that finish before the `authorize` node are authorised where they return** (KI-419, E12
  2026-10-29), through `_repaired_sql_denial` / `_denied`: the Focus Legacy group-name answer (scheme check in
  `_data_scheme_stage`; the answer keeps only groups inside the caller's area), the Focus Plus overall summary (its
  fixed SQL), cross_figures (`_c13_e12_cross_figures_denial`, from the plan's districts / block / per-district shape
  and before any query: the bundle's places are bind parameters and its village count would read as village level)
  and MGNREGA women-not-recorded (`_mg_women["shown"]`). The PMAY-G fixed path was already authorised. An area-pinned
  account gets the admin-expenditure caveat without its statewide figure.
- The scope itself fails closed (`auth.scope_from_user`, KI-421): no real scheme in the user's list gives no scheme,
  an unknown role is `public`, and the per-user cap can only narrow the role's cap.

### 2.8 Validate → execute → repair — `execute_with_repair(..., max_repairs=MAX_SQL_REPAIRS)` (Flow C)
The budget is 4 attempts in total (the initial one plus `MAX_SQL_REPAIRS = 3` repairs). Each attempt
runs these steps in order. Since 2026-10-02 one attempt is three functions:
- the rewrites (1) are `_scheme_sql_rewrites`;
- the guards, verifier, execution and post-check (2–4) are `_execute_one_attempt`;
- the repair call is `_repair_sql`.

`execute_with_repair` loops over them. The LangGraph path runs them as its `execute_attempt` ⇄
`repair` nodes, with the same budget and the same DB / budget re-raises. **Authorization:** the first
SQL is checked by `_data_authorize_stage`, and since 2026-10-02 every repaired SQL is checked too, after
the rewrites and before it runs (`_repaired_sql_denial`; D-033, KI-183). A denial returns `_denied`.

**1. In-place rewrites:**
- `_focus_legacy_geo_columns`
- `_uppercase_geo_literals`
- `_focusplus_drop_unrequested_verification_status`
- `_cm_legacy_keep_unresolved_off_village` (CM Elevate Legacy, Focus Legacy and, since
  2026-09-27, CM Elevate: KI-068)
- **CM Elevate only (2026-09-27, use-case QA, KI-069 / 070 / 072 / 074):**
  - `_cm_elevate_split_scheme_in_list`: a `scheme_name IN (…)` with 2+ programmes and no
    `GROUP BY scheme_name` gets `scheme_name` added to the SELECT and the GROUP BY. The IN list is
    read on the SQLGlot tree, so "(SEED)" inside a literal is no problem.
  - `_cm_elevate_sector_zero_groups`: a GROUP BY `sector_id` query with one
    `data_verified = '…'` in the WHERE moves that test into `COUNT(*) FILTER (…)`, so sectors
    with 0 stay listed.
  - `_cm_elevate_level_pending`: "pending at level N" drops an AND-ed `data_verified = 'On
    Hold'` when `current_level` is filtered.
  - `_cm_elevate_pending_without_level`: a plain "pending" (no level or stage named) that was
    filtered on `current_level = 'levelN'` is swapped back to the pending target —
    `data_verified = 'On Hold'` while file_status is locked, the pending funnel once readable.
  - `_cm_elevate_pending_funnel` (2026-10-30, D-B1-CME-01, gated on `cme_pending_rule.readable()`):
    a plain "pending" or "on hold" written as `data_verified = 'On Hold'` becomes the pending rule
    (`app/cme_pending_rule.sql()`, built from `cmelevate_pending_rule.yaml`;
    WHERE or FILTER); a query with no status test gets the rule inside its single COUNT's FILTER when
    it groups (level-wise, district-wise), else AND-ed into the WHERE. Another named state (Invalid,
    verified, forward, resubmit, rejected) is left alone.
  - `_cm_elevate_decision_status_column`: `current_file_status = 'pending'` (a value that column
    never holds) → the pending target above.
- `_cm_legacy_qualify_shared_geo_cols`
- **CM Elevate Legacy only (2026-09-29, use-case re-test + all-levels run):**
  - `_cm_legacy_sanctioned_count` (KI-166): a "sanctioned applications" count written as
    `COUNT(*) AS sanctioned…` becomes `COUNT(sanctioned_amount)`; a sanctioned question whose SQL
    has no sanction column gets `COUNT(sanctioned_amount) AS sanctioned_records`. Not / de- /
    non-sanctioned aliases and FILTER forms are left alone.
  - `_cm_legacy_unrequested_limit` (KI-168): a trailing LIMIT on a grouped result is dropped
    unless the question states a count (a singular "which scheme has" keeps LIMIT 1).
  - `_focus_legacy_village_code_only` now also covers CM Elevate Legacy and drops a
    `lgd_village_name` literal beside a pinned `village_code` (KI-173).
- `_mgnrega_numeric_division` (MGNREGA only, 2026-09-26, KI-044): casts the numerator of
  `SUM(<integer employment measure>) / …` to `numeric`, so person-days per household reads
  38.16, not the integer-truncated 38.00.
- `_mgnrega_lakh_not_divided` (MGNREGA only, 2026-09-26): removes a `÷100` applied to
  MGNREGA money whose alias still says `…lakh`. In the DATA-023 run, 219.48 lakh of wages was
  printed as "2.19 lakh". `_crore_conversion_for_single_village` only fires when the SQL says
  "crore".

- `_mgnrega_pin_village_code` (MGNREGA): when one village was resolved and the SQL filters a
  single different `village_code`, or an IN-list, the resolved code is substituted (AMPATIGRI,
  MAWKOHMIT & MAWKYNSAH).
- `_mgnrega_drop_geo_beside_village` (MGNREGA): removes `lgd_block` / `lgd_district` literals
  next to the resolved `village_code`. In the MAWLIEH case the generator added the wrong
  district.

**2. Deterministic guards.** Each one raises a `ValueError` whose message becomes the repair
instruction:

| Guard | Catches |
|---|---|
| `_focusplus_stated_amount_missing` (Focus Plus, KI-132, 2026-09-29) | a stated payment amount ("a loan of five thousand", "₹2,500 payments") with no `amount_disbursed = N` filter |
| `_resolved_scope_missing` (all schemes, KI-034, 2026-09-29) | a resolved district / block / comparison list / year_key absent from the SQL. Not required: geography beside a resolved village_code, a hill-range expansion, a year for CM Elevate or an all-years question; LIKE on the distinctive word counts. **KI-432 (2026-10-29):** a resolved assembly constituency must be in the SQL too; the MGNREGA prompt line names `assembly_constituency_name` (v_employment) and `ac_name` (v_expenditure). **KI-427 (2026-10-27):** a stated span is resolved as `year_key_list` (every year, c09 `_c09_stated_year_span`, prompt line `year_key BETWEEN A AND B`); every year must be in the SQL as a literal or inside a BETWEEN with the span's ends |
| `_mgnrega_village_filter_missing` (MGNREGA, KI-054) | a village was resolved but the SQL filters no village (it would return a block or statewide total) |
| `_village_filter_missing` (every single-scheme question, KI-188, 2026-10-02) | the same for the other five schemes. Its deterministic half, `_pin_missing_village_code` (in `_scheme_sql_rewrites`), first rewrites a simple one-SELECT query: adds `village_code = <code>`, or replaces a lone `lgd_village_name` text condition with the code (`_village_name_cond_to_code`, KI-197), and drops a block / district literal beside it in any UPPER / TRIM form (`_drop_geo_beside_pinned_village`, KI-196). D-034 |
| `_mgnrega_village_list_issue` (MGNREGA, KI-045) | "which villages …" SQL with no `lgd_village_name`, or "received employment" without `HAVING SUM(persons_employed) > 0` |
| `_mgnrega_comparison_without_figures` (MGNREGA, KI-047; checked on the result, after execution) | a comparison ("more on wages or materials?") whose rows hold no number, only a CASE label |
| `_focus_legacy_group_size_summed` | SUM of `no_of_pg_members` for a group-size question (must be MAX per `pg_id`) |
| `_village_name_filter_instead_of_code` | filters `lgd_village_name` when a `village_code` was resolved |
| `_village_filtered_at_wrong_level` | a village name placed in `lgd_block`/`lgd_district` |
| `_village_code_as_geography_key` | `geography_key = <village_code>` |
| `_crore_conversion_for_single_village` | MGNREGA lakh÷100 for one village (shows "0.00 crore") |
| `_mgnrega_facts_joined` | `v_employment` JOIN `v_expenditure` (row fan-out) |
| `_ac_with_invented_geo_filter` | an AC filter ANDed with an invented block or district |
| `_STATE_PSEUDO_FILTER` | a `'Meghalaya'` / `entity_type='State'` filter |
| `_rowgrain_no_aggregate` | a bare row read on a row-grain view for an aggregate question |

**3. Semantic verifier:** `_verify_sql` (**30B `qwen-model`**, `SQL_VERIFY_MODEL` in `app/config.py` — not the 4B
since 2026-10-15; runs AFTER execution; `build_verify_prompt`, `guided_json {ok, issue}`).
- It judges the SQL against the same schema, the resolved entities and the calibration examples.
- **Failure-open:** any error means "no issue".
- **False-positive filters** discard known-bad complaints:
  - `_VERIFIER_FALSE_EMPTY_ENTITIES`
  - `_verifier_complaint_is_cosmetic`
  - `_verifier_year_complaint_is_false`
  - `_verifier_apostrophe_complaint_is_false`
  - `_verifier_missing_geo_is_false`
  - `_verifier_wants_suppressed_geography`
  - `_verifier_check2_on_empty_entities`
  - `_verifier_join_complaint_is_false`
  - `_verifier_scheme_specific_complaint_is_false` (CM Elevate, 2026-09-27): the 4B model said
    `v_cm_elevate` has no `scheme_specific` column. The complaint is discarded when the SQL reads
    only the live-verified keys (`file_status`, `sector_id`, `gender_id`, `occupation_id`).
  - `_verifier_village_code_complaint_is_false` (MGNREGA)
  - `_focus_legacy_ac_verifier_complaint_is_false` (Focus Legacy, KI-369, 2026-10-22): a join / resolved-entity /
    letter-case complaint against the documented constituency query (`v_focus_legacy` + `dim_geography` joined on
    `geography_key`, `ac_name` = the resolved constituency) is discarded; a measure / grain complaint stands. The 30B
    called that join "prohibited" and the repairs answered the constituency's district (Dalu 928 for 203).
  - `_focus_legacy_aggregate_complaint_is_false` (Focus Legacy, KI-371): "without aggregating no_of_pg_members /
    wrap it in SUM()" when the SQL already SUMs exactly that column.
- PMAY-G constituency (D-096, 2026-10-30, KI-445): a resolved `assembly_constituency` with no finer place is a fixed
  `_pmay_facts_query` shape (dim "ac", `UPPER(ac_name) = ANY(...)`, answer "<X> assembly constituency"); the SQL
  prompt's entity line names `UPPER(ac_name)` on `v_pmay` (no join). Model path: rewrite `_pmay_ac_name_case`
  (`ac_name = 'X'` -> `UPPER(ac_name) = 'X'`, dim_geography is Title Case) and guard `_pmay_ac_filter_missing` (a
  resolved constituency the SQL does not filter on `ac_name` -> repair, never the district's or the state's figure).
  Shared village names (KI-630): `village_twins` is a fixed-query key too — one block-named row per village, never a sum.
- Focus Legacy guards in `_execute_one_attempt` (2026-10-22): `_focus_legacy_ac_filter_missing` (a resolved
  constituency the SQL does not filter on `ac_name` -> repair, never the district's figure; KI-369) and
  `_focus_legacy_members_counted_as_groups` (a "members" question answered with `COUNT(DISTINCT pg_id)` only; KI-371).
  Rewrites: `_focus_legacy_ac_name_case` (`ac_name = 'X'` -> `UPPER(ac_name) = 'X'`, dim_geography is Title Case) and
  `_focus_legacy_scheme_name_not_variant` now also drops `pg_entity_type = 'FOCUS_PG'` read off "FOCUS PG(s)", even as the
  only condition, unless the question asks about the group type (KI-370).

**4. `db.run_readonly(sql)` [DB]:** the safety check, auto-`LIMIT 1000`, a 15 s statement
timeout. **Since 2026-10-27 (D-073), with `CHATBOT_DATABASE_URL` set, the guarded statement runs as
`semantic.run_query(sql, SQL_MAX_RESULT_ROWS, SQL_MAX_COST)` on the `megh_chatbot` login**: the database
plans it, refuses fact row joins and plans above 1,000,000, and runs it with megh_readonly's rights.
The JSON rows are turned back into exactly what asyncpg returned (column order from `columns`; each
value's type from run_query's `types` list — sent since the team's 2026-10-27 reply — else from describing the statement on
megh_readonly — parse only, never executed): 582/584 recent statements identical in values and types,
the 2 others the same rows in another order (no ORDER BY). Refusals map onto existing errors:
`row_join` -> `RowJoinRefusedError` (ValueError, repair), `rejected` -> `UnsafeSQLError`,
`too_expensive` / 57014 / 53400 -> `QueryTooHeavyError`, class 08 / 53300 -> one retry after 1 s then
`DatabaseUnavailableError`, anything else -> `RunQueryError` (PostgreSQL's message, to repair). The
`check_query` pre-check below is skipped then (run_query makes it). Just before it (2026-10-27, D-072), `db.precheck_readonly` asks the database's
`semantic.check_query` to plan the query: a `row_join` (two fact tables joined row by row, seen
through views and CTEs) raises a `ValueError` that goes to repair without running the query.
Fail-open: no pool yet (offline), a missing function, a 5 s timeout or any error means no check;
`SQL_DB_PRECHECK=false` turns it off (~150–370 ms over the VPN). The server limits of megh_readonly
(DB team 2026-10-27) — 57014 statement_timeout, 53400 temp_file_limit (1 GB) — come back as
`db.QueryTooHeavyError`, a `TimeoutError`: one repair round with the reason, then the router's
504 "try a narrower question" (not the KB fallback). Other errors are unchanged; repairs stay
as they were (a timeout repaired into a working query on 2026-10-18, so timeouts are not made final).

**5. On any exception:** `build_repair_prompt` (the same context **without few-shot examples**,
plus the error and `_repair_hint`) → **30B** → `_extract_sql` → loop.

**6. When the budget is spent**, the exception propagates. See §3.4.

**The catch is `except (UnsafeSQLError, Exception)`, so *every* failure inside an attempt
triggers an LLM repair**, not only SQL errors (VERIFIED). That includes:
- a DB connection error (e.g. `WinError 121`);
- a pool or connect failure;
- asyncpg's 15 s `command_timeout`, which surfaces as `asyncio.TimeoutError`;
- `UnsafeSQLError`.

What happens once the budget is spent:
- **An infrastructure error** (e.g. a DB outage) costs up to 3 pointless 30B calls. It then
  reaches `_run_pipeline`'s generic handler, and the user gets the misleading "couldn't build a
  working query" (KI-025).
- **A slow query** re-raises `asyncio.TimeoutError`, which `_run_pipeline` treats as transient.
  The router returns **504**.
- **An `UnsafeSQLError`** ends in the KB fallback. The router's own `UnsafeSQLError → 500`
  branch is therefore effectively unreachable.

What is *outside* the try: the repair call itself (`call_sql_generator` inside the `except`
block). A gateway timeout, a 5xx or a `ModelBusyError` there propagates immediately.
Separately, `_verify_sql` swallows every exception, including `ModelBusyError`. **Under load,
verification is silently skipped.**

**Gaps (KI-003):** there is no convergence check (the identical SQL can be retried 4 times), and
the failing SQL is never logged.

### 2.9a CM Elevate Legacy answer guarantees (2026-09-29)
After the composer, every CM Elevate Legacy DATA answer passes `_cm_legacy_answer_guarantees`
(deterministic; prose rules had failed under sampling):
- `_cml_single_row_sentence` replaces the raw fallback dump ("0.58 total disbursed cr.") with a
  sentence naming the place and each figure (KI-176).
- `_cml_complete_list` rebuilds a per-group COUNT list whose figures are not beside their names
  ("… respectively"), under the composer's headline (KI-174; detection shared with CM Elevate's
  `_cme_complete_list`; year and money breakdowns untouched).
- `_cml_village_breakdown` rebuilds a garbled village list or one with a false "each of the N
  villages" claim, and adds the total when it is missing (KI-177).
- `_cml_fix_each_have_counts` recomputes every "N villages each have V records" from ALL rows —
  the composer sees 40 rows and the faithfulness check ignores whole numbers < 100 (KI-167).
- `_cml_fix_place_spelling` restores the stored spelling of the filtered place and of the
  result's place labels ("Sellsella" → Selsella; KI-172).
- `_cml_exact_single_amount` re-queries the exact rupees of a one-row figure under ₹0.10 crore:
  "₹0" instead of "under ₹0.01 crore", "₹0.01 crore (₹1,25,000)" (KI-171; `_cml_inr` = Indian
  grouping).
- `_cml_unmapped_in_scope` states the records with no village code that a village list leaves
  out, re-queried from the same scope (KI-167).

Resolution changes the same day: the village chip-tail pin runs for CM Elevate Legacy (KI-169);
twin-village chips rank by the scheme's own records (`_TWIN_RANK_VIEWS`, KI-170); urban bodies map
to CM Elevate Legacy's own stored blocks (`_cm_elevate_block_names(scheme)`, KI-175); a resolved
village settles the Garo-range check (KI-178); and, for ALL schemes, a trailing "village" is
dropped from the extracted village name when only the bare name is a stored village (KI-179).

**Constituency guards (2026-10-22, KI-381)**, run in `execute_with_repair` like the Focus Legacy KI-369 twins:
`_cm_legacy_ac_as_place_filter` (rewrite: a resolved constituency filtered as a district / block / village ->
`JOIN curated.dim_geography g ON g.geography_key = v.geography_key … UPPER(g.ac_name) = '<AC>'`),
`_cm_legacy_ac_name_case`, `_cm_legacy_ac_filter_missing` (no `ac_name` filter for a resolved constituency -> repair,
never a district's or the state's figure) and `_cm_legacy_ac_verifier_complaint_is_false` (a "prohibited join" /
entity / case complaint against the documented query is discarded). **No records (KI-383):** `_cml_no_records_sentence`
answers a one-row, all-empty result "No CM Elevate Legacy records are held for <place> in <FY> …", never "null" or "₹0".

**Overview routing (2026-10-22, KI-382, c14 route stage):** an overview / briefing request (`_OVERVIEW_REQUEST`) with no
place (`named_places`, `_overview_names_a_place`), count word or figure word (`_C14_FIGURE_WORDS`) is KNOWLEDGE even
when the sampled classifier says DATA; CM Elevate overviews are retrieved with `_scheme_overview_question` (as Focus
Legacy's were).

### 2.9 Result handling and composition
1. **Notes** are assembled from:
   - the resolver notes;
   - `_genuine_zero_notes`;
   - `_sector_not_tracked_notes`;
   - CM Elevate Legacy: `_cm_legacy_answer_notes`, `_cm_legacy_small_money_notes`, and
     `_cm_legacy_exact_totals`, which **re-queries exact totals in code** because the composer
     summed rounded rows wrongly. The subsidy/loan note now depends on the columns present
     (KI-176: told to "give all three" with only a total, the composer invented a split);
   - Focus Legacy: `_focus_legacy_answer_notes`, and `_focus_legacy_list_total`, which gives the
     true count of a truncated list; `_focus_legacy_unplaced_row` (KI-145), which re-runs a
     per-place breakdown without the model's `IS NOT NULL` filter to read the records that have
     no block / village / constituency. A one-place-column breakdown is then written by
     `_focus_legacy_breakdown_answer` and the composer is skipped (D-031, KI-150);
   - MGNREGA: `_mgnrega_answer_notes` (2026-09-26). It says three things:
     - a top-1 row is the statewide top, not "the only one" and not "the highest in its
       district";
     - money is in ₹ lakh, so write "lakh";
     - places are named in plain words, not `lgd_*` column names.

     These are backed deterministically after composition by `_mgnrega_top_one_wording`, which
     drops an "only district … in the result" sentence, and by `_mgnrega_money_units`, which
     adds " lakh" after a result amount stated without a unit.
   - `premise_check.check_premises` (`PREMISE_CHECK_ENABLED`).
2. **`compose_response(question, sql, rows, notes, entities, schemes, style_examples, extra_numbers)`**
   runs the **9B**:
   - **No rows (Flow D):** `_no_data_answer` is deterministic, with no model call.
   - **An all-NULL row, or all zero/NULL metrics:** the prompt adds "metrics the data DOES carry"
     (`available_metrics_text`) so the model says the metric is not tracked instead of reporting
     0.
   - **Multi-row results:** `_result_digest` supplies deterministic totals, mean, max and min
     over *all* rows. The composer sees at most the first 40 rows.
   - **Faithfulness checks:**
     - `_answer_numbers_faithful`: every number stated must appear in the result or the digest,
       within 0.5% tolerance;
     - `_answer_covers_metrics`: a single row must have every metric reported.
     - MGNREGA empty and zero results (KI-056): `_mgnrega_empty_answer` handles an all-NULL
       single row. A parameter-bound row count decides the wording:
       - "No MGNREGA … is recorded for X" when nothing matched;
       - "cannot be calculated … divided by 0" for a NULLIF ratio over existing rows.

       It skips the composer. `_mgnrega_null_zero_notes` and `_mgnrega_zero_backstop` handle one
       empty side of a combined row and genuine zeros.
     - MGNREGA exception (2026-09-26): when the question itself names the "100 days" measure,
       `100` is added to the allowed numbers. It is the measure's name, and correct sentences
       were being replaced by the row dump "3.39 completion 100 day pct.".
       `_answer_numbers_faithful` itself is unchanged, and any other wrong number is still
       caught (test `test_a_real_misquote_is_still_caught`).
     - **All schemes (2026-09-27, Focus Plus QA):**
       - **Mis-grouped digits (KI-062):** `_fix_digit_grouping` runs on the composed answer
         (and on the strict retry) before the check. The check strips commas, so "1,0263"
         passed as 10,263. A token valid in neither Western nor Indian grouping is re-grouped
         only when it has 4+ digits **and** its digits are a result value ("Tranches 1,2" is
         untouched).
       - **SQL filter literals (KI-064):** `_sql_literal_numbers(sql)` adds the numbers inside
         the executed SQL's quoted literals (`'12.5K'`, `'Tranch 4 - Feb-March'`) to the
         allowed set. They are the filter's labels. "…under the 12.5K batch" had been flagged
         as a misquote ("12.5"), and the fallback printed "31,317,500 amount raw.".
     - On failure → **one strict retry (9B)** → then `_deterministic_answer`.
   - **Hedge guard:** if the answer hedges ("not covered", "no data") over a real non-zero value
     → `_deterministic_answer` or `_deterministic_list_answer`.
3. **Post-composition guarantees:**
   - Focus Legacy (2026-09-29): `_focus_legacy_answer_guarantees` — month numbers become month
     names in the right calendar year of the FY (`_focus_legacy_month_labels`), money cells and
     their column sums become ₹ with Indian grouping (`_pmay_rupee_format(fmt=, column_totals=True)`,
     KI-147); `_focus_legacy_unplaced_guarantee` replaces the composer's own "no block" sentence
     with one exact, digit-form sentence (KI-145);
   - the Focus Legacy true-total line is prepended if the composer dropped it;
   - the year-gap note is prepended if the composer dropped it;
   - **Focus Plus (2026-09-27, KI-060/061/064): `_focusplus_answer_guarantees`**, gated on
     `schemes == ["Focus Plus"]`, in this order:
     1. `_fp_complete_list`: a per-category list (one label column, one figure, 3–15 rows)
        that leaves out any label is rebuilt from the rows ("The remaining districts show
        11,379, 11,007, …" had no district names).
     2. `_fp_breakdown_shares`: a GROUP BY status / verification / gender / occupation count
        gets "Share of the N … with a recorded X: A p%, …" plus the 12.5K-cohort note. It is
        skipped when a second label column exists, for money columns, or when the shares are
        already stated.
     3. `_fp_single_count_share`: a one-number count filtered on a person attribute gets "That
        is p% of the N beneficiaries in the 12.5K registration cohort …". Numerator and
        denominator are **parameter-bound recounts** (`COUNT(DISTINCT beneficiary_key)`) of the
        same WHERE, parsed by `_fp_parse_where`. That parser accepts only equality and
        IS NOT NULL on whitelisted columns; OR, IN, joins and subqueries → skipped. The share
        is stated **only if the recount equals the bot's own figure**. Any DB error leaves the
        answer unchanged.
     4. `_fp_comparison`: a compare / versus / "which is higher" question with a 2-row result
        gets "X is higher by D (X a vs Y b)". The metric is chosen from the question
        (beneficiaries / disbursement / payments). A "combined total" sentence equal to a+b is
        dropped. Skipped when the difference and a "higher" word are already stated.
     5. `_fp_format_numbers`: an amount equal to a result money value (or a money column's
        total) is written `₹126,197,500.00`; counts ≥ 10,000 get separators; "amount raw" →
        "amount disbursed".
   - **CM Elevate (2026-09-27, KI-068 to KI-074): `_cm_elevate_answer_guarantees`**, gated
     on `schemes == ["CM Elevate"]`, in this order:
     1. `_mgnrega_zero_backstop` (reused): a hedge over an all-zero single row → "0 … — the data
        records zero".
     2. `_cme_grouped_rows`: a result with two label columns (scheme × sector, scheme ×
        district) and up to 30 rows is rebuilt, grouped by programme with group totals, when
        some row's figure is not in a sentence naming one of its labels, or when the text says
        "respectively" or "each corresponding row".
     3. `_cme_complete_list`: only for "each / every / wise / distribution / breakdown / all …"
        questions. A one-label list with a row missing from the text is rebuilt, ending
        "Total N". A "which is highest" answer naming its top few is left alone.
     4. `_cme_multi_scheme_total`: SQL with a `scheme_name IN (…)` list gets any missing
        programme figure plus "Combined across these N programmes". The sum is exact because
        `request_id` never repeats across programmes.
     5. `_cme_comparison`: a compare cue on a programme × place result gets "Differences: …
        higher by D (a vs b)" per programme and per place. A one-label two-row result reuses
        `_fp_comparison`.
     KI-074 was decided on 2026-09-28 (product owner): "pending" = `data_verified = 'On Hold'`
     only; the interim `_cme_pending_file_status` second line was removed. **Superseded on
     2026-10-30 (D-B1-CME-01):** pending = Valid → file_status Pending / Send Back.
     The fixed `cme-sector-workflow` / `cme-sector-pending` queries count that funnel and
     `_cme_pending_answer` states it, once `scheme_specific` is readable by the chatbot's role
     (KI-624); until then the 2026-10-26 "not recorded" answer stands.
4. **Result:** `route:"data"`, `rows[:20]`, `data` = all rows, `row_count`, `sql`.

---

### 2.9b Answer framing (2026-10-19, D-054, KI-321)

`compose_response` ends with `_finish_answer(answer, rows, schemes, entities)`, and the finalize node runs
`_finish_data_result(result)` on every DATA result (composer, scheme deterministic facts, fixed queries alike): result
figures of 4+ digits get thousands separators (a year-like value never), and a single-figure answer naming neither the
scheme nor the area gets one closing scope sentence built from the resolved entities (`_display_from_resolved`,
`_scope_words`). The deterministic fallback used when the composer misquotes numbers is `_framed_fallback`: a briefing
sentence with a plain-words label per column (`_HUMAN_METRIC`), the money unit, and the household-years / person-years
caveat (`_METRIC_CAVEAT`). `_deterministic_answer` is unchanged for its other callers; `_is_fallback_answer` recognises
both forms (CM Elevate Legacy guarantees). Failed data turns (`answer_failed`) are left untouched.

### 2.9c Answer shapes (2026-10-22, D-063, KI-377)

`compose_response` reads the answer's shape before writing the prompt (`app/pipeline/common/c12_answer_shapes.py`):

| Shape | Detected from | The composer is told | Fallback (`_shaped_fallback`) |
|---|---|---|---|
| `ranking` | outer ORDER BY on a result measure (SQLGlot) + LIMIT < 200 or a rank word | lead with #1; numbered list in order (≤ 15); one closing gap sentence; lowest-first never "leads" | "Top N <items> by <metric> (scope):" + numbered list + gap |
| `compare` | 2 rows, or ≤ 3 + a compare word | verdict first: who is higher, difference and % | "A is ahead on X: a against b for B — a difference of d, p% more" |
| `trend` | a period label (year / fy / month) over ≥ 3 rows | first -> last change and %, peak, lowest; per-period list if ≤ 6 | "X went from a in P1 to b in Pn (+d, +p%); peaked at …" + list |
| `breakdown` | one varying label, otherwise | total, largest / smallest with share, list largest first | total + largest / smallest + list |
| `cross_tab` | two varying labels | total and the standout cells; no cell list | `_framed_fallback` |
| `list` | no measure | count, then the names | `_deterministic_list_answer` / `_framed_fallback` |
| `profile` | one row, ≥ 2 measures | every figure labelled (list when ≥ 4) | `_framed_fallback` |
| `single_value` | one row, one measure | the 2026-10-18 prompt unchanged | `_framed_fallback` |

`yes_no` (the question opens with is / are / does / did / has / can …) adds "open with Yes or No". The derived figures
(`_shape_facts`) go into the prompt as "Derived figures — computed by code" and into `data_nums`, so a gap, % change or
share the composer quotes passes `_answer_numbers_faithful`. Cross-scheme rows (several `scheme` values) have no shape.
The log line `compose_response: answer shape <kind>` records the shape of every composed answer.
**Query plan shadow (E1 stage 1, D-078, 2026-10-27):** after a data / knowledge turn, `_update_context` schedules `query_plan.shadow` (background): a typed plan of the question (4B guided JSON + deterministic years / top-N / measure / area level) logged with the turn's actual decisions to `logs/query_plan_shadow.jsonl`. Nothing reads it yet.
**Open-bug sweep (2026-10-29):** follow-ups — `_compare_with_place_followup_question` (KI-364, also for a whole-sentence "compare … with <place>"), `_c14_keep_block_level` (KI-037), `topic_memory._bare_place` for "go back to <place>" (KI-318); resolver — two or more named years -> `year_key_list` (KI-311), HQ-town names ask (KI-036, `_c09_hq_alias_readings`); SQL — Focus Plus district columns -> lgd_district (KI-359 / KI-426), MGNREGA constituency guard and v_expenditure.ac_name (KI-432), village-with-employment count guard (KI-436); repair — convergence and a 40 s budget (D-088); composer — CM Elevate level wording (KI-422), Focus Plus cohort zeros (KI-365); knowledge — bare FOCUS beside Focus+ (KI-290).
**Trend direction (KI-441, 2026-10-27):** `_c12s_fix_trend_direction` (last step of `compose_response`) sets the answer's first rose / fell verb from the sign of the trend's first-to-last change; the 9B had copied the example's "rose" over a fall.

**Query plan in the turn (E1 stage 2a, D-085, 2026-10-29) — OFF by default (`QUERY_PLAN_IN_TURN`):** when on, a new question's plan starts in c14 `_guardrail_check` right before the guardrail model call (`query_plan.start_for_turn`, kept in `session.turn_context`); not awaited; a refusal cancels it; `_update_context` hands it to the shadow (`take_for_turn`, `plan_from: "turn"`) instead of a second call. Off because, measured live, the two 4B calls queue on the gateway: turn median 11.8 s -> 14.1 s. Stage 2b: `_c13_intent_by_rules(question, session)` reads the plan's intent in place of its last-resort classifier
call (after every cue rule; OTHER / no plan / other words -> the call), via `query_plan.turn_plan(session, question)`.
Held-out set on vs off: 42/74 both, identical outcomes, +0.35 s median per question on -> left off.

**ROLLUP total rows (2026-10-22, KI-384):** `_c12s_rollup_split(sql, rows)` separates the rows a `GROUP BY ROLLUP` /
`CUBE` / `GROUPING SETS` adds (the group column NULL or its `COALESCE(col, '<label>')` fallback, e.g. "ALL DISTRICTS")
from the category rows. The shape, the derived figures, the fallbacks and the list-size check use the category rows;
the total row is given to the composer as "the query's own TOTAL row (not a category)". CM Elevate Legacy's few-shots
ask for that row on purpose (exact totals); before this the summary read it as a 13th district (5,646 for 2,823).

### 2.9d Answer formatting — E9 (2026-10-29, D-082, KI-447..449)

Three parts, all in `compose_response` and the c12 files:

1. **One money formatter** `_c12_money(value, unit)` (`unit` from the column suffix: `_c12_money_unit`): ₹, Indian
   grouping; a `_lakh` / `_cr` value stays in its unit at 2 decimals from 0.10 of it, else drops a unit (₹1,25,000 is
   never "0.01 crore"); a `_rupees` value is crore from ₹1 crore, lakh from ₹1 lakh, exact below; zero is "₹0".
   `_c12_fmt_value(col, v)` adds "%" for a pct column and leaves counts as `_fmt_num` (count grouping is an open
   decision). Used by `_deterministic_answer`, `_framed_fallback` and the templates. Scheme writers keep their own
   formats (KI-449).
2. **Figure-to-label check** `_c12_label_misbinds(answer, rows, derived)`, run after `_answer_numbers_faithful` and on
   the strict retry. For each figure that IS a result value (and not a code-derived total / gap / share): followed by
   more / less / higher / ahead … → must be a difference of two values; written ₹ / lakh / crore but only a pct value
   (or % but only money) → wrong unit; tied to a row name (name then figure with only spaces / dash / colon / bracket
   between, "<figure> in|for|at <name>", or the only name in its clause for figures ≥ 100 or with decimals) → must be
   that row's; followed (or preceded by "Label:") by another measure's words and none of its own → wrong measure. Hits
   are listed in the retry prompt ("put a figure next to the wrong label (…)"). Years, FY spans, "#1", list ordinals
   and small whole numbers not tied to a name are skipped.
3. **Templates per shape** (`ANSWER_TEMPLATES_ENABLED`, default true; conftest sets it false for the older suites):
   for `ranking` / `compare` / `trend` / `breakdown`, `_c12s_e9_body(shape, rows, question)` writes every line with a
   figure and `_c12s_e9_framing` asks the composer for ONE opening line with no figure (allowed numbers: years / FY
   spans, the SQL's own literals, the list size, digits in the entity names) and no verdict word for the shape
   (`_C12S_E9_FRAME_BANNED`); otherwise `_c12s_e9_frame_default` ("Top 5 blocks by person-days of employment
   (MGNREGA, East Khasi Hills district, FY 2023-24):"). A failed call also gives code's line. Answer = opening line +
   body, then `_finish_answer`. Body per shape:

| Shape | Always | Only when the question asks |
|---|---|---|
| ranking | numbered list in the query's order (≤ 15, then "…and N more in the table.") | "A is <gap> higher / lower than B." (gap / ahead / how far / compare …) |
| compare | "A is higher than B on <what>: a against b, a difference of d (p% more)"; equal sides said so; other measures one line each | — (% omitted for a non-additive measure; points for a %) |
| trend | "<What> rose / fell from a in P1 to b in Pn, up / down d (p%)." + per-period list (≤ 15) | "The highest was … in …; the lowest was … in …" (peak / highest / lowest …) |
| breakdown | "A is the largest with a; Z is the smallest with z." + list largest first (≤ 15) with other measures | total (total / overall …); shares (share / percent / % …) |

   Periods read "FY 2022-23" (also for a `year_key`). A measure repeated in a second money unit (`total_exp_lakh` +
   `total_exp_cr`) is said once; alias shorthands are said in full ("exp" → expenditure). The composer keeps the whole
   answer for: other shapes, yes / no questions, a premise correction note (`The question treats "…`), `extra_numbers`,
   ROLLUP total rows, no usable value. Other notes and the style shots go to / do not block the opening line. With the
   templates on, `_shaped_fallback` returns the templated answer under code's opening line. Log line:
   `compose_response: templated <kind> answer`.

### 2.9e RAG fix report fixes (2026-10-29, D-089..D-091, KI-574..KI-590; LIVE-VERIFIED in-process)
The tester's report (`megh_rag_fix_report.md`, 17 issues) and where each fix lives — all in stage functions or the
scheme files, no graph node changed:
- **Route stage (c14):** `_hybrid_split` — "<rules> and <scoped figure>" answers the rules half from the KB as the
  answer's preface (sources kept, `_attach_preface`) and runs the figures half as DATA. `_guardrail_check`: a 4B
  `scope_general` on a question naming Meghalaya is overruled when megh_knowledge scores ≥ 0.45
  (`_c14_kb_covers_meghalaya`); the knowledge stage then picks `rag.best_kb_scheme` instead of asking.
  `_ENTITLEMENT_QUESTION` also reads "how much assistance per house" / "unit assistance".
- **Intent (c13 / c01):** `_wage_rate_question` -> KNOWLEDGE (the notified rate is not in megh_db).
- **Clarification gate (c13):** `NEW_CHAT_ASKS_SCOPE` (false) — no place = statewide, no year = all years, stated;
  "this year / current FY / the latest year" = the scheme's latest held FY; `_c13_unresolved_named_place` — a named
  district / block that resolves to nothing -> "I couldn't find a district called …" + district chips (`unknown-place`).
- **Fixed queries (c13 chain):** `_mgnrega_villages_active_query` — "how many villages" = employment ∪ expenditure
  (the card's rule). **SQL rewrites (c11 chain):** `_mgnrega_summary_ratio_columns` — no AVG over
  `cost_per_person_day_rupees` / `unskilled_wage_share_pct`; a wage question reads unskilled wages.
- **Answer text (c12):** `_c12_normalise_figures` inside `_group_result_digits` (so every data answer): money through
  `_c12_money`, a `_rupees` column never "lakh", counts ≥ 1 lakh in Indian grouping, duplicate bracketed amounts
  collapsed. `_finish_data_result` adds the Focus Plus tranche note to a per-beneficiary average.
- **PMAY-G:** `_pmay_period` — "of the houses sanctioned in FY …". **CM Elevate:** D-090.
- **Follow-ups:** `ConversationState.recent_districts` + `substitute_references` ("compare both districts");
  c15 `_c15_why_comparative` -> the reason reply, which quotes the last answer.
- **Edge / guardrails:** categories `privacy_records` (names / phones / addresses of people) and `schema` (tables,
  columns, pg_*, information_schema), both before any SQL. **Router:** Devanagari -> English (D-091); 422 never
  echoes input (`main._invalid_request`); lifespan `_warm_up`.

### 2.9f Data-answer rules shared by every scheme (2026-10-29, D-092, KI-594..KI-603; LIVE-VERIFIED in-process)
The user's data-accuracy brief (`megh_chatbot_fix_prompt.md`: ten questions D1-D10 with known answers, root causes
RC1-RC8). One new pipeline file, `app/pipeline/common/c17_data_answer_rules.py` (loaded last; called at run time by
the stages that own each step), plus targeted edits. No graph node changed.
- **RC1 multi-part questions.** `_c17_sub_asks` cuts a question at its ask joiners. PMAY-G: `_pmay_metrics` keeps
  "houses" beside "completed" when one ask counts the houses and another the completed ones
  (`_pmay_total_and_status_asked`) and adds `progress`: in progress = House Sanctioned + Plinth + Roof Cast, not
  started / no status = the rest (Proposed Site, Existing site, NULL) — they add up to the total (D5:
  1,29,941 + 41,041 + 125 = 1,71,107). A total + a "which … most" in one question (`_c17_ask_plan`) becomes two
  questions run one after another by the conversation layer (`conversation_layer.AskPlan` / `answer_asks`, through
  `answer_many`, so the router's existing multi path and timeout apply): the second is completed with the first
  answer's scheme / place / year (`_c17_ranking_question`); the Note lines are said once; a failed ask is said, never
  dropped.
- **RC2 routing.** `_data_scheme_stage`: ONE named dataset with its own sub-schemes (`DatasetFacts.sub_scheme_column`:
  CM Elevate, CM Elevate Legacy) never takes the cross-scheme money ranking — "which scheme" is its `scheme_name`
  (D10 had fanned out to five schemes).
- **RC3 SQL validation.** `_execute_one_attempt` raises `_c17_sql_issue` for repair: a string constant aliased as a
  finding (`'PMAY' AS scheme_with_most_records`; a label like `'Meghalaya' AS name` is fine), a table owned by a
  scheme the question is not about (`DatasetFacts.owned_tables`), a "which <dim> … most" with no ORDER BY / MAX.
  The c11 rewrite chain runs `_c17_sql_hygiene`: a LIMIT on a one-row aggregate is dropped (D9's `LIMIT 1000000`).
- **RC4 superlatives.** A singular "which <dim> … most / least" with no stated length reads LIMIT 3 whatever LIMIT the
  model or the catalogue wrote (`_c17_widen_top1`; c16 `_c16_shape` builds 3); `compose_response` then answers in code
  (`_c17_runners_up_answer`): "Highest <measure> (<scope>): A, v1. Next: B (v2), then C (v3).", a tie said. The 4B
  verifier is shown the query with LIMIT 1 (`_c17_as_asked`): with LIMIT 3 it rejected every repair.
- **RC5 caveats.** `_finish_data_result` -> `_c17_attach_caveats`: a Note line when the answer states ₹ from a
  provisional / unverified dataset, and when an unfiltered (all-years) answer spans a year the dataset does not hold
  (years from `_SCHEME_DATA_YEARS`, live). The facts come from `scheme_registry.DATASETS` (D-092), which the cards'
  "*" now reads too (`routers/stats._cards`).
- **RC6 money.** `_c12_money` writes the exact amount and its size: "₹37,49,31,500 (≈ ₹37.49 crore)", paise only
  when present, a lakh column "₹25,701.49 lakh (≈ ₹257.01 crore)" (closes KI-449). `_c12_normalise_figures` (every
  data answer, via `_group_result_digits`) knows a money column by suffix or, unsuffixed, by name with the dataset's
  unit (`_c17_money_cols`; MGNREGA lakh, the rest rupees, CM Elevate none); puts "₹46.64 crore" back to the exact
  cell it rounds from; gives a lakh figure its ₹ and crore size; absorbs an old size bracket; is idempotent.
  "This is the X figure for across all financial years" -> "… figure across all financial years".
- **RC7** was already in place (answer-with-defaults, NEW_CHAT_ASKS_SCOPE false): D7 answers all years unasked.
- **§3 hardening:** every scheme's districts take "E / W / N / S / SW / EW <name>" forms (`entity_resolver.
  _add_direction_aliases`) and `detect_region` no longer reads them as the hill range; a compare / ranking label that
  is a `year_key` reads "FY 2022-23" (`_c12s_label`).
- **Not changed:** the MGNREGA SME catalogue asks which FY a bare "2023" means (KI-600, needs a decision); RC8's
  parallel sub-asks (run in order, KI-603).

### 2.9g Misspelt and variant names (2026-10-29, D-093, KI-604..KI-610; LIVE-VERIFIED in-process)
Brief: `megh_chatbot_spelling_fix_prompt.md` (T1-T10). VERIFIED in code:
- **`app/spelling.py`** runs first in c14 `_turn_context_stage` (step a0 above). `normalise(q)` returns the text plus
  `Correction`s (typed, canonical, kind scheme / district / block / word, how alias / sound / fuzzy, score).
  - Schemes: phrases from `data/spelling_aliases.yaml` `schemes:`; each word of 4+ letters may be a near miss (ratio
    >= 80, same first letter); "+" counts as "plus". Rewritten only when `_SCHEME_NAME_MATCHER` does not already read it.
    A bare misspelt "focus" becomes "Focus" (the which-Focus rule still asks).
  - Districts / blocks: forms (canonical + aliases) from every scheme's resolver catalogue + the YAML `districts:`.
    Exact -> same `sound_key` -> Damerau-Levenshtein on the key (1 / 2 / 3 edits by length), same first letter, one
    clear winner; a direction written last ("khasi hills east") is read; spans never include a function word or a
    level word. A one-word near miss needs a cue ("in", "district"). A block is never written over a village name or
    a village the index spells closer, and no district / block / scheme-word / domain-word rewrite touches a span
    that BEGINS an exact multi-word village name (`_starts_a_village`, KI-631 2026-10-30: "RONGARE ADING" had become
    the block "Rongara ADING", "Pyndeng Shallang" the word "pending"), and the normaliser steps over the whole
    village span (`_village_span_end`: "hawai bhoi" had lost "bhoi" to the Ri Bhoi alias); a name that is a village WITH the word
    "village" ("Centre Village") is left alone too. Exactness = the folded index OR the full stored name
    (`_exact_village`; the index folds VILLAGE away and drops one-word generic names). What the resolver already
    reads as written is left alone (`_resolver_reads`).
  - Villages: written with their real name only after the word "village" and when one village sounds clearly
    closest (`_village_at`; live T9: the SQL model filtered a view without village_code when the text kept the
    typo). Otherwise `entity_resolver._sound_village_rows` (sound key + edits, in memory) runs before the trigram
    search: one clear name -> that village, a close race -> the pick-list, best first.
  - Words: `words:` (closed list), 1 edit up to 5 letters, never a known word, place or village, never another form
    of the same word ("loans", "employ").
- **`unresolved_place(q)`**: up to three unknown words after in / at / from (not vocabulary, not `_NOT_A_PLACE`
  such as "detail", "hindi", months), not a place in any catalogue / the village index, not out of area. Used by
  c14 `_same_scheme_context_year` (no place carried for it) and c13 (the `unknown-place` pause, closest names first
  via `suggestions()`); c09 raises the same pause for a made-up district / block mention (`_c09_out_of_area_name`
  keeps OutOfScope for Guwahati etc.).
- **Picker expiry**: topic_memory `_pick_reply` takes a chip or a reply of 5 words or fewer; a longer one is a new
  question. Scheme / option pauses already did (`_resume_scheme_pause` 6 words, `_resume_option_pause` 12).
- **"Showing results for **X** (you typed 'y')."** opens a corrected data / knowledge answer (c15 `_attach_preface`;
  scheme / district / block corrections only); the result carries `spelling`; the semantic cache skips such answers.
- **Scheme picker order**: `spelling.scheme_scores` puts a clear best guess first (>= 60 and 10 ahead), all six kept.
- **Speed**: the gazetteer and the suggestion pool are built at startup (`spelling.warm()`, app/main.py); a warm call
  of normalise + unresolved_place is 1-5 ms (p95 < 150 ms test). `entity_resolver.resolve_dimension` (~130 ms a call)
  is not used here.
- **Adding an alias / a scheme**: an alias goes in `data/spelling_aliases.yaml` (restart, or `spelling.reload()`); a
  district / block alias in the scheme's `*_entity_resolver.yaml` is picked up automatically. A new scheme needs its
  `schemes:` entry here plus the registries in docs/SCHEMES.md §Adding a scheme.
- **2026-10-30 (Focus + / CM Elevate Legacy sheet re-test, KI-648/650/652)**: a word in the few-shot term map
  (`annotations._FEWSHOT_SYNONYMS`, e.g. the stored "Tranch") is a known word, never a place; a sound / fuzzy
  multi-word reading never starts on an ordinary word ("across South West Garo Hills" is not "across South West" ->
  a district); a span followed by "constituency" is read against the constituency catalogue first and is never
  rewritten to a same-named block ("William Nagar constituency").

### 2.9h Focus + / CM Elevate Legacy sheet re-test fixes (2026-10-30, KI-648..KI-654; LIVE-VERIFIED in-process)
- **Rephrase check** (c02 `_rephrase_violation`): a how-many / number-of question rephrased as "how much" is a
  changed measure (rejected; the original goes on). KI-653.
- **Verifier false positive** (c11 `_verifier_wants_amount_for_count`): on a how-many question whose SQL COUNTs and
  sums nothing, a complaint asking for a money SUM is discarded ("how many people got Focus Plus money" = 419
  beneficiaries, not ₹52.4 lakh). KI-653.
- **Follow-up routing** (c01 `_typed_intent`): a typed "what is it / that …" with a scope (statewide, a place, a year)
  is not decisive for KNOWLEDGE; the rewrite is classified ("What is it for the whole state?" -> the statewide
  figure). KI-654.
- **Focus Plus block guard** (`schemes/focus_plus.py` `_focusplus_lgd_only_block`): an equality on a known raw block
  is compared in upper case on both sides (`block_name_raw` is stored title case); an `lgd_block` equality naming a
  raw block moves to `UPPER(block_name_raw)` (not when the SQL filters a village). KI-649.
- **Verifier false positive** (c11 `_verifier_complaint_is_cosmetic`): the "use the resolved value verbatim, without
  UPPER()" complaint is discarded when the resolved block is filtered (as for constituencies before). KI-649.
- **Breakdown list lines** (c12 `_c12s_e9_extras`): the other measures shown per line are the ones the question
  names first, then SQL order (max 3); `_shaped_fallback` gets the question too. KI-651.
- **CM Elevate (applications) Sericulture** (`schemes/cm_elevate.py` `_cme_sericulture_split_note`): a spinning /
  weaving question on the combined scheme is told no split exists there (SME rule
  `sericulture_spinning_weaving_split_assumed`). KI-656.
- Live runners: `tests/sheet_runs/fp_run.py`, `cl_run.py` (sheet + hierarchy) and NEW `tests/sheet_runs/fpcl_perm.py`
  (46 permutation / multi-turn scenarios, DB truth). See TESTING.md.

### 2.9h MGNREGA UAT round fixes (2026-10-30, KI-635..KI-639; LIVE-VERIFIED in-process)
Found by `tests/sheet_runs/mg_uat.py` / `mg_uat_villages.py` (the MGNREGA sheet on the answer-with-defaults rules,
every district / block / constituency / village). VERIFIED in code:
- **Identifier cells stay bare** (`_c12_bare_codes`, the last step of `_c12_normalise_figures`, c12): a comma-grouped
  number in the answer whose digits are a `*_code` / `*_id` / `year_key` cell of the result — and not also a figure
  cell — is written as stored ("village code: 278380", not "2,78,380"). Figures keep their grouping.
- **A ranking of places is a breakdown by that level** (`_c11_ranked_levels`, c11): `_RANKING_CUE` plus the noun
  district / block / village feeds `_verifier_total_vs_breakdown_is_false`, so the verifier's "should be a single
  total" complaint against `GROUP BY lgd_district` is discarded (it had sent "Which district had the highest
  expenditure?" to the KB fallback once in three runs).
- **J-10 twins, one row each** (D-089): `sql_ast.group_by_village` runs right after `widen_village_filter` in the c11
  rewrite chain — a one-SELECT aggregate over `village_code IN (…)` with no village grouping gets `village_code,
  lgd_village_name, lgd_block` in SELECT and GROUP BY (a CTE / join / window / already-grouped query is left alone).
  `_verifier_twins_complaint_is_false` (c11 `_verify_sql`) discards the verifier's "should map to one village" /
  "should be a single total" complaints when every twin code is filtered and the query groups by village.
  **Fixed queries run once per twin:** `_mgnrega_twin_det` (mgnrega.py, tried in c13 `_data_deterministic_stage`
  after the fixed-query chain, so the metric catalogue stays the chain's last entry) builds the single-area query
  for the first twin (job cards, combined facts, breakdown, wages vs materials, admin expenditure, then the metric
  catalogue) and returns a 4-tuple `mg_det`; `_data_deterministic_rows` runs it once per twin with the village-code
  parameter slot swapped and tags each row `village_code` / `twin_village`; `_mgnrega_twins_answer` (top of
  `_data_post_rows_stage`) writes one answer per village with the shape's own writer (a twin with no row is named);
  catalogue rows go to the composer tagged. **Model path:** `_pin_missing_twin_codes` (c10) adds or substitutes
  `village_code IN (<twins>)` when the SQL filters no village or names it by text, then `group_by_village`;
  `_c12_missing_twins_note` (`_finish_data_result`, MGNREGA only) names a twin absent from the rows.
- **Village-grain money stays in lakh** (`_mgnrega_village_money_in_lakh`, c11 rewrite chain): a MGNREGA query over
  a village or twin list that divides a money column by 100 into `…_crore` is rewritten to the bare lakh column
  (aliases and ORDER BY references renamed) unless the question itself says crore — 1.60 lakh had read "0.02 crore".
- **The rephraser may not bring in "scheme(s)"** (`_rephrase_violation`, c02): a rephrase that adds the word where the
  user wrote none ("…under the available schemes…") is rejected like one that widens to all schemes.
- **A `> 0` HAVING is not an unasked threshold** (`_unasked_having_threshold`, KI-641): the T13.3 rewrite drops a HAVING
  that compares an aggregate with a number the question never gave; a comparison with 0 keeps the places that had the
  thing at all and stays (it was looping against `_mgnrega_village_list_issue` on every no-year constituency list).
- **A "which villages" list is one row per village** (`_mgnrega_village_list_one_row_each`, KI-642): a one-SELECT list
  with no aggregate, GROUP BY or DISTINCT (Raksamgre: 124 rows for 116 villages) is grouped by its plain columns plus
  `village_code` / `lgd_block`; each `measure > 0` in the WHERE becomes `HAVING SUM(measure) > 0`, the measure is
  selected as its SUM and the list is ordered by it. `_mgnrega_village_list_issue` (`_mg_lists_raw_rows`) is the backstop.
- **No year asked, no invented year filter** (`_mgnrega_all_years_no_year_filter`, KI-643): with no year named or
  resolved, a `year_key` condition the model wrote on an MGNREGA query is dropped (women and job-card queries keep
  their own year rules) — "average person-days per household in Meghalaya" had silently left FY 2025-26 out.
- **A block / district near miss inside a longer exact village name is not a near miss** (`spelling._inside_village_name`,
  KI-640): "RONGARE" in "RONGARE ADING" sounded like the Rongara block and the village guard only knew the two-word name;
  a sound / fuzzy hit whose span is part of an exact village name in the text (up to three tokens either side) stands.

### 2.9i Accuracy gold bank fixes (2026-11-11/12, KI-701..KI-717; LIVE-VERIFIED in-process)

Found by the accuracy gold bank (`tests/accuracy/`, TESTING.md "Accuracy gold bank"): 212 cases from the three client
PDFs, the UAT sheet, the goldens, the voice bank, paraphrase families and follow-up chains; truth recomputed live with
independent read-only SQL; every run as `superadmin`. Pipeline fixes approved by the user on 12 Nov 2026 where the DATA
answer was wrong. Each is a deterministic rule (no regex, D-046/047); regression tests in
`tests/test_accuracy_gold_fixes_2026_11_11.py` (real functions, no model / DB).

- **Routing / intent**
  - `c13._c13_terse_figure` (KI-715): ≤ 7 words, a named scheme, a measure word and a place the resolver knows, no
    knowledge cue → DATA ("PMAY-G completed EKH").
  - `c14._c14_data_refinement` (KI-713, KI-701): right after a DATA answer, a refinement of ≤ 8 words with no knowledge
    cue / form / entitlement / who-benefits / scheme-term question stays DATA even when the rewrite reads "What is …".
  - `c14._KF_RECORD_COUNT` (KI-703): "how many <applications | houses | records | villages …>" anywhere in the question
    keeps it off the design-count knowledge form.
- **Follow-up rewrites (deterministic, before the model rewrite)**
  - `c14._c14_one_scheme_of_comparison` (KI-714, step "0h''-only"): "only PMAY-G" after a comparison of PMAY-G with
    other schemes = the previous question with the other schemes and the compare words taken out.
  - `c14._c14_carried_breakdown` (KI-712): a measure change ("and person-days?") that names no breakdown keeps the
    previous question's single breakdown (by financial year / district / block).
  - `c14._c14_only_filter_keeps_breakdown` (KI-701): a bare "only …" filter (no place, no year) keeps it too.
  - `c14._c14_other_scheme_there` (KI-722, step "0h''-there"): "and Focus Plus beneficiaries there?" after one
    place's answer (no year) = that scheme's question with "in <place>"; "are there" is never a place.
  - `c14._c14_topn_reply` (KI-716): a typed N / "all" answers the top-N pause like its chip.
- **Multi-part questions (`c17`)**
  - `_c17_sub_asks` never cuts the " plus " of "Focus Plus" (KI-704).
  - `_c17_village_count_plan` (KI-706): an MGNREGA village count beside another figure is its own ask, so it takes
    the fixed query `_mgnrega_villages_active_query` (6,491 villages with an employment OR expenditure record), not a
    model query over v_employment alone (6,419).
- **SQL / catalogue**
  - `c06._YEARS_LIST_FIGURE` (KI-705): "how much money was remitted … by financial year" is a figure per year, not the
    list of years.
  - `c16._metric_catalog_plan` (KI-709): a CM Elevate Legacy SANCTIONED count never takes a catalogue measure without
    `sanctioned_amount` (COUNT(sanctioned_amount) = 2,288, not COUNT(DISTINCT application_number) = 2,291).
  - `pmay_g._PMAY_M["completed"]` reads "are / is / got … done" (KI-710); `_pmay_is_placeholder_exclusion` treats
    `sanction_date / sanction_no IS NOT NULL` as the registrations exclusion D-060 drops (KI-711).
  - `cm_elevate._cm_elevate_scheme_count_column` (KI-703, called in `c11` with the other CM Elevate rewrites): a count
    column named for schemes / programmes that counts request_id counts scheme_name.
  - CM Elevate pending rule (KI-707): `data/cm_elevate/cmelevate_pending_rule.yaml` reads the plain `file_status`
    column the DB team exposed (scheme_specific stays locked); the gate `cme_pending_rule.readable()` opened by
    itself; `schema_context._cme_rule_9` says so (no "keys you may read: none").
  - `focus_plus._focusplus_block_breakdown_on_raw` (KI-718): a Focus Plus block BREAKDOWN grouped on lgd_block (NULL
    on 15% of rows) is grouped on `UPPER(block_name_raw)`, unless the query reads block_name_raw, a village column or
    filters lgd_block.
  - `cm_elevate_legacy._cm_legacy_unasked_lender_filter` (KI-721): a `loan_entity` filter is dropped unless the
    question names a lender ("and the loan?" counted Bank only: ₹2.45 crore of ₹4.84 crore).
  - CM Elevate REJECTED (KI-720): while the rule reads a plain readable `file_status`, `c01._c01_cme_rejection_held`
    lets a rejected question through the measure-not-held pause, `_cme_workflow_query` counts
    `file_status = 'Rejected' AS rejected` and `_cme_pending_answer` states it (valid-only by default). "Approved"
    is no stored state and keeps the pause ("doesn't record approval decisions").
  - `cm_elevate._cme_level_number` replaces the last regex in `app/` (KI-719; D-046/047), guarded by
    `test_no_regex_module_anywhere_in_app`.
  - `c11._verifier_programme_filter_is_false` (KI-717): a Check-2 complaint about scheme_name is discarded (CM Elevate
    / CM Elevate Legacy) when every resolved programme is filtered verbatim and no other programme literal is there.
- **Answer wording**
  - `cm_elevate._cme_valid_wording` (KI-702): a count kept to the default valid rows (D-B1-CME-01) is called "valid"
    ("7,375 valid CM Elevate applications"), never "total".
  - `c13._c13_undrawn_chart_note` (KI-708): a chart kind the chat cannot draw (radar, area, scatter, heatmap …) is not
    claimed; a note says it is not available and a standard chart is drawn.
### 2.9f Chat UI audit changes (2026-10-29, D-088 / D-089, KI-574; offline-verified)
- **Cross-scheme reading (`app/cross_figures.py`):** `rank_ask` reads a place level (singular, plural or one letter
  off) beside any rank word (top / bottom / highest / lowest / best / worst / least / poorest / weakest, Hinglish
  "sabse jyada / kam"), "which district", "rank districts by", "districts ranked by". A district level + a rank word is
  `op="rank_districts"`, never a scheme leader; village / block / constituency rankings go to the per-scheme model path.
  One ranked list per scheme unless "combined / together / in total"; villages and money per head are never combined.
  Both ends, second place, "excluding <place>", condition + top N (by the gap), per-head ranking. Rows: the ranked
  districts only, with `rank`. New modes: `by_year` (a stated span or list of years: one fixed query per scheme
  grouped by year_key) and `overlap` (union / both / only-one of village codes; "which villages have both" lists them,
  checked as village-level data by RBAC). B-7: person days / job cards / applications go to the model path.
- **Per-year follow-ups (`conversation_layer.per_year_parts` / `answer_many`):** a question with a place, a level, N
  or a rank keeps its own words per scheme; otherwise the canonical sub-question, with the asked years. Each scheme is
  asked only the measures it holds (a note says which it does not record); no measure -> a "which figure?" pause.
  The merge gives one row shape: `financial_year` "2023-24", place columns by level, the column that matches the
  measure (codes skipped), money in ₹ crore (`money_crore`), `value` + `measure` when schemes measure different things.
- **Years (c06 `_relative_years`, c09):** "last N years", "this / last / current year", "latest year" read against the
  years the schemes hold (the label says which, and "FY 2026-27 has no data yet"). "2022-23 - 2024-25" is a span. Two
  or more named years on the cross-scheme path are always `year_key_list`. Focus's money / member words count as a
  measure for the year gate, so every scheme asks alike.
- **Rows to the UI:** `_attach_chart_hint` first runs `_c13_unify_scheme_rows` on multi-scheme rows (one
  financial_year, one place column per level, one value column). `_chart_hint` never stacks across schemes, across
  years for distinct counts / stocks, a rate, or a ranking; `year_key` + `financial_year` are one period;
  `measure_kinds.is_label_col` decides label columns. Every descending ORDER BY gets NULLS LAST (`sql_ast.nulls_last_on_desc`,
  last step of `_scheme_sql_rewrites`).
- **Chart requests (D-095, 2026-10-30):** a type the officer names is drawn, alone, whatever the rows (a caveat when
  the figures do not add up or a line joins places); a comparison is charted by default; a single figure asked as a
  chart is drawn as asked. One pure function decides what is drawn, `viewPlan()` in `frontend/src/chat/analytics.js`.
  A message of ONE type word and filler ("I want only bar", "now line") re-runs the previous data question with that
  view (c15 `_chart_view_request`, `bare`; the UI's `viewOnlyRequest` redraws locally the same way).

## 3. Other flows

### 3.1 Flow D — no data
- **Valid SQL, 0 rows** → `_no_data_answer(schemes, entities)`: one deterministic line that
  names the scope.
- **An aggregate over nothing** returns one row of NULLs, not zero rows. It is handled by the
  `_all_null` branch in `compose_response`.
- **A genuine zero** vs **not tracked:** handled by `_genuine_zero_notes` and the composer
  guidance. The user can still find the two hard to tell apart (TECHNICAL_BRIEF §4.2 F; current
  status UNKNOWN — NEEDS VERIFICATION).

### 3.2 Flow E — out of domain
Checked, in order:
1. `edge.detect_harmful` (a harmful-request refusal, first);
2. `edge.detect_edge_case`: hard off-topic (weather, markets, sport), greeting, identity,
   thanks, goodbye, profanity, confused, and a **domain whitelist** (no scheme vocabulary →
   `off_topic`);
3. unsupported named schemes (`_unsupported_scheme_named`, e.g. PM-KISAN) → a clarification that
   lists what is held;
4. out-of-Meghalaya places → `OutOfScope` → the standard "I'm Megh One AI" reply.

Edge replies carry `suggestions` (the `edge.STARTERS` chips). No model call is made.

### 3.3 Flow F — streaming (D-039, 2026-10-07)
`POST /api/query/stream` runs the same turn as `/api/query` and streams Server-Sent Events:
- `step`: a graph node started (`pipeline_graph._observed`); the UI maps nodes to labels
  ("Understanding your question → Finding the district… → Querying the database → Writing the
  answer");
- `draft_reset`, `token`: `llm.call_response_composer` streams from the gateway (`stream_model`)
  **only** when a live client is bound (`turn_events.streaming()`); otherwise it makes the plain call;
- `done` (the full result) or `error`.

**The streamed text is a draft.** `compose_response`, `rag.answer_from_kb` and every guard receive
the full text exactly as before and run unchanged; the strict retry streams again after a
`draft_reset`; the UI replaces the draft with `done`'s answer. A stream failure before completion
falls back to the plain call (`draft_reset` first); `ModelBusyError` is never swallowed.
`STREAM_COMPOSER_ENABLED=false` keeps the steps and turns the draft off.

### 3.3a Flow G — live voice (D-103, 2026-11-02)
The voice is outside the pipeline. Gemini Live (`gemini-3.8-live`, through `app/voice/relay.py`) hears the officer and
speaks; its one function, `ask_megh`, is answered by the chat page through `sendQuery` -> `POST /api/query/stream`, so a
spoken question is a typed question: every stage, gate, pause and check above runs unchanged. The page turns the checked
answer into its spoken form (`frontend/src/chat/voiceSpeech.js`) and the voice reads it. Numbers the voice says are
checked against that text (`app/voice/speech_guard.py`); a number from its own memory, or a wrong number, makes the page
run / re-read the pipeline's answer. No new model role inside the pipeline; the voice's model is set in
`certs/voice.env` (`VOICE_LIVE_MODEL`), not in `app/config.py`.
One spoken question is one pipeline question (D-105): the relay answers the model's reworded re-calls within a turn
from its first call and holds a call it makes on its own after the answer was read. The Secretary view draws the
answer's own rows (`frontend/src/chat/voice/vizPlan.js`); its desk figures come from `GET /api/voice/board`, fixed
read-only SQL beside the pipeline (like `/api/scheme-stats`), never through it.

### 3.4 Exception handling around DATA (in `_run_pipeline`)

| Exception | Result |
|---|---|
| `ClarificationNeeded` | re-raised → the router returns `route:"clarification"` |
| `OutOfScope` | `_out_of_scope_result` (an `edge` route) |
| `ModelBusyError`, `asyncio.TimeoutError`, `httpx.TimeoutException`, `httpx.TransportError`, HTTP ≥500 | re-raised → router 503/504/502 |
| a megh_db connection failure anywhere on the DATA path (`db.is_connection_error`: OSError / socket, asyncpg connection errors; not `TimeoutError`) | `DatabaseUnavailableError` → router **503** "Couldn't reach the Megh One data service… retry". `execute_with_repair` raises it before any repair; never the KB fallback (KI-025, 2026-09-28) |
| anything else (incl. a spent repair budget, `UnsafeSQLError`, DB connection errors, programming errors) | `_data_path_kb_fallback`: tries RAG once, else "couldn't build a working query" (`route:"data"`, `confidence:"low"`, empty `schemes`) |

The broad catch also hides programming bugs as "couldn't answer" (KI-009).

This except-chain is `_data_path_error_result` (2026-10-02). The LangGraph DATA nodes map errors
through the same function.

---

## 4. KNOWLEDGE path (RAG) (VERIFIED)

1. **Scope selection in `_run_pipeline`** picks `_kb_scheme`:
   1. exactly one scheme named;
   2. else exactly one scheme inferred from vocabulary (`_infer_scheme_from_terms`; B2 2026-10-29 added "mandays",
      "unskilled labour/workers" -> MGNREGA, "LAMP(S)" -> Focus Legacy, "level <n>" -> CM Elevate, "loan(s)" -> CM Elevate
      Legacy — each checked in information_schema to be held by that scheme alone; KI-481);
   3. else the previous turn's single scheme (not for a bare "Focus").
2. **Refusals and asks:**
   - a named unknown scheme → `_knowledge_not_covered_answer`;
   - a bare "Focus" → the which-Focus ask;
   - no scope at all → the which-scheme ask;
   - two or more schemes named → `rag.answer_from_kb_multi` (per-scheme retrieval).
3. **`rag.retrieve(question, scheme)`:**
   1. embed with `qwen3-embedding` via the gateway (1024-dim; collection `megh_knowledge` on
      `10.48.242.4:6333`, read-only, D-074 — it was `megh_scheme_kb_v4`, D-067). With
      `QDRANT_KB_READ_ONLY=true` startup never rebuilds it; megh_knowledge has no BM25 vector, so
      `.env` sets `RAG_HYBRID_ENABLED=false` (meaning-only search). Conversation memory is off (D-074);
   2. `vectorstore.search` with a payload filter on `scheme` (`MatchAny`: megh_knowledge stores a list;
      "CM Elevate" also matches its "CM Elevate Legacy" pieces), taking `RAG_TOP_K=12`;
   3. **re-rank** (`rag._rerank`, D-083, 2026-10-29; always, there is no off switch): `qwen3-reranker` on the
      gateway scores the 12 in the Qwen3 yes/no format; its order is fused with the vector order by rank (RRF,
      k=60). `score` stays the cosine similarity (the deployed re-ranker scores ~0.99 for nearly everything,
      KI-450); its score is kept as `rerank_score`. A gateway failure keeps the vector order for that question and
      logs `rag.rerank: qwen3-reranker failed`; there is no fallback scorer. Measured on 137 eval questions:
      right piece first 60.2% -> 62.4%, in the top 3 82.7% -> 88.0%;
   4. keep the top 8 (`RAG_RERANK_TOP_N`) scoring ≥ `RAG_MIN_SCORE=0.30`. The floor
      is real (2026-10-16): if **none** clear it, nothing is returned and the answer is "not covered".
4. **`rag.answer_from_kb`** answers by the top score:
   - ≥ `RAG_HIGH_CONFIDENCE=0.84` → the top chunk verbatim;
   - ≥ `RAG_MEDIUM_CONFIDENCE` (`.env` 0.35 on the qwen3 scale since D-067; 0.55 was the bge-small value)
     → the **9B** composes from the kept chunks. The scoped prompt
     includes `_naming_note`, which says for example that the docs call Focus Legacy "FOCUS".
     - A stray "that isn't covered" sentence is stripped from the answer.
     - An *outright* refusal gets **one retry** with the same prompt. A second refusal → None.
     - The code comment there says the composer "runs at non-zero temperature", but
       `RESPONSE_TEMPERATURE=0.0`. That is a stale code comment, not changed here.
   - otherwise → None → a "not covered" reply.

   Focus Legacy overview questions retrieve with a rewritten `retrieval_query`.
5. **CM Elevate Legacy** has no docs of its own. `kb_scheme()` maps it to CM Elevate
   (`_KB_SCHEME_ALIAS`).
6. **KB ingest** (`kb_ingest.ingest_kb`, a background task at startup):
   - takes every readable file in `data/incoming/<scheme>/` (`_INCOMING_SCHEMES`; the folder
     decides the scheme tag) plus `data/web/*.md` tagged `<!-- scheme: X -->`;
   - chunks them by heading;
   - rebuilds the collection when it is missing, has too few points, lacks any scheme, lacks the
     BM25 vector, or has another vector size than the embedding model (KI-402).
   - **The collection is shared.** After editing the KB, call admin `POST /api/rag/reingest` or
     restart.

7. **Knowledge fix 2026-10-29 (D-094, KI-611..618; LIVE-VERIFIED: golden 114/114 twice, RAG eval 98.4%).**
   - **Routing by form** (c14 `_knowledge_form_question`, `_KF_FORMS`): after `classify_intent`, a DATA verdict
     becomes KNOWLEDGE for a rate / registration-details / process / distance / guaranteed-days / funding-pattern
     / design-count / launch-admin / loan-or-grant question with no place, year, grouping, ranking, comparison or
     figure word (`_KF_FIGURE_VETO`); logged `intent override=knowledge_form form=…`. Also: the classifier prompt has
     form few-shots; `_hybrid_split` accepts a knowledge-form left half ("What does Focus Plus pay and how many got
     it in FY 2022-23?" = rules from the KB + figures); c06 `_is_years_list_question` skips launch words;
     `_overrules_scope_verdict` passes a knowledge-form question that names a scheme. Checked against 1,265 bank
     questions (1 flip, an "unanswerable by data" one) and the 74 held-out questions (0 flips).
   - **Bare "Focus":** vocabulary no longer settles it; "what does FOCUS stand for" reads Focus Legacy
     (`_FOCUS_ACRONYM_ASK`); anything else asks.
   - **`retrieve`** also searches: each part of a multi-part question (`_sub_asks`), facet queries (`_RAG_FACETS`:
     launch, amount, subsidy/sub-schemes, documents, eligibility, apply; MGNREGA apply adds the job card), and
     the English wording of romanised Hindi (`_looks_hinglish` -> `translate.to_english(q, "hi")`, also shown to
     the composer). Searches run in parallel, at most 6 at once per worker (`_bounded_search`), each with two Qdrant retries. Top-n +4 for a multi-part question. An FAQ piece whose heading asks
     the same question (`_faq_match`: ≥75% of the question's content stems, ≥40% of the heading's, or one short
     acronym) goes first, labelled OFFICIAL FAQ ANSWER in the prompt.
   - **Composer rules** (`_completeness_rule`): answer every part, opening with what the passages say; per-facet
     related facts; national vs Meghalaya rules apart; `scheme_registry.KNOWLEDGE_DISTINCTIONS` in
     `_naming_note` and in the multi-scheme sections.
   - **Deterministic backstops:** `ground_answer` (word/number support rescue; a number in neither the passages
     nor the question — digits or spelt out — is dropped; never empties the answer; no sentence split after an
     initial); after composing `_with_faq_facts`, `_with_related_ministry`, `_with_subscheme_count`.
   - **Citations:** `_supporting_chunks` (pieces the sentences lean on). **Next steps:** the last chip after a
     knowledge answer is `followups._KNOWLEDGE_DATA_NEXT[scheme]` (each routes DATA, tested live).
   - Tests: `tests/test_knowledge_routing_2026_10_29.py` (offline), `tests/live_chat_knowledge.py` (live, VPN).

---

## 5. Conversation context (VERIFIED)

| Mechanism | Where | Model? |
|---|---|---|
| Follow-up detection | `looks_like_followup`: ≤12 words; lead words, pronouns, scheme-swap fragments; name lookups stay standalone | – |
| Follow-up rewrite | `rewrite_followup(question, prev, extra_context)`; prompt from `_build_rewrite_prompt`; output checked by `_rewrite_provenance_violation` | 4B |
| Previous-turn evidence | `context_manager.build_rewrite_evidence`: the tiers below, replacing the old `prev.answer[:300]` slice | – |
| Extra context | `context_manager.build_followup_context`: state block, summary, Qdrant memory (≤1,200 approximate tokens) | embed |
| Structured state | `ConversationState`: schemes, entities, years, comparison districts. `update_state` runs after every answer but commits only a **successful** DATA turn. Persisted as `app.conversations.context_state` | – |
| Prior entities | `merged_prior_resolved` seeds `resolve_entities` for follow-ups; tranche / sub-scheme are only taken for their own scheme | – |
| Summary | `maybe_update_summary` every 4 turns | 4B |

### 5.0 Standalone or follow-up — decided before any rewrite (D-061, 2026-10-22; VERIFIED offline)

Every in-scope message that reaches the follow-up stage with a previous answer is classified by
`context_policy.turn_kind(raw_question)` (deterministic, no model, never reads the chat):

| Kind | Test | What it may take from memory |
|---|---|---|
| FOLLOWUP | reference cue (it/its/there/same/this/that as pointers/instead/above/previous, "compare this", "what about", leading "and"/"also", Hinglish dobara/wahi/uska/pehle) or a fragment with no measure | only what it leaves out (merge plan, rewrite, `prior_resolved`) |
| STANDALONE | own measure AND own scheme (named; or pinned by the measure when it also names its own year or place), no cue | nothing: statewide unless it names a place; its year, else the year chips (c13; D-065 — was the scheme's latest FY); banner "(new question)"; never rewritten. **Exception (D-075, KI-406):** when it only repeats the chat's measure (`detect_metric` = `state.metric`) on the chat's scheme, it keeps the chat's year (never the place) |
| VAGUE | a measure with no scheme named | one open topic: that topic's scope; 2+ single-scheme topics: chips (`_vague_topic_clarification`, rule `topic-ambiguous`) |

Slot-conflict guard: `context_policy.asked_levels` ("which X", "top N X", "by/each/per X", "X-wise") — that level
and below are never inherited as the filter, the parent is (`_c14_kept_place_fields`, and the merge plan's
`_RANK_OVER_GEO_MATCH` / `_ALL_GEO_MATCH` for follow-ups). Logged as `turn_kind` in the decision log. Reset,
small talk, out-of-scope and "go back to …" are decided earlier (conversation_layer, edge, topic_memory).

**Pause replies (D-065, 2026-10-22):** the kind is decided once, on the question the user typed. A pause stores it
(`Session.pending_turn_kind`, snapshot `pending.turn_kind`); a reply that resumes the pause (scope merge, typed pick,
or a tapped chip of any length) runs as that kind (`turn_context["resumed_turn_kind"]`), never re-classified from the
chip text, which names the scheme and the level and so reads as standalone. "…for mairang?" (vague) through the place
and whole-or-part chips keeps the chat's all years.

### 5.1 What the follow-up rewrite sees (VERIFIED, 2026-09-26)

Every model call is one stateless user message, so the rewrite is the only place earlier turns
reach a model. The SQL generator, verifier and composer see only its output, plus the
`prior_resolved` entities.

The prompt, in order:
1. The instructions. Entities may come only from the follow-up, the previous question, the
   previous filters or the Known context. A name from the previous result may be used only for
   the item the follow-up points at.
2. `extra_context`: the `Known context:` state line, the summary, and older turns from memory.
3. `PREVIOUS question: "…"`, the previous standalone question.
4. **Tier 1 — `PREVIOUS filters:`**, always. The previous turn's schemes and resolved entities,
   e.g. `scheme=Focus Plus; district=WEST GARO HILLS; year=FY 2024-25`. `village_code` is left
   out: its name is already in the previous question, and `prior_resolved` carries the code.
5. **Tier 2 — `PREVIOUS result:`**, only when `references_previous_result` matches ("the top
   one", "that block", "the second one", "each of them"). It is
   `Turn.result_summary`, a deterministic summary of the result **rows** in result order, built
   by `summarize_result` in the router (`CONTEXT_PREV_RESULT_MAX_TOKENS`, 120).
6. **Tier 3 — `PREVIOUS answer (excerpt):`**, only when the follow-up points into the result and
   there were no rows (a knowledge answer). Whole sentences within
   `CONTEXT_PREV_ANSWER_MAX_TOKENS` (120), never a mid-word cut.
7. `FOLLOW-UP: "…"`, then `Standalone question:`.

**Why the slice went:**
- Measured with the real prompt code: every follow-up carried answer text.
- A long answer's first 300 characters carried four block names (Dalu, Rongram, Tura,
  Phulbari) into "How many beneficiaries were there?", and the prompt allowed the model to use
  them.
- Anything past character 300 was invisible, even when the follow-up pointed at it.

**Provenance check:** `_rewrite_provenance_violation` runs on the model's output. It rejects a
rewrite that names a scheme, a district or a block that none of the permitted sources contains.
- The permitted sources are items 3–6, plus the follow-up and the state line.
- The summary and older turns count only when the follow-up reaches back ("earlier",
  "we discussed").
- Names are compared canonically with `entity_resolver.named_places`, so "ekh" permits "East
  Khasi Hills".
- Years are not checked, because the year change is usually the follow-up's own. Villages are
  not checked, because they are not catalogued offline.
- A cross-scheme follow-up ("all schemes") skips the scheme check.
- On a violation the original fragment goes on, and `inject_scheme_hint` plus `prior_resolved`
  still carry the scheme and filters. No extra model call is made.

**Failed turns:** a DATA result with no `sql`, no `schemes` and no `resolved_entities` is the
"couldn't build a working query" fallback. `update_state` does not commit it, so metric,
comparison, scheme and geography keep their last good values.

### 5.2 Scheme-pause resume (VERIFIED, 2026-09-26)

`scheme-not-specified` and `focus-scheme-ambiguous` (`SCHEME_PAUSE_RULES`) are now remembered
by the router. It stores `pending_scope_q`, plus `pending_scope_rule` and
`pending_scope_options`.

On the next turn, step 0a' runs `_resume_scheme_pause`:
- A reply that is just one offered scheme's name, e.g. "Focus Plus", "focus plus please", or
  "legacy" for the which-Focus pause, becomes **that chip's exact question**. It then gets the
  same `_pin_cm_elevate_dataset` pass, and `scope_resumed` stays False, as it does on the chip
  path.
- Any other reply goes through untouched, as before.

Previously a typed "Focus Plus" was answered as a new question and the paused ask was lost.

**2026-09-29 (KI-181): every chip pause resumes from a typed reply. VERIFIED live.**
- Three pause families now. `SCOPE_MERGE_RULES` (scope / year / entity / ranking count): the
  free-text reply is merged into the paused question, unchanged. `SCHEME_PAUSE_RULES`: as above.
  **Any other rule that offers options** (`swap-measure-unavailable`, `year-out-of-range`,
  `tranche-not-specified`, `region-needs-district`, `ac-narrow-scope`,
  `sericulture-spelling-ambiguous`, `cm-scheme-group-ambiguous`, `amount-not-held`,
  `village-or-outside-place`, `no-time-dimension`, `scheme-comparison-not-specified`, …): the
  router (`remember_pause`, generic branch) stores the question and the options.
- Step 0a'' runs `_resume_option_pause(reply, options)`: the chip's own question; an ordinal
  ("the second one", "2", "last"); "yes" when there is one option; otherwise the ONE option whose
  label words the reply names (strong: label ⊆ reply ⊆ label + chip question), or whose label /
  chip question holds all of the reply's words (weak). Tokens drop scheme names, filler, ₹ and
  thousands commas, and fold plurals. Two candidates at a level = no pick (never a guess). A reply
  naming a scheme picks only an option about that scheme.
- No pick: `_paused_thread_antecedent` — when the paused question names one scheme that the last
  answered turn was not about, and the reply names no scheme and its own vocabulary picks no other
  (`_infer_scheme_from_terms`), the paused question becomes `prev` and the thread state becomes
  that scheme with the carried place/year. Otherwise the reply goes on untouched.
- The measure-gap pause is remembered as its first offer (`turn_context["standalone_question"]`),
  a real question in the new scheme with the carried scope.
- Pauses with no options (`reference-ambiguous`, `column-not-held`) are not remembered.

**2026-09-27 (Focus Plus QA, FOCUS-029):**
- **Bank pause chips.** The "which bank?" pause (`_bank_clarification`) for a question naming
  no scheme had **no options**. It now offers "Focus Plus (bank name)" / "Focus Legacy (bank
  name)" under rule `bank-scheme-not-specified`, which is in `SCHEME_PAUSE_RULES`, so a typed
  scheme name resumes it too. A Focus Legacy bank question used to raise `KeyError` (no
  `_BANK_NOT_HELD_TEXT` entry). Now bank name / IFSC go to SQL, and only account-number /
  transfer / DBT questions are refused.
- **A resumed reply that pauses again.** `session.turn_context["resumed_question"]` holds the
  full question a reply resumed into, whether from a typed scheme name, a merged area/year reply
  or a chip. The router remembers it via `routers.query.pause_question(session, req.question)`
  instead of the bare reply. Before this, a typed "Focus Plus" → area pause was remembered as
  "Focus Plus", and the typed "All of Meghalaya" then ran as "Focus Plus, All of Meghalaya", a
  KB scheme overview. The same loss hit any typed area reply followed by a year pause. Chip
  clicks were unaffected, because a chip sends the whole question.
- **Batch / tranche is a scope.** `_needs_scope_clarification` no longer asks "which area?"
  when a Focus Plus tranche resolved or the question names the 12.5K / 93K batch. This follows
  the SME default `missing_geography → all_districts`.

**Scheme switch while an area / year pause waits (KI-405, 2026-10-27; LIVE-VERIFIED).** In the scope-pause
branch of `_turn_context_stage` (c14), before the merge: a reply that is a PURE switch to another scheme
(`_c14_pause_scheme_switch` -> `_scheme_substitution`: "What about MGNREGA?", "same for Focus Plus"; rules
`scope-not-specified` / `year-not-specified` only; not a bare "Focus") becomes the paused question asked for that scheme
(`_swap_scheme_in_question`), remembered as `resumed_question`. `scope_resumed` stays False, so the new scheme is asked
its own area / year. Before, it was merged ("How many PMAY-G beneficiaries are there, What about MGNREGA?") and answered
as a two-scheme figure. Any other reply (a place, a year, the same scheme, a switch that also adds a year) is unchanged.

### 5.3 Prompt budgets and observability (VERIFIED offline, 2026-09-26)

`app/context_budget.py` logs one `prompt_context` JSON line per model prompt:
- kind (`sql`, `sql_repair`, `sql_verify`, `rewrite`, `compose`);
- approximate tokens per named section;
- total, budget, `over_budget` and, if any, the `compressed` sections;
- `request_id`, set per request by `middleware/security_headers.py`;
- for `rewrite`, the tiers used, the follow-up kind and the guard verdict.

`llm.call_model` also logs one `llm_call` line per model call: role, model, queue ms, latency ms,
and the gateway's own `prompt_tokens` / `completion_tokens`. No prompt text is logged.

**Budgets** are `PROMPT_BUDGET_*` in config: SQL 15,360, classifier 7,992, and composer 0 (unchecked,
because qwen35-9b's max-model-len is not recorded).

The SQL prompt is **priority-aware** (`context_budget.assemble_prioritized`). **Required**
sections are never shortened:
- schema backbone, live schema, prohibited joins;
- common mistakes (business rules);
- resolved entities, scheme scope, question.

Only when over budget, the **optional** sections are compressed, in this order (B4, 2026-10-27):
1. the catalogue: first its lines the schema already states verbatim (`_dedupe_catalog`), then the
   SHARED tables' column notes (dim_*, v_cross_scheme_*, v_district_year_summary, v_place_names …) the
   question's words do not touch (`schema_introspect.catalog_block(focus=…)`). Every scheme-specific
   column note, table note, business term and metric definition stays;
2. the megh_sql_metadata view / join notes (views first, then joins);
3. last, the few-shot examples, from 5 to 3 to 1.

Nothing is removed to satisfy a count. If the required part alone is over, the prompt goes out
over budget and is logged as such. Under budget, the output is byte-identical to before.

Other prompts warn only.

**Measured LIVE 2026-10-27 (KI-442):** with the catalogue (~8.2k–9.4k per scheme, ~6k of it column
notes) the SQL prompt was 15.9k–17.1k tokens, over the 15,360 budget on every question, and the old
order cut the examples to ONE and dropped the view / join notes. After B4: 12.7k–14.2k, the 5 examples
kept (PMAY-G keeps the view / join notes too). The 2026-09-26 offline figure (3.0k–6.9k) excluded the
LIVE SCHEMA and catalogue blocks.

The earlier "2.5k–5.6k" figure was measured without the few-shot banks loaded, and was wrong.

### 5.4 Field-level merge, follow-up kinds and provenance (VERIFIED offline, 2026-09-26)

`app/context_policy.py` is deterministic: no model call and no DB round trip. It runs in about
0.6 ms per follow-up.

**`plan_state_merge(question, state, prev)`** gives every field one action:

| Action | When |
|---|---|
| **KEEP** | The question says nothing about the field. |
| **REPLACE** | The question names a new value. For geography, this clears the finer levels under it. |
| **CLEAR** | The question says "all / by / every X" or "all years". |
| **REQUIRE_CLARIFICATION** | An unpinnable reference. "the other one" / "former" / "latter" goes to the existing `entity-ambiguous` pause via `substitute_references`. A relative year with no known year is left to the existing year pause. |

**Scope-less measure follow-ups** (`is_scopeless_followup`, live finding 2026-09-26): a short
question (≤8 words) right after a DATA answer is treated as a follow-up when it asks only for a
measure and names no scheme, place or year. Examples: "How many beneficiaries were there?",
"What was the total?". `looks_like_followup` treats "how many" / "total" as standalone
anchors, so such questions used to lose the previous scope. The router's `is_cacheable` uses the
same predicate.

**Removed filters reach the rewrite** (live finding): for every field the plan CLEARs, the
prompt gets a line `REMOVED by the follow-up (do NOT include these): district=…`. The check
rejects a rewrite that re-adds the value (`cleared:<field>`). Live, "show it by district" had
been rewritten "…by district in West Garo Hills", which the check allowed because the previous
question names that district.

**`apply_merge_plan`** removes, from `resolve_entities`' `prior_resolved` fallback, every field
that is REPLACEd, CLEARed or not pinned. It never adds a value. It fixes two live-risk cases:
- "show it by district" after a West Garo Hills turn used to inherit the district filter;
- "what about South Garo Hills?" after a Dalu turn used to keep `block=DALU` under the new
  district.

**Follow-up kind → context layers:**

| Kind | Layers the rewrite gets |
|---|---|
| `NEW_QUERY` | none |
| `RESULT_REFERENCE` ("the top one", "that block", "how much was it?") | previous filters + result rows (or an answer excerpt when there are no rows) |
| `METRIC_CHANGE`, `TIME_CHANGE`, `GEOGRAPHY_CHANGE`, `GROUP_BY_CHANGE`, `COMPARISON`, `FILTER_CHANGE`, `CLARIFICATION_RESPONSE` | previous filters only |

The summary and older turns are added, for any kind, only on an explicit back-reference.

**Per-field policy** (`FIELD_POLICIES`, keyed by field and never by scheme):

| Field | Inherit? | User can replace? | User can clear? | Clarifies when | Validated against |
|---|---|---|---|---|---|
| scheme | yes | yes | no | nothing named and no vocabulary; a bare "Focus" | scheme registry |
| district | yes | yes | yes ("all districts", "statewide", "by district") | a hill-range name | resolver catalogue |
| block | yes (while the district is unchanged) | yes | yes | name collides with a village or AC | all catalogues' block lists |
| village | yes (while the block and district are unchanged) | yes | yes | several villages share the name | DB (`resolve_village`); not offline |
| year / financial_year | yes | **always** | yes ("all years", "by year", "cumulative") | relative year with no known year; scheme needs a year | `_SCHEME_DATA_YEARS`, year-gap handling |
| category (tranche, sub-scheme, demographics) | yes | yes | yes ("all tranches", "everyone") | sub-scheme family name; tranche not stated | catalogue + closed vocabulary |
| metric | yes | yes | no | never (unknown → "not tracked") | metric vocabulary |
| group_by | no | yes | yes | never | dimension vocabulary |

**Provenance** is recorded in `ConversationState.provenance` by `update_state`, with the facts
from `session.turn_context`. Each field gets a `{value, source, confidence, turn}` record.
- The sources are `current_user`, `previous_user`, `clarification_response`,
  `resolved_reference`, `validated_database` and `model_inference` (confidence 1.0, 1.0, 1.0,
  0.9, 0.9 and 0.5).
- `merged_prior_resolved` does not inherit a `model_inference` value.
- Provenance is persisted with the state.

**Field-specific rewrite checks** (`context_policy.rewrite_violation`, behind
`_rewrite_provenance_violation`), KI-029:
- **scheme, district, block:** must appear, canonically, in a permitted source.
- **year:** any year a permitted source names, or ±1 of one with a relative-year cue. An
  explicit year change by the user always passes.
- **metric:** compared by family (money / count / days / completion), so a paraphrase passes
  and a new measure does not.
- **category:** closed vocabulary. Demographics, tranche numbers, and every CM Elevate
  sub-scheme name and alias.
- **name:** a capitalised word found in text the rewrite was *not* allowed to use (the previous
  answer, or the summary and older turns without a back-reference) and in no permitted source.
  This is how villages are covered offline.

### 5.5 Shared conversation state across workers (VERIFIED offline, 2026-09-26; KI-028)

`app/session_sync.py` makes `app.conversations.context_state`, in Postgres, the source of truth.
- `sync_in` runs at the start of every request. It applies the durable snapshot when its `rev`
  is newer than the worker's own copy.
- `sync_out` runs, **awaited**, after every answered turn and every clarification pause.
  `conversation_store.save_session_state` is an upsert with a revision guard: a concurrent stale
  write is refused, so last writer does not win.
- The snapshot is `Session.to_snapshot`: the state and provenance, the last turn (question,
  route, schemes, entities, answer ≤2,000 chars, `result_summary`), the pending clarification
  including its options, and the recent questions.
- Each call is bounded by `CONTEXT_STATE_SYNC_TIMEOUT_SECONDS` (1.0) and never raises. With the
  DB down, the request runs on the worker's local copy, as before.
- `maybe_update_summary` no longer writes on its own, because a fire-and-forget write could land
  after the versioned one.
- Redis was not used: in this codebase it is an optional, best-effort cache that is unset in dev.
- Cost, measured live on 2026-09-26: `sync_in` p50 52 ms / p95 359 ms, and `sync_out` p50 50
  ms / p95 153 ms. That is about 100 ms added to a p50 turn of ~2.3 s. Across the live suite
  the state crossed workers on every turn.


### 5.7 Continuation gate and the semantic contract (VERIFIED offline, 2026-09-29; D-030)

**Why:** after a Focus Plus answer, "who is harshit" and "he is my collik remember" were rewritten
"…under Focus Plus" (RAG / DATA), and "now give me five thousand loan for me i am in crisis"
became a Focus Plus DATA pause. Two steps inherited the scheme for any short message: the edge
whitelist was skipped whenever a previous answer existed, and `looks_like_followup` reads any
≤6-word anchorless message as a fragment.

**Gate:** `context_policy.continuation_signals(q)` → signal names: `domain` (edge vocabulary),
`scheme`, `place`, `year`, `metric`, `category`, `group_by`, `compare`, `reference` (it / that /
one / same / before / said …), `rank`, `scheme_topic` (benefits, eligibility, documents, apply,
launched, amount …), `lead` (a ≤6-word "what about / and …"), `non_english`. Empty → the turn is a
new question: `has_context=False` for both edge checks, no merge plan, no rewrite, no KNOWLEDGE
fallback to the previous turn's scheme. Logged as `pipeline_decision` stage `continuation`.

**Places at every level (D-058, 2026-10-21, KI-340):** `place` covers districts, blocks, assembly
constituencies AND villages, named with or without the level word — `entity_resolver.place_mentions`
reads an in-memory index of every `dim_geography` village name and alias (`load_village_names`:
startup, else lazily at the top of `_turn_context_stage`). The same index lets edge step 6
(`_names_meghalaya_place`) pass a bare place in a new chat (the pipeline then asks the scheme) and
`_names_place_only` overrule a guardrail scope verdict on a short place message. A follow-up that is
only a village, a constituency or a block of another district is rewritten by c01
`_place_swap_rewrite` (previous question, place swapped; the level word only when the name has one
level, so a same-name block/village still reaches the level gate). `rewrite_violation` rejects a
model rewrite that drops a typed place (`dropped:<dim>`) or respells a typed village (`village`;
`_restore_typed_village` puts a near-copy back). The level question asks only for the SAME name at
two levels (`collides_across_dimensions`, c09 `_c09_same_name_village`).

**The level comes from the database (D-059, 2026-10-21, KI-342..345; `PLACE_GAZETTEER`, default on):** the same
index also holds each village's code / block / district (`village_places`) and the schemes with rows for it
(`village_scheme_data`). `match_places(question)` lists every place with all its database levels (exact first, then a
misspelt village via `village_fuzzy`); the entity extractor gets it as "places a database lookup found"
(`_c07_places_hint`). At the level gate: an exact village anywhere is never offered a look-alike block / constituency;
a typo goes to the village only when it leads every look-alike by 12 points (`_VILLAGE_FUZZY_LEAD`; "malwai" still
asks); then `_c09_gazetteer_settle` narrows by the remembered block, the remembered district and the asking scheme's
rows, and a single remaining reading is resolved silently through its own chip question (the result carries that
`question`). Chips say where each reading lies (`_c07_chip_where`). `resolve_village` narrows its trigram list to the
clearly closest village the same way. The route node's village-NAME search keeps its "villages named X" trigger.
Measures a scheme does not hold (KI-350): MGNREGA has no sanctioned amount / budget — route step 1d' pauses
with `column-not-held` and a "Total expenditure instead" chip; a short reply naming another scheme to such a pause
continues the paused question (`_paused_thread_antecedent(rule=…)`).
Follow-up rewrite of a place-only follow-up (KI-346/347): an extractor "village" that no village carries but that is
exactly a block / constituency moves to that slot (c09); the place swap drops a coarser breakdown
(`_c01_drop_coarser_breakdown`); a model rewrite is rejected when it invents a level word the database lacks
(`_c01_invented_level`) or new content words (`_c01_place_only_drift`), or when a follow-up naming a block /
district keeps the previous question's finer place (`_c01_kept_finer_place`, KI-358: "What about Rongara block?"
after a Badimbari village answer), and any rejected rewrite of a place-only
follow-up becomes the deterministic swap (`_place_swap_rewrite(force=True)`; a district only for the kept-place
rejection, `district=True`), never the bare fragment; a typed level word is read without its "?"; the chat's
district is carried onto a village only inside it; "its block" to a village pause restates the paused question at
that level (c14 `_c14_level_only_reply`).

**Other asks instead of guesses:** a bare "which one?" (`is_bare_reference` → plan
REQUIRE_CLARIFICATION → `reference-ambiguous`); a letter-swapped district acronym
(`entity_resolver.acronym_near_misses`, e.g. WHK → West Khasi Hills chip; runs in `_answer_data`
before `resolve_entities`); a Focus Plus payment amount it never pays (`amount-not-held`).

**Contract enforcement before execution** (§2.8): `_resolved_scope_missing` and
`_focusplus_stated_amount_missing` turn a dropped constraint into a repair instruction, before
the 4B verifier.

**State:** `update_state` now drops a field the turn's plan CLEARs / REPLACEs when the result does
not name it (KI-032), and a DATA turn with no plan (a question of its own) resets geography and
year. `ConversationState.year_all` records an all-financial-years scope; `inject_year_scope`
appends "across all financial years" to a follow-up that keeps the year (KI-030); the Known-context
line shows `year=all financial years`. Persisted in the snapshot.

**Observability:** `context_budget.log_decision(stage, **facts)` writes one `pipeline_decision`
JSON line (request_id, stage, labels only): `continuation`, `followup` (signals, kind, non-KEEP
actions), `edge`, `intent`, `clarify` (rule, reason), `sql_guard` (guard, verdict, missing field),
`entity_search`. With `prompt_context` (sizes) and `llm_call` (tokens, latency) that answers why
an intent, scheme, clarification or SQL rejection happened.

**Second pass (2026-09-29, live-verified, KI-136 to KI-144):**
- a bare "Focus" used as a scheme name (`_names_bare_focus_scheme`, not `_FOCUS_AS_NOUN`) is never
  sent to the model rewrite, so the which-Focus pause asks;
- which thread a follow-up continues is decided per follow-up (`_followup_thread_state`): after a
  KNOWLEDGE answer about another scheme, a follow-up naming nothing continues that scheme with a clean
  state; one whose own words pick the earlier scheme ("and person-days?" = MGNREGA) continues the
  earlier thread, with that scheme's last DATA turn as the antecedent (`_data_thread_antecedent`,
  which also takes a place / year-only change after knowledge answers back to the last DATA turn).
  The digression never overwrites the session state; `update_state` drops unnamed filters when the
  committed scheme changes;
- after a KNOWLEDGE answer, a measure-only request gets the scheme appended with no model rewrite
  (`_measure_after_knowledge`), and a rewritten follow-up's intent comes from the typed words when
  the fast path decides them (`_typed_intent`);
- the rewrite must keep the follow-up's own metric family (`rewrite_violation`);
- the KNOWLEDGE path drops a year and a place the user never typed (`_drop_inherited_time`,
  `_drop_inherited_place`);
- a Focus Plus stated-amount answer is guaranteed to say which payments it covers and, for "loan",
  that Focus Plus is not a loan (the composer note alone was ignored live);
- a paused follow-up is remembered as its standalone form (`turn_context["standalone_question"]`,
  `routers.query.pause_question`);
- "all of them / combined / in total / both" CLEARs the dimension the last follow-up varied
  (`ConversationState.last_dimension`); for the year the rewrite is deterministic (`_all_years_rewrite`).

**Cost:** under 1 ms per turn in total (measured: continuation_signals 0.63 ms, the rest
≤0.16 ms each); no model call added.

### 5.6 Scheme substitution (VERIFIED live, 2026-09-26)

"give me same for mgnrega" after "how many beneficiaries in focus + for all of Meghalaya across
all financial years" means the **same operation on another scheme**.

**The failure it fixes, traced live:**
1. `looks_like_followup` returned False: the message names a scheme, and
   `_SCHEME_SWAP_FOLLOWUP` only knew a fixed set of openings.
2. So no rewrite ran, and `classify_intent` saw the bare words. The 4B classifier returned
   KNOWLEDGE.
3. RAG then answered with general MGNREGA information.

**The fix:**
- `pipeline._scheme_substitution(q)` returns `(scheme, pure)`. It needs a continuation cue
  (same / do it / repeat / likewise / what about / now for / and for / instead / switch to …)
  plus exactly one scheme from `_SCHEME_NAME_MATCHER`, the registry. No scheme name is
  hard-coded. `pure` means nothing else is asked once fillers are removed.
- A **pure** substitution is a follow-up (`looks_like_followup`). The existing deterministic
  `_scheme_swap_rewrite` swaps only the scheme in the previous question, so intent, metric,
  geography, time and grouping carry over verbatim, and `prior_resolved` inherits the filters.
- **With a "same" cue and changes of its own** ("give me the same for mgnrega in 2023-24"),
  `is_scheme_substitution(q, prev)` makes it a follow-up. It then goes through the checked model
  rewrite and the merge plan.
- The merge plan labels both kinds `SCHEME_SUBSTITUTION`. The router's `is_cacheable` excludes
  them.
- **Not substitutions:**
  - two schemes (a comparison);
  - the scheme already in play;
  - no antecedent;
  - a weak cue with other content ("what about MGNREGA eligibility?"), which keeps its previous
    reading;
  - no scheme at all ("same number by district", "same for Dalu", "same but last year"), which
    goes through the normal field-level plan.

**Request-verb swaps and measure gaps (KI-180, VERIFIED live 2026-09-29):**
- `_SCHEME_SWAP_FOLLOWUP` also accepts a request verb before the preposition ("give me for
  pmay", "show us the same for PMAY-G", "can you give me for pmay?", "pmay too"), and
  `_SUBSTITUTION_CUE` reads "give/show/get/tell/fetch me [the same] for|in|under" as a cue ("give
  me for pmay please"). "tell me about pmay" / "what is pmay" / "give me pmay houses" are not
  swaps. A bare "focus plus please" is not a follow-up either (it stays cacheable).
- `_swap_measure_gap(followup, rewritten, prev, state)`, called in `_run_pipeline` right after
  the follow-up rewrite: after a DATA turn, when a scheme swap carried over a measure that only
  another scheme holds (`_SCHEME_OWN_MEASURES`: MGNREGA person-days / job cards / wages /
  material / employment; PMAY-G houses) and the follow-up did not type it, it raises
  `ClarificationNeeded(rule="swap-measure-unavailable")`: "PMAY-G doesn't record person-days —
  only MGNREGA does", with the new scheme's own measures (`_SCHEME_HEADLINE_OFFERS`) as chips,
  for the same scope (`_swap_scope_phrase`: state place + FY / all years; CM Elevate gets no
  year). Money and counts exist in every scheme and are left to the generator. Since KI-181 the pause is remembered (§5.2): a typed "houses sanctioned" or "the second one"
  resumes the chip.

---

### 5.8 Conversation layer and topic memory (2026-10-08, D-043; LIVE-VERIFIED)

Runs in `routers.query._answer` after `session_sync.sync_in`, before the caches
(`conversation_layer.prepare_turn`). It hands the pipeline a question, or answers a bare reset itself.
Off with `CONVERSATION_LAYER_ENABLED=false` (every message then runs exactly as before).

| Message | What happens |
|---|---|
| any, idle > `CONTEXT_IDLE_EXPIRY_SECONDS` (14400 = 4 h, D-051) | state, turns, summary, pending pause and topics cleared; a paused LangGraph run for the thread deleted; then the message runs fresh (cacheable) |
| "start a new topic", "forget the previous question", "let's start again", "reset" | the same clearing; bare -> edge reply `edge_type: context_reset`; "Forget that. How many …?" -> only the question runs |
| "what was the PMAY-G information again?", "remind me about PMAY-G" (a topic this chat holds, not the active one) | -> `Go back to PMAY-G, <PMAY-G's last question>` for topic_memory |
| "How many beneficiaries are there?" right after a single-scheme KNOWLEDGE answer (also after "go back to X", and inside "coming back to X, …") | -> `… under PMAY-G?`, the pipeline's own `_measure_after_knowledge` rewrite (KI-222) |
| "What about PMAY-G?" | untouched: the existing scheme swap (§5.6) |

Topic memory (`app/topic_memory.py`, called first thing in `_turn_context_stage`) keeps one record per
scheme topic (state, last turn, last 5 questions, summary) and restores it on "go back to / coming back
to / back to / switch back to …"; an unnamed "the previous topic" with two or more candidates asks
which. `session.topics` and `session.context_at` are in the durable snapshot, so both work on any
worker. A topic switch, a reset and a rewritten turn are never cached.

**Backward context memory (2026-10-18, D-050; LIVE-VERIFIED).** Each topic also keeps a ledger of its last 6
questions with the scope each ran in. In `_turn_context_stage`: `topic_memory.resolve_turn` restores an earlier
QUESTION by order / content (or asks with `ledger-ambiguous` chips) and answers "what did we discuss?"; then,
only for a backward cue the rules placed nowhere, `topic_memory.resolve_reference` asks the 9B to pick a ledger
id (NONE / ASK otherwise). A restore re-runs the question in the restored scope. `node_finalize` adds
`scope_banner` to every DATA answer (`_attach_scope_banner`, from the SQL's own entities; "(from earlier)" on a
restore). After an idle expiry the router adds `continue_offer` ("Continue with MGNREGA (…)") to the first reply;
tapping it restores the set-aside context (`conversation_layer`, `Session.expired_ctx`). A new district clears
the old block and village (`context_manager.update_state`).

**"Show me the districts, I'll choose one" (2026-10-18, KI-317; LIVE-VERIFIED).** Step 0g of `_turn_followup_stage`, before the follow-up rewrite: right after a DATA answer, a message that asks to see the districts in order to pick one (`_asks_to_pick_district`: "district(s)" plus choose / pick / select / "ask me" / "I will say" / list / "what are the"; never with a ranking or breakdown word, "district-wise", or "how many" without a choose word), that names no district / block and no other scheme, pauses with the previous question once per district (`_pick_district_clarification`, rule `scope-not-specified`, "for all of Meghalaya" / the earlier district taken out, plus an "All of Meghalaya" chip). `standalone_question` is that stem, so a typed "East Khasi Hills" merges back.

**Talking about the conversation itself (2026-10-18, D-052, KI-310).** `c15_conversation_meta.py`. `_meta_kind(raw, prev)`
reads the typed words (no model): a complaint lead ("why are you not giving me …", "that's wrong, I asked for …",
"no, I meant …") followed by a dimension word is a **breakdown**, followed by content is a **correction**, followed by
nothing is **misread**; otherwise recap / explain / misread / suggest word lists, each only when the message brings no
scheme, place, year or measure of its own. Edge stage step 0-b (`_conversation_meta_answer`, before the edge banks):
**recap** = the previous answer again with its scope line; **explain** = `llm.call_rewriter` (role `explain`, 9B,
`LLM_REFERENCE_TIMEOUT_SECONDS`) on the previous question / answer / rows summary / scope, kept only when its numbers
are a subset of those and its shape is sane, else `_c15_explain_fallback`; **misread** = "Sorry — I read your message
as “<previous question>” …" (3 rotating wordings) + how to ask; **suggest** = a bullet list (`_c15_chips`: "Break that
down by district / block", "Compare with the previous financial year", then `edge._SCHEME_STARTERS`). Replies are
`route: edge`, `edge_type` = the kind, `context_dependent`, and set the topic-memory "aside" so the next message still
continues the topic. Follow-up stage step 0h (`_meta_question`): **correction** -> the text after the lead runs as the
follow-up ("completed houses", the normal rewrite keeps the scope); **breakdown** -> `_c05_statewide_stem(prev.question)
+ " by <dim>"`, standalone, no rewrite; both set `turn_context["answer_preface"]`, which `_attach_preface` (finalize)
puts in front of a data / knowledge answer.
Route stage step 1i: `_overview_question` (one scheme, one district / block, an overview cue, no measure) -> the scheme's
headline question (`_C15_OVERVIEW_TEMPLATES`), intent DATA, preface "Here's an overview of …". Follow-up stage step 0i:
`_relative_year_clarification` ("last year" / "this year" with no year in the thread state, no own scheme / place / year)
-> `year-not-specified` pause with the scheme's FYs as single-year chips (no year-by-year chip for MGNREGA, KI-311).
**reason** ("why is it so low?", a data turn behind it, not about the bot): a fixed reply plus `_c15_reason_chips`
("<headline measure> by block in <parent district> in FY …" via `entity_resolver.block_parent_district`, by district,
"Compare with the previous financial year", year by year except MGNREGA). `looks_like_followup` strips opening fillers
(`_c01_strip_opening_fillers`: ok / okay / so / yes / sure / please …).
Follow-up stage step 0h' (KI-316): `_rollup_question(raw, prev, session.turns, session)`: a roll-up cue (`_C15_ROLLUP_DISTRICT` /
`_BLOCK` / `_STATE`) with no place, scheme or year of its own, after a DATA turn -> the topic's last aggregate question
(`_c15_earlier_data_turns`: the topic ledger newest-first, then `session.turns`; breakdown-shaped questions skipped by
`_c15_is_breakdown_question`) with the place swapped (`_c15_swap_place`, every form of the name), standalone, plus a
`MergePlan(GEOGRAPHY_CHANGE)` that CLEARs the rolled-past levels (`_c15_rollup_plan`), kept through the stage as `_rollup_plan`
so `_turn_data_context_stage.apply_merge_plan` drops them from `prior_resolved`. Asides: `conversation_replies.restyle` records
the aside for EVERY kind (a harmful refusal included); `conversation_layer.resume_after_small_talk` also treats a `denied` turn as
an aside. Acceptance: TESTING.md 2026-10-18 (context memory through the HTTP API).
Follow-up stage step 0h'' (KI-320): `_compare_with_scheme_question(raw, prev)`: a compare cue (compare / compared / vs /
versus / against) + exactly ONE scheme name that is not the previous turn's (exact name first, else the fuzzy spelling) + nothing
else (no place, year or other words beyond fillers) after a single-scheme DATA turn -> "Compare <prev> and <named> in <place>
in <FY>" (place / year from `_scope_banner_place` / `_scope_banner_year` of the previous resolved entities), standalone, no model
call; `cross_scheme.detect` then takes it.

## 6. Post-answer
- `followups.build_followups(route, question, schemes, resolved, sql, rows)`: up to 3
  deterministic `follow_up_options`, from per-scheme banks. No model call.
- Caching is done in the router (exact + semantic). Clarifications, follow-up fragments and any
  reply to a pending clarification (`session.pending_scope_q` set) are never looked up in or
  written to the cache.

---

## 7. Where to change what (guidance)

| Symptom | Look at |
|---|---|
| Wrong scheme picked | `_shortcut_scheme`, `_SCHEME_NAME_MATCHER`, `_<X>_ONLY_TERMS`, `_infer_scheme_from_terms`, `_pin_cm_elevate_dataset` |
| Place misresolved | `entity_resolver.resolve_dimension` / YAML catalogues, `extract_entity_mentions` prompt, `_drop_producer_group_names` |
| Wrong SQL shape | few-shot YAML (add a right-shaped example), `schema_context` rules, then a guard in `execute_with_repair` |
| Verifier false positive | add a filter to `_verify_sql` (e.g. `_verifier_village_code_complaint_is_false`) or a calibration example in `prompt_builder._VERIFY_CALIBRATION` |
| Wrong number in prose | `compose_response` guards; never loosen `_answer_numbers_faithful` |
| Clarification loop | `_reply_abandons_scope_pause`, the gate's `_needs_*` function, `pending_scope_q` handling |
| Typed scheme reply not resumed | `_resume_scheme_pause`, `SCHEME_PAUSE_RULES`, router `pending_scope_rule/options` |
| Follow-up lost or gained a filter | `context_policy.plan_state_merge` / `apply_merge_plan` (the plan is in `session.turn_context["plan"]`), `context_manager.build_rewrite_evidence`, `context_policy.rewrite_violation`; the `prompt_context` line with `"kind": "rewrite"` shows the kind, tiers and guard verdict |
| A message inherited a scheme it has nothing to do with / a follow-up lost its context | `context_policy.continuation_signals` (§5.7); the `pipeline_decision` line with `"stage": "continuation"` or `"followup"` shows the signals |
| A stated constraint missing from the SQL | `_resolved_scope_missing`, `_focusplus_stated_amount_missing` (§2.8); `pipeline_decision` `"stage": "sql_guard"` |
| Follow-up broke after a worker switch | `session_sync.sync_in/sync_out` log lines, `app.conversations.context_state->>'rev'` |
| KB answer wrong scheme | `_kb_scheme` selection, `rag._SCHEME_DOC_NAMES`, KB tags |

## 8. LangGraph orchestrator (2026-10-02, D-032; opt-in, offline-verified only)

The same stages, run as a 21-node graph:

```
context → edge → followup → route → (knowledge | data_context → scope_scheme → entities →
clarification_gate → deterministic → sql_generate → authorize → execute_attempt ⇄ repair →
post_rows → compose → guarantees → assemble) → finalize → context_update
```

- Any `ClarificationNeeded` → `pause_gate` (`interrupt()`), with a checkpoint under
  `thread_id = session_id`. The resume loops to `context`, where step c/c'/c'' decides.
- No prompt, model role, guard, gate or composer check changed. The graph spends exactly the
  model and DB calls of the sequential path (tested).
- Details: [LANGGRAPH_ARCHITECTURE.md](LANGGRAPH_ARCHITECTURE.md),
  [CONTEXT_AND_LANGGRAPH.md](CONTEXT_AND_LANGGRAPH.md),
  [LANGGRAPH_PAUSE_RESUME.md](LANGGRAPH_PAUSE_RESUME.md),
  [LANGGRAPH_MIGRATION.md](LANGGRAPH_MIGRATION.md).

