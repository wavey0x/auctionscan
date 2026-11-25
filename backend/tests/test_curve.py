"""Curve DutchAuctionBurner: weekly lots indexed through the shared round model."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from hexbytes import HexBytes
from web3 import Web3

from backend.api.app import create_app
from backend.indexer import replay as replay_module
from backend.indexer.auction_params import RawAuctionParams, decode_params
from backend.indexer.config import load_settings
from backend.indexer.decode import AbiRegistry
from backend.indexer.facts import delete_derived_take_events, persist_raw_logs, upsert_indexed_blocks
from backend.indexer.observations import BlockReader
from backend.indexer.pricing import enqueue_opened_round_pricing, enqueue_pricing_work
from backend.indexer.projections import (
    apply_batch,
    apply_native_event_projections,
    clear_projection_state,
    clear_take_state,
    reconcile_round_statuses,
    update_sync_state,
    upsert_tracked_auction_seeds,
)
from backend.indexer.takes import (
    COW_SETTLEMENT,
    COW_TRADE_TOPIC,
    CURVE_RECOVERED_TOPIC,
    CURVE_TAKEN_TOPIC,
    TRANSFER_TOPIC,
    TakeDetector,
    find_cow_trade,
    find_curve_taken,
    is_curve_recovery,
)
from backend.indexer.types import AuctionSeed, IndexedBlockRecord, RawLogRecord, TokenMetadata
from backend.indexer.writer import Writer

from .helpers import DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN, make_hydrator, make_prepared, make_snapshot


BURNER = "0xc014a92c76709d6c7f7c7841823b7164d6d2abd4"
FEE_COLLECTOR = "0xa2bcd1a4efbd04b63cd03f5aff2561106ebcce00"
OWNER = "0x40907540d8a6c65c637785e8f8b742ae6b0b9968"
CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
USDC = DEFAULT_FROM_TOKEN
WETH = "0x0000000000000000000000000000000000000e7e"
STETH = "0xae7ab96520de3a18e5e111b5eaab095312d7fe84"
DC035 = "0xdc035d45d973e3ec169d2276ddab16f1e407384f"
COW_SOLD = "0x38eeb52f0771140d10c4e9a9a72349a329fe8a6a"
TAKER = "0x0000000000000000000000000000000000000abc"
WAD = 10**18
START_TOTAL = 250_000 * WAD
FLOOR_TOTAL = 100 * WAD
WEEK_ONE = 1_700_010_000
WEEK_TWO = WEEK_ONE + 7 * 86_400
DAY = 86_400
CURVE_ABI = json.loads(
    (Path(__file__).resolve().parents[2] / "artifacts/auction_source/curve-1/0xc014A92C76709D6c7f7c7841823b7164D6D2AbD4/abi.json").read_text()
)
assert DEFAULT_WANT_TOKEN  # Yearn fixtures keep their own want token.


def _metadata(token: str, decimals: int, symbol: str) -> TokenMetadata:
    return TokenMetadata(chain_id=1, token_address=token, symbol=symbol, name=symbol, decimals=decimals)


TOKENS = {
    USDC: _metadata(USDC, 6, "USDC"),
    WETH: _metadata(WETH, 18, "WETH"),
    CRVUSD: _metadata(CRVUSD, 18, "crvUSD"),
    STETH: _metadata(STETH, 18, "stETH"),
    DC035: _metadata(DC035, 18, "DC035"),
    COW_SOLD: _metadata(COW_SOLD, 18, "COWSOLD"),
}


def _snapshot(block_number: int):
    return make_snapshot(
        auction_address=BURNER,
        block_number=block_number,
        want_token=CRVUSD,
        governance=OWNER,
        receiver=FEE_COLLECTOR,
        starting_price_raw=str(START_TOTAL),
        minimum_price_raw=str(FLOOR_TOTAL),
        step_decay_rate_raw=None,
        step_duration_raw="36",
        auction_length_raw="86400",
    )


def _economics(block_number: int = 100):
    prepared = make_prepared(
        event_name="EconomicsSet", tx_nonce=block_number, block_number=block_number, address=BURNER,
        version="curve-1", capability_family="curve-1",
        payload={"want": CRVUSD, "start_total": START_TOTAL, "floor_total": FLOOR_TOTAL, "step_duration": 36},
        snapshot=_snapshot(block_number),
    )
    return replace(prepared, token_metadata=(TOKENS[CRVUSD],))


def _staged(tx_nonce: int, block_number: int, token: str, amount: int, starts_at: int = WEEK_ONE,
            log_index: int = 0, *, restage: bool = False):
    """A LotStaged log after translation. Collection reads no snapshot for a restage."""
    prepared = make_prepared(
        event_name="AuctionKicked", tx_nonce=tx_nonce, block_number=block_number, log_index=log_index,
        address=BURNER, version="curve-1", capability_family="curve-1",
        payload={"from": token, "available": amount, "startsAt": starts_at, "endsAt": starts_at + DAY},
        snapshot=None if restage else _snapshot(block_number),
    )
    return prepared if restage else replace(prepared, token_metadata=(TOKENS[token], TOKENS[CRVUSD]))


def _recovered(tx_nonce: int, block_number: int, token: str, amount: int):
    return make_prepared(
        event_name="AuctionSwept", tx_nonce=tx_nonce, block_number=block_number, address=BURNER,
        version="curve-1", capability_family="curve-1", payload={"token": token, "amount": amount},
    )


def _round_rows(writer):
    return {
        row["round_id"]: dict(row)
        for row in writer.fetchall("SELECT * FROM rounds WHERE auction_address = ? ORDER BY round_id", (BURNER,))
    }


def _statuses(writer):
    return {round_id: row["status"] for round_id, row in _round_rows(writer).items()}


def _seed_week(writer):
    batch = [
        _economics(),
        _staged(10, 110, USDC, 1_000 * 10**6),
        _staged(11, 111, WETH, 5 * WAD),
        # The next collect re-snapshots USDC for the same window.
        _staged(12, 120, USDC, 1_500 * 10**6, restage=True),
    ]
    writer.transaction(lambda conn: apply_batch(conn, batch))
    return batch


def test_lot_staged_and_economics_logs_decode_from_the_deployed_burner(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", "http://localhost:8545")
    settings = load_settings(target_network="ethereum")
    registry = AbiRegistry(settings)
    seed = settings.chains["ethereum"].auctions[0]
    assert (seed.address, seed.version, seed.start_block) == (BURNER, "curve-1", 26_385_347)

    def log(topics, data, block, log_index):
        return {
            "address": BURNER, "topics": [HexBytes(topic) for topic in topics], "data": HexBytes(data),
            "blockNumber": block, "blockHash": HexBytes("0x" + "11" * 32), "logIndex": log_index,
            "transactionHash": HexBytes("0x" + "22" * 32), "transactionIndex": 0,
        }

    def word(value: int) -> str:
        return f"{value:064x}"

    # Ethereum tx 0xd7570970…dfa: WBTC staged Monday for Tuesday's window.
    wbtc = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
    w3 = Web3()
    staged = registry.decode_auction_log(
        w3, "curve-1",
        log([registry.auction_event_topic("curve-1", "LotStaged"), "0x" + wbtc[2:].rjust(64, "0")],
            "0x" + word(180_144) + word(START_TOTAL) + word(FLOOR_TOTAL) + word(1_795_478_400) + word(1_795_564_800),
            26_474_107, 3),
        chain_id=1, timestamp=1_795_392_000,
    )
    assert staged.event_name == "AuctionKicked"
    assert staged.payload == {"from": wbtc, "available": 180_144, "startsAt": 1_795_478_400, "endsAt": 1_795_564_800}

    economics = registry.decode_auction_log(
        w3, "curve-1",
        log([registry.auction_event_topic("curve-1", "EconomicsSet"), "0x" + CRVUSD[2:].rjust(64, "0")],
            "0x" + word(START_TOTAL) + word(FLOOR_TOTAL) + word(36), 26_385_347, 1),
        chain_id=1, timestamp=1_794_323_771,
    )
    assert economics.event_name == "EconomicsSet"
    assert (economics.payload["want"], economics.payload["step_duration"]) == (CRVUSD, 36)

    recovered = registry.decode_auction_log(
        w3, "curve-1",
        log([registry.auction_event_topic("curve-1", "Recovered"), "0x" + wbtc[2:].rjust(64, "0")],
            "0x" + word(5), 26_500_000, 0),
        chain_id=1, timestamp=1_795_600_000,
    )
    assert (recovered.event_name, recovered.payload) == ("AuctionSwept", {"token": wbtc, "amount": 5})


def test_curve_lot_bounds_decode_totals_and_the_implied_step_decay():
    decoded = decode_params(
        "curve_lot_bounds",
        RawAuctionParams(
            starting_price_raw=str(START_TOTAL), minimum_price_raw=str(FLOOR_TOTAL),
            step_duration_raw="36", auction_length_raw="86400",
        ),
        want_decimals=18,
    )
    assert decoded.starting_price == "250000"
    assert decoded.floor_price == "100"
    assert decoded.minimum_price is None
    assert (decoded.step_duration_seconds, decoded.auction_length_seconds) == (36, 86_400)
    # The floor is reached in the last of (86400 - 1) // 36 = 2399 steps.
    decay = Decimal(decoded.step_decay_percent) / 100
    assert Decimal("0.0032") < decay < Decimal("0.0033")
    assert abs(Decimal(250_000) * (1 - decay) ** 2399 - 100) < Decimal("0.000001")
    # Without the want token's decimals the totals cannot be scaled.
    unscaled = decode_params("curve_lot_bounds", RawAuctionParams(starting_price_raw="1", minimum_price_raw="1"))
    assert (unscaled.starting_price, unscaled.floor_price) == (None, None)


def test_staged_lots_open_one_scheduled_round_per_token_and_window(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    _seed_week(writer)

    auction = writer.fetchone("SELECT * FROM auctions WHERE auction_address = ?", (BURNER,))
    assert auction["factory_address"] is None
    assert (auction["version"], auction["want_token"], auction["receiver"]) == ("curve-1", CRVUSD, FEE_COLLECTOR)
    params = writer.fetchone("SELECT * FROM auction_current_params WHERE auction_address = ?", (BURNER,))
    assert (params["param_schema"], params["starting_price"], params["floor_price"]) == ("curve_lot_bounds", "250000", "100")

    rounds = _round_rows(writer)
    assert sorted(rounds) == [1, 2]
    usdc, weth = rounds[1], rounds[2]
    assert (usdc["from_token"], weth["from_token"]) == (USDC, WETH)
    assert usdc["status"] == weth["status"] == "scheduled"
    assert (usdc["kicked_at"], usdc["scheduled_end_at"], usdc["end_at"]) == (WEEK_ONE, WEEK_ONE + DAY, WEEK_ONE + DAY)
    # The restage re-snapshotted USDC's lot rather than opening a round.
    assert (usdc["initial_available_raw"], usdc["remaining_available_raw"]) == (str(1_500 * 10**6), str(1_500 * 10**6))
    assert (usdc["starting_price"], usdc["floor_price"], usdc["minimum_price"]) == ("250000", "100", None)
    snapshots = writer.fetchall("SELECT round_id, snapshot_tx_hash FROM round_param_snapshot ORDER BY round_id")
    assert [(row["round_id"], row["snapshot_tx_hash"]) for row in snapshots] == [(1, f"0x{10:064x}"), (2, f"0x{11:064x}")]
    enabled = writer.fetchall("SELECT from_token FROM auction_tokens WHERE auction_address = ? ORDER BY from_token", (BURNER,))
    assert [row["from_token"] for row in enabled] == sorted([USDC, WETH])

    # Next week's collect restages USDC for a new window: a new round.
    writer.transaction(lambda conn: apply_batch(conn, [_staged(20, 700, USDC, 900 * 10**6, starts_at=WEEK_TWO)]))
    assert _round_rows(writer)[3]["kicked_at"] == WEEK_TWO


def test_windows_open_at_their_start_and_end_before_their_exclusive_end(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    _seed_week(writer)

    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE - 1))
    assert _statuses(writer) == {1: "scheduled", 2: "scheduled"}
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE))
    assert _statuses(writer) == {1: "live", 2: "live"}
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE + DAY - 1))
    assert _statuses(writer) == {1: "live", 2: "live"}
    # The window is [startsAt, endsAt): nothing trades at endsAt.
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE + DAY))
    assert _statuses(writer) == {1: "expired", 2: "expired"}
    # A reorg that moves indexed time back before the window reschedules it.
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE - 1))
    assert _statuses(writer) == {1: "scheduled", 2: "scheduled"}


def test_window_that_passed_within_one_batch_opens_and_expires_together(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    _seed_week(writer)
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE + 2 * DAY))
    assert set(_statuses(writer).values()) == {"expired"}


def test_a_restage_after_recovery_reopens_the_round_with_the_new_lot(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    writer.transaction(lambda conn: apply_batch(conn, [_economics(), _staged(10, 110, USDC, 1_000 * 10**6)]))
    # The owner recovers the lot, then a collect in the same COLLECT frame restages it.
    writer.transaction(lambda conn: apply_batch(conn, [_recovered(11, 111, USDC, 1_000 * 10**6)]))
    assert _round_rows(writer)[1]["status"] == "settled"
    writer.transaction(lambda conn: apply_batch(conn, [_staged(12, 112, USDC, 400 * 10**6, restage=True)]))
    restaged = _round_rows(writer)[1]
    assert (restaged["status"], restaged["settled_at"], restaged["end_at"]) == ("scheduled", None, WEEK_ONE + DAY)
    assert (restaged["initial_available_raw"], restaged["remaining_available_raw"]) == (str(400 * 10**6), str(400 * 10**6))
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE))
    assert _statuses(writer) == {1: "live"}


def test_an_empty_lot_waits_for_its_window_and_takes_a_later_stage(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    writer.transaction(lambda conn: apply_batch(conn, [_economics(), _staged(10, 110, USDC, 0)]))
    # Nothing sold, so an empty lot is not sold out.
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE - 10))
    assert _statuses(writer) == {1: "scheduled"}
    writer.transaction(lambda conn: apply_batch(conn, [_staged(11, 111, USDC, 7 * 10**6, restage=True)]))
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE))
    assert (_round_rows(writer)[1]["status"], _round_rows(writer)[1]["remaining_available_raw"]) == ("live", str(7 * 10**6))
    # Had it stayed empty, its window would still end in an expiry.
    writer.transaction(lambda conn: apply_batch(conn, [_staged(12, 112, WETH, 0)]))
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE + DAY))
    assert _statuses(writer) == {1: "expired", 2: "expired"}


def test_replay_rebuilds_restaged_rounds_from_stored_facts(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    _seed_week(writer)
    before = {round_id: {key: row[key] for key in ("from_token", "status", "kicked_at", "initial_available_raw", "floor_price")}
              for round_id, row in _round_rows(writer).items()}

    chain = SimpleNamespace(config=SimpleNamespace(chain_id=1, name="ethereum"),
                            reader=SimpleNamespace(header=lambda *_args, **_kwargs: None))
    hydrator = make_hydrator(
        read_event_token_metadata=lambda _chain, prepared: tuple(
            TOKENS[token] for token in {prepared.domain_event.payload.get("from"), CRVUSD} if token
        ),
    )

    def rebuild(conn):
        events = replay_module.load_native_events(conn, chain, hydrator)
        clear_projection_state(conn, 1)
        apply_native_event_projections(conn, events)

    writer.transaction(rebuild)
    after = {round_id: {key: row[key] for key in ("from_token", "status", "kicked_at", "initial_available_raw", "floor_price")}
             for round_id, row in _round_rows(writer).items()}
    assert after == before


def test_seeded_auctions_are_tracked_once_and_survive_projection_rebuilds(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    seed = AuctionSeed(address=BURNER, version="curve-1", capability_family="curve-1", start_block=100)
    assert writer.transaction(lambda conn: upsert_tracked_auction_seeds(conn, 1, (seed,))) == [seed]
    assert writer.transaction(lambda conn: upsert_tracked_auction_seeds(conn, 1, (seed,))) == []
    earlier = replace(seed, start_block=90)
    assert writer.transaction(lambda conn: upsert_tracked_auction_seeds(conn, 1, (earlier,))) == [earlier]

    writer.transaction(lambda conn: clear_projection_state(conn, 1))
    row = writer.fetchone("SELECT * FROM tracked_auctions WHERE auction_address = ?", (BURNER,))
    assert (row["factory_address"], row["discovered_block"], row["version"]) == (None, 90, "curve-1")


def test_kick_quotes_are_queued_when_indexed_time_crosses_the_window_start(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    batch = _seed_week(writer)
    assert writer.transaction(lambda conn: enqueue_pricing_work(conn, batch)) == 0

    def enqueue(after, until):
        return writer.transaction(lambda conn: enqueue_opened_round_pricing(
            conn, chain_id=1, after_timestamp=after, until_timestamp=until))

    assert enqueue(WEEK_ONE - 100, WEEK_ONE - 1) == 0
    # A lot sold out in the batch that opens its window is still quoted.
    writer.transaction(lambda conn: conn.execute(
        "UPDATE rounds SET status = 'sold_out', remaining_available_raw = '0' WHERE round_id = 2"))
    assert enqueue(WEEK_ONE - 1, WEEK_ONE + 12) == 4
    quote = writer.fetchone(
        "SELECT * FROM pricing_capture_queue WHERE round_id = 1 AND entity_kind = 'round_kick_quote'",
    )
    # The lot as finally staged, linked to the round's first kick.
    assert (quote["event_timestamp"], quote["amount_in_raw"]) == (WEEK_ONE, str(1_500 * 10**6))
    assert (quote["source_tx_hash"], quote["source_event_name"]) == (f"0x{10:064x}", "AuctionKicked")
    assert enqueue(WEEK_ONE + 12, WEEK_ONE + 24) == 0


# Receipts of four Ethereum fills from the burner's first window, trimmed to
# the logs that decide them; amounts, accounts and log indexes are on-chain.
# A fifth, built the same way, sells a lot out in its window's opening block.
def _pad(address: str) -> str:
    return "0x" + address[2:].rjust(64, "0")


def _log(address, topics, words, log_index):
    data = "0x" + "".join(f"{word:064x}" for word in words)
    return {"address": address, "topics": topics, "data": data, "logIndex": log_index}


def _transfer_log(token, sender, recipient, amount, log_index):
    return _log(token, [TRANSFER_TOPIC, _pad(sender), _pad(recipient)], [amount], log_index)


def _taken_log(token, caller, recipient, amount_out, payment, remaining, log_index):
    return _log(BURNER, [CURVE_TAKEN_TOPIC, _pad(token), _pad(caller)],
                [int(recipient, 16), amount_out, payment, remaining], log_index)


def _trade_log(owner, sell, buy, sell_amount, buy_amount, log_index):
    return _log(COW_SETTLEMENT, [COW_TRADE_TOPIC, _pad(owner)],
                [int(sell, 16), int(buy, 16), sell_amount, buy_amount, 0, 0xE0, 56], log_index)


STETH_FIRST_CALLER = "0x783200370d73753c73d3007c9bf47c91421d0e9a"
STETH_SECOND_CALLER = "0xb6e34ef28d91ccf9da456c97e715139502b7cf8b"
NATIVE_CALLER = "0x259008f1b4a156e29dd3520e7161ad934f565431"
COW_SOLVER = "0x5c3593481cba011737e36ded62f1797c9f6afce1"
STETH_LOT = 2_433_453_575_045_390_849
DC035_LOT = 9_677_519_494_821_469_507_193
COW_LOT = 1_354_554_029_542_462_254_555

FILLS = [
    {   # Built like the native receipts below: a lot sold out in the block that opens its window.
        "block": 499, "tx_from": TAKER,
        "transfer": (WETH, TAKER, 5 * WAD, 10),
        "logs": [
            _transfer_log(WETH, BURNER, TAKER, 5 * WAD, 10),
            _transfer_log(CRVUSD, TAKER, FEE_COLLECTOR, 12_000 * WAD, 11),
            _taken_log(WETH, TAKER, TAKER, 5 * WAD, 12_000 * WAD, 0, 12),
        ],
    },
    {   # 0x6d77cc…e487: a native take of the whole stETH lot. stETH rebased
        # during the window, so the lot still holds 159452204591176 wei.
        "block": 500, "tx_from": "0x3bf88fcc6ef008df2b2d2bafee3a529652bf5e68",
        "transfer": (STETH, STETH_FIRST_CALLER, STETH_LOT, 193),
        "logs": [
            _transfer_log(STETH, BURNER, STETH_FIRST_CALLER, STETH_LOT, 193),
            _transfer_log(CRVUSD, STETH_FIRST_CALLER, FEE_COLLECTOR, 4_118_075_393_629_161_311_446, 196),
            _taken_log(STETH, STETH_FIRST_CALLER, STETH_FIRST_CALLER, STETH_LOT,
                       4_118_075_393_629_161_311_446, 159_452_204_591_176, 197),
        ],
    },
    {   # 0xd526af…7c83: a second take sells that rebase; stETH's rounding leaves 1 wei.
        "block": 501, "tx_from": "0xa84ff98f90600bd7a79988b233bfa7ba3a481ddf",
        "transfer": (STETH, STETH_SECOND_CALLER, 159_452_204_591_176, 1028),
        "logs": [
            _transfer_log(STETH, BURNER, STETH_SECOND_CALLER, 159_452_204_591_176, 1028),
            _transfer_log(CRVUSD, STETH_SECOND_CALLER, FEE_COLLECTOR, 262_887_882_508_394_781, 1054),
            _taken_log(STETH, STETH_SECOND_CALLER, STETH_SECOND_CALLER, 159_452_204_591_176,
                       262_887_882_508_394_781, 1, 1055),
        ],
    },
    {   # 0xb3af0f…785f: the caller paid and sent the tokens to the FeeCollector itself.
        "block": 502, "tx_from": NATIVE_CALLER,
        "transfer": (DC035, FEE_COLLECTOR, 2_000 * WAD, 1164),
        "logs": [
            _transfer_log(DC035, BURNER, FEE_COLLECTOR, 2_000 * WAD, 1164),
            _transfer_log(CRVUSD, NATIVE_CALLER, FEE_COLLECTOR, 3_147_284_724_738_559_125_588, 1165),
            _taken_log(DC035, NATIVE_CALLER, FEE_COLLECTOR, 2_000 * WAD,
                       3_147_284_724_738_559_125_588, 7_677_519_494_821_469_507_193, 1166),
        ],
    },
    {   # 0x3a51e2…e883: a CoW settlement fills the burner's signed order beside another trade.
        "block": 503, "tx_from": COW_SOLVER, "available": 0,
        "transfer": (COW_SOLD, COW_SETTLEMENT, COW_LOT, 404),
        "logs": [
            _trade_log(BURNER, COW_SOLD, CRVUSD, COW_LOT, 1_896_689_346_798_844_534_186, 402),
            _trade_log("0x3cda13cd" + "00" * 16, USDC, WETH, 1_895_187_119, 1_946_358_564_423_554_930_730, 403),
            _transfer_log(COW_SOLD, BURNER, COW_SETTLEMENT, COW_LOT, 404),
            _transfer_log(CRVUSD, COW_SETTLEMENT, FEE_COLLECTOR, 1_896_689_346_798_844_534_186, 422),
        ],
    },
]


def _header(block: int) -> IndexedBlockRecord:
    return IndexedBlockRecord(1, block, f"0x{block:064x}", f"0x{block - 1:064x}", WEEK_ONE + (block - 499) * 12)


def _fill_raw_log(fill) -> RawLogRecord:
    token, recipient, amount, log_index = fill["transfer"]
    header = _header(fill["block"])
    return RawLogRecord(
        chain_id=1, block_number=header.block_number, block_hash=header.block_hash, tx_hash=header.block_hash,
        tx_index=0, log_index=log_index, address=token, topic0=TRANSFER_TOPIC, topic1=_pad(BURNER),
        topic2=_pad(recipient), topic3=None, data=hex(amount), timestamp=header.timestamp,
    )


class _FillsEth:
    """Serves the fills' transactions, receipts and the lot's post-fill availability."""

    def __init__(self):
        self.by_hash = {_header(fill["block"]).block_hash: fill for fill in FILLS}
        self.available_calls = 0

    def get_transaction(self, tx_hash):
        fill = self.by_hash[tx_hash]
        return {"hash": tx_hash, "blockHash": tx_hash, "from": fill["tx_from"], "input": "0x1105e47b"}

    def get_transaction_receipt(self, tx_hash):
        fill = self.by_hash[tx_hash]
        return {"transactionHash": tx_hash, "blockHash": tx_hash,
                "logs": [dict(log, transactionHash=tx_hash, blockHash=tx_hash) for log in fill["logs"]]}

    def call(self, transaction, block_identifier, ccip_read_enabled=False):
        self.available_calls += 1
        fill = self.by_hash[block_identifier["blockHash"]]
        return HexBytes(f"{fill['available']:064x}")


class _FillsWeb3:
    to_checksum_address = staticmethod(Web3.to_checksum_address)
    codec = Web3().codec

    def __init__(self):
        self.eth = _FillsEth()


class _CurveAbiRegistry:
    def auction_contract(self, _w3, address, _version):
        return Web3().eth.contract(address=Web3.to_checksum_address(address), abi=CURVE_ABI)


class _TokenHydrator:
    def read_token_metadata(self, _chain, token_address, *, block_number=None):
        return TOKENS[token_address]


def _fills_outcome(writer):
    rounds = {
        row["from_token"]: (row["status"], row["initial_available_raw"], row["sold_amount_raw"],
                            row["remaining_available_raw"], row["paid_amount_raw"], row["take_count"])
        for row in writer.fetchall("SELECT * FROM rounds WHERE auction_address = ?", (BURNER,))
    }
    takes = [
        (row["round_id"], row["from_token"], row["taker"], row["amount_taken_raw"], row["amount_paid_raw"])
        for row in writer.fetchall("SELECT * FROM takes ORDER BY timestamp, log_index")
    ]
    return rounds, takes


def test_fills_keep_inventory_attribution_and_proceeds_through_sync_and_replays(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    stages = [
        _staged(10, 110, STETH, 2_093_572_007_059_716),
        _staged(11, 111, DC035, DC035_LOT),
        _staged(12, 112, COW_SOLD, COW_LOT),
        _staged(13, 113, STETH, STETH_LOT, restage=True),
        # The owner recovers USDC's lot, and a later collect restages it for the same window.
        _staged(14, 114, USDC, 1_000 * 10**6),
        _recovered(15, 115, USDC, 1_000 * 10**6),
        _staged(16, 116, USDC, 400 * 10**6, restage=True),
        _staged(17, 117, WETH, 5 * WAD),
    ]
    raw_logs = [_fill_raw_log(fill) for fill in FILLS]
    w3 = _FillsWeb3()
    chain = SimpleNamespace(config=SimpleNamespace(chain_id=1, name="ethereum"), w3=w3)
    detector = TakeDetector(_CurveAbiRegistry(), _TokenHydrator())
    headers = [_header(fill["block"]) for fill in FILLS]

    # Incremental sync: the stages are collected in the same batch as the fills.
    writer.transaction(lambda conn: apply_batch(conn, [_economics()]))
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=w3, header_reader=_header, headers=headers)
    detected = detector._derive_take_events(chain, writer.connection, raw_logs, native_events=stages)

    def persist(conn):
        apply_batch(conn, stages)
        chain.reader.persist(conn)
        persist_raw_logs(conn, raw_logs)
        apply_batch(conn, detected)
        reconcile_round_statuses(conn, 1, headers[-1].timestamp)
        upsert_indexed_blocks(conn, [_header(block) for block in (100, *range(110, 118))])

    writer.transaction(persist)
    incremental = _fills_outcome(writer)
    rounds, takes = incremental
    # The restage after recovery is authoritative: the round waits for, then trades in, its window.
    assert rounds[USDC] == ("live", str(400 * 10**6), "0", str(400 * 10**6), None, 0)
    # A lot that sells out in the block that opens its window.
    assert rounds[WETH] == ("sold_out", str(5 * WAD), str(5 * WAD), "0", str(12_000 * WAD), 1)
    assert rounds[STETH] == ("live", str(STETH_LOT), str(STETH_LOT + 159_452_204_591_176), "1",
                             str(4_118_075_393_629_161_311_446 + 262_887_882_508_394_781), 2)
    assert rounds[DC035] == ("live", str(DC035_LOT), str(2_000 * WAD), "7677519494821469507193",
                             "3147284724738559125588", 1)
    assert rounds[COW_SOLD] == ("sold_out", str(COW_LOT), str(COW_LOT), "0", "1896689346798844534186", 1)
    # Native fills are the caller's; the CoW fill is the solver's, not the settlement's.
    assert [take[2] for take in takes] == [TAKER, STETH_FIRST_CALLER, STETH_SECOND_CALLER, NATIVE_CALLER, COW_SOLVER]
    methods = [json.loads(row["payload_json"])["matchingMethod"]
               for row in writer.fetchall("SELECT payload_json FROM domain_events WHERE event_name = 'Take' ORDER BY block_number")]
    assert methods == ["taken_event", "taken_event", "taken_event", "taken_event", "cow_trade"]
    assert w3.eth.available_calls == 1  # only the adapter fill reads the lot's availability

    # Indexed time crossed every window's start in this batch: each lot is quoted as finally
    # staged, the one sold in its opening block and the restaged one included.
    writer.transaction(lambda conn: enqueue_opened_round_pricing(
        conn, chain_id=1, after_timestamp=WEEK_ONE - 1, until_timestamp=headers[-1].timestamp))
    quoted = {
        row["from_token"]: row["amount_in_raw"]
        for row in writer.fetchall("SELECT from_token, amount_in_raw FROM pricing_capture_queue WHERE entity_kind = 'round_kick_quote'")
    }
    assert quoted == {STETH: str(STETH_LOT), DC035: str(DC035_LOT), COW_SOLD: str(COW_LOT),
                      USDC: str(400 * 10**6), WETH: str(5 * WAD)}

    offline = SimpleNamespace(config=chain.config, w3=w3)

    def replay_takes():
        offline.reader = BlockReader(writer.connection, chain_id=1, w3=w3, header_reader=None, offline=True)
        return TakeDetector(_CurveAbiRegistry(), _TokenHydrator()).replay_chain(offline, writer.connection)

    # Full replay from stored facts.
    hydrator = make_hydrator(read_event_token_metadata=lambda _chain, prepared: prepared.token_metadata)
    offline.reader = BlockReader(writer.connection, chain_id=1, w3=w3, header_reader=None, offline=True)
    native = replay_module.load_native_events(writer.connection, offline, hydrator)
    take_events = replay_takes()

    def full_replay(conn):
        delete_derived_take_events(conn, 1)
        clear_projection_state(conn, 1)
        apply_native_event_projections(conn, native)
        apply_batch(conn, take_events)
        reconcile_round_statuses(conn, 1, headers[-1].timestamp)

    writer.transaction(full_replay)
    assert _fills_outcome(writer) == incremental

    # Takes-only replay.
    take_events = replay_takes()

    def takes_replay(conn):
        delete_derived_take_events(conn, 1)
        clear_take_state(conn, 1)
        apply_batch(conn, take_events)
        reconcile_round_statuses(conn, 1, headers[-1].timestamp)

    writer.transaction(takes_replay)
    assert _fills_outcome(writer) == incremental
    assert w3.eth.available_calls == 1  # replays read the stored observation


def test_receipt_readers_claim_each_payment_log_once():
    logs = [
        _transfer_log(USDC, BURNER, TAKER, 5, 1),
        _taken_log(USDC, TAKER, TAKER, 5, 50, 0, 2),
        _transfer_log(USDC, BURNER, TAKER, 5, 3),
        _taken_log(USDC, TAKER, TAKER, 5, 51, 0, 4),
    ]
    claimed: set[int] = set()
    first = find_curve_taken(logs, auction=BURNER, token=USDC, amount_taken=5, transfer_log_index=1, claimed=claimed)
    claimed.add(first["log_index"])
    second = find_curve_taken(logs, auction=BURNER, token=USDC, amount_taken=5, transfer_log_index=1, claimed=claimed)
    assert (first["payment"], second["payment"]) == (50, 51)

    trades = [_trade_log(BURNER, USDC, CRVUSD, 5, 60, 7), _trade_log(BURNER, USDC, CRVUSD, 5, 61, 8)]
    claimed = {7}
    assert find_cow_trade(trades, owner=BURNER, sell_token=USDC, buy_token=CRVUSD, sell_amount=5, claimed=claimed)["payment"] == 61
    assert find_cow_trade(trades, owner=BURNER, sell_token=USDC, buy_token=WETH, sell_amount=5, claimed=set()) is None


def test_only_the_recovered_transfer_is_excluded_from_takes():
    recovered = _log(BURNER, [CURVE_RECOVERED_TOPIC, _pad(USDC)], [1_000], 9)
    assert is_curve_recovery([recovered], auction=BURNER, token=USDC, amount=1_000)
    assert not is_curve_recovery([recovered], auction=BURNER, token=USDC, amount=999)
    assert not is_curve_recovery([recovered], auction=BURNER, token=WETH, amount=1_000)


def test_takes_resolve_to_the_window_that_holds_them(tmp_path):
    writer = Writer(str(tmp_path / "curve.sqlite3"))
    _seed_week(writer)
    detector = TakeDetector(None, None)

    def window(token, timestamp, native_events=()):
        found = detector._lot_window(writer.connection, chain_id=1, auction_address=BURNER, token=token,
                                     timestamp=timestamp, native_events=list(native_events))
        return None if found is None else (found.starts_at, found.want_token, found.receiver)

    assert window(USDC, WEEK_ONE) == (WEEK_ONE, CRVUSD, FEE_COLLECTOR)
    assert window(WETH, WEEK_ONE + DAY - 1) == (WEEK_ONE, CRVUSD, FEE_COLLECTOR)
    assert window(USDC, WEEK_ONE - 1) is None
    assert window(USDC, WEEK_ONE + DAY) is None
    # A window first staged in the same batch is found from its first stage.
    in_flight = [_staged(30, 700, WETH, WAD, starts_at=WEEK_TWO), _staged(31, 701, WETH, 2 * WAD, starts_at=WEEK_TWO, restage=True)]
    assert window(WETH, WEEK_TWO + 5, in_flight) == (WEEK_TWO, CRVUSD, FEE_COLLECTOR)


def _seed_api(path) -> None:
    writer = Writer(str(path))
    _seed_week(writer)
    take = make_prepared(
        event_name="Take", tx_nonce=40, block_number=800, log_index=4, address=USDC, auction_address=BURNER,
        version="curve-1", capability_family="curve-1",
        payload={
            "window": WEEK_ONE, "taker": TAKER, "receiver": FEE_COLLECTOR, "from": USDC, "to": CRVUSD,
            "amountTaken": 1_500 * 10**6, "amountPaid": 1_499 * WAD, "expectedAmountPaid": None,
            "priceE18": 999_333_333_333_333_333, "matchingMethod": "taken_event", "remainingAvailable": 0,
        },
    )
    writer.transaction(lambda conn: apply_batch(conn, [take]))
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE + 60))
    writer.transaction(lambda conn: update_sync_state(
        conn, chain_id=1, network_name="ethereum", latest_rpc_head=900, confirmed_head=900,
        last_confirmed_processed=900, last_live_processed=900, health="ok",
    ))


def test_api_lists_burner_rounds_with_protocol_and_floor(tmp_path):
    path = tmp_path / "curve.sqlite3"
    _seed_api(path)
    client = TestClient(create_app(db_path=str(path)))

    curve = client.get("/api/rounds", params={"protocol": "curve"}).json()
    assert curve["status_counts"] == {"all": 2, "scheduled": 0, "live": 1, "sold_out": 1, "expired": 0, "settled": 0}
    by_round = {item["round_id"]: item for item in curve["rounds"]}
    usdc = by_round[1]
    assert (usdc["protocol"], usdc["version"], usdc["status"]) == ("curve", "curve-1", "sold_out")
    # A lot total of 250,000 and 100 crvUSD over 1,500 USDC, per USDC.
    assert abs(Decimal(usdc["starting_price_per_unit"]) - Decimal(250_000) / 1_500) < Decimal("1e-20")
    assert abs(Decimal(usdc["floor_price_per_unit"]) - Decimal(100) / 1_500) < Decimal("1e-20")
    assert usdc["minimum_price"] is None
    assert Decimal(usdc["decay_percent"].rstrip("%")) > 0

    assert client.get("/api/rounds", params={"protocol": "yearn"}).json()["total"] == 0
    assert client.get("/api/rounds", params={"protocol": "other"}).status_code == 422

    detail = client.get(f"/api/auctions/{BURNER}", params={"chain_id": 1}).json()
    assert detail["protocol"] == "curve"
    assert (detail["parameters"]["starting_price"], detail["parameters"]["floor_price"]) == ("250000", "100")
    assert {token["address"].lower() for token in detail["from_tokens"]} == {USDC, WETH}


def test_api_counts_rounds_waiting_for_their_window(tmp_path):
    path = tmp_path / "curve.sqlite3"
    writer = Writer(str(path))
    _seed_week(writer)
    writer.transaction(lambda conn: update_sync_state(
        conn, chain_id=1, network_name="ethereum", latest_rpc_head=200, confirmed_head=200,
        last_confirmed_processed=200, last_live_processed=200, health="ok",
    ))
    client = TestClient(create_app(db_path=str(path)))
    scheduled = client.get("/api/rounds", params={"status": "scheduled"}).json()
    assert scheduled["total"] == 2
    assert {item["status"] for item in scheduled["rounds"]} == {"scheduled"}
    assert not any(item["is_active"] for item in scheduled["rounds"])


@pytest.mark.parametrize("from_decimals, raw, expected", [(6, 10**30, 10**18), (18, 7 * 10**17, 7 * 10**17)])
def test_live_price_reads_curve_quotes_per_whole_token(monkeypatch, from_decimals, raw, expected):
    from backend.indexer import live_price
    from .test_observations import _Provider

    monkeypatch.setenv("ETHEREUM_RPC_URL", "http://localhost:8545")
    provider = _Provider()
    monkeypatch.setattr(live_price, "HTTPProvider", lambda *args, **kwargs: provider)
    live_price._network_runtime.cache_clear()
    _, w3 = live_price._network_runtime("ethereum")
    call = w3.eth.contract(address=Web3.to_checksum_address(BURNER), abi=[{
        "type": "function", "name": "price", "stateMutability": "view",
        "inputs": [{"name": "_from", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}],
    }]).functions.price(Web3.to_checksum_address(USDC))._encode_transaction_data()
    provider.results[call] = "0x" + f"{raw:064x}"
    result = live_price.read_live_round_price(
        network_key="ethereum", version="curve-1", auction_address=BURNER, from_token=USDC,
        want_token=CRVUSD, block_hash="0x" + "33" * 32, from_decimals=from_decimals,
    )
    live_price._network_runtime.cache_clear()
    # Curve quotes per 1e18 raw units; the API reads per whole token.
    assert result.current_price_raw == str(expected)


def test_lots_opening_together_share_one_want_token_price_request(tmp_path):
    from backend.indexer.pricing import PricingCaptureRuntime
    from .helpers import capture_due_pricing
    from .test_pricing import _FakePricingClient

    class _CountingClient(_FakePricingClient):
        price_requests = 0

        def fetch_price(self, **kwargs):
            type(self).price_requests += 1
            return super().fetch_price(**kwargs)

    writer = Writer(str(tmp_path / "curve.sqlite3"))
    _seed_week(writer)
    writer.transaction(lambda conn: reconcile_round_statuses(conn, 1, WEEK_ONE))
    assert writer.transaction(lambda conn: enqueue_opened_round_pricing(
        conn, chain_id=1, after_timestamp=WEEK_ONE - 1, until_timestamp=WEEK_ONE)) == 4

    runtime = PricingCaptureRuntime(client=_CountingClient(), max_capture_lag_seconds=10**10, max_concurrency=1)
    capture_due_pricing(runtime, writer, chain_id=1)

    assert _CountingClient.price_requests == 1
    facts = writer.fetchall("SELECT round_id, source_tx_hash FROM pricing_price_facts ORDER BY round_id")
    # Each round keeps its own fact, linked to its own first kick.
    assert [(row["round_id"], row["source_tx_hash"]) for row in facts] == [(1, f"0x{10:064x}"), (2, f"0x{11:064x}")]
    assert writer.fetchone("SELECT COUNT(*) AS n FROM pricing_capture_queue")["n"] == 0
