from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api import db as api_db
from backend.api import queries as api_queries
from backend.indexer import pricing as pricing_module
from backend.indexer.pricing import PricingApiClient, PricingCaptureRuntime, ProviderCapability, enqueue_pricing_work, rebuild_pricing_projections
from backend.indexer.projections import apply_batch, apply_batch_with_results, apply_native_event_projections, clear_projection_state, clear_take_state
from backend.indexer.writer import Writer
from backend.indexer.types import TokenMetadata

from .helpers import capture_due_pricing, DEFAULT_AUCTION, DEFAULT_FACTORY, DEFAULT_FROM_TOKEN, DEFAULT_RECEIVER, DEFAULT_WANT_TOKEN, make_prepared, make_snapshot


ONE_ETHER = 10**18
ONE_USDC = 10**6
TAKER = "0x0000000000000000000000000000000000000abc"


def _extra_take(*, tx_nonce: int, block_number: int, amount_taken: int = 50 * ONE_ETHER):
    return make_prepared(
        event_name="Take",
        tx_nonce=tx_nonce,
        block_number=block_number,
        log_index=tx_nonce,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": amount_taken,
            "amountPaid": 40 * ONE_USDC,
            "expectedAmountPaid": 40 * ONE_USDC,
            "priceE18": 800_000_000_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )


def _rows_snapshot(writer: Writer, table: str, order_by: str) -> list[tuple]:
    return [tuple(row) for row in writer.fetchall(f"SELECT * FROM {table} ORDER BY {order_by}")]


def test_pricing_api_client_refreshes_provider_cache_after_ttl(monkeypatch):
    current_time = [1000.0]
    responses = iter(
        [
            {
                "providers": [
                    {
                        "id": "curve",
                        "supports_price": True,
                        "supports_quote": True,
                        "supported_chains": [1],
                    },
                    {
                        "id": "odos",
                        "supports_price": True,
                        "supports_quote": True,
                        "supported_chains": [1],
                    },
                ]
            },
            {
                "providers": [
                    {
                        "id": "curve",
                        "supports_price": True,
                        "supports_quote": True,
                        "supported_chains": [1],
                    }
                ]
            },
        ]
    )
    request_paths: list[str] = []

    def request_json(path: str) -> dict:
        request_paths.append(path)
        return next(responses)

    monkeypatch.setattr(pricing_module.time, "monotonic", lambda: current_time[0])
    client = PricingApiClient(base_url="https://prices.example", api_key="")
    monkeypatch.setattr(client, "_request_json", request_json)

    assert [item.id for item in client.supported_providers(chain_id=1, kind="quote")] == ["curve", "odos"]

    current_time[0] += pricing_module.DEFAULT_PROVIDER_CACHE_TTL_SECONDS - 1
    assert [item.id for item in client.supported_providers(chain_id=1, kind="quote")] == ["curve", "odos"]
    assert request_paths == ["/v1/providers"]

    current_time[0] += 1
    assert [item.id for item in client.supported_providers(chain_id=1, kind="quote")] == ["curve"]
    assert request_paths == ["/v1/providers", "/v1/providers"]


