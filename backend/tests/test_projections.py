from backend.indexer.projections import apply_batch
from backend.indexer.types import AuctionSnapshot, DomainEventRecord, PreparedEvent, RawLogRecord
from backend.indexer.writer import Writer


def _raw(tx_byte: int, log_index: int, block_number: int) -> RawLogRecord:
    return RawLogRecord(
        chain_id=1,
        block_number=block_number,
        block_hash=f"0x{tx_byte:064x}",
        tx_hash=f"0x{tx_byte:064x}",
        tx_index=0,
        log_index=log_index,
        address="0x0000000000000000000000000000000000000aaa",
        topic0="0x01",
        topic1="0x02",
        topic2=None,
        topic3=None,
        data="0x",
        timestamp=1_700_000_000 + block_number,
    )


def _kicked(tx_byte: int, log_index: int, block_number: int, available: int) -> PreparedEvent:
    raw_log = _raw(tx_byte, log_index, block_number)
    event = DomainEventRecord(
        chain_id=1,
        block_number=block_number,
        block_hash=raw_log.block_hash,
        tx_hash=raw_log.tx_hash,
        tx_index=raw_log.tx_index,
        log_index=log_index,
        event_name="AuctionKicked",
        address=raw_log.address,
        auction_address=raw_log.address,
        version="1.0.4",
        capability_family="1.0.4",
        payload={
            "from": "0x0000000000000000000000000000000000000bbb",
            "available": available,
        },
        timestamp=raw_log.timestamp,
    )
    snapshot = AuctionSnapshot(
        chain_id=1,
        auction_address=raw_log.address,
        block_number=block_number,
        want_token="0x0000000000000000000000000000000000000ccc",
        governance="0x0000000000000000000000000000000000000ddd",
        receiver="0x0000000000000000000000000000000000000eee",
        starting_price_raw="100",
        minimum_price_raw="50",
        step_decay_rate_raw="25",
        step_duration_raw="60",
        auction_length_raw="86400",
        extra_params={},
    )
    return PreparedEvent(raw_log=raw_log, domain_event=event, snapshot=snapshot)


def test_apply_batch_assigns_deterministic_round_ids(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    first = _kicked(tx_byte=1, log_index=0, block_number=100, available=500)
    second = _kicked(tx_byte=2, log_index=0, block_number=101, available=600)

    inserted = writer.transaction(lambda conn: apply_batch(conn, [first, second]))

    assert inserted == 2
    rows = writer.fetchall(
        """
        SELECT round_id, from_token, want_token, initial_available_raw
          FROM rounds
         ORDER BY round_id ASC
        """
    )

    assert [row["round_id"] for row in rows] == [1, 2]
    assert rows[0]["from_token"] == "0x0000000000000000000000000000000000000bbb"
    assert rows[0]["want_token"] == "0x0000000000000000000000000000000000000ccc"
    assert rows[1]["initial_available_raw"] == "600"
