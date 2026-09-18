from __future__ import annotations

from backend.indexer import collection as collection_module

from backend.indexer.discovery import DiscoveryResult

import logging
from types import SimpleNamespace

import backend.indexer.runtime as runtime_module
import pytest
from backend.indexer.address_aliases import AddressAliasUpdate
from backend.indexer.hydration import Hydrator
from backend.indexer.runtime import IndexerRuntime
from backend.indexer.types import (
    ChainConfig,
    DomainEventRecord,
    FactorySeed,
    IndexedBlockRecord,
    TokenMetadata,
    normalize_address,
    normalize_hex,
)
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


class _FakeChain:
    def __init__(self, config: ChainConfig, latest_heads: list[int]) -> None:
        self.config = config
        self._latest_heads = iter(latest_heads)

    def latest_head(self) -> int:
        return next(self._latest_heads)

    finality_mode = "confirmations"

    def confirmed_header(self, latest_head: int):
        return self.block_header(latest_head)

    def block_header(self, block_number: int) -> IndexedBlockRecord:
        return IndexedBlockRecord(
            chain_id=self.config.chain_id,
            block_number=block_number,
            block_hash=f"0x{block_number:064x}",
            parent_hash=f"0x{max(0, block_number - 1):064x}",
            timestamp=1_700_000_000 + block_number,
        )

    def block_timestamp(self, block_number: int) -> int:
        return 1_700_000_000 + block_number


def _factory_seed(start_block: int, source: str = "config") -> FactorySeed:
    return FactorySeed(
        address=DEFAULT_FACTORY,
        version="1.0.4",
        capability_family="1.0.4",
        start_block=start_block,
        deploy_block=start_block,
        deploy_block_source=source,
        discovery_source="registry",
        enabled=True,
    )


def _build_runtime(tmp_path, *, latest_heads: list[int], monkeypatch) -> tuple[IndexerRuntime, _FakeChain]:
    config = ChainConfig(
        name="ethereum",
        chain_id=1,
        rpc_url="http://localhost:8545",
        finality_depth=0,
        block_batch_size=1_000,
        poll_interval_seconds=1.0,
        factories=(),
    )
    chain = _FakeChain(config, latest_heads)
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime.settings = SimpleNamespace(versions={}, chains={"ethereum": config})
    runtime.network_name = "ethereum"
    runtime.chain_config = config
    runtime.writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    runtime.abi_registry = object()
    runtime.hydrator = object()
    runtime.take_detector = SimpleNamespace(
        scan_window=lambda _chain, _conn, from_block, to_block, native_events=(): ([], []),
        replay_chain=lambda _chain, _conn: [],
    )
    runtime.chain = chain
    runtime.discovery_chain = chain
    runtime._factory_seeds = None
    runtime._factory_refresh_attempted_at = None
    runtime._factory_refresh_interval_seconds = runtime_module.FACTORY_REFRESH_INTERVAL_SECONDS
    return runtime, chain


class _AuctionScanRegistry:
    def __init__(self) -> None:
        self.events = {
            "v1": {"AuctionKicked": "0x01"},
            "v2": {"AuctionEnabled": "0x02"},
        }
        self.decode_calls: list[tuple[str, str]] = []

    def version_definition(self, version: str):
        return SimpleNamespace(supported_events=tuple(self.events[version]))

    def auction_event_topic(self, version: str, event_name: str) -> str:
        return self.events[version][event_name]

    def decode_auction_log(self, _w3, version: str, log, *, chain_id: int, timestamp: int):
        topic0 = normalize_hex(log["topics"][0])
        event_name = next(
            name for name, topic in self.events[version].items() if topic == topic0
        )
        self.decode_calls.append((version, topic0))
        payload = (
            {"from": DEFAULT_FROM_TOKEN}
            if event_name == "AuctionKicked"
            else {"from": DEFAULT_FROM_TOKEN, "to": DEFAULT_WANT_TOKEN}
        )
        return DomainEventRecord(
            chain_id=chain_id,
            block_number=int(log["blockNumber"]),
            block_hash=normalize_hex(log["blockHash"]),
            tx_hash=normalize_hex(log["transactionHash"]),
            tx_index=int(log.get("transactionIndex", 0)),
            log_index=int(log["logIndex"]),
            event_name=event_name,
            address=normalize_address(log["address"]),
            auction_address=normalize_address(log["address"]),
            version=version,
            capability_family=version,
            payload=payload,
            timestamp=timestamp,
        )


