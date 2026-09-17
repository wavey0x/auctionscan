from __future__ import annotations

from backend.indexer import collection as collection_module
from .helpers import make_hydrator

from backend.indexer.discovery import DiscoveryResult

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

import backend.indexer.runtime as runtime_module
from backend.indexer.runtime import IndexerRuntime
from backend.indexer.types import ChainConfig, FactorySeed, IndexedBlockRecord, TokenMetadata
from backend.indexer.writer import Writer

from .helpers import (
    DEFAULT_AUCTION,
    DEFAULT_FACTORY,
    DEFAULT_FROM_TOKEN,
    DEFAULT_RECEIVER,
    DEFAULT_WANT_TOKEN,
    make_prepared,
    make_snapshot,
)


ORPHAN_AUCTION = "0x0000000000000000000000000000000000000f0f"


def _hash(label: str) -> str:
    if label.startswith("old-"):
        return f"0x{int(label[4:]):064x}"
    return f"0x{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _header(block_number: int, label: str, parent_label: str) -> IndexedBlockRecord:
    return IndexedBlockRecord(
        chain_id=1,
        block_number=block_number,
        block_hash=_hash(label),
        parent_hash=_hash(parent_label),
        timestamp=1_700_000_000 + block_number,
    )


class _MutableChain:
    def __init__(self, config: ChainConfig, *, latest_heads: list[int], headers: dict[int, IndexedBlockRecord]) -> None:
        self.config = config
        self._latest_heads = iter(latest_heads)
        self.headers = headers

    def latest_head(self) -> int:
        return next(self._latest_heads)

    finality_mode = "confirmations"

    def confirmed_header(self, latest_head: int):
        return self.block_header(max(0, latest_head - self.config.finality_depth))

    def block_header(self, block_number: int) -> IndexedBlockRecord:
        return self.headers[block_number]

    def block_timestamp(self, block_number: int) -> int:
        return self.headers[block_number].timestamp


def _factory_seed(start_block: int = 100) -> FactorySeed:
    return FactorySeed(
        address=DEFAULT_FACTORY,
        version="1.0.4",
        capability_family="1.0.4",
        start_block=start_block,
        deploy_block=start_block,
        deploy_block_source="config",
        discovery_source="config",
        enabled=True,
    )


def _window_events(mapping: dict[int, list], from_block: int, to_block: int, chain=None) -> list:
    events = []
    for block_number in range(from_block, to_block + 1):
        for item in mapping.get(block_number, ()):
            block_hash = chain.block_header(block_number).block_hash if chain else f"0x{block_number:064x}"
            events.append(replace(item,
                raw_log=replace(item.raw_log, block_number=block_number, block_hash=block_hash),
                domain_event=replace(item.domain_event, block_number=block_number, block_hash=block_hash)))
    return events


def _build_runtime(
    tmp_path,
    *,
    latest_heads: list[int],
    finality_depth: int = 2,
    headers: dict[int, IndexedBlockRecord],
    factory_events_by_block: dict[int, list] | None = None,
    auction_events_by_block: dict[int, list] | None = None,
    take_events_by_block: dict[int, list] | None = None,
    monkeypatch,
) -> tuple[IndexerRuntime, _MutableChain]:
    config = ChainConfig(
        name="ethereum",
        chain_id=1,
        rpc_url="http://localhost:8545",
        enabled=True,
        finality_depth=finality_depth,
        block_batch_size=10_000,
        poll_interval_seconds=1.0,
        factories=(),
    )
    chain = _MutableChain(config, latest_heads=latest_heads, headers=headers)
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime.settings = SimpleNamespace(versions={}, chains={"ethereum": config})
    runtime.network_name = "ethereum"
    runtime.chain_config = config
    runtime.writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    runtime.chain = chain
    runtime.discovery_chain = chain
    runtime.pricing = None
    runtime.abi_registry = object()
    runtime.hydrator = make_hydrator(
        read_token_metadata=lambda chain, token, block_number: TokenMetadata(
            chain_id=chain.config.chain_id,
            token_address=token,
            symbol=None,
            name=None,
            decimals=6 if token == DEFAULT_WANT_TOKEN else 18,
        )
    )
    runtime.discoverer = SimpleNamespace(
        refresh_factories=lambda _chain, confirmed_head, known_factories: DiscoveryResult([_factory_seed()], [])
    )
    monkeypatch.setattr(
        collection_module,
        "scan_factory_events",
        lambda _chain, _registry, _hydrator, _tracked_factories, from_block, to_block: _window_events(
            factory_events_by_block or {}, from_block, to_block, _chain
        ),
    )
    monkeypatch.setattr(
        collection_module,
        "scan_auction_events",
        lambda _chain, _registry, _hydrator, _tracked_auctions, from_block, to_block: _window_events(
            auction_events_by_block or {}, from_block, to_block, _chain
        ),
    )
    runtime.take_detector = SimpleNamespace(
        scan_window=lambda _chain, _conn, from_block, to_block, native_events=(): (
            [],
            _window_events(take_events_by_block or {}, from_block, to_block, _chain),
        ),
        replay_chain=lambda _chain, _conn: [],
    )
    runtime._refresh_receiver_aliases = lambda _prepared_events: None
    return runtime, chain


