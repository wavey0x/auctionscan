from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from .prices_api import (
    PricingApiClient,
    ProviderCapability,
    PricesApiAuthError,
    PricesApiError,
    PricesApiRateLimitError,
)
from .types import PreparedEvent, decimal_text
from .pricing_projections import _source_round, rebuild_pricing_projections


logger = logging.getLogger(__name__)

DEFAULT_MAX_CAPTURE_LAG_SECONDS = 600
DEFAULT_TIMEOUT_MS = 7000
DEFAULT_RETRY_SECONDS = 60


def _now() -> int:
    return int(time.time())


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _json_dumps_or_none(payload: Any) -> str | None:
    if payload is None:
        return None
    return _json_dumps(payload)


def _provider_error_type(error_payload: dict[str, Any] | None) -> str | None:
    if error_payload is None:
        return None
    raw_value = error_payload.get("type")
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return text or None


def _coalesce_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


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
