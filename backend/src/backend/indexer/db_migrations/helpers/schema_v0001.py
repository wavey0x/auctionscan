from __future__ import annotations

import json
import sqlite3

from backend.indexer.observations import OBSERVATION_SCHEMA

CURRENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sync_state (
    chain_id INTEGER PRIMARY KEY,
    network_name TEXT NOT NULL,
    latest_rpc_head INTEGER,
    confirmed_head INTEGER,
    last_confirmed_processed INTEGER,
    last_live_processed INTEGER,
    finality_mode TEXT,
    finality_warning TEXT,
    confirmed_head_hash TEXT,
    confirmed_head_timestamp INTEGER,
    last_confirmed_hash TEXT,
    latest_rpc_head_timestamp INTEGER,
    last_finality_advance_at INTEGER,
    last_reorg_at INTEGER,
    reorg_count INTEGER NOT NULL DEFAULT 0,
    last_success_at INTEGER,
    last_error TEXT,
    discovery_status_json TEXT,
    health TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS tracked_factories (
    chain_id INTEGER NOT NULL,
    factory_address TEXT NOT NULL,
    version TEXT NOT NULL,
    capability_family TEXT NOT NULL,
    discovery_source TEXT NOT NULL,
    start_block INTEGER NOT NULL,
    deploy_block INTEGER,
    deploy_block_source TEXT,
    active_flag INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (chain_id, factory_address)
);

CREATE TABLE IF NOT EXISTS tracked_auctions (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    factory_address TEXT NOT NULL,
    version TEXT NOT NULL,
    capability_family TEXT NOT NULL,
    discovered_block INTEGER NOT NULL,
    discovered_tx_hash TEXT NOT NULL,
    active_flag INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (chain_id, auction_address)
);

CREATE TABLE IF NOT EXISTS chain_logs (
    chain_id INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    tx_index INTEGER NOT NULL,
    log_index INTEGER NOT NULL,
    address TEXT NOT NULL,
    topic0 TEXT,
    topic1 TEXT,
    topic2 TEXT,
    topic3 TEXT,
    data TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    PRIMARY KEY (chain_id, tx_hash, log_index)
);

CREATE TABLE IF NOT EXISTS indexed_blocks (
    chain_id INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    parent_hash TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    PRIMARY KEY (chain_id, block_number)
);

CREATE TABLE IF NOT EXISTS domain_events (
    chain_id INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    tx_index INTEGER NOT NULL,
    log_index INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    address TEXT NOT NULL,
    auction_address TEXT NOT NULL,
    version TEXT NOT NULL,
    capability_family TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    PRIMARY KEY (chain_id, tx_hash, log_index)
);

CREATE TABLE IF NOT EXISTS tokens (
    chain_id INTEGER NOT NULL,
    token_address TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    decimals INTEGER,
    metadata_block INTEGER NOT NULL DEFAULT -1,
    metadata_updated_at INTEGER NOT NULL,
    PRIMARY KEY (chain_id, token_address)
);

CREATE TABLE IF NOT EXISTS address_aliases (
    chain_id INTEGER NOT NULL,
    address TEXT NOT NULL,
    alias_text TEXT,
    checked_at INTEGER,
    PRIMARY KEY (chain_id, address)
);

CREATE TABLE IF NOT EXISTS auctions (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    factory_address TEXT NOT NULL,
    version TEXT NOT NULL,
    capability_family TEXT NOT NULL,
    governance TEXT,
    receiver TEXT,
    want_token TEXT,
    deployment_block INTEGER NOT NULL,
    latest_lifecycle_block INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (chain_id, auction_address)
);

CREATE TABLE IF NOT EXISTS auction_tokens (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    from_token TEXT NOT NULL,
    want_token TEXT,
    currently_enabled INTEGER NOT NULL DEFAULT 0,
    enabled_at INTEGER,
    enabled_at_block INTEGER,
    disabled_at INTEGER,
    disabled_at_block INTEGER,
    latest_lifecycle_block INTEGER NOT NULL,
    PRIMARY KEY (chain_id, auction_address, from_token)
);

CREATE TABLE IF NOT EXISTS auction_current_params (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    param_schema TEXT,
    receiver TEXT,
    minimum_price_raw TEXT,
    starting_price_raw TEXT,
    step_decay_rate_raw TEXT,
    step_duration_raw TEXT,
    auction_length_raw TEXT,
    minimum_price TEXT,
    starting_price TEXT,
    step_decay_percent TEXT,
    step_duration_seconds INTEGER,
    auction_length_seconds INTEGER,
    extra_params_json TEXT,
    last_updated_block INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (chain_id, auction_address)
);

CREATE TABLE IF NOT EXISTS rounds (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    from_token TEXT NOT NULL,
    want_token TEXT,
    status TEXT NOT NULL,
    kicked_at INTEGER NOT NULL,
    scheduled_end_at INTEGER,
    end_at INTEGER,
    settled_at INTEGER,
    initial_available_raw TEXT NOT NULL,
    remaining_available_raw TEXT NOT NULL,
    sold_amount_raw TEXT NOT NULL,
    paid_amount_raw TEXT,
    paid_sold_amount_raw TEXT NOT NULL DEFAULT '0',
    paid_take_count INTEGER NOT NULL DEFAULT 0,
    take_count INTEGER NOT NULL DEFAULT 0,
    last_take_at INTEGER,
    last_take_price_raw TEXT,
    receiver TEXT,
    minimum_price TEXT,
    starting_price TEXT,
    step_decay_percent TEXT,
    step_duration_seconds INTEGER,
    auction_length_seconds INTEGER,
    snapshot_block INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (chain_id, auction_address, round_id)
);

CREATE TABLE IF NOT EXISTS round_param_snapshot (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    from_token TEXT NOT NULL,
    want_token TEXT,
    version TEXT NOT NULL,
    block_hash TEXT,
    snapshot_block INTEGER NOT NULL,
    snapshot_tx_hash TEXT NOT NULL,
    snapshot_log_index INTEGER NOT NULL,
    param_schema TEXT,
    receiver TEXT,
    minimum_price_raw TEXT,
    starting_price_raw TEXT,
    step_decay_rate_raw TEXT,
    step_duration_raw TEXT,
    auction_length_raw TEXT,
    extra_params_json TEXT,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (chain_id, auction_address, round_id)
);

CREATE TABLE IF NOT EXISTS auction_snapshot_facts (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL,
    round_id INTEGER,
    version TEXT NOT NULL,
    block_hash TEXT,
    param_schema TEXT,
    block_number INTEGER NOT NULL,
    tx_hash TEXT NOT NULL,
    log_index INTEGER NOT NULL,
    want_token TEXT,
    governance TEXT,
    receiver TEXT,
    minimum_price_raw TEXT,
    starting_price_raw TEXT,
    step_decay_rate_raw TEXT,
    step_duration_raw TEXT,
    auction_length_raw TEXT,
    extra_params_json TEXT,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (chain_id, tx_hash, log_index)
);

CREATE TABLE IF NOT EXISTS takes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    take_seq INTEGER NOT NULL,
    tx_hash TEXT NOT NULL,
    tx_index INTEGER NOT NULL,
    log_index INTEGER NOT NULL,
    taker TEXT NOT NULL,
    receiver TEXT,
    from_token TEXT NOT NULL,
    want_token TEXT,
    amount_taken_raw TEXT NOT NULL,
    amount_paid_raw TEXT,
    expected_amount_paid_raw TEXT,
    timestamp INTEGER NOT NULL,
    UNIQUE (chain_id, tx_hash, log_index),
    UNIQUE (chain_id, auction_address, round_id, take_seq)
);

