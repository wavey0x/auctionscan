from __future__ import annotations

from backend.indexer import replay as replay_module
from .helpers import make_hydrator

import logging
import time
from types import SimpleNamespace

import pytest

import backend.indexer.takes as takes_module
from backend.indexer.facts import delete_derived_take_events
from backend.indexer.projections import apply_batch, clear_take_state, reconcile_round_statuses
from backend.indexer.runtime import IndexerRuntime
from backend.indexer.takes import TRANSFER_TOPIC, TakeDetector
from backend.indexer.types import ChainConfig, RawLogRecord, TokenMetadata
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


TAKER = "0x0000000000000000000000000000000000000abc"


class _FakeReceiptEth:
    def __init__(self, receipt_logs, tx_input: str = "0x4d44e663"):
        self._receipt_logs = receipt_logs
        self._tx_input = tx_input
        self.block_hash = None

    def call(self, *_args, **_kwargs):
        from web3.exceptions import ContractLogicError
        raise ContractLogicError("execution reverted")

    def get_transaction_receipt(self, _tx_hash):
        return {"transactionHash": _tx_hash, "blockHash": self.block_hash or _tx_hash,
                "logs": [dict(log, transactionHash=_tx_hash, blockHash=self.block_hash or _tx_hash) for log in self._receipt_logs]}

    def get_transaction(self, _tx_hash):
        return {"hash": _tx_hash, "blockHash": self.block_hash or _tx_hash, "input": self._tx_input}


class _FakeTakeWeb3:
    from web3 import Web3
    to_checksum_address = staticmethod(Web3.to_checksum_address)
    codec = Web3().codec
    def __init__(self, receipt_logs, tx_input: str = "0x4d44e663"):
        self.eth = _FakeReceiptEth(receipt_logs, tx_input=tx_input)


class _FakeTakeHydrator:
    def read_token_metadata(self, chain, token_address: str, *, block_number=None):
        decimals = 18 if token_address == DEFAULT_FROM_TOKEN else 6
        return TokenMetadata(
            chain_id=chain.config.chain_id,
            token_address=token_address,
            symbol=None,
            name=None,
            decimals=decimals,
        )


