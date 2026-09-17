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
