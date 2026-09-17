from backend.indexer.discovery import DiscoveryResult
from dataclasses import replace

import pytest

from .test_reorg_runtime import _base_events, _base_headers, _build_runtime, _factory_seed


def test_new_factory_rewind_leaves_a_consistent_prefix_when_rescan_fails(tmp_path):
    events = _base_events()
    runtime, chain = _build_runtime(
        tmp_path, latest_heads=[104] * 5, headers=_base_headers(),
        factory_events_by_block={100: [events['deployment']]},
        auction_events_by_block={101: [events['enabled']], 102: [events['kicked']]},
        take_events_by_block={104: [events['take_old']]},
    )
    runtime.sync_once()
    runtime.sync_once()
    assert runtime.writer.fetchone('SELECT COUNT(*) FROM takes')[0] == 1
    runtime._factory_seeds = None
    added = replace(_factory_seed(103), address='0x0000000000000000000000000000000000000fab')
    runtime.discoverer.refresh_factories = lambda *args, **kwargs: DiscoveryResult([_factory_seed(), added], [])
    original = runtime._scan_factory_events

    def fail(*args):
        raise RuntimeError('RPC unavailable after factory discovery')

    runtime._scan_factory_events = fail
    with pytest.raises(RuntimeError, match='RPC unavailable'):
        runtime.sync_once()
    state = runtime._load_sync_state_row()
    assert state['last_live_processed'] == state['last_confirmed_processed'] == 102
    assert state['last_confirmed_hash'] == chain.headers[102].block_hash
    assert state['reorg_count'] == 0
    assert runtime.writer.fetchone('SELECT MAX(block_number) FROM chain_logs')[0] == 102
    assert runtime.writer.fetchone('SELECT COUNT(*) FROM takes')[0] == 0
    assert runtime.writer.fetchone('SELECT COUNT(*) FROM taker_summary')[0] == 0
    assert runtime.writer.fetchone('SELECT COUNT(*) FROM tracked_factories')[0] == 2
    runtime._scan_factory_events = original
    runtime.sync_once()
    assert runtime._load_sync_state_row()['last_live_processed'] == 104
    assert runtime.writer.fetchone('SELECT COUNT(*) FROM takes')[0] == 1