def _base_events():
    deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=1,
        block_number=100,
        address=DEFAULT_FACTORY,
        auction_address=DEFAULT_AUCTION,
        payload={"want": DEFAULT_WANT_TOKEN},
        snapshot=make_snapshot(block_number=100),
    )
    enabled = make_prepared(
        event_name="AuctionEnabled",
        tx_nonce=2,
        block_number=101,
        payload={"from": DEFAULT_FROM_TOKEN, "to": DEFAULT_WANT_TOKEN},
    )
    kicked = make_prepared(
        event_name="AuctionKicked",
        tx_nonce=3,
        block_number=102,
        payload={"from": DEFAULT_FROM_TOKEN, "available": 500},
        snapshot=make_snapshot(block_number=102),
    )
    take_old = make_prepared(
        event_name="Take",
        tx_nonce=4,
        block_number=104,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": "0x0000000000000000000000000000000000000abc",
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200,
            "amountPaid": 150,
            "expectedAmountPaid": 150,
            "priceE18": 750_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )
    take_new = make_prepared(
        event_name="Take",
        tx_nonce=40,
        block_number=104,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": "0x0000000000000000000000000000000000000def",
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 180,
            "amountPaid": 140,
            "expectedAmountPaid": 140,
            "priceE18": 777_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )
    orphan_deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=5,
        block_number=103,
        address=DEFAULT_FACTORY,
        auction_address=ORPHAN_AUCTION,
        payload={"want": DEFAULT_WANT_TOKEN},
        snapshot=make_snapshot(block_number=103, auction_address=ORPHAN_AUCTION),
    )
    return {
        "deployment": deployment,
        "enabled": enabled,
        "kicked": kicked,
        "take_old": take_old,
        "take_new": take_new,
        "orphan_deployment": orphan_deployment,
    }


def _base_headers() -> dict[int, IndexedBlockRecord]:
    return {
        100: _header(100, "old-100", "old-099"),
        101: _header(101, "old-101", "old-100"),
        102: _header(102, "old-102", "old-101"),
        103: _header(103, "old-103", "old-102"),
        104: _header(104, "old-104", "old-103"),
        105: _header(105, "old-105", "old-104"),
    }


def test_near_tip_continues_without_reorg_and_stores_gapless_live_tail(tmp_path, *, monkeypatch):
    events = _base_events()
    headers = _base_headers()
    runtime, _chain = _build_runtime(
        tmp_path,
        latest_heads=[103, 103, 103],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={103: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )

    assert runtime.sync_chain_once() == 2
    assert runtime.sync_chain_once() == 2
    assert runtime.sync_chain_once() == 0

    state = runtime.writer.fetchone(
        """
        SELECT confirmed_head, last_confirmed_processed, last_live_processed, health
          FROM sync_state
         WHERE chain_id = 1
        """
    )
    assert dict(state) == {
        "confirmed_head": 101,
        "last_confirmed_processed": 101,
        "last_live_processed": 103,
        "health": "idle",
    }
    indexed_rows = runtime.writer.fetchall(
        "SELECT block_number FROM indexed_blocks WHERE chain_id = 1 AND block_number > (SELECT last_confirmed_processed FROM sync_state WHERE chain_id = 1) ORDER BY block_number ASC"
    )
    assert [int(row["block_number"]) for row in indexed_rows] == [102, 103]
    queue_rows = runtime.writer.fetchall(
        "SELECT entity_kind, take_seq FROM pricing_capture_queue WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [(row["entity_kind"], row["take_seq"]) for row in queue_rows] == [
        ("round_kick_quote", None),
        ("want_token_price", None),
        ("take_quote", 1),
        ("want_token_price", 1),
    ]


def test_short_reorg_rolls_back_live_tip_and_replays_new_branch(tmp_path, *, monkeypatch):
    events = _base_events()
    headers = _base_headers()
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 104],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={104: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )

    runtime.sync_chain_once()
    runtime.sync_chain_once()

    chain.headers[104] = _header(104, "new-104", "old-103")
    runtime.take_detector = SimpleNamespace(
        scan_window=lambda _chain, _conn, from_block, to_block, native_events=(): ([], _window_events({104: [events["take_new"]]}, from_block, to_block, _chain)),
        replay_chain=lambda _chain, _conn: [],
    )

    runtime.sync_chain_once()

    takes = runtime.writer.fetchall(
        "SELECT tx_hash, taker FROM takes WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [(row["tx_hash"], row["taker"]) for row in takes] == [
        (events["take_new"].domain_event.tx_hash, events["take_new"].domain_event.payload["taker"])
    ]
    state = runtime.writer.fetchone(
        "SELECT reorg_count, last_confirmed_processed, last_live_processed FROM sync_state WHERE chain_id = 1"
    )
    assert dict(state) == {
        "reorg_count": 1,
        "last_confirmed_processed": 102,
        "last_live_processed": 104,
    }
    indexed = runtime.writer.fetchall(
        "SELECT block_number, block_hash FROM indexed_blocks WHERE chain_id = 1 AND block_number > (SELECT last_confirmed_processed FROM sync_state WHERE chain_id = 1) ORDER BY block_number ASC"
    )
    assert [(int(row["block_number"]), row["block_hash"]) for row in indexed] == [
        (103, headers[103].block_hash),
        (104, chain.headers[104].block_hash),
    ]
    queue_rows = runtime.writer.fetchall(
        """
        SELECT entity_kind, take_seq, source_tx_hash
          FROM pricing_capture_queue
         WHERE chain_id = 1
         ORDER BY id ASC
        """
    )
    assert [(row["entity_kind"], row["take_seq"], row["source_tx_hash"]) for row in queue_rows] == [
        ("round_kick_quote", None, events["kicked"].domain_event.tx_hash),
        ("want_token_price", None, events["kicked"].domain_event.tx_hash),
        ("take_quote", 1, events["take_new"].domain_event.tx_hash),
        ("want_token_price", 1, events["take_new"].domain_event.tx_hash),
    ]


