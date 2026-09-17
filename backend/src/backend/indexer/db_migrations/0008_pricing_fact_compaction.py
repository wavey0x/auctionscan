from __future__ import annotations

import hashlib
import json
from typing import Any

from yoyo import step


DEFAULT_TIMEOUT_MS = 7000

QUOTE_PARENT_COLUMNS = (
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
)

PRICE_PARENT_COLUMNS = (
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
)

QUOTE_PROVIDER_COLUMNS = (
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
)

PRICE_PROVIDER_COLUMNS = (
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
)

CREATE_COMPACT_TABLES_SQL = """
CREATE TABLE pricing_quote_facts_compact (
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

CREATE TABLE pricing_quote_provider_facts_compact (
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
    FOREIGN KEY (quote_fact_id) REFERENCES pricing_quote_facts_compact(id) ON DELETE CASCADE,
    UNIQUE (quote_fact_id, provider_id)
);

CREATE TABLE pricing_price_facts_compact (
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

CREATE TABLE pricing_price_provider_facts_compact (
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
    FOREIGN KEY (price_fact_id) REFERENCES pricing_price_facts_compact(id) ON DELETE CASCADE,
    UNIQUE (price_fact_id, provider_id)
);
"""

INDEX_SQL = """
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
"""


def _column_names(conn, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _execute_statements(conn, script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def _fetch_dicts(conn, query: str) -> list[dict[str, Any]]:
    cursor = conn.execute(query)
    names = [str(column[0]) for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _parse_request_params(raw: str, *, table: str, fact_id: int) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid {table}.request_params_json for fact {fact_id}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"non-object {table}.request_params_json for fact {fact_id}")
    return value


def _timeout_ms(request_params: dict[str, Any], *, table: str, fact_id: int) -> int:
    raw = request_params.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    try:
        timeout_ms = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid timeout_ms for {table} fact {fact_id}") from exc
    if timeout_ms < 0:
        raise RuntimeError(f"negative timeout_ms for {table} fact {fact_id}")
    return timeout_ms


def _include_route(request_params: dict[str, Any]) -> int:
    value = request_params.get("include_route", True)
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1):
        return int(value)
    raise RuntimeError("invalid include_route in pricing_quote_facts.request_params_json")


def _insert_row(conn, table: str, columns: tuple[str, ...], values: tuple[Any, ...]) -> None:
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )


def _copy_parent_facts(
    conn,
    *,
    source_table: str,
    target_table: str,
    retained_columns: tuple[str, ...],
    include_route: bool,
) -> list[tuple[int, int, int | None]]:
    rows = _fetch_dicts(conn, f"SELECT * FROM {source_table} ORDER BY id")
    derived: list[tuple[int, int, int | None]] = []
    target_columns = list(retained_columns)
    insert_at = target_columns.index("capture_state")
    target_columns.insert(insert_at, "timeout_ms")
    if include_route:
        target_columns.insert(insert_at + 1, "include_route")
    for row in rows:
        fact_id = int(row["id"])
        request_params = _parse_request_params(
            row["request_params_json"],
            table=source_table,
            fact_id=fact_id,
        )
        timeout_ms = _timeout_ms(request_params, table=source_table, fact_id=fact_id)
        route_value = _include_route(request_params) if include_route else None
        values = [row[column] for column in retained_columns]
        values.insert(insert_at, timeout_ms)
        if include_route:
            values.insert(insert_at + 1, route_value)
        _insert_row(conn, target_table, tuple(target_columns), tuple(values))
        derived.append((fact_id, timeout_ms, route_value))
    return derived


def _copy_provider_facts(
    conn,
    *,
    source_table: str,
    target_table: str,
    retained_columns: tuple[str, ...],
) -> None:
    columns = ", ".join(retained_columns)
    conn.execute(
        f"INSERT INTO {target_table} ({columns}) SELECT {columns} FROM {source_table} ORDER BY id"
    )


def _tuples(conn, table: str, columns: tuple[str, ...]) -> list[tuple[Any, ...]]:
    selected = ", ".join(columns)
    return [tuple(row) for row in conn.execute(f"SELECT {selected} FROM {table} ORDER BY id").fetchall()]


def _raw_hashes(conn, table: str) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        f"SELECT id, aggregate_response_json, aggregate_error_json FROM {table} ORDER BY id"
    ).fetchall()
    return [
        (
            int(row[0]),
            hashlib.sha256((row[1] or "").encode()).hexdigest(),
            hashlib.sha256((row[2] or "").encode()).hexdigest(),
        )
        for row in rows
    ]


def _json_or_none(raw: str | None, *, label: str) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid JSON in {label}") from exc


