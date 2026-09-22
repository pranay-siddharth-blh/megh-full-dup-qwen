## Why

`app/entity_resolver.py`'s own module docstring states it is "scoped down
from [the resolver YAML's] full 8-stage pipeline... skipping... stage 7
embedding fallback," and `docs/baseline-audit.md` §5.6 marks the node
"Implemented and verified" on that reduced scope (stages 1/2/3/6 only).
`data/mgnrega/mgnrega_entity_resolver.yaml`'s own `matching_pipeline` (the
SME-authored spec this module is ported from) already fully specifies the
missing stage:

```yaml
- stage: 7_embedding
  test: BGE-small nearest neighbour over the dimension catalogue
  use_when: fuzzy returned nothing at or above 80
  accept_at: cosine >= 0.88 AND the value is unique in its dimension
  otherwise: fall through to not_found with the top 5 as suggestions
```

Two concrete, observable gaps follow from this being unbuilt:

1. A genuine synonym or paraphrase for a district/block/year value that
   RapidFuzz's string-similarity scoring doesn't catch (e.g. a descriptive
   phrase rather than a misspelling) falls straight to `not_found` today,
   with no second chance.
2. `resolve_dimension`'s `not_found` branch never populates `Resolved.
   candidates` — there is no "top 5 as suggestions" did-you-mean list at
   all today, contradicting both the YAML spec above and this feature's
   own stated purpose (three outcomes per entity: resolved / ambiguous /
   **not found, did-you-mean fallback**).

Separately, a Redis-backed cache is requested for "dimension values." Re-
verifying against the current code: the in-memory catalogues this loads
(district ~12, block ~56, year 4, per scheme) are read once from
version-controlled YAML at startup (`app/main.py:78`) and cost nothing to
re-read — Redis would cache something that is already free. The one piece
of entity resolution that *does* hit a slow, shared, cacheable resource on
every call is `resolve_village` (`app/entity_resolver.py:629`): a live
Postgres query against `curated.dim_geography` (~6,000 rows) per village
mention, with no caching at all today. This proposal redirects the caching
ask to where re-verification shows it actually pays for something,
following this repo's established practice of correcting a literal
original-spec reading against what the real code needs (see
`query-analyzer-consolidation`'s task 4.1 for precedent) rather than
building an unneeded cache in front of an already-in-memory YAML table.

## What Changes

- **Embedding fallback (stage 7)** for `resolve_dimension` only, on
  `district` / `block` / `year` / `assembly_constituency` / `tranche_label`
  — the closed-set catalogues already living in `_catalog`. Fires only
  when stage 6 (RapidFuzz) does not resolve or land in the ambiguous band
  (i.e. top score < 80, per the YAML's `use_when`). Embeds the user text
  and every catalogue canonical+alias once via the existing
  `app/local_embed.py` (`fastembed`, `BAAI/bge-small-en-v1.5`, already a
  pinned dependency, CPU/offline, no gateway call), takes the nearest
  neighbour by cosine similarity, and accepts it only when similarity
  ≥ 0.88 **and** it is the unique top candidate for that dimension —
  otherwise falls through to `not_found`. Catalogue vectors are computed
  once inside `load_all()` and held in-process (module-level, alongside
  the existing `_catalog`); not persisted to Redis or disk — recompute
  cost is a few hundred short strings, sub-second, same lifecycle as the
  YAML catalogue itself.
- **Blocked-pairs guard extended to the embedding stage**: the same
  `_blocked` pair set stage 6 already consults must also veto an embedding
  match, for the same reason (e.g. `LASKEIN` / `THADLASKEIN` must never
  resolve into each other via any matching stage).
- **Did-you-mean suggestions on `not_found`**: `Resolved.candidates` is
  populated with up to 5 nearest values (by whichever stage got furthest —
  RapidFuzz's own extract list when it ran, else the embedding stage's
  nearest neighbours) whenever resolution ends in `not_found`, matching
  the YAML's "fall through to not_found with the top 5 as suggestions" and
  this feature's own stated three-way contract.
- **Redis-backed cache for `resolve_village`**: read-through cache keyed on
  `fold(text) + district scope + block scope`, short TTL, using the exact
  best-effort pattern `app/cache.py` already establishes (`REDIS_URL`
  unset, unreachable, or erroring silently degrades to running the DB
  query directly — never fails a request). Caches the resolved outcome
  (`resolved` / `ambiguous` / `not_found` payload), not raw rows.
- **Explicitly out of scope / non-goals:**
  - `resolve_house_status` and `resolve_tranche_label`'s closed-set token
    matching — these already have deliberately hand-curated deny-lists
    (`_HOUSE_STATUS_ALIAS_DENY`, etc.) precisely because generic
    similarity matching (fuzzy *or* semantic) resolves overloaded terms
    wrong (e.g. "sanctioned" is also a date/amount filter). Adding
    embedding fallback there would reopen exactly the ambiguity that deny
    list was built to close. `tranche_label`'s own dimension entry in
    `_catalog` is excluded from the new stage-7 fallback for the same
    reason — its guard logic (`_TRANCHE_NUMBER_RE`) exists to prevent a
    bare, unscoped fuzzy/semantic match.
  - The YAML's `stage: 5_contains` (whole-word substring containment) —
    partially covered today by `scan_dimension` (district only, by
    design; blocks are deliberately excluded there due to 26/56 block
    names colliding with assembly constituencies or villages). Extending
    stage 5 to more dimensions is a separate, differently-scoped decision
    and not part of this change.
  - `resolve_village`'s own matching logic (exact → trigram) is unchanged;
    this change only adds a cache in front of it.
  - No new dependency: `fastembed` and `redis` are both already pinned in
    `requirements.txt`/`requirements.lock`.

## Capabilities

### New Capabilities
- `entity-resolver-semantic-fallback`: for the closed-set dimension
  catalogues (district/block/year/assembly_constituency), a user mention
  that RapidFuzz cannot confidently resolve gets one more deterministic
  attempt via embedding nearest-neighbour before falling to `not_found`;
  every `not_found` outcome carries up to 5 suggested values; village
  resolution's DB round trip is cached behind a best-effort, silently-
  degrading Redis layer.

### Modified Capabilities
- None. `resolve_dimension`'s existing stages 1/2/3/6 behavior, return
  shape, and all currently-passing `tests/test_entity_resolver.py` checks
  are unchanged — the embedding stage only runs where those stages already
  fall through to `not_found`/low-confidence `ambiguous`, and
  `resolve_village`'s query logic is unchanged, only wrapped in a cache.

## Impact

- **Modified**: `app/entity_resolver.py` (embedding stage, suggestions
  population, village cache wrapper), `app/config.py` (new settings:
  embedding-fallback threshold/enable flag, village cache TTL — reusing
  existing `REDIS_URL`/`LOCAL_EMBEDDING_MODEL` settings, not new ones for
  those).
- **New dependency**: none.
- **Tests**: extend `tests/test_entity_resolver.py` (or a sibling
  `tests/test_entity_resolver_semantic_fallback.py`, matching this
  codebase's one-capability-per-file convention where a change is
  substantial) covering the embedding accept/reject bands, the blocked-
  pairs veto applying to the new stage, did-you-mean population on
  `not_found`, and the village cache hit/miss/degraded-Redis paths
  (mocked, no live Redis/DB required — matching how `resolve_village` is
  exercised today per that test file's own docstring).
- **No schema/API breaking change**: `Resolved.candidates` on `not_found`
  is new and additive (previously always empty on that path); nothing
  existing is removed or renamed.
