from __future__ import annotations

from backend.indexer.types import AuctionSnapshot, DomainEventRecord, PreparedEvent, RawLogRecord


DEFAULT_CHAIN_ID = 1
DEFAULT_FACTORY = "0x0000000000000000000000000000000000000faa"
DEFAULT_AUCTION = "0x0000000000000000000000000000000000000aaa"
DEFAULT_FROM_TOKEN = "0x0000000000000000000000000000000000000bbb"
DEFAULT_WANT_TOKEN = "0x0000000000000000000000000000000000000ccc"
DEFAULT_GOVERNANCE = "0x0000000000000000000000000000000000000ddd"
DEFAULT_RECEIVER = "0x0000000000000000000000000000000000000eee"
UPDATED_RECEIVER = "0x0000000000000000000000000000000000000eff"


def capture_due_pricing(pricing, writer, *, chain_id: int) -> int:
    """Wait for the real single-job worker when building deterministic fixtures."""
    processed = 0
    pricing.poll(writer, chain_id=chain_id)
    while pricing._outstanding is not None:
        pricing._outstanding.result(timeout=10)
        pricing.poll(writer, chain_id=chain_id)
        processed += 1
    return processed


def make_raw(
    *,
    chain_id: int = DEFAULT_CHAIN_ID,
    tx_nonce: int,
    block_number: int,
    log_index: int = 0,
    tx_index: int = 0,
    address: str = DEFAULT_AUCTION,
    timestamp: int | None = None,
    topic0: str = "0x01",
) -> RawLogRecord:
    if timestamp is None:
        timestamp = 1_700_000_000 + block_number
    return RawLogRecord(
        chain_id=chain_id,
        block_number=block_number,
        block_hash=f"0x{block_number:064x}",
        tx_hash=f"0x{tx_nonce:064x}",
        tx_index=tx_index,
        log_index=log_index,
        address=address,
        topic0=topic0,
        topic1="0x02",
        topic2=None,
        topic3=None,
        data="0x",
        timestamp=timestamp,
    )


def make_snapshot(
    *,
    chain_id: int = DEFAULT_CHAIN_ID,
    auction_address: str = DEFAULT_AUCTION,
    block_number: int,
    want_token: str | None = DEFAULT_WANT_TOKEN,
    governance: str | None = DEFAULT_GOVERNANCE,
    receiver: str | None = DEFAULT_RECEIVER,
    starting_price_raw: str | None = "100",
    minimum_price_raw: str | None = "50",
    step_decay_rate_raw: str | None = "25",
    step_duration_raw: str | None = "60",
    auction_length_raw: str | None = "86400",
    extra_params: dict | None = None,
) -> AuctionSnapshot:
    return AuctionSnapshot(
        chain_id=chain_id,
        auction_address=auction_address,
        block_number=block_number,
        want_token=want_token,
        governance=governance,
        receiver=receiver,
        starting_price_raw=starting_price_raw,
        minimum_price_raw=minimum_price_raw,
        step_decay_rate_raw=step_decay_rate_raw,
        step_duration_raw=step_duration_raw,
        auction_length_raw=auction_length_raw,
        extra_params=extra_params or {},
    )


def make_prepared(
    *,
    event_name: str,
    tx_nonce: int,
    block_number: int,
    log_index: int = 0,
    tx_index: int = 0,
    chain_id: int = DEFAULT_CHAIN_ID,
    address: str = DEFAULT_AUCTION,
    auction_address: str | None = None,
    version: str = "1.0.4",
    capability_family: str = "1.0.4",
    payload: dict | None = None,
    snapshot: AuctionSnapshot | None = None,
) -> PreparedEvent:
    raw_log = make_raw(
        chain_id=chain_id,
        tx_nonce=tx_nonce,
        block_number=block_number,
        log_index=log_index,
        tx_index=tx_index,
        address=address,
    )
    return PreparedEvent(
        raw_log=raw_log,
        domain_event=DomainEventRecord(
            chain_id=chain_id,
            block_number=block_number,
            block_hash=raw_log.block_hash,
            tx_hash=raw_log.tx_hash,
            tx_index=tx_index,
            log_index=log_index,
            event_name=event_name,
            address=address,
            auction_address=auction_address or address,
            version=version,
            capability_family=capability_family,
            payload=payload or {},
            timestamp=raw_log.timestamp,
        ),
        snapshot=snapshot,
    )


def make_hydrator(**readers):
    from backend.indexer.hydration import Hydrator

    hydrator = Hydrator(None)
    for name, reader in readers.items():
        setattr(hydrator, name, reader)
    return hydrator