class _AuctionScanHydrator(Hydrator):
    def __init__(self) -> None:
        self.snapshot_calls: list[tuple[str, str, int]] = []
        self.metadata_calls: list[tuple[str, int]] = []

    def read_auction_snapshot(
        self,
        _chain,
        version: str,
        auction_address: str,
        block_number: int,
        *,
        event_payload,
    ):
        self.snapshot_calls.append((version, auction_address, block_number))
        return make_snapshot(
            auction_address=auction_address,
            block_number=block_number,
            want_token=None,
        )

    def read_token_metadata(self, chain, token_address: str, *, block_number: int):
        self.metadata_calls.append((token_address, block_number))
        return TokenMetadata(
            chain_id=chain.config.chain_id,
            token_address=token_address,
            symbol=None,
            name=None,
            decimals=None,
        )


def _auction_rpc_log(
    *,
    address: str,
    topic0: str,
    block_number: int,
    tx_index: int = 0,
    log_index: int = 0,
):
    nonce = block_number * 100 + log_index
    return {
        "address": address,
        "topics": [topic0],
        "data": "0x",
        "blockNumber": block_number,
        "blockHash": f"0x{block_number:064x}",
        "transactionHash": f"0x{nonce:064x}",
        "transactionIndex": tx_index,
        "logIndex": log_index,
    }


def test_auction_scan_combines_topics_filters_false_positives_and_preserves_order(monkeypatch):
    first_auction = "0x0000000000000000000000000000000000000101"
    second_auction = "0x0000000000000000000000000000000000000102"
    registry = _AuctionScanRegistry()
    hydrator = _AuctionScanHydrator()
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime.abi_registry = registry
    runtime.hydrator = hydrator
    chain = SimpleNamespace(
        config=SimpleNamespace(chain_id=1),
        w3=object(),
        block_timestamp=lambda block_number: 1_700_000_000 + block_number,
    )
    fetch_calls = []

    def fake_fetch_logs(_w3, **kwargs):
        fetch_calls.append(kwargs)
        return [
            _auction_rpc_log(
                address=first_auction,
                topic0="0x01",
                block_number=12,
                log_index=2,
            ),
            _auction_rpc_log(
                address=first_auction,
                topic0="0x02",
                block_number=10,
                log_index=1,
            ),
            _auction_rpc_log(
                address=second_auction,
                topic0="0x02",
                block_number=11,
                log_index=3,
            ),
        ]

    monkeypatch.setattr(collection_module, "fetch_logs", fake_fetch_logs)

    prepared = collection_module.scan_auction_events(
        chain,
        runtime.abi_registry,
        runtime.hydrator,
        [
            {"auction_address": first_auction.upper(), "version": "v1"},
            {"auction_address": second_auction, "version": "v2"},
        ],
        10,
        12,
    )

    assert len(fetch_calls) == 1
    assert fetch_calls[0]["address"] == [first_auction, second_auction]
    assert fetch_calls[0]["topics"] == [["0x01", "0x02"]]
    assert [item.domain_event.event_name for item in prepared] == [
        "AuctionEnabled",
        "AuctionKicked",
    ]
    assert [item.raw_log.block_number for item in prepared] == [11, 12]
    assert registry.decode_calls == [("v2", "0x02"), ("v1", "0x01")]
    assert hydrator.snapshot_calls == [("v1", first_auction, 12)]
    assert hydrator.metadata_calls == [
        (DEFAULT_FROM_TOKEN, 11),
        (DEFAULT_WANT_TOKEN, 11),
        (DEFAULT_FROM_TOKEN, 12),
    ]


