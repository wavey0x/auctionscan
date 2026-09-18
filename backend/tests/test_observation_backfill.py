from .helpers import make_hydrator

import pytest
from web3 import Web3

from backend.indexer.observations import BranchChanged, MissingObservation
from backend.indexer.takes import TakeDetector
from backend.indexer.types import TokenMetadata
from .helpers import DEFAULT_WANT_TOKEN, make_snapshot
from .test_observations import _Provider
from .test_reorg_runtime import _base_events, _base_headers, _build_runtime


def _incomplete_runtime(tmp_path, *, monkeypatch):
    events = _base_events()
    runtime, chain = _build_runtime(
        tmp_path,
        latest_heads=[104, 104, 104],
        headers=_base_headers(),
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        monkeypatch=monkeypatch,
    )
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    runtime.writer.transaction(lambda conn: (
        conn.execute("DELETE FROM indexed_blocks"),
        conn.execute("DELETE FROM auction_snapshot_facts"),
        conn.execute("DELETE FROM round_param_snapshot"),
        conn.execute("UPDATE sync_state SET health = 'error', last_error = 'existing error'"),
    ))
    provider = _Provider()
    chain.w3 = Web3(provider)
    chain.w3.middleware_onion.clear()

    def read_value(address, number):
        fn = chain.w3.eth.contract(address=Web3.to_checksum_address(address), abi=[{
            "type": "function", "name": "decimals", "inputs": [],
            "outputs": [{"type": "uint8"}], "stateMutability": "view",
        }]).functions.decimals()
        return chain.reader.call(fn, number)

    def snapshot(_chain, version, address, number, **kwargs):
        read_value(address, number)
        return make_snapshot(auction_address=address, block_number=number)

    runtime.hydrator = make_hydrator(
        read_auction_snapshot=snapshot,
        read_token_metadata=lambda _chain, token, block_number: TokenMetadata(
            chain_id=1,
            token_address=token,
            symbol=None,
            name=None,
            decimals=read_value(token, block_number),
        ),
    )
    runtime.take_detector = TakeDetector(runtime.abi_registry, runtime.hydrator)
    return runtime, chain, provider


def test_backfill_resumes_from_facts_then_both_replays_are_offline(tmp_path, *, monkeypatch):
    runtime, chain, provider = _incomplete_runtime(tmp_path, monkeypatch=monkeypatch)
    coverage = runtime.backfill_observations(check_only=True)
    assert coverage["blocks"] == coverage["missing"] == 4
    assert provider.calls == []
    partial = runtime.backfill_observations(max_blocks=1)
    assert partial["captured"] == partial["complete"] == 1
    assert partial["missing"] == 3
    calls_after_first = len(provider.calls)
    result = runtime.backfill_observations()
    assert result["captured"] == 3
    assert result["missing"] == 0
    assert len(provider.calls) > calls_after_first
    assert runtime.writer.fetchone("SELECT block_hash FROM auction_snapshot_facts")[0] == chain.headers[100].block_hash
    before = dict(runtime._load_sync_state_row())
    provider.failure = AssertionError("Offline maintenance contacted RPC")
    chain.block_header = lambda _number: pytest.fail("Offline maintenance requested a header")
    assert runtime.backfill_observations(check_only=True)["missing"] == 0
    for takes_only in (False, True):
        runtime.reproject_chain(takes_only=takes_only)
        assert dict(runtime._load_sync_state_row()) == before


@pytest.mark.parametrize("takes_only", [False, True])
@pytest.mark.parametrize("missing_input, message", [
    ("metadata", "Missing call"),
    ("auction_snapshot_facts", "Missing DeployedNewAuction snapshot"),
    ("round_param_snapshot", "Missing AuctionKicked snapshot"),
])
def test_incomplete_inputs_refuse_replay_without_replacing_projections(
    tmp_path, takes_only, missing_input, message, *, monkeypatch
):
    runtime, chain, provider = _incomplete_runtime(tmp_path, monkeypatch=monkeypatch)
    runtime.backfill_observations()
    if missing_input == "metadata":
        runtime.writer.transaction(lambda conn: conn.execute(
            "DELETE FROM rpc_observations WHERE block_number = 101 AND subject LIKE ?", (DEFAULT_WANT_TOKEN + ':%',),
        ))
    else:
        runtime.writer.transaction(lambda conn: conn.execute(f"DELETE FROM {missing_input}"))
    before = list(runtime.writer.fetchall("SELECT * FROM rounds"))
    provider.failure = AssertionError("Replay must not repair its inputs through RPC")
    with pytest.raises(MissingObservation, match=message):
        runtime.reproject_chain(takes_only=takes_only)
    assert list(runtime.writer.fetchall("SELECT * FROM rounds")) == before


