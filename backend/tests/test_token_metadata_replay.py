from dataclasses import replace

import pytest

from backend.indexer.projections import (
    apply_batch, apply_native_event_projections, apply_take_event_projections,
    clear_projection_state,
)
from backend.indexer.types import TokenMetadata
from backend.indexer.writer import Writer
from .helpers import DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN, make_prepared
from .test_reorg_runtime import _base_events


@pytest.mark.parametrize("latest_symbol,latest_name", [("NEW", "New name"), (None, None)])
def test_metadata_is_independent_of_native_take_batching_and_drops_orphans(tmp_path, latest_symbol, latest_name):
    events = _base_events()
    old = TokenMetadata(1, DEFAULT_FROM_TOKEN, "OLD", "Old name", 18)
    new = replace(old, symbol=latest_symbol, name=latest_name)
    take = replace(events["take_old"], token_metadata=(old,))
    updated = replace(make_prepared(
        event_name="AuctionEnabled", tx_nonce=50, block_number=105,
        payload={"from": DEFAULT_FROM_TOKEN, "to": DEFAULT_WANT_TOKEN},
    ), token_metadata=(new,))
    native = [events["deployment"], events["enabled"], events["kicked"], updated]
    for name, batches in (
        ("one", [[*native, take]]),
        ("split", [[*native[:-1], take], [updated]]),
    ):
        writer = Writer(str(tmp_path / f"{name}.sqlite3"))
        for batch in batches:
            writer.transaction(lambda conn: apply_batch(conn, batch))
        assert tuple(writer.fetchone("SELECT symbol, name, metadata_block FROM tokens")) == (latest_symbol, latest_name, 105)
        writer.transaction(lambda conn: conn.execute(
            "INSERT INTO tokens (chain_id, token_address, symbol, metadata_updated_at, metadata_block) VALUES (1, 'orphan', 'ORPHAN', 0, 106)"))
        writer.transaction(lambda conn: (
            clear_projection_state(conn, 1),
            apply_native_event_projections(conn, native),
            apply_take_event_projections(conn, [take]),
        ))
        assert writer.fetchone("SELECT COUNT(*) FROM tokens")[0] == 1
        assert tuple(writer.fetchone("SELECT symbol, name, metadata_block FROM tokens")) == (latest_symbol, latest_name, 105)
