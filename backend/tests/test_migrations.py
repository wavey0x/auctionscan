from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.indexer.migrations import _read_migrations, apply_pending_migrations, has_pending_migrations

from .helpers import capture_due_pricing, DEFAULT_AUCTION, DEFAULT_FACTORY, DEFAULT_FROM_TOKEN, DEFAULT_GOVERNANCE, DEFAULT_RECEIVER, DEFAULT_WANT_TOKEN


def _table_names(db_path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


@pytest.mark.parametrize("interrupt_migration", [False, True])
def test_cleanup_preserves_populated_database_and_incremental_writes(tmp_path, monkeypatch, interrupt_migration):
    from backend.indexer.pricing import PricingCaptureRuntime
    from backend.indexer.pricing_projections import rebuild_pricing_projections
    from backend.indexer.projections import apply_batch
    from .helpers import make_prepared
    from .test_pricing import _FakePricingClient, _seed_pricing_db

    path = tmp_path / "upgrade.sqlite3"
    writer, _ = _seed_pricing_db(path)
    capture_due_pricing(PricingCaptureRuntime(client=_FakePricingClient(), max_capture_lag_seconds=10**9), writer, chain_id=1)
    conn = writer.connection
    current_schema = list(conn.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name"))
    tables = sorted(_table_names(path) - {"sqlite_sequence", "yoyo_lock"})
    # Restore precisely the removed storage to exercise real DROP statements on
    # populated tables. Retained schema/constraints are supplied by bootstrap.
    for table, columns in {
        "take_pricing": ("canonical_from_price_fact_id INTEGER", "from_token_price_usd TEXT"),
        "round_pricing": ("kick_contract_expected_out_raw TEXT", "kick_start_premium_bps INTEGER"),
        "rounds": ("minimum_price_raw TEXT", "starting_price_raw TEXT", "step_decay_rate_raw TEXT", "step_duration_raw TEXT", "auction_length_raw TEXT"),
        "auctions": ("has_enabled_tokens INTEGER NOT NULL DEFAULT 0",),
    }.items():
        for column in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
    conn.execute("CREATE TABLE auction_param_history (id INTEGER PRIMARY KEY, value_text TEXT)")
    conn.execute("INSERT INTO auction_param_history VALUES (1, 'obsolete derived value')")
    conn.execute("DELETE FROM _yoyo_migration WHERE migration_id = '0018_legacy_cleanup'")
    conn.commit()
    before = {table: [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')] for table in tables if not table.startswith('_yoyo')}
    assert has_pending_migrations(path)

    if interrupt_migration:
        old_schema = list(conn.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name"))
        from yoyo.backends.core.sqlite3 import SQLiteBackend
        real_connect = SQLiteBackend.connect

        def fail_last_drop(backend, uri):
            connection = real_connect(backend, uri)
            connection.set_authorizer(
                lambda action, name, *_: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_DROP_TABLE and name == "auction_param_history"
                else sqlite3.SQLITE_OK
            )
            return connection

        with monkeypatch.context() as patch:
            patch.setattr(SQLiteBackend, "connect", fail_last_drop)
            with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
                apply_pending_migrations(path)
        assert list(conn.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name")) == old_schema
        assert {table: [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')] for table in before} == before
        assert has_pending_migrations(path)

    apply_pending_migrations(path)
    assert not has_pending_migrations(path)
    assert "auction_param_history" not in _table_names(path)
    # SQLite may change SQL whitespace on DROP COLUMN; definitions and indexes
    # must otherwise be identical to fresh bootstrap.
    normalize = lambda rows: [(row[0], "".join((row[1] or "").split())) for row in rows]
    assert normalize(conn.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name")) == normalize(current_schema)
    for table, old_rows in before.items():
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        assert [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')] == [
            {key: row[key] for key in columns} for row in old_rows
        ]
    after = list(conn.iterdump())
    apply_pending_migrations(path)
    assert list(conn.iterdump()) == after
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert list(conn.execute("PRAGMA foreign_key_check")) == []

    # Continue writing the migrated projections, with no reproject first.
    update = make_prepared(event_name="UpdatedStartingPrice", tx_nonce=5, block_number=104, payload={"startingPrice": 75})
    writer.transaction(lambda db: apply_batch(db, [update]))
    writer.transaction(lambda db: rebuild_pricing_projections(db, chain_id=1))
    assert writer.fetchone("SELECT starting_price FROM auction_current_params")[0] == "75"
    client = TestClient(create_app(db_path=str(path)))
    assert client.get("/api/rounds").status_code == 200
    assert client.get(f"/api/takes/1/0x{103:064x}/0x{4:064x}/4").json()["amount_paid_usd"] == "150"


def _restore_pre_compaction_pricing_tables(conn: sqlite3.Connection) -> None:
    previous_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    quote_facts = [dict(row) for row in conn.execute("SELECT * FROM pricing_quote_facts")]
    price_facts = [dict(row) for row in conn.execute("SELECT * FROM pricing_price_facts")]
    quote_providers = [
        dict(row) for row in conn.execute("SELECT * FROM pricing_quote_provider_facts")
    ]
    price_providers = [
        dict(row) for row in conn.execute("SELECT * FROM pricing_price_provider_facts")
    ]
    conn.row_factory = previous_row_factory
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        DROP TABLE pricing_quote_provider_facts;
        DROP TABLE pricing_price_provider_facts;
        DROP TABLE pricing_quote_facts;
        DROP TABLE pricing_price_facts;

        CREATE TABLE pricing_quote_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id INTEGER NOT NULL,
            auction_address TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            take_seq INTEGER,
            context_kind TEXT NOT NULL,
            capture_origin TEXT NOT NULL DEFAULT 'native',
            source_tx_hash TEXT,
            source_log_index INTEGER,
            source_event_name TEXT,
            source_block_number INTEGER,
            source_block_hash TEXT,
            event_timestamp INTEGER NOT NULL,
            captured_at INTEGER NOT NULL,
            capture_lag_seconds INTEGER NOT NULL,
            from_token TEXT NOT NULL,
            to_token TEXT NOT NULL,
            amount_in_raw TEXT NOT NULL,
            use_underlying INTEGER NOT NULL DEFAULT 1,
            provider_order_json TEXT NOT NULL,
            request_params_json TEXT NOT NULL,
            capture_state TEXT NOT NULL,
            request_id TEXT,
            upstream_selected_quote_json TEXT,
            upstream_summary_json TEXT,
            aggregate_response_json TEXT,
            vault_context_json TEXT,
            aggregate_error_json TEXT,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE pricing_quote_provider_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_fact_id INTEGER NOT NULL,
            provider_id TEXT NOT NULL,
            provider_position INTEGER NOT NULL,
            participation_status TEXT NOT NULL,
            amount_in_raw TEXT,
            amount_out_raw TEXT,
            amount_out_min_raw TEXT,
            price_impact_bps INTEGER,
            estimated_gas INTEGER,
            latency_ms INTEGER,
            as_of TEXT,
            retrieved_at TEXT,
            error_code TEXT,
            error_message TEXT,
            error_retry_after_ms INTEGER,
            route_json TEXT,
            raw_provider_payload_json TEXT,
            FOREIGN KEY (quote_fact_id) REFERENCES pricing_quote_facts(id) ON DELETE CASCADE,
            UNIQUE (quote_fact_id, provider_id)
        );

        CREATE TABLE pricing_price_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id INTEGER NOT NULL,
            auction_address TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            take_seq INTEGER,
            context_kind TEXT NOT NULL,
            capture_origin TEXT NOT NULL DEFAULT 'native',
            price_role TEXT NOT NULL,
            source_tx_hash TEXT,
            source_log_index INTEGER,
            source_event_name TEXT,
            source_block_number INTEGER,
            source_block_hash TEXT,
            event_timestamp INTEGER NOT NULL,
            captured_at INTEGER NOT NULL,
            capture_lag_seconds INTEGER NOT NULL,
            token TEXT NOT NULL,
            use_underlying INTEGER NOT NULL DEFAULT 1,
            provider_order_json TEXT NOT NULL,
            request_params_json TEXT NOT NULL,
            capture_state TEXT NOT NULL,
            request_id TEXT,
            upstream_selected_price_json TEXT,
            upstream_summary_json TEXT,
            aggregate_response_json TEXT,
            vault_context_json TEXT,
            aggregate_error_json TEXT,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE pricing_price_provider_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price_fact_id INTEGER NOT NULL,
            provider_id TEXT NOT NULL,
            provider_position INTEGER NOT NULL,
            participation_status TEXT NOT NULL,
            price_usd TEXT,
            latency_ms INTEGER,
            as_of TEXT,
            retrieved_at TEXT,
            error_code TEXT,
            error_message TEXT,
            error_retry_after_ms INTEGER,
            raw_provider_payload_json TEXT,
            FOREIGN KEY (price_fact_id) REFERENCES pricing_price_facts(id) ON DELETE CASCADE,
            UNIQUE (price_fact_id, provider_id)
        );
        """
    )
    conn.execute("PRAGMA foreign_keys = ON")

    def json_or_none(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":")) if value is not None else None

    def provider_payloads(raw):
        aggregate = json.loads(raw) if raw else {}
        providers = aggregate.get("providers") if isinstance(aggregate, dict) else None
        if isinstance(providers, dict):
            return providers
        legacy_rows = aggregate.get("legacy_provider_rows") if isinstance(aggregate, dict) else None
        return {
            str(item["source"]): item
            for item in legacy_rows or []
            if isinstance(item, dict) and item.get("source") is not None
        }

    def insert_dict(table, values):
        columns = tuple(values)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )

    quote_order = {}
    for provider in sorted(
        quote_providers,
        key=lambda row: (int(row["quote_fact_id"]), int(row["provider_position"])),
    ):
        quote_order.setdefault(int(provider["quote_fact_id"]), []).append(provider["provider_id"])
    price_order = {}
    for provider in sorted(
        price_providers,
        key=lambda row: (int(row["price_fact_id"]), int(row["provider_position"])),
    ):
        price_order.setdefault(int(provider["price_fact_id"]), []).append(provider["provider_id"])

    for values in quote_facts:
        timeout_ms = values.pop("timeout_ms")
        include_route = bool(values.pop("include_route"))
        aggregate = json.loads(values["aggregate_response_json"]) if values["aggregate_response_json"] else {}
        selected = aggregate.get("quote") if isinstance(aggregate, dict) else None
        values.update(
            provider_order_json=json.dumps(quote_order.get(int(values["id"]), [])),
            request_params_json=json.dumps(
                {
                    "chain_id": values["chain_id"],
                    "token_in": values["from_token"],
                    "token_out": values["to_token"],
                    "amount_in": values["amount_in_raw"],
                    "providers": quote_order.get(int(values["id"]), []),
                    "include_route": include_route,
                    "use_underlying": bool(values["use_underlying"]),
                    "timeout_ms": timeout_ms,
                }
            ),
            upstream_selected_quote_json=json_or_none(selected),
            upstream_summary_json=json_or_none(aggregate.get("summary") if isinstance(aggregate, dict) else None),
            vault_context_json=json_or_none(selected.get("vault_context") if isinstance(selected, dict) else None),
        )
        insert_dict("pricing_quote_facts", values)

    for values in price_facts:
        timeout_ms = values.pop("timeout_ms")
        aggregate = json.loads(values["aggregate_response_json"]) if values["aggregate_response_json"] else {}
        selected = aggregate.get("price_data") if isinstance(aggregate, dict) else None
        values.update(
            provider_order_json=json.dumps(price_order.get(int(values["id"]), [])),
            request_params_json=json.dumps(
                {
                    "chain_id": values["chain_id"],
                    "token": values["token"],
                    "providers": price_order.get(int(values["id"]), []),
                    "use_underlying": bool(values["use_underlying"]),
                    "timeout_ms": timeout_ms,
                }
            ),
            upstream_selected_price_json=json_or_none(selected),
            upstream_summary_json=json_or_none(aggregate.get("summary") if isinstance(aggregate, dict) else None),
            vault_context_json=json_or_none(selected.get("vault_context") if isinstance(selected, dict) else None),
        )
        insert_dict("pricing_price_facts", values)

    quote_payloads = {
        int(row["id"]): provider_payloads(row["aggregate_response_json"])
        for row in quote_facts
    }
    for values in quote_providers:
        payload = quote_payloads.get(int(values["quote_fact_id"]), {}).get(values["provider_id"])
        route = payload.get("route") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and "route" not in payload:
            route = payload.get("routing_path")
            if isinstance(route, str):
                try:
                    route = json.loads(route)
                except ValueError:
                    pass
        values.update(
            route_json=json_or_none(route),
            raw_provider_payload_json=json_or_none(payload),
        )
        insert_dict("pricing_quote_provider_facts", values)

    price_payloads = {
        int(row["id"]): provider_payloads(row["aggregate_response_json"])
        for row in price_facts
    }
    for values in price_providers:
        payload = price_payloads.get(int(values["price_fact_id"]), {}).get(values["provider_id"])
        values["raw_provider_payload_json"] = json_or_none(payload)
        insert_dict("pricing_price_provider_facts", values)


def _strip_capture_origin_from_pricing_fact_tables(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        CREATE TABLE pricing_quote_facts_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id INTEGER NOT NULL,
            auction_address TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            take_seq INTEGER,
            context_kind TEXT NOT NULL,
            event_timestamp INTEGER NOT NULL,
            captured_at INTEGER NOT NULL,
            capture_lag_seconds INTEGER NOT NULL,
            from_token TEXT NOT NULL,
            to_token TEXT NOT NULL,
            amount_in_raw TEXT NOT NULL,
            use_underlying INTEGER NOT NULL DEFAULT 1,
            provider_order_json TEXT NOT NULL,
            request_params_json TEXT NOT NULL,
            capture_state TEXT NOT NULL,
            request_id TEXT,
            upstream_selected_quote_json TEXT,
            upstream_summary_json TEXT,
            aggregate_response_json TEXT,
            vault_context_json TEXT,
            aggregate_error_json TEXT,
            created_at INTEGER NOT NULL
        );

        INSERT INTO pricing_quote_facts_old (
            id, chain_id, auction_address, round_id, take_seq, context_kind,
            event_timestamp, captured_at, capture_lag_seconds, from_token,
            to_token, amount_in_raw, use_underlying, provider_order_json,
            request_params_json, capture_state, request_id,
            upstream_selected_quote_json, upstream_summary_json,
            aggregate_response_json, vault_context_json, aggregate_error_json,
            created_at
        )
        SELECT id, chain_id, auction_address, round_id, take_seq, context_kind,
               event_timestamp, captured_at, capture_lag_seconds, from_token,
               to_token, amount_in_raw, use_underlying, provider_order_json,
               request_params_json, capture_state, request_id,
               upstream_selected_quote_json, upstream_summary_json,
               aggregate_response_json, vault_context_json, aggregate_error_json,
               created_at
          FROM pricing_quote_facts;

        DROP TABLE pricing_quote_facts;
        ALTER TABLE pricing_quote_facts_old RENAME TO pricing_quote_facts;

        CREATE TABLE pricing_price_facts_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id INTEGER NOT NULL,
            auction_address TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            take_seq INTEGER,
            context_kind TEXT NOT NULL,
            price_role TEXT NOT NULL,
            event_timestamp INTEGER NOT NULL,
            captured_at INTEGER NOT NULL,
            capture_lag_seconds INTEGER NOT NULL,
            token TEXT NOT NULL,
            use_underlying INTEGER NOT NULL DEFAULT 1,
            provider_order_json TEXT NOT NULL,
            request_params_json TEXT NOT NULL,
            capture_state TEXT NOT NULL,
            request_id TEXT,
            upstream_selected_price_json TEXT,
            upstream_summary_json TEXT,
            aggregate_response_json TEXT,
            vault_context_json TEXT,
            aggregate_error_json TEXT,
            created_at INTEGER NOT NULL
        );

        INSERT INTO pricing_price_facts_old (
            id, chain_id, auction_address, round_id, take_seq, context_kind,
            price_role, event_timestamp, captured_at, capture_lag_seconds,
            token, use_underlying, provider_order_json, request_params_json,
            capture_state, request_id, upstream_selected_price_json,
            upstream_summary_json, aggregate_response_json, vault_context_json,
            aggregate_error_json, created_at
        )
        SELECT id, chain_id, auction_address, round_id, take_seq, context_kind,
               price_role, event_timestamp, captured_at, capture_lag_seconds,
               token, use_underlying, provider_order_json, request_params_json,
               capture_state, request_id, upstream_selected_price_json,
               upstream_summary_json, aggregate_response_json, vault_context_json,
               aggregate_error_json, created_at
          FROM pricing_price_facts;

        DROP TABLE pricing_price_facts;
        ALTER TABLE pricing_price_facts_old RENAME TO pricing_price_facts;
        """
    )
    conn.execute("PRAGMA foreign_keys = ON")


def _strip_pricing_source_linkage(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        CREATE TABLE pricing_capture_queue_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id INTEGER NOT NULL,
            auction_address TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            take_seq INTEGER,
            entity_kind TEXT NOT NULL,
            event_timestamp INTEGER NOT NULL,
            from_token TEXT,
            to_token TEXT,
            token TEXT,
            amount_in_raw TEXT,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at INTEGER,
            last_error TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        INSERT INTO pricing_capture_queue_old (
            id, chain_id, auction_address, round_id, take_seq, entity_kind,
            event_timestamp, from_token, to_token, token, amount_in_raw,
            status, attempt_count, next_attempt_at, last_error, priority,
            created_at, updated_at
        )
        SELECT id, chain_id, auction_address, round_id, take_seq, entity_kind,
               event_timestamp, from_token, to_token, token, amount_in_raw,
               status, attempt_count, next_attempt_at, last_error, priority,
               created_at, updated_at
          FROM pricing_capture_queue;

        DROP TABLE pricing_capture_queue;
        ALTER TABLE pricing_capture_queue_old RENAME TO pricing_capture_queue;

        CREATE TABLE pricing_quote_facts_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id INTEGER NOT NULL,
            auction_address TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            take_seq INTEGER,
            context_kind TEXT NOT NULL,
            capture_origin TEXT NOT NULL DEFAULT 'native',
            event_timestamp INTEGER NOT NULL,
            captured_at INTEGER NOT NULL,
            capture_lag_seconds INTEGER NOT NULL,
            from_token TEXT NOT NULL,
            to_token TEXT NOT NULL,
            amount_in_raw TEXT NOT NULL,
            use_underlying INTEGER NOT NULL DEFAULT 1,
            provider_order_json TEXT NOT NULL,
            request_params_json TEXT NOT NULL,
            capture_state TEXT NOT NULL,
            request_id TEXT,
            upstream_selected_quote_json TEXT,
            upstream_summary_json TEXT,
            aggregate_response_json TEXT,
            vault_context_json TEXT,
            aggregate_error_json TEXT,
            created_at INTEGER NOT NULL
        );

        INSERT INTO pricing_quote_facts_old (
            id, chain_id, auction_address, round_id, take_seq, context_kind,
            capture_origin, event_timestamp, captured_at, capture_lag_seconds,
            from_token, to_token, amount_in_raw, use_underlying,
            provider_order_json, request_params_json, capture_state, request_id,
            upstream_selected_quote_json, upstream_summary_json,
            aggregate_response_json, vault_context_json, aggregate_error_json,
            created_at
        )
        SELECT id, chain_id, auction_address, round_id, take_seq, context_kind,
               capture_origin, event_timestamp, captured_at, capture_lag_seconds,
               from_token, to_token, amount_in_raw, use_underlying,
               provider_order_json, request_params_json, capture_state, request_id,
               upstream_selected_quote_json, upstream_summary_json,
               aggregate_response_json, vault_context_json, aggregate_error_json,
               created_at
          FROM pricing_quote_facts;

        DROP TABLE pricing_quote_facts;
        ALTER TABLE pricing_quote_facts_old RENAME TO pricing_quote_facts;

        CREATE TABLE pricing_price_facts_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id INTEGER NOT NULL,
            auction_address TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            take_seq INTEGER,
            context_kind TEXT NOT NULL,
            capture_origin TEXT NOT NULL DEFAULT 'native',
            price_role TEXT NOT NULL,
            event_timestamp INTEGER NOT NULL,
            captured_at INTEGER NOT NULL,
            capture_lag_seconds INTEGER NOT NULL,
            token TEXT NOT NULL,
            use_underlying INTEGER NOT NULL DEFAULT 1,
            provider_order_json TEXT NOT NULL,
            request_params_json TEXT NOT NULL,
            capture_state TEXT NOT NULL,
            request_id TEXT,
            upstream_selected_price_json TEXT,
            upstream_summary_json TEXT,
            aggregate_response_json TEXT,
            vault_context_json TEXT,
            aggregate_error_json TEXT,
            created_at INTEGER NOT NULL
        );

        INSERT INTO pricing_price_facts_old (
            id, chain_id, auction_address, round_id, take_seq, context_kind,
            capture_origin, price_role, event_timestamp, captured_at, capture_lag_seconds,
            token, use_underlying, provider_order_json, request_params_json,
            capture_state, request_id, upstream_selected_price_json,
            upstream_summary_json, aggregate_response_json, vault_context_json,
            aggregate_error_json, created_at
        )
        SELECT id, chain_id, auction_address, round_id, take_seq, context_kind,
               capture_origin, price_role, event_timestamp, captured_at, capture_lag_seconds,
               token, use_underlying, provider_order_json, request_params_json,
               capture_state, request_id, upstream_selected_price_json,
               upstream_summary_json, aggregate_response_json, vault_context_json,
               aggregate_error_json, created_at
          FROM pricing_price_facts;

        DROP TABLE pricing_price_facts;
        ALTER TABLE pricing_price_facts_old RENAME TO pricing_price_facts;
        """
    )
    conn.execute("PRAGMA foreign_keys = ON")


def test_apply_pending_migrations_bootstraps_empty_db(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"

    apply_pending_migrations(db_path)

    tables = _table_names(db_path)
    assert "sync_state" in tables
    assert "rounds" in tables
    assert "auction_snapshot_facts" in tables
    assert "take_pricing_source" in tables
    assert "round_pricing_source" in tables
    assert "address_aliases" in tables
    assert "search_documents" not in tables
    assert "_yoyo_migration" in tables
    assert "yoyo_lock" in tables
    with sqlite3.connect(db_path) as conn:
        quote_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(pricing_quote_facts)")
        }
        price_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(pricing_price_facts)")
        }
        quote_provider_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(pricing_quote_provider_facts)")
        }
        price_provider_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(pricing_price_provider_facts)")
        }
    assert {"timeout_ms", "include_route"} <= quote_columns
    assert "timeout_ms" in price_columns
    assert {
        "provider_order_json",
        "request_params_json",
        "upstream_selected_quote_json",
        "upstream_summary_json",
        "vault_context_json",
    }.isdisjoint(quote_columns)
    assert {
        "provider_order_json",
        "request_params_json",
        "upstream_selected_price_json",
        "upstream_summary_json",
        "vault_context_json",
    }.isdisjoint(price_columns)
    assert {"route_json", "raw_provider_payload_json"}.isdisjoint(quote_provider_columns)
    assert "raw_provider_payload_json" not in price_provider_columns
    assert has_pending_migrations(db_path) is False


def test_apply_pending_migrations_stamps_current_schema_without_losing_data(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    apply_pending_migrations(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tokens (
                chain_id, token_address, symbol, name, decimals, metadata_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, DEFAULT_WANT_TOKEN, "WANT", "Want Token", 6, 222),
        )
        conn.execute("DROP TABLE _yoyo_log")
        conn.execute("DROP TABLE _yoyo_migration")
        conn.execute("DROP TABLE _yoyo_version")
        conn.execute("DROP TABLE yoyo_lock")
        conn.commit()

    assert has_pending_migrations(db_path) is True

    apply_pending_migrations(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT symbol, metadata_updated_at FROM tokens WHERE chain_id = 1 AND token_address = ?",
            (DEFAULT_WANT_TOKEN,),
        ).fetchone()
    assert row == ("WANT", 222)
    assert has_pending_migrations(db_path) is False


def test_apply_pending_migrations_adds_address_aliases_to_existing_0001_db(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    apply_pending_migrations(db_path)

    migration_hash_by_id = {migration.id: str(migration.hash) for migration in _read_migrations()}
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE address_aliases")
        conn.execute(
            "DELETE FROM _yoyo_migration WHERE migration_hash = ?",
            (migration_hash_by_id["0002_address_aliases"],),
        )
        conn.commit()

    assert has_pending_migrations(db_path) is True

    apply_pending_migrations(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        migration_ids = {
            row[0]
            for row in conn.execute("SELECT migration_id FROM _yoyo_migration").fetchall()
        }

    assert "address_aliases" in tables
    assert "0002_address_aliases" in migration_ids
    assert has_pending_migrations(db_path) is False


def test_apply_pending_migrations_adds_capture_origin_to_existing_pricing_fact_tables(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    apply_pending_migrations(db_path)

    migration_hash_by_id = {migration.id: str(migration.hash) for migration in _read_migrations()}
    with sqlite3.connect(db_path) as conn:
        _restore_pre_compaction_pricing_tables(conn)
        conn.execute(
            """
            INSERT INTO pricing_quote_facts (
                chain_id, auction_address, round_id, take_seq, context_kind, capture_origin,
                event_timestamp, captured_at, capture_lag_seconds, from_token, to_token,
                amount_in_raw, use_underlying, provider_order_json, request_params_json,
                capture_state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                DEFAULT_AUCTION,
                1,
                1,
                "take",
                "native",
                1_700_000_103,
                1_700_000_104,
                1,
                DEFAULT_FROM_TOKEN,
                DEFAULT_WANT_TOKEN,
                "200000000000000000000",
                1,
                "[]",
                "{}",
                "fresh",
                1_700_000_104,
            ),
        )
        conn.execute(
            """
            INSERT INTO pricing_price_facts (
                chain_id, auction_address, round_id, take_seq, context_kind, capture_origin,
                price_role, event_timestamp, captured_at, capture_lag_seconds, token,
                use_underlying, provider_order_json, request_params_json, capture_state,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                DEFAULT_AUCTION,
                1,
                1,
                "take",
                "native",
                "want_token",
                1_700_000_103,
                1_700_000_104,
                1,
                DEFAULT_WANT_TOKEN,
                1,
                "[]",
                "{}",
                "fresh",
                1_700_000_104,
            ),
        )
        _strip_capture_origin_from_pricing_fact_tables(conn)
        conn.execute(
            "DELETE FROM _yoyo_migration WHERE migration_hash = ?",
            (migration_hash_by_id["0003_pricing_capture_origin"],),
        )
        conn.commit()

    assert has_pending_migrations(db_path) is True

    apply_pending_migrations(db_path)

    with sqlite3.connect(db_path) as conn:
        quote_columns = {row[1] for row in conn.execute("PRAGMA table_info(pricing_quote_facts)").fetchall()}
        price_columns = {row[1] for row in conn.execute("PRAGMA table_info(pricing_price_facts)").fetchall()}
        quote_origin = conn.execute("SELECT capture_origin FROM pricing_quote_facts").fetchone()[0]
        price_origin = conn.execute("SELECT capture_origin FROM pricing_price_facts").fetchone()[0]
        migration_ids = {
            row[0]
            for row in conn.execute("SELECT migration_id FROM _yoyo_migration").fetchall()
        }

    assert "capture_origin" in quote_columns
    assert "capture_origin" in price_columns
    assert quote_origin == "native"
    assert price_origin == "native"
    assert "0003_pricing_capture_origin" in migration_ids
    assert has_pending_migrations(db_path) is False


def test_apply_pending_migrations_adds_pricing_source_linkage_to_existing_tables(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    apply_pending_migrations(db_path)

    migration_hash_by_id = {migration.id: str(migration.hash) for migration in _read_migrations()}
    with sqlite3.connect(db_path) as conn:
        _restore_pre_compaction_pricing_tables(conn)
        conn.execute(
            """
            INSERT INTO domain_events (
                chain_id, block_number, block_hash, tx_hash, tx_index, log_index, event_name,
                address, auction_address, version, capability_family, payload_json, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                102,
                "0x0000000000000000000000000000000000000000000000000000000000000102",
                "0x0000000000000000000000000000000000000000000000000000000000000102",
                0,
                2,
                "AuctionKicked",
                DEFAULT_AUCTION,
                DEFAULT_AUCTION,
                "1.0.4",
                "1.0.4",
                json.dumps({"from": DEFAULT_FROM_TOKEN, "available": "500"}),
                1_700_000_102,
            ),
        )
        conn.execute(
            """
            INSERT INTO domain_events (
                chain_id, block_number, block_hash, tx_hash, tx_index, log_index, event_name,
                address, auction_address, version, capability_family, payload_json, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                103,
                "0x0000000000000000000000000000000000000000000000000000000000000103",
                "0x0000000000000000000000000000000000000000000000000000000000000103",
                0,
                3,
                "Take",
                DEFAULT_AUCTION,
                DEFAULT_AUCTION,
                "1.0.4",
                "1.0.4",
                json.dumps({"roundId": 1, "amountTaken": "200"}),
                1_700_000_103,
            ),
        )
        conn.execute(
            """
            INSERT INTO round_param_snapshot (
                chain_id, auction_address, round_id, from_token, want_token, version,
                snapshot_block, snapshot_tx_hash, snapshot_log_index, receiver,
                minimum_price_raw, starting_price_raw, step_decay_rate_raw,
                step_duration_raw, auction_length_raw, extra_params_json, param_schema, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                DEFAULT_AUCTION,
                1,
                DEFAULT_FROM_TOKEN,
                DEFAULT_WANT_TOKEN,
                "1.0.4",
                102,
                "0x0000000000000000000000000000000000000000000000000000000000000102",
                2,
                DEFAULT_RECEIVER,
                "1000000",
                "2000000",
                "100",
                "60",
                "86400",
                "{}",
                "v1_wad_bps",
                1_700_000_102,
            ),
        )
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
                DEFAULT_AUCTION,
                1,
                1,
                "0x0000000000000000000000000000000000000000000000000000000000000103",
                0,
                3,
                "0x0000000000000000000000000000000000000abc",
                DEFAULT_RECEIVER,
                DEFAULT_FROM_TOKEN,
                DEFAULT_WANT_TOKEN,
                "200000000000000000000",
                "150000000",
                "150000000",
                1_700_000_103,
            ),
        )
        conn.execute(
            """
            INSERT INTO pricing_capture_queue (
                chain_id, auction_address, round_id, take_seq, entity_kind, event_timestamp,
                from_token, to_token, token, amount_in_raw, status, attempt_count,
                next_attempt_at, last_error, priority, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                DEFAULT_AUCTION,
                1,
                1,
                "take_quote",
                1_700_000_103,
                DEFAULT_FROM_TOKEN,
                DEFAULT_WANT_TOKEN,
                None,
                "200000000000000000000",
                "pending",
                0,
                None,
                None,
                200,
                1_700_000_104,
                1_700_000_104,
            ),
        )
        conn.execute(
            """
            INSERT INTO pricing_quote_facts (
                chain_id, auction_address, round_id, take_seq, context_kind, capture_origin,
                event_timestamp, captured_at, capture_lag_seconds, from_token, to_token,
                amount_in_raw, use_underlying, provider_order_json, request_params_json,
                capture_state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                DEFAULT_AUCTION,
                1,
                1,
                "take",
                "native",
                1_700_000_103,
                1_700_000_104,
                1,
                DEFAULT_FROM_TOKEN,
                DEFAULT_WANT_TOKEN,
                "200000000000000000000",
                1,
                "[]",
                "{}",
                "fresh",
                1_700_000_104,
            ),
        )
        conn.execute(
            """
            INSERT INTO pricing_price_facts (
                chain_id, auction_address, round_id, take_seq, context_kind, capture_origin,
                price_role, event_timestamp, captured_at, capture_lag_seconds, token,
                use_underlying, provider_order_json, request_params_json, capture_state,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                DEFAULT_AUCTION,
                1,
                None,
                "round_kick",
                "native",
                "want_token",
                1_700_000_102,
                1_700_000_104,
                2,
                DEFAULT_WANT_TOKEN,
                1,
                "[]",
                "{}",
                "fresh",
                1_700_000_104,
            ),
        )
        _strip_pricing_source_linkage(conn)
        conn.execute(
            "DELETE FROM _yoyo_migration WHERE migration_hash = ?",
            (migration_hash_by_id["0005_pricing_source_linkage"],),
        )
        conn.commit()

    assert has_pending_migrations(db_path) is True

    apply_pending_migrations(db_path)

    with sqlite3.connect(db_path) as conn:
        queue_columns = {row[1] for row in conn.execute("PRAGMA table_info(pricing_capture_queue)").fetchall()}
        quote_columns = {row[1] for row in conn.execute("PRAGMA table_info(pricing_quote_facts)").fetchall()}
        price_columns = {row[1] for row in conn.execute("PRAGMA table_info(pricing_price_facts)").fetchall()}
        queue_count = conn.execute("SELECT COUNT(*) FROM pricing_capture_queue").fetchone()[0]
        quote_source = conn.execute(
            """
            SELECT source_tx_hash, source_log_index, source_event_name, source_block_number, source_block_hash
              FROM pricing_quote_facts
            """
        ).fetchone()
        price_source = conn.execute(
            """
            SELECT source_tx_hash, source_log_index, source_event_name, source_block_number, source_block_hash
              FROM pricing_price_facts
            """
        ).fetchone()
        migration_ids = {
            row[0]
            for row in conn.execute("SELECT migration_id FROM _yoyo_migration").fetchall()
        }

    assert "source_tx_hash" in queue_columns
    assert "source_tx_hash" in quote_columns
    assert "source_tx_hash" in price_columns
    assert queue_count == 0
    assert quote_source == (
        "0x0000000000000000000000000000000000000000000000000000000000000103",
        3,
        "Take",
        103,
        "0x0000000000000000000000000000000000000000000000000000000000000103",
    )
    assert price_source == (
        "0x0000000000000000000000000000000000000000000000000000000000000102",
        2,
        "AuctionKicked",
        102,
        "0x0000000000000000000000000000000000000000000000000000000000000102",
    )
    assert "0005_pricing_source_linkage" in migration_ids
    assert has_pending_migrations(db_path) is False


def test_pricing_fact_compaction_preserves_audit_history_projections_and_replay(tmp_path):
    from backend.indexer.pricing import PricingCaptureRuntime
    from backend.indexer.pricing_projections import rebuild_pricing_projections

    from .test_pricing import _FakePricingClient, _seed_pricing_db

    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    capture_due_pricing(PricingCaptureRuntime(
        client=_FakePricingClient(),
        max_capture_lag_seconds=10**9,
    ), writer, chain_id=1)
    writer.connection.close()

    migration_hash_by_id = {migration.id: str(migration.hash) for migration in _read_migrations()}
    with sqlite3.connect(db_path) as conn:
        _restore_pre_compaction_pricing_tables(conn)
        quote_fact_id, quote_request_json = conn.execute(
            "SELECT id, request_params_json FROM pricing_quote_facts ORDER BY id LIMIT 1"
        ).fetchone()
        quote_request = json.loads(quote_request_json)
        quote_request.update(timeout_ms=4321, include_route=False)
        conn.execute(
            "UPDATE pricing_quote_facts SET request_params_json = ? WHERE id = ?",
            (json.dumps(quote_request), quote_fact_id),
        )
        price_fact_id, price_request_json = conn.execute(
            "SELECT id, request_params_json FROM pricing_price_facts ORDER BY id LIMIT 1"
        ).fetchone()
        price_request = json.loads(price_request_json)
        price_request["timeout_ms"] = 8765
        conn.execute(
            "UPDATE pricing_price_facts SET request_params_json = ? WHERE id = ?",
            (json.dumps(price_request), price_fact_id),
        )
        conn.commit()

    take_url = f"/api/takes/1/0x{103:064x}/0x{4:064x}/4"
    before_response = TestClient(create_app(db_path=str(db_path))).get(take_url)
    assert before_response.status_code == 200

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM _yoyo_migration WHERE migration_hash = ?",
            (migration_hash_by_id["0008_pricing_fact_compaction"],),
        )
        conn.commit()

    parent_columns = {
        "pricing_quote_facts": (
            "id",
            "chain_id",
            "auction_address",
            "round_id",
            "take_seq",
            "context_kind",
            "capture_origin",
            "source_tx_hash",
            "source_log_index",
            "source_event_name",
            "source_block_number",
            "source_block_hash",
            "event_timestamp",
            "captured_at",
            "capture_lag_seconds",
            "from_token",
            "to_token",
            "amount_in_raw",
            "use_underlying",
            "capture_state",
            "request_id",
            "aggregate_response_json",
            "aggregate_error_json",
            "created_at",
        ),
        "pricing_price_facts": (
            "id",
            "chain_id",
            "auction_address",
            "round_id",
            "take_seq",
            "context_kind",
            "capture_origin",
            "price_role",
            "source_tx_hash",
            "source_log_index",
            "source_event_name",
            "source_block_number",
            "source_block_hash",
            "event_timestamp",
            "captured_at",
            "capture_lag_seconds",
            "token",
            "use_underlying",
            "capture_state",
            "request_id",
            "aggregate_response_json",
            "aggregate_error_json",
            "created_at",
        ),
    }
    provider_columns = {
        "pricing_quote_provider_facts": (
            "id",
            "quote_fact_id",
            "provider_id",
            "provider_position",
            "participation_status",
            "amount_in_raw",
            "amount_out_raw",
            "amount_out_min_raw",
            "price_impact_bps",
            "estimated_gas",
            "latency_ms",
            "as_of",
            "retrieved_at",
            "error_code",
            "error_message",
            "error_retry_after_ms",
        ),
        "pricing_price_provider_facts": (
            "id",
            "price_fact_id",
            "provider_id",
            "provider_position",
            "participation_status",
            "price_usd",
            "latency_ms",
            "as_of",
            "retrieved_at",
            "error_code",
            "error_message",
            "error_retry_after_ms",
        ),
    }
    projection_tables = {
        "take_pricing": "chain_id, auction_address, round_id, take_seq",
        "take_pricing_source": "chain_id, auction_address, round_id, take_seq, source_id",
        "round_pricing": "chain_id, auction_address, round_id",
        "round_pricing_source": "chain_id, auction_address, round_id, source_id",
        "taker_pricing_summary": "chain_id, taker",
    }

    def selected_rows(conn, table, columns):
        return conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY id"
        ).fetchall()

    def raw_hashes(conn, table):
        return [
            (
                row[0],
                hashlib.sha256((row[1] or "").encode()).hexdigest(),
                hashlib.sha256((row[2] or "").encode()).hexdigest(),
            )
            for row in conn.execute(
                f"SELECT id, aggregate_response_json, aggregate_error_json FROM {table} ORDER BY id"
            )
        ]

    with sqlite3.connect(db_path) as conn:
        before_parents = {
            table: selected_rows(conn, table, columns)
            for table, columns in parent_columns.items()
        }
        before_providers = {
            table: selected_rows(conn, table, columns)
            for table, columns in provider_columns.items()
        }
        before_hashes = {table: raw_hashes(conn, table) for table in parent_columns}
        before_projections = {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
            for table, order_by in projection_tables.items()
        }
        duplicate_json_bytes = conn.execute(
            """
            SELECT
                COALESCE((SELECT SUM(
                    length(provider_order_json) + length(request_params_json)
                    + COALESCE(length(upstream_selected_quote_json), 0)
                    + COALESCE(length(upstream_summary_json), 0)
                    + COALESCE(length(vault_context_json), 0)
                ) FROM pricing_quote_facts), 0)
              + COALESCE((SELECT SUM(
                    length(provider_order_json) + length(request_params_json)
                    + COALESCE(length(upstream_selected_price_json), 0)
                    + COALESCE(length(upstream_summary_json), 0)
                    + COALESCE(length(vault_context_json), 0)
                ) FROM pricing_price_facts), 0)
              + COALESCE((SELECT SUM(
                    COALESCE(length(route_json), 0)
                    + COALESCE(length(raw_provider_payload_json), 0)
                ) FROM pricing_quote_provider_facts), 0)
              + COALESCE((SELECT SUM(
                    COALESCE(length(raw_provider_payload_json), 0)
                ) FROM pricing_price_provider_facts), 0)
            """
        ).fetchone()[0]

    assert duplicate_json_bytes > 0
    assert has_pending_migrations(db_path) is True
    apply_pending_migrations(db_path)
    assert has_pending_migrations(db_path) is False

    after_response = TestClient(create_app(db_path=str(db_path))).get(take_url)
    assert after_response.status_code == 200
    assert after_response.json() == before_response.json()

    with sqlite3.connect(db_path) as conn:
        assert {
            table: selected_rows(conn, table, columns)
            for table, columns in parent_columns.items()
        } == before_parents
        assert {
            table: selected_rows(conn, table, columns)
            for table, columns in provider_columns.items()
        } == before_providers
        assert {table: raw_hashes(conn, table) for table in parent_columns} == before_hashes
        assert {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
            for table, order_by in projection_tables.items()
        } == before_projections
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {
            tuple(row)
            for row in conn.execute(
                "SELECT timeout_ms, include_route FROM pricing_quote_facts"
            )
        } == {(4321, 0), (7000, 1)}
        assert {
            row[0] for row in conn.execute("SELECT timeout_ms FROM pricing_price_facts")
        } == {7000, 8765}

        conn.row_factory = sqlite3.Row
        rebuild_pricing_projections(conn, chain_id=1)
        replayed_projections = {
            table: [
                tuple(row)
                for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
            ]
            for table, order_by in projection_tables.items()
        }
        assert replayed_projections == before_projections

        max_quote_id = max(row[0] for row in before_parents["pricing_quote_facts"])
        source = conn.execute(
            "SELECT * FROM pricing_quote_facts ORDER BY id LIMIT 1"
        ).fetchone()
        columns = [column[1] for column in conn.execute("PRAGMA table_info(pricing_quote_facts)")]
        insert_columns = columns[1:]
        cursor = conn.execute(
            f"INSERT INTO pricing_quote_facts ({', '.join(insert_columns)}) "
            f"VALUES ({', '.join('?' for _ in insert_columns)})",
            tuple(source[index] for index in range(1, len(columns))),
        )
        assert cursor.lastrowid > max_quote_id


def test_pricing_fact_compaction_fails_closed_when_raw_provider_payload_is_not_reconstructable(
    tmp_path,
):
    from backend.indexer.pricing import PricingCaptureRuntime

    from .test_pricing import _FakePricingClient, _seed_pricing_db

    db_path = tmp_path / "auctionscan.sqlite3"
    writer, _events = _seed_pricing_db(db_path)
    capture_due_pricing(PricingCaptureRuntime(
        client=_FakePricingClient(),
        max_capture_lag_seconds=10**9,
    ), writer, chain_id=1)
    writer.connection.close()

    migration_hash_by_id = {migration.id: str(migration.hash) for migration in _read_migrations()}
    with sqlite3.connect(db_path) as conn:
        _restore_pre_compaction_pricing_tables(conn)
        before_count = conn.execute(
            "SELECT COUNT(*) FROM pricing_quote_provider_facts"
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE pricing_quote_provider_facts
               SET raw_provider_payload_json = '{"tampered":true}'
             WHERE id = (SELECT MIN(id) FROM pricing_quote_provider_facts)
            """
        )
        conn.execute(
            "DELETE FROM _yoyo_migration WHERE migration_hash = ?",
            (migration_hash_by_id["0008_pricing_fact_compaction"],),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="provider payload cannot be reconstructed"):
        apply_pending_migrations(db_path)

    with sqlite3.connect(db_path) as conn:
        quote_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(pricing_quote_facts)")
        }
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        after_count = conn.execute(
            "SELECT COUNT(*) FROM pricing_quote_provider_facts"
        ).fetchone()[0]
        compact_migration_stamped = conn.execute(
            "SELECT COUNT(*) FROM _yoyo_migration WHERE migration_hash = ?",
            (migration_hash_by_id["0008_pricing_fact_compaction"],),
        ).fetchone()[0]

    assert "request_params_json" in quote_columns
    assert not any(table.endswith("_compact") for table in tables)
    assert after_count == before_count
    assert compact_migration_stamped == 0


def test_apply_pending_migrations_adds_pricing_source_projection_tables(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    apply_pending_migrations(db_path)

    migration_hash_by_id = {migration.id: str(migration.hash) for migration in _read_migrations()}
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE take_pricing_source")
        conn.execute("DROP TABLE round_pricing_source")
        conn.execute("ALTER TABLE take_pricing DROP COLUMN market_quote_out_usd")
        conn.execute("ALTER TABLE take_pricing DROP COLUMN priced_volume_usd")
        conn.execute(
            "DELETE FROM _yoyo_migration WHERE migration_hash = ?",
            (migration_hash_by_id["0006_pricing_source_projections"],),
        )
        conn.commit()

    assert has_pending_migrations(db_path) is True
    apply_pending_migrations(db_path)

    tables = _table_names(db_path)
    assert "take_pricing_source" in tables
    assert "round_pricing_source" in tables
    with sqlite3.connect(db_path) as conn:
        take_pricing_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(take_pricing)").fetchall()
        }
        migration_ids = {
            row[0]
            for row in conn.execute("SELECT migration_id FROM _yoyo_migration").fetchall()
        }
    assert "0006_pricing_source_projections" in migration_ids
    assert {"market_quote_out_usd", "priced_volume_usd"} <= take_pricing_columns
    assert has_pending_migrations(db_path) is False


def test_apply_pending_migrations_moves_taker_coverage_and_removes_search_table(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    apply_pending_migrations(db_path)

    migration_hash_by_id = {migration.id: str(migration.hash) for migration in _read_migrations()}
    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE taker_pricing_summary DROP COLUMN priced_volume_usd")
        conn.execute("ALTER TABLE taker_pricing_summary DROP COLUMN total_volume_usd_for_share")
        conn.execute(
            """
            CREATE TABLE search_documents (
                doc_type TEXT NOT NULL,
                doc_key TEXT NOT NULL,
                content TEXT NOT NULL,
                chain_id INTEGER
            )
            """
        )
        conn.execute(
            "DELETE FROM _yoyo_migration WHERE migration_hash = ?",
            (migration_hash_by_id["0007_taker_sql_search"],),
        )
        conn.commit()

    assert has_pending_migrations(db_path) is True
    apply_pending_migrations(db_path)

    tables = _table_names(db_path)
    assert "search_documents" not in tables
    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(taker_pricing_summary)").fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    assert {"priced_volume_usd", "total_volume_usd_for_share"} <= columns
    assert {
        "idx_takes_taker_global",
        "idx_takes_tx_hash_search",
        "idx_auctions_address_search",
        "idx_taker_summary_address_search",
        "idx_tokens_address_search",
        "idx_round_snapshot_tx_hash_search",
    } <= indexes
    assert has_pending_migrations(db_path) is False


def test_api_returns_503_when_schema_migrations_are_pending(tmp_path):
    db_path = tmp_path / "auctionscan.sqlite3"
    sqlite3.connect(db_path).close()
    client = TestClient(create_app(db_path=str(db_path)))

    response = client.get("/api/health")

    assert response.status_code == 503
    assert "schema is outdated" in response.json()["detail"]
    assert str(db_path) not in response.text
