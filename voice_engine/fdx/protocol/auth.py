"""How a WebSocket client presents its key, and TLS for the team gateway. One place, so the day AI ops say how their
gateway wants the key on `/ws/def/<model>/` routes it is one setting, not a code change.

  auth style            meaning
  header:<Name>         the key in header <Name> (Kyutai's own: header:kyutai-api-key)
  bearer                Authorization: Bearer <key>
  query:<name>          ?<name>=<key> on the URL (Kyutai also accepts query:auth_id)
  none / ''             no key

The team gateway (3 Nov, from its console): `wss://10.48.242.4/ws/def/<model>/...`, its per-model key in header `apikey`
(a browser uses `?apikey=`). Behind it Kyutai STT still checks its own `kyutai-api-key` (public_token), and PersonaPlex
needs a `voice_prompt` (NATF2.pt) and NO `seed` (the stock server crashes on both cases; core_fork fixes them).
  STT:  FDX_STT_URL, FDX_STT_API_KEY=public_token (server), FDX_STT_GATEWAY_KEY (+ FDX_STT_GATEWAY_AUTH, default header:apikey)
  core: FDX_CORE_URL, FDX_CORE_API_KEY, FDX_CORE_AUTH=header:apikey, FDX_VOICE_PROMPT=NATF2.pt

wss:// to the internal gateway uses a self-signed certificate: FDX_TLS_INSECURE=1 (default on) skips verification.
Keys are never logged; a URL that carries a key is never printed by this module."""
from __future__ import annotations

import os
import ssl
import urllib.parse


def ca_bundle() -> str:
    """The gateway's CA file when FDX_CA_BUNDLE names one that exists, else "" (14 Nov 2026: with it, certificate
    verification is ON for every gateway call, wss and https; one setting, no code)."""
    p = (os.environ.get("FDX_CA_BUNDLE") or "").strip()
    return p if p and os.path.isfile(p) else ""


def _insecure(flag_env: str = "FDX_TLS_INSECURE", default: str = "1") -> bool:
    return os.environ.get(flag_env, default).strip().lower() in ("1", "true", "yes", "on")


def httpx_verify(flag_env: str = "FDX_TLS_INSECURE", default: str = "1"):
    """What to pass as httpx `verify=`: the CA file when one is configured (verification on, whatever the insecure
    flag says), else True / False from the flag (`default` = the flag's value when unset)."""
    bundle = ca_bundle()
    if bundle:
        return bundle
    return not _insecure(flag_env, default)


def tls_context(url: str):
    if not url.startswith("wss://"):
        return None
    bundle = ca_bundle()
    if bundle:
        ctx = ssl.create_default_context(cafile=bundle)
        ctx.check_hostname = os.environ.get("FDX_TLS_CHECK_HOSTNAME", "1").strip().lower() not in ("0", "false", "no", "off")
        return ctx
    ctx = ssl.create_default_context()
    if _insecure():
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def apply(url: str, key: str, style: str) -> tuple[str, dict]:
    """(url, headers) with the key placed as `style` says."""
    style = (style or "").strip()
    if not key or style in ("", "none"):
        return url, {}
    if style == "bearer":
        return url, {"Authorization": f"Bearer {key}"}
    kind, _, name = style.partition(":")
    if kind == "header" and name:
        return url, {name: key}
    if kind == "query" and name:
        return url + ("&" if "?" in url else "?") + urllib.parse.urlencode({name: key}), {}
    raise ValueError(f"unknown auth style {style!r} (header:<Name> | bearer | query:<name> | none)")


def connect_kwargs(url: str, key: str, style: str, extra: list[tuple[str, str]] | None = None) -> tuple[str, dict]:
    """(url, extra websockets.connect kwargs). `extra` = more (key, style) pairs: the team gateway takes ITS key as header
    `apikey` while the server behind it still wants its own (Kyutai: kyutai-api-key public_token) (3 Nov)."""
    u, headers = apply(url, key, style)
    for k2, s2 in extra or []:
        u, h2 = apply(u, k2, s2)
        headers.update(h2)
    kw = {"additional_headers": headers}
    ctx = tls_context(u)
    if ctx is not None:
        kw["ssl"] = ctx
    return u, kw
