## 1. Embedding fallback (stage 7) for closed-set dimensions

- [x] 1.1 Re-verified before coding: `app/entity_resolver.py`'s `resolve_dimension`/
      `_catalog` and `app/local_embed.py`'s `embed()` were re-read in this
      session immediately before implementation; nothing had changed since
      the proposal was written.
- [x] 1.2 Added module-level `_embeddings: dict[str, dict[str, list[tuple[str,
      list[float]]]]]` (scheme -> dimension -> [(canonical, unit_vector)]),
      populated by a new `load_embeddings()` for `district`/`block`/`year`/
      `assembly_constituency` only. Each canonical + alias string is embedded
      **individually, not averaged** (one vector per string, tagged with its
      owning canonical) — an alias phrased very differently from its
      canonical can then still be the nearest match on its own terms. `_unit`/
      `_dot` added (same L2-normalise-then-dot-product pattern as
      `app/semantic_cache.py`).
- [x] 1.3 `resolve_dimension` is now `async` (only stage 7 needs to await
      anything; stages 1/2/3/6 are unchanged sync logic). After stage 6 fails
      to resolve — including the blocked-pair early-return path, not just the
      final fallthrough — `_embedding_fallback()` embeds the user text,
      ranks catalogue canonicals by best cosine similarity across their own
      variant vectors, and resolves only when the top score clears
      `settings.ENTITY_RESOLVER_EMBEDDING_ACCEPT` (0.88, the YAML's own
      figure) **and** leads its runner-up by at least `_EMBED_RUNNER_UP_GAP`
      (0.03). The blocked-pairs guard is re-applied to the embedding stage's
      own top candidate.
      **Deviation from the literal spec, found empirically, not
      guessed:** the proposal's "unique top candidate" language turned out
      to be insufficient on its own. Probing the real model (BAAI/
      bge-small-en-v1.5 via fastembed) against the actual MGNREGA district
      catalogue found that a genuinely ambiguous phrase like "khasi hills
      area" (no east/west/south qualifier) still produces a distinct,
      confident-looking top match (West Khasi Hills, cosine 0.9475) whose
      nearest sibling (South West Khasi Hills, 0.9404) is only 0.007 behind
      — well inside model noise — while a real, correctly-resolvable
      paraphrase ("district with Shillong" -> East Khasi Hills, 0.9584) has
      a ~0.29 gap to its nearest sibling. Added an explicit minimum-gap
      requirement calibrated against this observed separation (see the
      comment above `_EMBED_RUNNER_UP_GAP` in `entity_resolver.py` for the
      full data). Without it, several genuinely ambiguous mentions would
      have silently resolved to an arbitrary specific district instead of
      correctly falling through to `not_found`/`ambiguous`.
      **Second deviation, also found by testing, not assumed:** loading the
      catalogue vectors via `fastembed` on this box, even with the model
      already cached locally from a prior session, **hung for 45+ seconds**
      with no error — `HF_HUB_OFFLINE=1` was required to make it check the
      local cache instead of first reaching out to the HuggingFace Hub for
      metadata, which this environment has no route to. Since `app/main.py`'s
      `_try()` wrapper only catches exceptions (not hangs), this would have
      silently violated its own "never blocks boot" contract on any
      network-restricted box. Fixed by wrapping the startup call in
      `asyncio.wait_for(..., timeout=settings.
      ENTITY_RESOLVER_EMBEDDING_LOAD_TIMEOUT_SECONDS)` (new setting,
      default 90s) rather than forcing `HF_HUB_OFFLINE` globally (which
      would break a genuinely fresh box's first-time model download).
- [x] 1.4 Added `tests/test_entity_resolver_semantic_fallback.py` — 8 checks,
      deterministic by construction (a synthetic "TESTSCHEME" catalogue with
      hand-placed 2D unit vectors at exact, reproducible cosine similarities,
      plus a monkeypatched `_embed_texts`; no real model load, no network).
      Covers: a clearly-nearest match resolving despite fuzzy failing
      entirely; a top score below the acceptance bar falling through; a
      high top score with an unsafe runner-up gap being rejected (the exact
      failure mode found in 1.3); the blocked-pairs guard vetoing an
      otherwise-accepted embedding match; `tranche_label`/`house_status`
      never invoking the stage (no catalogue vectors exist for them); and
      full end-to-end wiring through the real `resolve_dimension`. All 8
      passing.
- [x] 1.5 Ran `tests/test_entity_resolver.py` unmodified in substance (only
      change: `resolve_dimension` calls now `await`, required by 1.3's
      signature change, and one new check that `not_found` carries
      suggestions) — all 18 checks pass, confirming stages 1/2/3/6 keep
      their existing behavior.

## 2. Did-you-mean suggestions on not_found

- [x] 2.1 `resolve_dimension` now populates `Resolved.candidates` (up to 5
      entries, via a new `_suggestions()` helper) on every `not_found`
      return, including the blocked-pair early return. Source is always
      RapidFuzz's own `process.extract` ranking — confirmed during
      implementation that stage 6 always runs and always produces a ranked
      list whenever the dimension's catalogue is non-empty, so the
      embedding-neighbours-as-suggestions branch the proposal described as
      a fallback is unreachable in practice and was not built as dead code.
- [x] 2.2 Added to `tests/test_entity_resolver.py` (real MGNREGA data): a
      `not_found` result for a genuinely foreign place name still carries a
      non-empty `candidates` list. Added to the new semantic-fallback test
      file: a `not_found` result's candidates all name real catalogue
      values from the synthetic scheme.
- [x] 2.3 Checked every `.candidates` read site in `app/pipeline.py` (7
      occurrences): all of them are gated on `status == "ambiguous"` and
      read `resolve_village`'s candidate shape (`village_code`/`name`/
      `district`/`block`), never `resolve_dimension`'s `not_found` output.
      No collision found — `not_found`'s newly-populated `candidates` is
      not read anywhere today. `pipeline.py`'s existing not-found handling
      (`notes.append(f"'{x}' is not a known {dim} ...")`, consumed by
      `app/query_analyzer.py`'s regex-based ambiguous-note parsing) is
      **left untouched** — wiring the new suggestions into that user-facing
      text was not part of this proposal's scope and risks that parser;
      the data is available for a future change to consume.

## 3. Redis-backed cache for resolve_village

- [x] 3.1 Re-verified `app/cache.py`'s Redis pattern (lazy client via
      `_redis()`, `REDIS_URL` gate, silent degrade on any failure) and
      `resolve_village`'s call sites/return shape immediately before
      wrapping it — unchanged since the proposal was written.
