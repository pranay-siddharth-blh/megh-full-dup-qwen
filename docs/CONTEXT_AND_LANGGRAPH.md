# Conversation context and LangGraph

How a conversation's context is kept, used and protected, and how it runs inside the LangGraph
orchestrator (the only one, D-036). **Short version: the context logic lives in ordinary
functions (context_manager, context_policy, topic_memory, conversation_layer); the graph runs them
as nodes and records what they decided. Postgres holds the conversation; the checkpoint holds only
a paused run.** Rewritten 2026-10-29 (lane A2, DOC-01b); it used to stop at D-030.

## 1. The layers, kept separate

| Layer | What | Where it lives | Lifetime |
|---|---|---|---|
| Conversation state | `ConversationState` (scheme, place, year, metric, tranche, comparison, provenance), the last turn (+ row summary), the pending pause, recent questions, the rolling summary, **the topics and their question ledger**, the idle clock, a set-aside (expired) or stopped context | `Session` (per-worker copy) ↔ `app.conversations.context_state` + `summary` (Postgres, versioned, D-023), with the owner (`user_id`) | the conversation (retention: `CONVERSATION_RETENTION_DAYS`, 0 = keep) |
| Semantic memory | past turns (question, standalone question, answer excerpt) for "relevant earlier turns" | Qdrant `CONTEXT_MEMORY_COLLECTION`, filtered by tenant, user, session and `memory_since` | `CONTEXT_MEMORY_RETENTION_DAYS` (30), or until the chat is deleted |
| Execution state | this turn's question, merge plan, inherited filters, schemes, entities, SQL, rows, answer | LangGraph state (`MeghalayaGraphState`) | one run (`fresh_turn_state`) |
| Checkpoint | a **paused** run | Postgres `app.checkpoint*`, `thread_id = session_id` | while a pause waits (`PIPELINE_GRAPH_PAUSE_TTL_SECONDS`), or until the chat is deleted |

Raw chat history is never copied into graph state or back into a prompt (D-022): the rewrite gets
the previous turn's filters, and its rows or answer excerpt only when the follow-up points into
them; every rewritten field is provenance-checked (D-024, `context_policy.rewrite_violation`).

## 2. Lifecycle of one turn

```
router _answer (one turn at a time per conversation on this worker: _TURN_LOCKS, CTX-01)
  session_store.ensure; the in-memory owner must be the caller          -> else 403
  session_sync.sync_in(user_id=...); the durable owner must be the caller -> else 403
  copy of the session as the turn found it (restored on 503/504/5xx and on Stop, CTX-10)
  conversation_layer.prepare_turn: stop / continue, idle expiry ("Continue with ..." chip),
      "start a new topic", plain-words recall, small talk, scheme listing
  caches (only is_cacheable turns; a cache hit first files the previous turn under its topic)
graph:
  context        topic_memory.resolve_turn (checkpoint = file the last turn under its topic;
                 "go back to <scheme | place | question N>"; "what did we discuss?"); reads
                 session.state; consumes a pending pause; continuation signals
  edge           a message with no continuation signal is a new question (no inheritance)
  followup       turn kind (D-061: FOLLOWUP / STANDALONE / VAGUE; D-065, D-075); deterministic
                 rewrites first (chart view, correction, compare with a scheme, breakdown of a
                 statewide answer, compare with a place, roll-up); else the merge plan
                 (KEEP / REPLACE / CLEAR / REQUIRE_CLARIFICATION) and the provenance-checked
                 model rewrite
  route          DATA or KNOWLEDGE
  data_context   prior_resolved = turn entities + state, minus what the plan REPLACEs / CLEARs,
                 minus model_inference values
  … DATA nodes …
  context_update update_state (+ rolling summary)
router: add_turn (not for a typed "stop") -> persist_turn -> index_turn -> sync_out (rev + 1)
```

## 3. Inheritance rules (each implemented once; the graph calls the same functions)

