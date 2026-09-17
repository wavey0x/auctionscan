from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..cache_policy import CHAINS, REFERENCE, set_cache_policy
from ..db import Database
from ..models import ChainInfo, ChainsResponse, TokenModel, TokensResponse
from ..queries import list_tokens
from ..serializers import checksum_address, token_logo_url


router = APIRouter(tags=["reference"])


def get_database(request: Request) -> Database:
    return request.app.state.db


@router.get("/chains", response_model=ChainsResponse)
def get_chains(response: Response, db: Database = Depends(get_database)) -> ChainsResponse:
    set_cache_policy(response, CHAINS)
    chains = {
        chain_id: ChainInfo(
            chain_id=chain_id,
            name=meta.name,
            short_name=meta.short_name,
            icon=meta.icon,
            explorer=meta.explorer,
            emoji=meta.emoji,
        )
        for chain_id, meta in sorted(db.chain_catalog.items())
        if not meta.disabled
    }
    return ChainsResponse(chains=chains, count=len(chains))


@router.get("/tokens", response_model=TokensResponse)
def get_tokens(
    response: Response,
    chain_id: int | None = Query(default=None),
    db: Database = Depends(get_database),
) -> TokensResponse:
    set_cache_policy(response, REFERENCE)
    try:
        with db.connect() as conn:
            rows = list_tokens(conn, chain_id=chain_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    tokens = [
        TokenModel(
            address=checksum_address(row["token_address"]) or row["token_address"],
            symbol=row["symbol"] or (checksum_address(row["token_address"]) or row["token_address"]),
            name=row["name"] or (checksum_address(row["token_address"]) or row["token_address"]),
            decimals=int(row["decimals"] or 0),
            chain_id=int(row["chain_id"]),
            logo_url=token_logo_url(int(row["chain_id"]), row["token_address"]),
        )
        for row in rows
    ]
    return TokensResponse(tokens=tokens, count=len(tokens))
