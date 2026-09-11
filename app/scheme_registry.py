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