| Rule | Implemented by | Where |
|---|---|---|
| Explicit value in the question replaces the old one | `context_policy.plan_state_merge` → REPLACE | `followup` |
| Elliptical follow-up keeps scheme / place / year / metric | plan KEEP + `merged_prior_resolved` | `followup`, `data_context` |
| A self-sufficient question inherits nothing; with no year of its own it is asked the year | `context_policy.turn_kind` (D-061), D-065 | `followup` → `pause_gate` |
| …unless it repeats the chat's measure on the chat's scheme: it keeps the year, never the place | `_same_scheme_context_year` (D-075) | `followup` |
| "by district" or a new district clears the old block / village | plan CLEAR + `apply_merge_plan` | `data_context` |
| "Break it down by district" after a statewide answer = that question by district | `_c01_ctx07_breakdown_question` (CTX-07) | `followup` |
| "Compare … with <place>" = the previous question for both places | `_c01_ctx07_compare_place_question` (CTX-07); a plain place swap stays the model's (D-056) | `followup` |
| Scheme switch drops the old scheme's filters, but the old topic is kept | `update_state`; `topic_memory` | `followup`, `context_update` |
| A KNOWLEDGE / edge digression neither inherits nor overwrites | `update_state`, `resume_after_small_talk` | `context`, `context_update` |
| A value no user ever supplied is not inherited | provenance (`model_inference`) | `data_context` |
| "Which one?" with nothing to pick → ask | REQUIRE_CLARIFICATION, topic / ledger pauses | `followup`, `context` → `pause_gate` |
| A pause reply continues the PAUSED thread | `_paused_thread_antecedent`; D-065 keeps the paused question's kind | `context` |
| A follow-up that is ONE edit of the last data answer (regroup / roll-up, rank, one place, another measure, another year) is that answer's frame edited and rendered | `_c18_frame_followup` (D-110), first in the ctx07 loop; the string rules after it stay as fallbacks | `followup` |
| …and inherits exactly the edited frame's places and years | `_c18_merge_plan` + `_c18_prior_from_frame` (turn_context `frame_prior`) | `followup`, `data_context` |
| "the first one" / "1" / a lone "yes" to a which-scheme pause picks that chip | `_resume_scheme_pause` (D-110, as `_resume_option_pause`) | `context` |

## 3a. The answer frame (D-110, 2026-11-15)

**What it is.** A small plain-data record of what a DATA answer WAS (`app/answer_frame.py`): `schemes`,
`metric_key` (the catalogue key, only when the catalogue answered), `measure_text` (the question's own measure words,
scheme kept, scope and shape cut out), `qtype` (total / breakdown / ranking / compare / list / other), `group`
(district / block / village / constituency / year / month / scheme), `filters` (place and year keys exactly as
resolved), `all_years`, `order`, `limit`, `chart`, `source` (catalogue / fixed / model / cross), `sql_shape`, the
`question`. **Filled deterministically after the answer** (`finalize` → `c18 _attach_answer_frame` →
`_c18_fill_frame`): the catalogue's own query (its `/* metric:<key> <qtype> */` comment, its GROUP BY / ORDER BY /
LIMIT) when it answered, else the final SQL read with `sql_ast` (outer GROUP BY columns mapped to a dimension, ORDER BY
on the measure + a LIMIT under 100 = a ranking), else None. **Nothing is guessed**: `SELECT 1`, a set operation, a
grouping by an unknown column or by two dimensions leave `qtype` None / "other", and the resolver then does nothing.

**Where it lives.** `Turn.answer_frame` (a dict, so `Turn(**asdict)` in the graph state works), `build_turn` (reads
`result["answer_frame"]`, else fills it from the result: a cached or older result), the durable snapshot (the last
turn AND the turn before it, `_session.turn_before`, so a follow-up after a knowledge aside works on a fresh worker),
topic memory (`_turn_dict` / `_turn_from`), and every context frame (D-100: `measure`, `group`, `order`, `limit`,
`chart`, and the whole frame as `af`, for an older snapshot). An old snapshot loads with empty frames.