def test_full_live_tail_reorg_recovers_at_confirmed_boundary(tmp_path, *, monkeypatch):
    events = _base_events()
    headers = _base_headers()
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 104],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]], 103: [events["orphan_deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        monkeypatch=monkeypatch,
    )

    runtime.sync_chain_once()
    runtime.sync_chain_once()

    chain.headers[103] = _header(103, "new-103", "old-102")
    chain.headers[104] = _header(104, "new-104", "new-103")
    monkeypatch.setattr(
        collection_module,
        "scan_factory_events",
        lambda _chain, _registry, _hydrator, _tracked_factories, from_block, to_block: [],
    )

    runtime.sync_chain_once()

    state = runtime.writer.fetchone(
        "SELECT reorg_count, last_confirmed_processed, last_live_processed FROM sync_state WHERE chain_id = 1"
    )
    assert dict(state) == {
        "reorg_count": 1,
        "last_confirmed_processed": 102,
        "last_live_processed": 104,
    }
    indexed = runtime.writer.fetchall(
        "SELECT block_number, block_hash FROM indexed_blocks WHERE chain_id = 1 AND block_number > (SELECT last_confirmed_processed FROM sync_state WHERE chain_id = 1) ORDER BY block_number ASC"
    )
    assert [(int(row["block_number"]), row["block_hash"]) for row in indexed] == [
        (103, chain.headers[103].block_hash),
        (104, chain.headers[104].block_hash),
    ]


def test_orphan_live_tail_deployment_is_removed_after_rebuild(tmp_path, *, monkeypatch):
    events = _base_events()
    headers = _base_headers()
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 104],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]], 103: [events["orphan_deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        monkeypatch=monkeypatch,
    )

    runtime.sync_chain_once()
    runtime.sync_chain_once()
    assert runtime.writer.fetchone(
        "SELECT auction_address FROM tracked_auctions WHERE chain_id = 1 AND auction_address = ?",
        (ORPHAN_AUCTION,),
    ) is not None

    chain.headers[103] = _header(103, "new-103", "old-102")
    chain.headers[104] = _header(104, "new-104", "new-103")
    monkeypatch.setattr(
        collection_module,
        "scan_factory_events",
        lambda _chain, _registry, _hydrator, _tracked_factories, from_block, to_block: [],
    )

    runtime.sync_chain_once()

    assert runtime.writer.fetchone(
        "SELECT auction_address FROM tracked_auctions WHERE chain_id = 1 AND auction_address = ?",
        (ORPHAN_AUCTION,),
    ) is None
    assert runtime.writer.fetchone(
        "SELECT auction_address FROM auctions WHERE chain_id = 1 AND auction_address = ?",
        (ORPHAN_AUCTION,),
    ) is None


def test_divergence_below_confirmed_boundary_raises_fatal_error(tmp_path, *, monkeypatch):
    events = _base_events()
    headers = _base_headers()
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[103, 103, 103],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={103: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )

    runtime.sync_chain_once()
    runtime.sync_chain_once()

    chain.headers[101] = _header(101, "new-101", "old-100")
    chain.headers[102] = _header(102, "new-102", "new-101")
    chain.headers[103] = _header(103, "new-103", "new-102")

    with pytest.raises(RuntimeError, match="confirmed boundary"):
        runtime.sync_chain_once()


def test_live_pricing_is_enqueued_immediately_and_promotion_does_not_duplicate_rows(tmp_path, *, monkeypatch):
    events = _base_events()
    take_on_103 = make_prepared(
        event_name="Take",
        tx_nonce=41,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": "0x0000000000000000000000000000000000000abc",
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200,
            "amountPaid": 150,
            "expectedAmountPaid": 150,
            "priceE18": 750_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )
    headers = _base_headers()
    runtime, _chain = _build_runtime(
        tmp_path,
        latest_heads=[103, 103, 104, 105],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={103: [take_on_103]},
        monkeypatch=monkeypatch,
    )

    runtime.sync_chain_once()
    runtime.sync_chain_once()
    queue_rows = runtime.writer.fetchall(
        "SELECT entity_kind, take_seq FROM pricing_capture_queue WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [(row["entity_kind"], row["take_seq"]) for row in queue_rows] == [
        ("round_kick_quote", None),
        ("want_token_price", None),
        ("take_quote", 1),
        ("want_token_price", 1),
    ]

    runtime.sync_chain_once()
    queue_rows = runtime.writer.fetchall(
        "SELECT entity_kind, take_seq FROM pricing_capture_queue WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [(row["entity_kind"], row["take_seq"]) for row in queue_rows] == [
        ("round_kick_quote", None),
        ("want_token_price", None),
        ("take_quote", 1),
        ("want_token_price", 1),
    ]


def test_promotion_does_not_duplicate_live_pricing_rows(tmp_path, *, monkeypatch):
    events = _base_events()
    headers = _base_headers()
    runtime, _chain = _build_runtime(
        tmp_path,
        latest_heads=[103, 103, 104, 105],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={103: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )

    runtime.sync_chain_once()
    runtime.sync_chain_once()
    runtime.sync_chain_once()

    queue_rows = runtime.writer.fetchall(
        "SELECT entity_kind, take_seq FROM pricing_capture_queue WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [(row["entity_kind"], row["take_seq"]) for row in queue_rows] == [
        ("round_kick_quote", None),
        ("want_token_price", None),
        ("take_quote", 1),
        ("want_token_price", 1),
    ]

    runtime.sync_chain_once()
    queue_rows = runtime.writer.fetchall(
        "SELECT entity_kind, take_seq FROM pricing_capture_queue WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [(row["entity_kind"], row["take_seq"]) for row in queue_rows] == [
        ("round_kick_quote", None),
        ("want_token_price", None),
        ("take_quote", 1),
        ("want_token_price", 1),
    ]


def test_reorg_recovery_deletes_orphaned_take_queue_rows(tmp_path, *, monkeypatch):
    events = _base_events()
    headers = _base_headers()
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 104],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={104: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )

    runtime.sync_chain_once()
    runtime.sync_chain_once()

    queue_before = runtime.writer.fetchall(
        """
        SELECT entity_kind, take_seq, source_tx_hash
          FROM pricing_capture_queue
         WHERE chain_id = 1
         ORDER BY id ASC
        """
    )
    assert [(row["entity_kind"], row["take_seq"], row["source_tx_hash"]) for row in queue_before] == [
        ("round_kick_quote", None, events["kicked"].domain_event.tx_hash),
        ("want_token_price", None, events["kicked"].domain_event.tx_hash),
        ("take_quote", 1, events["take_old"].domain_event.tx_hash),
        ("want_token_price", 1, events["take_old"].domain_event.tx_hash),
    ]
    runtime.writer.transaction(
        lambda conn: conn.executescript(
            f"""
            INSERT INTO take_pricing_source (
                chain_id, auction_address, round_id, take_seq, source_id,
                market_quote_out_raw, pricing_status
            ) VALUES (1, '{DEFAULT_AUCTION}', 1, 1, 'orphan', '1', 'priced');
            INSERT INTO round_pricing_source (
                chain_id, auction_address, round_id, source_id
            ) VALUES (1, '{DEFAULT_AUCTION}', 1, 'orphan');
            """
        )
    )

    chain.headers[104] = _header(104, "new-104", "old-103")
    runtime.take_detector = SimpleNamespace(
        scan_window=lambda _chain, _conn, from_block, to_block, native_events=(): ([], _window_events({104: [events["take_new"]]}, from_block, to_block, _chain)),
        replay_chain=lambda _chain, _conn: [],
    )

    runtime.sync_chain_once()

    queue_after = runtime.writer.fetchall(
        """
        SELECT entity_kind, take_seq, source_tx_hash
          FROM pricing_capture_queue
         WHERE chain_id = 1
         ORDER BY id ASC
        """
    )
    assert [(row["entity_kind"], row["take_seq"], row["source_tx_hash"]) for row in queue_after] == [
        ("round_kick_quote", None, events["kicked"].domain_event.tx_hash),
        ("want_token_price", None, events["kicked"].domain_event.tx_hash),
        ("take_quote", 1, events["take_new"].domain_event.tx_hash),
        ("want_token_price", 1, events["take_new"].domain_event.tx_hash),
    ]
    assert runtime.writer.fetchone(
        "SELECT COUNT(*) AS count FROM take_pricing_source WHERE chain_id = 1"
    )["count"] == 0
    assert runtime.writer.fetchone(
        "SELECT COUNT(*) AS count FROM round_pricing_source WHERE chain_id = 1"
    )["count"] == 0


def test_reorg_recovery_retry_after_transaction_failure_replays_cleanly(tmp_path, monkeypatch):
    events = _base_events()
    headers = _base_headers()
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 104, 104],
        headers=headers,
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={104: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )

    runtime.sync_chain_once()
    runtime.sync_chain_once()

    chain.headers[104] = _header(104, "new-104", "old-103")
    runtime.take_detector = SimpleNamespace(
        scan_window=lambda _chain, _conn, from_block, to_block, native_events=(): ([], _window_events({104: [events["take_new"]]}, from_block, to_block, _chain)),
        replay_chain=lambda _chain, _conn: [],
    )

    original_rebuild = runtime_module.rebuild_pricing_projections
    triggered = {"value": False}

    def failing_rebuild(conn, *, chain_id: int) -> None:
        if not triggered["value"]:
            triggered["value"] = True
            raise RuntimeError("boom during rollback")
        return original_rebuild(conn, chain_id=chain_id)

    monkeypatch.setattr(runtime_module, "rebuild_pricing_projections", failing_rebuild)
    with pytest.raises(RuntimeError, match="boom during rollback"):
        runtime.sync_chain_once()

    takes_after_failure = runtime.writer.fetchall(
        "SELECT tx_hash FROM takes WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [row["tx_hash"] for row in takes_after_failure] == [events["take_old"].domain_event.tx_hash]
    queue_after_failure = runtime.writer.fetchall(
        """
        SELECT entity_kind, take_seq, source_tx_hash
          FROM pricing_capture_queue
         WHERE chain_id = 1
         ORDER BY id ASC
        """
    )
    assert [(row["entity_kind"], row["take_seq"], row["source_tx_hash"]) for row in queue_after_failure] == [
        ("round_kick_quote", None, events["kicked"].domain_event.tx_hash),
        ("want_token_price", None, events["kicked"].domain_event.tx_hash),
        ("take_quote", 1, events["take_old"].domain_event.tx_hash),
        ("want_token_price", 1, events["take_old"].domain_event.tx_hash),
    ]

    monkeypatch.setattr(runtime_module, "rebuild_pricing_projections", original_rebuild)
    runtime.sync_chain_once()

    takes_after_retry = runtime.writer.fetchall(
        "SELECT tx_hash FROM takes WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [row["tx_hash"] for row in takes_after_retry] == [events["take_new"].domain_event.tx_hash]
    queue_after_retry = runtime.writer.fetchall(
        """
        SELECT entity_kind, take_seq, source_tx_hash
          FROM pricing_capture_queue
         WHERE chain_id = 1
         ORDER BY id ASC
        """
    )
    assert [(row["entity_kind"], row["take_seq"], row["source_tx_hash"]) for row in queue_after_retry] == [
        ("round_kick_quote", None, events["kicked"].domain_event.tx_hash),
        ("want_token_price", None, events["kicked"].domain_event.tx_hash),
        ("take_quote", 1, events["take_new"].domain_event.tx_hash),
        ("want_token_price", 1, events["take_new"].domain_event.tx_hash),
    ]


def test_real_chain_adapter_observes_changed_header(tmp_path, *, monkeypatch):
    from backend.indexer.chains import ChainState

    events = _base_events()
    runtime, mutable = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 104],
        headers=_base_headers(),
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={104: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )

    class Eth:
        @property
        def block_number(self):
            return mutable.latest_head()

        def get_block(self, number):
            if number == "finalized":
                number = 102
            header = mutable.block_header(number)
            return {"number": header.block_number, "hash": header.block_hash,
                    "parentHash": header.parent_hash, "timestamp": header.timestamp}

    runtime.chain = ChainState(mutable.config, SimpleNamespace(eth=Eth()))
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    mutable.headers[104] = _header(104, "replacement-104", "old-103")
    runtime.take_detector.scan_window = lambda *_args, **_kwargs: ([], [])
    runtime.sync_chain_once()
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM takes")[0] == 0
    assert runtime.writer.fetchone("SELECT reorg_count FROM sync_state")[0] == 1


def test_shorter_replacement_chain_removes_missing_tip(tmp_path, *, monkeypatch):
    events = _base_events()
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 103],
        headers=_base_headers(),
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={104: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    del chain.headers[104]
    runtime.sync_chain_once()
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM takes")[0] == 0
    assert runtime.writer.fetchone("SELECT last_live_processed FROM sync_state")[0] == 103


@pytest.mark.parametrize("takes_only", [False, True])
def test_replay_failure_preserves_all_projections_and_sync_metadata(tmp_path, monkeypatch, takes_only):
    events = _base_events()
    runtime, _chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104],
        headers=_base_headers(),
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={104: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    runtime.writer.transaction(lambda conn: conn.execute(
        "UPDATE sync_state SET health = 'error', last_error = 'previous RPC failure', last_success_at = 12"))
    tables = ["takes", "rounds", "auctions", "taker_summary", "domain_events", "sync_state", "pricing_capture_queue"]
    before = {table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")] for table in tables}
    monkeypatch.setattr(runtime_module, "rebuild_pricing_projections", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("repair failed")))
    with pytest.raises(RuntimeError, match="repair failed"):
        runtime.reproject_chain(takes_only=takes_only)
    after = {table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")] for table in tables}
    assert after == before


RECOVERY_PROJECTIONS = (
    "auctions",
    "tracked_auctions",
    "tokens",
    "auction_tokens",
    "auction_current_params",
    "auction_param_history",
    "rounds",
    "takes",
    "taker_summary",
    "take_pricing",
    "round_pricing",
    "take_pricing_source",
    "round_pricing_source",
    "taker_pricing_summary",
)


def _projection_values(writer):
    result = {}
    for table in RECOVERY_PROJECTIONS:
        rows = []
        for row in writer.fetchall(f"SELECT * FROM {table}"):
            values = dict(row)
            for key in ("created_at", "updated_at", "metadata_updated_at"):
                values.pop(key, None)
            if table in {"auction_param_history", "takes"}:
                values.pop("id", None)
            rows.append(values)
        result[table] = rows
    return result


def _event_free_recovery_runtime(tmp_path, monkeypatch, scenario="live", *, available=500):
    from backend.indexer.facts import persist_raw_logs
    from backend.indexer.pricing import PricingCaptureRuntime
    from .helpers import capture_due_pricing
    from .test_pricing import _FakePricingClient

    events = _base_events()
    events["kicked"] = replace(
        events["kicked"],
        domain_event=replace(
            events["kicked"].domain_event, payload={"from": DEFAULT_FROM_TOKEN, "available": available}
        ),
    )
    if scenario in {"expiry", "swept_expired"}:
        events["kicked"] = replace(
            events["kicked"],
            snapshot=replace(
                events["kicked"].snapshot,
                auction_length_raw="3" if scenario == "expiry" else "1",
            ),
        )
    if scenario in {"sold_out", "swept_sold_out"}:
        take = events["take_old"]
        events["take_old"] = replace(
            take,
            domain_event=replace(
                take.domain_event,
                payload={
                    **take.domain_event.payload,
                    "amountTaken": 500,
                },
            ),
        )
    factories = {100: [events["deployment"]]}
    auctions = {101: [events["enabled"]], 102: [events["kicked"]]}
    takes = {} if scenario == "swept_expired" else {104: [events["take_old"]]}
    if scenario.startswith("swept"):
        auctions[105] = [
            make_prepared(
                event_name="AuctionSwept",
                tx_nonce=77,
                block_number=105,
                payload={"token": DEFAULT_FROM_TOKEN},
            )
        ]
    elif scenario == "settled":
        auctions[105] = [
            make_prepared(
                event_name="AuctionSettled",
                tx_nonce=77,
                block_number=105,
                payload={"from": DEFAULT_FROM_TOKEN},
            )
        ]
    headers = {**_base_headers(), 106: _header(106, "old-106", "old-105")}
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 105, 106, 106],
        headers=headers,
        factory_events_by_block=factories,
        auction_events_by_block=auctions,
        take_events_by_block=takes,
        monkeypatch=monkeypatch,
    )
    # Match the real collector: token observations must exist before comparing
    # preserved projections to metadata reconstructed by offline replay.
    for mapping in (factories, auctions, takes):
        for number, batch in mapping.items():
            mapping[number] = [
                replace(event, token_metadata=runtime.hydrator.read_event_token_metadata(chain, event))
                for event in batch
            ]
    for _ in range(4):
        runtime.sync_chain_once()
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, runtime.writer, chain_id=1)
    pricing.discard()
    from backend.indexer.takes import TRANSFER_TOPIC

    rejected = replace(
        make_prepared(event_name="Take", tx_nonce=999, block_number=106).raw_log, topic0=TRANSFER_TOPIC
    )
    runtime.writer.transaction(
        lambda conn: (
            persist_raw_logs(conn, [rejected]),
            conn.execute(
                """INSERT INTO rpc_observations
            (chain_id, block_number, block_hash, kind, subject, status, result_json)
            VALUES (1, 106, ?, 'transaction', ?, 'ok', '{}')""",
                (rejected.block_hash, rejected.tx_hash),
            ),
        )
    )
    return runtime, chain


