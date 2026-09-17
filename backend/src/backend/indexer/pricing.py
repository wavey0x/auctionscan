from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

import json
import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any
from urllib import error, parse, request

from .prices_api import (
    DEFAULT_PRICES_API_BASE_URL,
    PricesApiAuthError,
    PricesApiError,
    PricesApiRateLimitError,
)
from .types import PreparedEvent, decimal_text
from .pricing_summary import QuoteSelection, PriceSelection, summarize_quote, summarize_price


logger = logging.getLogger(__name__)

DEFAULT_MAX_CAPTURE_LAG_SECONDS = 600
DEFAULT_TIMEOUT_MS = 7000
DEFAULT_RETRY_SECONDS = 60
DEFAULT_PROVIDER_CACHE_TTL_SECONDS = 60


def _now() -> int:
    return int(time.time())


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _json_dumps_or_none(payload: Any) -> str | None:
    if payload is None:
        return None
    return _json_dumps(payload)


def _extract_detail_message(body: str) -> str | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or None
    detail = payload.get("detail")
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return None


def _provider_error_type(error_payload: dict[str, Any] | None) -> str | None:
    if error_payload is None:
        return None
    raw_value = error_payload.get("type")
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return text or None


def _decimal_from_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _raw_to_units(raw_value: str | None, decimals: int | None) -> Decimal | None:
    if raw_value is None or decimals is None:
        return None
    raw = _decimal_from_value(raw_value)
    if raw is None:
        return None
    with localcontext() as context:
        context.prec = 80
        return raw / (Decimal(10) ** int(decimals or 0))


def _usd_value(raw_value: str | None, decimals: int | None, price_usd: str | None) -> str | None:
    units = _raw_to_units(raw_value, decimals)
    price = _decimal_from_value(price_usd)
    if units is None or price is None:
        return None
    with localcontext() as context:
        context.prec = 80
        return _decimal_to_text(units * price)