def test_auction_scan_uses_three_filters_for_production_shaped_addresses(monkeypatch):
    registry = _AuctionScanRegistry()
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime.abi_registry = registry
    runtime.hydrator = _AuctionScanHydrator()
    chain = SimpleNamespace(
        config=SimpleNamespace(chain_id=1),
        w3=object(),
        block_timestamp=lambda block_number: block_number,
    )
    tracked = [
        {
            "auction_address": f"0x{index + 1:040x}",
            "version": "v1" if index % 2 == 0 else "v2",
        }
        for index in range(261)
    ]
    fetch_calls = []

    def fake_fetch_logs(_w3, **kwargs):
        fetch_calls.append(kwargs)
        return []

    monkeypatch.setattr(collection_module, "fetch_logs", fake_fetch_logs)

    assert (
        collection_module.scan_auction_events(chain, runtime.abi_registry, runtime.hydrator, tracked, 1, 100)
        == []
    )
    assert [len(call["address"]) for call in fetch_calls] == [100, 100, 61]
    assert {tuple(call["topics"][0]) for call in fetch_calls} == {("0x01", "0x02")}


def test_sync_chain_once_advances_cursor_and_idles_without_new_blocks(tmp_path, *, monkeypatch):
    runtime, chain = _build_runtime(tmp_path, latest_heads=[101, 101], monkeypatch=monkeypatch)
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
    runtime.discoverer = SimpleNamespace(
        refresh_factories=lambda _chain, confirmed_head, known_factories: DiscoveryResult([_factory_seed(100)], [])
    )
    scan_ranges = []

    def scan_factory_events(_chain, _registry, _hydrator, _tracked_factories, from_block, to_block):
        scan_ranges.append(("factory", from_block, to_block))
        return [deployment]

    def scan_auction_events(_chain, _registry, _hydrator, tracked_auctions, from_block, to_block):
        scan_ranges.append(("auction", from_block, to_block, len(tracked_auctions)))
        return [enabled]

    monkeypatch.setattr(collection_module, "scan_factory_events", scan_factory_events)
    monkeypatch.setattr(collection_module, "scan_auction_events", scan_auction_events)

    inserted = runtime.sync_chain_once()
    idle_inserted = runtime.sync_chain_once()

    assert inserted == 2
    assert idle_inserted == 0
    assert scan_ranges == [("factory", 100, 101), ("auction", 100, 101, 1)]

    sync_state = runtime.writer.fetchone(
        """
        SELECT last_confirmed_processed, last_live_processed, latest_rpc_head, confirmed_head, health
          FROM sync_state
         WHERE chain_id = 1
        """
    )
    assert dict(sync_state) == {
        "last_confirmed_processed": 101,
        "last_live_processed": 101,
        "latest_rpc_head": 101,
        "confirmed_head": 101,
        "health": "idle",
    }

    event_count = runtime.writer.fetchone("SELECT COUNT(*) AS count FROM domain_events")
    assert event_count["count"] == 2


