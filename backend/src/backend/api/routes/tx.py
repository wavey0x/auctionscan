from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..cache_policy import PERSISTED, set_cache_policy
from ..db import Database
from ..models import TxResolveDestination, TxResolveResponse
from ..queries import resolve_transaction
from ..serializers import checksum_address


router = APIRouter(tags=["tx"])


def get_database(request: Request) -> Database:
    return request.app.state.db


@router.get("/tx/{tx_hash}/resolve", response_model=TxResolveResponse)
def resolve_tx(
    tx_hash: str,
    response: Response,
    chain_id: int | None = Query(default=None),
    block_hash: str | None = Query(default=None),
    log_index: int | None = Query(default=None, ge=0),
    db: Database = Depends(get_database),
) -> TxResolveResponse:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            payload = resolve_transaction(conn, tx_hash=tx_hash, chain_id=chain_id, block_hash=block_hash, log_index=log_index)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    destination_payload = payload.get("destination")
    destination = (
        TxResolveDestination(
            occurrence=destination_payload.get("occurrence"),
            take_occurrence=destination_payload.get("take_occurrence"),
            kind=str(destination_payload["kind"]),
            chain_id=int(destination_payload["chain_id"]),
            auction_address=(
                checksum_address(str(destination_payload["auction_address"]))
                or str(destination_payload["auction_address"])
            ),
            round_id=(
                int(destination_payload["round_id"])
                if destination_payload.get("round_id") is not None
                else None
            ),
        )
        if destination_payload is not None
        else None
    )
    return TxResolveResponse(
        normalized_tx_hash=payload.get("normalized_tx_hash"),
        outcome=str(payload["outcome"]),
        kind=str(payload["kind"]) if payload.get("kind") is not None else None,
        destination=destination,
    )
