from __future__ import annotations

import time
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..cache_policy import NO_STORE, set_cache_policy
from ..db import Database
from ..models import DiscoveryStatus, HealthChain, HealthResponse
from ..queries import load_sync_state
from ..serializers import checksum_address


router = APIRouter(tags=["health"])


SUCCESS_MAX_AGE_SECONDS = 60
HEAD_MAX_AGE_SECONDS = 90
FINALITY_MAX_AGE_SECONDS = 1800
DISCOVERY_MAX_AGE_SECONDS = 600
INDEXER_ERROR_MESSAGE = "Indexer sync failed; check server logs"


def discovery_status(row, *, now: int) -> DiscoveryStatus:
    saved = json.loads(row["discovery_status_json"]) if row and row["discovery_status_json"] else {}
    count = saved.get("known_factory_count", 0)
    success = saved.get("last_success_at")
    problems = [{**problem, "factory_address": checksum_address(problem["factory_address"])}
                for problem in saved.get("problems", [])]
    status = "ok"
    if count == 0:
        status = "unavailable"
    elif saved.get("last_error") or problems:
        status = "partial"
    elif success is None or now - success > DISCOVERY_MAX_AGE_SECONDS:
        status = "stale"
    return DiscoveryStatus(status=status, known_factory_count=count, problems=problems,
                           last_attempt_at=saved.get("last_attempt_at"), last_success_at=success,
                           last_error=saved.get("last_error"))


def chain_health(row, *, now: int) -> tuple[str, str | None, str | None]:
    if row is None:
        return "unknown", "Waiting for indexing to start", None
    warning = row["finality_warning"]
    if (row["finality_mode"] == "finalized" and row["confirmed_head_timestamp"] is not None
            and now - int(row["confirmed_head_timestamp"]) > FINALITY_MAX_AGE_SECONDS):
        warning = warning or "Finality has stopped advancing"
    if row["last_error"] or row["health"] == "error":
        # Transport exceptions may contain authenticated URLs. Full diagnostics
        # remain in private indexer logs and must not enter the public response.
        return "error", INDEXER_ERROR_MESSAGE, warning
    if row["last_success_at"] is None or now - int(row["last_success_at"]) > SUCCESS_MAX_AGE_SECONDS:
        return "stale", "Indexer has not completed a recent sync", warning
    if row["latest_rpc_head_timestamp"] is None:
        return "stale", "No verified node head timestamp", warning
    if now - int(row["latest_rpc_head_timestamp"]) > HEAD_MAX_AGE_SECONDS:
        return "stale", "Node is serving an old chain head", warning
    if warning:
        return "degraded", warning, warning
    if row["last_live_processed"] is not None and row["latest_rpc_head"] is not None and int(row["last_live_processed"]) < int(row["latest_rpc_head"]):
        return "indexing", "Catching up to the chain head", None
    return "ok", None, None


def get_database(request: Request) -> Database:
    return request.app.state.db


@router.get("/health", response_model=HealthResponse)
def get_health(response: Response, db: Database = Depends(get_database)) -> HealthResponse:
    set_cache_policy(response, NO_STORE)
    try:
        with db.connect() as conn:
            rows = {int(row["chain_id"]): row for row in load_sync_state(conn)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = []
    now = int(time.time())
    for chain_id, meta in sorted(db.chain_catalog.items()):
        if meta.disabled:
            continue
        row = rows.get(chain_id)
        confirmed_head = int(row["confirmed_head"]) if row and row["confirmed_head"] is not None else None
        last_confirmed_processed = int(row["last_confirmed_processed"]) if row and row["last_confirmed_processed"] is not None else None
        block_lag = None
        if row and row["latest_rpc_head"] is not None and row["last_live_processed"] is not None:
            block_lag = max(0, int(row["latest_rpc_head"]) - int(row["last_live_processed"]))
        health, detail, warning = chain_health(row, now=now)
        payload.append(
            HealthChain(
                chain_id=chain_id,
                network_name=meta.network_key,
                name=meta.name,
                short_name=meta.short_name,
                start_block=meta.start_block,
                latest_rpc_head=int(row["latest_rpc_head"]) if row and row["latest_rpc_head"] is not None else None,
                confirmed_head=confirmed_head,
                last_confirmed_processed=last_confirmed_processed,
                last_live_processed=(
                    int(row["last_live_processed"])
                    if row and row["last_live_processed"] is not None
                    else None
                ),
                block_lag=block_lag,
                reorg_count=int(row["reorg_count"]) if row and row["reorg_count"] is not None else 0,
                last_reorg_at=int(row["last_reorg_at"]) if row and row["last_reorg_at"] is not None else None,
                health=health,
                health_detail=detail,
                finality_warning=warning,
                **{key: row[key] if row else None for key in (
                    "last_success_at", "latest_rpc_head_timestamp", "finality_mode", "confirmed_head_hash",
                    "confirmed_head_timestamp", "last_confirmed_hash", "last_finality_advance_at",
                )},
                last_error=INDEXER_ERROR_MESSAGE if row and row["last_error"] else None,
                indexed=row is not None,
                discovery=discovery_status(row, now=now),
            )
        )
    return HealthResponse(chains=payload, count=len(payload))
