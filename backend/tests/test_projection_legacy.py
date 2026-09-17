from __future__ import annotations

from backend.indexer.projections import apply_batch
from backend.indexer.writer import Writer

from .helpers import DEFAULT_AUCTION, DEFAULT_FACTORY, DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN, make_prepared, make_snapshot


def test_apply_batch_projects_legacy_kick_from_prior_auction_enabled(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    auction_id = "0x" + "11" * 32

    deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=1,
        block_number=100,
        address=DEFAULT_FACTORY,
        auction_address=DEFAULT_AUCTION,
        version="0.0.1",
        capability_family="0.0.1",
        payload={"want": DEFAULT_WANT_TOKEN},
        snapshot=make_snapshot(
            block_number=100,
            receiver=None,
            starting_price_raw="100",
            minimum_price_raw=None,
            step_decay_rate_raw=None,
            step_duration_raw=None,
            auction_length_raw="3600",
        ),
    )
    enabled = make_prepared(
        event_name="AuctionEnabled",
        tx_nonce=2,
        block_number=101,
        version="0.0.1",
        capability_family="0.0.1",
        payload={
            "auctionId": auction_id,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "auctionAddress": DEFAULT_AUCTION,
        },
    )
    kicked = make_prepared(
        event_name="AuctionKicked",
        tx_nonce=3,
        block_number=102,
        version="0.0.1",
        capability_family="0.0.1",
        payload={"auctionId": auction_id, "available": 321},
        snapshot=make_snapshot(
            block_number=102,
            receiver=None,
            starting_price_raw="100",
            minimum_price_raw=None,
            step_decay_rate_raw=None,
            step_duration_raw=None,
            auction_length_raw="3600",
        ),
    )

    inserted = writer.transaction(lambda conn: apply_batch(conn, [deployment, enabled, kicked]))

    assert inserted == 3
    round_row = writer.fetchone(
        """
        SELECT round_id, from_token, want_token, initial_available_raw
          FROM rounds
         WHERE chain_id = 1 AND auction_address = ?
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(round_row) == {
        "round_id": 1,
        "from_token": DEFAULT_FROM_TOKEN,
        "want_token": DEFAULT_WANT_TOKEN,
        "initial_available_raw": "321",
    }
