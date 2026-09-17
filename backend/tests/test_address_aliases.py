from __future__ import annotations

from backend.indexer.address_aliases import (
    AddressAliasUpdate,
    apply_address_alias_updates,
    load_address_alias_backfill_candidates,
)
from backend.indexer.projections import apply_batch
from backend.indexer.writer import Writer

from .helpers import (
    DEFAULT_AUCTION,
    DEFAULT_CHAIN_ID,
    DEFAULT_FACTORY,
    DEFAULT_FROM_TOKEN,
    DEFAULT_RECEIVER,
    DEFAULT_WANT_TOKEN,
    make_prepared,
    make_snapshot,
)


SECOND_RECEIVER = "0x0000000000000000000000000000000000000f11"


def _seed_receiver_facts(path) -> Writer:
    writer = Writer(str(path))
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
    writer.transaction(lambda conn: apply_batch(conn, [deployment, enabled, kicked]))
    return writer


def test_load_address_alias_backfill_candidates_respects_retry_window_and_takes_receiver(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_receiver_facts(db_path)
    writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO address_aliases (chain_id, address, alias_text, checked_at)
            VALUES (?, ?, ?, ?)
            """,
            (DEFAULT_CHAIN_ID, DEFAULT_RECEIVER, None, 950),
        )
    )
    writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO takes (
                chain_id,
                auction_address,
                round_id,
                take_seq,
                tx_hash,
                tx_index,
                log_index,
                taker,
                receiver,
                from_token,
                want_token,
                amount_taken_raw,
                amount_paid_raw,
                expected_amount_paid_raw,
                timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                DEFAULT_CHAIN_ID,
                DEFAULT_AUCTION,
                99,
                1,
                "0x0000000000000000000000000000000000000000000000000000000000000abc",
                0,
                0,
                "0x0000000000000000000000000000000000000123",
                SECOND_RECEIVER,
                DEFAULT_FROM_TOKEN,
                DEFAULT_WANT_TOKEN,
                "1",
                "1",
                "1",
                1_700_000_999,
            ),
        )
    )

    candidates = load_address_alias_backfill_candidates(
        writer.connection,
        chain_id=DEFAULT_CHAIN_ID,
        force=False,
        now=1_000,
        retry_after_seconds=200,
    )

    assert [item.address for item in candidates] == [SECOND_RECEIVER]


def test_apply_address_alias_updates_persists_alias_and_checked_at(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = Writer(str(db_path))

    updated = writer.transaction(
        lambda conn: apply_address_alias_updates(
            conn,
            [
                AddressAliasUpdate(
                    chain_id=DEFAULT_CHAIN_ID,
                    address=DEFAULT_RECEIVER,
                    alias_text="Treasury Receiver",
                    checked_at=1_234,
                ),
                AddressAliasUpdate(
                    chain_id=DEFAULT_CHAIN_ID,
                    address=SECOND_RECEIVER,
                    alias_text=None,
                    checked_at=1_235,
                ),
            ],
        )
    )

    assert updated == 2

    alias_row = writer.fetchone(
        """
        SELECT alias_text, checked_at
          FROM address_aliases
         WHERE chain_id = ? AND address = ?
        """,
        (DEFAULT_CHAIN_ID, DEFAULT_RECEIVER),
    )
    assert dict(alias_row) == {
        "alias_text": "Treasury Receiver",
        "checked_at": 1_234,
    }

    missing_row = writer.fetchone(
        """
        SELECT alias_text, checked_at
          FROM address_aliases
         WHERE chain_id = ? AND address = ?
        """,
        (DEFAULT_CHAIN_ID, SECOND_RECEIVER),
    )
    assert dict(missing_row) == {
        "alias_text": None,
        "checked_at": 1_235,
    }