def _recover_at_105(runtime, *, record_reorg=True):
    runtime.writer.transaction(
        lambda conn: runtime._recover_live_tail_reorg(
            conn,
            ancestor_block=105,
            latest_rpc_head=106,
            confirmed_head=104,
            last_confirmed_processed=104,
            record_reorg=record_reorg,
        )
    )


@pytest.mark.parametrize(
    "scenario,status,end,settled",
    [
        ("live", "live", 86502, None),
        ("expiry", "live", 105, None),
        ("sold_out", "sold_out", 104, None),
        ("settled", "settled", 86502, 105),
        ("swept_expired", "settled", 103, 105),
        ("swept_sold_out", "sold_out", 104, 105),
    ],
)
def test_event_free_recovery_matches_full_repair_without_replay(
    tmp_path, monkeypatch, scenario, status, end, settled, caplog
):
    import copy
    import sqlite3
    from unittest.mock import patch

    runtime, chain = _event_free_recovery_runtime(tmp_path, monkeypatch, scenario)
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM domain_events WHERE block_number > 105")[0] == 0
    if scenario == "expiry":
        assert runtime.writer.fetchone("SELECT status FROM rounds")[0] == "expired"
    price_tables = (
        "pricing_quote_facts",
        "pricing_quote_provider_facts",
        "pricing_price_facts",
        "pricing_price_provider_facts",
    )
    facts = {
        table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")]
        for table in price_tables
    }
    assert facts["pricing_quote_facts"]
    copy_path = tmp_path / "reference.sqlite3"
    with sqlite3.connect(copy_path) as destination:
        runtime.writer.connection.backup(destination)
    reference = copy.copy(runtime)
    reference.writer = Writer(str(copy_path))
    reference.chain = copy.copy(chain)
    # Maintenance deliberately forces full repair on the independent copy.
    with patch.object(
        runtime_module.replay, "load_native_events", wraps=runtime_module.replay.load_native_events
    ) as native:
        _recover_at_105(reference, record_reorg=False)
        assert native.call_count == 1

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Event-free recovery attempted historical replay")

    with monkeypatch.context() as guard, caplog.at_level("INFO"):
        guard.setattr(runtime_module, "clear_rebuildable_chain_state", unexpected)
        guard.setattr(runtime_module.replay, "load_native_events", unexpected)
        guard.setattr(runtime_module.replay, "load_take_events", unexpected)
        guard.setattr(runtime_module, "rebuild_pricing_projections", unexpected)
        _recover_at_105(runtime)
    assert _projection_values(runtime.writer) == _projection_values(reference.writer)
    assert tuple(runtime.writer.fetchone("SELECT status, end_at, settled_at FROM rounds")) == (
        status,
        1700000000 + end,
        None if settled is None else 1700000000 + settled,
    )
    for table in (
        "chain_logs",
        "domain_events",
        "indexed_blocks",
        "rpc_observations",
        "round_param_snapshot",
        "auction_snapshot_facts",
    ):
        assert [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")] == [
            tuple(row) for row in reference.writer.fetchall(f"SELECT * FROM {table}")
        ]
    for table in price_tables:
        for writer in (runtime.writer, reference.writer):
            assert [tuple(row) for row in writer.fetchall(f"SELECT * FROM {table}")] == facts[table]
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM chain_logs WHERE block_number > 105")[0] == 0
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM rpc_observations WHERE block_number > 105")[0] == 0
    state = runtime._load_sync_state_row()
    assert (
        state["last_confirmed_processed"],
        state["last_live_processed"],
        state["reorg_count"],
        state["health"],
    ) == (104, 105, 1, "ok")
    assert state["last_confirmed_hash"] == chain.headers[104].block_hash
    assert reference._load_sync_state_row()["reorg_count"] == 0
    assert "replay_skipped=True" in caplog.text and "pricing_rebuild_seconds=0.000000" in caplog.text
    if scenario == "expiry":
        chain.headers[106] = _header(106, "replacement-106", "old-105")
        runtime.sync_chain_once()
        assert runtime.writer.fetchone("SELECT status FROM rounds")[0] == "expired"
        assert runtime._load_sync_state_row()["last_live_processed"] == 106


