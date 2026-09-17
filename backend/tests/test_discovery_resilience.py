import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.routes.health import discovery_status
from backend.indexer.discovery import FactoryDiscoverer
from backend.indexer.types import RegistryConfig
from .test_discovery_refresh import _FakeAbiRegistry, _FakeRegistryContract, _FakeWeb3, DISCOVERED_FACTORY
from .test_runtime import _build_runtime, _factory_seed


def prepare(runtime, chain, *, configured, registry):
    chain.config = replace(chain.config, factories=tuple(configured), registry=RegistryConfig(address='0x0000000000000000000000000000000000000abc', start_block=100))
    chain.w3 = _FakeWeb3()
    runtime.chain_config = chain.config
    runtime.discovery_chain = chain
    runtime.discoverer = FactoryDiscoverer(_FakeAbiRegistry(registry))
    runtime._scan_factory_events = lambda *args: []
    runtime._scan_auction_events = lambda *args: []


def test_registry_outage_after_restart_keeps_factories_indexing_and_old_findings(tmp_path, monkeypatch):
    clock = [1000]
    monkeypatch.setattr('backend.indexer.runtime.time.time', lambda: clock[0])
    runtime, chain = _build_runtime(tmp_path, latest_heads=[100])
    prepare(runtime, chain, configured=[_factory_seed(100)], registry=_FakeRegistryContract(
        [DISCOVERED_FACTORY], {DISCOVERED_FACTORY: ('9.9.9', 'ignored', False)}))
    runtime.sync_once()
    assert runtime._load_sync_state_row()['last_live_processed'] == 100
    before = json.loads(runtime._load_sync_state_row()['discovery_status_json'])
    assert before['problems'][0]['code'] == 'unsupported_version'
    runtime.writer.connection.close()

    clock[0] = 1301
    restarted, new_chain = _build_runtime(tmp_path, latest_heads=[101])
    prepare(restarted, new_chain, configured=[], registry=_FakeRegistryContract(RuntimeError('offline'), {}))
    restarted.sync_once()
    row = restarted._load_sync_state_row()
    after = json.loads(row['discovery_status_json'])
    assert row['last_live_processed'] == 101
    assert after['known_factory_count'] == 1
    assert after['last_attempt_at'] == 1301
    assert after['last_success_at'] == 1000
    assert after['problems'] == before['problems']
    assert after['last_error'] == 'Registry lookup failed'
    assert discovery_status(row, now=1301).status == 'partial'
    payload = TestClient(create_app(db_path=str(tmp_path / 'auctionscan.sqlite3'))).get('/api/health').json()
    status = next(item for item in payload['chains'] if item['chain_id'] == 1)['discovery']
    assert status['status'] == 'partial'
    assert status['problems'][0]['version'] == '9.9.9'


def test_first_startup_without_discovery_does_not_advance_or_busy_loop(tmp_path, monkeypatch):
    runtime, chain = _build_runtime(tmp_path, latest_heads=[105, 106])
    prepare(runtime, chain, configured=[], registry=_FakeRegistryContract(RuntimeError('offline'), {}))
    runtime.sync_once()
    row = runtime._load_sync_state_row()
    assert row['last_live_processed'] == 99
    assert row['last_success_at'] is None
    assert discovery_status(row, now=1000).status == 'unavailable'
    runtime.discoverer.refresh_factories = lambda *args, **kwargs: pytest.fail('retried before refresh cadence')
    monkeypatch.setattr('backend.indexer.runtime.time.sleep', lambda _: (_ for _ in ()).throw(SystemExit))
    with pytest.raises(SystemExit):
        runtime.watch()
    assert runtime._load_sync_state_row()['last_live_processed'] == 99


@pytest.mark.parametrize('failure, expected', [('lookup', 'lookup_failed'), ('deployment', 'deployment_unresolved')])
def test_factory_failures_are_structured_and_preserve_configured_indexing(tmp_path, failure, expected):
    runtime, chain = _build_runtime(tmp_path, latest_heads=[100])
    info = RuntimeError('offline') if failure == 'lookup' else ('1.0.4', 'ignored', False)
    prepare(runtime, chain, configured=[_factory_seed(100)], registry=_FakeRegistryContract([DISCOVERED_FACTORY], {DISCOVERED_FACTORY: info}))
    runtime.discoverer.resolve_contract_deploy_block = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('offline'))
    runtime.sync_once()
    row = runtime._load_sync_state_row()
    status = discovery_status(row, now=1000)
    assert row['last_live_processed'] == 100
    assert status.status == 'partial'
    assert status.problems[0].code == expected
    assert status.last_success_at is None


def test_healthy_discovery_ages_without_changing_indexing_health():
    saved = {'known_factory_count': 1, 'last_success_at': 1000, 'last_attempt_at': 1000, 'last_error': None, 'problems': []}
    row = {'discovery_status_json': json.dumps(saved)}
    assert discovery_status(row, now=1001).status == 'ok'
    assert discovery_status(row, now=1601).status == 'stale'
