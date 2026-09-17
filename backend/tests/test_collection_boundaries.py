from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.indexer.chains import ChainState
from backend.indexer.observations import BlockReader, BranchChanged
from backend.indexer.polling import fetch_logs
from backend.indexer.projections import apply_batch
from backend.indexer.facts import persist_raw_logs
from backend.indexer.takes import SWEEP_SELECTOR, TRANSFER_TOPIC, TakeDetector
from backend.indexer.writer import Writer
from .helpers import DEFAULT_AUCTION, DEFAULT_FROM_TOKEN, DEFAULT_RECEIVER, DEFAULT_WANT_TOKEN
from .test_reorg_runtime import _base_events, _base_headers, _build_runtime, _header
from .test_replay_and_takes import (
    TAKER, _FakeAbiRegistry, _FakeTakeHydrator, _FakeTakeWeb3,
    _base_native_batch, _rpc_transfer_log,
)


def test_empty_hash_bound_scan_rechecks_canonical_tip_before_committing(tmp_path):
    events = _base_events()
    runtime, mutable = _build_runtime(
        tmp_path, latest_heads=[104, 104], headers=_base_headers(),
        factory_events_by_block={100: [events['deployment']]},
        auction_events_by_block={101: [events['enabled']], 102: [events['kicked']]},
    )
    runtime.sync_once()
    before = {table: [tuple(row) for row in runtime.writer.fetchall(f'SELECT * FROM {table}')]
              for table in ('chain_logs', 'domain_events', 'rounds', 'indexed_blocks', 'sync_state')}
    requests = []

    class Eth:
        @property
        def block_number(self):
            return mutable.latest_head()

        def get_block(self, number):
            assert not runtime.writer.connection.in_transaction
            header = mutable.block_header(102 if number == 'finalized' else number)
            return {'number': header.block_number, 'hash': header.block_hash,
                    'parentHash': header.parent_hash, 'timestamp': header.timestamp}

        def get_logs(self, params):
            assert not runtime.writer.connection.in_transaction
            requests.append(params)
            if params['blockHash'] == mutable.headers[104].block_hash:
                mutable.headers[104] = _header(104, 'replacement-104', 'old-103')
            return []

    runtime.chain = ChainState(mutable.config, SimpleNamespace(eth=Eth()))
    runtime._scan_auction_events = lambda chain, _auctions, start, end: fetch_logs(
        chain.w3, from_block=start, to_block=end, block_hashes=chain.reader.log_hashes,
    )
    with pytest.raises(BranchChanged, match='Canonical branch changed during collection'):
        runtime.sync_once()
    assert requests == [{'blockHash': _base_headers()[number].block_hash} for number in (103, 104)]
    assert before == {table: [tuple(row) for row in runtime.writer.fetchall(f'SELECT * FROM {table}')]
                      for table in before}


def test_new_auction_first_take_is_prepared_before_any_batch_writes(tmp_path):
    writer = Writer(str(tmp_path / 'new-auction.sqlite3'))
    header = _header(103, 'old-103', 'old-102')
    native = [replace(p,
        raw_log=replace(p.raw_log, block_number=103, block_hash=header.block_hash, log_index=index),
        domain_event=replace(p.domain_event, block_number=103, block_hash=header.block_hash, log_index=index),
        snapshot=replace(p.snapshot, block_number=103) if p.snapshot else None,
    ) for index, p in enumerate(_base_native_batch())]
    receipt_logs = [{'address': DEFAULT_WANT_TOKEN, 'topics': [TRANSFER_TOPIC,
        '0x' + TAKER[2:].rjust(64, '0'), '0x' + DEFAULT_RECEIVER[2:].rjust(64, '0')],
        'data': hex(150_000_000), 'logIndex': 7}]
    w3 = _FakeTakeWeb3(receipt_logs)
    w3.eth.block_hash = header.block_hash
    logs = [dict(_rpc_transfer_log(from_token=DEFAULT_FROM_TOKEN, auction_address=DEFAULT_AUCTION,
                 tx_nonce=nonce, block_number=103, log_index=index), data=hex(200))
            for nonce, index in ((50, 4), (51, 9))]

    def get_logs(params):
        assert not writer.connection.in_transaction
        assert params['blockHash'] == header.block_hash
        return logs

    original_transaction = w3.eth.get_transaction
    def transaction(tx_hash):
        assert not writer.connection.in_transaction
        value = original_transaction(tx_hash)
        if tx_hash == f'0x{51:064x}':
            value['input'] = SWEEP_SELECTOR
        return value

    w3.eth.get_logs = get_logs
    w3.eth.get_transaction = transaction
    config = SimpleNamespace(chain_id=1, name='ethereum')
    chain = ChainState(config, w3)
    chain.reader = BlockReader(writer.connection, chain_id=1, w3=w3, header_reader=None, headers=[header])
    chain.reader.log_hashes = {103: header.block_hash}
    detector = TakeDetector(_FakeAbiRegistry(), _FakeTakeHydrator())
    raw, takes = detector.scan_window(chain, writer.connection, from_block=103, to_block=103, native_events=native)
    assert writer.fetchone('SELECT COUNT(*) FROM auctions')[0] == 0
    assert len(raw) == 2 and len(takes) == 1
    assert takes[0].domain_event.payload['roundId'] == 1
    writer.transaction(lambda conn: (
        chain.reader.persist(conn), apply_batch(conn, native), persist_raw_logs(conn, raw), apply_batch(conn, takes),
    ))
    assert writer.fetchone('SELECT COUNT(*) FROM takes')[0] == 1
    rejected_inputs = {row['kind'] for row in writer.fetchall(
        'SELECT kind FROM rpc_observations WHERE subject = ?', (f'0x{51:064x}',))}
    assert rejected_inputs == {'receipt', 'transaction'}