def test_sync_chain_once_rewinds_when_factory_start_moves_earlier(tmp_path, *, monkeypatch):
    runtime, chain = _build_runtime(tmp_path, latest_heads=[100, 105], monkeypatch=monkeypatch)
    runtime._factory_refresh_interval_seconds = 0
    factory_sequences = iter([[_factory_seed(100)], [_factory_seed(80, source="binary_search")]])
    runtime.discoverer = SimpleNamespace(
        refresh_factories=lambda _chain, confirmed_head, known_factories: DiscoveryResult(next(factory_sequences), [])
    )
    scan_ranges = []

    def scan_factory_events(_chain, _registry, _hydrator, _tracked_factories, from_block, to_block):
        scan_ranges.append((from_block, to_block))
        return []

    monkeypatch.setattr(collection_module, "scan_factory_events", scan_factory_events)
    monkeypatch.setattr(
        collection_module,
        "scan_auction_events",
        lambda _chain, _registry, _hydrator, _tracked_auctions, from_block, to_block: [],
    )

    first = runtime.sync_chain_once()
    second = runtime.sync_chain_once()

    assert first == 0
    assert second == 0
    assert scan_ranges == [(100, 100), (80, 105)]

    tracked_factory = runtime.writer.fetchone(
        """
        SELECT start_block, deploy_block, deploy_block_source
          FROM tracked_factories
         WHERE chain_id = 1 AND factory_address = ?
        """,
        (DEFAULT_FACTORY,),
    )
    assert dict(tracked_factory) == {
        "start_block": 80,
        "deploy_block": 80,
        "deploy_block_source": "binary_search",
    }

    sync_state = runtime.writer.fetchone(
        "SELECT last_confirmed_processed, last_live_processed FROM sync_state WHERE chain_id = 1"
    )
    assert dict(sync_state) == {
        "last_confirmed_processed": 105,
        "last_live_processed": 105,
    }


def test_factory_refresh_uses_attempt_cadence_and_preserves_success_on_failure(tmp_path, monkeypatch):
    import json

    runtime, chain = _build_runtime(tmp_path, latest_heads=[100], monkeypatch=monkeypatch)
    clock = [1000]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime_module.time, "time", lambda: clock[0])
    calls = []
    problem = {"factory_address": DEFAULT_FACTORY, "code": "unsupported_version", "version": "9.9.9"}
    def refresh(_chain, confirmed_head, known_factories):
        calls.append(confirmed_head)
        return DiscoveryResult([_factory_seed(100)], [problem]) if len(calls) == 1 else DiscoveryResult(known_factories, [], "Registry lookup failed")
    runtime.discoverer = SimpleNamespace(refresh_factories=refresh)
    assert runtime._refresh_factory_seeds(chain, confirmed_head=100) == [_factory_seed(100)]
    clock[0] = 1299
    assert runtime._refresh_factory_seeds(chain, confirmed_head=101) == [_factory_seed(100)]
    clock[0] = 1300
    assert runtime._refresh_factory_seeds(chain, confirmed_head=102) == [_factory_seed(100)]
    clock[0] = 1301
    runtime._refresh_factory_seeds(chain, confirmed_head=103)
    assert calls == [100, 102]
    saved = json.loads(runtime._load_sync_state_row()["discovery_status_json"])
    assert saved["last_success_at"] == 1000
    assert saved["last_attempt_at"] == 1300
    assert saved["last_error"] == "Registry lookup failed"
    assert saved["problems"] == [problem]


def test_sync_chain_once_logs_inserted_entities(caplog, tmp_path, *, monkeypatch):
    runtime, chain = _build_runtime(tmp_path, latest_heads=[103], monkeypatch=monkeypatch)
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
    take = make_prepared(
        event_name="Take",
        tx_nonce=4,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": "0x0000000000000000000000000000000000000abc",
            "receiver": "0x0000000000000000000000000000000000000eee",
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200,
            "amountPaid": 150_000_000,
            "expectedAmountPaid": 150_000_000,
            "priceE18": 750_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )
    runtime.discoverer = SimpleNamespace(
        refresh_factories=lambda _chain, confirmed_head, known_factories: DiscoveryResult([_factory_seed(100)], [])
    )
    monkeypatch.setattr(
        collection_module,
        "scan_factory_events",
        lambda _chain, _registry, _hydrator, _tracked_factories, from_block, to_block: [deployment],
    )
    monkeypatch.setattr(
        collection_module,
        "scan_auction_events",
        lambda _chain, _registry, _hydrator, _tracked_auctions, from_block, to_block: [enabled, kicked],
    )
    runtime.take_detector = SimpleNamespace(
        scan_window=lambda _chain, _conn, from_block, to_block, native_events=(): ([], [take]),
        replay_chain=lambda _chain, _conn: [],
    )

    with caplog.at_level(logging.INFO):
        inserted = runtime.sync_chain_once()

    assert inserted == 4
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "factory discovered network=ethereum chain_id=1" in messages
    assert f"auction deployed network=ethereum block=100 auction={DEFAULT_AUCTION}" in messages
    assert (
        f"round kicked network=ethereum block=102 auction={DEFAULT_AUCTION} round_id=1"
        in messages
    )
    assert f"take detected network=ethereum block=103 auction={DEFAULT_AUCTION} round_id=1" in messages


