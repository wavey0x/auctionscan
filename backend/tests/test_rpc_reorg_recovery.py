from web3 import Web3
from web3.providers.base import BaseProvider
import pytest

from backend.indexer.chains import ChainState
from .test_reorg_runtime import _base_events, _base_headers, _build_runtime, _header


@pytest.mark.parametrize("replacement_head", [103, 104])
def test_rpc_recovery_handles_a_changed_or_missing_tip(tmp_path, replacement_head):
    events = _base_events()
    runtime, mutable = _build_runtime(
        tmp_path, latest_heads=[104, 104, replacement_head], headers=_base_headers(),
        factory_events_by_block={100: [events["deployment"]]},
        auction_events_by_block={101: [events["enabled"]], 102: [events["kicked"]]},
        take_events_by_block={104: [events["take_old"]]},
    )
    requested_blocks = []

    class Provider(BaseProvider):
        def make_request(self, method, params):
            assert not runtime.writer.connection.in_transaction
            if method == "eth_blockNumber":
                result = hex(mutable.latest_head())
            elif method == "eth_getBlockByNumber":
                number = 102 if params[0] == "finalized" else int(params[0], 16)
                requested_blocks.append(number)
                header = mutable.headers.get(number)
                result = None if header is None else {
                    "number": hex(number), "hash": header.block_hash,
                    "parentHash": header.parent_hash, "timestamp": hex(header.timestamp),
                }
            else:
                raise AssertionError(f"Unexpected RPC method: {method}")
            return {"jsonrpc": "2.0", "id": 1, "result": result}

    runtime.chain = ChainState(mutable.config, Web3(Provider()))
    runtime.sync_once()
    runtime.sync_once()
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM takes")[0] == 1

    if replacement_head == 103:
        del mutable.headers[104]
    else:
        mutable.headers[104] = _header(104, "replacement-104", "old-103")
    requested_blocks.clear()
    runtime.take_detector.scan_window = lambda *_args, **_kwargs: ([], [])
    runtime.sync_once()

    state = runtime._load_sync_state_row()
    assert state["last_live_processed"] == replacement_head
    assert state["reorg_count"] == 1
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM takes")[0] == 0
    assert runtime.writer.fetchone("SELECT COUNT(*) FROM taker_summary")[0] == 0
    assert max(requested_blocks) <= replacement_head
    assert runtime.writer.fetchone(
        "SELECT block_hash FROM indexed_blocks WHERE block_number = ?", (replacement_head,),
    )[0] == mutable.headers[replacement_head].block_hash
