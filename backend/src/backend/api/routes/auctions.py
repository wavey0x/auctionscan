from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from backend.indexer.types import normalize_address

from ..cache_policy import PERSISTED, REFERENCE, set_cache_policy
from ..db import Database
from ..queries import load_as_of, get_round_by_occurrence
from ..models import (
    AuctionActivity,
    AuctionDetails,
    AuctionParameters,
    AuctionTakesResponse,
    AuctionVersionOption,
    AuctionVersionsResponse,
    AuctionsResponse,
    TokenModel,
)
from ..pricing_sources import build_take_pricing_maps
from ..queries import (
    get_auction,
    get_auction_activity,
    list_auction_from_tokens,
    list_auction_takes,
    list_auction_versions,
    list_auctions,
    list_take_pricing_sources_for_keys,
)
from ..serializers import (
    auction_list_item_from_row,
    checksum_address,
    decimal_string,
    decimal_text_value,
    percent_text_value,
    take_list_item_from_row,
    token_logo_url,
    token_payload,
)


router = APIRouter(tags=["auctions"])


def get_database(request: Request) -> Database:
    return request.app.state.db


@router.get("/auction-versions", response_model=AuctionVersionsResponse)
def get_auction_versions(
    response: Response,
    chain_id: int | None = Query(default=None),
    db: Database = Depends(get_database),
) -> AuctionVersionsResponse:
    set_cache_policy(response, REFERENCE)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            rows = list_auction_versions(conn, chain_id=chain_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    versions = [
        AuctionVersionOption(
            version=row["version"],
            auction_count=int(row["auction_count"]),
            round_count=int(row["round_count"]),
        )
        for row in rows
    ]
    return AuctionVersionsResponse(as_of=as_of, versions=versions, count=len(versions))


@router.get("/auctions", response_model=AuctionsResponse)
def get_auctions(
    response: Response,
    chain_id: int | None = Query(default=None),
    version: list[str] | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Database = Depends(get_database),
) -> AuctionsResponse:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            total, rows = list_auctions(
                conn,
                chain_id=chain_id,
                versions=version,
                page=page,
                limit=limit,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AuctionsResponse(
        as_of=as_of,
        auctions=[auction_list_item_from_row(row) for row in rows],
        total=total,
        page=page,
        per_page=limit,
        has_next=(page * limit) < total,
    )


@router.get("/auctions/{auction_address}", response_model=AuctionDetails | None)
def get_auction_detail(
    auction_address: str,
    response: Response,
    chain_id: int = Query(...),
    db: Database = Depends(get_database),
) -> AuctionDetails | None:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            row = get_auction(conn, chain_id=chain_id, auction_address=auction_address)
            if row is None:
                return None
            from_token_rows = list_auction_from_tokens(conn, chain_id=chain_id, auction_address=auction_address)
            activity = get_auction_activity(conn, chain_id=chain_id, auction_address=auction_address)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    want_token = token_payload(
        chain_id=chain_id,
        address=row["want_token"],
        symbol=row["want_token_symbol"],
        name=row["want_token_name"],
        decimals=row["want_token_decimals"],
    )
    if want_token is None:
        placeholder = checksum_address(row["want_token"]) or "0x0000000000000000000000000000000000000000"
        want_token = TokenModel(
            address=placeholder,
            symbol=placeholder,
            name=placeholder,
            decimals=0,
            chain_id=chain_id,
            logo_url=token_logo_url(chain_id, placeholder),
        )
    from_tokens = [
        token_payload(
            chain_id=chain_id,
            address=item["token_address"],
            symbol=item["symbol"],
            name=item["name"],
            decimals=item["decimals"],
        )
        for item in from_token_rows
    ]
    return AuctionDetails(
        as_of=as_of,
        address=checksum_address(row["auction_address"]) or row["auction_address"],
        chain_id=chain_id,
        receiver=checksum_address(row["current_receiver"] or row["receiver"]),
        receiver_name=row["receiver_name"],
        version=row["version"],
        from_tokens=[item for item in from_tokens if item is not None],
        want_token=want_token,
        parameters=AuctionParameters(
            update_interval=int(row["step_duration_seconds"]) if row["step_duration_seconds"] is not None else None,
            decay_percent=percent_text_value(row["step_decay_percent"]),
            auction_length=int(row["auction_length_seconds"]) if row["auction_length_seconds"] is not None else None,
            starting_price=decimal_text_value(row["starting_price"]),
            minimum_price=decimal_text_value(row["minimum_price"]),
        ),
        activity=AuctionActivity(
            total_participants=activity["total_participants"],
            total_volume=decimal_string(activity["total_paid_raw"], row["want_token_decimals"]),
            paid_take_count=activity["paid_take_count"],
            total_rounds=activity["total_rounds"],
            total_takes=activity["total_takes"],
        ),
    )


@router.get("/auctions/{auction_address}/takes", response_model=AuctionTakesResponse)
def get_auction_takes(
    auction_address: str,
    response: Response,
    chain_id: int = Query(...),
    kick_block_hash: str | None = Query(default=None),
    kick_tx_hash: str | None = Query(default=None),
    kick_log_index: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    db: Database = Depends(get_database),
) -> AuctionTakesResponse:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            round_id = None
            if any(value is not None for value in (kick_block_hash, kick_tx_hash, kick_log_index)):
                if kick_block_hash is None or kick_tx_hash is None or kick_log_index is None:
                    raise HTTPException(status_code=422, detail="Complete kick occurrence required")
                round_row = get_round_by_occurrence(conn, chain_id=chain_id, block_hash=kick_block_hash, tx_hash=kick_tx_hash, log_index=kick_log_index)
                if round_row is None or round_row["auction_address"] != normalize_address(auction_address):
                    raise HTTPException(status_code=404, detail="Round occurrence not found")
                round_id = int(round_row["round_id"])
            rows = list_auction_takes(
                conn,
                chain_id=chain_id,
                auction_address=auction_address,
                round_id=round_id,
                limit=limit,
            )
            take_keys = [
                (int(item["chain_id"]), str(item["auction_address"]), int(item["round_id"]), int(item["take_seq"]))
                for item in rows
            ]
            source_rows = list_take_pricing_sources_for_keys(conn, take_keys=take_keys)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    take_pricing_maps, options = build_take_pricing_maps(rows, source_rows)
    return AuctionTakesResponse(
        as_of=as_of,
        takes=[
            take_list_item_from_row(
                row,
                pricing_by_source=take_pricing_maps.get(
                    (int(row["chain_id"]), normalize_address(str(row["auction_address"])), int(row["round_id"]), int(row["take_seq"]))
                ),
            )
            for row in rows
        ],
        available_price_sources=options,
    )