@pytest.mark.parametrize("failure", ["before_commit", "missing_header"])
def test_event_free_recovery_rolls_back_every_mutation(tmp_path, monkeypatch, failure):
    from backend.indexer.observations import MissingObservation

    runtime, _ = _event_free_recovery_runtime(tmp_path, monkeypatch, "expiry")
    if failure == "missing_header":
        runtime.writer.transaction(
            lambda conn: conn.execute("DELETE FROM indexed_blocks WHERE block_number = 105")
        )
    else:
        original = runtime._update_state

        def fail(conn, **kwargs):
            original(conn, **kwargs)
            raise RuntimeError("failed before commit")

        monkeypatch.setattr(runtime, "_update_state", fail)
    before = list(runtime.writer.connection.iterdump())
    with pytest.raises(
        (MissingObservation, RuntimeError), match="Missing ancestor timestamp|failed before commit"
    ):
        _recover_at_105(runtime)
    assert list(runtime.writer.connection.iterdump()) == before


@pytest.mark.parametrize("event_name", ["Take", "UpdatedStartingPrice"])
def test_any_removed_domain_event_requires_full_recovery(tmp_path, monkeypatch, event_name):
    from unittest.mock import patch
    from backend.indexer.projections import apply_batch

    runtime, _ = _event_free_recovery_runtime(tmp_path, monkeypatch)
    expected = _projection_values(runtime.writer)
    if event_name == "Take":
        take = _base_events()["take_new"]
        removed = replace(
            take,
            raw_log=replace(take.raw_log, block_number=106, block_hash=_hash("old-106")),
            domain_event=replace(
                take.domain_event, block_number=106, block_hash=_hash("old-106"), timestamp=1700000106
            ),
        )
    else:
        removed = make_prepared(
            event_name=event_name, tx_nonce=98, block_number=106, payload={"startingPrice": 999}
        )
    runtime.writer.transaction(lambda conn: apply_batch(conn, [removed]))
    assert [
        row[0]
        for row in runtime.writer.fetchall("SELECT event_name FROM domain_events WHERE block_number > 105")
    ] == [event_name]
    with patch.object(
        runtime_module.replay, "load_native_events", wraps=runtime_module.replay.load_native_events
    ) as native:
        _recover_at_105(runtime)
        assert native.call_count == 1
    assert _projection_values(runtime.writer) == expected