class _FakeAbiRegistry:
    def auction_contract(self, _w3, address, _version):
        from web3 import Web3
        return Web3().eth.contract(address=Web3.to_checksum_address(address), abi=[{
            "name": "getAmountNeeded", "type": "function", "stateMutability": "view",
            "inputs": [{"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "timestamp", "type": "uint256"}],
            "outputs": [{"type": "uint256"}],
        }])


def _base_native_batch():
    deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=1,
        block_number=100,
        address=DEFAULT_FACTORY,
        auction_address=DEFAULT_AUCTION,
        version="1.0.4",
        capability_family="1.0.4",
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
    return [deployment, enabled, kicked]


def _seed_native_state(writer: Writer) -> None:
    writer.transaction(lambda conn: apply_batch(conn, _base_native_batch()))
    writer.transaction(
        lambda conn: conn.executemany(
            """
            INSERT OR REPLACE INTO tokens (
                chain_id, token_address, symbol, name, decimals, metadata_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, DEFAULT_FROM_TOKEN, "FROM", "From Token", 18, 0),
                (1, DEFAULT_WANT_TOKEN, "WANT", "Want Token", 6, 0),
            ],
        )
    )


def _make_transfer_raw(*, tx_hash_nonce: int = 50) -> RawLogRecord:
    return RawLogRecord(
        chain_id=1,
        block_number=103,
        block_hash=f"0x{tx_hash_nonce:064x}",
        tx_hash=f"0x{tx_hash_nonce:064x}",
        tx_index=0,
        log_index=4,
        address=DEFAULT_FROM_TOKEN,
        topic0=TRANSFER_TOPIC,
        topic1="0x" + DEFAULT_AUCTION[2:].rjust(64, "0"),
        topic2="0x" + TAKER[2:].rjust(64, "0"),
        topic3=None,
        data=hex(200),
        timestamp=1_700_000_103,
    )


def _rpc_transfer_log(
    *,
    from_token: str,
    auction_address: str,
    tx_nonce: int,
    block_number: int,
    log_index: int,
):
    return {
        "address": from_token,
        "topics": [
            TRANSFER_TOPIC,
            "0x" + auction_address[2:].rjust(64, "0"),
            "0x" + TAKER[2:].rjust(64, "0"),
        ],
        "data": "0x01",
        "blockNumber": block_number,
        "blockHash": f"0x{block_number:064x}",
        "transactionHash": f"0x{tx_nonce:064x}",
        "transactionIndex": 0,
        "logIndex": log_index,
    }


class _EffectivePairRows:
    def __init__(self, rows) -> None:
        self.rows = rows

    def fetchall(self):
        return self.rows


class _EffectivePairConnection:
    def __init__(self, rows) -> None:
        self.rows = rows

    def execute(self, _query, _params):
        return _EffectivePairRows(self.rows)


class _TransferFilterEth:
    def __init__(self, logs) -> None:
        self.logs = logs
        self.calls = []

    def get_logs(self, params):
        self.calls.append(dict(params))
        raw_addresses = params["address"]
        addresses = {
            item.lower()
            for item in (raw_addresses if isinstance(raw_addresses, list) else [raw_addresses])
        }
        raw_sender_topics = params["topics"][1]
        sender_topics = {
            item.lower()
            for item in (
                raw_sender_topics
                if isinstance(raw_sender_topics, list)
                else [raw_sender_topics]
            )
        }
        matched = [
            log
            for log in self.logs
            if log["address"].lower() in addresses
            and log["topics"][1].lower() in sender_topics
        ]
        return matched + matched


class _TransferFilterWeb3:
    def __init__(self, logs) -> None:
        self.eth = _TransferFilterEth(logs)

    @staticmethod
    def to_checksum_address(address: str) -> str:
        return address


def test_transfer_scan_matrix_matches_exact_strategies_and_filters_broad_results():
    auctions = [f"0x{10_000 + index:040x}" for index in range(101)]
    tokens = [f"0x{20_000 + index:040x}" for index in range(101)]
    rows = [
        {"auction_address": auction, "from_token": token}
        for auction, token in zip(auctions, tokens, strict=True)
    ]
    logs = [
        _rpc_transfer_log(
            from_token=tokens[0],
            auction_address=auctions[0],
            tx_nonce=10,
            block_number=3,
            log_index=2,
        ),
        _rpc_transfer_log(
            from_token=tokens[50],
            auction_address=auctions[50],
            tx_nonce=11,
            block_number=1,
            log_index=3,
        ),
        _rpc_transfer_log(
            from_token=tokens[100],
            auction_address=auctions[100],
            tx_nonce=12,
            block_number=2,
            log_index=4,
        ),
        _rpc_transfer_log(
            from_token=tokens[0],
            auction_address=auctions[1],
            tx_nonce=13,
            block_number=1,
            log_index=5,
        ),
    ]
    chain = SimpleNamespace(
        config=SimpleNamespace(chain_id=1),
        w3=_TransferFilterWeb3(logs),
        block_timestamp=lambda block_number: 1_700_000_000 + block_number,
    )
    conn = _EffectivePairConnection(rows)

    def scan(strategy: str | None = None):
        chain.w3.eth.calls.clear()
        detector = TakeDetector(_FakeAbiRegistry(), _FakeTakeHydrator())
        if strategy is not None:
            detector._transfer_scan_plan = lambda *_args: (strategy, 0)
        detector._derive_take_events = lambda _chain, _conn, _raw_logs, **_kwargs: []
        raw_logs, _events = detector.scan_window(chain, conn, from_block=1, to_block=3)
        return raw_logs, list(chain.w3.eth.calls)

    selected_logs, selected_calls = scan()
    auction_logs, auction_calls = scan("auction")
    token_logs, token_calls = scan("token")

    def identities(raw_logs):
        return [(item.tx_hash, item.log_index) for item in raw_logs]

    expected = [
        (f"0x{11:064x}", 3),
        (f"0x{12:064x}", 4),
        (f"0x{10:064x}", 2),
    ]
    assert identities(selected_logs) == expected
    assert identities(auction_logs) == expected
    assert identities(token_logs) == expected
    assert len(selected_calls) == 4
    assert len(auction_calls) == 101
    assert len(token_calls) == 101
    assert all(len(call["address"]) <= takes_module.ADDRESS_CHUNK for call in selected_calls)
    assert all(
        len(call["topics"][1]) <= takes_module.TOPIC_CHUNK
        for call in selected_calls
    )
    assert (f"0x{13:064x}", 5) not in identities(selected_logs)


def test_transfer_scan_plans_six_matrix_filters_for_production_shape():
    detector = TakeDetector(_FakeAbiRegistry(), _FakeTakeHydrator())
    auctions = [f"0x{30_000 + index:040x}" for index in range(261)]
    tokens = [f"0x{40_000 + index:040x}" for index in range(177)]
    auction_to_tokens = {
        auction: [tokens[index % len(tokens)]]
        for index, auction in enumerate(auctions)
    }
    token_to_auctions: dict[str, list[str]] = {token: [] for token in tokens}
    for auction, from_tokens in auction_to_tokens.items():
        token_to_auctions[from_tokens[0]].append(auction)

    assert detector._transfer_scan_plan(auction_to_tokens, token_to_auctions) == (
        "matrix",
        6,
    )


def test_take_detector_replay_chain_derives_take_from_stored_transfer_logs(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)
    raw_log = _make_transfer_raw()
    writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO chain_logs (
                chain_id, block_number, block_hash, tx_hash, tx_index, log_index,
                address, topic0, topic1, topic2, topic3, data, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_log.chain_id,
                raw_log.block_number,
                raw_log.block_hash,
                raw_log.tx_hash,
                raw_log.tx_index,
                raw_log.log_index,
                raw_log.address,
                raw_log.topic0,
                raw_log.topic1,
                raw_log.topic2,
                raw_log.topic3,
                raw_log.data,
                raw_log.timestamp,
            ),
        )
    )
    receipt_logs = [
        {
            "address": DEFAULT_WANT_TOKEN,
            "topics": [
                TRANSFER_TOPIC,
                "0x" + TAKER[2:].rjust(64, "0"),
                "0x" + DEFAULT_RECEIVER[2:].rjust(64, "0"),
            ],
            "data": hex(150_000_000),
            "logIndex": 7,
        }
    ]
    chain = SimpleNamespace(
        config=SimpleNamespace(chain_id=1),
        w3=_FakeTakeWeb3(receipt_logs),
    )
    detector = TakeDetector(_FakeAbiRegistry(), _FakeTakeHydrator())

    from backend.indexer.observations import BlockReader
    from backend.indexer.types import IndexedBlockRecord
    headers = [IndexedBlockRecord(1, row["block_number"], row["block_hash"], "0x" + "00" * 32, row["timestamp"])
               for row in writer.fetchall("SELECT * FROM chain_logs WHERE topic0 = ?", (TRANSFER_TOPIC,))]
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, headers=headers)
    detector.replay_chain(chain, writer.connection)
    writer.transaction(chain.reader.persist)
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, offline=True)
    events = detector.replay_chain(chain, writer.connection)

    assert len(events) == 1
    payload = events[0].domain_event.payload
    assert payload["roundId"] == 1
    assert payload["taker"] == TAKER
    assert payload["from"] == DEFAULT_FROM_TOKEN
    assert payload["to"] == DEFAULT_WANT_TOKEN
    assert payload["amountTaken"] == 200
    assert payload["amountPaid"] == 150_000_000
    assert payload["matchingMethod"] == "receiver_transfer"


def test_take_detector_ignores_sweep_transfer_logs(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)
    raw_log = _make_transfer_raw(tx_hash_nonce=61)
    writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO chain_logs (
                chain_id, block_number, block_hash, tx_hash, tx_index, log_index,
                address, topic0, topic1, topic2, topic3, data, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_log.chain_id,
                raw_log.block_number,
                raw_log.block_hash,
                raw_log.tx_hash,
                raw_log.tx_index,
                raw_log.log_index,
                raw_log.address,
                raw_log.topic0,
                raw_log.topic1,
                raw_log.topic2,
                raw_log.topic3,
                raw_log.data,
                raw_log.timestamp,
            ),
        )
    )
    chain = SimpleNamespace(
        config=SimpleNamespace(chain_id=1),
        w3=_FakeTakeWeb3([], tx_input="0x01681a62"),
    )
    detector = TakeDetector(_FakeAbiRegistry(), _FakeTakeHydrator())

    from backend.indexer.observations import BlockReader
    from backend.indexer.types import IndexedBlockRecord
    headers = [IndexedBlockRecord(1, row["block_number"], row["block_hash"], "0x" + "00" * 32, row["timestamp"])
               for row in writer.fetchall("SELECT * FROM chain_logs WHERE topic0 = ?", (TRANSFER_TOPIC,))]
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, headers=headers)
    detector.replay_chain(chain, writer.connection)
    writer.transaction(chain.reader.persist)
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, offline=True)
    events = detector.replay_chain(chain, writer.connection)

    assert events == []


def test_take_detector_ignores_transfers_in_auction_swept_transactions(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)
    raw_log = _make_transfer_raw(tx_hash_nonce=63)
    writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO chain_logs (
                chain_id, block_number, block_hash, tx_hash, tx_index, log_index,
                address, topic0, topic1, topic2, topic3, data, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_log.chain_id,
                raw_log.block_number,
                raw_log.block_hash,
                raw_log.tx_hash,
                raw_log.tx_index,
                raw_log.log_index,
                raw_log.address,
                raw_log.topic0,
                raw_log.topic1,
                raw_log.topic2,
                raw_log.topic3,
                raw_log.data,
                raw_log.timestamp,
            ),
        )
    )
    swept_prepared = make_prepared(
        event_name="AuctionSwept",
        tx_nonce=63,
        block_number=103,
        log_index=5,
        payload={"token": DEFAULT_FROM_TOKEN, "to": DEFAULT_RECEIVER},
    )
    writer.transaction(lambda conn: apply_batch(conn, [swept_prepared]))
    receipt_logs = [
        {
            "address": DEFAULT_WANT_TOKEN,
            "topics": [
                TRANSFER_TOPIC,
                "0x" + TAKER[2:].rjust(64, "0"),
                "0x" + DEFAULT_RECEIVER[2:].rjust(64, "0"),
            ],
            "data": hex(150_000_000),
            "logIndex": 7,
        }
    ]
    chain = SimpleNamespace(
        config=SimpleNamespace(chain_id=1),
        w3=_FakeTakeWeb3(receipt_logs, tx_input="0x4d44e663"),
    )
    detector = TakeDetector(_FakeAbiRegistry(), _FakeTakeHydrator())

    from backend.indexer.observations import BlockReader
    from backend.indexer.types import IndexedBlockRecord
    headers = [IndexedBlockRecord(1, row["block_number"], row["block_hash"], "0x" + "00" * 32, row["timestamp"])
               for row in writer.fetchall("SELECT * FROM chain_logs WHERE topic0 = ?", (TRANSFER_TOPIC,))]
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, headers=headers)
    detector.replay_chain(chain, writer.connection)
    writer.transaction(chain.reader.persist)
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, offline=True)
    events = detector.replay_chain(chain, writer.connection)

    assert events == []


def test_take_detector_ignores_transfers_after_round_end(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)
    late_transfer = _make_transfer_raw(tx_hash_nonce=62)
    late_transfer = RawLogRecord(
        chain_id=late_transfer.chain_id,
        block_number=late_transfer.block_number,
        block_hash=late_transfer.block_hash,
        tx_hash=late_transfer.tx_hash,
        tx_index=late_transfer.tx_index,
        log_index=late_transfer.log_index,
        address=late_transfer.address,
        topic0=late_transfer.topic0,
        topic1=late_transfer.topic1,
        topic2=late_transfer.topic2,
        topic3=late_transfer.topic3,
        data=late_transfer.data,
        timestamp=1_700_086_600,
    )
    writer.transaction(
        lambda conn: conn.execute(
            """
            UPDATE rounds
               SET status = 'expired',
                   end_at = ?,
                   scheduled_end_at = ?,
                   updated_at = ?
             WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
            """,
            (1_700_086_500, 1_700_086_500, 1_700_086_500, DEFAULT_AUCTION),
        )
    )
    writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO chain_logs (
                chain_id, block_number, block_hash, tx_hash, tx_index, log_index,
                address, topic0, topic1, topic2, topic3, data, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                late_transfer.chain_id,
                late_transfer.block_number,
                late_transfer.block_hash,
                late_transfer.tx_hash,
                late_transfer.tx_index,
                late_transfer.log_index,
                late_transfer.address,
                late_transfer.topic0,
                late_transfer.topic1,
                late_transfer.topic2,
                late_transfer.topic3,
                late_transfer.data,
                late_transfer.timestamp,
            ),
        )
    )
    receipt_logs = [
        {
            "address": DEFAULT_WANT_TOKEN,
            "topics": [
                TRANSFER_TOPIC,
                "0x" + TAKER[2:].rjust(64, "0"),
                "0x" + DEFAULT_RECEIVER[2:].rjust(64, "0"),
            ],
            "data": hex(150_000_000),
            "logIndex": 7,
        }
    ]
    chain = SimpleNamespace(
        config=SimpleNamespace(chain_id=1),
        w3=_FakeTakeWeb3(receipt_logs),
    )
    detector = TakeDetector(_FakeAbiRegistry(), _FakeTakeHydrator())

    from backend.indexer.observations import BlockReader
    from backend.indexer.types import IndexedBlockRecord
    headers = [IndexedBlockRecord(1, row["block_number"], row["block_hash"], "0x" + "00" * 32, row["timestamp"])
               for row in writer.fetchall("SELECT * FROM chain_logs WHERE topic0 = ?", (TRANSFER_TOPIC,))]
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, headers=headers)
    detector.replay_chain(chain, writer.connection)
    writer.transaction(chain.reader.persist)
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, offline=True)
    events = detector.replay_chain(chain, writer.connection)

    assert events == []


def test_apply_batch_projects_take_and_clear_take_state(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)
    take_raw = _make_transfer_raw(tx_hash_nonce=51)
    take_prepared = make_prepared(
        event_name="Take",
        tx_nonce=51,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200,
            "amountPaid": 150_000_000,
            "expectedAmountPaid": None,
            "priceE18": 750_000_000_000,
        },
    )
    take_prepared = take_prepared.__class__(
        raw_log=take_raw,
        domain_event=take_prepared.domain_event,
        snapshot=None,
        token_metadata=(),
    )

    inserted = writer.transaction(lambda conn: apply_batch(conn, [take_prepared]))

    assert inserted == 1
    take_row = writer.fetchone(
        """
        SELECT round_id, take_seq, taker, amount_taken_raw, amount_paid_raw
          FROM takes
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(take_row) == {
        "round_id": 1,
        "take_seq": 1,
        "taker": TAKER,
        "amount_taken_raw": "200",
        "amount_paid_raw": "150000000",
    }

    round_row = writer.fetchone(
        """
        SELECT take_count, sold_amount_raw, paid_amount_raw, remaining_available_raw, last_take_price_raw
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(round_row) == {
        "take_count": 1,
        "sold_amount_raw": "200",
        "paid_amount_raw": "150000000",
        "remaining_available_raw": "300",
        "last_take_price_raw": "750000000000",
    }

    writer.transaction(lambda conn: (delete_derived_take_events(conn, 1), clear_take_state(conn, 1)))

    assert writer.fetchone("SELECT COUNT(*) AS count FROM takes")["count"] == 0
    assert writer.fetchone("SELECT COUNT(*) AS count FROM taker_summary")["count"] == 0
    reset_round = writer.fetchone(
        """
        SELECT take_count, sold_amount_raw, paid_amount_raw, remaining_available_raw
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(reset_round) == {
        "take_count": 0,
        "sold_amount_raw": "0",
        "paid_amount_raw": None,
        "remaining_available_raw": "500",
    }


def test_apply_batch_preserves_unknown_payment_when_transfer_match_is_missing(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)
    take_raw = _make_transfer_raw(tx_hash_nonce=60)
    take_prepared = make_prepared(
        event_name="Take",
        tx_nonce=60,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200,
            "amountPaid": None,
            "expectedAmountPaid": 150_000_000,
            "priceE18": 750_000_000_000,
            "matchingMethod": "amount_needed",
        },
    )
    take_prepared = take_prepared.__class__(
        raw_log=take_raw,
        domain_event=take_prepared.domain_event,
        snapshot=None,
        token_metadata=(),
    )

    inserted = writer.transaction(lambda conn: apply_batch(conn, [take_prepared]))

    assert inserted == 1
    take_row = writer.fetchone(
        """
        SELECT amount_paid_raw, expected_amount_paid_raw
          FROM takes
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(take_row) == {
        "amount_paid_raw": None,
        "expected_amount_paid_raw": "150000000",
    }

    round_row = writer.fetchone(
        """
        SELECT paid_amount_raw, remaining_available_raw
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(round_row) == {
        "paid_amount_raw": None,
        "remaining_available_raw": "300",
    }

    taker_summary = writer.fetchone(
        """
        SELECT take_count
          FROM taker_summary
         WHERE chain_id = 1 AND taker = ?
        """,
        (TAKER,),
    )
    assert dict(taker_summary) == {
        "take_count": 1,
    }


def test_apply_batch_marks_sold_out_round_and_restores_scheduled_end_on_clear(caplog, tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)
    take_raw = _make_transfer_raw(tx_hash_nonce=52)
    take_prepared = make_prepared(
        event_name="Take",
        tx_nonce=52,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 500,
            "amountPaid": 375_000_000,
            "expectedAmountPaid": 375_000_000,
            "priceE18": 750_000_000_000,
        },
    )
    take_prepared = take_prepared.__class__(
        raw_log=take_raw,
        domain_event=take_prepared.domain_event,
        snapshot=None,
        token_metadata=(),
    )

    with caplog.at_level(logging.INFO):
        writer.transaction(lambda conn: apply_batch(conn, [take_prepared]))

    sold_out_round = writer.fetchone(
        """
        SELECT status, end_at, scheduled_end_at, remaining_available_raw, take_count
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(sold_out_round) == {
        "status": "sold_out",
        "end_at": 1_700_000_103,
        "scheduled_end_at": 1_700_086_502,
        "remaining_available_raw": "0",
        "take_count": 1,
    }
    assert (
        f"round sold_out chain_id=1 auction={DEFAULT_AUCTION} round_id=1 closed_at=1700000103"
        in "\n".join(record.getMessage() for record in caplog.records)
    )

    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, 1_700_086_503))
    reconciled_round = writer.fetchone(
        """
        SELECT status, end_at
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(reconciled_round) == {
        "status": "sold_out",
        "end_at": 1_700_000_103,
    }

    writer.transaction(lambda conn: (delete_derived_take_events(conn, 1), clear_take_state(conn, 1)))

    reset_round = writer.fetchone(
        """
        SELECT status, end_at, scheduled_end_at, remaining_available_raw, take_count
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(reset_round) == {
        "status": "live",
        "end_at": 1_700_086_502,
        "scheduled_end_at": 1_700_086_502,
        "remaining_available_raw": "500",
        "take_count": 0,
    }


def test_apply_batch_closes_swept_round_before_take_replay(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)
    swept = make_prepared(
        event_name="AuctionSwept",
        tx_nonce=53,
        block_number=104,
        payload={"token": DEFAULT_FROM_TOKEN, "to": DEFAULT_RECEIVER},
    )
    take_raw = _make_transfer_raw(tx_hash_nonce=54)
    take_prepared = make_prepared(
        event_name="Take",
        tx_nonce=54,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 499,
            "amountPaid": 374_250_000,
            "expectedAmountPaid": 374_250_000,
            "priceE18": 750_000_000_000,
        },
    )
    take_prepared = take_prepared.__class__(
        raw_log=take_raw,
        domain_event=take_prepared.domain_event,
        snapshot=None,
        token_metadata=(),
    )

    writer.transaction(lambda conn: apply_batch(conn, [swept]))
    writer.transaction(lambda conn: apply_batch(conn, [take_prepared]))

    swept_round = writer.fetchone(
        """
        SELECT status, settled_at, end_at, scheduled_end_at, remaining_available_raw, take_count
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(swept_round) == {
        "status": "settled",
        "settled_at": 1_700_000_104,
        "end_at": 1_700_000_104,
        "scheduled_end_at": 1_700_086_502,
        "remaining_available_raw": "1",
        "take_count": 1,
    }


def test_apply_batch_prefers_sold_out_status_when_take_replays_after_settle(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    deployment, enabled, kicked = _base_native_batch()
    settled = make_prepared(
        event_name="AuctionSettled",
        tx_nonce=53,
        block_number=104,
        payload={"from": DEFAULT_FROM_TOKEN},
    )
    take_raw = _make_transfer_raw(tx_hash_nonce=54)
    take_prepared = make_prepared(
        event_name="Take",
        tx_nonce=54,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 500,
            "amountPaid": 375_000_000,
            "expectedAmountPaid": 375_000_000,
            "priceE18": 750_000_000_000,
        },
    )
    take_prepared = take_prepared.__class__(
        raw_log=take_raw,
        domain_event=take_prepared.domain_event,
        snapshot=None,
        token_metadata=(),
    )

    writer.transaction(lambda conn: apply_batch(conn, [deployment, enabled, kicked, settled, take_prepared]))

    settled_round = writer.fetchone(
        """
        SELECT status, settled_at, end_at, scheduled_end_at, last_take_at, remaining_available_raw
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(settled_round) == {
        "status": "sold_out",
        "settled_at": 1_700_000_104,
        "end_at": 1_700_000_103,
        "scheduled_end_at": 1_700_086_502,
        "last_take_at": 1_700_000_103,
        "remaining_available_raw": "0",
    }


def test_apply_batch_preserves_sold_out_status_when_settle_arrives_after_sellout(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    deployment, enabled, kicked = _base_native_batch()
    take_raw = _make_transfer_raw(tx_hash_nonce=54)
    take_prepared = make_prepared(
        event_name="Take",
        tx_nonce=54,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 500,
            "amountPaid": 375_000_000,
            "expectedAmountPaid": 375_000_000,
            "priceE18": 750_000_000_000,
        },
    )
    take_prepared = take_prepared.__class__(
        raw_log=take_raw,
        domain_event=take_prepared.domain_event,
        snapshot=None,
        token_metadata=(),
    )
    settled = make_prepared(
        event_name="AuctionSettled",
        tx_nonce=55,
        block_number=104,
        payload={"from": DEFAULT_FROM_TOKEN},
    )

    writer.transaction(lambda conn: apply_batch(conn, [deployment, enabled, kicked, take_prepared, settled]))

    settled_round = writer.fetchone(
        """
        SELECT status, settled_at, end_at, scheduled_end_at, last_take_at, remaining_available_raw
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(settled_round) == {
        "status": "sold_out",
        "settled_at": 1_700_000_104,
        "end_at": 1_700_000_103,
        "scheduled_end_at": 1_700_086_502,
        "last_take_at": 1_700_000_103,
        "remaining_available_raw": "0",
    }


def test_reconcile_round_statuses_expires_live_rounds_without_touching_terminal_rows(caplog, tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)

    with caplog.at_level(logging.INFO):
        writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, 1_700_086_503))

    expired_round = writer.fetchone(
        """
        SELECT status, end_at, scheduled_end_at
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(expired_round) == {
        "status": "expired",
        "end_at": 1_700_086_502,
        "scheduled_end_at": 1_700_086_502,
    }
    assert (
        f"round expired chain_id=1 auction={DEFAULT_AUCTION} round_id=1 end_at=1700086502 confirmed_timestamp=1700086503"
        in "\n".join(record.getMessage() for record in caplog.records)
    )


def test_reconcile_round_statuses_repairs_sold_out_settled_round_end_at(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    _seed_native_state(writer)

    writer.transaction(
        lambda conn: conn.execute(
            """
            UPDATE rounds
               SET status = 'settled',
                   settled_at = ?,
                   remaining_available_raw = '0',
                   last_take_at = ?,
                   end_at = scheduled_end_at
             WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
            """,
            (1_700_000_104, 1_700_000_103, DEFAULT_AUCTION),
        )
    )

    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, 1_700_086_503))

    repaired_round = writer.fetchone(
        """
        SELECT status, settled_at, end_at, scheduled_end_at, last_take_at
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(repaired_round) == {
        "status": "sold_out",
        "settled_at": 1_700_000_104,
        "end_at": 1_700_000_103,
        "scheduled_end_at": 1_700_086_502,
        "last_take_at": 1_700_000_103,
    }


def test_reproject_chain_rebuilds_native_projections(tmp_path, *, monkeypatch):
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime.writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    config = ChainConfig(
        name="ethereum",
        chain_id=1,
        rpc_url="http://localhost:8545",
        finality_depth=0,
        block_batch_size=1_000,
        poll_interval_seconds=1.0,
        factories=(),
    )
    chain = SimpleNamespace(
        config=config,
        latest_head=lambda: 120,
        confirmed_head_from=lambda head: head,
        block_timestamp=lambda block_number: 1_700_000_000 + block_number,
    )
    runtime.network_name = "ethereum"
    runtime.chain_config = config
    runtime.chain = chain
    runtime.hydrator = object()
    runtime.take_detector = SimpleNamespace(replay_chain=lambda _chain, _conn: [])
    monkeypatch.setattr(replay_module, "load_native_events", lambda *_args: _base_native_batch())

    runtime.writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO sync_state (
                chain_id, network_name, latest_rpc_head, confirmed_head,
                last_confirmed_processed, last_live_processed, reorg_count, health
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "ethereum", 120, 120, 120, 120, 0, "ok"),
        )
    )
    runtime.writer.transaction(lambda conn: apply_batch(conn, _base_native_batch()))
    runtime.writer.transaction(lambda conn: conn.execute("DELETE FROM rounds WHERE chain_id = 1"))

    runtime.writer.transaction(lambda conn: conn.execute(
        "INSERT INTO indexed_blocks VALUES (1, 120, ?, ?, 1700000120)",
        ("0x" + "78".zfill(64), "0x" + "77".zfill(64)),
    ))
    projected = runtime.reproject_chain()

    assert projected == 3
    rebuilt_round = runtime.writer.fetchone(
        """
        SELECT round_id, from_token, status
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(rebuilt_round) == {
        "round_id": 1,
        "from_token": DEFAULT_FROM_TOKEN,
        "status": "live",
    }
    snapshot_row = runtime.writer.fetchone(
        """
        SELECT param_schema
          FROM round_param_snapshot
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    deploy_snapshot_row = runtime.writer.fetchone(
        """
        SELECT snapshot_kind, param_schema
          FROM auction_snapshot_facts
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(snapshot_row) == {"param_schema": "v1_wad_bps"}
    assert dict(deploy_snapshot_row) == {
        "snapshot_kind": "deploy",
        "param_schema": "v1_wad_bps",
    }


def test_replay_native_events_uses_persisted_snapshots_before_rpc(tmp_path):
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime.writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    config = ChainConfig(
        name="ethereum",
        chain_id=1,
        rpc_url="http://localhost:8545",
        finality_depth=0,
        block_batch_size=1_000,
        poll_interval_seconds=1.0,
        factories=(),
    )
    chain = SimpleNamespace(
        config=config,
        latest_head=lambda: 120,
        confirmed_head_from=lambda head: head,
        block_timestamp=lambda block_number: 1_700_000_000 + block_number,
    )
    runtime.network_name = "ethereum"
    runtime.chain_config = config
    runtime.chain = chain
    runtime.hydrator = object()
    runtime.take_detector = SimpleNamespace(replay_chain=lambda _chain, _conn: [])

    def _unexpected_snapshot(*_args, **_kwargs):
        raise AssertionError("read_auction_snapshot should not be called during replay")

    def _token_metadata(_chain, token_address: str, *, block_number=None):
        return TokenMetadata(
            chain_id=1,
            token_address=token_address,
            symbol=None,
            name=None,
            decimals=18 if token_address == DEFAULT_FROM_TOKEN else 6,
        )

    runtime.hydrator = make_hydrator(
        read_auction_snapshot=_unexpected_snapshot,
        read_token_metadata=_token_metadata,
    )

    from backend.indexer.types import IndexedBlockRecord
    from backend.indexer.observations import BlockReader
    runtime.writer.transaction(lambda conn: apply_batch(conn, _base_native_batch()))
    chain.reader = BlockReader(runtime.writer.connection, chain_id=1, w3=None, header_reader=None, offline=True,
                               headers=[IndexedBlockRecord(1, event.raw_log.block_number, event.raw_log.block_hash,
                                                           "0x" + "00" * 32, event.raw_log.timestamp)
                                        for event in _base_native_batch()])

    replayed = replay_module.load_native_events(runtime.writer.connection, runtime.chain, runtime.hydrator)

    assert len(replayed) == 3
    deployment = next(item for item in replayed if item.domain_event.event_name == "DeployedNewAuction")
    kicked = next(item for item in replayed if item.domain_event.event_name == "AuctionKicked")
    assert deployment.snapshot is not None
    assert kicked.snapshot is not None
    assert deployment.snapshot.starting_price_raw == "100"
    assert kicked.snapshot.starting_price_raw == "100"


def test_watch_marks_chain_error_and_continues(monkeypatch, tmp_path):
    runtime = IndexerRuntime.__new__(IndexerRuntime)
    runtime.writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    bad_config = ChainConfig(
        name="bad",
        chain_id=1,
        rpc_url="http://localhost:8545",
        finality_depth=0,
        block_batch_size=1_000,
        poll_interval_seconds=0.01,
        factories=(),
    )
    runtime.network_name = "bad"
    runtime.chain_config = bad_config
    runtime.chain = SimpleNamespace(
        config=bad_config,
        latest_head=lambda: 50,
        confirmed_head_from=lambda head: head,
    )
    called: list[str] = []

    def fake_sync_chain_once(*, max_blocks=None):
        called.append("bad")
        if len(called) == 1:
            raise RuntimeError("boom")
        return 0

    runtime.sync_chain_once = fake_sync_chain_once

    def stop_sleep(_seconds: float):
        raise SystemExit

    monkeypatch.setattr(time, "sleep", stop_sleep)

    with pytest.raises(SystemExit):
        runtime.watch()

    assert called == ["bad"]
    sync_state = runtime.writer.fetchone(
        "SELECT latest_rpc_head, confirmed_head, health, last_error FROM sync_state WHERE chain_id = 1"
    )
    assert dict(sync_state) == {
        "latest_rpc_head": -1,
        "confirmed_head": -1,
        "health": "error",
        "last_error": "boom",
    }


def test_multiple_kicks_and_takes_in_one_block_match_batching_and_offline_replay(tmp_path):
    from dataclasses import replace
    from backend.indexer.observations import BlockReader
    from backend.indexer.facts import persist_raw_logs
    from backend.indexer.types import IndexedBlockRecord

    header = IndexedBlockRecord(1, 103, f"0x{103:064x}", f"0x{102:064x}", 1700000103)
    kicks = [make_prepared(
        event_name="AuctionKicked", tx_nonce=80 + i, block_number=103, log_index=1 + i * 5,
        payload={"from": DEFAULT_FROM_TOKEN, "available": 500 + i * 500},
        snapshot=make_snapshot(block_number=103),
    ) for i in range(2)]
    transfers = [replace(_make_transfer_raw(tx_hash_nonce=90 + i), block_hash=header.block_hash, log_index=4 + i * 5)
                 for i in range(2)]
    receipt_logs = [{
        "address": DEFAULT_WANT_TOKEN,
        "topics": [TRANSFER_TOPIC, "0x" + TAKER[2:].rjust(64, "0"), "0x" + DEFAULT_RECEIVER[2:].rjust(64, "0")],
        "data": hex(150000000), "logIndex": 7,
    }]
    snapshots = []
    for mode in ("single", "split"):
        writer = Writer(str(tmp_path / f"{mode}.sqlite3"))
        _seed_native_state(writer)
        chain = SimpleNamespace(config=SimpleNamespace(chain_id=1), w3=_FakeTakeWeb3(receipt_logs))
        chain.w3.eth.block_hash = header.block_hash
        detector = TakeDetector(_FakeAbiRegistry(), _FakeTakeHydrator())
        batches = [(kicks, transfers)] if mode == "single" else [([kick], [transfer]) for kick, transfer in zip(kicks, transfers)]
        for native, raw in batches:
            chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, headers=[header])
            takes = detector._derive_take_events(chain, writer.connection, raw, native_events=native)

            def commit(conn):
                chain.reader.persist(conn)
                apply_batch(conn, native)
                persist_raw_logs(conn, raw)
                apply_batch(conn, takes)
            writer.transaction(commit)

        query = "SELECT round_id, take_seq, amount_taken_raw, amount_paid_raw FROM takes ORDER BY round_id, take_seq"
        expected = [(2, 1, "200", "150000000"), (3, 1, "200", "150000000")]
        assert [tuple(row) for row in writer.fetchall(query)] == expected
        snapshots.append([tuple(row) for row in writer.fetchall("SELECT round_id, sold_amount_raw, remaining_available_raw, take_count FROM rounds ORDER BY round_id")])
        chain.reader = BlockReader(writer.connection, chain_id=1, w3=chain.w3, header_reader=None, offline=True)
        chain.w3.eth.get_transaction = lambda *_: (_ for _ in ()).throw(AssertionError("Replay used RPC"))
        chain.w3.eth.get_transaction_receipt = chain.w3.eth.get_transaction
        replayed = detector.replay_chain(chain, writer.connection)
        writer.transaction(lambda conn: (delete_derived_take_events(conn, 1), clear_take_state(conn, 1), apply_batch(conn, replayed)))
        assert [tuple(row) for row in writer.fetchall(query)] == expected
        assert [tuple(row) for row in writer.fetchall("SELECT round_id, sold_amount_raw, remaining_available_raw, take_count FROM rounds ORDER BY round_id")] == snapshots[-1]
    assert snapshots[0] == snapshots[1]


def test_projection_replay_cannot_write_snapshot_facts(tmp_path):
    import sqlite3
    from backend.indexer.projections import apply_native_event_projections, clear_rebuildable_chain_state

    writer = Writer(str(tmp_path / "snapshots.sqlite3"))
    native = _base_native_batch() + [make_prepared(
        event_name="AuctionKicked", tx_nonce=80 + i, block_number=103, log_index=1 + i * 5,
        payload={"from": DEFAULT_FROM_TOKEN, "available": 500 + i * 500},
        snapshot=make_snapshot(block_number=103),
    ) for i in range(2)]
    writer.transaction(lambda conn: apply_batch(conn, native))
    tables = ("auction_snapshot_facts", "round_param_snapshot")
    before = {table: [tuple(row) for row in writer.fetchall(f"SELECT * FROM {table}")] for table in tables}
    assert [row[0] for row in writer.fetchall("SELECT round_id FROM round_param_snapshot ORDER BY round_id")] == [1, 2, 3]

    def protect_snapshots(action, table, _column, _database, _trigger):
        if table in tables and action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    writer.connection.set_authorizer(protect_snapshots)
    try:
        writer.transaction(lambda conn: (
            clear_rebuildable_chain_state(conn, 1), apply_native_event_projections(conn, native),
        ))
    finally:
        writer.connection.set_authorizer(None)
    assert writer.transaction(lambda conn: apply_batch(conn, native)) == 0
    assert {table: [tuple(row) for row in writer.fetchall(f"SELECT * FROM {table}")] for table in tables} == before


@pytest.mark.parametrize("takes_only", [False, True])
def test_maintenance_take_replacement_is_atomic_and_preserves_native_facts(tmp_path, monkeypatch, takes_only):
    import backend.indexer.runtime as runtime_module
    from .test_reorg_runtime import _base_events, _base_headers, _build_runtime

    events = _base_events()
    runtime, _ = _build_runtime(
        tmp_path,
        latest_heads=[105, 105],
        headers=_base_headers(),
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={104: [events["take_old"]]},
        monkeypatch=monkeypatch,
    )
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    runtime.take_detector.replay_chain = lambda _chain, _conn: [events["take_old"]]
    tables = ("chain_logs", "domain_events", "auction_snapshot_facts", "round_param_snapshot",
              "takes", "rounds", "pricing_capture_queue")
    before = {table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")] for table in tables}
    original = runtime_module.apply_batch

    def fail_after_deleting_takes(conn, prepared):
        assert conn.execute("SELECT COUNT(*) FROM domain_events WHERE event_name = 'Take'").fetchone()[0] == 0
        original(conn, prepared)
        raise RuntimeError("replacement failed")

    monkeypatch.setattr(runtime_module, "apply_batch", fail_after_deleting_takes)
    with pytest.raises(RuntimeError, match="replacement failed"):
        runtime.reproject_chain(takes_only=takes_only)
    assert {table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")] for table in tables} == before
    native_before = [tuple(row) for row in runtime.writer.fetchall("SELECT * FROM domain_events WHERE event_name != 'Take'")]
    monkeypatch.setattr(runtime_module, "apply_batch", original)
    runtime.reproject_chain(takes_only=takes_only)
    assert [tuple(row) for row in runtime.writer.fetchall("SELECT * FROM domain_events WHERE event_name != 'Take'")] == native_before
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM domain_events WHERE event_name = 'Take'")[0] == 1
    for table in ("chain_logs", "auction_snapshot_facts", "round_param_snapshot"):
        assert [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")] == before[table]


def test_expiry_reconciliation_is_reversible_and_does_not_repeat_writes(tmp_path):
    writer = Writer(str(tmp_path / "expiry.sqlite3"))
    _seed_native_state(writer)
    end = writer.fetchone("SELECT end_at FROM rounds")[0]
    for timestamp, status in (
        (end - 1, "live"),
        (end, "live"),
        (end + 1, "expired"),
        (end, "live"),
        (end - 1, "live"),
        (end + 1, "expired"),
    ):
        writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, timestamp))
        assert writer.fetchone("SELECT status FROM rounds")[0] == status
        before = writer.connection.total_changes
        writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, timestamp))
        assert writer.connection.total_changes == before
    writer.transaction(lambda conn: conn.execute("UPDATE rounds SET end_at = NULL"))
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, end - 1))
    assert writer.fetchone("SELECT status FROM rounds")[0] == "expired"
