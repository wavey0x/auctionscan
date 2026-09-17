from dataclasses import replace

from backend.indexer import pricing as pricing_module
from backend.indexer.pricing import PricingCaptureRuntime, enqueue_pricing_work
from backend.indexer.projections import apply_batch_with_results
from .test_pricing import _FakePricingClient, _extra_take, _seed_pricing_db


def test_expired_backlog_cannot_delay_a_fresh_quote(tmp_path, monkeypatch):
    now = 1_700_001_000
    monkeypatch.setattr(pricing_module, '_now', lambda: now)
    writer, _ = _seed_pricing_db(tmp_path / 'pricing.sqlite3')
    assert writer.fetchone('SELECT COUNT(*) FROM pricing_capture_queue')[0] == 4
    take = _extra_take(tx_nonce=84, block_number=104)
    take = replace(take, raw_log=replace(take.raw_log, timestamp=now),
                   domain_event=replace(take.domain_event, timestamp=now))
    writer.transaction(lambda conn: enqueue_pricing_work(conn, apply_batch_with_results(conn, [take])))
    runtime = PricingCaptureRuntime(client=_FakePricingClient())
    try:
        runtime.poll(writer, chain_id=1)
        attempt = runtime._outstanding.result(timeout=3)
        assert attempt.job.source_tx_hash == take.raw_log.tx_hash
        assert attempt.fact_kind == 'quote'
        assert writer.fetchone('SELECT COUNT(*) FROM pricing_capture_queue')[0] == 2
        assert writer.fetchone('SELECT MIN(event_timestamp) FROM pricing_capture_queue')[0] == now
    finally:
        runtime.discard()
