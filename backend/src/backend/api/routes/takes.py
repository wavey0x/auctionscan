from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.indexer.types import normalize_address

from ..cache_policy import NO_STORE, set_cache_policy
from ..db import Database
from ..models import TakeDetail
from ..queries import (
    get_take_by_occurrence,
    list_take_pricing_sources_for_keys,
    list_take_price_facts,
    list_take_price_provider_facts,
    list_take_quote_facts,
    list_take_quote_provider_facts,
)
from ..serializers import take_detail_from_row
from ..pricing_sources import build_take_pricing_maps


router = APIRouter(tags=["takes"])


def get_database(request: Request) -> Database:
    return request.app.state.db


@router.get("/takes/{chain_id}/{block_hash}/{tx_hash}/{log_index}", response_model=TakeDetail)
def get_take_detail(
    chain_id: int,
    block_hash: str,
    tx_hash: str,
    log_index: int,
    response: Response,
    db: Database = Depends(get_database),
) -> TakeDetail:
    set_cache_policy(response, NO_STORE)
    try:
        with db.connect() as conn:
            row = get_take_by_occurrence(
                conn,
                chain_id=chain_id,
                block_hash=block_hash,
                tx_hash=tx_hash,
                log_index=log_index,
            )
            if row is not None:
                auction_address, round_id, take_seq = row["auction_address"], row["round_id"], row["take_seq"]
                quote_fact_rows = list_take_quote_facts(
                    conn,
                    chain_id=chain_id,
                    auction_address=auction_address,
                    round_id=round_id,
                    take_seq=take_seq,
                )
                quote_provider_rows = list_take_quote_provider_facts(
                    conn,
                    quote_fact_ids=[int(item["id"]) for item in quote_fact_rows],
                )
                price_fact_rows = list_take_price_facts(
                    conn,
                    chain_id=chain_id,
                    auction_address=auction_address,
                    round_id=round_id,
                    take_seq=take_seq,
                )
                price_provider_rows = list_take_price_provider_facts(
                    conn,
                    price_fact_ids=[int(item["id"]) for item in price_fact_rows],
                )
                source_rows = list_take_pricing_sources_for_keys(
                    conn,
                    take_keys=[(chain_id, auction_address, round_id, take_seq)],
                )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Take occurrence not found")
    take_pricing_maps, _options = build_take_pricing_maps([row], source_rows)
    take_key = (int(row["chain_id"]), normalize_address(str(row["auction_address"])), int(row["round_id"]), int(row["take_seq"]))
    return take_detail_from_row(
        row,
        quote_fact_rows=quote_fact_rows,
        quote_provider_rows=quote_provider_rows,
        price_fact_rows=price_fact_rows,
        price_provider_rows=price_provider_rows,
        pricing_by_source=take_pricing_maps.get(take_key),
    )