def test_branch_mismatch_during_backfill_refuses_adoption(tmp_path, *, monkeypatch):
    runtime, chain, provider = _incomplete_runtime(tmp_path, monkeypatch=monkeypatch)
    runtime.backfill_observations(max_blocks=1)
    runtime.writer.transaction(lambda conn: conn.execute(
        "UPDATE chain_logs SET block_hash = ? WHERE block_number = 102", ('0x' + 'ee' * 32,),
    ))
    before = dict(runtime._load_sync_state_row())
    with pytest.raises(BranchChanged):
        runtime.backfill_observations()
    assert dict(runtime._load_sync_state_row()) == before
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM rounds")[0] == 1


@pytest.mark.parametrize("check_only", [False, True])
@pytest.mark.parametrize("invalid", ["finality", "auction_snapshot_facts", "round_param_snapshot"])
def test_backfill_refuses_unprepared_data_without_mutation(tmp_path, monkeypatch, check_only, invalid):
    runtime, chain, provider = _incomplete_runtime(tmp_path, monkeypatch=monkeypatch)
    runtime.backfill_observations()
    if invalid == "finality":
        runtime.writer.transaction(lambda conn: conn.execute("UPDATE sync_state SET finality_mode = NULL"))
    else:
        runtime.writer.transaction(lambda conn: conn.execute(f"UPDATE {invalid} SET block_hash = NULL"))
    before = list(runtime.writer.connection.iterdump())
    calls = len(provider.calls)
    with pytest.raises(MissingObservation, match="previous application revision"):
        runtime.backfill_observations(check_only=check_only)
    assert list(runtime.writer.connection.iterdump()) == before
    assert len(provider.calls) == calls


def test_backfill_missing_calls_preserves_existing_snapshots(tmp_path, monkeypatch):
    runtime, chain, provider = _incomplete_runtime(tmp_path, monkeypatch=monkeypatch)
    runtime.backfill_observations()
    snapshots = {table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")]
                 for table in ("auction_snapshot_facts", "round_param_snapshot")}
    runtime.writer.transaction(lambda conn: conn.execute("DELETE FROM rpc_observations WHERE block_number = 100"))
    assert runtime.backfill_observations()["missing"] == 0
    assert {table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")]
            for table in snapshots} == snapshots


def test_backfill_transport_failure_does_not_mark_partial_block_complete(tmp_path, *, monkeypatch):
    runtime, chain, provider = _incomplete_runtime(tmp_path, monkeypatch=monkeypatch)
    runtime.backfill_observations(max_blocks=1)
    provider.failure = TimeoutError("Node offline")
    with pytest.raises(TimeoutError):
        runtime.backfill_observations()
    assert runtime.backfill_observations(check_only=True)["complete"] == 1


def test_full_reproject_repairs_legacy_sweep_on_a_backup_offline(tmp_path, monkeypatch):
    import sqlite3
    from dataclasses import replace
    from backend.indexer.facts import upsert_indexed_blocks
    from backend.indexer.projections import apply_batch
    from backend.indexer.writer import Writer
    from .helpers import DEFAULT_FROM_TOKEN, make_prepared

    runtime, chain, provider = _incomplete_runtime(tmp_path, monkeypatch=monkeypatch)
    original = runtime.hydrator.read_auction_snapshot
    runtime.hydrator.read_auction_snapshot = lambda *args, **kwargs: replace(
        original(*args, **kwargs), auction_length_raw="1"
    )
    runtime.backfill_observations()
    sweep = make_prepared(
        event_name="AuctionSwept", tx_nonce=77, block_number=105, payload={"token": DEFAULT_FROM_TOKEN}
    )
    runtime.writer.transaction(
        lambda conn: (
            upsert_indexed_blocks(conn, [chain.headers[105]]),
            apply_batch(conn, [sweep]),
            # Reproduce the projection left by the old incremental sweep guard.
            conn.execute("UPDATE rounds SET status = 'expired', settled_at = NULL"),
            conn.execute("UPDATE sync_state SET last_live_processed = 105"),
        )
    )
    original_writer = runtime.writer
    backup = tmp_path / "repair.sqlite3"
    with sqlite3.connect(backup) as destination:
        original_writer.connection.backup(destination)
    runtime.writer = Writer(str(backup))
    tables = (
        "chain_logs",
        "domain_events",
        "rpc_observations",
        "indexed_blocks",
        "auction_snapshot_facts",
        "round_param_snapshot",
    )
    before = {
        table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")] for table in tables
    }
    provider.failure = AssertionError("Repair attempted live RPC")
    chain.block_header = lambda _number: pytest.fail("Repair requested a live header")
    assert runtime.backfill_observations(check_only=True)["missing"] == 0
    runtime.reproject_chain()
    assert tuple(runtime.writer.fetchone("SELECT status, settled_at, end_at FROM rounds")) == (
        "settled",
        1700000105,
        1700000103,
    )
    assert {
        table: [tuple(row) for row in runtime.writer.fetchall(f"SELECT * FROM {table}")] for table in tables
    } == before
    assert tuple(original_writer.fetchone("SELECT status, settled_at FROM rounds")) == ("expired", None)
