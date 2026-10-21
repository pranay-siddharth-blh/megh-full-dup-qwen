"""Mint a short-lived JWT for a seeded user with the app's own security module,
so the headless UI check (chat_flow.py) can sign in without a password (the
seed passwords are rotated; KI-023). Run from the repo root with the venv so
.env loads; the token is written to the given file and never printed.

    .venv/Scripts/python.exe tests/ui_headless/mint_token.py state-rd tests/ui_headless/token.txt
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import appdb, security  # noqa: E402


async def main(username: str, out: Path) -> None:
    rec = await appdb.get_user_by_username(username)
    if not rec or not rec.get("is_active"):
        raise SystemExit(f"{username}: not found or inactive")
    out.write_text(security.issue_token({"sub": str(rec["user_id"]), "username": rec["username"],
                                         "tenant_id": rec["tenant_id"], "role": rec["role"]},
                                        ttl_minutes=120), encoding="utf-8")
    print("token written for", rec["username"], "role", rec["role"])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], Path(sys.argv[2])))