def test_confirmed_batches_enqueue_pricing_before_advancing_confirmed_cursor(tmp_path, *, monkeypatch):
    runtime, _chain = _build_runtime(tmp_path, latest_heads=[103], monkeypatch=monkeypatch)
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
    take = make_prepared(
        event_name="Take",
        tx_nonce=4,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": "0x0000000000000000000000000000000000000abc",
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200,
            "amountPaid": 150_000_000,
            "expectedAmountPaid": 150_000_000,
            "priceE18": 750_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )
    runtime.discoverer = SimpleNamespace(
        refresh_factories=lambda _chain, confirmed_head, known_factories: DiscoveryResult([_factory_seed(100)], [])
    )
    monkeypatch.setattr(
        collection_module,
        "scan_factory_events",
        lambda _chain, _registry, _hydrator, _tracked_factories, from_block, to_block: [deployment],
    )
    monkeypatch.setattr(
        collection_module,
        "scan_auction_events",
        lambda _chain, _registry, _hydrator, _tracked_auctions, from_block, to_block: [enabled, kicked],
    )
    runtime.take_detector = SimpleNamespace(
        scan_window=lambda _chain, _conn, from_block, to_block, native_events=(): ([], [take]),
        replay_chain=lambda _chain, _conn: [],
    )

    inserted = runtime.sync_chain_once()

    assert inserted == 4
    sync_state = runtime.writer.fetchone(
        "SELECT last_confirmed_processed, last_live_processed FROM sync_state WHERE chain_id = 1"
    )
    assert dict(sync_state) == {
        "last_confirmed_processed": 103,
        "last_live_processed": 103,
    }
    queue_rows = runtime.writer.fetchall(
        "SELECT entity_kind, take_seq FROM pricing_capture_queue WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [(row["entity_kind"], row["take_seq"]) for row in queue_rows] == [
        ("round_kick_quote", None),
        ("want_token_price", None),
        ("take_quote", 1),
        ("want_token_price", 1),
    ]


