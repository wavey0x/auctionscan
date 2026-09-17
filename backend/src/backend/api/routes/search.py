from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..cache_policy import PERSISTED, set_cache_policy
from ..db import Database
from ..models import SearchResponse, SearchResult
from ..queries import search_index
from ..serializers import checksum_address, token_logo_url


router = APIRouter(tags=["search"])


def get_database(request: Request) -> Database:
    return request.app.state.db


@router.get("/search", response_model=SearchResponse)
def search(
    response: Response,
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_database),
) -> SearchResponse:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            rows = search_index(conn, query=q, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    results = [
        SearchResult(
            type=item["type"],
            chain_id=item["chain_id"],
            address_or_hash=(
                checksum_address(item["address_or_hash"])
                if item["type"] in {"auction", "taker", "token"}
                else str(item["address_or_hash"]).lower()
            )
            or item["address_or_hash"],
            metadata={
                key: (
                    checksum_address(value)
                    if key.endswith("address") and isinstance(value, str)
                    else value
                )
                for key, value in (item.get("metadata") or {}).items()
            }
            | (
                {
                    "logo_url": token_logo_url(
                        int(item["chain_id"]),
                        str(item["address_or_hash"]),
                    )
                }
                if item["type"] == "token"
                else {}
            )
            or None,
        )
        for item in rows
    ]
    return SearchResponse(results=results, total=len(results), query=q)
