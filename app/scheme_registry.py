"""
Scheme registry — the structural backbone for schema retrieval and join
discovery. Loads scheme_registry.yaml once at startup, exactly like
app/annotations.py and app/entity_resolver.py load their YAML caches (no
periodic refresh exists anywhere in this codebase — checked both before
writing this). Reload without a redeploy is a manual admin-triggered action,
matching the real precedent already in the codebase
(app/routers/rag.py's POST /api/rag/reingest), not an automatic background
refresh.
"""
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "scheme_registry.yaml"

# scheme_id -> {"display_name", "aliases", "tables", "shared"}
_registry: dict[str, dict] = {}


def load_all() -> None:
    """Read scheme_registry.yaml. Safe to call again to reload — replaces the
    whole registry, never merges, so a removed entry actually disappears."""
    global _registry
    try:
        data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("scheme_registry: no file at %s", _REGISTRY_PATH)
        _registry = {}
        return

    new_registry: dict[str, dict] = {}
    for entry in (data or {}).get("schemes", []):
        scheme_id = entry.get("id")
        if not scheme_id:
            continue
        new_registry[scheme_id] = {
            "display_name": entry.get("display_name", scheme_id),
            "aliases": list(entry.get("aliases") or []),
            "tables": list(entry.get("tables") or []),
            "shared": bool(entry.get("shared", False)),
        }
    _registry = new_registry
    logger.info("scheme_registry: loaded %d entries from %s", len(_registry), _REGISTRY_PATH)


def scheme_ids(include_shared: bool = False) -> list[str]:
    """Every registered scheme id, excluding the shared/cross-scheme entry
    unless include_shared is set."""
    return [sid for sid, e in _registry.items() if include_shared or not e["shared"]]


def tables_for(scheme_id: str) -> list[str]:
    return list(_registry.get(scheme_id, {}).get("tables", []))


def shared_scheme_ids() -> list[str]:
    """Scheme ids tagged shared=true — their tables/documents are retrieved
    regardless of which scheme(s) are classified active."""
    return [sid for sid, e in _registry.items() if e["shared"]]


def is_shared(scheme_id: str) -> bool:
    return bool(_registry.get(scheme_id, {}).get("shared", False))


def entry(scheme_id: str) -> dict | None:
    return _registry.get(scheme_id)


def snapshot() -> dict:
    return {sid: dict(e) for sid, e in _registry.items()}


# openspec/changes/multi-tenant-rls-scheme-scaleout: not a hard limit — a
# startup log warning once scheme count crosses this, pointing at the
# actual fix (schema-retrieval-reranking / sql-generation-vector-fewshot)
# rather than silently letting the risk grow unnoticed as schemes 5-25 get
# added one at a time. The number itself is a judgment call, not measured:
# app/schema_context.py's 912 lines of hand-curated per-scheme Python (the
# real growth risk this warns about) were written for 4 schemes; 10 is a
# round "well before 25" checkpoint to force a look, not a proven cliff.
SCHEME_COUNT_WARN_THRESHOLD = 10


def warn_if_scheme_count_high(threshold: int = SCHEME_COUNT_WARN_THRESHOLD) -> None:
    """Call once at startup, after load_all(). Logs (does not raise/block
    boot) once the registered non-shared scheme count crosses `threshold` —
    see openspec/changes/archive/2026-09-11-phase-3-schema-retrieval-join-discovery/proposal.md's
    own "headroom for scheme count to grow well past 4" note, which this
    makes an actual, visible signal instead of an assumption nobody
    re-checks."""
    n = len(scheme_ids(include_shared=False))
    if n > threshold:
        logger.warning(
            "scheme_registry: %d schemes registered (> %d) — "
            "app/schema_context.py's hand-curated per-scheme blocks and the "
            "per-role scheme literals in app/auth.py/prompt_builder.py/"
            "followups.py's regex dictionaries do not scale automatically; "
            "revisit openspec/changes/schema-retrieval-reranking and "
            "sql-generation-vector-fewshot before adding more schemes by hand.",
            n, threshold,
        )


async def sync_to_db(default_tenant_id: int | None = None) -> None:
    """openspec/changes/multi-tenant-rls-scheme-scaleout: upsert the
    in-memory registry (loaded by load_all() above) into app.schemes, the
    DB-backed source of truth app.tenant_schemes' entitlement checks and
    the curated-data RLS policies (deploy/sql/03_tenant_scheme_rls.sql)
    read. Onboarding scheme #5 through #25 is the same one call this makes
    on every registry reload (POST /api/rag/reload-scheme-registry) — no
    hand-written SQL per scheme.

    `default_tenant_id`, when given, seeds that tenant's grants with every
    currently-registered non-shared scheme, but ONLY the first time (when
    the tenant has zero grants) — this preserves today's single-tenant
    deployment's behavior unchanged when the flag is first turned on,
    without silently re-granting a scheme an admin deliberately revoked on
    a later restart/reload. Pass None (e.g. from the admin reload endpoint)
    to sync scheme identity only, without touching any tenant's grants."""
    from app import appdb  # local import: avoids a startup import cycle

    for scheme_id, entry_data in _registry.items():
        await appdb.upsert_scheme(scheme_id, entry_data["display_name"], entry_data["shared"])

    if default_tenant_id is None:
        return
    existing = await appdb.list_tenant_schemes(default_tenant_id)
    if existing:
        return
    for scheme_id in scheme_ids(include_shared=False):
        await appdb.grant_tenant_scheme(default_tenant_id, scheme_id)
    logger.info("scheme_registry: seeded tenant %s with %d scheme grant(s)",
                default_tenant_id, len(scheme_ids(include_shared=False)))
