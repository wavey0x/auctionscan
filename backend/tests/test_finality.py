from dataclasses import replace

import pytest

from .test_reorg_runtime import _base_events, _base_headers, _build_runtime, _header


def _runtime(tmp_path, heads, finality=101, **kwargs):
    events = _base_events()
    runtime, chain = _build_runtime(
        tmp_path, latest_heads=heads, headers=_base_headers(),
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        **kwargs,
    )
    chain.finality_mode = "finalized"
    chain.finalized_number = finality
    chain.confirmed_header = lambda _latest: chain.block_header(chain.finalized_number)
    return runtime, chain


def test_finalized_indexed_checkpoint_has_its_own_height_and_hash(tmp_path):
    runtime, chain = _runtime(tmp_path, [104], finality=103)
    runtime.sync_chain_once(max_blocks=1)
    state = runtime._load_sync_state_row()
    assert state["confirmed_head"] == 103
    assert state["confirmed_head_hash"] == chain.headers[103].block_hash
    assert state["last_confirmed_processed"] == state["last_live_processed"] == 100
    assert state["last_confirmed_hash"] == chain.headers[100].block_hash


def test_stalled_and_regressed_finality_keep_following_live_head(tmp_path):
    runtime, chain = _runtime(tmp_path, [104, 104, 105, 105])
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    assert runtime._load_sync_state_row()["last_live_processed"] == 105
    chain.finalized_number = 100
    runtime.sync_chain_once()
    state = runtime._load_sync_state_row()
    assert state["last_confirmed_processed"] == 101
    assert state["last_confirmed_hash"] == chain.headers[101].block_hash
    assert state["confirmed_head"] == 101
    assert "regressed" in state["finality_warning"]


def test_conflicting_finalized_observation_stops_before_indexing(tmp_path):
    runtime, chain = _runtime(tmp_path, [104, 104], finality=103)
    runtime.sync_chain_once(max_blocks=1)
    chain.headers[103] = _header(103, "conflict-103", "old-102")
    with pytest.raises(RuntimeError, match="Conflicting finalized anchor"):
        runtime.sync_chain_once()
    assert runtime._load_sync_state_row()["last_live_processed"] == 100


def test_expiry_advances_with_empty_live_blocks_during_finality_stall(tmp_path):
    events = _base_events()
    kicked = replace(events["kicked"], snapshot=replace(events["kicked"].snapshot, auction_length_raw="2"))
    runtime, chain = _runtime(tmp_path, [104, 104, 105])
    runtime._scan_auction_events = lambda _chain, _auctions, from_block, to_block: [
        item for item in [events["enabled"], kicked] if from_block <= item.domain_event.block_number <= to_block
    ]
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    assert runtime.writer.fetchone("SELECT status FROM rounds")[0] == "live"
    assert runtime.sync_chain_once() == 0
    assert runtime.writer.fetchone("SELECT status FROM rounds")[0] == "expired"
    assert runtime._load_sync_state_row()["last_confirmed_processed"] == 101
    assert runtime._load_sync_state_row()["last_live_processed"] == 105


def test_live_indexing_requires_explicit_backfill_for_unverified_database(tmp_path):
    runtime, chain = _runtime(tmp_path, [104, 104, 104], finality=102)
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    runtime.writer.transaction(lambda conn: (
        conn.execute("UPDATE sync_state SET finality_mode = NULL, last_confirmed_hash = NULL"),
        conn.execute("UPDATE chain_logs SET block_hash = ? WHERE block_number = 101", ("0x" + "ee" * 32,)),
    ))
    from backend.indexer.observations import MissingObservation
    before = dict(runtime._load_sync_state_row())
    with pytest.raises(MissingObservation, match="--backfill-observations"):
        runtime.sync_chain_once()
    assert dict(runtime._load_sync_state_row()) == before