CREATE TABLE IF NOT EXISTS pricing_capture_queue (
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
    source_tx_hash TEXT,
    source_log_index INTEGER,
    source_event_name TEXT,
    source_block_number INTEGER,
    source_block_hash TEXT,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER,
    last_error TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pricing_quote_facts (
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
    timeout_ms INTEGER NOT NULL DEFAULT 7000,
    include_route INTEGER NOT NULL DEFAULT 1,
    capture_state TEXT NOT NULL,
    request_id TEXT,
    aggregate_response_json TEXT,
    aggregate_error_json TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pricing_quote_provider_facts (
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
    FOREIGN KEY (quote_fact_id) REFERENCES pricing_quote_facts(id) ON DELETE CASCADE,
    UNIQUE (quote_fact_id, provider_id)
);

CREATE TABLE IF NOT EXISTS pricing_price_facts (
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
    timeout_ms INTEGER NOT NULL DEFAULT 7000,
    capture_state TEXT NOT NULL,
    request_id TEXT,
    aggregate_response_json TEXT,
    aggregate_error_json TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pricing_price_provider_facts (
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
    FOREIGN KEY (price_fact_id) REFERENCES pricing_price_facts(id) ON DELETE CASCADE,
    UNIQUE (price_fact_id, provider_id)
);

CREATE TABLE IF NOT EXISTS taker_summary (
    chain_id INTEGER NOT NULL,
    taker TEXT NOT NULL,
    take_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at INTEGER,
    last_seen_at INTEGER,
    PRIMARY KEY (chain_id, taker)
);

CREATE TABLE IF NOT EXISTS take_pricing (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    take_seq INTEGER NOT NULL,
    canonical_quote_fact_id INTEGER,
    canonical_want_price_fact_id INTEGER,
    amount_taken_raw TEXT NOT NULL,
    actual_paid_raw TEXT,
    expected_paid_raw TEXT,
    market_quote_out_raw TEXT,
    market_quote_out_usd TEXT,
    want_token_price_usd TEXT,
    auction_profit_raw TEXT,
    auction_profit_bps INTEGER,
    auction_profit_usd TEXT,
    priced_volume_usd TEXT,
    pricing_status TEXT NOT NULL,
    provider_success_count INTEGER NOT NULL DEFAULT 0,
    quote_spread_bps INTEGER,
    capture_lag_seconds INTEGER,
    fresh_quote INTEGER NOT NULL DEFAULT 0,
    fresh_want_price INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chain_id, auction_address, round_id, take_seq)
);

CREATE TABLE IF NOT EXISTS take_pricing_source (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    take_seq INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    quote_fact_id INTEGER,
    market_quote_out_raw TEXT,
    market_quote_out_usd TEXT,
    auction_profit_raw TEXT,
    auction_profit_usd TEXT,
    auction_profit_bps INTEGER,
    priced_volume_usd TEXT,
    pricing_status TEXT NOT NULL,
    PRIMARY KEY (chain_id, auction_address, round_id, take_seq, source_id)
);

CREATE TABLE IF NOT EXISTS round_pricing (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    kick_quote_fact_id INTEGER,
    kick_market_quote_out_raw TEXT,
    kick_market_quote_usd TEXT,
    total_actual_paid_raw TEXT,
    total_market_quote_out_raw TEXT,
    paid_usd_take_count INTEGER NOT NULL DEFAULT 0,
    total_actual_paid_usd TEXT,
    total_market_quote_usd TEXT,
    total_auction_profit_usd TEXT,
    total_auction_profit_bps INTEGER,
    priced_take_count INTEGER NOT NULL DEFAULT 0,
    usd_priced_take_count INTEGER NOT NULL DEFAULT 0,
    total_take_count INTEGER NOT NULL DEFAULT 0,
    priced_volume_share TEXT,
    PRIMARY KEY (chain_id, auction_address, round_id)
);

CREATE TABLE IF NOT EXISTS round_pricing_source (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    total_actual_paid_raw TEXT,
    total_market_quote_out_raw TEXT,
    total_actual_paid_usd TEXT,
    total_market_quote_usd TEXT,
    total_auction_profit_usd TEXT,
    total_auction_profit_bps INTEGER,
    priced_take_count INTEGER NOT NULL DEFAULT 0,
    usd_priced_take_count INTEGER NOT NULL DEFAULT 0,
    total_take_count INTEGER NOT NULL DEFAULT 0,
    priced_volume_share TEXT,
    PRIMARY KEY (chain_id, auction_address, round_id, source_id)
);

CREATE TABLE IF NOT EXISTS taker_pricing_summary (
    chain_id INTEGER NOT NULL,
    taker TEXT NOT NULL,
    priced_take_count INTEGER NOT NULL DEFAULT 0,
    total_take_count INTEGER NOT NULL DEFAULT 0,
    paid_usd_take_count INTEGER NOT NULL DEFAULT 0,
    total_actual_paid_usd TEXT,
    total_market_quote_usd TEXT,
    total_taker_profit_usd TEXT,
    avg_taker_profit_usd TEXT,
    priced_volume_usd TEXT NOT NULL DEFAULT '0',
    total_volume_usd_for_share TEXT NOT NULL DEFAULT '0',
    priced_volume_share TEXT,
    first_priced_take_at INTEGER,
    last_priced_take_at INTEGER,
    PRIMARY KEY (chain_id, taker)
);

CREATE INDEX IF NOT EXISTS idx_chain_logs_block ON chain_logs (chain_id, block_number);
CREATE INDEX IF NOT EXISTS idx_indexed_blocks_chain_number ON indexed_blocks (chain_id, block_number);
CREATE INDEX IF NOT EXISTS idx_domain_events_auction ON domain_events (chain_id, auction_address, event_name, block_number, tx_index, log_index);
CREATE INDEX IF NOT EXISTS idx_domain_events_block ON domain_events (chain_id, block_number, tx_index, log_index);
CREATE INDEX IF NOT EXISTS idx_tracked_auctions_factory ON tracked_auctions (chain_id, factory_address);
CREATE INDEX IF NOT EXISTS idx_rounds_lookup ON rounds (chain_id, auction_address, from_token, kicked_at, round_id);
CREATE INDEX IF NOT EXISTS idx_rounds_status_lookup ON rounds (chain_id, status, end_at);
CREATE INDEX IF NOT EXISTS idx_auction_tokens_effective ON auction_tokens (chain_id, auction_address, enabled_at_block, disabled_at_block, from_token);
CREATE INDEX IF NOT EXISTS idx_rounds_take_lookup ON rounds (chain_id, auction_address, from_token, kicked_at, end_at, round_id);
CREATE INDEX IF NOT EXISTS idx_chain_logs_transfer_lookup ON chain_logs (chain_id, topic0, topic1, block_number, address);
CREATE INDEX IF NOT EXISTS idx_takes_round ON takes (chain_id, auction_address, round_id, take_seq);
CREATE INDEX IF NOT EXISTS idx_takes_taker ON takes (chain_id, taker, timestamp);
CREATE INDEX IF NOT EXISTS idx_takes_taker_global
    ON takes (taker, timestamp DESC, chain_id, auction_address);
CREATE INDEX IF NOT EXISTS idx_takes_tx_hash_search
    ON takes (tx_hash COLLATE NOCASE, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_auctions_address_search
    ON auctions (auction_address COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_taker_summary_address_search
    ON taker_summary (taker COLLATE NOCASE, chain_id);
CREATE INDEX IF NOT EXISTS idx_tokens_address_search
    ON tokens (token_address COLLATE NOCASE, chain_id);
CREATE INDEX IF NOT EXISTS idx_round_param_snapshot_tx_hash ON round_param_snapshot (chain_id, snapshot_tx_hash);
CREATE INDEX IF NOT EXISTS idx_round_snapshot_tx_hash_search
    ON round_param_snapshot (snapshot_tx_hash COLLATE NOCASE, snapshot_block DESC);
CREATE INDEX IF NOT EXISTS idx_auction_snapshot_facts_lookup ON auction_snapshot_facts (chain_id, auction_address, snapshot_kind, block_number);
CREATE INDEX IF NOT EXISTS idx_pricing_capture_queue_pending
    ON pricing_capture_queue (chain_id, status, next_attempt_at, priority DESC, created_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pricing_capture_queue_source_entity
    ON pricing_capture_queue (chain_id, source_block_hash, source_tx_hash, source_log_index, entity_kind);
CREATE INDEX IF NOT EXISTS idx_pricing_capture_queue_source_lookup
    ON pricing_capture_queue (chain_id, source_tx_hash, source_log_index);
CREATE INDEX IF NOT EXISTS idx_pricing_quote_facts_lookup
    ON pricing_quote_facts (chain_id, auction_address, round_id, take_seq, context_kind, capture_state, captured_at, id);
CREATE INDEX IF NOT EXISTS idx_pricing_quote_facts_source_lookup
    ON pricing_quote_facts (chain_id, source_tx_hash, source_log_index, source_event_name, captured_at, id);
CREATE INDEX IF NOT EXISTS idx_pricing_price_facts_lookup
    ON pricing_price_facts (chain_id, auction_address, round_id, take_seq, context_kind, price_role, capture_state, captured_at, id);
CREATE INDEX IF NOT EXISTS idx_pricing_price_facts_source_lookup
    ON pricing_price_facts (chain_id, source_tx_hash, source_log_index, source_event_name, captured_at, id);
CREATE INDEX IF NOT EXISTS idx_pricing_quote_provider_fact_id
    ON pricing_quote_provider_facts (quote_fact_id, provider_position);
CREATE INDEX IF NOT EXISTS idx_pricing_price_provider_fact_id
    ON pricing_price_provider_facts (price_fact_id, provider_position);
CREATE INDEX IF NOT EXISTS idx_take_pricing_round
    ON take_pricing (chain_id, auction_address, round_id, take_seq);
CREATE INDEX IF NOT EXISTS idx_take_pricing_source_lookup
    ON take_pricing_source (chain_id, auction_address, round_id, take_seq, source_id);
CREATE INDEX IF NOT EXISTS idx_round_pricing_lookup
    ON round_pricing (chain_id, auction_address, round_id);
CREATE INDEX IF NOT EXISTS idx_round_pricing_source_lookup
    ON round_pricing_source (chain_id, auction_address, round_id, source_id);
CREATE INDEX IF NOT EXISTS idx_taker_pricing_summary_lookup
    ON taker_pricing_summary (chain_id, taker);
"""

def ensure_current_schema(conn) -> None:
    conn.row_factory = sqlite3.Row
    conn.executescript(CURRENT_SCHEMA_SQL)
    conn.executescript(OBSERVATION_SCHEMA)


def _ensure_pricing_fact_columns(conn) -> None:
    _add_column_if_missing(
        conn,
        "pricing_quote_facts",
        "capture_origin",
        "capture_origin TEXT NOT NULL DEFAULT 'native'",
    )
    _add_column_if_missing(
        conn,
        "pricing_price_facts",
        "capture_origin",
        "capture_origin TEXT NOT NULL DEFAULT 'native'",
    )


def _ensure_pricing_source_linkage(conn) -> None:
    source_columns = (
        ("source_tx_hash", "source_tx_hash TEXT"),
        ("source_log_index", "source_log_index INTEGER"),
        ("source_event_name", "source_event_name TEXT"),
        ("source_block_number", "source_block_number INTEGER"),
        ("source_block_hash", "source_block_hash TEXT"),
    )
    for column_name, definition in source_columns:
        _add_column_if_missing(conn, "pricing_capture_queue", column_name, definition)
        _add_column_if_missing(conn, "pricing_quote_facts", column_name, definition)
        _add_column_if_missing(conn, "pricing_price_facts", column_name, definition)

    if _table_exists(conn, "pricing_capture_queue"):
        conn.execute(
            """
            DELETE FROM pricing_capture_queue
             WHERE source_tx_hash IS NULL
                OR source_log_index IS NULL
                OR source_event_name IS NULL
            """
        )
        conn.execute(
            """
            DELETE FROM pricing_capture_queue
             WHERE rowid NOT IN (
                   SELECT MIN(rowid)
                     FROM pricing_capture_queue
                    GROUP BY chain_id, source_block_hash, source_tx_hash, source_log_index, entity_kind
             )
            """
        )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pricing_capture_queue_source_entity
            ON pricing_capture_queue (chain_id, source_block_hash, source_tx_hash, source_log_index, entity_kind)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pricing_capture_queue_source_lookup
            ON pricing_capture_queue (chain_id, source_tx_hash, source_log_index)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pricing_quote_facts_source_lookup
            ON pricing_quote_facts (chain_id, source_tx_hash, source_log_index, source_event_name, captured_at, id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pricing_price_facts_source_lookup
            ON pricing_price_facts (chain_id, source_tx_hash, source_log_index, source_event_name, captured_at, id)
        """
    )

    _backfill_pricing_source_linkage(conn, "pricing_quote_facts")
    _backfill_pricing_source_linkage(conn, "pricing_price_facts")


def _backfill_pricing_source_linkage(conn, table_name: str) -> None:
    if not _table_exists(conn, table_name):
        return
    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT rowid AS migration_rowid,
                   chain_id,
                   auction_address,
                   round_id,
                   take_seq,
                   context_kind,
                   source_tx_hash,
                   source_log_index,
                   source_event_name
              FROM {table_name}
             WHERE source_tx_hash IS NULL
                OR source_log_index IS NULL
                OR source_event_name IS NULL
            """
        ).fetchall()
        for row in rows:
            context_kind = str(row["context_kind"])
            source_tx_hash: str | None = None
            source_log_index: int | None = None
            source_event_name: str | None = None

            if context_kind == "take" and row["take_seq"] is not None:
                take_rows = conn.execute(
                    """
                    SELECT tx_hash, log_index
                      FROM takes
                     WHERE chain_id = ?
                       AND auction_address = ?
                       AND round_id = ?
                       AND take_seq = ?
                    """,
                    (
                        int(row["chain_id"]),
                        row["auction_address"],
                        int(row["round_id"]),
                        int(row["take_seq"]),
                    ),
                ).fetchall()
                if len(take_rows) != 1:
                    continue
                take_row = take_rows[0]
                source_tx_hash = str(take_row["tx_hash"])
                source_log_index = int(take_row["log_index"])
                source_event_name = "Take"
            elif context_kind == "round_kick":
                snapshot_rows = conn.execute(
                    """
                    SELECT snapshot_tx_hash, snapshot_log_index
                      FROM round_param_snapshot
                     WHERE chain_id = ?
                       AND auction_address = ?
                       AND round_id = ?
                    """,
                    (
                        int(row["chain_id"]),
                        row["auction_address"],
                        int(row["round_id"]),
                    ),
                ).fetchall()
                if len(snapshot_rows) != 1:
                    continue
                snapshot_row = snapshot_rows[0]
                source_tx_hash = str(snapshot_row["snapshot_tx_hash"])
                source_log_index = int(snapshot_row["snapshot_log_index"])
                source_event_name = "AuctionKicked"
            else:
                continue

            event_row = conn.execute(
                """
                SELECT block_number, block_hash
                  FROM domain_events
                 WHERE chain_id = ?
                   AND tx_hash = ?
                   AND log_index = ?
                """,
                (
                    int(row["chain_id"]),
                    source_tx_hash,
                    source_log_index,
                ),
            ).fetchone()
            source_block_number = int(event_row["block_number"]) if event_row is not None else None
            source_block_hash = str(event_row["block_hash"]) if event_row is not None else None

            conn.execute(
                f"""
                UPDATE {table_name}
                   SET source_tx_hash = ?,
                       source_log_index = ?,
                       source_event_name = ?,
                       source_block_number = ?,
                       source_block_hash = ?
                 WHERE rowid = ?
                """,
                (
                    source_tx_hash,
                    source_log_index,
                    source_event_name,
                    source_block_number,
                    source_block_hash,
                    int(row["migration_rowid"]),
                ),
            )
    finally:
        conn.row_factory = original_row_factory


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
          FROM sqlite_master
         WHERE type IN ('table', 'view')
           AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _column_names(conn, table_name: str) -> set[str]:
    names: set[str] = set()
    for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall():
        if isinstance(row, sqlite3.Row):
            names.add(str(row["name"]))
        else:
            names.add(str(row[1]))
    return names


def _add_column_if_missing(conn, table_name: str, column_name: str, column_definition: str) -> None:
    if not _table_exists(conn, table_name):
        return
    if column_name in _column_names(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def _json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