**The resolver** (`_c18_frame_followup`, run FIRST in the ctx07 loop of c14 and in `rewrite_followup`'s model-failed
path): the base is the previous turn's frame, or, after a knowledge aside on the same scheme(s), the last data turn's
(in-process turns, then the context frames' `af`). The message is read as ONE edit (`_c18_read_edit`), in this order:
rank ("which is the lowest", "top 3", "and the least?"), regroup with an optional place / year ("now by block", "what
about block wise breakdown", "break it down by block for Ri Bhoi"; a grouping at or above a filter clears that filter
and the levels below = a roll-up; after a ranking a place regroup keeps the ranking: "now by block" after "Top 3
districts" = "Top 3 blocks"), one place with a lead word ("only Ri Bhoi", "what about Ri Bhoi?", "and Ri Bhoi?",
"only Umsning block"; a block's district is its parent from the catalogue), another measure (c01's catalogue measure
swap applied to `measure_text`), another year ("what about 2023-24", "the year before"; one year of a per-year list
= that year's total). A scheme named in the message, a bare place, a village, a cross-scheme frame: None. ONE renderer
(`_c18_render`) writes the standalone question: `<measure>[ under <scheme>][ in <place>][ by <group>][ in FY <year>]`,
a ranking opened by "Which district has the lowest: " / "Top 3 districts: " (the shapes `_c01_ranked_stem` reads), so
every output is a shape the next turn reads back. The merge plan (`_c18_merge_plan`: KEEP / REPLACE / CLEAR per field
from the two frames) and the inherited filters (`_c18_prior_from_frame`: every place / year key replaced by exactly the
frame's; tranche / CM sub-scheme kept) go to the later stages through `session.turn_context` (`plan`, `frame_prior`,
`frame_edit`).

**The catalogue takes the frame** (`_c18_catalogue_from_frame`, called first in `_metric_catalog_query` with
`d["frame_edit"]`): only when the previous answer was the catalogue's (a `metric_key`), the measure is verified for the
frame's query type (`data/metric_catalog_verified.yaml`), and the resolver's filters agree with the frame's; else the
words are matched as before.

**One grouping reader.** `context_policy.grouping_dims` (moved from c02 `_c02_breakdowns`, which now calls it):
"across / in / for all (the) districts" and "every block" are a grouping of that place level, read the same way by
`asked_levels` (which adds only rankings over a level and the statewide scope words).

## 4. Topics, expiry, stop and reset

- **Topics** (`topic_memory`): one record per scheme set, with its state, last turn and a ledger of
  its questions (`CONTEXT_LEDGER_PER_TOPIC`), all in the durable snapshot. "Go back to MGNREGA",
  "go back to the first question", "go back to the East Khasi Hills one" and "go back to
  Mawphlang" restore the scope that question ran in. Since CTX-02 (2026-10-29) a revision jump no
  longer resets them: cache hits, small talk and "stop" save a revision without passing through
  the graph.
- **Idle expiry** (`CONTEXT_IDLE_EXPIRY_SECONDS`): the context is set aside and the first reply,
  a pause included, offers "Continue with …"; the tap restores it and abandons any pause asked
  since. Any other message drops it.
- **"Start a new topic"** clears state, turns, summary, pending pause and topics, everywhere: the
  durable summary is written as the session holds it, None included (CTX-11).
- **Stop**: a typed "stop" with nothing running is answered and is not a turn (the topic carries
  on, CTX-13); the Stop button cancels the turn, restores the session as the turn found it and
  records the question for "continue".

## 5. Caches and privacy

- The answer caches are shared by everyone in the same scope, so only turns that do not depend on
  their chat are read from or written to them (`routers/query.is_cacheable`). A table test runs the
  real gate over every harness turn (`tests/test_cacheable_shapes_2026_10_28.py`, CTX-06).
- Cached results never carry the asker's own words (`translated_from`, CTX-14).
- A conversation belongs to the user who started it: anyone else sending its id gets **403**,
  checked on this worker's copy and on the durable row, with an SQL backstop in the upserts
  (CTX-01). Unknown owners (dev, old rows) are not checked.
- Deleting a chat deletes its turns, its Qdrant memory, its paused run and this worker's Session
  (CTX-04). The decision log never holds question text: `log_decision` logs a hash and a length
  (CTX-08).

## 6. Examples (tests that drive these through the real graph or router)

| Conversation | Result | Test |
|---|---|---|
| CM Elevate EKH → "What about West Khasi Hills?" | scheme kept, district replaced | `test_pipeline_graph.py` |
| … → pause → "thanks" / "What is CM Elevate?" | the pause is abandoned | `test_pipeline_graph.py` |
| MGNREGA → PMAY-G → cached MGNREGA → "go back to MGNREGA" | both topics kept, MGNREGA's scope restored | `test_topic_rev_2026_10_28.py` |
| MGNREGA → "stop" → "What about FY 2023-24?" | "… under MGNREGA" | `test_stop_offer_cache_2026_10_29.py` |
| statewide Focus Plus → "Break it down by district" | the question by district | `test_ctx07_followups_2026_10_29.py` |
| another user on the same id | 403, owner untouched | `test_ownership_turns_2026_10_29.py` |

## 7. Debugging a context decision

1. Find the request's `pipeline_graph_run` line: `path` shows which nodes ran, and
   `pause_outcome` how a pending pause was read.
2. Read the `pipeline_decision` lines with the same `request_id`: stages `conversation`,
   `topic`, `turn_kind`, `continuation`, `followup` (kind, actions, rewrite), `pause_reply`,
   `intent`, `data_context`. Question text appears only as `{"sha256", "chars"}`.
3. With `PIPELINE_GRAPH_KEEP_THREADS=true` locally, `graph.aget_state({"configurable":
   {"thread_id": sid}})` shows `conversation_context`, `plan`, `prior_resolved` and
   `context_after` for the last run.
4. Live: `tests/conversation_harness` (in-process with `--fresh-worker`, or HTTP with the caches
   on) and `tests/live_context_validation.py` (a dated result file per run).
