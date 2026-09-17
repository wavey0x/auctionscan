from __future__ import annotations

import json

from backend.indexer.projections import apply_batch
from backend.indexer.writer import Writer

from .helpers import (
    DEFAULT_AUCTION,
    DEFAULT_FACTORY,
    DEFAULT_FROM_TOKEN,
    DEFAULT_WANT_TOKEN,
    UPDATED_RECEIVER,
    make_prepared,
    make_snapshot,
)


def test_apply_batch_projects_lifecycle_state_and_is_idempotent(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=1,
        block_number=100,
        address=DEFAULT_FACTORY,
        auction_address=DEFAULT_AUCTION,
        payload={"deployer": "0x00000000000000000000000000000000000000de", "want": DEFAULT_WANT_TOKEN},
        snapshot=make_snapshot(block_number=100),
    )
    enabled = make_prepared(
        event_name="AuctionEnabled",
        tx_nonce=2,
        block_number=101,
        payload={"from": DEFAULT_FROM_TOKEN, "to": DEFAULT_WANT_TOKEN},
    )
    receiver_updated = make_prepared(
        event_name="UpdatedReceiver",
        tx_nonce=3,
        block_number=102,
        payload={"receiver": UPDATED_RECEIVER},
    )
    minimum_updated = make_prepared(
        event_name="UpdatedMinimumPrice",
        tx_nonce=4,
        block_number=103,
        payload={"minimumPrice": 42},
    )
    kicked = make_prepared(
        event_name="AuctionKicked",
        tx_nonce=5,
        block_number=104,
        payload={"from": DEFAULT_FROM_TOKEN, "available": 500},
        snapshot=make_snapshot(block_number=104, receiver=UPDATED_RECEIVER, minimum_price_raw="42"),
    )
    settled = make_prepared(
        event_name="AuctionSettled",
        tx_nonce=6,
        block_number=105,
        payload={"from": DEFAULT_FROM_TOKEN},
    )
    disabled = make_prepared(
        event_name="AuctionDisabled",
        tx_nonce=7,
        block_number=106,
        payload={"from": DEFAULT_FROM_TOKEN},
    )
    swept = make_prepared(
        event_name="AuctionSwept",
        tx_nonce=8,
        block_number=107,
    )

    batch = [deployment, enabled, receiver_updated, minimum_updated, kicked, settled, disabled, swept]

    inserted = writer.transaction(lambda conn: apply_batch(conn, batch))
    replayed = writer.transaction(lambda conn: apply_batch(conn, batch))

    assert inserted == len(batch)
    assert replayed == 0

    auction = writer.fetchone(
        """
        SELECT factory_address, receiver, want_token, has_enabled_tokens, latest_lifecycle_block
          FROM auctions
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(auction) == {
        "factory_address": DEFAULT_FACTORY,
        "receiver": UPDATED_RECEIVER,
        "want_token": DEFAULT_WANT_TOKEN,
        "has_enabled_tokens": 0,
        "latest_lifecycle_block": 107,
    }

    token_row = writer.fetchone(
        """
        SELECT currently_enabled, enabled_at_block, disabled_at_block, latest_lifecycle_block
          FROM auction_tokens
         WHERE chain_id = 1 AND auction_address = ? AND from_token = ?
        """,
        (DEFAULT_AUCTION, DEFAULT_FROM_TOKEN),
    )
    assert dict(token_row) == {
        "currently_enabled": 0,
        "enabled_at_block": 101,
        "disabled_at_block": 106,
        "latest_lifecycle_block": 106,
    }

    params = writer.fetchone(
        """
        SELECT param_schema, receiver, minimum_price_raw, starting_price_raw, minimum_price,
               starting_price, step_decay_percent, step_duration_seconds, auction_length_seconds,
               extra_params_json, last_updated_block
          FROM auction_current_params
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(params) == {
        "param_schema": "v1_wad_bps",
        "receiver": UPDATED_RECEIVER,
        "minimum_price_raw": "42",
        "starting_price_raw": "100",
        "minimum_price": "0.000000000000000042",
        "starting_price": "100",
        "step_decay_percent": "0.25",
        "step_duration_seconds": 60,
        "auction_length_seconds": 86400,
        "extra_params_json": "{}",
        "last_updated_block": 103,
    }

    round_row = writer.fetchone(
        """
        SELECT round_id, status, settled_at, initial_available_raw, receiver, minimum_price_raw,
               minimum_price, starting_price, step_decay_percent, step_duration_seconds,
               auction_length_seconds
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(round_row) == {
        "round_id": 1,
        "status": "settled",
        "settled_at": 1_700_000_105,
        "initial_available_raw": "500",
        "receiver": UPDATED_RECEIVER,
        "minimum_price_raw": "42",
        "minimum_price": "0.000000000000000042",
        "starting_price": "100",
        "step_decay_percent": "0.25",
        "step_duration_seconds": 60,
        "auction_length_seconds": 86400,
    }

    snapshot_row = writer.fetchone(
        """
        SELECT param_schema
          FROM round_param_snapshot
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(snapshot_row) == {"param_schema": "v1_wad_bps"}

    event_count = writer.fetchone("SELECT COUNT(*) AS count FROM domain_events")
    param_history_count = writer.fetchone("SELECT COUNT(*) AS count FROM auction_param_history")
    assert event_count["count"] == len(batch)
    assert param_history_count["count"] == 2


def test_apply_batch_decodes_1_0_5_wad_scaled_starting_price(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    starting_price_raw = "100000000000000000000"
    minimum_price_raw = "50000000000000000000"
    snapshot = make_snapshot(
        block_number=100,
        starting_price_raw=starting_price_raw,
        minimum_price_raw=minimum_price_raw,
    )
    deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=1,
        block_number=100,
        address=DEFAULT_FACTORY,
        auction_address=DEFAULT_AUCTION,
        version="1.0.5",
        capability_family="1.0.5",
        payload={"want": DEFAULT_WANT_TOKEN},
        snapshot=snapshot,
    )
    kicked = make_prepared(
        event_name="AuctionKicked",
        tx_nonce=2,
        block_number=101,
        version="1.0.5",
        capability_family="1.0.5",
        payload={"from": DEFAULT_FROM_TOKEN, "available": 500},
        snapshot=make_snapshot(
            block_number=101,
            starting_price_raw=starting_price_raw,
            minimum_price_raw=minimum_price_raw,
        ),
    )

    inserted = writer.transaction(lambda conn: apply_batch(conn, [deployment, kicked]))

    assert inserted == 2
    params = writer.fetchone(
        """
        SELECT param_schema, minimum_price_raw, starting_price_raw, minimum_price,
               starting_price, step_decay_percent, step_duration_seconds,
               auction_length_seconds
          FROM auction_current_params
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(params) == {
        "param_schema": "v1_wad_start_wad_bps",
        "minimum_price_raw": minimum_price_raw,
        "starting_price_raw": starting_price_raw,
        "minimum_price": "50",
        "starting_price": "100",
        "step_decay_percent": "0.25",
        "step_duration_seconds": 60,
        "auction_length_seconds": 86400,
    }

    round_row = writer.fetchone(
        """
        SELECT minimum_price_raw, starting_price_raw, minimum_price, starting_price
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(round_row) == {
        "minimum_price_raw": minimum_price_raw,
        "starting_price_raw": starting_price_raw,
        "minimum_price": "50",
        "starting_price": "100",
    }

    snapshot_row = writer.fetchone(
        """
        SELECT param_schema
          FROM round_param_snapshot
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(snapshot_row) == {"param_schema": "v1_wad_start_wad_bps"}

    deploy_fact = writer.fetchone(
        """
        SELECT param_schema, minimum_price_raw, starting_price_raw
          FROM auction_snapshot_facts
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(deploy_fact) == {
        "param_schema": "v1_wad_start_wad_bps",
        "minimum_price_raw": minimum_price_raw,
        "starting_price_raw": starting_price_raw,
    }


def test_apply_batch_merges_updated_let_cow_peek_extra_params(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=1,
        block_number=200,
        address=DEFAULT_FACTORY,
        auction_address=DEFAULT_AUCTION,
        version="1.0.3cc",
        capability_family="1.0.3",
        payload={"deployer": "0x00000000000000000000000000000000000000de", "want": DEFAULT_WANT_TOKEN},
        snapshot=make_snapshot(block_number=200, extra_params={"origin": "snapshot"}),
    )
    let_cow_peek = make_prepared(
        event_name="UpdatedLetCowPeek",
        tx_nonce=2,
        block_number=201,
        version="1.0.3cc",
        capability_family="1.0.3",
        payload={"letCowPeek": True},
    )

    inserted = writer.transaction(lambda conn: apply_batch(conn, [deployment, let_cow_peek]))

    assert inserted == 2
    params = writer.fetchone(
        """
        SELECT extra_params_json, last_updated_block
          FROM auction_current_params
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert params["last_updated_block"] == 201
    assert json.loads(params["extra_params_json"]) == {"letCowPeek": True, "origin": "snapshot"}

    history = writer.fetchone(
        """
        SELECT param_key, value_text, value_json
          FROM auction_param_history
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(history) == {
        "param_key": "letCowPeek",
        "value_text": "1",
        "value_json": '{"letCowPeek":true,"origin":"snapshot"}',
    }
