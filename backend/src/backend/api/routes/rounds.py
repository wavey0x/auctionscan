from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from backend.indexer.live_price import read_live_round_price

from ..cache_policy import NO_STORE, PERSISTED, set_cache_policy
from ..db import Database
from ..queries import load_as_of, occurrence_from_row
from ..models import RoundDetailResponse, RoundLivePrice, RoundsResponse
from ..pricing_sources import build_round_pricing_by_source
from ..queries import get_round_by_occurrence, list_round_pricing_sources, list_rounds
from ..serializers import checksum_address, decimal_string, round_list_item_from_row


router = APIRouter(tags=["rounds"])


def get_database(request: Request) -> Database:
    return request.app.state.db


@router.get("/rounds", response_model=RoundsResponse)
def get_rounds(
    response: Response,
    chain_id: int | None = Query(default=None),
    auction_address: str | None = Query(default=None),
    round_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    pair: str | None = Query(default=None),
    tx_hash: str | None = Query(default=None),
    time_window: str | None = Query(default=None),
    version: list[str] | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=15, ge=1, le=200),
    db: Database = Depends(get_database),
) -> RoundsResponse:
    set_cache_policy(response, PERSISTED)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            total, rows = list_rounds(
                conn,
                chain_id=chain_id,
                auction_address=auction_address,
                round_id=round_id,
                status=status,
                pair=pair,
                tx_hash=tx_hash,
                time_window=time_window,
                versions=version,
                page=page,
                limit=limit,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rounds = [round_list_item_from_row(row) for row in rows]
    return RoundsResponse(
        as_of=as_of,
        rounds=rounds,
        total=total,
        page=page,
        per_page=limit,
        has_next=(page * limit) < total,
    )


@router.get("/rounds/{chain_id}/{block_hash}/{tx_hash}/{log_index}", response_model=RoundDetailResponse)
def get_round_detail(
    chain_id: int,
    block_hash: str,
    tx_hash: str,
    log_index: int,
    response: Response,
    db: Database = Depends(get_database),
) -> RoundDetailResponse:
    set_cache_policy(response, NO_STORE)
    try:
        with db.connect() as conn:
            as_of = load_as_of(conn)
            row = get_round_by_occurrence(
                conn,
                chain_id=chain_id,
                block_hash=block_hash,
                tx_hash=tx_hash,
                log_index=log_index,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Round occurrence not found")
            source_rows = list_round_pricing_sources(
                conn,
                chain_id=chain_id,
                auction_address=row["auction_address"],
                round_id=row["round_id"],
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    pricing_by_source = build_round_pricing_by_source(row, source_rows)
    return RoundDetailResponse(as_of=as_of, round=round_list_item_from_row(row, pricing_by_source=pricing_by_source))


@router.get("/rounds/{chain_id}/{block_hash}/{tx_hash}/{log_index}/live-price", response_model=RoundLivePrice)
def get_round_live_price(
    chain_id: int,
    block_hash: str,
    tx_hash: str,
    log_index: int,
    response: Response,
    indexed_block: int = Query(..., ge=0),
    indexed_block_hash: str = Query(...),
    indexed_timestamp: int = Query(..., ge=0),
    db: Database = Depends(get_database),
) -> RoundLivePrice:
    set_cache_policy(response, NO_STORE)
    try:
        with db.connect() as conn:
            checkpoint = load_as_of(conn).get(chain_id)
            row = get_round_by_occurrence(
                conn,
                chain_id=chain_id,
                block_hash=block_hash,
                tx_hash=tx_hash,
                log_index=log_index,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Round occurrence not found")
            current = conn.execute(
                """SELECT r.round_id FROM rounds r
                   JOIN round_param_snapshot s ON s.chain_id=r.chain_id AND s.auction_address=r.auction_address AND s.round_id=r.round_id
                   WHERE r.chain_id=? AND r.auction_address=? AND r.from_token=?
                   ORDER BY r.snapshot_block DESC, s.snapshot_log_index DESC LIMIT 1""",
                (chain_id, row["auction_address"], row["from_token"]),
            ).fetchone()
            is_current = current is not None and current["round_id"] == row["round_id"]
            if checkpoint is None or any(checkpoint[key] is None for key in ("indexed_block", "indexed_block_hash", "indexed_timestamp")):
                raise HTTPException(status_code=503, detail="Indexed snapshot unavailable")
            if (indexed_block, indexed_block_hash.lower(), indexed_timestamp) != (checkpoint["indexed_block"], checkpoint["indexed_block_hash"], checkpoint["indexed_timestamp"]):
                raise HTTPException(status_code=409, detail={"code": "snapshot_mismatch"}, headers={"Cache-Control": NO_STORE})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    response_base = {
        "occurrence": occurrence_from_row(row, kick=True),
        "indexed_block": indexed_block,
        "indexed_block_hash": indexed_block_hash.lower(),
        "indexed_timestamp": indexed_timestamp,
        "chain_id": chain_id,
        "auction_address": checksum_address(row["auction_address"]),
        "round_id": int(row["round_id"]),
    }
    if str(row["status"]) != "live" or not is_current:
        return RoundLivePrice(
            **response_base,
            is_active=False,
        )

    chain_metadata = db.chain_catalog.get(chain_id)
    if chain_metadata is None:
        raise HTTPException(status_code=503, detail=f"Chain metadata unavailable for chain_id={chain_id}")
    if not row["version"] or not row["from_token"]:
        raise HTTPException(status_code=503, detail="Round is missing live pricing metadata")
    if row["want_token_decimals"] is None:
        raise HTTPException(status_code=503, detail="Round is missing want token decimals for live pricing")

    try:
        live_price = read_live_round_price(
            network_key=chain_metadata.network_key,
            version=str(row["version"]),
            auction_address=str(row["auction_address"]),
            from_token=str(row["from_token"]),
            want_token=str(row["want_token"]),
            block_hash=indexed_block_hash.lower(),
        )
    except Exception as exc:  # pragma: no cover - exercised via API error handling
        raise HTTPException(status_code=503, detail="Live price unavailable") from exc

    return RoundLivePrice(
        **response_base,
        is_active=live_price.is_active,
        current_price_raw=live_price.current_price_raw,
        current_price=decimal_string(live_price.current_price_raw, int(row["want_token_decimals"])),
    )
