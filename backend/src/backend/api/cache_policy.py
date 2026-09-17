from __future__ import annotations

from typing import Final

from fastapi import Response


NO_STORE: Final = "no-store"
CHAINS: Final = "public, max-age=3600"
REFERENCE: Final = "public, max-age=300, stale-while-revalidate=600"
PERSISTED: Final = "public, max-age=2"


def set_cache_policy(response: Response, policy: str) -> None:
    response.headers["Cache-Control"] = policy