def test_confirmed_batch_retry_after_transaction_failure_does_not_advance_cursor_or_duplicate_queue_rows(
    tmp_path,
    monkeypatch,
):
    runtime, _chain = _build_runtime(tmp_path, latest_heads=[103, 103], monkeypatch=monkeypatch)
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
    take = make_prepared(
        event_name="Take",
        tx_nonce=4,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": "0x0000000000000000000000000000000000000abc",
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200,
            "amountPaid": 150_000_000,
            "expectedAmountPaid": 150_000_000,
            "priceE18": 750_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )
    runtime.discoverer = SimpleNamespace(
        refresh_factories=lambda _chain, confirmed_head, known_factories: DiscoveryResult([_factory_seed(100)], [])
    )
    monkeypatch.setattr(
        collection_module,
        "scan_factory_events",
        lambda _chain, _registry, _hydrator, _tracked_factories, from_block, to_block: [deployment],
    )
    monkeypatch.setattr(
        collection_module,
        "scan_auction_events",
        lambda _chain, _registry, _hydrator, _tracked_auctions, from_block, to_block: [enabled, kicked],
    )
    runtime.take_detector = SimpleNamespace(
        scan_window=lambda _chain, _conn, from_block, to_block, native_events=(): ([], [take]),
        replay_chain=lambda _chain, _conn: [],
    )

    original_enqueue = runtime_module.enqueue_pricing_work
    triggered = {"value": False}

    def failing_enqueue(conn, prepared_events) -> int:
        inserted = original_enqueue(conn, prepared_events)
        if not triggered["value"]:
            triggered["value"] = True
            raise RuntimeError("boom during confirmed batch")
        return inserted

    monkeypatch.setattr(runtime_module, "enqueue_pricing_work", failing_enqueue)
    with pytest.raises(RuntimeError, match="boom during confirmed batch"):
        runtime.sync_chain_once()

    state_after_failure = runtime.writer.fetchone(
        "SELECT last_confirmed_processed, last_live_processed FROM sync_state WHERE chain_id = 1"
    )
    assert dict(state_after_failure) == {
        "last_confirmed_processed": 99,
        "last_live_processed": 99,
    }
    assert runtime.writer.fetchone("SELECT COUNT(*) AS count FROM domain_events")["count"] == 0
    assert runtime.writer.fetchone("SELECT COUNT(*) AS count FROM pricing_capture_queue")["count"] == 0

    monkeypatch.setattr(runtime_module, "enqueue_pricing_work", original_enqueue)
    runtime.sync_chain_once()

    state_after_retry = runtime.writer.fetchone(
        "SELECT last_confirmed_processed, last_live_processed FROM sync_state WHERE chain_id = 1"
    )
    assert dict(state_after_retry) == {
        "last_confirmed_processed": 103,
        "last_live_processed": 103,
    }
    queue_rows = runtime.writer.fetchall(
        "SELECT entity_kind, take_seq FROM pricing_capture_queue WHERE chain_id = 1 ORDER BY id ASC"
    )
    assert [(row["entity_kind"], row["take_seq"]) for row in queue_rows] == [
        ("round_kick_quote", None),
        ("want_token_price", None),
        ("take_quote", 1),
        ("want_token_price", 1),
    ]


def test_watch_only_syncs_chain_before_sleep(monkeypatch):
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime._factory_seeds = (_factory_seed(100),)
    runtime.network_name = "ethereum"
    runtime.chain = SimpleNamespace(
        config=SimpleNamespace(poll_interval_seconds=0.01),
    )
    calls: list[tuple[str, object]] = []

    def fake_sync_chain_once(*, max_blocks=None):
        calls.append(("sync", max_blocks))
        return 0

    runtime.sync_chain_once = fake_sync_chain_once
    runtime._mark_chain_error = lambda exc: calls.append(("chain_error", exc))
    runtime._load_sync_state_row = lambda: {"last_live_processed": 100, "latest_rpc_head": 100}

    def stop_sleep(_seconds: float):
        raise SystemExit

    monkeypatch.setattr(runtime_module.time, "sleep", stop_sleep)

    with pytest.raises(SystemExit):
        runtime.watch(max_blocks=25)

    assert calls == [("sync", 25)]


def test_sync_does_not_wait_for_receiver_alias_lookup(tmp_path, monkeypatch):
    runtime, _chain = _build_runtime(tmp_path, latest_heads=[101], monkeypatch=monkeypatch)
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
    runtime.discoverer = SimpleNamespace(
        refresh_factories=lambda _chain, confirmed_head, known_factories: DiscoveryResult([_factory_seed(100)], [])
    )
    monkeypatch.setattr(
        collection_module,
        "scan_factory_events",
        lambda _chain, _registry, _hydrator, _tracked_factories, from_block, to_block: [deployment],
    )
    monkeypatch.setattr(
        collection_module,
        "scan_auction_events",
        lambda _chain, _registry, _hydrator, _tracked_auctions, from_block, to_block: [enabled],
    )

    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("Alias I/O must stay out of live indexing")

    monkeypatch.setattr("backend.indexer.runtime.resolve_address_alias_updates_multicall", unexpected_lookup)

    inserted = runtime.sync_chain_once()

    assert inserted == 2
    alias_row = runtime.writer.fetchone(
        """
        SELECT alias_text, checked_at
          FROM address_aliases
         WHERE chain_id = 1 AND address = ?
        """,
        (DEFAULT_RECEIVER,),
    )
    assert alias_row is None


