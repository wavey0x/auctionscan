from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from backend.indexer.types import normalize_address

from ..cache_policy import PERSISTED, set_cache_policy
from ..db import Database
from ..queries import load_as_of, occurrence_from_row, list_take_pricing_sources_for_keys
from ..models import TakerDetail, TakerListResponse, TakerSummary, TakerTake, TakerTakesResponse
from ..pricing_sources import build_take_pricing_maps
from ..taker_queries import get_taker_detail, list_taker_takes, list_takers
from ..serializers import checksum_address, decimal_string, float_value, iso_utc, quote_price


router = APIRouter(tags=["takers"])


def get_database(request: Request) -> Database:
    return request.app.state.db


@router.get("/takers", response_model=TakerListResponse)
def get_takers(
    response: Response,
    chain_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=15, ge=1, le=200),
    sort_by: str = Query(default="volume"),
    q: str | None = Query(default=None),
    db: Database = Depends(get_database),
) -> TakerListResponse:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            total, page_items = list_takers(
                conn,
                chain_id=chain_id,
                sort_by=sort_by,
                taker_query=q,
                page=page,
                limit=limit,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    payload = [
        TakerSummary(
            taker=checksum_address(item["taker"]) or item["taker"],
            total_takes=item["total_takes"],
            unique_auctions=item["unique_auctions"],
            unique_chains=item["unique_chains"],
            total_volume_usd=item["total_actual_paid_usd"],
        paid_usd_take_count=item["paid_usd_take_count"],
            avg_take_size_usd=(
                (item["total_actual_paid_usd"] / item["paid_usd_take_count"])
                if item["total_actual_paid_usd"] is not None and item["paid_usd_take_count"] > 0
                else None
            ),
            total_taker_profit_usd=item["total_taker_profit_usd"],
            avg_taker_profit_usd=item["avg_taker_profit_usd"],
            priced_take_count=item["priced_take_count"],
            priced_volume_share=item["priced_volume_share"],
            last_take=iso_utc(item["last_take"]),
            first_take=iso_utc(item["first_take"]),
            rank_by_takes=item["rank_by_takes"],
            rank_by_volume=item["rank_by_volume"],
            active_chains=item["active_chains"],
        )
        for item in page_items
    ]
    return TakerListResponse(
        as_of=as_of,
        takers=payload,
        total=total,
        page=page,
        per_page=limit,
        has_next=(page * limit) < total,
    )


@router.get("/takers/{taker_address}", response_model=TakerDetail | None)
def get_taker(
    taker_address: str,
    response: Response,
    db: Database = Depends(get_database),
) -> TakerDetail | None:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            item = get_taker_detail(conn, taker_address=taker_address)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if item is None:
        return None
    return TakerDetail(
        as_of=as_of,
        taker=checksum_address(item["taker"]) or item["taker"],
        total_takes=item["total_takes"],
        unique_auctions=item["unique_auctions"],
        unique_chains=item["unique_chains"],
        total_volume_usd=item["total_actual_paid_usd"],
        paid_usd_take_count=item["paid_usd_take_count"],
        avg_take_size_usd=(
            (item["total_actual_paid_usd"] / item["paid_usd_take_count"])
            if item["total_actual_paid_usd"] is not None and item["paid_usd_take_count"] > 0
            else None
        ),
        total_taker_profit_usd=item["total_taker_profit_usd"],
        avg_taker_profit_usd=item["avg_taker_profit_usd"],
        priced_take_count=item["priced_take_count"],
        priced_volume_share=item["priced_volume_share"],
        last_take=iso_utc(item["last_take"]),
        first_take=iso_utc(item["first_take"]),
        rank_by_takes=item["rank_by_takes"],
        rank_by_volume=item["rank_by_volume"],
        active_chains=item["active_chains"],
        auction_breakdown=[
                {
                    "auction_address": checksum_address(row["auction_address"]) or row["auction_address"],
                    "chain_id": row["chain_id"],
                    "takes_count": row["takes_count"],
                    "paid_usd_take_count": row["paid_usd_take_count"],
                    "priced_take_count": row["priced_take_count"],
                    "volume_usd": row["volume_usd"],
                    "taker_profit_usd": row["taker_profit_usd"],
                    "last_take": iso_utc(row["last_take"]),
                    "first_take": iso_utc(row["first_take"]),
                }
            for row in item["auction_breakdown"]
        ],
    )


@router.get("/takers/{taker_address}/takes", response_model=TakerTakesResponse)
def get_taker_takes(
    taker_address: str,
    response: Response,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=15, ge=1, le=200),
    db: Database = Depends(get_database),
) -> TakerTakesResponse:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            total_count, rows = list_taker_takes(
                conn,
                taker_address=taker_address,
                page=page,
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
    takes = []
    for row in rows:
        from_decimals = int(row["from_token_decimals"]) if row["from_token_decimals"] is not None else None
        want_decimals = int(row["want_token_decimals"]) if row["want_token_decimals"] is not None else None
        paid_raw = row["amount_paid_raw"]
        takes.append(
            TakerTake(
                occurrence=occurrence_from_row(row),
                round_occurrence=occurrence_from_row(row, kick=True),
                chain_id=int(row["chain_id"]),
                auction_address=checksum_address(row["auction_address"]) or row["auction_address"],
                round_id=int(row["round_id"]),
                take_seq=int(row["take_seq"]),
                taker=checksum_address(row["taker"]) or row["taker"],
                timestamp=iso_utc(row["timestamp"]) or "",
                tx_hash=str(row["tx_hash"]).lower(),
                amount_taken=decimal_string(row["amount_taken_raw"], from_decimals),
                amount_paid=decimal_string(paid_raw, want_decimals),
                expected_amount_paid=decimal_string(row["expected_amount_paid_raw"], want_decimals),
                price=quote_price(
                    paid_raw=paid_raw,
                    sold_raw=row["amount_taken_raw"],
                    from_decimals=from_decimals,
                    want_decimals=want_decimals,
                ),
                price_usd=float_value(row["want_token_price_usd"]),
                taker_profit_usd=(
                    -float(row["auction_profit_usd"])
                    if row["auction_profit_usd"] is not None
                    else None
                ),
                pricing_status=row["pricing_status"],
                pricing_by_source=take_pricing_maps.get(
                    (int(row["chain_id"]), normalize_address(str(row["auction_address"])), int(row["round_id"]), int(row["take_seq"]))
                ),
            )
        )

    total_pages = 0 if total_count == 0 else ((total_count + limit - 1) // limit)
    return TakerTakesResponse(
        as_of=as_of,
        takes=takes,
        total_count=total_count,
        page=page,
        limit=limit,
        total_pages=total_pages,
        available_price_sources=options,
    )