def _provider_payloads(aggregate: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(aggregate, dict):
        return {}
    providers = aggregate.get("providers")
    if isinstance(providers, dict):
        return {
            str(provider_id): payload
            for provider_id, payload in providers.items()
            if isinstance(payload, dict)
        }
    legacy_rows = aggregate.get("legacy_provider_rows")
    if not isinstance(legacy_rows, list):
        return {}
    return {
        str(payload["source"]): payload
        for payload in legacy_rows
        if isinstance(payload, dict) and payload.get("source") is not None
    }


def _route_from_provider_payload(payload: dict[str, Any] | None) -> Any:
    if payload is None:
        return None
    if "route" in payload:
        return payload.get("route")
    routing_path = payload.get("routing_path")
    if not isinstance(routing_path, str):
        return routing_path
    try:
        return json.loads(routing_path)
    except ValueError:
        return routing_path


def _validate_provider_raw_reconstruction(
    conn,
    *,
    parent_table: str,
    provider_table: str,
    fact_id_column: str,
    has_route: bool,
) -> None:
    route_select = ", p.route_json" if has_route else ""
    rows = _fetch_dicts(
        conn,
        f"""
        SELECT p.id, p.provider_id, p.raw_provider_payload_json,
               f.aggregate_response_json{route_select}
          FROM {provider_table} p
          JOIN {parent_table} f ON f.id = p.{fact_id_column}
         ORDER BY p.id
        """,
    )
    for row in rows:
        aggregate = _json_or_none(
            row["aggregate_response_json"],
            label=f"{parent_table}.aggregate_response_json",
        )
        derived_payload = _provider_payloads(aggregate).get(str(row["provider_id"]))
        legacy_payload = _json_or_none(
            row["raw_provider_payload_json"],
            label=f"{provider_table}.raw_provider_payload_json",
        )
        if legacy_payload != derived_payload:
            raise RuntimeError(
                f"provider payload cannot be reconstructed for {provider_table} row {row['id']}"
            )
        if has_route:
            legacy_route = _json_or_none(
                row["route_json"],
                label=f"{provider_table}.route_json",
            )
            derived_route = _route_from_provider_payload(derived_payload)
            if legacy_route != derived_route:
                raise RuntimeError(
                    f"provider route cannot be reconstructed for {provider_table} row {row['id']}"
                )


def _validate_copy(
    conn,
    *,
    source_table: str,
    target_table: str,
    retained_columns: tuple[str, ...],
) -> None:
    source_rows = _tuples(conn, source_table, retained_columns)
    target_rows = _tuples(conn, target_table, retained_columns)
    if source_rows != target_rows:
        raise RuntimeError(f"pricing fact compaction changed retained rows for {source_table}")


def _validate_derived_columns(
    conn,
    *,
    target_table: str,
    expected: list[tuple[int, int, int | None]],
    include_route: bool,
) -> None:
    columns = "id, timeout_ms, include_route" if include_route else "id, timeout_ms, NULL"
    actual = [tuple(row) for row in conn.execute(f"SELECT {columns} FROM {target_table} ORDER BY id")]
    if actual != expected:
        raise RuntimeError(f"pricing fact compaction changed request scalars for {target_table}")


def compact_pricing_facts(conn) -> None:
    quote_columns = _column_names(conn, "pricing_quote_facts")
    price_columns = _column_names(conn, "pricing_price_facts")
    quote_provider_columns = _column_names(conn, "pricing_quote_provider_facts")
    price_provider_columns = _column_names(conn, "pricing_price_provider_facts")

    removed_quote_columns = {
        "provider_order_json",
        "request_params_json",
        "upstream_selected_quote_json",
        "upstream_summary_json",
        "vault_context_json",
    }
    removed_price_columns = {
        "provider_order_json",
        "request_params_json",
        "upstream_selected_price_json",
        "upstream_summary_json",
        "vault_context_json",
    }
    compact = (
        "timeout_ms" in quote_columns
        and "include_route" in quote_columns
        and removed_quote_columns.isdisjoint(quote_columns)
        and "timeout_ms" in price_columns
        and removed_price_columns.isdisjoint(price_columns)
        and "raw_provider_payload_json" not in quote_provider_columns
        and "route_json" not in quote_provider_columns
        and "raw_provider_payload_json" not in price_provider_columns
    )
    if compact:
        _execute_statements(conn, INDEX_SQL)
        return

    legacy = (
        "request_params_json" in quote_columns
        and "provider_order_json" in quote_columns
        and "request_params_json" in price_columns
        and "provider_order_json" in price_columns
        and "raw_provider_payload_json" in quote_provider_columns
        and "route_json" in quote_provider_columns
        and "raw_provider_payload_json" in price_provider_columns
    )
    if not legacy:
        raise RuntimeError("pricing fact tables are neither legacy nor compact")

    _validate_provider_raw_reconstruction(
        conn,
        parent_table="pricing_quote_facts",
        provider_table="pricing_quote_provider_facts",
        fact_id_column="quote_fact_id",
        has_route=True,
    )
    _validate_provider_raw_reconstruction(
        conn,
        parent_table="pricing_price_facts",
        provider_table="pricing_price_provider_facts",
        fact_id_column="price_fact_id",
        has_route=False,
    )

    _execute_statements(conn, CREATE_COMPACT_TABLES_SQL)
    quote_derived = _copy_parent_facts(
        conn,
        source_table="pricing_quote_facts",
        target_table="pricing_quote_facts_compact",
        retained_columns=QUOTE_PARENT_COLUMNS,
        include_route=True,
    )
    price_derived = _copy_parent_facts(
        conn,
        source_table="pricing_price_facts",
        target_table="pricing_price_facts_compact",
        retained_columns=PRICE_PARENT_COLUMNS,
        include_route=False,
    )
    _copy_provider_facts(
        conn,
        source_table="pricing_quote_provider_facts",
        target_table="pricing_quote_provider_facts_compact",
        retained_columns=QUOTE_PROVIDER_COLUMNS,
    )
    _copy_provider_facts(
        conn,
        source_table="pricing_price_provider_facts",
        target_table="pricing_price_provider_facts_compact",
        retained_columns=PRICE_PROVIDER_COLUMNS,
    )

    _validate_copy(
        conn,
        source_table="pricing_quote_facts",
        target_table="pricing_quote_facts_compact",
        retained_columns=QUOTE_PARENT_COLUMNS,
    )
    _validate_copy(
        conn,
        source_table="pricing_price_facts",
        target_table="pricing_price_facts_compact",
        retained_columns=PRICE_PARENT_COLUMNS,
    )
    _validate_copy(
        conn,
        source_table="pricing_quote_provider_facts",
        target_table="pricing_quote_provider_facts_compact",
        retained_columns=QUOTE_PROVIDER_COLUMNS,
    )
    _validate_copy(
        conn,
        source_table="pricing_price_provider_facts",
        target_table="pricing_price_provider_facts_compact",
        retained_columns=PRICE_PROVIDER_COLUMNS,
    )
    _validate_derived_columns(
        conn,
        target_table="pricing_quote_facts_compact",
        expected=quote_derived,
        include_route=True,
    )
    _validate_derived_columns(
        conn,
        target_table="pricing_price_facts_compact",
        expected=price_derived,
        include_route=False,
    )
    if _raw_hashes(conn, "pricing_quote_facts") != _raw_hashes(conn, "pricing_quote_facts_compact"):
        raise RuntimeError("pricing quote raw payload hashes changed during compaction")
    if _raw_hashes(conn, "pricing_price_facts") != _raw_hashes(conn, "pricing_price_facts_compact"):
        raise RuntimeError("pricing price raw payload hashes changed during compaction")

    orphan_counts = (
        conn.execute(
            """
            SELECT COUNT(*)
              FROM pricing_quote_provider_facts_compact p
              LEFT JOIN pricing_quote_facts_compact f ON f.id = p.quote_fact_id
             WHERE f.id IS NULL
            """
        ).fetchone()[0],
        conn.execute(
            """
            SELECT COUNT(*)
              FROM pricing_price_provider_facts_compact p
              LEFT JOIN pricing_price_facts_compact f ON f.id = p.price_fact_id
             WHERE f.id IS NULL
            """
        ).fetchone()[0],
    )
    if orphan_counts != (0, 0):
        raise RuntimeError("pricing fact compaction created orphan provider rows")

    _execute_statements(
        conn,
        """
        DROP TABLE pricing_quote_provider_facts;
        DROP TABLE pricing_price_provider_facts;
        DROP TABLE pricing_quote_facts;
        DROP TABLE pricing_price_facts;
        ALTER TABLE pricing_quote_facts_compact RENAME TO pricing_quote_facts;
        ALTER TABLE pricing_quote_provider_facts_compact RENAME TO pricing_quote_provider_facts;
        ALTER TABLE pricing_price_facts_compact RENAME TO pricing_price_facts;
        ALTER TABLE pricing_price_provider_facts_compact RENAME TO pricing_price_provider_facts;
        """
    )
    _execute_statements(conn, INDEX_SQL)
    foreign_key_violations = [
        *conn.execute("PRAGMA foreign_key_check(pricing_quote_provider_facts)").fetchall(),
        *conn.execute("PRAGMA foreign_key_check(pricing_price_provider_facts)").fetchall(),
    ]
    if foreign_key_violations:
        raise RuntimeError("pricing fact compaction left provider foreign-key violations")


steps = [step(compact_pricing_facts)]