@pytest.mark.parametrize("history_size", [20, 1000])
def test_recovery_paths_agree_as_take_history_grows(tmp_path, monkeypatch, history_size):
    """Also provides a repeatable local timing sample with pytest -s; no latency gate."""
    import copy
    import sqlite3
    import time
    from backend.indexer.facts import upsert_indexed_blocks
    from backend.indexer.projections import apply_batch
    from backend.indexer.pricing_projections import rebuild_pricing_projections

    runtime, chain = _event_free_recovery_runtime(tmp_path, monkeypatch, available=history_size + 500)
    template = _base_events()["take_old"]
    takes = []
    headers = []
    for i in range(history_size):
        number = 107 + i
        header = _header(number, f"old-{number}", f"old-{number - 1}")
        headers.append(header)
        event = make_prepared(
            event_name="Take",
            tx_nonce=10000 + i,
            block_number=number,
            log_index=4,
            payload={
                **template.domain_event.payload,
                "amountTaken": 1,
                "amountPaid": 1,
                "expectedAmountPaid": 1,
            },
        )
        takes.append(replace(event, token_metadata=runtime.hydrator.read_event_token_metadata(chain, event)))
    tip = 107 + history_size
    headers.append(_header(tip, f"old-{tip}", f"old-{tip - 1}"))
    runtime.writer.transaction(
        lambda conn: (
            upsert_indexed_blocks(conn, headers),
            apply_batch(conn, takes),
            rebuild_pricing_projections(conn, chain_id=1),
            conn.execute("UPDATE sync_state SET last_live_processed = ?", (tip,)),
        )
    )

    def clone(name):
        destination_path = tmp_path / f"{name}.sqlite3"
        with sqlite3.connect(destination_path) as destination:
            runtime.writer.connection.backup(destination)
        result = copy.copy(runtime)
        result.writer = Writer(str(destination_path))
        result.chain = copy.copy(chain)
        return result

    empty_reference, removed, removed_reference = (
        clone(name) for name in ("empty-full", "removed", "removed-full")
    )
    for label, target, ancestor, recorded in (
        ("empty-fast", runtime, tip - 1, True),
        ("empty-full", empty_reference, tip - 1, False),
        ("take-full", removed, tip - 2, True),
        ("take-reference", removed_reference, tip - 2, False),
    ):
        started = time.perf_counter()
        target.writer.transaction(
            lambda conn: target._recover_live_tail_reorg(
                conn,
                ancestor_block=ancestor,
                latest_rpc_head=tip,
                confirmed_head=104,
                last_confirmed_processed=104,
                record_reorg=recorded,
            )
        )
        print(
            f"recovery sample added_takes={history_size} path={label} seconds={time.perf_counter() - started:.6f}"
        )
    assert _projection_values(runtime.writer) == _projection_values(empty_reference.writer)
    assert _projection_values(removed.writer) == _projection_values(removed_reference.writer)
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM takes")[0] == history_size + 1
    assert removed.writer.fetchone("SELECT COUNT(*) FROM takes")[0] == history_size
