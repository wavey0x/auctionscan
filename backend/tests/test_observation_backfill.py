from types import SimpleNamespace

import pytest
from web3 import Web3

from backend.indexer.observations import MissingObservation
from backend.indexer.takes import TakeDetector
from backend.indexer.types import TokenMetadata
from .helpers import DEFAULT_WANT_TOKEN, make_snapshot
from .test_observations import _Provider
from .test_reorg_runtime import _base_events, _base_headers, _build_runtime


def _legacy_runtime(tmp_path):
    events = _base_events()
    runtime, chain = _build_runtime(
        tmp_path, latest_heads=[104, 104, 104], headers=_base_headers(),
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
    )
    runtime.sync_chain_once()
    runtime.sync_chain_once()
    runtime.writer.transaction(lambda conn: (
        conn.execute("DELETE FROM indexed_blocks"),
        conn.execute("UPDATE auction_snapshot_facts SET block_hash = NULL"),
        conn.execute("UPDATE round_param_snapshot SET block_hash = NULL"),
        conn.execute("UPDATE sync_state SET finality_mode = NULL, last_confirmed_hash = NULL, health = 'error', last_error = 'existing error'"),
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

    runtime.hydrator = SimpleNamespace(
        read_auction_snapshot=snapshot,
        read_token_metadata=lambda _chain, token, block_number: TokenMetadata(
            chain_id=1, token_address=token, symbol=None, name=None,
            decimals=read_value(token, block_number),
        ),
    )
    runtime.take_detector = TakeDetector(runtime.abi_registry, runtime.hydrator)
    return runtime, chain, provider


def test_backfill_resumes_from_facts_then_both_replays_are_offline(tmp_path):
    runtime, chain, provider = _legacy_runtime(tmp_path)
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
def test_incomplete_inputs_refuse_replay_without_replacing_projections(tmp_path, takes_only, missing_input, message):
    runtime, chain, provider = _legacy_runtime(tmp_path)
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


def test_legacy_orphan_during_backfill_adopts_only_the_completed_prefix(tmp_path):
    runtime, chain, provider = _legacy_runtime(tmp_path)
    runtime.writer.transaction(lambda conn: (
        conn.execute("UPDATE chain_logs SET block_hash = ? WHERE block_number = 102", ('0x' + 'ee' * 32,)),
        conn.execute("UPDATE domain_events SET block_hash = ? WHERE block_number = 102", ('0x' + 'ee' * 32,)),
    ))
    chain.finality_mode = "finalized"
    result = runtime.backfill_observations()
    assert result["missing"] == 0
    assert result["resume_indexing"] is True
    state = runtime._load_sync_state_row()
    assert state["last_live_processed"] == 101
    assert state["last_confirmed_hash"] == chain.headers[101].block_hash
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM rounds")[0] == 0
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM rpc_observations WHERE block_number > 101")[0] == 0


def test_backfill_transport_failure_does_not_mark_partial_block_complete(tmp_path):
    runtime, chain, provider = _legacy_runtime(tmp_path)
    runtime.backfill_observations(max_blocks=1)
    provider.failure = TimeoutError("Node offline")
    with pytest.raises(TimeoutError):
        runtime.backfill_observations()
    assert runtime.backfill_observations(check_only=True)["complete"] == 1