def _ratio_text(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        return _decimal_to_text(Decimal(numerator) / Decimal(denominator))


def _decimal_ratio_text(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        return _decimal_to_text(numerator / denominator)


def _bps_from_raws(actual_raw: str | None, benchmark_raw: str | None) -> int | None:
    actual = _decimal_from_value(actual_raw)
    benchmark = _decimal_from_value(benchmark_raw)
    if actual is None or benchmark is None or benchmark <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        bps = ((actual / benchmark) - Decimal(1)) * Decimal(10_000)
    return int(bps.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _coalesce_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


@dataclass(frozen=True)
class ProviderCapability:
    id: str
    supports_price: bool
    supports_quote: bool
    supported_chains: tuple[int, ...]
    requires_api_key: bool
    available: bool
    unavailable_reason: str | None


@dataclass(frozen=True)
class PricingQueueJob:
    id: int
    chain_id: int
    auction_address: str
    round_id: int
    take_seq: int | None
    entity_kind: str
    event_timestamp: int
    from_token: str | None
    to_token: str | None
    token: str | None
    amount_in_raw: str | None
    source_tx_hash: str | None
    source_log_index: int | None
    source_event_name: str | None
    source_block_number: int | None
    source_block_hash: str | None
    status: str
    attempt_count: int
    next_attempt_at: int | None
    last_error: str | None
    priority: int
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class SelectedPricingJob:
    job: PricingQueueJob
    source_exists: bool


@dataclass(frozen=True)
class PricingAttemptResult:
    job: PricingQueueJob
    fact_kind: str | None
    provider_scope: tuple[ProviderCapability, ...]
    capture_state: str | None
    captured_at: int | None
    payload_json: str | None
    aggregate_error_json: str | None
    queue_action: str
    last_error: str | None
    next_attempt_at: int | None


@dataclass(frozen=True)
class PricingDrainSummary:
    facts_written: int
    retries: int
    terminal_deletions: int
    projection_rows: int
    rebuild_seconds: float


class PricingApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("PRICES_API_BASE_URL") or DEFAULT_PRICES_API_BASE_URL).rstrip("/")
        self.api_key = (api_key if api_key is not None else os.environ.get("PRICES_API_KEY", "")).strip()
        self.timeout_seconds = timeout_seconds
        self._providers_cache: list[ProviderCapability] | None = None
        self._providers_cache_expires_at: float | None = None

    def fetch_providers(self) -> list[ProviderCapability]:
        now = time.monotonic()
        if (
            self._providers_cache is None
            or self._providers_cache_expires_at is None
            or now >= self._providers_cache_expires_at
        ):
            payload = self._request_json("/v1/providers")
            providers = payload.get("providers")
            if not isinstance(providers, list):
                raise PricesApiError("prices API providers response was malformed")
            self._providers_cache = [
                ProviderCapability(
                    id=str(item["id"]),
                    supports_price=bool(item.get("supports_price")),
                    supports_quote=bool(item.get("supports_quote")),
                    supported_chains=tuple(int(chain_id) for chain_id in item.get("supported_chains") or ()),
                    requires_api_key=bool(item.get("requires_api_key")),
                    available=bool(item.get("available", True)),
                    unavailable_reason=(
                        str(item["unavailable_reason"]).strip()
                        if item.get("unavailable_reason")
                        else None
                    ),
                )
                for item in providers
                if isinstance(item, dict) and item.get("id")
            ]
            self._providers_cache_expires_at = time.monotonic() + DEFAULT_PROVIDER_CACHE_TTL_SECONDS
        return list(self._providers_cache)

    def supported_providers(self, *, chain_id: int, kind: str) -> list[ProviderCapability]:
        providers = []
        for item in self.fetch_providers():
            if chain_id not in item.supported_chains:
                continue
            if kind == "quote" and not item.supports_quote:
                continue
            if kind == "price" and not item.supports_price:
                continue
            providers.append(item)
        return providers

    def fetch_quote(
        self,
        *,
        chain_id: int,
        token_in: str,
        token_out: str,
        amount_in: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict[str, Any]:
        query = parse.urlencode(
            {
                "chain_id": chain_id,
                "token_in": token_in,
                "token_out": token_out,
                "amount_in": amount_in,
                "providers": providers,
                "include_route": True,
                "use_underlying": use_underlying,
                "timeout_ms": timeout_ms,
            },
            doseq=True,
        )
        return self._request_json(f"/v1/quote?{query}")

    def fetch_price(
        self,
        *,
        chain_id: int,
        token: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict[str, Any]:
        query = parse.urlencode(
            {
                "chain_id": chain_id,
                "token": token,
                "providers": providers,
                "use_underlying": use_underlying,
                "timeout_ms": timeout_ms,
            },
            doseq=True,
        )
        return self._request_json(f"/v1/price?{query}")

    def _request_json(self, path: str) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "auctionscan/pricing",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        req = request.Request(f"{self.base_url}{path}", headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            if exc.code in {401, 403}:
                raise PricesApiAuthError(
                    f"prices API authentication failed ({exc.code})"
                ) from exc
            if exc.code == 429:
                raise PricesApiRateLimitError("prices API rate limit exceeded") from exc
            raise PricesApiError(
                f"prices API request failed ({exc.code}): {_extract_detail_message(body) or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise PricesApiError(f"prices API request failed: {exc.reason}") from exc

        if not isinstance(payload, dict):
            raise PricesApiError("prices API returned a non-object JSON payload")
        return payload


def _queue_job_from_row(row) -> PricingQueueJob:
    return PricingQueueJob(
        id=int(row["id"]),
        chain_id=int(row["chain_id"]),
        auction_address=str(row["auction_address"]),
        round_id=int(row["round_id"]),
        take_seq=int(row["take_seq"]) if row["take_seq"] is not None else None,
        entity_kind=str(row["entity_kind"]),
        event_timestamp=int(row["event_timestamp"]),
        from_token=row["from_token"],
        to_token=row["to_token"],
        token=row["token"],
        amount_in_raw=row["amount_in_raw"],
        source_tx_hash=row["source_tx_hash"],
        source_log_index=int(row["source_log_index"]) if row["source_log_index"] is not None else None,
        source_event_name=row["source_event_name"],
        source_block_number=int(row["source_block_number"]) if row["source_block_number"] is not None else None,
        source_block_hash=row["source_block_hash"],
        status=str(row["status"]),
        attempt_count=int(row["attempt_count"]),
        next_attempt_at=int(row["next_attempt_at"]) if row["next_attempt_at"] is not None else None,
        last_error=row["last_error"],
        priority=int(row["priority"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
    )


def _lookup_take_identity(conn, prepared: PreparedEvent) -> tuple[int, int] | None:
    event = prepared.domain_event
    row = conn.execute(
        """
        SELECT round_id, take_seq
          FROM takes
         WHERE chain_id = ? AND tx_hash = ? AND log_index = ?
        """,
        (event.chain_id, event.tx_hash, event.log_index),
    ).fetchone()
    if row is None:
        return None
    return int(row["round_id"]), int(row["take_seq"])


def _lookup_kick_pricing_context(
    conn,
    prepared: PreparedEvent,
) -> tuple[int | None, str | None]:
    event = prepared.domain_event
    round_id = event.payload.get("roundId")
    if round_id is not None:
        row = conn.execute(
            """
            SELECT want_token
              FROM rounds
             WHERE chain_id = ? AND auction_address = ? AND round_id = ?
            """,
            (event.chain_id, event.auction_address, int(round_id)),
        ).fetchone()
        want_token = row["want_token"] if row is not None else None
        return int(round_id), want_token

    row = conn.execute(
        """
        SELECT round_id, want_token
          FROM round_param_snapshot
         WHERE chain_id = ? AND snapshot_tx_hash = ? AND snapshot_log_index = ?
        """,
        (event.chain_id, event.tx_hash, event.log_index),
    ).fetchone()
    if row is None:
        return None, None
    return int(row["round_id"]), row["want_token"]


def enqueue_pricing_work(conn, prepared_events: list[PreparedEvent]) -> int:
    rows: list[tuple[Any, ...]] = []
    now = _now()
    for prepared in prepared_events:
        event = prepared.domain_event
        if event.event_name == "AuctionKicked":
            round_id, looked_up_want_token = _lookup_kick_pricing_context(conn, prepared)
            from_token = event.payload.get("from")
            want_token = prepared.snapshot.want_token if prepared.snapshot else looked_up_want_token
            amount_in_raw = decimal_text(event.payload.get("available"))
            if round_id is None or not from_token or not want_token or not amount_in_raw:
                continue
            rows.append(
                (
                    event.chain_id,
                    event.auction_address,
                    round_id,
                    None,
                    "round_kick_quote",
                    event.timestamp,
                    from_token,
                    want_token,
                    None,
                    amount_in_raw,
                    event.tx_hash,
                    event.log_index,
                    event.event_name,
                    event.block_number,
                    event.block_hash,
                    "pending",
                    0,
                    now,
                    None,
                    100,
                    now,
                    now,
                )
            )
            if want_token:
                rows.append(
                    (
                        event.chain_id,
                        event.auction_address,
                        round_id,
                        None,
                        "want_token_price",
                        event.timestamp,
                        None,
                        None,
                        want_token,
                        None,
                        event.tx_hash,
                        event.log_index,
                        event.event_name,
                        event.block_number,
                        event.block_hash,
                        "pending",
                        0,
                        now,
                        None,
                        90,
                        now,
                        now,
                    )
                )
        elif event.event_name == "Take":
            identity = _lookup_take_identity(conn, prepared)
            if identity is None:
                continue
            round_id, take_seq = identity
            want_token = event.payload.get("to")
            amount_in_raw = decimal_text(event.payload.get("amountTaken"))
            if event.payload.get("from") and want_token and amount_in_raw:
                rows.append(
                    (
                        event.chain_id,
                        event.auction_address,
                        round_id,
                        take_seq,
                        "take_quote",
                        event.timestamp,
                        event.payload.get("from"),
                        want_token,
                        None,
                        amount_in_raw,
                        event.tx_hash,
                        event.log_index,
                        event.event_name,
                        event.block_number,
                        event.block_hash,
                        "pending",
                        0,
                        now,
                        None,
                        200,
                        now,
                        now,
                    )
                )
            if want_token:
                rows.append(
                    (
                        event.chain_id,
                        event.auction_address,
                        round_id,
                        take_seq,
                        "want_token_price",
                        event.timestamp,
                        None,
                        None,
                        want_token,
                        None,
                        event.tx_hash,
                        event.log_index,
                        event.event_name,
                        event.block_number,
                        event.block_hash,
                        "pending",
                        0,
                        now,
                        None,
                        190,
                        now,
                        now,
                    )
                )
    if not rows:
        return 0
    before_total_changes = conn.total_changes
    conn.executemany(
        """
        INSERT INTO pricing_capture_queue (
            chain_id, auction_address, round_id, take_seq, entity_kind, event_timestamp,
            from_token, to_token, token, amount_in_raw,
            source_tx_hash, source_log_index, source_event_name, source_block_number, source_block_hash,
            status, attempt_count,
            next_attempt_at, last_error, priority, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chain_id, source_block_hash, source_tx_hash, source_log_index, entity_kind) DO NOTHING
        """,
        rows,
    )
    return int(conn.total_changes - before_total_changes)


def _source_round(conn, *, chain_id: int, block_hash: str, tx_hash: str, log_index: int,
                  event_name: str) -> tuple[str, int] | None:
    if not block_hash or event_name not in {"Take", "AuctionKicked"}:
        return None
    # Require both a surviving projection and its exact canonical source event.
    if event_name == "Take":
        source = "takes"
        tx_column, log_column = "tx_hash", "log_index"
    else:
        source = "round_param_snapshot"
        tx_column, log_column = "snapshot_tx_hash", "snapshot_log_index"
    row = conn.execute(
        f"""
        SELECT s.auction_address, s.round_id FROM {source} s JOIN domain_events e
          ON e.chain_id = s.chain_id AND e.tx_hash = s.{tx_column} AND e.log_index = s.{log_column}
         WHERE e.chain_id = ? AND e.block_hash = ? AND e.tx_hash = ? AND e.log_index = ? AND e.event_name = ?
        """,
        (chain_id, block_hash, tx_hash, log_index, event_name),
    ).fetchone()
    return (str(row[0]), int(row[1])) if row else None


def _queue_job_round(conn, job: PricingQueueJob) -> tuple[str, int] | None:
    return _source_round(conn, chain_id=job.chain_id, block_hash=job.source_block_hash,
                         tx_hash=job.source_tx_hash, log_index=job.source_log_index, event_name=job.source_event_name)


def refresh_event_pricing(conn, *, chain_id: int, events: list[PreparedEvent]) -> None:
    rounds = set()
    for prepared in events:
        event = prepared.domain_event
        key = _source_round(conn, chain_id=chain_id, block_hash=event.block_hash,
                            tx_hash=event.tx_hash, log_index=event.log_index, event_name=event.event_name)
        if key is not None:
            rounds.add(key)
    if rounds:
        rebuild_pricing_projections(conn, chain_id=chain_id, rounds=rounds)


def _queue_job_source_exists(conn, job: PricingQueueJob) -> bool:
    return _queue_job_round(conn, job) is not None

def delete_orphaned_pricing_queue_rows(conn, *, chain_id: int) -> int:
    rows = conn.execute("SELECT * FROM pricing_capture_queue WHERE chain_id = ?", (chain_id,)).fetchall()
    orphan_ids = [(row["id"],) for row in rows if not _queue_job_source_exists(conn, _queue_job_from_row(row))]
    conn.executemany("DELETE FROM pricing_capture_queue WHERE id = ?", orphan_ids)
    return len(orphan_ids)


def _select_due_queue_jobs(
    conn,
    *,
    chain_id: int,
    limit: int,
    max_capture_lag_seconds: int,
) -> list[SelectedPricingJob]:
    now = _now()
    # Catch-up can enqueue many old events. Expire them together so they cannot
    # spend successive worker slots ahead of a fresh, capturable observation.
    conn.execute(
        "DELETE FROM pricing_capture_queue WHERE chain_id = ? AND event_timestamp <= ?",
        (chain_id, now - max_capture_lag_seconds),
    )
    rows = conn.execute(
        """
        SELECT *
          FROM pricing_capture_queue
         WHERE chain_id = ?
           AND (
                status = 'pending'
                OR (status = 'failed' AND next_attempt_at IS NOT NULL AND next_attempt_at <= ?)
         )
         ORDER BY priority DESC, created_at ASC, id ASC
         LIMIT ?
        """,
        (chain_id, now, limit),
    ).fetchall()
    jobs = [_queue_job_from_row(row) for row in rows]
    return [
        SelectedPricingJob(job=job, source_exists=_queue_job_source_exists(conn, job))
        for job in jobs
    ]


def _update_queue_status(
    conn,
    *,
    job_id: int,
    status: str,
    attempt_count: int,
    last_error: str | None,
    next_attempt_at: int | None = None,
) -> None:
    conn.execute(
        """
        UPDATE pricing_capture_queue
           SET status = ?,
               attempt_count = ?,
               last_error = ?,
               next_attempt_at = ?,
               updated_at = ?
         WHERE id = ?
        """,
        (status, attempt_count, last_error, next_attempt_at, _now(), job_id),
    )


def _provider_scope(
    client: PricingApiClient,
    *,
    chain_id: int,
    kind: str,
) -> tuple[list[ProviderCapability], list[str]]:
    scope = client.supported_providers(chain_id=chain_id, kind=kind)
    requestable = [item.id for item in scope if item.available]
    return scope, requestable


def _persist_quote_fact(
    conn,
    *,
    job: PricingQueueJob,
    provider_scope: list[ProviderCapability],
    use_underlying: bool,
    timeout_ms: int,
    captured_at: int,
    capture_state: str,
    payload: dict[str, Any] | None,
    aggregate_error: dict[str, Any] | None,
) -> int:
    capture_lag_seconds = max(0, captured_at - job.event_timestamp)
    cursor = conn.execute(
        """
        INSERT INTO pricing_quote_facts (
            chain_id, auction_address, round_id, take_seq, context_kind,
            capture_origin, source_tx_hash, source_log_index, source_event_name,
            source_block_number, source_block_hash,
            event_timestamp, captured_at, capture_lag_seconds, from_token,
            to_token, amount_in_raw, use_underlying, timeout_ms, include_route,
            capture_state, request_id, aggregate_response_json, aggregate_error_json,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.chain_id,
            job.auction_address,
            job.round_id,
            job.take_seq,
            "round_kick" if job.entity_kind == "round_kick_quote" else "take",
            "native",
            job.source_tx_hash,
            job.source_log_index,
            job.source_event_name,
            job.source_block_number,
            job.source_block_hash,
            job.event_timestamp,
            captured_at,
            capture_lag_seconds,
            job.from_token,
            job.to_token,
            job.amount_in_raw,
            1 if use_underlying else 0,
            timeout_ms,
            1,
            capture_state,
            payload.get("request_id") if payload else None,
            _json_dumps_or_none(payload),
            _json_dumps_or_none(aggregate_error),
            captured_at,
        ),
    )
    fact_id = int(cursor.lastrowid)
    provider_entries = payload.get("providers") if payload else None
    if not isinstance(provider_entries, dict):
        provider_entries = {}
    for position, capability in enumerate(provider_scope):
        entry = provider_entries.get(capability.id)
        if isinstance(entry, dict):
            participation_status = str(entry.get("status") or ("ok" if entry.get("success") else "error"))
            error_payload = entry.get("error") if isinstance(entry.get("error"), dict) else None
            conn.execute(
                """
                INSERT INTO pricing_quote_provider_facts (
                    quote_fact_id, provider_id, provider_position,
                    participation_status, amount_in_raw, amount_out_raw,
                    amount_out_min_raw, price_impact_bps, estimated_gas,
                    latency_ms, as_of, retrieved_at, error_code,
                    error_message, error_retry_after_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    capability.id,
                    position,
                    participation_status,
                    decimal_text(entry.get("amount_in")),
                    decimal_text(entry.get("amount_out")),
                    decimal_text(entry.get("amount_out_min")),
                    _coalesce_int(entry.get("price_impact_bps"), default=None) if entry.get("price_impact_bps") is not None else None,
                    _coalesce_int(entry.get("estimated_gas"), default=None) if entry.get("estimated_gas") is not None else None,
                    _coalesce_int(entry.get("latency_ms")),
                    entry.get("as_of"),
                    entry.get("retrieved_at"),
                    _provider_error_type(error_payload),
                    error_payload.get("message") if error_payload else None,
                    _coalesce_int(error_payload.get("retry_after_ms"), default=None)
                    if error_payload and error_payload.get("retry_after_ms") is not None
                    else None,
                ),
            )
            continue
        participation_status = "unavailable" if not capability.available else "not_requested"
        conn.execute(
            """
            INSERT INTO pricing_quote_provider_facts (
                quote_fact_id, provider_id, provider_position, participation_status,
                latency_ms, error_message
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                capability.id,
                position,
                participation_status,
                0,
                capability.unavailable_reason,
            ),
        )
    return fact_id


def _persist_price_fact(
    conn,
    *,
    job: PricingQueueJob,
    provider_scope: list[ProviderCapability],
    use_underlying: bool,
    timeout_ms: int,
    captured_at: int,
    capture_state: str,
    payload: dict[str, Any] | None,
    aggregate_error: dict[str, Any] | None,
) -> int:
    capture_lag_seconds = max(0, captured_at - job.event_timestamp)
    cursor = conn.execute(
        """
        INSERT INTO pricing_price_facts (
            chain_id, auction_address, round_id, take_seq, context_kind,
            capture_origin, price_role, source_tx_hash, source_log_index, source_event_name,
            source_block_number, source_block_hash,
            event_timestamp, captured_at, capture_lag_seconds,
            token, use_underlying, timeout_ms, capture_state, request_id,
            aggregate_response_json,
            aggregate_error_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.chain_id,
            job.auction_address,
            job.round_id,
            job.take_seq,
            "round_kick" if job.take_seq is None else "take",
            "native",
            "want_token",
            job.source_tx_hash,
            job.source_log_index,
            job.source_event_name,
            job.source_block_number,
            job.source_block_hash,
            job.event_timestamp,
            captured_at,
            capture_lag_seconds,
            job.token,
            1 if use_underlying else 0,
            timeout_ms,
            capture_state,
            payload.get("request_id") if payload else None,
            _json_dumps_or_none(payload),
            _json_dumps_or_none(aggregate_error),
            captured_at,
        ),
    )
    fact_id = int(cursor.lastrowid)
    provider_entries = payload.get("providers") if payload else None
    if not isinstance(provider_entries, dict):
        provider_entries = {}
    for position, capability in enumerate(provider_scope):
        entry = provider_entries.get(capability.id)
        if isinstance(entry, dict):
            participation_status = str(entry.get("status") or ("ok" if entry.get("success") else "error"))
            error_payload = entry.get("error") if isinstance(entry.get("error"), dict) else None
            conn.execute(
                """
                INSERT INTO pricing_price_provider_facts (
                    price_fact_id, provider_id, provider_position,
                    participation_status, price_usd, latency_ms, as_of,
                    retrieved_at, error_code, error_message,
                    error_retry_after_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    capability.id,
                    position,
                    participation_status,
                    decimal_text(entry.get("price")),
                    _coalesce_int(entry.get("latency_ms")),
                    entry.get("as_of"),
                    entry.get("retrieved_at"),
                    _provider_error_type(error_payload),
                    error_payload.get("message") if error_payload else None,
                    _coalesce_int(error_payload.get("retry_after_ms"), default=None)
                    if error_payload and error_payload.get("retry_after_ms") is not None
                    else None,
                ),
            )
            continue
        participation_status = "unavailable" if not capability.available else "not_requested"
        conn.execute(
            """
            INSERT INTO pricing_price_provider_facts (
                price_fact_id, provider_id, provider_position, participation_status,
                latency_ms, error_message
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                capability.id,
                position,
                participation_status,
                0,
                capability.unavailable_reason,
            ),
        )
    return fact_id


def _latest_capture_state(rows: list[Any]) -> str | None:
    if not rows:
        return None
    return str(rows[0]["capture_state"])


def _take_pricing_status(
    *,
    quote_selection: QuoteSelection | None,
    price_selection: PriceSelection | None,
    quote_rows: list[Any],
    price_rows: list[Any],
) -> str:
    if quote_selection and price_selection:
        return "priced"
    if quote_selection:
        return "quote_only"
    states = [_latest_capture_state(quote_rows), _latest_capture_state(price_rows)]
    if "unsupported_chain" in states:
        return "unsupported_chain"
    if "stale" in states:
        return "stale"
    if "failed" in states:
        return "failed"
    return "unpriced"


def _round_filter(alias: str, rounds: set[tuple[str, int]] | None) -> tuple[str, tuple]:
    if rounds is None:
        return "", ()
    if not rounds:
        return " AND 0", ()
    placeholders = ",".join("(?, ?)" for _ in rounds)
    return (f" AND ({alias}.auction_address, {alias}.round_id) IN (VALUES {placeholders})",
            tuple(value for key in sorted(rounds) for value in key))


def _load_surviving_take_sources(conn, *, chain_id: int, rounds: set[tuple[str, int]] | None = None) -> dict[tuple[int, str, str, int], tuple[str, int, int]]:
    scope, params = _round_filter("t", rounds)
    rows = conn.execute(
        f"""
        SELECT t.chain_id, e.block_hash, t.tx_hash, t.log_index, t.auction_address, t.round_id, t.take_seq
          FROM takes t JOIN domain_events e
            ON e.chain_id = t.chain_id AND e.tx_hash = t.tx_hash AND e.log_index = t.log_index
           AND e.event_name = 'Take'
         WHERE t.chain_id = ? {scope}
        """, (chain_id, *params),
    ).fetchall()
    return {
        (int(row["chain_id"]), str(row["block_hash"]), str(row["tx_hash"]), int(row["log_index"])):
        (str(row["auction_address"]), int(row["round_id"]), int(row["take_seq"]))
        for row in rows
    }


def _load_surviving_kick_sources(conn, *, chain_id: int, rounds: set[tuple[str, int]] | None = None) -> dict[tuple[int, str, str, int], tuple[str, int]]:
    scope, params = _round_filter("s", rounds)
    rows = conn.execute(
        f"""
        SELECT s.chain_id, e.block_hash, s.snapshot_tx_hash, s.snapshot_log_index, s.auction_address, s.round_id
          FROM round_param_snapshot s JOIN domain_events e
            ON e.chain_id = s.chain_id AND e.tx_hash = s.snapshot_tx_hash AND e.log_index = s.snapshot_log_index
           AND e.event_name = 'AuctionKicked'
         WHERE s.chain_id = ? {scope}
        """, (chain_id, *params),
    ).fetchall()
    return {
        (int(row["chain_id"]), str(row["block_hash"]), str(row["snapshot_tx_hash"]), int(row["snapshot_log_index"])):
        (str(row["auction_address"]), int(row["round_id"]))
        for row in rows
    }


def _resolved_take_source_key(row, *, take_sources) -> tuple[str, int, int] | None:
    if row["source_block_hash"] is None or row["source_tx_hash"] is None or row["source_log_index"] is None:
        return None
    return take_sources.get((int(row["chain_id"]), str(row["source_block_hash"]), str(row["source_tx_hash"]), int(row["source_log_index"])))


def _resolved_kick_source_key(row, *, kick_sources) -> tuple[str, int] | None:
    if row["source_block_hash"] is None or row["source_tx_hash"] is None or row["source_log_index"] is None:
        return None
    return kick_sources.get((int(row["chain_id"]), str(row["source_block_hash"]), str(row["source_tx_hash"]), int(row["source_log_index"])))


def _resolved_quote_fact_key(
    row,
    *,
    take_sources: dict[tuple[int, str, str, int], tuple[str, int, int]],
    kick_sources: dict[tuple[int, str, str, int], tuple[str, int]],
) -> tuple[str, tuple[str, int, int] | tuple[str, int]] | None:
    context_kind = str(row["context_kind"])
    if context_kind == "take":
        key = _resolved_take_source_key(row, take_sources=take_sources)
        return ("take", key) if key is not None else None
    if context_kind == "round_kick":
        key = _resolved_kick_source_key(row, kick_sources=kick_sources)
        return ("round_kick", key) if key is not None else None
    return None


def _resolved_price_fact_key(
    row,
    *,
    take_sources: dict[tuple[int, str, str, int], tuple[str, int, int]],
    kick_sources: dict[tuple[int, str, str, int], tuple[str, int]],
) -> tuple[str, tuple[str, int, int] | tuple[str, int]] | None:
    if str(row["price_role"]) != "want_token":
        return None
    context_kind = str(row["context_kind"])
    if context_kind == "take":
        key = _resolved_take_source_key(row, take_sources=take_sources)
        return ("take", key) if key is not None else None
    if context_kind == "round_kick":
        key = _resolved_kick_source_key(row, kick_sources=kick_sources)
        return ("round_kick", key) if key is not None else None
    return None


def rebuild_pricing_projections(
    conn, *, chain_id: int, rounds: set[tuple[str, int]] | None = None,
    previous_takers: set[str] = frozenset(),
) -> int:
    """Use the same reducers for repair and updates. Capture old takers before deleting takes."""
    scope, params = _round_filter("takes", rounds)
    affected_takers = None if rounds is None else set(previous_takers) | {
        str(row[0]) for row in conn.execute(f"SELECT DISTINCT taker FROM takes WHERE chain_id = ? {scope}", (chain_id, *params))
    }
    for table in ("take_pricing_source", "round_pricing_source", "take_pricing", "round_pricing"):
        scope, params = _round_filter(table, rounds)
        conn.execute(f"DELETE FROM {table} WHERE chain_id = ? {scope}", (chain_id, *params))
    take_sources = _load_surviving_take_sources(conn, chain_id=chain_id, rounds=rounds)
    kick_sources = _load_surviving_kick_sources(conn, chain_id=chain_id, rounds=rounds)
    # Match canonical source occurrences, not fact-time round IDs (which replay can change).
    source_cte = ""
    source_join = ""
    source_params = ()
    if rounds is not None:
        take_scope, take_params = _round_filter("t", rounds)
        kick_scope, kick_params = _round_filter("s", rounds)
        source_cte = f"""WITH selected_sources(chain_id, block_hash, tx_hash, log_index) AS (
            SELECT e.chain_id, e.block_hash, e.tx_hash, e.log_index
              FROM takes t JOIN domain_events e ON e.chain_id = t.chain_id
               AND e.tx_hash = t.tx_hash AND e.log_index = t.log_index AND e.event_name = 'Take'
             WHERE t.chain_id = ? {take_scope}
            UNION
            SELECT e.chain_id, e.block_hash, e.tx_hash, e.log_index
              FROM round_param_snapshot s JOIN domain_events e ON e.chain_id = s.chain_id
               AND e.tx_hash = s.snapshot_tx_hash AND e.log_index = s.snapshot_log_index
               AND e.event_name = 'AuctionKicked'
             WHERE s.chain_id = ? {kick_scope}
        )"""
        source_params = (chain_id, *take_params, chain_id, *kick_params)
        source_join = """JOIN selected_sources selected ON selected.chain_id = {alias}.chain_id
            AND selected.block_hash = {alias}.source_block_hash
            AND selected.tx_hash = {alias}.source_tx_hash AND selected.log_index = {alias}.source_log_index"""

    quote_facts = list(
        conn.execute(
            f"""{source_cte}
            SELECT q.*
              FROM pricing_quote_facts q
              {source_join.format(alias="q")}
             WHERE q.chain_id = ?
             ORDER BY q.captured_at ASC, q.id ASC
            """,
            (*source_params, chain_id),
        ).fetchall()
    )
    quote_provider_rows = list(
        conn.execute(
            f"""{source_cte}
            SELECT qp.*, q.context_kind, q.auction_address, q.round_id, q.take_seq
              FROM pricing_quote_provider_facts qp
              JOIN pricing_quote_facts q
                ON q.id = qp.quote_fact_id
              {source_join.format(alias="q")}
             WHERE q.chain_id = ?
             ORDER BY qp.quote_fact_id ASC, qp.provider_position ASC
            """,
            (*source_params, chain_id),
        ).fetchall()
    )
    price_facts = list(
        conn.execute(
            f"""{source_cte}
            SELECT p.*
              FROM pricing_price_facts p
              {source_join.format(alias="p")}
             WHERE p.chain_id = ?
             ORDER BY p.captured_at ASC, p.id ASC
            """,
            (*source_params, chain_id),
        ).fetchall()
    )
    price_provider_rows = list(
        conn.execute(
            f"""{source_cte}
            SELECT pp.*, p.context_kind, p.price_role, p.auction_address, p.round_id, p.take_seq
              FROM pricing_price_provider_facts pp
              JOIN pricing_price_facts p
                ON p.id = pp.price_fact_id
              {source_join.format(alias="p")}
             WHERE p.chain_id = ?
             ORDER BY pp.price_fact_id ASC, pp.provider_position ASC
            """,
            (*source_params, chain_id),
        ).fetchall()
    )

    quote_providers_by_fact: dict[int, list[Any]] = {}
    for row in quote_provider_rows:
        quote_providers_by_fact.setdefault(int(row["quote_fact_id"]), []).append(row)

    price_providers_by_fact: dict[int, list[Any]] = {}
    for row in price_provider_rows:
        price_providers_by_fact.setdefault(int(row["price_fact_id"]), []).append(row)

    take_quote_rows: dict[tuple[str, int, int], list[Any]] = {}
    round_quote_rows: dict[tuple[str, int], list[Any]] = {}
    take_quote_selection: dict[tuple[str, int, int], QuoteSelection] = {}
    round_quote_selection: dict[tuple[str, int], QuoteSelection] = {}
    for row in quote_facts:
        resolved = _resolved_quote_fact_key(
            row,
            take_sources=take_sources,
            kick_sources=kick_sources,
        )
        if resolved is None:
            continue
        context_kind, key = resolved
        if context_kind == "take":
            take_quote_rows.setdefault(key, []).insert(0, row)
            selection = summarize_quote(row, quote_providers_by_fact.get(int(row["id"]), [])) if row["capture_state"] == "fresh" else None
            if selection is not None and key not in take_quote_selection:
                take_quote_selection[key] = selection
        elif context_kind == "round_kick":
            round_quote_rows.setdefault(key, []).insert(0, row)
            selection = summarize_quote(row, quote_providers_by_fact.get(int(row["id"]), [])) if row["capture_state"] == "fresh" else None
            if selection is not None and key not in round_quote_selection:
                round_quote_selection[key] = selection

    take_price_rows: dict[tuple[str, int, int], list[Any]] = {}
    round_price_rows: dict[tuple[str, int], list[Any]] = {}
    take_price_selection: dict[tuple[str, int, int], PriceSelection] = {}
    round_price_selection: dict[tuple[str, int], PriceSelection] = {}
    for row in price_facts:
        resolved = _resolved_price_fact_key(
            row,
            take_sources=take_sources,
            kick_sources=kick_sources,
        )
        if resolved is None:
            continue
        context_kind, key = resolved
        if context_kind == "take":
            take_price_rows.setdefault(key, []).insert(0, row)
            selection = summarize_price(row, price_providers_by_fact.get(int(row["id"]), [])) if row["capture_state"] == "fresh" else None
            if selection is not None and key not in take_price_selection:
                take_price_selection[key] = selection
        elif context_kind == "round_kick":
            round_price_rows.setdefault(key, []).insert(0, row)
            selection = summarize_price(row, price_providers_by_fact.get(int(row["id"]), [])) if row["capture_state"] == "fresh" else None
            if selection is not None and key not in round_price_selection:
                round_price_selection[key] = selection

    scope, params = _round_filter("t", rounds)
    take_rows = list(
        conn.execute(
            f"""
            SELECT t.chain_id,
                   t.auction_address,
                   t.round_id,
                   t.take_seq,
                   t.taker,
                   t.amount_taken_raw,
                   t.amount_paid_raw,
                   t.expected_amount_paid_raw,
                   t.timestamp,
                   t.from_token,
                   t.want_token,
                   wt.decimals AS want_token_decimals
              FROM takes t
              LEFT JOIN tokens wt
                ON wt.chain_id = t.chain_id
               AND wt.token_address = t.want_token
             WHERE t.chain_id = ? {scope}
             ORDER BY t.round_id ASC, t.take_seq ASC
            """,
            (chain_id, *params),
        ).fetchall()
    )

    take_pricing_rows: list[tuple[Any, ...]] = []
    take_pricing_source_rows: list[tuple[Any, ...]] = []
    take_rollups: dict[tuple[str, int], dict[str, Any]] = {}
    provider_round_rollups: dict[tuple[str, int, str], dict[str, Any]] = {}

    for row in take_rows:
        key = (str(row["auction_address"]), int(row["round_id"]), int(row["take_seq"]))
        quote_selection = take_quote_selection.get(key)
        price_selection = take_price_selection.get(key)
        want_decimals = int(row["want_token_decimals"]) if row["want_token_decimals"] is not None else None
        actual_paid_raw = row["amount_paid_raw"]
        market_quote_out_raw = quote_selection.amount_out_raw if quote_selection else None
        want_token_price_usd = price_selection.price_usd if price_selection else None
        auction_profit_raw = None
        if row["amount_paid_raw"] is not None and market_quote_out_raw is not None:
            auction_profit_raw = str(int(row["amount_paid_raw"]) - int(market_quote_out_raw))
        auction_profit_usd = _usd_value(auction_profit_raw, want_decimals, want_token_price_usd)
        actual_paid_usd = _usd_value(actual_paid_raw, want_decimals, want_token_price_usd)
        market_quote_out_usd = _usd_value(
            market_quote_out_raw,
            want_decimals,
            want_token_price_usd,
        )
        pricing_status = _take_pricing_status(
            quote_selection=quote_selection,
            price_selection=price_selection,
            quote_rows=take_quote_rows.get(key, []),
            price_rows=take_price_rows.get(key, []),
        )
        take_pricing_rows.append(
            (
                chain_id,
                row["auction_address"],
                int(row["round_id"]),
                int(row["take_seq"]),
                quote_selection.fact_id if quote_selection else None,
                price_selection.fact_id if price_selection else None,
                None,
                row["amount_taken_raw"],
                row["amount_paid_raw"],
                row["expected_amount_paid_raw"],
                market_quote_out_raw,
                market_quote_out_usd,
                want_token_price_usd,
                None,
                auction_profit_raw,
                _bps_from_raws(row["amount_paid_raw"], market_quote_out_raw),
                auction_profit_usd,
                actual_paid_usd,
                pricing_status,
                quote_selection.success_count if quote_selection else 0,
                quote_selection.spread_bps if quote_selection else None,
                quote_selection.capture_lag_seconds if quote_selection else None,
                1 if quote_selection else 0,
                1 if price_selection else 0,
            )
        )

        selected_provider_rows = (
            quote_providers_by_fact.get(quote_selection.fact_id, [])
            if quote_selection is not None
            else []
        )
        seen_source_ids: set[str] = set()
        for provider_row in selected_provider_rows:
            if provider_row["participation_status"] != "ok" or provider_row["amount_out_raw"] is None:
                continue
            source_id = str(provider_row["provider_id"] or "").strip().lower()
            if not source_id or source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            provider_market_quote_out_raw = str(provider_row["amount_out_raw"])
            provider_profit_raw = None
            if actual_paid_raw is not None:
                provider_profit_raw = str(int(actual_paid_raw) - int(provider_market_quote_out_raw))
            provider_market_quote_usd = _usd_value(
                provider_market_quote_out_raw,
                want_decimals,
                want_token_price_usd,
            )
            provider_profit_usd = _usd_value(
                provider_profit_raw,
                want_decimals,
                want_token_price_usd,
            )
            provider_profit_bps = _bps_from_raws(
                actual_paid_raw,
                provider_market_quote_out_raw,
            )
            take_pricing_source_rows.append(
                (
                    chain_id,
                    row["auction_address"],
                    int(row["round_id"]),
                    int(row["take_seq"]),
                    source_id,
                    quote_selection.fact_id,
                    provider_market_quote_out_raw,
                    provider_market_quote_usd,
                    provider_profit_raw,
                    provider_profit_usd,
                    provider_profit_bps,
                    actual_paid_usd,
                    "priced",
                )
            )

            provider_rollup = provider_round_rollups.setdefault(
                (str(row["auction_address"]), int(row["round_id"]), source_id),
                {
                    "total_actual_paid_raw": 0,
                    "total_market_quote_out_raw": 0,
                    "total_actual_paid_usd": Decimal(0),
                    "total_market_quote_usd": Decimal(0),
                    "total_auction_profit_usd": Decimal(0),
                    "priced_take_count": 0,
                    "usd_priced_take_count": 0,
                    "has_actual_paid_usd": False,
                    "has_market_quote_usd": False,
                    "has_profit_usd": False,
                    "priced_volume_raw": 0,
                },
            )
            if actual_paid_raw is not None:
                provider_rollup["total_actual_paid_raw"] += int(actual_paid_raw)
                provider_rollup["total_market_quote_out_raw"] += int(provider_market_quote_out_raw)
                provider_rollup["priced_take_count"] += 1
                provider_rollup["priced_volume_raw"] += int(row["amount_taken_raw"])
            if provider_profit_usd is not None:
                provider_rollup["usd_priced_take_count"] += 1
                provider_rollup["has_actual_paid_usd"] = True
                provider_rollup["has_market_quote_usd"] = True
                provider_rollup["has_profit_usd"] = True
                provider_rollup["total_actual_paid_usd"] += Decimal(actual_paid_usd)
                provider_rollup["total_market_quote_usd"] += Decimal(provider_market_quote_usd)
                provider_rollup["total_auction_profit_usd"] += Decimal(provider_profit_usd)

        round_key = (str(row["auction_address"]), int(row["round_id"]))
        round_rollup = take_rollups.setdefault(
            round_key,
            {
                "total_actual_paid_raw": 0,
                "matched_actual_paid_raw": 0,
                "matched_market_quote_out_raw": 0,
                "total_market_quote_out_raw": 0,
                "priced_take_count": 0,
                "usd_priced_take_count": 0,
                "paid_usd_take_count": 0,
                "paid_take_count": 0,
                "priced_volume_raw": 0,
                "total_take_count": 0,
                "total_actual_paid_usd": Decimal(0),
                "total_market_quote_usd": Decimal(0),
                "total_auction_profit_usd": Decimal(0),
                "has_actual_paid_usd": False,
                "has_market_quote_usd": False,
                "has_profit_usd": False,
            },
        )
        if actual_paid_raw is not None:
            round_rollup["total_actual_paid_raw"] += int(actual_paid_raw)
            round_rollup["paid_take_count"] += 1
        # PnL must compare receipts and quotes for the same fills. Unknown
        # receipts or missing quotes contribute to neither side of the ratio.
        if row["amount_paid_raw"] is not None and market_quote_out_raw is not None:
            round_rollup["matched_actual_paid_raw"] += int(row["amount_paid_raw"])
            round_rollup["matched_market_quote_out_raw"] += int(market_quote_out_raw)
        round_rollup["total_take_count"] += 1
        if quote_selection is not None and actual_paid_raw is not None:
            round_rollup["total_market_quote_out_raw"] += int(market_quote_out_raw)
            round_rollup["priced_take_count"] += 1
            round_rollup["priced_volume_raw"] += int(row["amount_taken_raw"])
        actual_paid_usd = _usd_value(row["amount_paid_raw"], want_decimals, want_token_price_usd)
        market_quote_usd = _usd_value(market_quote_out_raw, want_decimals, want_token_price_usd)
        if actual_paid_usd is not None:
            round_rollup["paid_usd_take_count"] += 1
            round_rollup["has_actual_paid_usd"] = True
            round_rollup["total_actual_paid_usd"] += Decimal(actual_paid_usd)
        if auction_profit_usd is not None:
            round_rollup["has_market_quote_usd"] = True
            round_rollup["total_market_quote_usd"] += Decimal(market_quote_usd)
        if auction_profit_usd is not None:
            round_rollup["usd_priced_take_count"] += 1
            round_rollup["has_profit_usd"] = True
            round_rollup["total_auction_profit_usd"] += Decimal(auction_profit_usd)


    if take_pricing_rows:
        conn.executemany(
            """
            INSERT INTO take_pricing (
                chain_id, auction_address, round_id, take_seq,
                canonical_quote_fact_id, canonical_want_price_fact_id,
                canonical_from_price_fact_id, amount_taken_raw, actual_paid_raw,
                expected_paid_raw, market_quote_out_raw, market_quote_out_usd,
                want_token_price_usd,
                from_token_price_usd, auction_profit_raw, auction_profit_bps,
                auction_profit_usd, priced_volume_usd, pricing_status,
                provider_success_count, quote_spread_bps, capture_lag_seconds,
                fresh_quote, fresh_want_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            take_pricing_rows,
        )
    if take_pricing_source_rows:
        conn.executemany(
            """
            INSERT INTO take_pricing_source (
                chain_id, auction_address, round_id, take_seq, source_id,
                quote_fact_id, market_quote_out_raw, market_quote_out_usd,
                auction_profit_raw, auction_profit_usd, auction_profit_bps,
                priced_volume_usd, pricing_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            take_pricing_source_rows,
        )

    scope, params = _round_filter("r", rounds)
    round_rows = list(
        conn.execute(
            f"""
            SELECT r.chain_id,
                   r.auction_address,
                   r.round_id,
                   r.initial_available_raw,
                   r.sold_amount_raw,
                   r.take_count,
                   r.want_token,
                   wt.decimals AS want_token_decimals
              FROM rounds r
              LEFT JOIN tokens wt
                ON wt.chain_id = r.chain_id
               AND wt.token_address = r.want_token
             WHERE r.chain_id = ? {scope}
             ORDER BY r.round_id ASC
            """,
            (chain_id, *params),
        ).fetchall()
    )

    round_pricing_rows: list[tuple[Any, ...]] = []
    round_pricing_source_rows: list[tuple[Any, ...]] = []
    for row in round_rows:
        key = (str(row["auction_address"]), int(row["round_id"]))
        quote_selection = round_quote_selection.get(key)
        price_selection = round_price_selection.get(key)
        want_decimals = int(row["want_token_decimals"]) if row["want_token_decimals"] is not None else None
        rollup = take_rollups.get(
            key,
            {
                "total_actual_paid_raw": 0,
                "matched_actual_paid_raw": 0,
                "matched_market_quote_out_raw": 0,
                "total_market_quote_out_raw": 0,
                "priced_take_count": 0,
                "usd_priced_take_count": 0,
                "paid_usd_take_count": 0,
                "paid_take_count": 0,
                "priced_volume_raw": 0,
                "total_take_count": int(row["take_count"]),
                "total_actual_paid_usd": Decimal(0),
                "total_market_quote_usd": Decimal(0),
                "total_auction_profit_usd": Decimal(0),
                "has_actual_paid_usd": False,
                "has_market_quote_usd": False,
                "has_profit_usd": False,
            },
        )
        kick_market_quote_out_raw = quote_selection.amount_out_raw if quote_selection else None
        kick_market_quote_usd = _usd_value(
            kick_market_quote_out_raw,
            want_decimals,
            price_selection.price_usd if price_selection else None,
        )
        total_actual_paid_raw = str(rollup["total_actual_paid_raw"]) if rollup["paid_take_count"] else None
        total_market_quote_out_raw = str(rollup["total_market_quote_out_raw"]) if rollup["priced_take_count"] else None
        round_pricing_rows.append(
            (
                chain_id,
                row["auction_address"],
                int(row["round_id"]),
                quote_selection.fact_id if quote_selection else None,
                kick_market_quote_out_raw,
                kick_market_quote_usd,
                None,
                None,
                total_actual_paid_raw,
                total_market_quote_out_raw,
                _decimal_to_text(rollup["total_actual_paid_usd"]) if rollup["has_actual_paid_usd"] else None,
                _decimal_to_text(rollup["total_market_quote_usd"]) if rollup["has_market_quote_usd"] else None,
                _decimal_to_text(rollup["total_auction_profit_usd"]) if rollup["has_profit_usd"] else None,
                _bps_from_raws(
                    str(rollup["matched_actual_paid_raw"]),
                    str(rollup["matched_market_quote_out_raw"]),
                ),
                int(rollup["priced_take_count"]),
                int(rollup["usd_priced_take_count"]),
                int(rollup["paid_usd_take_count"]),
                int(row["take_count"]),
                _ratio_text(int(rollup["priced_volume_raw"]), int(row["sold_amount_raw"] or 0)),
            )
        )
        provider_keys = sorted(
            (
                provider_key
                for provider_key in provider_round_rollups
                if provider_key[0] == key[0] and provider_key[1] == key[1]
            ),
            key=lambda provider_key: provider_key[2],
        )
        for provider_key in provider_keys:
            source_id = provider_key[2]
            provider_rollup = provider_round_rollups[provider_key]
            provider_actual_raw = str(provider_rollup["total_actual_paid_raw"]) if provider_rollup["priced_take_count"] else None
            provider_market_raw = str(provider_rollup["total_market_quote_out_raw"]) if provider_rollup["priced_take_count"] else None
            provider_volume_share = _ratio_text(provider_rollup["priced_volume_raw"], int(row["sold_amount_raw"]))
            round_pricing_source_rows.append(
                (
                    chain_id,
                    row["auction_address"],
                    int(row["round_id"]),
                    source_id,
                    provider_actual_raw,
                    provider_market_raw,
                    _decimal_to_text(provider_rollup["total_actual_paid_usd"])
                    if provider_rollup["has_actual_paid_usd"]
                    else None,
                    _decimal_to_text(provider_rollup["total_market_quote_usd"])
                    if provider_rollup["has_market_quote_usd"]
                    else None,
                    _decimal_to_text(provider_rollup["total_auction_profit_usd"])
                    if provider_rollup["has_profit_usd"]
                    else None,
                    _bps_from_raws(provider_actual_raw, provider_market_raw),
                    int(provider_rollup["priced_take_count"]),
                    int(provider_rollup["usd_priced_take_count"]),
                    int(row["take_count"]),
                    provider_volume_share,
                )
            )

    if round_pricing_rows:
        conn.executemany(
            """
            INSERT INTO round_pricing (
                chain_id, auction_address, round_id, kick_quote_fact_id,
                kick_market_quote_out_raw, kick_market_quote_usd,
                kick_contract_expected_out_raw, kick_start_premium_bps,
                total_actual_paid_raw,
                total_market_quote_out_raw, total_actual_paid_usd,
                total_market_quote_usd, total_auction_profit_usd,
                total_auction_profit_bps, priced_take_count, usd_priced_take_count, paid_usd_take_count, total_take_count,
                priced_volume_share
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            round_pricing_rows,
        )
    if round_pricing_source_rows:
        conn.executemany(
            """
            INSERT INTO round_pricing_source (
                chain_id, auction_address, round_id, source_id,
                total_actual_paid_raw, total_market_quote_out_raw,
                total_actual_paid_usd, total_market_quote_usd,
                total_auction_profit_usd, total_auction_profit_bps,
                priced_take_count, usd_priced_take_count, total_take_count, priced_volume_share
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            round_pricing_source_rows,
        )

    taker_rows_written = _rebuild_taker_pricing_summaries(conn, chain_id=chain_id, takers=affected_takers)
    return (
        len(take_pricing_rows)
        + len(take_pricing_source_rows)
        + len(round_pricing_rows)
        + len(round_pricing_source_rows)
        + taker_rows_written
    )


def _rebuild_taker_pricing_summaries(conn, *, chain_id: int, takers: set[str] | None) -> int:
    if takers == set():
        return 0
    scope = "" if takers is None else " AND taker IN (" + ",".join("?" for _ in takers) + ")"
    params = (chain_id, *sorted(takers or ()))
    conn.execute(f"DELETE FROM taker_pricing_summary WHERE chain_id = ? {scope}", params)
    rows = conn.execute(f"""
        SELECT t.taker, t.timestamp, t.amount_paid_raw, wt.decimals AS want_token_decimals,
               p.canonical_quote_fact_id, p.want_token_price_usd, p.market_quote_out_usd,
               p.auction_profit_usd, p.priced_volume_usd
          FROM takes t
          LEFT JOIN take_pricing p ON p.chain_id = t.chain_id AND p.auction_address = t.auction_address
               AND p.round_id = t.round_id AND p.take_seq = t.take_seq
          LEFT JOIN tokens wt ON wt.chain_id = t.chain_id AND wt.token_address = t.want_token
         WHERE t.chain_id = ? {scope}
         ORDER BY t.auction_address, t.round_id, t.take_seq
    """, params).fetchall()
    taker_rollups: dict[str, dict[str, Any]] = {}
    for row in rows:
        actual_paid_usd = _usd_value(row["amount_paid_raw"], row["want_token_decimals"], row["want_token_price_usd"])
        market_quote_usd = row["market_quote_out_usd"]
        auction_profit_usd = row["auction_profit_usd"]
        taker = str(row["taker"])
        taker_rollup = taker_rollups.setdefault(
            taker,
            {
                "total_take_count": 0,
                "priced_take_count": 0,
                "paid_usd_take_count": 0,
                "total_actual_paid_usd": Decimal(0),
                "total_market_quote_usd": Decimal(0),
                "total_taker_profit_usd": Decimal(0),
                "priced_volume_usd": Decimal(0),
                "total_volume_usd_for_share": Decimal(0),
                "has_actual_paid_usd": False,
                "has_market_quote_usd": False,
                "has_taker_profit_usd": False,
                "first_priced_take_at": None,
                "last_priced_take_at": None,
            },
        )
        taker_rollup["total_take_count"] += 1
        if actual_paid_usd is not None:
            taker_rollup["total_volume_usd_for_share"] += Decimal(actual_paid_usd)
            if row["canonical_quote_fact_id"] is not None:
                taker_rollup["priced_volume_usd"] += Decimal(actual_paid_usd)
        if auction_profit_usd is not None:
            taker_rollup["priced_take_count"] += 1
            timestamp = int(row["timestamp"])
            if taker_rollup["first_priced_take_at"] is None:
                taker_rollup["first_priced_take_at"] = timestamp
                taker_rollup["last_priced_take_at"] = timestamp
            else:
                taker_rollup["first_priced_take_at"] = min(taker_rollup["first_priced_take_at"], timestamp)
                taker_rollup["last_priced_take_at"] = max(taker_rollup["last_priced_take_at"], timestamp)
        if actual_paid_usd is not None:
            taker_rollup["paid_usd_take_count"] += 1
            taker_rollup["has_actual_paid_usd"] = True
            taker_rollup["total_actual_paid_usd"] += Decimal(actual_paid_usd)
        if auction_profit_usd is not None:
            taker_rollup["has_market_quote_usd"] = True
            taker_rollup["total_market_quote_usd"] += Decimal(market_quote_usd)
        if auction_profit_usd is not None:
            taker_rollup["has_taker_profit_usd"] = True
            taker_rollup["total_taker_profit_usd"] += -Decimal(auction_profit_usd)

    taker_pricing_rows: list[tuple[Any, ...]] = []
    for taker, rollup in sorted(taker_rollups.items()):
        average_profit = None
        if rollup["priced_take_count"] > 0 and rollup["has_taker_profit_usd"]:
            with localcontext() as context:
                context.prec = 80
                average_profit = _decimal_to_text(
                    rollup["total_taker_profit_usd"] / Decimal(rollup["priced_take_count"])
                )
        taker_pricing_rows.append(
            (
                chain_id,
                taker,
                int(rollup["priced_take_count"]),
                int(rollup["total_take_count"]),
                int(rollup["paid_usd_take_count"]),
                _decimal_to_text(rollup["total_actual_paid_usd"]) if rollup["has_actual_paid_usd"] else None,
                _decimal_to_text(rollup["total_market_quote_usd"]) if rollup["has_market_quote_usd"] else None,
                _decimal_to_text(rollup["total_taker_profit_usd"]) if rollup["has_taker_profit_usd"] else None,
                average_profit,
                _decimal_to_text(rollup["priced_volume_usd"]),
                _decimal_to_text(rollup["total_volume_usd_for_share"]),
                _decimal_ratio_text(rollup["priced_volume_usd"], rollup["total_volume_usd_for_share"]),
                rollup["first_priced_take_at"],
                rollup["last_priced_take_at"],
            )
        )

    if taker_pricing_rows:
        conn.executemany(
            """
            INSERT INTO taker_pricing_summary (
                chain_id, taker, priced_take_count, total_take_count, paid_usd_take_count,
                total_actual_paid_usd, total_market_quote_usd,
                total_taker_profit_usd, avg_taker_profit_usd,
                priced_volume_usd, total_volume_usd_for_share,
                priced_volume_share, first_priced_take_at, last_priced_take_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            taker_pricing_rows,
        )
    return len(taker_pricing_rows)


class PricingCaptureRuntime:
    def __init__(
        self,
        *,
        client: PricingApiClient | None = None,
        max_capture_lag_seconds: int = DEFAULT_MAX_CAPTURE_LAG_SECONDS,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry_seconds: int = DEFAULT_RETRY_SECONDS,
        use_underlying: bool = True,
    ) -> None:
        self.client = client or PricingApiClient()
        self.max_capture_lag_seconds = max_capture_lag_seconds
        self.timeout_ms = timeout_ms
        self.retry_seconds = retry_seconds
        self.use_underlying = use_underlying
        self._executor: ThreadPoolExecutor | None = None
        self._outstanding: Future[PricingAttemptResult] | None = None

    def poll(self, writer, *, chain_id: int) -> int:
        """Commit a ready result and dispatch at most one HTTP job; never wait."""
        committed = 0
        if self._outstanding is not None:
            if not self._outstanding.done():
                return 0
            try:
                attempt = self._outstanding.result()
            except BaseException:
                self._outstanding = None
                raise
            summary = writer.transaction(lambda conn: self._commit_attempts(
                conn, chain_id=chain_id, attempts=(attempt,),
            ))
            committed = summary.facts_written
            self._outstanding = None

        selected = writer.transaction(lambda conn: _select_due_queue_jobs(
            conn, chain_id=chain_id, limit=1, max_capture_lag_seconds=self.max_capture_lag_seconds,
        ))
        if selected:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pricing")
            # The durable queue row remains pending until its result is committed.
            self._outstanding = self._executor.submit(self._attempt, selected[0])
        return committed

    def discard(self) -> None:
        """Maintenance discards results; pending durable jobs remain retryable."""
        self._outstanding = None
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    def _attempt(self, selected: SelectedPricingJob) -> PricingAttemptResult:
        job = selected.job
        if not selected.source_exists:
            return self._terminal_without_fact(job, reason="missing_source")
        if _now() - job.event_timestamp >= self.max_capture_lag_seconds:
            return self._terminal_without_fact(job, reason="stale")
        if job.entity_kind in {"round_kick_quote", "take_quote"}:
            return self._attempt_quote(job)
        if job.entity_kind == "want_token_price":
            return self._attempt_price(job)
        return self._terminal_without_fact(
            job,
            reason=f"unsupported entity_kind {job.entity_kind}",
        )

    def _terminal_without_fact(
        self,
        job: PricingQueueJob,
        *,
        reason: str,
    ) -> PricingAttemptResult:
        return PricingAttemptResult(
            job=job,
            fact_kind=None,
            provider_scope=(),
            capture_state=None,
            captured_at=None,
            payload_json=None,
            aggregate_error_json=None,
            queue_action="delete",
            last_error=reason,
            next_attempt_at=None,
        )

    def _failed_attempt(
        self,
        job: PricingQueueJob,
        *,
        fact_kind: str,
        provider_scope: tuple[ProviderCapability, ...],
        code: str,
        message: str,
        retryable: bool,
        capture_state: str = "failed",
    ) -> PricingAttemptResult:
        captured_at = _now()
        return PricingAttemptResult(
            job=job,
            fact_kind=fact_kind,
            provider_scope=provider_scope,
            capture_state=capture_state,
            captured_at=captured_at,
            payload_json=None,
            aggregate_error_json=_json_dumps({"code": code, "message": message}),
            queue_action="retry" if retryable else "delete",
            last_error=message,
            next_attempt_at=captured_at + self.retry_seconds if retryable else None,
        )

    def _attempt_quote(self, job: PricingQueueJob) -> PricingAttemptResult:
        try:
            provider_scope, requestable = _provider_scope(
                self.client,
                chain_id=job.chain_id,
                kind="quote",
            )
        except Exception as exc:
            return self._failed_attempt(
                job,
                fact_kind="quote",
                provider_scope=(),
                code="provider_discovery_failed",
                message=str(exc),
                retryable=True,
            )
        frozen_scope = tuple(provider_scope)
        if not provider_scope:
            return self._failed_attempt(
                job,
                fact_kind="quote",
                provider_scope=frozen_scope,
                code="unsupported_chain",
                message=f"no quote providers support chain {job.chain_id}",
                retryable=False,
                capture_state="unsupported_chain",
            )
        if not requestable:
            return self._failed_attempt(
                job,
                fact_kind="quote",
                provider_scope=frozen_scope,
                code="unavailable",
                message="no available quote providers",
                retryable=True,
            )
        try:
            payload = self.client.fetch_quote(
                chain_id=job.chain_id,
                token_in=str(job.from_token),
                token_out=str(job.to_token),
                amount_in=str(job.amount_in_raw),
                providers=requestable,
                use_underlying=self.use_underlying,
                timeout_ms=self.timeout_ms,
            )
            payload_json = _json_dumps(payload)
        except Exception as exc:
            return self._failed_attempt(
                job,
                fact_kind="quote",
                provider_scope=frozen_scope,
                code="request_failed",
                message=str(exc),
                retryable=True,
            )
        captured_at = _now()
        return PricingAttemptResult(
            job=job,
            fact_kind="quote",
            provider_scope=frozen_scope,
            capture_state=(
                "fresh"
                if captured_at - job.event_timestamp < self.max_capture_lag_seconds
                else "stale"
            ),
            captured_at=captured_at,
            payload_json=payload_json,
            aggregate_error_json=None,
            queue_action="delete",
            last_error=None,
            next_attempt_at=None,
        )

    def _attempt_price(self, job: PricingQueueJob) -> PricingAttemptResult:
        try:
            provider_scope, requestable = _provider_scope(
                self.client,
                chain_id=job.chain_id,
                kind="price",
            )
        except Exception as exc:
            return self._failed_attempt(
                job,
                fact_kind="price",
                provider_scope=(),
                code="provider_discovery_failed",
                message=str(exc),
                retryable=True,
            )
        frozen_scope = tuple(provider_scope)
        if not provider_scope:
            return self._failed_attempt(
                job,
                fact_kind="price",
                provider_scope=frozen_scope,
                code="unsupported_chain",
                message=f"no price providers support chain {job.chain_id}",
                retryable=False,
                capture_state="unsupported_chain",
            )
        if not requestable:
            return self._failed_attempt(
                job,
                fact_kind="price",
                provider_scope=frozen_scope,
                code="unavailable",
                message="no available price providers",
                retryable=True,
            )
        try:
            payload = self.client.fetch_price(
                chain_id=job.chain_id,
                token=str(job.token),
                providers=requestable,
                use_underlying=self.use_underlying,
                timeout_ms=self.timeout_ms,
            )
            payload_json = _json_dumps(payload)
        except Exception as exc:
            return self._failed_attempt(
                job,
                fact_kind="price",
                provider_scope=frozen_scope,
                code="request_failed",
                message=str(exc),
                retryable=True,
            )
        captured_at = _now()
        return PricingAttemptResult(
            job=job,
            fact_kind="price",
            provider_scope=frozen_scope,
            capture_state=(
                "fresh"
                if captured_at - job.event_timestamp < self.max_capture_lag_seconds
                else "stale"
            ),
            captured_at=captured_at,
            payload_json=payload_json,
            aggregate_error_json=None,
            queue_action="delete",
            last_error=None,
            next_attempt_at=None,
        )

    def _commit_attempts(
        self,
        conn,
        *,
        chain_id: int,
        attempts: tuple[PricingAttemptResult, ...],
    ) -> PricingDrainSummary:
        affected_rounds: set[tuple[str, int]] = set()
        facts_written = 0
        retries = 0
        terminal_deletions = 0
        for attempt in attempts:
            job = attempt.job
            queue_row = conn.execute(
                "SELECT 1 FROM pricing_capture_queue WHERE id = ? AND chain_id = ?",
                (job.id, chain_id),
            ).fetchone()
            if queue_row is None:
                continue
            current_round = _queue_job_round(conn, job)
            if current_round is None:
                deleted = conn.execute(
                    "DELETE FROM pricing_capture_queue WHERE id = ?",
                    (job.id,),
                )
                terminal_deletions += int(deleted.rowcount or 0)
                continue

            payload = json.loads(attempt.payload_json) if attempt.payload_json else None
            aggregate_error = (
                json.loads(attempt.aggregate_error_json)
                if attempt.aggregate_error_json
                else None
            )
            if attempt.fact_kind == "quote":
                _persist_quote_fact(
                    conn,
                    job=job,
                    provider_scope=list(attempt.provider_scope),
                    use_underlying=self.use_underlying,
                    timeout_ms=self.timeout_ms,
                    captured_at=int(attempt.captured_at),
                    capture_state=str(attempt.capture_state),
                    payload=payload,
                    aggregate_error=aggregate_error,
                )
                facts_written += 1
                affected_rounds.add(current_round)
            elif attempt.fact_kind == "price":
                _persist_price_fact(
                    conn,
                    job=job,
                    provider_scope=list(attempt.provider_scope),
                    use_underlying=self.use_underlying,
                    timeout_ms=self.timeout_ms,
                    captured_at=int(attempt.captured_at),
                    capture_state=str(attempt.capture_state),
                    payload=payload,
                    aggregate_error=aggregate_error,
                )
                facts_written += 1
                affected_rounds.add(current_round)

            if attempt.queue_action == "retry":
                _update_queue_status(
                    conn,
                    job_id=job.id,
                    status="failed",
                    attempt_count=job.attempt_count + 1,
                    last_error=attempt.last_error,
                    next_attempt_at=attempt.next_attempt_at,
                )
                retries += 1
            else:
                deleted = conn.execute(
                    "DELETE FROM pricing_capture_queue WHERE id = ?",
                    (job.id,),
                )
                terminal_deletions += int(deleted.rowcount or 0)

        rebuild_started = time.perf_counter()
        projection_rows = rebuild_pricing_projections(conn, chain_id=chain_id, rounds=affected_rounds) if affected_rounds else 0
        rebuild_seconds = time.perf_counter() - rebuild_started
        return PricingDrainSummary(
            facts_written=facts_written,
            retries=retries,
            terminal_deletions=terminal_deletions,
            projection_rows=int(projection_rows),
            rebuild_seconds=rebuild_seconds,
        )
