from __future__ import annotations

import json

import pytest

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api import db as api_db
from backend.api.serializers import checksum_address, token_logo_url
from backend.indexer.live_price import LiveRoundPriceResult
from backend.indexer.projections import apply_batch, update_sync_state
from backend.indexer.writer import Writer

from .helpers import (
    DEFAULT_AUCTION,
    DEFAULT_FACTORY,
    DEFAULT_FROM_TOKEN,
    DEFAULT_RECEIVER,
    DEFAULT_WANT_TOKEN,
    make_prepared,
    make_snapshot,
)


TAKER = "0x0000000000000000000000000000000000000abc"
SECOND_AUCTION = "0x0000000000000000000000000000000000000aab"
THIRD_AUCTION = "0x0000000000000000000000000000000000000aac"
ONE_ETHER = 10**18
ONE_USDC = 10**6


def _seed_api_db(path) -> Writer:
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
    writer.transaction(lambda conn: apply_batch(conn, [deployment, enabled, kicked, take]))
    writer.transaction(
        lambda conn: conn.executemany(
            """
            INSERT OR REPLACE INTO tokens (
                chain_id, token_address, symbol, name, decimals, metadata_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, DEFAULT_FROM_TOKEN, "FROM", "From Token", 18, 0),
                (1, DEFAULT_WANT_TOKEN, "WANT", "Want Token", 6, 0),
            ],
        )
    )
    writer.transaction(
        lambda conn: update_sync_state(
            conn,
            chain_id=1,
            network_name="ethereum",
            latest_rpc_head=120,
            confirmed_head=118,
            last_confirmed_processed=103,
            last_live_processed=103,
            health="ok",
            last_error=None,
        )
    )
    writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO address_aliases (chain_id, address, alias_text, checked_at)
            VALUES (?, ?, ?, ?)
            """,
            (1, DEFAULT_RECEIVER, "Treasury Receiver", 1_700_000_200),
        )
    )
    return writer


def _tx_hash(tx_nonce: int) -> str:
    return f"0x{tx_nonce:064x}"


def _insert_take_match(
    conn,
    *,
    tx_nonce: int,
    auction_address: str,
    round_id: int,
    take_seq: int,
    log_index: int,
):
    conn.execute(
        """
        INSERT INTO takes (
            chain_id, auction_address, round_id, take_seq, tx_hash, tx_index, log_index,
            taker, receiver, from_token, want_token, amount_taken_raw, amount_paid_raw,
            expected_amount_paid_raw, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            auction_address,
            round_id,
            take_seq,
            _tx_hash(tx_nonce),
            0,
            log_index,
            TAKER,
            DEFAULT_RECEIVER,
            DEFAULT_FROM_TOKEN,
            DEFAULT_WANT_TOKEN,
            str(10 * ONE_ETHER),
            str(5 * ONE_USDC),
            str(5 * ONE_USDC),
            1_700_000_000 + tx_nonce,
        ),
    )


def _insert_kick_match(
    conn,
    *,
    tx_nonce: int,
    auction_address: str,
    round_id: int,
    log_index: int,
):
    conn.execute(
        """
        INSERT INTO round_param_snapshot (
            chain_id, auction_address, round_id, from_token, want_token, version,
            snapshot_block, snapshot_tx_hash, snapshot_log_index, param_schema, receiver,
            minimum_price_raw, starting_price_raw, step_decay_rate_raw, step_duration_raw,
            auction_length_raw, extra_params_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            auction_address,
            round_id,
            DEFAULT_FROM_TOKEN,
            DEFAULT_WANT_TOKEN,
            "1.0.4",
            200 + tx_nonce,
            _tx_hash(tx_nonce),
            log_index,
            "v1_wad_bps",
            DEFAULT_RECEIVER,
            "50",
            "100",
            "25",
            "60",
            "86400",
            "{}",
            1_700_000_000 + tx_nonce,
        ),
    )