def test_sync_chain_once_ignores_receiver_alias_transport_failures(tmp_path, monkeypatch):
    runtime, _chain = _build_runtime(tmp_path, latest_heads=[101], monkeypatch=monkeypatch)
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
    runtime.discoverer = SimpleNamespace(
        refresh_factories=lambda _chain, confirmed_head, known_factories: DiscoveryResult([_factory_seed(100)], [])
    )
    monkeypatch.setattr(
        collection_module,
        "scan_factory_events",
        lambda _chain, _registry, _hydrator, _tracked_factories, from_block, to_block: [deployment],
    )
    monkeypatch.setattr(
        collection_module,
        "scan_auction_events",
        lambda _chain, _registry, _hydrator, _tracked_auctions, from_block, to_block: [enabled],
    )

    monkeypatch.setattr(
        "backend.indexer.runtime.resolve_address_alias_updates_multicall",
        lambda chain, addresses: [],
    )

    inserted = runtime.sync_chain_once()

    assert inserted == 2
    alias_row = runtime.writer.fetchone(
        """
        SELECT alias_text, checked_at
          FROM address_aliases
         WHERE chain_id = 1 AND address = ?
        """,
        (DEFAULT_RECEIVER,),
    )
    assert alias_row is None


def test_backfill_receiver_aliases_updates_missing_rows(tmp_path, monkeypatch):
    runtime, _chain = _build_runtime(tmp_path, latest_heads=[100], monkeypatch=monkeypatch)
    runtime.writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO auctions (
                chain_id, auction_address, factory_address, version, capability_family,
                governance, receiver, want_token, deployment_block,
                latest_lifecycle_block, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                DEFAULT_AUCTION,
                DEFAULT_FACTORY,
                "1.0.4",
                "1.0.4",
                None,
                DEFAULT_RECEIVER,
                DEFAULT_WANT_TOKEN,
                100,
                100,
                100,
                100,
            ),
        )
    )

    monkeypatch.setattr(
        "backend.indexer.runtime.resolve_address_alias_updates_multicall",
        lambda chain, addresses: [
            AddressAliasUpdate(
                chain_id=chain.config.chain_id,
                address=address,
                alias_text="Treasury Receiver",
                checked_at=1_234,
            )
            for address in addresses
        ],
    )

    summary = runtime.backfill_receiver_aliases()

    assert summary.checked == 1
    assert summary.updated == 1
    alias_row = runtime.writer.fetchone(
        """
        SELECT alias_text, checked_at
          FROM address_aliases
         WHERE chain_id = 1 AND address = ?
        """,
        (DEFAULT_RECEIVER,),
    )
    assert dict(alias_row) == {
        "alias_text": "Treasury Receiver",
        "checked_at": 1_234,
    }


def test_watch_catches_up_through_empty_batches_without_sleep(monkeypatch):
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime._factory_seeds = (_factory_seed(100),)
    runtime.network_name = "ethereum"
    runtime.chain = SimpleNamespace(config=SimpleNamespace(poll_interval_seconds=2))
    state = {"last_live_processed": 0, "latest_rpc_head": 3}
    calls = []

    def sync(**_kwargs):
        state["last_live_processed"] += 1
        calls.append(state["last_live_processed"])
        return 0

    runtime.sync_chain_once = sync
    runtime._load_sync_state_row = lambda: state
    runtime._mark_chain_error = lambda exc: (_ for _ in ()).throw(exc)
    monkeypatch.setattr(runtime_module.time, "sleep", lambda _: (_ for _ in ()).throw(SystemExit))
    with pytest.raises(SystemExit):
        runtime.watch()
    assert calls == [1, 2, 3]