- [x] 3.2 Reused `app.cache._redis()` directly (one shared client per
      process) rather than standing up a second Redis connection. Added
      `_village_cache_key` (folded text + district/block scope — two
      different scopes for the same text are genuinely different lookups),
      `_village_cache_get`/`_village_cache_put` (JSON via `dataclasses.
      asdict`/`Resolved(**data)`), and new `VILLAGE_CACHE_TTL_SECONDS`
      setting (default 600s — deliberately separate from
      `RESPONSE_CACHE_TTL_SECONDS`, a different cache domain).
      **Correctness fix made during implementation, not left for review:**
      the first draft only wrapped the Redis `get`/`setex` calls in
      try/except, not the `_redis()` client-acquisition call itself. Since
      `app.cache._redis()` already catches its own connection errors and
      returns `None`, this happened to work — but it silently assumed that
      stays true rather than guaranteeing it locally, so a future change to
      `_redis()` could have turned a cache outage into a raised exception
      out of `resolve_village`, a real user-facing lookup. Moved the whole
      body inside the `try` before writing the test in 3.4 that would have
      caught it.
- [x] 3.3 `resolve_village` is now a thin cache-check wrapper; the original
      body (unchanged) was renamed to `_resolve_village_live`.
- [x] 3.4 Added `tests/test_entity_resolver_village_cache.py` — 11 checks,
      `_redis` and `fetch_rows` both monkeypatched (in-memory fake Redis, no
      live server): cache hit skips the DB and returns the same outcome;
      cache miss (including a different district/block scope) queries the
      DB and populates the cache; a Redis connection error on every call
      still resolves correctly via the DB, both on first *and* second call,
      with no exception raised (this is the check that would have caught
      3.2's near-miss); Redis unconfigured (`_redis()` returning `None`,
      the actual default/common case) behaves identically to the outage
      case. All 11 passing.

## 4. Regression sweep

- [x] 4.1 Ran the full `tests/` suite (32 files, one process each). **31/32
      passing** — every file this change touches or could plausibly affect
      (`test_entity_resolver.py`, `test_entity_resolver_semantic_fallback.py`,
      `test_entity_resolver_village_cache.py`, `test_scope_scheme_classifier.py`,
      `test_query_analyzer.py`, `test_query_analyzer_integration.py`,
      `test_langgraph_query_analyzer.py`, `test_query_langgraph_wiring.py`,
      `test_pipeline_schema_retrieval.py`, `test_pipeline_join_discovery.py`)
      included and passing. The 1 non-passing file, `smoke_restructure.py`,
      requires a live server on localhost (none running in this
      environment) — the same pre-existing, unrelated environmental gap
      already documented for this file in prior changes' regression
      sweeps; it does not import or exercise `app/entity_resolver.py`.
- [x] 4.2 Updated `docs/baseline-audit.md` §5.6's row with a dated Update
      block: what was closed (stage 7, did-you-mean suggestions, village
      caching), what stayed deliberately unbuilt (house_status/tranche_label
      embedding, stage 5 containment), and the empirical runner-up-gap
      correction — without overstating scope.