def _insert_deployment_match(
    conn,
    *,
    tx_nonce: int,
    auction_address: str,
    log_index: int,
):
    conn.execute(
        """
        INSERT INTO domain_events (
            chain_id, block_number, block_hash, tx_hash, tx_index, log_index, event_name,
            address, auction_address, version, capability_family, payload_json, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            300 + tx_nonce,
            _tx_hash(tx_nonce + 1_000),
            _tx_hash(tx_nonce),
            0,
            log_index,
            "DeployedNewAuction",
            DEFAULT_FACTORY,
            auction_address,
            "1.0.4",
            "1.0.4",
            json.dumps({"auction": auction_address, "want": DEFAULT_WANT_TOKEN}),
            1_700_000_000 + tx_nonce,
        ),
    )


def test_api_reference_and_health_routes(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_api_db(db_path)
    client = TestClient(create_app(db_path=str(db_path)))

    chains = client.get("/api/chains")
    assert chains.status_code == 200
    assert chains.headers["cache-control"] == "public, max-age=3600"
    chain_payload = chains.json()
    assert chain_payload["count"] >= 1
    assert chain_payload["chains"]["1"]["name"] == "Ethereum"

    tokens = client.get("/api/tokens", params={"chain_id": 1})
    assert tokens.status_code == 200
    assert tokens.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=600"
    token_payload = tokens.json()
    assert token_payload["count"] == 2
    assert {item["symbol"] for item in token_payload["tokens"]} == {"FROM", "WANT"}
    assert {item["logo_url"] for item in token_payload["tokens"]} == {
        token_logo_url(1, DEFAULT_FROM_TOKEN),
        token_logo_url(1, DEFAULT_WANT_TOKEN),
    }
    assert token_logo_url(1, DEFAULT_WANT_TOKEN.upper()) == (
        f"https://prices.wavey.info/token-logos/1/{DEFAULT_WANT_TOKEN}"
    )

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.headers["cache-control"] == "no-store"
    health_payload = health.json()
    ethereum = next(item for item in health_payload["chains"] if item["chain_id"] == 1)
    assert ethereum["indexed"] is True
    assert ethereum["health"] == "stale"
    assert ethereum["health_detail"] == "No verified node head timestamp"
    assert ethereum["confirmed_head"] == 118
    assert ethereum["last_confirmed_processed"] == 103


def test_api_rounds_auction_take_taker_and_search_routes(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_api_db(db_path)
    client = TestClient(create_app(db_path=str(db_path)))

    rounds = client.get("/api/rounds", params={"chain_id": 1})
    assert rounds.status_code == 200
    assert rounds.headers["cache-control"] == "public, max-age=2"
    rounds_payload = rounds.json()
    assert rounds_payload["total"] == 1
    round_item = rounds_payload["rounds"][0]
    assert round_item["auction_address"] == "0x0000000000000000000000000000000000000aaa"
    assert round_item["status"] == "live"
    assert round_item["is_active"] is True
    assert round_item["scheduled_end_at"] is not None
    assert round_item["sold_amount"] == "200"
    assert round_item["paid_amount"] == "150"
    assert round_item["receiver_name"] == "Treasury Receiver"
    assert round_item["starting_price"] == "100"
    assert round_item["starting_price_per_unit"] == "0.2"
    assert round_item["update_interval"] == 60
    assert round_item["decay_percent"] == "0.25%"
    assert round_item["auction_length"] == 86400
    assert round_item["from_token_logo_url"] == token_logo_url(1, DEFAULT_FROM_TOKEN)
    assert round_item["want_token_logo_url"] == token_logo_url(1, DEFAULT_WANT_TOKEN)

    auctions = client.get("/api/auctions", params={"chain_id": 1})
    assert auctions.status_code == 200
    assert auctions.json()["auctions"][0]["want_token"]["logo_url"] == token_logo_url(
        1,
        DEFAULT_WANT_TOKEN,
    )

    auction = client.get(
        f"/api/auctions/{DEFAULT_AUCTION}",
        params={"chain_id": 1},
    )
    assert auction.status_code == 200
    auction_payload = auction.json()
    assert auction_payload["address"] == "0x0000000000000000000000000000000000000aaa"
    assert auction_payload["receiver_name"] == "Treasury Receiver"
    assert auction_payload["parameters"]["auction_length"] == 86400
    assert auction_payload["parameters"]["starting_price"] == "100"
    assert auction_payload["parameters"]["decay_percent"] == "0.25%"
    assert auction_payload["activity"]["total_takes"] == 1
    assert auction_payload["want_token"]["logo_url"] == token_logo_url(1, DEFAULT_WANT_TOKEN)
    assert auction_payload["from_tokens"][0]["logo_url"] == token_logo_url(
        1,
        DEFAULT_FROM_TOKEN,
    )

    auction_rounds = client.get(
        f"/api/auctions/{DEFAULT_AUCTION}/rounds",
        params={"chain_id": 1},
    )
    assert auction_rounds.status_code == 404
    filtered_rounds = client.get(
        "/api/rounds", params={"chain_id": 1, "auction_address": DEFAULT_AUCTION}
    )
    assert filtered_rounds.status_code == 200
    assert filtered_rounds.json()["rounds"] == rounds_payload["rounds"]

    auction_takes = client.get(
        f"/api/auctions/{DEFAULT_AUCTION}/takes",
        params={"chain_id": 1},
    )
    assert auction_takes.status_code == 200
    takes_payload = auction_takes.json()
    assert takes_payload["available_price_sources"] == [
        {
            "id": "canonical",
            "label": "Default",
            "is_default": True,
            "priced_take_count": 0,
            "usd_priced_take_count": 0,
            "total_take_count": 1,
            "priced_volume_share": None,
        }
    ]
    assert len(takes_payload["takes"]) == 1
    assert takes_payload["takes"][0]["amount_paid"] == "150"
    assert takes_payload["takes"][0]["confirmed"] is True
    assert takes_payload["takes"][0]["receiver_name"] == "Treasury Receiver"
    assert takes_payload["takes"][0]["from_token_logo_url"] == token_logo_url(
        1,
        DEFAULT_FROM_TOKEN,
    )
    assert takes_payload["takes"][0]["to_token_logo_url"] == token_logo_url(
        1,
        DEFAULT_WANT_TOKEN,
    )

    round_detail = client.get(f"/api/rounds/1/{DEFAULT_AUCTION}/1")
    assert round_detail.status_code == 200
    round_detail_payload = round_detail.json()
    assert round_detail_payload["round"]["round_id"] == 1
    assert round_detail_payload["round"]["from_token_logo_url"] == token_logo_url(
        1,
        DEFAULT_FROM_TOKEN,
    )
    assert round_detail_payload["round"]["want_token_logo_url"] == token_logo_url(
        1,
        DEFAULT_WANT_TOKEN,
    )
    assert round_detail_payload["round"]["pricing_by_source"] == {
        "canonical": {
            "total_market_quote_usd": None,
            "total_auction_profit_usd": None,
            "total_auction_profit_bps": None,
            "priced_take_count": 0,
            "usd_priced_take_count": 0,
            "total_take_count": 1,
            "priced_volume_share": None,
        }
    }

    take = client.get(f"/api/takes/1/0x{103:064x}/0x{4:064x}/4")
    assert take.status_code == 200
    take_payload = take.json()
    assert take_payload["take_seq"] == 1
    assert {"auction_address", "amount_taken_usd", "token_prices", "take_quotes",
            "gas_price", "base_fee", "priority_fee", "gas_used",
            "transaction_fee_eth", "transaction_fee_usd"}.isdisjoint(take_payload)
    assert take_payload["auction"] == checksum_address(DEFAULT_AUCTION)
    assert take_payload["confirmed"] is True
    assert take_payload["block_number"] == 103
    assert take_payload["price"] == "0.75"
    assert take_payload["receiver_name"] == "Treasury Receiver"
    assert take_payload["from_token_logo_url"] == token_logo_url(1, DEFAULT_FROM_TOKEN)
    assert take_payload["to_token_logo_url"] == token_logo_url(1, DEFAULT_WANT_TOKEN)
    assert take_payload["pricing_by_source"] == {
        "canonical": {
            "market_quote_out": None,
            "market_quote_out_usd": None,
            "pnl_usd": None,
            "pnl_percent": None,
            "pricing_status": None,
        }
    }

    takers = client.get("/api/takers")
    assert takers.status_code == 200
    takers_payload = takers.json()
    assert takers_payload["total"] == 1
    assert takers_payload["takers"][0]["taker"] == "0x0000000000000000000000000000000000000aBc"

    takers_filtered = client.get("/api/takers", params={"q": "0abc", "sort_by": "taker"})
    assert takers_filtered.status_code == 200
    takers_filtered_payload = takers_filtered.json()
    assert takers_filtered_payload["total"] == 1
    assert takers_filtered_payload["takers"][0]["taker"] == "0x0000000000000000000000000000000000000aBc"

    taker = client.get("/api/takers/0x0000000000000000000000000000000000000abc")
    assert taker.status_code == 200
    taker_payload = taker.json()
    assert taker_payload["unique_auctions"] == 1
    assert taker_payload["auction_breakdown"][0]["auction_address"] == "0x0000000000000000000000000000000000000aaa"

    taker_takes = client.get("/api/takers/0x0000000000000000000000000000000000000abc/takes")
    assert taker_takes.status_code == 200
    taker_takes_payload = taker_takes.json()
    assert taker_takes_payload["total_count"] == 1
    assert {"sequence", "sold"}.isdisjoint(taker_takes_payload["takes"][0])
    assert taker_takes_payload["takes"][0]["take_seq"] == 1
    assert taker_takes_payload["takes"][0]["amount_taken"] == "200"
    assert taker_takes_payload["takes"][0]["price"] == "0.75"
    assert taker_takes_payload["available_price_sources"] == [
        {
            "id": "canonical",
            "label": "Default",
            "is_default": True,
            "priced_take_count": 0,
            "usd_priced_take_count": 0,
            "total_take_count": 1,
            "priced_volume_share": None,
        }
    ]
    assert taker_takes_payload["takes"][0]["pricing_by_source"] == {
        "canonical": {
            "market_quote_out": None,
            "market_quote_out_usd": None,
            "pnl_usd": None,
            "pnl_percent": None,
            "pricing_status": None,
        }
    }

    auction_search = client.get("/api/search", params={"q": "0x0000000000000000000000000000000000000aaa"})
    assert auction_search.status_code == 200
    auction_search_payload = auction_search.json()
    assert auction_search_payload["results"][0]["type"] == "auction"

    tx_search = client.get("/api/search", params={"q": "0x0000000000000000000000000000000000000000000000000000000000000004"})
    assert tx_search.status_code == 200
    tx_search_payload = tx_search.json()
    assert tx_search_payload["results"][0]["type"] == "transaction"


def test_search_handles_mixed_case_prefixes_tokens_deduplication_and_limits(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)
    writer.transaction(
        lambda conn: conn.execute(
            "UPDATE tokens SET name = ? WHERE chain_id = 1 AND token_address = ?",
            (DEFAULT_WANT_TOKEN, DEFAULT_WANT_TOKEN),
        )
    )
    client = TestClient(create_app(db_path=str(db_path)))

    auction_results = client.get(
        "/api/search",
        params={"q": DEFAULT_AUCTION.upper()},
    ).json()["results"]
    assert auction_results[0]["type"] == "auction"
    assert auction_results[0]["address_or_hash"] == checksum_address(DEFAULT_AUCTION)

    taker_results = client.get(
        "/api/search",
        params={"q": TAKER.upper()},
    ).json()["results"]
    assert any(
        item["type"] == "taker" and item["address_or_hash"] == checksum_address(TAKER)
        for item in taker_results
    )

    tx_results = client.get(
        "/api/search",
        params={"q": _tx_hash(4).upper()},
    ).json()["results"]
    assert tx_results[0]["type"] == "transaction"
    assert tx_results[0]["address_or_hash"] == _tx_hash(4)

    symbol_results = client.get("/api/search", params={"q": "wAnT"}).json()["results"]
    want_token = next(item for item in symbol_results if item["type"] == "token")
    assert want_token["address_or_hash"] == checksum_address(DEFAULT_WANT_TOKEN)
    assert want_token["metadata"]["symbol"] == "WANT"
    assert want_token["metadata"]["logo_url"] == token_logo_url(1, DEFAULT_WANT_TOKEN)

    name_results = client.get("/api/search", params={"q": "from token"}).json()["results"]
    assert [item["metadata"]["symbol"] for item in name_results if item["type"] == "token"] == ["FROM"]

    token_address_results = client.get(
        "/api/search",
        params={"q": DEFAULT_WANT_TOKEN.upper()},
    ).json()["results"]
    matching_tokens = [
        item
        for item in token_address_results
        if item["type"] == "token"
        and item["address_or_hash"].lower() == DEFAULT_WANT_TOKEN
    ]
    assert len(matching_tokens) == 1

    limited = client.get("/api/search", params={"q": "0x0000", "limit": 1}).json()
    assert limited["total"] == 1
    assert len(limited["results"]) == 1


def test_search_prefix_queries_use_focused_indexes(tmp_path):
    writer = _seed_api_db(tmp_path / "auctionscan.sqlite3")
    plans = {
        "idx_auctions_address_search": writer.fetchall(
            "EXPLAIN QUERY PLAN SELECT * FROM auctions WHERE auction_address LIKE ? COLLATE NOCASE",
            (f"{DEFAULT_AUCTION[:12]}%",),
        ),
        "idx_taker_summary_address_search": writer.fetchall(
            "EXPLAIN QUERY PLAN SELECT * FROM taker_summary WHERE taker LIKE ? COLLATE NOCASE",
            (f"{TAKER[:12]}%",),
        ),
        "idx_takes_tx_hash_search": writer.fetchall(
            "EXPLAIN QUERY PLAN SELECT * FROM takes WHERE tx_hash LIKE ? COLLATE NOCASE",
            (f"{_tx_hash(4)[:12]}%",),
        ),
        "idx_round_snapshot_tx_hash_search": writer.fetchall(
            "EXPLAIN QUERY PLAN SELECT * FROM round_param_snapshot WHERE snapshot_tx_hash LIKE ? COLLATE NOCASE",
            (f"{_tx_hash(3)[:12]}%",),
        ),
        "idx_tokens_address_search": writer.fetchall(
            "EXPLAIN QUERY PLAN SELECT * FROM tokens WHERE token_address LIKE ? COLLATE NOCASE",
            (f"{DEFAULT_WANT_TOKEN[:12]}%",),
        ),
    }
    for index_name, rows in plans.items():
        detail = "\n".join(str(row["detail"]) for row in rows)
        assert index_name in detail


def test_api_version_filters_and_auction_version_routes(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)
    writer.transaction(
        lambda conn: apply_batch(
            conn,
            [
                make_prepared(
                    event_name="DeployedNewAuction",
                    tx_nonce=11,
                    block_number=110,
                    address=DEFAULT_FACTORY,
                    auction_address=SECOND_AUCTION,
                    version="1.0.5",
                    capability_family="1.0.5",
                    payload={"want": DEFAULT_WANT_TOKEN},
                    snapshot=make_snapshot(
                        auction_address=SECOND_AUCTION,
                        block_number=110,
                        starting_price_raw=str(100 * ONE_ETHER),
                        minimum_price_raw=str(50 * ONE_ETHER),
                    ),
                ),
                make_prepared(
                    event_name="AuctionEnabled",
                    tx_nonce=12,
                    block_number=111,
                    address=SECOND_AUCTION,
                    auction_address=SECOND_AUCTION,
                    version="1.0.5",
                    capability_family="1.0.5",
                    payload={"from": DEFAULT_FROM_TOKEN, "to": DEFAULT_WANT_TOKEN},
                ),
                make_prepared(
                    event_name="AuctionKicked",
                    tx_nonce=13,
                    block_number=112,
                    address=SECOND_AUCTION,
                    auction_address=SECOND_AUCTION,
                    version="1.0.5",
                    capability_family="1.0.5",
                    payload={"from": DEFAULT_FROM_TOKEN, "available": 25 * ONE_ETHER},
                    snapshot=make_snapshot(
                        auction_address=SECOND_AUCTION,
                        block_number=112,
                        starting_price_raw=str(100 * ONE_ETHER),
                        minimum_price_raw=str(50 * ONE_ETHER),
                    ),
                ),
            ],
        )
    )
    client = TestClient(create_app(db_path=str(db_path)))

    prefixed_rounds = client.get("/api/rounds", params={"version": "v1.0.5"})
    assert prefixed_rounds.status_code == 200
    prefixed_payload = prefixed_rounds.json()
    assert prefixed_payload["total"] == 1
    assert prefixed_payload["rounds"][0]["auction_address"] == checksum_address(SECOND_AUCTION)
    assert prefixed_payload["rounds"][0]["version"] == "1.0.5"
    assert prefixed_payload["rounds"][0]["starting_price"] == "100"

    repeated_rounds = client.get("/api/rounds", params=[("version", "1.0.5"), ("version", "1.0.4")])
    assert repeated_rounds.status_code == 200
    assert repeated_rounds.json()["total"] == 2

    missing_rounds = client.get("/api/rounds", params={"version": "9.9.9"})
    assert missing_rounds.status_code == 200
    assert missing_rounds.json()["total"] == 0

    versions = client.get("/api/auction-versions")
    assert versions.status_code == 200
    assert versions.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=600"
    version_payload = versions.json()
    assert version_payload["count"] == 2
    assert version_payload["versions"] == [
        {"version": "1.0.5", "auction_count": 1, "round_count": 1},
        {"version": "1.0.4", "auction_count": 1, "round_count": 1},
    ]

    auctions = client.get("/api/auctions", params={"version": "1.0.5"})
    assert auctions.status_code == 200
    auctions_payload = auctions.json()
    assert auctions_payload["total"] == 1
    assert auctions_payload["auctions"][0]["address"] == checksum_address(SECOND_AUCTION)
    assert auctions_payload["auctions"][0]["version"] == "1.0.5"
    assert auctions_payload["auctions"][0]["total_rounds"] == 1
    assert auctions_payload["auctions"][0]["total_takes"] == 0


def test_api_tx_resolve_routes_take_kick_deployment_invalid_and_not_found(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_api_db(db_path)
    client = TestClient(create_app(db_path=str(db_path)))

    take_response = client.get(f"/api/tx/{_tx_hash(4)}/resolve")
    assert take_response.status_code == 200
    assert take_response.json() == {
        "normalized_tx_hash": _tx_hash(4),
        "outcome": "resolved",
        "kind": "take",
        "destination": {
            "kind": "round",
            "chain_id": 1,
            "auction_address": checksum_address(DEFAULT_AUCTION),
            "round_id": 1,
            "occurrence": {"chain_id": 1, "block_hash": _tx_hash(102), "tx_hash": _tx_hash(3), "log_index": 0},
            "take_occurrence": None,
        },
    }

    bare_take_response = client.get(f"/api/tx/{_tx_hash(4)[2:]}/resolve")
    assert bare_take_response.status_code == 200
    assert bare_take_response.json()["normalized_tx_hash"] == _tx_hash(4)
    assert bare_take_response.json()["kind"] == "take"

    kick_response = client.get(f"/api/tx/{_tx_hash(3)}/resolve")
    assert kick_response.status_code == 200
    assert kick_response.json() == {
        "normalized_tx_hash": _tx_hash(3),
        "outcome": "resolved",
        "kind": "kick",
        "destination": {
            "kind": "round",
            "chain_id": 1,
            "auction_address": checksum_address(DEFAULT_AUCTION),
            "round_id": 1,
            "occurrence": {"chain_id": 1, "block_hash": _tx_hash(102), "tx_hash": _tx_hash(3), "log_index": 0},
            "take_occurrence": None,
        },
    }

    deployment_response = client.get(f"/api/tx/{_tx_hash(1)}/resolve")
    assert deployment_response.status_code == 200
    assert deployment_response.json() == {
        "normalized_tx_hash": _tx_hash(1),
        "outcome": "resolved",
        "kind": "deployment",
        "destination": {
            "kind": "auction",
            "chain_id": 1,
            "auction_address": checksum_address(DEFAULT_AUCTION),
            "round_id": None,
            "occurrence": None,
            "take_occurrence": None,
        },
    }

    invalid_response = client.get("/api/tx/not-a-hash/resolve")
    assert invalid_response.status_code == 200
    assert invalid_response.json() == {
        "normalized_tx_hash": None,
        "outcome": "invalid",
        "kind": None,
        "destination": None,
    }

    missing_response = client.get(f"/api/tx/{_tx_hash(99)}/resolve")
    assert missing_response.status_code == 200
    assert missing_response.json() == {
        "normalized_tx_hash": _tx_hash(99),
        "outcome": "not_found",
        "kind": None,
        "destination": None,
    }


def test_api_tx_resolve_applies_priority_and_ambiguity_rules(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)
    writer.transaction(
        lambda conn: (
            _insert_kick_match(conn, tx_nonce=4, auction_address=SECOND_AUCTION, round_id=2, log_index=1),
            _insert_deployment_match(conn, tx_nonce=4, auction_address=THIRD_AUCTION, log_index=2),
            _insert_deployment_match(conn, tx_nonce=3, auction_address=SECOND_AUCTION, log_index=3),
            _insert_take_match(conn, tx_nonce=8, auction_address=DEFAULT_AUCTION, round_id=1, take_seq=2, log_index=8),
            _insert_take_match(conn, tx_nonce=8, auction_address=SECOND_AUCTION, round_id=2, take_seq=1, log_index=9),
            _insert_kick_match(conn, tx_nonce=9, auction_address=DEFAULT_AUCTION, round_id=2, log_index=9),
            _insert_kick_match(conn, tx_nonce=9, auction_address=SECOND_AUCTION, round_id=3, log_index=10),
            _insert_deployment_match(conn, tx_nonce=10, auction_address=THIRD_AUCTION, log_index=7),
            _insert_deployment_match(conn, tx_nonce=10, auction_address=SECOND_AUCTION, log_index=5),
        )
    )
    client = TestClient(create_app(db_path=str(db_path)))

    take_priority = client.get(f"/api/tx/{_tx_hash(4)}/resolve")
    assert take_priority.status_code == 200
    assert take_priority.json()["kind"] == "take"
    assert take_priority.json()["destination"] == {
        "kind": "round",
        "chain_id": 1,
        "auction_address": checksum_address(DEFAULT_AUCTION),
        "round_id": 1,
        "occurrence": {"chain_id": 1, "block_hash": _tx_hash(102), "tx_hash": _tx_hash(3), "log_index": 0},
        "take_occurrence": None,
    }

    kick_priority = client.get(f"/api/tx/{_tx_hash(3)}/resolve")
    assert kick_priority.status_code == 200
    assert kick_priority.json()["kind"] == "kick"
    assert kick_priority.json()["destination"] == {
        "kind": "round",
        "chain_id": 1,
        "auction_address": checksum_address(DEFAULT_AUCTION),
        "round_id": 1,
        "occurrence": {"chain_id": 1, "block_hash": _tx_hash(102), "tx_hash": _tx_hash(3), "log_index": 0},
        "take_occurrence": None,
    }

    ambiguous_take = client.get(f"/api/tx/{_tx_hash(8)}/resolve")
    assert ambiguous_take.status_code == 200
    assert ambiguous_take.json() == {
        "normalized_tx_hash": _tx_hash(8),
        "outcome": "ambiguous",
        "kind": "take",
        "destination": None,
    }

    ambiguous_kick = client.get(f"/api/tx/{_tx_hash(9)}/resolve")
    assert ambiguous_kick.status_code == 200
    assert ambiguous_kick.json() == {
        "normalized_tx_hash": _tx_hash(9),
        "outcome": "ambiguous",
        "kind": "kick",
        "destination": None,
    }

    deployment_fallback = client.get(f"/api/tx/{_tx_hash(10)}/resolve")
    assert deployment_fallback.status_code == 200
    assert deployment_fallback.json() == {
        "normalized_tx_hash": _tx_hash(10),
        "outcome": "resolved",
        "kind": "deployment",
        "destination": {
            "kind": "auction",
            "chain_id": 1,
            "auction_address": checksum_address(SECOND_AUCTION),
            "round_id": None,
            "occurrence": None,
            "take_occurrence": None,
        },
    }


LIVE_REFERENCE = {"indexed_block": 103, "indexed_block_hash": _tx_hash(103), "indexed_timestamp": 1_700_000_103}


def _seed_live_price_db(path):
    writer = _seed_api_db(path)
    writer.transaction(lambda conn: conn.execute(
        "INSERT INTO indexed_blocks (chain_id, block_number, block_hash, parent_hash, timestamp) VALUES (1, 103, ?, ?, ?)",
        (_tx_hash(103), _tx_hash(102), LIVE_REFERENCE["indexed_timestamp"]),
    ))
    return writer


def test_api_round_live_price_route_reads_active_round_price(tmp_path, monkeypatch):
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_live_price_db(db_path)
    client = TestClient(create_app(db_path=str(db_path)))
    captured: dict[str, str] = {}

    def _fake_read_live_round_price(*, network_key: str, version: str, auction_address: str, from_token: str, want_token: str, block_hash: str):
        captured.update(
            network_key=network_key,
            version=version,
            auction_address=auction_address,
            from_token=from_token,
            want_token=want_token,
            block_hash=block_hash,
        )
        return LiveRoundPriceResult(
            is_active=True,
            current_price_raw="750000",
        )

    monkeypatch.setattr("backend.api.routes.rounds.read_live_round_price", _fake_read_live_round_price)

    response = client.get(f"/api/rounds/1/0x{102:064x}/0x{3:064x}/0/live-price", params=LIVE_REFERENCE)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload == {
        "chain_id": 1,
        "auction_address": "0x0000000000000000000000000000000000000aaa",
        "round_id": 1,
        "is_active": True,
        "current_price_raw": "750000",
        "current_price": "0.75",
        **LIVE_REFERENCE,
        "occurrence": {"chain_id": 1, "block_hash": _tx_hash(102), "tx_hash": _tx_hash(3), "log_index": 0},
    }
    assert captured == {
        "network_key": "ethereum",
        "version": "1.0.4",
        "auction_address": DEFAULT_AUCTION,
        "from_token": DEFAULT_FROM_TOKEN,
        "want_token": DEFAULT_WANT_TOKEN,
        "block_hash": _tx_hash(103),
    }


def test_api_round_live_price_route_skips_inactive_rounds(tmp_path, monkeypatch):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_live_price_db(db_path)
    writer.transaction(
        lambda conn: conn.execute(
            """
            UPDATE rounds
               SET status = 'expired',
                   end_at = kicked_at + 86400,
                   updated_at = kicked_at + 86400
             WHERE chain_id = 1
               AND auction_address = ?
               AND round_id = 1
            """,
            (DEFAULT_AUCTION,),
        )
    )
    client = TestClient(create_app(db_path=str(db_path)))

    def _unexpected_read_live_round_price(**_kwargs):
        raise AssertionError("inactive rounds should not trigger live price reads")

    monkeypatch.setattr("backend.api.routes.rounds.read_live_round_price", _unexpected_read_live_round_price)

    response = client.get(f"/api/rounds/1/0x{102:064x}/0x{3:064x}/0/live-price", params=LIVE_REFERENCE)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "chain_id": 1,
        "auction_address": "0x0000000000000000000000000000000000000aaa",
        "round_id": 1,
        "is_active": False,
        "current_price_raw": None,
        "current_price": None,
        **LIVE_REFERENCE,
        "occurrence": {"chain_id": 1, "block_hash": _tx_hash(102), "tx_hash": _tx_hash(3), "log_index": 0},
    }


def test_api_compresses_large_json_responses(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_api_db(db_path)
    client = TestClient(create_app(db_path=str(db_path)))

    response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    schemas = response.json()["components"]["schemas"]
    assert "logo_url" in schemas["TokenModel"]["properties"]
    assert {"from_token_logo_url", "want_token_logo_url"} <= set(
        schemas["RoundListItem"]["properties"]
    )
    assert {"from_token_logo_url", "to_token_logo_url"} <= set(
        schemas["TakeListItem"]["properties"]
    )


def test_api_rounds_are_sorted_by_most_recent_kick_date(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)
    older_kick = 1_700_000_100
    older_last_take = 1_700_000_900
    newer_kick = 1_700_000_500
    round_duration = 86_400

    def _prepare_round_ordering(conn):
        conn.execute(
            """
            UPDATE rounds
               SET kicked_at = ?,
                   scheduled_end_at = ?,
                   last_take_at = ?,
                   updated_at = ?
             WHERE chain_id = 1
               AND auction_address = ?
               AND round_id = 1
            """,
            (
                older_kick,
                older_kick + round_duration,
                older_last_take,
                older_last_take,
                DEFAULT_AUCTION,
            ),
        )
        apply_batch(conn, [make_prepared(
            event_name="AuctionKicked", tx_nonce=5, block_number=104,
            payload={"from": DEFAULT_FROM_TOKEN, "available": 500 * ONE_ETHER},
            snapshot=make_snapshot(block_number=104),
        )])
        conn.execute("UPDATE rounds SET kicked_at = ? WHERE round_id = 2", (newer_kick,))

    writer.transaction(_prepare_round_ordering)
    client = TestClient(create_app(db_path=str(db_path)))

    rounds = client.get("/api/rounds", params={"chain_id": 1})
    assert rounds.status_code == 200
    rounds_payload = rounds.json()
    assert [item["round_id"] for item in rounds_payload["rounds"][:2]] == [2, 1]


def test_rounds_keep_snapshot_settings_when_current_auction_settings_change(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)

    def _update_current_params(conn):
        conn.execute(
            """
            UPDATE auction_current_params
               SET starting_price_raw = ?,
                   minimum_price_raw = ?,
                   step_decay_rate_raw = ?,
                   step_duration_raw = ?,
                   auction_length_raw = ?,
                   starting_price = ?,
                   minimum_price = ?,
                   step_decay_percent = ?,
                   step_duration_seconds = ?,
                   auction_length_seconds = ?,
                   updated_at = ?
             WHERE chain_id = 1
               AND auction_address = ?
            """,
            (
                "622",
                "209246570612320234",
                "50",
                "120",
                "43200",
                "622",
                "0.209246570612320234",
                "0.5",
                120,
                43200,
                1_700_000_999,
                DEFAULT_AUCTION,
            ),
        )
    writer.transaction(_update_current_params)

    client = TestClient(create_app(db_path=str(db_path)))

    rounds = client.get("/api/rounds", params={"chain_id": 1, "auction_address": DEFAULT_AUCTION, "round_id": 1})
    assert rounds.status_code == 200
    round_item = rounds.json()["rounds"][0]
    assert round_item["starting_price"] == "100"
    assert round_item["starting_price_per_unit"] == "0.2"
    assert round_item["minimum_price"] == "0.00000000000000005"
    assert round_item["update_interval"] == 60
    assert round_item["auction_length"] == 86400
    assert round_item["decay_percent"] == "0.25%"

    auction = client.get(f"/api/auctions/{DEFAULT_AUCTION}", params={"chain_id": 1})
    assert auction.status_code == 200
    auction_payload = auction.json()
    assert auction_payload["parameters"]["starting_price"] == "622"
    assert auction_payload["parameters"]["minimum_price"] == "0.209246570612320234"
    assert auction_payload["parameters"]["update_interval"] == 120
    assert auction_payload["parameters"]["auction_length"] == 43200
    assert auction_payload["parameters"]["decay_percent"] == "0.50%"


def test_round_starting_price_per_unit_is_null_when_initial_available_is_zero(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)

    writer.transaction(
        lambda conn: conn.execute(
            """
            UPDATE rounds
               SET initial_available_raw = '0',
                   updated_at = ?
             WHERE chain_id = 1
               AND auction_address = ?
               AND round_id = 1
            """,
            (1_700_001_000, DEFAULT_AUCTION),
        )
    )

    client = TestClient(create_app(db_path=str(db_path)))
    rounds = client.get("/api/rounds", params={"chain_id": 1, "auction_address": DEFAULT_AUCTION, "round_id": 1})

    assert rounds.status_code == 200
    round_item = rounds.json()["rounds"][0]
    assert round_item["starting_price"] == "100"
    assert round_item["starting_price_per_unit"] is None


def test_api_uses_configured_database_even_when_only_default_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_api_db(db_path)
    monkeypatch.setenv("AUCTIONSCAN_DB_PATH", "new/backend/data/auctionscan.sqlite3")
    monkeypatch.setattr(api_db, "_default_db_path", lambda repo_root: db_path)

    client = TestClient(create_app())

    rounds = client.get("/api/rounds", params={"chain_id": 1})
    assert rounds.status_code == 503
    assert "SQLite database not found" in rounds.json()["detail"]


def test_api_explicit_db_path_remains_strict_for_missing_files():
    client = TestClient(create_app(db_path="new/backend/data/auctionscan.sqlite3"))

    rounds = client.get("/api/rounds", params={"chain_id": 1})
    assert rounds.status_code == 503
    assert "SQLite database not found" in rounds.json()["detail"]
    assert "new/backend/data" not in rounds.text


def test_health_does_not_publish_private_rpc_diagnostics(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)
    private_error = "RPC failed at https://private-rpc.invalid/private-credential; config /srv/private/settings"
    writer.transaction(lambda conn: conn.execute(
        "UPDATE sync_state SET health = 'error', last_error = ? WHERE chain_id = 1",
        (private_error,),
    ))
    client = TestClient(create_app(db_path=str(db_path)))

    response = client.get("/api/health")

    assert response.status_code == 200
    chain = next(item for item in response.json()["chains"] if item["chain_id"] == 1)
    assert chain["health"] == "error"
    assert chain["health_detail"] == chain["last_error"] == "Indexer sync failed; check server logs"
    assert "private-credential" not in response.text
    assert "/srv/private" not in response.text
    assert writer.fetchone("SELECT last_error FROM sync_state WHERE chain_id = 1")[0] == private_error


def test_response_reads_share_a_snapshot_during_writer_commit(tmp_path):
    from backend.api.db import Database
    from backend.indexer.writer import Writer

    path = str(tmp_path / "auctionscan.sqlite3")
    writer = Writer(path)
    writer.transaction(lambda conn: conn.execute(
        "INSERT INTO sync_state (chain_id, network_name, last_live_processed) VALUES (1, 'ethereum', 100)"))
    db = Database(path)
    with db.connect() as reader:
        assert reader.execute("SELECT last_live_processed FROM sync_state").fetchone()[0] == 100
        writer.transaction(lambda conn: conn.execute("UPDATE sync_state SET last_live_processed = 101"))
        assert reader.execute("SELECT last_live_processed FROM sync_state").fetchone()[0] == 100
    with db.connect() as reader:
        assert reader.execute("SELECT last_live_processed FROM sync_state").fetchone()[0] == 101


def test_aggregate_checkpoint_and_values_share_the_same_snapshot(tmp_path, monkeypatch):
    import backend.api.routes.rounds as routes
    from backend.indexer.writer import Writer

    path = tmp_path / "auctionscan.sqlite3"
    _seed_api_db(path)
    writer = Writer(str(path))
    writer.transaction(lambda conn: (
        conn.execute("UPDATE sync_state SET last_live_processed = 103, last_confirmed_processed = 102, finality_mode = 'finalized', last_confirmed_hash = '0x102'"),
        conn.execute("INSERT INTO indexed_blocks (chain_id, block_number, block_hash, parent_hash, timestamp) VALUES (1, 103, '0x103', '0x102', 1700000103), (1, 104, '0x104', '0x103', 1700000104)"),
    ))
    original = routes.list_rounds

    def concurrent_commit(conn, **kwargs):
        writer.transaction(lambda writer_conn: (
            writer_conn.execute("UPDATE sync_state SET last_live_processed = 104"),
            writer_conn.execute("DELETE FROM rounds"),
        ))
        return original(conn, **kwargs)

    monkeypatch.setattr(routes, "list_rounds", concurrent_commit)
    client = TestClient(create_app(db_path=str(path)))
    response = client.get("/api/rounds").json()
    assert response["total"] > 0
    assert response["as_of"]["1"] == {
        "indexed_block": 103, "indexed_block_hash": "0x103", "indexed_timestamp": 1700000103,
        "confirmed_block": 102, "confirmed_block_hash": "0x102", "finality_mode": "finalized",
    }
    response = client.get("/api/rounds").json()
    assert response["total"] == 0
    assert response["as_of"]["1"]["indexed_block"] == 104


def test_numbered_round_lookup_is_scoped_by_chain_and_auction(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_api_db(db_path)
    client = TestClient(create_app(db_path=str(db_path)))
    for address in (DEFAULT_AUCTION.lower(), DEFAULT_AUCTION.upper()):
        response = client.get(f"/api/rounds/1/{address}/1")
        assert response.status_code == 200
        assert response.json()["round"]["auction_address"].lower() == DEFAULT_AUCTION.lower()
        assert response.headers["cache-control"] == "no-store"
    for path in (f"/api/rounds/10/{DEFAULT_AUCTION}/1", f"/api/rounds/1/{TAKER}/1", f"/api/rounds/1/{DEFAULT_AUCTION}/999"):
        assert client.get(path).status_code == 404


def test_numbered_round_links_follow_projections_while_take_links_keep_exact_identity(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)
    client = TestClient(create_app(db_path=str(db_path)))
    round_url = f"/api/rounds/1/{DEFAULT_AUCTION}/1"
    take_url = f"/api/takes/1/{_tx_hash(103)}/{_tx_hash(4)}/4"
    before_round = client.get(round_url).json()["round"]["occurrence"]
    before_take = client.get(take_url).json()["occurrence"]
    def renumber(conn):
        conn.execute("UPDATE rounds SET round_id = 7")
        conn.execute("UPDATE round_param_snapshot SET round_id = 7")
        conn.execute("UPDATE takes SET round_id = 7, take_seq = 9")
    writer.transaction(renumber)
    assert client.get(round_url).status_code == 404
    round_url = f"/api/rounds/1/{DEFAULT_AUCTION}/7"
    assert client.get(round_url).json()["round"]["round_id"] == 7
    assert client.get(round_url).json()["round"]["occurrence"] == before_round
    take = client.get(take_url).json()
    assert take["round_id"] == 7 and take["take_seq"] == 9
    assert take["occurrence"] == before_take
    assert take["round_occurrence"] == before_round
    params = {"chain_id": 1, "block_hash": _tx_hash(103), "log_index": 4}
    exact = client.get(f"/api/tx/{_tx_hash(4)}/resolve", params=params).json()
    assert exact["destination"]["take_occurrence"] == before_take
    assert exact["destination"]["occurrence"] == before_round
    # Same transaction and log re-included on another branch is a different occurrence.
    writer.transaction(lambda conn: conn.execute("UPDATE domain_events SET block_hash = ? WHERE tx_hash IN (?, ?)", (_tx_hash(999), _tx_hash(3), _tx_hash(4))))
    assert client.get(round_url).json()["round"]["occurrence"]["block_hash"] == _tx_hash(999)
    assert client.get(take_url).status_code == 404
    assert client.get(f"/api/tx/{_tx_hash(4)}/resolve", params=params).json()["outcome"] == "not_found"
    assert client.get(f"/api/takes/1/{_tx_hash(999)}/{_tx_hash(4)}/4").json()["take_seq"] == 9
    assert client.get(f"/api/auctions/{DEFAULT_AUCTION}/takes", params={"chain_id": 1, "kick_block_hash": _tx_hash(102), "kick_tx_hash": _tx_hash(3), "kick_log_index": 0}).status_code == 404


def test_exact_transaction_resolution_distinguishes_logs_and_never_falls_back(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_api_db(db_path)
    writer.transaction(lambda conn: apply_batch(conn, [make_prepared(
        event_name="Take", tx_nonce=4, block_number=103, log_index=5,
        payload={"roundId": 1, "taker": TAKER, "receiver": DEFAULT_RECEIVER, "from": DEFAULT_FROM_TOKEN, "to": DEFAULT_WANT_TOKEN, "amountTaken": ONE_ETHER, "amountPaid": ONE_USDC},
    )]))
    client = TestClient(create_app(db_path=str(db_path)))
    base = f"/api/tx/{_tx_hash(4)}/resolve"
    for log_index in (4, 5):
        result = client.get(base, params={"chain_id": 1, "block_hash": _tx_hash(103), "log_index": log_index}).json()
        assert result["outcome"] == "resolved"
        assert result["destination"]["take_occurrence"]["log_index"] == log_index
    assert client.get(base, params={"chain_id": 1, "block_hash": _tx_hash(103), "log_index": 6}).json()["outcome"] == "not_found"
    assert client.get(base, params={"chain_id": 1}).json()["outcome"] == "invalid"


@pytest.mark.parametrize("changed", [
    {"indexed_block": 104},
    {"indexed_block_hash": _tx_hash(999)},
    {"indexed_timestamp": 1_700_000_104},
])
def test_live_price_rejects_snapshot_mismatch_without_rpc(tmp_path, monkeypatch, changed):
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_live_price_db(db_path)
    def no_rpc(**kwargs):
        pytest.fail("Mismatched snapshots must not call RPC")
    monkeypatch.setattr("backend.api.routes.rounds.read_live_round_price", no_rpc)
    client = TestClient(create_app(db_path=str(db_path)))
    response = client.get(f"/api/rounds/1/{_tx_hash(102)}/{_tx_hash(3)}/0/live-price", params={**LIVE_REFERENCE, **changed})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "snapshot_mismatch"
    assert response.headers["cache-control"] == "no-store"


def test_live_price_closes_database_snapshot_before_rpc_and_survives_failure(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from backend.api.db import Database
    db_path = tmp_path / "auctionscan.sqlite3"
    _seed_live_price_db(db_path)
    active = False
    original = Database.connect
    @contextmanager
    def tracked(self):
        nonlocal active
        with original(self) as conn:
            active = True
            try:
                yield conn
            finally:
                active = False
    monkeypatch.setattr(Database, "connect", tracked)
    def fail_rpc(**kwargs):
        assert not active
        assert kwargs["block_hash"] == LIVE_REFERENCE["indexed_block_hash"]
        raise TimeoutError("Provider unavailable")
    monkeypatch.setattr("backend.api.routes.rounds.read_live_round_price", fail_rpc)
    client = TestClient(create_app(db_path=str(db_path)))
    url = f"/api/rounds/1/{_tx_hash(102)}/{_tx_hash(3)}/0"
    assert client.get(url + "/live-price", params=LIVE_REFERENCE).status_code == 503
    assert client.get(f"/api/rounds/1/{DEFAULT_AUCTION}/1").status_code == 200


def test_later_kick_cannot_supply_price_to_earlier_round(tmp_path, monkeypatch):
    db_path = tmp_path / "auctionscan.sqlite3"
    writer = _seed_live_price_db(db_path)
    def later_kick(conn):
        apply_batch(conn, [make_prepared(event_name="AuctionKicked", tx_nonce=5, block_number=103, log_index=5,
            payload={"from": DEFAULT_FROM_TOKEN, "available": 500 * ONE_ETHER}, snapshot=make_snapshot(block_number=103))])
        conn.execute("UPDATE rounds SET status='live'")  # Even a stale status must not bypass the occurrence check.
    writer.transaction(later_kick)
    def no_rpc(**kwargs):
        pytest.fail("An earlier kick must not read the current token auction price")
    monkeypatch.setattr("backend.api.routes.rounds.read_live_round_price", no_rpc)
    client = TestClient(create_app(db_path=str(db_path)))
    response = client.get(f"/api/rounds/1/{_tx_hash(102)}/{_tx_hash(3)}/0/live-price", params=LIVE_REFERENCE)
    assert response.status_code == 200 and response.json()["is_active"] is False


def test_openapi_exposes_only_current_take_and_round_contract():
    schema = create_app().openapi()
    assert "/api/auctions/{auction_address}/rounds" not in schema["paths"]
    assert "/api/rounds/{chain_id}/{auction_address}/{round_id}" in schema["paths"]
    assert "/api/rounds/{chain_id}/{block_hash}/{tx_hash}/{log_index}" not in schema["paths"]
    models = schema["components"]["schemas"]
    assert {"AuctionRound", "AuctionRoundsResponse"}.isdisjoint(models)
    removed = {
        "TakerTake": {"sequence", "sold"},
        "TakeListItem": {"amount_taken_usd"},
        "TakeDetail": {"auction_address", "amount_taken_usd", "token_prices", "take_quotes",
                       "gas_price", "base_fee", "priority_fee", "gas_used",
                       "transaction_fee_eth", "transaction_fee_usd"},
        "PricingQuoteProvider": {"route", "raw_provider_payload"},
        "PricingPriceProvider": {"raw_provider_payload"},
    }
    for name, keys in removed.items():
        assert keys.isdisjoint(models[name]["properties"])