class _FakePricingClient:
    def __init__(self) -> None:
        self._providers = [
            ProviderCapability(
                id="curve",
                supports_price=True,
                supports_quote=True,
                supported_chains=(1,),
                requires_api_key=False,
                available=True,
                unavailable_reason=None,
            ),
            ProviderCapability(
                id="odos",
                supports_price=True,
                supports_quote=True,
                supported_chains=(1,),
                requires_api_key=False,
                available=True,
                unavailable_reason=None,
            ),
            ProviderCapability(
                id="enso",
                supports_price=True,
                supports_quote=True,
                supported_chains=(1,),
                requires_api_key=False,
                available=True,
                unavailable_reason=None,
            ),
        ]

    def supported_providers(self, *, chain_id: int, kind: str) -> list[ProviderCapability]:
        return [
            item
            for item in self._providers
            if chain_id in item.supported_chains and (item.supports_quote if kind == "quote" else item.supports_price)
        ]

    def fetch_quote(
        self,
        *,
        chain_id: int,
        token_in: str,
        token_out: str,
        amount_in: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict:
        amount_in_int = int(amount_in)
        if amount_in_int == 500 * ONE_ETHER:
            amounts = {
                "curve": 320 * ONE_USDC,
                "odos": 330 * ONE_USDC,
                "enso": 340 * ONE_USDC,
            }
        else:
            amounts = {
                "curve": 130 * ONE_USDC,
                "odos": 140 * ONE_USDC,
                "enso": 150 * ONE_USDC,
            }
        return {
            "request_id": f"quote-{amount_in}",
            "chain_id": chain_id,
            "token_in": {"chain_id": chain_id, "address": token_in, "symbol": "FROM", "decimals": 18},
            "token_out": {"chain_id": chain_id, "address": token_out, "symbol": "WANT", "decimals": 6},
            "provider_order": providers,
            "quote": {
                "provider": "odos",
                "amount_in": amount_in_int,
                "amount_out": amounts["odos"],
                "latency_ms": 42,
                "retrieved_at": "2026-04-08T12:00:00Z",
                "vault_context": None,
            },
            "providers": {
                provider_id: {
                    "status": "ok",
                    "success": True,
                    "amount_in": amount_in_int,
                    "amount_out": amounts[provider_id],
                    "amount_out_min": amounts[provider_id] - (1 * ONE_USDC),
                    "price_impact_bps": 12,
                    "estimated_gas": 123_456,
                    "latency_ms": 30 + index,
                    "as_of": "2026-04-08T12:00:00Z",
                    "retrieved_at": "2026-04-08T12:00:00Z",
                    "error": None,
                    "route": {"provider": provider_id},
                }
                for index, provider_id in enumerate(providers)
            },
            "summary": {
                "requested_providers": len(providers),
                "successful_providers": len(providers),
                "failed_providers": 0,
                "high_amount_out": max(amounts.values()),
                "low_amount_out": min(amounts.values()),
                "median_amount_out": sorted(amounts.values())[1],
            },
        }

    def fetch_price(
        self,
        *,
        chain_id: int,
        token: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict:
        prices = {
            "curve": "0.99",
            "odos": "1.00",
            "enso": "1.01",
        }
        return {
            "request_id": f"price-{token}",
            "chain_id": chain_id,
            "token": {"chain_id": chain_id, "address": token, "symbol": "WANT", "decimals": 6},
            "provider_order": providers,
            "price_data": {
                "provider": "odos",
                "price": prices["odos"],
                "latency_ms": 18,
                "retrieved_at": "2026-04-08T12:00:00Z",
                "vault_context": None,
            },
            "providers": {
                provider_id: {
                    "status": "ok",
                    "success": True,
                    "price": prices[provider_id],
                    "latency_ms": 10 + index,
                    "as_of": "2026-04-08T12:00:00Z",
                    "retrieved_at": "2026-04-08T12:00:00Z",
                    "error": None,
                }
                for index, provider_id in enumerate(providers)
            },
            "summary": {
                "requested_providers": len(providers),
                "successful_providers": len(providers),
                "failed_providers": 0,
                "high_price": "1.01",
                "low_price": "0.99",
                "median_price": "1.00",
                "deviation_bps": 100,
            },
        }


class _FlakyQuotePricingClient(_FakePricingClient):
    def __init__(self, *, quote_failures: dict[int, int]) -> None:
        super().__init__()
        self._quote_failures = dict(quote_failures)

    def fetch_quote(
        self,
        *,
        chain_id: int,
        token_in: str,
        token_out: str,
        amount_in: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict:
        amount_in_int = int(amount_in)
        remaining = self._quote_failures.get(amount_in_int, 0)
        if remaining > 0:
            self._quote_failures[amount_in_int] = remaining - 1
            raise RuntimeError(f"temporary quote failure for {amount_in_int}")
        return super().fetch_quote(
            chain_id=chain_id,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            providers=providers,
            use_underlying=use_underlying,
            timeout_ms=timeout_ms,
        )


class _ProviderErrorPricingClient(_FakePricingClient):
    def fetch_quote(
        self,
        *,
        chain_id: int,
        token_in: str,
        token_out: str,
        amount_in: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict:
        payload = super().fetch_quote(
            chain_id=chain_id,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            providers=providers,
            use_underlying=use_underlying,
            timeout_ms=timeout_ms,
        )
        curve = payload["providers"]["curve"]
        curve.update(
            {
                "status": "error",
                "success": False,
                "amount_out": None,
                "amount_out_min": None,
                "error": {
                    "type": "UPSTREAM_HTTP",
                    "code": 500,
                    "message": "Curve returned 500",
                },
            }
        )
        return payload

    def fetch_price(
        self,
        *,
        chain_id: int,
        token: str,
        providers: list[str],
        use_underlying: bool,
        timeout_ms: int,
    ) -> dict:
        payload = super().fetch_price(
            chain_id=chain_id,
            token=token,
            providers=providers,
            use_underlying=use_underlying,
            timeout_ms=timeout_ms,
        )
        curve = payload["providers"]["curve"]
        curve.update(
            {
                "status": "error",
                "success": False,
                "price": None,
                "error": {
                    "type": "RATE_LIMITED",
                    "code": 429,
                    "message": "Curve returned 429",
                    "retry_after_ms": 1000,
                },
            }
        )
        return payload


def _seed_pricing_db(
    path,
    *,
    take_payload: dict | None = None,
    extra_events: list | None = None,
) -> tuple[Writer, dict[str, object]]:
    writer = Writer(str(path))
    deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=1,
        block_number=100,
        address=DEFAULT_FACTORY,
        auction_address=DEFAULT_AUCTION,
        version="1.0.4",
        capability_family="1.0.4",
        payload={"want": DEFAULT_WANT_TOKEN},
        snapshot=make_snapshot(block_number=100),
    )
    enabled = make_prepared(
        event_name="AuctionEnabled",
        tx_nonce=2,
        block_number=101,
        payload={"from": DEFAULT_FROM_TOKEN, "to": DEFAULT_WANT_TOKEN},
    )
    kicked = make_prepared(
        event_name="AuctionKicked",
        tx_nonce=3,
        block_number=102,
        payload={"from": DEFAULT_FROM_TOKEN, "available": 500 * ONE_ETHER},
        snapshot=make_snapshot(block_number=102),
    )
    take = make_prepared(
        event_name="Take",
        tx_nonce=4,
        block_number=103,
        log_index=4,
        payload=take_payload or {
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200 * ONE_ETHER,
            "amountPaid": 150 * ONE_USDC,
            "expectedAmountPaid": 150 * ONE_USDC,
            "priceE18": 750_000_000_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )

    metadata = (
        TokenMetadata(1, DEFAULT_FROM_TOKEN, "FROM", "From Token", 18),
        TokenMetadata(1, DEFAULT_WANT_TOKEN, "WANT", "Want Token", 6),
    )
    kicked = replace(kicked, token_metadata=metadata)
    take = replace(take, token_metadata=metadata)

    def seed(conn) -> None:
        inserted = apply_batch_with_results(conn, [deployment, enabled, kicked, take, *(extra_events or [])])
        enqueue_pricing_work(conn, inserted)

    writer.transaction(seed)
    return writer, {
        "deployment": deployment,
        "enabled": enabled,
        "kicked": kicked,
        "take": take,
    }


def _seed_manual_taker_db(
    path,
    *,
    token_rows: list[tuple[object, ...]],
    take_rows: list[tuple[object, ...]],
    taker_summary_rows: list[tuple[object, ...]],
    take_pricing_rows: list[tuple[object, ...]] | None = None,
    taker_pricing_rows: list[tuple[object, ...]] | None = None,
) -> Writer:
    writer = Writer(str(path))

    def seed(conn) -> None:
        conn.executemany(
            """
            INSERT INTO tokens (
                chain_id, token_address, symbol, name, decimals, metadata_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            token_rows,
        )
        conn.executemany(
            """
            INSERT INTO takes (
                chain_id, auction_address, round_id, take_seq, tx_hash, tx_index, log_index,
                taker, receiver, from_token, want_token, amount_taken_raw, amount_paid_raw,
                expected_amount_paid_raw, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            take_rows,
        )
        conn.executemany(
            """
            INSERT INTO taker_summary (
                chain_id, taker, take_count, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            taker_summary_rows,
        )
        if take_pricing_rows:
            conn.executemany(
                """
                INSERT INTO take_pricing (
                    chain_id, auction_address, round_id, take_seq, amount_taken_raw,
                    actual_paid_raw, expected_paid_raw, market_quote_out_raw,
                    want_token_price_usd, auction_profit_raw, auction_profit_usd,
                    pricing_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                take_pricing_rows,
            )
        if taker_pricing_rows:
            conn.executemany(
                """
                INSERT INTO taker_pricing_summary (
                    chain_id, taker, priced_take_count, total_take_count, total_actual_paid_usd,
                    total_market_quote_usd, total_taker_profit_usd, avg_taker_profit_usd,
                    priced_volume_usd, total_volume_usd_for_share, priced_volume_share,
                    first_priced_take_at, last_priced_take_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                taker_pricing_rows,
            )

    writer.transaction(seed)
    return writer


def test_pricing_capture_persists_facts_and_builds_projections(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)

    processed = capture_due_pricing(pricing, writer, chain_id=1)

    assert processed == 4
    queue_rows = writer.fetchall(
        """
        SELECT entity_kind, status
          FROM pricing_capture_queue
         WHERE chain_id = 1
         ORDER BY id ASC
        """
    )
    assert queue_rows == []

    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_quote_facts")["count"] == 2
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_price_facts")["count"] == 2
    assert {
        tuple(row)
        for row in writer.fetchall(
            "SELECT timeout_ms, include_route FROM pricing_quote_facts"
        )
    } == {(7000, 1)}
    assert {
        row["timeout_ms"]
        for row in writer.fetchall("SELECT timeout_ms FROM pricing_price_facts")
    } == {7000}
    assert {
        row["capture_origin"]
        for row in writer.fetchall("SELECT DISTINCT capture_origin FROM pricing_quote_facts")
    } == {"native"}
    assert {
        row["capture_origin"]
        for row in writer.fetchall("SELECT DISTINCT capture_origin FROM pricing_price_facts")
    } == {"native"}
    quote_sources = writer.fetchall(
        """
        SELECT context_kind, source_tx_hash, source_log_index, source_event_name
          FROM pricing_quote_facts
         WHERE chain_id = 1
         ORDER BY context_kind ASC, id ASC
        """
    )
    assert [(row["context_kind"], row["source_tx_hash"], row["source_log_index"], row["source_event_name"]) for row in quote_sources] == [
        ("round_kick", events["kicked"].domain_event.tx_hash, events["kicked"].domain_event.log_index, "AuctionKicked"),
        ("take", events["take"].domain_event.tx_hash, events["take"].domain_event.log_index, "Take"),
    ]
    price_sources = writer.fetchall(
        """
        SELECT context_kind, source_tx_hash, source_log_index, source_event_name
          FROM pricing_price_facts
         WHERE chain_id = 1
         ORDER BY context_kind ASC, id ASC
        """
    )
    assert [(row["context_kind"], row["source_tx_hash"], row["source_log_index"], row["source_event_name"]) for row in price_sources] == [
        ("round_kick", events["kicked"].domain_event.tx_hash, events["kicked"].domain_event.log_index, "AuctionKicked"),
        ("take", events["take"].domain_event.tx_hash, events["take"].domain_event.log_index, "Take"),
    ]

    take_pricing = writer.fetchone(
        """
        SELECT market_quote_out_raw, want_token_price_usd, auction_profit_raw,
               auction_profit_usd, pricing_status, provider_success_count,
               quote_spread_bps, fresh_quote, fresh_want_price
          FROM take_pricing
         WHERE chain_id = 1
           AND auction_address = ?
           AND round_id = 1
           AND take_seq = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(take_pricing) == {
        "market_quote_out_raw": "140000000",
        "want_token_price_usd": "1",
        "auction_profit_raw": "10000000",
        "auction_profit_usd": "10",
        "pricing_status": "priced",
        "provider_success_count": 3,
        "quote_spread_bps": 1429,
        "fresh_quote": 1,
        "fresh_want_price": 1,
    }

    round_pricing = writer.fetchone(
        """
        SELECT kick_market_quote_out_raw, kick_market_quote_usd, total_actual_paid_raw,
               total_market_quote_out_raw, total_auction_profit_usd, priced_take_count,
               total_take_count, priced_volume_share
          FROM round_pricing
         WHERE chain_id = 1
           AND auction_address = ?
           AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(round_pricing) == {
        "kick_market_quote_out_raw": "330000000",
        "kick_market_quote_usd": "330",
        "total_actual_paid_raw": "150000000",
        "total_market_quote_out_raw": "140000000",
        "total_auction_profit_usd": "10",
        "priced_take_count": 1,
        "total_take_count": 1,
        "priced_volume_share": "1",
    }


@pytest.mark.parametrize(
    ("quote_failures", "expected_bps", "expected_profit", "priced_count"),
    [
        ({50 * ONE_ETHER: 1}, 714, "10", 1),
        ({50 * ONE_ETHER: 1, 200 * ONE_ETHER: 1}, None, None, 0),
        ({}, -3214, "-90", 2),
    ],
)
def test_round_pnl_compares_only_matching_quoted_fills(
    tmp_path, quote_failures, expected_bps, expected_profit, priced_count
):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(
        db_path, extra_events=[_extra_take(tx_nonce=5, block_number=104)]
    )
    pricing = PricingCaptureRuntime(
        client=_FlakyQuotePricingClient(quote_failures=quote_failures),
        max_capture_lag_seconds=10**9,
    )
    capture_due_pricing(pricing, writer, chain_id=1)
    fact_tables = {
        table: _rows_snapshot(writer, table, "id")
        for table in (
            "pricing_quote_facts", "pricing_quote_provider_facts",
            "pricing_price_facts", "pricing_price_provider_facts",
        )
    }

    for _ in range(2):
        writer.transaction(lambda conn: rebuild_pricing_projections(conn, chain_id=1))
        row = writer.fetchone("SELECT * FROM round_pricing")
        assert row["total_actual_paid_raw"] == str(190 * ONE_USDC)
        assert row["total_actual_paid_usd"] == "190"
        assert row["total_auction_profit_bps"] == expected_bps
        assert row["total_auction_profit_usd"] == expected_profit
        assert row["priced_take_count"] == priced_count
        assert row["total_take_count"] == 2
        assert float(row["priced_volume_share"]) == [0, 0.8, 1][priced_count]
        for table, snapshot in fact_tables.items():
            assert _rows_snapshot(writer, table, "id") == snapshot

    client = TestClient(create_app(db_path=str(db_path)))
    round_item = client.get("/api/rounds").json()["rounds"][0]
    assert round_item["total_auction_profit_bps"] == (
        expected_bps / 100 if expected_bps is not None else None
    )
    assert round_item["total_auction_profit_usd"] == expected_profit


@pytest.mark.parametrize("actual_paid", [None, "0"])
def test_round_pnl_distinguishes_unknown_payment_from_zero(tmp_path, actual_paid):
    writer, _events = _seed_pricing_db(tmp_path / "auctionscan.sqlite3")
    pricing = PricingCaptureRuntime(
        client=_FakePricingClient(), max_capture_lag_seconds=10**9
    )
    capture_due_pricing(pricing, writer, chain_id=1)

    def rebuild_with_payment(conn):
        conn.execute("UPDATE takes SET amount_paid_raw = ?", (actual_paid,))
        rebuild_pricing_projections(conn, chain_id=1)

    writer.transaction(rebuild_with_payment)
    row = writer.fetchone("SELECT * FROM round_pricing")
    assert row["total_auction_profit_bps"] == (None if actual_paid is None else -10000)
    assert row["total_auction_profit_usd"] == (None if actual_paid is None else "-140")
    assert row["total_market_quote_out_raw"] == (None if actual_paid is None else str(140 * ONE_USDC))


def test_pricing_worker_keeps_network_outside_transactions(
    tmp_path,
    monkeypatch,
    caplog,
):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(
        db_path,
        extra_events=[
            _extra_take(tx_nonce=5, block_number=104),
            _extra_take(tx_nonce=6, block_number=105),
        ],
    )
    transaction_depth = [0]
    original_transaction = writer.transaction

    def tracked_transaction(fn):
        def tracked_callback(conn):
            transaction_depth[0] += 1
            try:
                return fn(conn)
            finally:
                transaction_depth[0] -= 1

        return original_transaction(tracked_callback)

    writer.transaction = tracked_transaction

    class _TransactionCheckingClient(_FakePricingClient):
        def _assert_network_context(self):
            assert transaction_depth[0] == 0
            assert {
                row["status"]
                for row in writer.fetchall("SELECT status FROM pricing_capture_queue")
            } == {"pending"}

        def supported_providers(self, *, chain_id: int, kind: str):
            self._assert_network_context()
            return super().supported_providers(chain_id=chain_id, kind=kind)

        def fetch_quote(self, **kwargs):
            self._assert_network_context()
            return super().fetch_quote(**kwargs)

        def fetch_price(self, **kwargs):
            self._assert_network_context()
            return super().fetch_price(**kwargs)

    rebuild_calls = []
    original_rebuild = pricing_module.rebuild_pricing_projections

    def counted_rebuild(conn, *, chain_id: int, **kwargs):
        rebuild_calls.append(chain_id)
        return original_rebuild(conn, chain_id=chain_id, **kwargs)

    monkeypatch.setattr(pricing_module, "rebuild_pricing_projections", counted_rebuild)
    pricing = PricingCaptureRuntime(
        client=_TransactionCheckingClient(),
        max_capture_lag_seconds=10**9,
    )

    with caplog.at_level(logging.INFO):
        processed = capture_due_pricing(pricing, writer, chain_id=1)

    assert processed == 8
    assert rebuild_calls == [1] * 8
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_capture_queue")["count"] == 0
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_quote_facts")["count"] == 4
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_price_facts")["count"] == 4


def test_pricing_drain_rolls_back_facts_queue_and_projections_when_rebuild_fails(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    capture_due_pricing(PricingCaptureRuntime(
        client=_FakePricingClient(),
        max_capture_lag_seconds=10**9,
    ), writer, chain_id=1)
    extra_take = _extra_take(tx_nonce=7, block_number=106)

    def add_extra_take(conn):
        inserted = apply_batch_with_results(conn, [extra_take])
        assert enqueue_pricing_work(conn, inserted) == 2

    writer.transaction(add_extra_take)
    tables = {
        "pricing_capture_queue": "id",
        "pricing_quote_facts": "id",
        "pricing_quote_provider_facts": "id",
        "pricing_price_facts": "id",
        "pricing_price_provider_facts": "id",
        "take_pricing": "chain_id, auction_address, round_id, take_seq",
        "round_pricing": "chain_id, auction_address, round_id",
        "taker_pricing_summary": "chain_id, taker",
    }
    before = {
        table: _rows_snapshot(writer, table, order_by)
        for table, order_by in tables.items()
    }
    original_rebuild = pricing_module.rebuild_pricing_projections

    def failing_rebuild(conn, *, chain_id: int, **kwargs):
        original_rebuild(conn, chain_id=chain_id, **kwargs)
        raise RuntimeError("injected pricing rebuild failure")

    monkeypatch.setattr(pricing_module, "rebuild_pricing_projections", failing_rebuild)
    pricing = PricingCaptureRuntime(
        client=_FakePricingClient(),
        max_capture_lag_seconds=10**9,
    )

    with pytest.raises(RuntimeError, match="injected pricing rebuild failure"):
        capture_due_pricing(pricing, writer, chain_id=1)

    after = {
        table: _rows_snapshot(writer, table, order_by)
        for table, order_by in tables.items()
    }
    assert after == before


def test_pricing_drain_persists_unsupported_attempts_and_deletes_terminal_jobs(tmp_path):
    class _UnsupportedClient:
        def supported_providers(self, *, chain_id: int, kind: str):
            return []

        def fetch_quote(self, **_kwargs):
            raise AssertionError("unsupported quote jobs must not make a quote request")

        def fetch_price(self, **_kwargs):
            raise AssertionError("unsupported price jobs must not make a price request")

    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(
        client=_UnsupportedClient(),
        max_capture_lag_seconds=10**9,
    )

    assert capture_due_pricing(pricing, writer, chain_id=1) == 4
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_capture_queue")["count"] == 0
    assert {
        row["capture_state"]
        for row in writer.fetchall("SELECT capture_state FROM pricing_quote_facts")
    } == {"unsupported_chain"}
    assert {
        row["capture_state"]
        for row in writer.fetchall("SELECT capture_state FROM pricing_price_facts")
    } == {"unsupported_chain"}


def test_pricing_poll_deletes_stale_jobs_without_dispatch(tmp_path):
    class _UnexpectedClient(_FakePricingClient):
        def supported_providers(self, *, chain_id: int, kind: str):
            raise AssertionError("stale jobs must not discover providers")

    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(
        client=_UnexpectedClient(),
        max_capture_lag_seconds=1,
    )

    assert capture_due_pricing(pricing, writer, chain_id=1) == 0
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_capture_queue")["count"] == 0
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_quote_facts")["count"] == 0
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_price_facts")["count"] == 0


def test_pricing_drain_skips_missing_sources_and_revalidates_sources_before_commit(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)

    class _ReorgingClient(_FakePricingClient):
        def __init__(self) -> None:
            super().__init__()
            self.deleted_source = False

        def fetch_quote(self, **kwargs):
            if int(kwargs["amount_in"]) == 200 * ONE_ETHER and not self.deleted_source:
                writer.transaction(
                    lambda conn: conn.execute(
                        "DELETE FROM takes WHERE chain_id = 1 AND tx_hash = ? AND log_index = ?",
                        (f"0x{4:064x}", 4),
                    )
                )
                self.deleted_source = True
            return super().fetch_quote(**kwargs)

    pricing = PricingCaptureRuntime(
        client=_ReorgingClient(),
        max_capture_lag_seconds=10**9,
    )

    assert capture_due_pricing(pricing, writer, chain_id=1) == 4
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_capture_queue")["count"] == 0
    assert writer.fetchone(
        "SELECT COUNT(*) AS count FROM pricing_quote_facts WHERE context_kind = 'take'"
    )["count"] == 0
    assert writer.fetchone(
        "SELECT COUNT(*) AS count FROM pricing_price_facts WHERE context_kind = 'take'"
    )["count"] == 0
    assert writer.fetchone(
        "SELECT COUNT(*) AS count FROM pricing_quote_facts WHERE context_kind = 'round_kick'"
    )["count"] == 1
    assert writer.fetchone(
        "SELECT COUNT(*) AS count FROM pricing_price_facts WHERE context_kind = 'round_kick'"
    )["count"] == 1


def test_pricing_drain_deletes_jobs_whose_sources_are_already_missing(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    writer.transaction(lambda conn: conn.execute("DELETE FROM takes WHERE chain_id = 1"))
    pricing = PricingCaptureRuntime(
        client=_FakePricingClient(),
        max_capture_lag_seconds=10**9,
    )

    assert capture_due_pricing(pricing, writer, chain_id=1) == 4
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_capture_queue")["count"] == 0
    assert writer.fetchone(
        "SELECT COUNT(*) AS count FROM pricing_quote_facts WHERE context_kind = 'take'"
    )["count"] == 0
    assert writer.fetchone(
        "SELECT COUNT(*) AS count FROM pricing_price_facts WHERE context_kind = 'take'"
    )["count"] == 0
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_quote_facts")["count"] == 1
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_price_facts")["count"] == 1


def test_migration_retires_obsolete_queue_states_before_current_worker_starts(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)

    def prepare_legacy_queue(conn):
        conn.execute(
            "DELETE FROM pricing_capture_queue WHERE entity_kind = 'want_token_price'"
        )
        conn.execute(
            "UPDATE pricing_capture_queue SET status = 'processing' WHERE entity_kind = 'take_quote'"
        )
        conn.execute(
            "UPDATE pricing_capture_queue SET status = 'done' WHERE entity_kind = 'round_kick_quote'"
        )

    writer.transaction(prepare_legacy_queue)
    writer.transaction(lambda conn: conn.execute("DELETE FROM _yoyo_migration WHERE migration_id = '0014_retire_old_pricing_queue_states'"))
    from backend.indexer.migrations import apply_pending_migrations
    apply_pending_migrations(db_path)
    assert {row[0] for row in writer.fetchall("SELECT status FROM pricing_capture_queue")} == {"pending"}
    pricing = PricingCaptureRuntime(
        client=_FakePricingClient(),
        max_capture_lag_seconds=10**9,
    )

    assert capture_due_pricing(pricing, writer, chain_id=1) == 1
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_capture_queue")["count"] == 0
    assert writer.fetchone("SELECT COUNT(*) AS count FROM pricing_quote_facts")["count"] == 1


def test_pricing_capture_reads_provider_error_type_from_price_api_shape(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(
        client=_ProviderErrorPricingClient(),
        max_capture_lag_seconds=10**9,
    )

    capture_due_pricing(pricing, writer, chain_id=1)

    quote_error = writer.fetchone(
        """
        SELECT p.error_code, f.aggregate_response_json
          FROM pricing_quote_provider_facts p
          JOIN pricing_quote_facts f ON f.id = p.quote_fact_id
         WHERE p.provider_id = 'curve'
           AND p.error_code IS NOT NULL
         LIMIT 1
        """
    )
    price_error = writer.fetchone(
        """
        SELECT p.error_code, p.error_retry_after_ms, f.aggregate_response_json
          FROM pricing_price_provider_facts p
          JOIN pricing_price_facts f ON f.id = p.price_fact_id
         WHERE p.provider_id = 'curve'
           AND p.error_code IS NOT NULL
         LIMIT 1
        """
    )

    assert quote_error["error_code"] == "UPSTREAM_HTTP"
    assert json.loads(quote_error["aggregate_response_json"])["providers"]["curve"]["error"]["code"] == 500
    assert price_error["error_code"] == "RATE_LIMITED"
    assert price_error["error_retry_after_ms"] == 1000
    assert json.loads(price_error["aggregate_response_json"])["providers"]["curve"]["error"]["code"] == 429


def test_enqueue_pricing_work_returns_inserted_row_count_and_dedupes(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = Writer(str(db_path))
    deployment = make_prepared(
        event_name="DeployedNewAuction",
        tx_nonce=1,
        block_number=100,
        address=DEFAULT_FACTORY,
        auction_address=DEFAULT_AUCTION,
        version="1.0.4",
        capability_family="1.0.4",
        payload={"want": DEFAULT_WANT_TOKEN},
        snapshot=make_snapshot(block_number=100),
    )
    enabled = make_prepared(
        event_name="AuctionEnabled",
        tx_nonce=2,
        block_number=101,
        payload={"from": DEFAULT_FROM_TOKEN, "to": DEFAULT_WANT_TOKEN},
    )
    kicked = make_prepared(
        event_name="AuctionKicked",
        tx_nonce=3,
        block_number=102,
        payload={"from": DEFAULT_FROM_TOKEN, "available": 500 * ONE_ETHER},
        snapshot=make_snapshot(block_number=102),
    )
    take = make_prepared(
        event_name="Take",
        tx_nonce=4,
        block_number=103,
        log_index=4,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200 * ONE_ETHER,
            "amountPaid": 150 * ONE_USDC,
            "expectedAmountPaid": 150 * ONE_USDC,
            "priceE18": 750_000_000_000_000_000,
            "matchingMethod": "receiver_transfer",
        },
    )

    def seed_and_enqueue(conn) -> tuple[int, int]:
        inserted = apply_batch_with_results(conn, [deployment, enabled, kicked, take])
        first_inserted = enqueue_pricing_work(conn, inserted)
        second_inserted = enqueue_pricing_work(conn, inserted)
        return first_inserted, second_inserted

    first_inserted, second_inserted = writer.transaction(seed_and_enqueue)

    assert first_inserted == 4
    assert second_inserted == 0


def test_pricing_rebuild_uses_stored_facts_only(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)

    projection_tables = {
        "take_pricing": "chain_id, auction_address, round_id, take_seq",
        "take_pricing_source": "chain_id, auction_address, round_id, take_seq, source_id",
        "round_pricing": "chain_id, auction_address, round_id",
        "round_pricing_source": "chain_id, auction_address, round_id, source_id",
        "taker_pricing_summary": "chain_id, taker",
    }
    fact_tables = {
        "pricing_quote_facts": "id",
        "pricing_quote_provider_facts": "id",
        "pricing_price_facts": "id",
        "pricing_price_provider_facts": "id",
    }
    projections_before = {
        table: _rows_snapshot(writer, table, order_by)
        for table, order_by in projection_tables.items()
    }
    facts_before = {
        table: _rows_snapshot(writer, table, order_by)
        for table, order_by in fact_tables.items()
    }

    writer.transaction(lambda conn: clear_projection_state(conn, 1))
    assert {
        table: _rows_snapshot(writer, table, order_by)
        for table, order_by in fact_tables.items()
    } == facts_before

    writer.transaction(lambda conn: apply_native_event_projections(conn, [events["deployment"], events["enabled"], events["kicked"]]))
    writer.transaction(lambda conn: apply_batch(conn, [events["take"]]))
    writer.transaction(lambda conn: rebuild_pricing_projections(conn, chain_id=1))

    projections_after = {
        table: _rows_snapshot(writer, table, order_by)
        for table, order_by in projection_tables.items()
    }
    assert projections_after == projections_before

    writer.transaction(lambda conn: clear_take_state(conn, 1))
    writer.transaction(lambda conn: apply_batch(conn, [events["take"]]))
    writer.transaction(lambda conn: rebuild_pricing_projections(conn, chain_id=1))

    takes_only_projections = {
        table: _rows_snapshot(writer, table, order_by)
        for table, order_by in projection_tables.items()
    }
    assert takes_only_projections == projections_before


def test_pricing_rebuild_resolves_take_canonical_rows_via_source_linkage(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)

    writer.transaction(
        lambda conn: conn.executescript(
            """
            UPDATE pricing_quote_facts
               SET auction_address = '0x0000000000000000000000000000000000000bad',
                   round_id = 999,
                   take_seq = 999
             WHERE chain_id = 1
               AND context_kind = 'take';
            UPDATE pricing_price_facts
               SET auction_address = '0x0000000000000000000000000000000000000bad',
                   round_id = 999,
                   take_seq = 999
             WHERE chain_id = 1
               AND context_kind = 'take';
            """
        )
    )

    writer.transaction(lambda conn: rebuild_pricing_projections(conn, chain_id=1))

    take_pricing = writer.fetchone(
        """
        SELECT market_quote_out_raw, want_token_price_usd, pricing_status
          FROM take_pricing
         WHERE chain_id = 1
           AND auction_address = ?
           AND round_id = 1
           AND take_seq = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(take_pricing) == {
        "market_quote_out_raw": "140000000",
        "want_token_price_usd": "1",
        "pricing_status": "priced",
    }


def test_pricing_rebuild_ignores_take_facts_with_unresolved_source_linkage(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)

    writer.transaction(
        lambda conn: conn.executescript(
            """
            UPDATE pricing_quote_facts
               SET source_tx_hash = '0x0000000000000000000000000000000000000000000000000000000000000bad'
             WHERE chain_id = 1
               AND context_kind = 'take';
            UPDATE pricing_price_facts
               SET source_tx_hash = '0x0000000000000000000000000000000000000000000000000000000000000bad'
             WHERE chain_id = 1
               AND context_kind = 'take';
            """
        )
    )

    writer.transaction(lambda conn: rebuild_pricing_projections(conn, chain_id=1))

    take_pricing = writer.fetchone(
        """
        SELECT market_quote_out_raw, want_token_price_usd, pricing_status,
               canonical_quote_fact_id, canonical_want_price_fact_id
          FROM take_pricing
         WHERE chain_id = 1
           AND auction_address = ?
           AND round_id = 1
           AND take_seq = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(take_pricing) == {
        "market_quote_out_raw": None,
        "want_token_price_usd": None,
        "pricing_status": "unpriced",
        "canonical_quote_fact_id": None,
        "canonical_want_price_fact_id": None,
    }


def test_take_and_round_api_surfaces_use_canonical_pricing(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)

    client = TestClient(create_app(db_path=str(db_path)))

    take_payload = client.get(f"/api/takes/1/0x{103:064x}/0x{4:064x}/4").json()
    assert take_payload["market_quote_out"] == "140"
    assert take_payload["market_quote_out_usd"] == "140"
    assert take_payload["amount_paid_usd"] == "150"
    assert take_payload["price_differential_usd"] == "10"
    assert take_payload["price_differential_percent"] == 7.14
    assert take_payload["pricing_status"] == "priced"
    assert take_payload["provider_success_count"] == 3
    assert take_payload["quote_facts"][0]["provider_success_count"] == 3
    assert take_payload["price_facts"][0]["canonical_price_usd"] == "1"
    quote_provider = take_payload["quote_facts"][0]["providers"][0]
    assert quote_provider["route"] == {"provider": quote_provider["provider_id"]}
    assert quote_provider["raw_provider_payload"]["amount_out"] is not None
    price_provider = take_payload["price_facts"][0]["providers"][0]
    assert price_provider["raw_provider_payload"]["price"] is not None
    assert take_payload["pricing_by_source"] == {
        "canonical": {
            "market_quote_out": "140",
            "market_quote_out_usd": "140",
            "pnl_usd": "10",
            "pnl_percent": 7.14,
            "pricing_status": "priced",
        },
        "curve": {
            "market_quote_out": "130",
            "market_quote_out_usd": "130",
            "pnl_usd": "20",
            "pnl_percent": 15.38,
            "pricing_status": "priced",
        },
        "enso": {
            "market_quote_out": "150",
            "market_quote_out_usd": "150",
            "pnl_usd": "0",
            "pnl_percent": 0.0,
            "pricing_status": "priced",
        },
        "odos": {
            "market_quote_out": "140",
            "market_quote_out_usd": "140",
            "pnl_usd": "10",
            "pnl_percent": 7.14,
            "pricing_status": "priced",
        },
    }

    rounds_payload = client.get("/api/rounds", params={"chain_id": 1}).json()
    round_item = rounds_payload["rounds"][0]
    assert round_item["kick_market_quote"] == "330"
    assert round_item["kick_market_quote_usd"] == "330"
    assert round_item["expected_price_per_unit"] == "0.66"
    assert round_item["total_actual_paid_usd"] == "150"
    assert round_item["total_market_quote_usd"] == "140"
    assert round_item["total_auction_profit_usd"] == "10"
    assert round_item["total_auction_profit_bps"] == 7.14
    assert round_item["priced_take_count"] == 1
    assert round_item["priced_volume_share"] == 1.0

    round_detail_payload = client.get(f"/api/rounds/1/0x{102:064x}/0x{3:064x}/0").json()
    assert round_detail_payload["round"]["expected_price_per_unit"] == "0.66"
    assert round_detail_payload["round"]["pricing_by_source"] == {
        "canonical": {
            "total_market_quote_usd": "140",
            "total_auction_profit_usd": "10",
            "total_auction_profit_bps": 7.14,
            "priced_take_count": 1,
            "usd_priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": 1.0,
        },
        "curve": {
            "total_market_quote_usd": "130",
            "total_auction_profit_usd": "20",
            "total_auction_profit_bps": 15.38,
            "priced_take_count": 1,
            "usd_priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": 1.0,
        },
        "enso": {
            "total_market_quote_usd": "150",
            "total_auction_profit_usd": "0",
            "total_auction_profit_bps": 0.0,
            "priced_take_count": 1,
            "usd_priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": 1.0,
        },
        "odos": {
            "total_market_quote_usd": "140",
            "total_auction_profit_usd": "10",
            "total_auction_profit_bps": 7.14,
            "priced_take_count": 1,
            "usd_priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": 1.0,
        },
    }

    auction_takes_payload = client.get(
        "/api/auctions/0x0000000000000000000000000000000000000aaa/takes",
        params={"chain_id": 1},
    ).json()
    assert auction_takes_payload["available_price_sources"] == [
        {
            "id": "canonical",
            "label": "Default",
            "is_default": True,
            "priced_take_count": 1,
            "usd_priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": 1.0,
        },
        {
            "id": "curve",
            "label": "Curve",
            "is_default": False,
            "priced_take_count": 1,
            "usd_priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": 1.0,
        },
        {
            "id": "enso",
            "label": "Enso",
            "is_default": False,
            "priced_take_count": 1,
            "usd_priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": 1.0,
        },
        {
            "id": "odos",
            "label": "Odos",
            "is_default": False,
            "priced_take_count": 1,
            "usd_priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": 1.0,
        },
    ]
    assert auction_takes_payload["takes"][0]["pricing_by_source"]["curve"]["pnl_usd"] == "20"
    assert auction_takes_payload["takes"][0]["pricing_by_source"]["enso"]["pnl_percent"] == 0.0

    taker_takes_payload = client.get("/api/takers/0x0000000000000000000000000000000000000abc/takes").json()
    assert taker_takes_payload["available_price_sources"] == auction_takes_payload["available_price_sources"]
    assert taker_takes_payload["takes"][0]["pricing_by_source"]["odos"]["pnl_usd"] == "10"
    assert taker_takes_payload["takes"][0]["pricing_by_source"]["curve"]["market_quote_out"] == "130"

    takers_payload = client.get("/api/takers").json()
    assert takers_payload["takers"][0]["total_volume_usd"] == 150.0
    assert takers_payload["takers"][0]["total_taker_profit_usd"] == -10.0


def test_pricing_source_projections_pin_selected_attempt_and_provider_values(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)

    selected_fact = writer.fetchone(
        """
        SELECT *
          FROM pricing_quote_facts
         WHERE chain_id = 1 AND context_kind = 'take'
         ORDER BY captured_at ASC, id ASC
         LIMIT 1
        """
    )
    selected_fact_id = int(selected_fact["id"])

    def insert_later_attempt(conn) -> int:
        values = {key: selected_fact[key] for key in selected_fact.keys() if key != "id"}
        values["captured_at"] = int(selected_fact["captured_at"]) + 10
        values["capture_lag_seconds"] = int(selected_fact["capture_lag_seconds"]) + 10
        values["request_id"] = "later-attempt"
        columns = list(values)
        cursor = conn.execute(
            f"INSERT INTO pricing_quote_facts ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
        later_fact_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO pricing_quote_provider_facts (
                quote_fact_id, provider_id, provider_position,
                participation_status, amount_in_raw, amount_out_raw
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (later_fact_id, "later", 0, "ok", str(200 * ONE_ETHER), str(120 * ONE_USDC)),
        )
        rebuild_pricing_projections(conn, chain_id=1)
        return later_fact_id

    later_fact_id = writer.transaction(insert_later_attempt)
    assert later_fact_id != selected_fact_id

    canonical_row = writer.fetchone(
        """
        SELECT canonical_quote_fact_id, market_quote_out_raw,
               market_quote_out_usd, auction_profit_raw,
               auction_profit_usd, auction_profit_bps,
               priced_volume_usd, pricing_status
          FROM take_pricing
         WHERE chain_id = 1
           AND auction_address = ?
           AND round_id = 1
           AND take_seq = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(canonical_row) == {
        "canonical_quote_fact_id": selected_fact_id,
        "market_quote_out_raw": str(140 * ONE_USDC),
        "market_quote_out_usd": "140",
        "auction_profit_raw": str(10 * ONE_USDC),
        "auction_profit_usd": "10",
        "auction_profit_bps": 714,
        "priced_volume_usd": "150",
        "pricing_status": "priced",
    }

    source_rows = writer.fetchall(
        """
        SELECT source_id, quote_fact_id, market_quote_out_raw,
               market_quote_out_usd, auction_profit_raw,
               auction_profit_usd, auction_profit_bps,
               priced_volume_usd, pricing_status
          FROM take_pricing_source
         WHERE chain_id = 1
           AND auction_address = ?
           AND round_id = 1
           AND take_seq = 1
         ORDER BY source_id ASC
        """,
        (DEFAULT_AUCTION,),
    )
    assert [dict(row) for row in source_rows] == [
        {
            "source_id": "curve",
            "quote_fact_id": selected_fact_id,
            "market_quote_out_raw": str(130 * ONE_USDC),
            "market_quote_out_usd": "130",
            "auction_profit_raw": str(20 * ONE_USDC),
            "auction_profit_usd": "20",
            "auction_profit_bps": 1538,
            "priced_volume_usd": "150",
            "pricing_status": "priced",
        },
        {
            "source_id": "enso",
            "quote_fact_id": selected_fact_id,
            "market_quote_out_raw": str(150 * ONE_USDC),
            "market_quote_out_usd": "150",
            "auction_profit_raw": "0",
            "auction_profit_usd": "0",
            "auction_profit_bps": 0,
            "priced_volume_usd": "150",
            "pricing_status": "priced",
        },
        {
            "source_id": "odos",
            "quote_fact_id": selected_fact_id,
            "market_quote_out_raw": str(140 * ONE_USDC),
            "market_quote_out_usd": "140",
            "auction_profit_raw": str(10 * ONE_USDC),
            "auction_profit_usd": "10",
            "auction_profit_bps": 714,
            "priced_volume_usd": "150",
            "pricing_status": "priced",
        },
    ]

    round_sources = writer.fetchall(
        """
        SELECT source_id, total_market_quote_usd, total_auction_profit_usd,
               total_auction_profit_bps, priced_take_count,
               total_take_count, priced_volume_share
          FROM round_pricing_source
         WHERE chain_id = 1 AND auction_address = ? AND round_id = 1
         ORDER BY source_id ASC
        """,
        (DEFAULT_AUCTION,),
    )
    assert [dict(row) for row in round_sources] == [
        {
            "source_id": "curve",
            "total_market_quote_usd": "130",
            "total_auction_profit_usd": "20",
            "total_auction_profit_bps": 1538,
            "priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": "1",
        },
        {
            "source_id": "enso",
            "total_market_quote_usd": "150",
            "total_auction_profit_usd": "0",
            "total_auction_profit_bps": 0,
            "priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": "1",
        },
        {
            "source_id": "odos",
            "total_market_quote_usd": "140",
            "total_auction_profit_usd": "10",
            "total_auction_profit_bps": 714,
            "priced_take_count": 1,
            "total_take_count": 1,
            "priced_volume_share": "1",
        },
    ]


def test_pricing_list_routes_read_projections_without_pricing_facts(tmp_path, monkeypatch):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)

    statements: list[str] = []
    original_connect = api_db.Database.connect

    @contextmanager
    def traced_connect(database):
        with original_connect(database) as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(api_db.Database, "connect", traced_connect)
    client = TestClient(create_app(db_path=str(db_path)))
    responses = [
        client.get(f"/api/auctions/{DEFAULT_AUCTION}/takes", params={"chain_id": 1}),
        client.get(f"/api/takers/{TAKER}/takes"),
        client.get(f"/api/rounds/1/0x{102:064x}/0x{3:064x}/0"),
    ]
    assert [response.status_code for response in responses] == [200, 200, 200]

    traced_sql = "\n".join(statements).lower()
    for fact_table in (
        "pricing_quote_facts",
        "pricing_quote_provider_facts",
        "pricing_price_facts",
        "pricing_price_provider_facts",
    ):
        assert fact_table not in traced_sql
    assert "take_pricing_source" in traced_sql
    assert "round_pricing_source" in traced_sql


def test_pricing_retries_retryable_failures(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    pricing = PricingCaptureRuntime(
        client=_FlakyQuotePricingClient(quote_failures={500 * ONE_ETHER: 1}),
        max_capture_lag_seconds=10**9,
        retry_seconds=60,
    )

    processed = capture_due_pricing(pricing, writer, chain_id=1)

    assert processed == 4
    first_attempt = writer.fetchone(
        """
        SELECT status, attempt_count, next_attempt_at, last_error
          FROM pricing_capture_queue
         WHERE chain_id = 1
           AND entity_kind = 'round_kick_quote'
        """
    )
    assert dict(first_attempt) == {
        "status": "failed",
        "attempt_count": 1,
        "next_attempt_at": int(first_attempt["next_attempt_at"]),
        "last_error": f"temporary quote failure for {500 * ONE_ETHER}",
    }
    assert writer.fetchone(
        """
        SELECT COUNT(*) AS count
          FROM pricing_quote_facts
         WHERE chain_id = 1
           AND context_kind = 'round_kick'
        """
    )["count"] == 1

    writer.transaction(
        lambda conn: conn.execute(
            """
            UPDATE pricing_capture_queue
               SET next_attempt_at = 0
             WHERE chain_id = 1
               AND entity_kind = 'round_kick_quote'
            """
        )
    )

    processed = capture_due_pricing(pricing, writer, chain_id=1)

    assert processed == 1
    retried = writer.fetchone(
        """
        SELECT status, attempt_count, next_attempt_at, last_error
          FROM pricing_capture_queue
         WHERE chain_id = 1
           AND entity_kind = 'round_kick_quote'
        """
    )
    assert retried is None
    assert writer.fetchone(
        """
        SELECT COUNT(*) AS count
          FROM pricing_quote_facts
         WHERE chain_id = 1
           AND context_kind = 'round_kick'
        """
    )["count"] == 2
    round_pricing = writer.fetchone(
        """
        SELECT kick_market_quote_out_raw
          FROM round_pricing
         WHERE chain_id = 1
           AND auction_address = ?
           AND round_id = 1
        """,
        (DEFAULT_AUCTION,),
    )
    assert dict(round_pricing) == {"kick_market_quote_out_raw": "330000000"}


def test_expected_only_take_keeps_estimates_out_of_observed_metrics(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(
        db_path,
        take_payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 200 * ONE_ETHER,
            "amountPaid": None,
            "expectedAmountPaid": 150 * ONE_USDC,
            "priceE18": 750_000_000_000_000_000,
            "matchingMethod": "amount_needed",
        },
    )
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)

    client = TestClient(create_app(db_path=str(db_path)))

    take_payload = client.get(f"/api/takes/1/0x{103:064x}/0x{4:064x}/4").json()
    assert take_payload["amount_paid"] is None
    assert take_payload["expected_amount_paid"] == "150"
    assert take_payload["amount_paid_usd"] is None
    assert take_payload["price"] is None
    assert take_payload["price_differential_usd"] is None

    taker_takes = client.get("/api/takers/0x0000000000000000000000000000000000000abc/takes").json()
    assert taker_takes["takes"][0]["amount_paid"] is None
    assert taker_takes["takes"][0]["expected_amount_paid"] == "150"
    assert taker_takes["takes"][0]["taker_profit_usd"] is None


def test_taker_pricing_summary_uses_usd_volume_share(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    extra_take = make_prepared(
        event_name="Take",
        tx_nonce=5,
        block_number=104,
        log_index=5,
        payload={
            "roundId": 1,
            "taker": TAKER,
            "receiver": DEFAULT_RECEIVER,
            "from": DEFAULT_FROM_TOKEN,
            "to": DEFAULT_WANT_TOKEN,
            "amountTaken": 50 * ONE_ETHER,
            "amountPaid": 50 * ONE_USDC,
            "expectedAmountPaid": 50 * ONE_USDC,
            "priceE18": 1,
            "matchingMethod": "receiver_transfer",
        },
    )
    writer, _events = _seed_pricing_db(db_path, extra_events=[extra_take])
    pricing = PricingCaptureRuntime(
        client=_FlakyQuotePricingClient(quote_failures={50 * ONE_ETHER: 1}),
        max_capture_lag_seconds=10**9,
        retry_seconds=60,
    )

    capture_due_pricing(pricing, writer, chain_id=1)

    taker_summary = writer.fetchone(
        """
        SELECT priced_take_count, total_take_count, total_taker_profit_usd,
               avg_taker_profit_usd, priced_volume_usd,
               total_volume_usd_for_share, priced_volume_share
          FROM taker_pricing_summary
         WHERE chain_id = 1
           AND taker = ?
        """,
        (TAKER,),
    )
    assert dict(taker_summary) == {
        "priced_take_count": 1,
        "total_take_count": 2,
        "total_taker_profit_usd": "-10",
        "avg_taker_profit_usd": "-10",
        "priced_volume_usd": "150",
        "total_volume_usd_for_share": "200",
        "priced_volume_share": "0.75",
    }


def test_takers_api_aggregates_cross_chain_profit_and_volume_share(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    taker = TAKER
    other_taker = "0x0000000000000000000000000000000000000def"
    chain_two_auction = "0x0000000000000000000000000000000000000bbb"
    chain_two_from = "0x0000000000000000000000000000000000000ddd"
    chain_two_want = "0x0000000000000000000000000000000000000eee"
    _seed_manual_taker_db(
        db_path,
        token_rows=[
            (1, DEFAULT_WANT_TOKEN, "WANT", "Want Token", 6, 0),
            (1, DEFAULT_FROM_TOKEN, "FROM", "From Token", 18, 0),
            (2, chain_two_want, "WANT2", "Want Token 2", 6, 0),
            (2, chain_two_from, "FROM2", "From Token 2", 18, 0),
        ],
        take_rows=[
            (1, DEFAULT_AUCTION, 1, 1, "0x01", 0, 1, taker, DEFAULT_RECEIVER, DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN, str(100 * ONE_ETHER), str(100 * ONE_USDC), str(100 * ONE_USDC), 1000),
            (1, DEFAULT_AUCTION, 1, 2, "0x02", 0, 2, taker, DEFAULT_RECEIVER, DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN, str(100 * ONE_ETHER), str(100 * ONE_USDC), str(100 * ONE_USDC), 1010),
            (2, chain_two_auction, 1, 1, "0x03", 0, 1, taker, DEFAULT_RECEIVER, chain_two_from, chain_two_want, str(50 * ONE_ETHER), str(50 * ONE_USDC), str(50 * ONE_USDC), 1020),
            (1, DEFAULT_AUCTION, 2, 1, "0x04", 0, 3, other_taker, DEFAULT_RECEIVER, DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN, str(10 * ONE_ETHER), str(10 * ONE_USDC), str(10 * ONE_USDC), 1030),
        ],
        taker_summary_rows=[
            (1, taker, 2, 1000, 1010),
            (2, taker, 1, 1020, 1020),
            (1, other_taker, 1, 1030, 1030),
        ],
        take_pricing_rows=[
            (1, DEFAULT_AUCTION, 1, 1, str(100 * ONE_ETHER), str(100 * ONE_USDC), str(100 * ONE_USDC), str(120 * ONE_USDC), "1", str(-20 * ONE_USDC), "-20", "priced"),
            (1, DEFAULT_AUCTION, 1, 2, str(100 * ONE_ETHER), str(100 * ONE_USDC), str(100 * ONE_USDC), None, "1", None, None, "failed"),
            (2, chain_two_auction, 1, 1, str(50 * ONE_ETHER), str(50 * ONE_USDC), str(50 * ONE_USDC), str(60 * ONE_USDC), "1", str(-10 * ONE_USDC), "-10", "priced"),
            (1, DEFAULT_AUCTION, 2, 1, str(10 * ONE_ETHER), str(10 * ONE_USDC), str(10 * ONE_USDC), str(10 * ONE_USDC), "1", "0", "0", "priced"),
        ],
        taker_pricing_rows=[
            (1, taker, 1, 2, "200", "120", "20", "20", "100", "200", "0.5", 1000, 1000),
            (2, taker, 1, 1, "50", "60", "10", "10", "50", "50", "1", 1020, 1020),
            (1, other_taker, 1, 1, "10", "10", "0", "0", "10", "10", "1", 1030, 1030),
        ],
    )
    client = TestClient(create_app(db_path=str(db_path)))

    payload = client.get("/api/takers").json()
    target = next(item for item in payload["takers"] if item["taker"].lower() == taker)

    assert target["total_volume_usd"] == 250.0
    assert target["total_taker_profit_usd"] == 30.0
    assert target["avg_taker_profit_usd"] == 15.0
    assert target["priced_take_count"] == 2
    assert target["priced_volume_share"] == pytest.approx(0.6)
    assert target["unique_chains"] == 2
    assert target["rank_by_volume"] == 1


def test_takers_volume_sort_ignores_raw_cross_token_integers(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    taker_large_raw = "0x0000000000000000000000000000000000000a11"
    taker_more_takes = "0x0000000000000000000000000000000000000b22"
    raw18_token = "0x0000000000000000000000000000000000000c33"
    raw6_token = "0x0000000000000000000000000000000000000d44"
    _seed_manual_taker_db(
        db_path,
        token_rows=[
            (1, raw18_token, "RAW18", "Raw 18", 18, 0),
            (1, raw6_token, "RAW6", "Raw 6", 6, 0),
            (1, DEFAULT_FROM_TOKEN, "FROM", "From Token", 18, 0),
        ],
        take_rows=[
            (1, DEFAULT_AUCTION, 1, 1, "0xaa", 0, 1, taker_large_raw, DEFAULT_RECEIVER, DEFAULT_FROM_TOKEN, raw18_token, str(10 * ONE_ETHER), str(ONE_ETHER), str(ONE_ETHER), 1000),
            (1, DEFAULT_AUCTION, 1, 2, "0xbb", 0, 2, taker_more_takes, DEFAULT_RECEIVER, DEFAULT_FROM_TOKEN, raw6_token, str(10 * ONE_ETHER), str(ONE_USDC), str(ONE_USDC), 1010),
            (1, DEFAULT_AUCTION, 1, 3, "0xcc", 0, 3, taker_more_takes, DEFAULT_RECEIVER, DEFAULT_FROM_TOKEN, raw6_token, str(10 * ONE_ETHER), str(ONE_USDC), str(ONE_USDC), 1020),
        ],
        taker_summary_rows=[
            (1, taker_large_raw, 1, 1000, 1000),
            (1, taker_more_takes, 2, 1010, 1020),
        ],
    )
    client = TestClient(create_app(db_path=str(db_path)))

    payload = client.get("/api/takers").json()

    assert [item["taker"].lower() for item in payload["takers"]] == [
        taker_more_takes,
        taker_large_raw,
    ]


def test_taker_sql_sorting_filtering_ranks_pagination_and_detail(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    takers = {
        "a": "0x0000000000000000000000000000000000000a01",
        "b": "0x0000000000000000000000000000000000000b02",
        "c": "0x0000000000000000000000000000000000000c03",
        "d": "0x0000000000000000000000000000000000000d04",
    }
    auction_two = "0x0000000000000000000000000000000000000aab"
    auction_three = "0x0000000000000000000000000000000000000aac"
    take_specs = [
        (1, DEFAULT_AUCTION, takers["a"], 100),
        (1, DEFAULT_AUCTION, takers["b"], 200),
        (2, auction_two, takers["b"], 190),
        (1, DEFAULT_AUCTION, takers["c"], 150),
        (1, DEFAULT_AUCTION, takers["c"], 140),
        (1, DEFAULT_AUCTION, takers["c"], 130),
        (1, DEFAULT_AUCTION, takers["d"], 250),
        (1, auction_three, takers["d"], 240),
        (1, auction_three, takers["d"], 230),
        (1, DEFAULT_AUCTION, takers["d"], 220),
    ]
    take_rows = [
        (
            chain_id,
            auction_address,
            index,
            1,
            f"0x{index:064x}",
            0,
            index,
            taker,
            DEFAULT_RECEIVER,
            DEFAULT_FROM_TOKEN,
            DEFAULT_WANT_TOKEN,
            str(ONE_ETHER),
            str(ONE_USDC),
            str(ONE_USDC),
            timestamp,
        )
        for index, (chain_id, auction_address, taker, timestamp) in enumerate(take_specs, start=1)
    ]
    writer = _seed_manual_taker_db(
        db_path,
        token_rows=[
            (1, DEFAULT_WANT_TOKEN, "WANT", "Want", 6, 0),
            (1, DEFAULT_FROM_TOKEN, "FROM", "From", 18, 0),
            (2, DEFAULT_WANT_TOKEN, "WANT", "Want", 6, 0),
            (2, DEFAULT_FROM_TOKEN, "FROM", "From", 18, 0),
        ],
        take_rows=take_rows,
        taker_summary_rows=[
            (1, takers["a"], 1, 100, 100),
            (1, takers["b"], 1, 200, 200),
            (2, takers["b"], 1, 190, 190),
            (1, takers["c"], 3, 130, 150),
            (1, takers["d"], 4, 220, 250),
        ],
        taker_pricing_rows=[
            (1, takers["a"], 1, 1, "100", "90", "10", "10", "100", "100", "1", 100, 100),
            (1, takers["b"], 1, 1, "100", "90", "10", "10", "100", "100", "1", 200, 200),
            (2, takers["b"], 1, 1, "200", "180", "20", "20", "200", "200", "1", 190, 190),
            (1, takers["c"], 3, 3, "200", "170", "30", "10", "200", "200", "1", 130, 150),
        ],
    )
    client = TestClient(create_app(db_path=str(db_path)))

    expected_orders = {
        "volume": ["b", "c", "a", "d"],
        "takes": ["d", "c", "b", "a"],
        "recent": ["d", "b", "c", "a"],
        "chains": ["b", "d", "c", "a"],
        "auctions": ["d", "b", "c", "a"],
        "taker": ["a", "b", "c", "d"],
    }
    volume_ranks = {takers["b"]: 1, takers["c"]: 2, takers["a"]: 3, takers["d"]: 4}
    take_ranks = {takers["d"]: 1, takers["c"]: 2, takers["b"]: 3, takers["a"]: 4}
    for sort_by, expected_keys in expected_orders.items():
        payload = client.get(
            "/api/takers",
            params={"sort_by": sort_by, "limit": 10},
        ).json()
        assert [item["taker"].lower() for item in payload["takers"]] == [
            takers[key]
            for key in expected_keys
        ]
        assert {
            item["taker"].lower(): item["rank_by_volume"]
            for item in payload["takers"]
        } == volume_ranks
        assert {
            item["taker"].lower(): item["rank_by_takes"]
            for item in payload["takers"]
        } == take_ranks

    first_page = client.get("/api/takers", params={"page": 1, "limit": 2}).json()
    second_page = client.get("/api/takers", params={"page": 2, "limit": 2}).json()
    empty_page = client.get("/api/takers", params={"page": 3, "limit": 2}).json()
    assert first_page["total"] == second_page["total"] == empty_page["total"] == 4
    assert len(first_page["takers"]) == len(second_page["takers"]) == 2
    assert empty_page["takers"] == []
    assert first_page["has_next"] is True
    assert second_page["has_next"] is False

    chain_filtered = client.get("/api/takers", params={"chain_id": 2}).json()
    assert chain_filtered["total"] == 1
    assert chain_filtered["takers"][0]["taker"].lower() == takers["b"]
    assert chain_filtered["takers"][0]["total_takes"] == 1
    assert chain_filtered["takers"][0]["active_chains"] == [2]
    assert chain_filtered["takers"][0]["rank_by_volume"] == 1

    address_filtered = client.get(
        "/api/takers",
        params={"q": "0B02", "sort_by": "recent"},
    ).json()
    assert address_filtered["total"] == 1
    assert address_filtered["takers"][0]["taker"].lower() == takers["b"]

    detail = client.get(f"/api/takers/{takers['b'].upper()}").json()
    assert detail["taker"].lower() == takers["b"]
    assert detail["unique_chains"] == 2
    assert detail["unique_auctions"] == 2
    assert detail["rank_by_volume"] == 1
    assert detail["rank_by_takes"] == 3
    assert len(detail["auction_breakdown"]) == 2

    plan = "\n".join(
        str(row["detail"])
        for row in writer.fetchall(
            "EXPLAIN QUERY PLAN SELECT * FROM takes WHERE taker = ? ORDER BY timestamp DESC",
            (takers["b"],),
        )
    )
    assert "idx_takes_taker_global" in plan


def test_taker_sql_materializes_only_the_requested_page(tmp_path, monkeypatch):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))
    rows = [
        (
            1,
            f"0x{index:040x}",
            index + 1,
            index,
            index,
        )
        for index in range(261)
    ]
    writer.transaction(
        lambda conn: conn.executemany(
            """
            INSERT INTO taker_summary (
                chain_id, taker, take_count, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
    )

    materialized = 0
    original = api_queries._taker_item_from_row

    def counted(row):
        nonlocal materialized
        materialized += 1
        return original(row)

    monkeypatch.setattr(api_queries, "_taker_item_from_row", counted)
    total, page_rows = api_queries.list_takers(
        writer.connection,
        chain_id=None,
        sort_by="takes",
        page=7,
        limit=15,
    )

    assert total == 261
    assert len(page_rows) == 15
    assert materialized == 15


def test_pricing_excludes_previous_branch_of_reincluded_transaction(tmp_path):
    writer, _events = _seed_pricing_db(tmp_path / "auctionscan.sqlite3")
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)
    old_fact_count = writer.fetchone("SELECT COUNT(*) FROM pricing_quote_facts")[0]

    def replace_source(conn):
        conn.execute("UPDATE domain_events SET block_hash = ? WHERE event_name IN ('Take', 'AuctionKicked')", ("0x" + "fe" * 32,))
        rebuild_pricing_projections(conn, chain_id=1)

    writer.transaction(replace_source)
    assert writer.fetchone("SELECT COUNT(*) FROM pricing_quote_facts")[0] == old_fact_count
    assert writer.fetchone("SELECT COUNT(*) FROM take_pricing WHERE canonical_quote_fact_id IS NOT NULL OR canonical_want_price_fact_id IS NOT NULL")[0] == 0
    assert writer.fetchone("SELECT COUNT(*) FROM round_pricing_source")[0] == 0


def test_scoped_pricing_matches_full_rebuild_and_removes_vanished_taker(tmp_path):
    writer, events = _seed_pricing_db(tmp_path / "auctionscan.sqlite3")
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    capture_due_pricing(pricing, writer, chain_id=1)
    old_takers = {str(row[0]) for row in writer.fetchall("SELECT DISTINCT taker FROM takes")}
    target = writer.fetchone("SELECT auction_address, round_id FROM takes")
    rounds = {(str(target[0]), int(target[1]))}
    tables = ("take_pricing", "take_pricing_source", "round_pricing", "round_pricing_source", "taker_pricing_summary")

    def snapshot():
        return {table: sorted(tuple(row) for row in writer.fetchall(f"SELECT * FROM {table}")) for table in tables}

    # The same taker also participates in an unaffected round. Updating one
    # round must still retain that taker's contributions from the other round.
    kick = events["kicked"]
    from dataclasses import replace
    another_kick = replace(kick, raw_log=replace(kick.raw_log, tx_hash='0x' + 'aa' * 32, block_number=110),
                           domain_event=replace(kick.domain_event, tx_hash='0x' + 'aa' * 32, block_number=110))
    another_take = _extra_take(tx_nonce=88, block_number=111)
    another_take = replace(another_take, domain_event=replace(another_take.domain_event,
                           payload={**another_take.domain_event.payload, "roundId": 2}))
    writer.transaction(lambda conn: (
        apply_batch_with_results(conn, [another_kick, another_take]),
        rebuild_pricing_projections(conn, chain_id=1),
    ))
    unaffected = tuple(writer.fetchone("SELECT * FROM round_pricing WHERE round_id = 2"))
    writer.transaction(lambda conn: (
        conn.execute("UPDATE takes SET amount_paid_raw = '0' WHERE round_id = 1"),
        rebuild_pricing_projections(conn, chain_id=1, rounds=rounds),
    ))
    scoped = snapshot()
    assert tuple(writer.fetchone("SELECT * FROM round_pricing WHERE round_id = 2")) == unaffected
    writer.transaction(lambda conn: rebuild_pricing_projections(conn, chain_id=1))
    assert snapshot() == scoped

    # Capture old participants before mutation; removal must clear their final
    # summary even though the replacement state contains no trace of them.
    writer.transaction(lambda conn: (
        conn.execute("DELETE FROM takes"), conn.execute("DELETE FROM taker_summary"),
        rebuild_pricing_projections(conn, chain_id=1, rounds=rounds | {(str(target[0]), 2)}, previous_takers=old_takers),
    ))
    assert writer.fetchone("SELECT COUNT(*) FROM taker_pricing_summary")[0] == 0
    scoped = snapshot()
    writer.transaction(lambda conn: rebuild_pricing_projections(conn, chain_id=1))
    assert snapshot() == scoped


def test_pricing_completion_rejects_reincluded_source(tmp_path):
    writer, _events = _seed_pricing_db(tmp_path / "auctionscan.sqlite3")
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    original_attempt = pricing._attempt

    def reorg_during_request(selected):
        result = original_attempt(selected)
        writer.transaction(lambda conn: conn.execute(
            "UPDATE domain_events SET block_hash = ? WHERE tx_hash = ? AND log_index = ?",
            ("0x" + "fe" * 32, result.job.source_tx_hash, result.job.source_log_index),
        ))
        return result

    pricing._attempt = reorg_during_request
    capture_due_pricing(pricing, writer, chain_id=1)
    assert writer.fetchone("SELECT COUNT(*) FROM pricing_quote_facts")[0] == 0
    assert writer.fetchone("SELECT COUNT(*) FROM pricing_capture_queue")[0] == 0


def test_background_pricing_is_bounded_and_does_not_hold_writer(tmp_path):
    from threading import Event

    writer, _events = _seed_pricing_db(tmp_path / "auctionscan.sqlite3")
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    started, release = Event(), Event()
    calls = []
    original = pricing._attempt

    def slow_attempt(selected):
        calls.append(selected.job.id)
        started.set()
        assert release.wait(timeout=5)
        return original(selected)

    pricing._attempt = slow_attempt
    try:
        assert pricing.poll(writer, chain_id=1) == 0
        assert started.wait(timeout=2)
        for _ in range(3):
            assert pricing.poll(writer, chain_id=1) == 0
        assert len(calls) == 1
        writer.transaction(lambda conn: conn.execute("UPDATE sync_state SET last_success_at = 42"))
        assert writer.fetchone("SELECT COUNT(*) FROM pricing_capture_queue")[0] == 4
        release.set()
        pricing._outstanding.result(timeout=3)
        assert pricing.poll(writer, chain_id=1) == 1
        assert writer.fetchone("SELECT COUNT(*) FROM pricing_capture_queue")[0] == 3
    finally:
        release.set()
        pricing.discard()


def test_pricing_restart_retries_pending_work_without_resetting_capture_age(tmp_path, monkeypatch):
    writer, _events = _seed_pricing_db(tmp_path / "auctionscan.sqlite3")
    pricing = PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9)
    pricing.poll(writer, chain_id=1)
    pricing._outstanding.result(timeout=3)
    pricing.discard()
    assert writer.fetchone("SELECT COUNT(*) FROM pricing_quote_facts")[0] == 0
    assert writer.fetchone("SELECT COUNT(*) FROM pricing_capture_queue")[0] == 4
    monkeypatch.setattr(pricing_module, "_now", lambda: 10**12)
    restarted = PricingCaptureRuntime(client=_FakePricingClient())
    capture_due_pricing(restarted, writer, chain_id=1)
    assert writer.fetchone("SELECT COUNT(*) FROM pricing_quote_facts")[0] == 0
    assert writer.fetchone("SELECT COUNT(*) FROM pricing_capture_queue")[0] == 0


@pytest.mark.parametrize("actual_paid", [None, 0, 150 * ONE_USDC])
@pytest.mark.parametrize("usd_available", [False, True])
def test_payment_meaning_and_coverage_agree_across_api_views(tmp_path, actual_paid, usd_available):
    db_path = tmp_path / "auctionscan.sqlite3"
    payload = dict(_extra_take(tx_nonce=4, block_number=103).domain_event.payload)
    payload.update(amountPaid=actual_paid, expectedAmountPaid=150 * ONE_USDC)
    writer, _ = _seed_pricing_db(db_path, take_payload=payload)
    capture_due_pricing(PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9), writer, chain_id=1)
    if not usd_available:
        def remove_usd(conn):
            conn.execute("UPDATE pricing_price_facts SET capture_state = 'stale'")
            rebuild_pricing_projections(conn, chain_id=1)
        writer.transaction(remove_usd)
    observed = actual_paid is not None
    paid = str(actual_paid // ONE_USDC) if observed else None
    usd_count = int(observed and usd_available)
    client = TestClient(create_app(db_path=str(db_path)))
    take = client.get(f"/api/takes/1/0x{103:064x}/0x{4:064x}/4").json()
    round_item = client.get(f"/api/rounds/1/0x{102:064x}/0x{3:064x}/0").json()["round"]
    auction = client.get(f"/api/auctions/{DEFAULT_AUCTION}", params={"chain_id": 1}).json()
    taker = client.get(f"/api/takers/{TAKER}").json()
    listed_taker = client.get("/api/takers").json()["takers"][0]
    assert take["amount_paid"] == round_item["paid_amount"] == auction["activity"]["total_volume"] == paid
    assert take["expected_amount_paid"] == "150"
    assert round_item["paid_take_count"] == auction["activity"]["paid_take_count"] == int(observed)
    assert round_item["priced_take_count"] == int(observed)
    assert round_item["paid_usd_take_count"] == round_item["usd_priced_take_count"] == usd_count
    for summary in (taker, listed_taker):
        assert summary["paid_usd_take_count"] == summary["priced_take_count"] == usd_count
        assert summary["total_volume_usd"] == (float(paid) if usd_count else None)
        assert summary["avg_take_size_usd"] == (float(paid) if usd_count else None)
    assert taker["auction_breakdown"][0]["paid_usd_take_count"] == usd_count
    for source in round_item["pricing_by_source"].values():
        assert source["priced_take_count"] == int(observed)
        assert source["usd_priced_take_count"] == usd_count
        assert (source["total_auction_profit_usd"] is not None) == bool(usd_count)


def test_partial_payment_averages_use_their_own_contributing_takes(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    estimated = _extra_take(tx_nonce=5, block_number=104)
    estimated = replace(estimated, domain_event=replace(estimated.domain_event, payload={**estimated.domain_event.payload, "amountPaid": None}))
    observed = _extra_take(tx_nonce=6, block_number=105)
    writer, _ = _seed_pricing_db(db_path, extra_events=[estimated, observed])
    capture_due_pricing(PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9), writer, chain_id=1)
    def exclude_last_usd(conn):
        conn.execute("UPDATE pricing_price_facts SET capture_state = 'stale' WHERE take_seq = 3")
        rebuild_pricing_projections(conn, chain_id=1)
    writer.transaction(exclude_last_usd)
    client = TestClient(create_app(db_path=str(db_path)))
    round_item = client.get(f"/api/rounds/1/0x{102:064x}/0x{3:064x}/0").json()["round"]
    assert round_item["sold_amount"] == "300"
    assert round_item["paid_amount"] == "190"
    assert round_item["avg_execution_price"] == "0.76"  # 190 / (200 + 50), excludes the estimated fill.
    assert round_item["paid_take_count"] == round_item["priced_take_count"] == 2
    assert round_item["paid_usd_take_count"] == round_item["usd_priced_take_count"] == 1
    taker = client.get(f"/api/takers/{TAKER}").json()
    assert taker["total_takes"] == 3
    assert taker["total_volume_usd"] == taker["avg_take_size_usd"] == 150
    assert taker["paid_usd_take_count"] == 1


def test_missing_decimals_do_not_create_usd_totals(tmp_path):
    writer, _ = _seed_pricing_db(tmp_path / "auctionscan.sqlite3")
    capture_due_pricing(PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9), writer, chain_id=1)
    def remove_decimals(conn):
        conn.execute("UPDATE tokens SET decimals = NULL WHERE token_address = ?", (DEFAULT_WANT_TOKEN,))
        rebuild_pricing_projections(conn, chain_id=1)
    writer.transaction(remove_decimals)
    round_row = writer.fetchone("SELECT * FROM round_pricing")
    assert round_row["total_actual_paid_raw"] == str(150 * ONE_USDC)
    assert round_row["total_actual_paid_usd"] is None
    assert round_row["paid_usd_take_count"] == round_row["usd_priced_take_count"] == 0
    assert round_row["priced_take_count"] == 1


def test_audit_uses_canonical_tie_breaking_but_keeps_stale_attempts_inspectable(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _ = _seed_pricing_db(db_path)
    capture_due_pricing(PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9), writer, chain_id=1)
    def use_two_providers(conn):
        conn.execute("UPDATE pricing_quote_provider_facts SET participation_status = 'error' WHERE provider_id = 'enso'")
        rebuild_pricing_projections(conn, chain_id=1)
    writer.transaction(use_two_providers)
    client = TestClient(create_app(db_path=str(db_path)))
    url = f"/api/takes/1/0x{103:064x}/0x{4:064x}/4"
    detail = client.get(url).json()
    assert detail["market_quote_out"] == detail["quote_facts"][0]["canonical_amount_out"] == "130"
    assert detail["quote_facts"][0]["provider_success_count"] == 2
    def expire_capture(conn):
        conn.execute("UPDATE pricing_quote_facts SET capture_state = 'stale'")
        rebuild_pricing_projections(conn, chain_id=1)
    writer.transaction(expire_capture)
    detail = client.get(url).json()
    assert detail["market_quote_out"] is None
    assert detail["quote_facts"][0]["canonical_amount_out"] == "130"
    assert detail["quote_facts"][0]["capture_state"] == "stale"
