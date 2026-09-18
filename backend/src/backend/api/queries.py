from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from backend.indexer.types import normalize_address
from backend.indexer.versioning import normalize_version_filters, version_sort_index

_CONFIRMED_CASE = """CASE
                   WHEN ss.last_confirmed_processed IS NOT NULL
                        AND e.block_number <= ss.last_confirmed_processed
                        THEN 1
                   ELSE 0
               END AS confirmed"""

_CONFIRMED_JOIN = """LEFT JOIN sync_state ss
            ON ss.chain_id = t.chain_id"""

_TX_HASH_PATTERN = re.compile(r"^(?:0x)?[0-9a-f]{64}$")


def _activity_expr() -> str:
    return "COALESCE(r.last_take_at, r.end_at, r.kicked_at)"


def normalize_tx_hash_query(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if not _TX_HASH_PATTERN.fullmatch(text):
        return None
    return text if text.startswith("0x") else f"0x{text}"


def _round_from_clause() -> str:
    return """
        FROM rounds r
        JOIN auctions a
          ON a.chain_id = r.chain_id
         AND a.auction_address = r.auction_address
        LEFT JOIN round_pricing rp
          ON rp.chain_id = r.chain_id
         AND rp.auction_address = r.auction_address
         AND rp.round_id = r.round_id
        LEFT JOIN round_param_snapshot rs
          ON rs.chain_id = r.chain_id
         AND rs.auction_address = r.auction_address
         AND rs.round_id = r.round_id
        JOIN domain_events kick
          ON kick.chain_id = rs.chain_id
         AND kick.tx_hash = rs.snapshot_tx_hash
         AND kick.log_index = rs.snapshot_log_index
        LEFT JOIN address_aliases ra
          ON ra.chain_id = r.chain_id
         AND ra.address = r.receiver
        LEFT JOIN tokens ft
          ON ft.chain_id = r.chain_id
         AND ft.token_address = r.from_token
        LEFT JOIN tokens wt
          ON wt.chain_id = r.chain_id
         AND wt.token_address = r.want_token
    """


def _round_select_clause() -> str:
    return f"""
        SELECT r.chain_id,
               r.auction_address,
               r.round_id,
               r.status,
               r.kicked_at,
               r.scheduled_end_at,
               r.end_at,
               r.last_take_at,
               {_activity_expr()} AS activity_at,
               r.take_count,
               r.sold_amount_raw,
               r.paid_amount_raw,
               r.paid_sold_amount_raw,
               r.paid_take_count,
               r.last_take_price_raw,
               rp.kick_market_quote_out_raw,
               rp.kick_market_quote_usd,
               rp.total_actual_paid_usd,
               rp.total_market_quote_usd,
               rp.total_auction_profit_usd,
               rp.total_auction_profit_bps,
               rp.priced_take_count,
               rp.usd_priced_take_count,
               rp.paid_usd_take_count,
               rp.total_take_count,
               rp.priced_volume_share,
               r.remaining_available_raw,
               r.initial_available_raw,
               r.receiver,
               ra.alias_text AS receiver_name,
               r.minimum_price,
               r.starting_price,
               r.step_decay_percent,
               r.step_duration_seconds,
               r.auction_length_seconds,
               r.from_token,
               r.want_token,
               r.snapshot_block,
               a.version,
               rs.snapshot_tx_hash,
               rs.snapshot_log_index,
               kick.block_hash AS snapshot_block_hash,
               ft.symbol AS from_token_symbol,
               ft.name AS from_token_name,
               ft.decimals AS from_token_decimals,
               wt.symbol AS want_token_symbol,
               wt.name AS want_token_name,
               wt.decimals AS want_token_decimals
        {_round_from_clause()}
    """


def _token_term_clause(alias: str, term: str) -> tuple[str, list[str]]:
    lowered = term.lower()
    params = [f"%{lowered}%", f"%{lowered}%"]
    clause = f"(LOWER(COALESCE({alias}.symbol, '')) LIKE ? OR LOWER(COALESCE({alias}.name, '')) LIKE ?"
    if lowered.startswith("0x"):
        clause += f" OR LOWER(COALESCE({alias}.token_address, '')) LIKE ?"
        params.append(f"{lowered}%")
    clause += ")"
    return clause, params


def _status_clause(status: str | None) -> tuple[str, list[Any]]:
    if not status or status == "all":
        return "", []
    if status == "active":
        return " AND r.status = ?", ["live"]
    if status == "completed":
        return " AND r.status IN (?, ?, ?)", ["sold_out", "expired", "settled"]
    return " AND r.status = ?", [status]


def _time_window_clause(time_window: str | None) -> tuple[str, list[Any]]:
    if not time_window or time_window == "all":
        return "", []
    windows = {
        "24h": 24 * 60 * 60,
        "7d": 7 * 24 * 60 * 60,
        "30d": 30 * 24 * 60 * 60,
        "90d": 90 * 24 * 60 * 60,
    }
    duration = windows.get(time_window)
    if duration is None:
        return "", []
    cutoff = int(time.time()) - duration
    return f" AND {_activity_expr()} >= ?", [cutoff]


def _version_clause(column: str, versions: list[str] | tuple[str, ...] | None) -> tuple[str, list[Any]]:
    normalized = normalize_version_filters(list(versions) if versions else None)
    if not normalized:
        return "", []
    placeholders = ", ".join("?" for _ in normalized)
    return f" AND LOWER({column}) IN ({placeholders})", normalized


def build_round_filters(
    *,
    chain_id: int | None,
    auction_address: str | None,
    round_id: int | None,
    status: str | None,
    pair: str | None,
    tx_hash: str | None,
    time_window: str | None,
    versions: list[str] | tuple[str, ...] | None,
) -> tuple[str, list[Any]]:
    clauses = [" WHERE 1 = 1"]
    params: list[Any] = []
    if chain_id is not None:
        clauses.append(" AND r.chain_id = ?")
        params.append(chain_id)
    if auction_address:
        clauses.append(" AND r.auction_address = ?")
        params.append(normalize_address(auction_address))
    if round_id is not None:
        clauses.append(" AND r.round_id = ?")
        params.append(round_id)
    if tx_hash:
        lowered_tx_hash = tx_hash.lower()
        clauses.append(
            """
             AND (
                   LOWER(COALESCE(rs.snapshot_tx_hash, '')) = ?
                OR EXISTS (
                       SELECT 1
                         FROM takes tk
                        WHERE tk.chain_id = r.chain_id
                          AND tk.auction_address = r.auction_address
                          AND tk.round_id = r.round_id
                          AND LOWER(tk.tx_hash) = ?
                   )
             )
            """
        )
        params.extend([lowered_tx_hash, lowered_tx_hash])
    status_sql, status_params = _status_clause(status)
    clauses.append(status_sql)
    params.extend(status_params)
    time_sql, time_params = _time_window_clause(time_window)
    clauses.append(time_sql)
    params.extend(time_params)
    version_sql, version_params = _version_clause("a.version", versions)
    clauses.append(version_sql)
    params.extend(version_params)
    if pair:
        parts = [item.strip() for item in pair.split("/") if item.strip()]
        if len(parts) >= 2:
            left_sql, left_params = _token_term_clause("ft", parts[0])
            right_sql, right_params = _token_term_clause("wt", parts[1])
            clauses.append(f" AND {left_sql} AND {right_sql}")
            params.extend(left_params)
            params.extend(right_params)
        else:
            token_sql, token_params = _token_term_clause("ft", parts[0])
            want_sql, want_params = _token_term_clause("wt", parts[0])
            clauses.append(f" AND ({token_sql} OR {want_sql})")
            params.extend(token_params)
            params.extend(want_params)
    return "".join(clauses), params


def list_tokens(conn: sqlite3.Connection, *, chain_id: int | None) -> list[sqlite3.Row]:
    sql = """
        SELECT chain_id, token_address, symbol, name, decimals
          FROM tokens
         WHERE (? IS NULL OR chain_id = ?)
         ORDER BY chain_id ASC, LOWER(COALESCE(symbol, token_address)) ASC, token_address ASC
    """
    return list(conn.execute(sql, (chain_id, chain_id)).fetchall())


def list_rounds(
    conn: sqlite3.Connection,
    *,
    chain_id: int | None,
    auction_address: str | None,
    round_id: int | None,
    status: str | None,
    pair: str | None,
    tx_hash: str | None,
    time_window: str | None,
    versions: list[str] | tuple[str, ...] | None,
    page: int,
    limit: int,
) -> tuple[int, list[sqlite3.Row]]:
    where_sql, params = build_round_filters(
        chain_id=chain_id,
        auction_address=auction_address,
        round_id=round_id,
        status=status,
        pair=pair,
        tx_hash=tx_hash,
        time_window=time_window,
        versions=versions,
    )
    count_sql = f"SELECT COUNT(*) AS count {_round_from_clause()} {where_sql}"
    total = int(conn.execute(count_sql, params).fetchone()["count"])
    query_sql = _round_select_clause() + where_sql + " ORDER BY r.kicked_at DESC, r.round_id DESC LIMIT ? OFFSET ?"
    rows = list(conn.execute(query_sql, (*params, limit, (page - 1) * limit)).fetchall())
    return total, rows


def get_round(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
    round_id: int,
) -> sqlite3.Row | None:
    sql = (
        _round_select_clause()
        + """
        WHERE r.chain_id = ?
          AND r.auction_address = ?
          AND r.round_id = ?
        LIMIT 1
        """
    )
    return conn.execute(
        sql,
        (chain_id, normalize_address(auction_address), round_id),
    ).fetchone()


def get_auction(conn: sqlite3.Connection, *, chain_id: int, auction_address: str) -> sqlite3.Row | None:
    sql = """
        SELECT a.chain_id,
               a.auction_address,
               a.receiver,
               aa.alias_text AS receiver_name,
               a.want_token,
               a.version,
               ac.receiver AS current_receiver,
               ac.minimum_price,
               ac.starting_price,
               ac.step_decay_percent,
               ac.step_duration_seconds,
               ac.auction_length_seconds,
               wt.symbol AS want_token_symbol,
               wt.name AS want_token_name,
               wt.decimals AS want_token_decimals
          FROM auctions a
          LEFT JOIN auction_current_params ac
            ON ac.chain_id = a.chain_id
           AND ac.auction_address = a.auction_address
          LEFT JOIN address_aliases aa
            ON aa.chain_id = a.chain_id
           AND aa.address = COALESCE(ac.receiver, a.receiver)
          LEFT JOIN tokens wt
            ON wt.chain_id = a.chain_id
           AND wt.token_address = a.want_token
         WHERE a.chain_id = ? AND a.auction_address = ?
    """
    return conn.execute(sql, (chain_id, normalize_address(auction_address))).fetchone()


def list_auction_versions(conn: sqlite3.Connection, *, chain_id: int | None) -> list[sqlite3.Row]:
    sql = """
        SELECT a.version,
               COUNT(DISTINCT a.chain_id || ':' || a.auction_address) AS auction_count,
               COUNT(r.round_id) AS round_count
          FROM auctions a
          LEFT JOIN rounds r
            ON r.chain_id = a.chain_id
           AND r.auction_address = a.auction_address
         WHERE (? IS NULL OR a.chain_id = ?)
           AND a.version IS NOT NULL
           AND a.version != ''
         GROUP BY a.version
    """
    rows = list(conn.execute(sql, (chain_id, chain_id)).fetchall())
    return sorted(rows, key=lambda row: version_sort_index(row["version"]))


def list_auctions(
    conn: sqlite3.Connection,
    *,
    chain_id: int | None,
    versions: list[str] | tuple[str, ...] | None,
    page: int,
    limit: int,
) -> tuple[int, list[sqlite3.Row]]:
    clauses = [" WHERE 1 = 1"]
    params: list[Any] = []
    if chain_id is not None:
        clauses.append(" AND a.chain_id = ?")
        params.append(chain_id)
    version_sql, version_params = _version_clause("a.version", versions)
    clauses.append(version_sql)
    params.extend(version_params)
    where_sql = "".join(clauses)
    count_sql = f"SELECT COUNT(*) AS count FROM auctions a {where_sql}"
    total = int(conn.execute(count_sql, params).fetchone()["count"])
    sql = f"""
        WITH round_rollup AS (
            SELECT chain_id,
                   auction_address,
                   COUNT(*) AS total_rounds,
                   COALESCE(SUM(take_count), 0) AS total_takes,
                   MAX(COALESCE(last_take_at, end_at, kicked_at)) AS latest_activity_at
              FROM rounds
             GROUP BY chain_id, auction_address
        )
        SELECT a.chain_id,
               a.auction_address,
               COALESCE(ac.receiver, a.receiver) AS receiver,
               aa.alias_text AS receiver_name,
               a.want_token,
               a.version,
               wt.symbol AS want_token_symbol,
               wt.name AS want_token_name,
               wt.decimals AS want_token_decimals,
               COALESCE(rr.total_rounds, 0) AS total_rounds,
               COALESCE(rr.total_takes, 0) AS total_takes,
               rr.latest_activity_at
          FROM auctions a
          LEFT JOIN auction_current_params ac
            ON ac.chain_id = a.chain_id
           AND ac.auction_address = a.auction_address
          LEFT JOIN round_rollup rr
            ON rr.chain_id = a.chain_id
           AND rr.auction_address = a.auction_address
          LEFT JOIN address_aliases aa
            ON aa.chain_id = a.chain_id
           AND aa.address = COALESCE(ac.receiver, a.receiver)
          LEFT JOIN tokens wt
            ON wt.chain_id = a.chain_id
           AND wt.token_address = a.want_token
        {where_sql}
         ORDER BY COALESCE(rr.latest_activity_at, 0) DESC,
                  a.chain_id ASC,
                  a.auction_address ASC
         LIMIT ? OFFSET ?
    """
    rows = list(conn.execute(sql, (*params, limit, (page - 1) * limit)).fetchall())
    return total, rows


def list_auction_from_tokens(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
) -> list[sqlite3.Row]:
    sql = """
        SELECT DISTINCT at.from_token AS token_address,
               t.symbol,
               t.name,
               t.decimals
          FROM auction_tokens at
          LEFT JOIN tokens t
            ON t.chain_id = at.chain_id
           AND t.token_address = at.from_token
         WHERE at.chain_id = ? AND at.auction_address = ?
         ORDER BY at.currently_enabled DESC, LOWER(COALESCE(t.symbol, at.from_token)) ASC
    """
    return list(conn.execute(sql, (chain_id, normalize_address(auction_address))).fetchall())


def get_auction_activity(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
) -> dict[str, Any]:
    auction_norm = normalize_address(auction_address)
    round_rows = conn.execute(
        """
        SELECT paid_amount_raw, paid_take_count, take_count
          FROM rounds
         WHERE chain_id = ? AND auction_address = ?
        """,
        (chain_id, auction_norm),
    ).fetchall()
    total_paid_raw = sum(int(row["paid_amount_raw"] or 0) for row in round_rows)
    paid_take_count = sum(int(row["paid_take_count"]) for row in round_rows)
    total_takes = sum(int(row["take_count"]) for row in round_rows)
    total_rounds = len(round_rows)
    participant_row = conn.execute(
        """
        SELECT COUNT(DISTINCT taker) AS count
          FROM takes
         WHERE chain_id = ? AND auction_address = ?
        """,
        (chain_id, auction_norm),
    ).fetchone()
    return {
        "total_paid_raw": str(total_paid_raw) if paid_take_count else None,
        "paid_take_count": paid_take_count,
        "total_takes": total_takes,
        "total_rounds": total_rounds,
        "total_participants": int(participant_row["count"]),
    }


def list_auction_rounds(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
    round_id: int | None,
    limit: int,
) -> list[sqlite3.Row]:
    where_sql, params = build_round_filters(
        chain_id=chain_id,
        auction_address=auction_address,
        round_id=round_id,
        status=None,
        pair=None,
        tx_hash=None,
        time_window=None,
        versions=None,
    )
    sql = _round_select_clause() + where_sql + " ORDER BY r.round_id DESC LIMIT ?"
    return list(conn.execute(sql, (*params, limit)).fetchall())


def list_auction_takes(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
    round_id: int | None,
    limit: int,
) -> list[sqlite3.Row]:
    sql = f"""
        SELECT t.chain_id,
               t.auction_address,
               t.round_id,
               t.take_seq,
               t.taker,
               t.receiver,
               ra.alias_text AS receiver_name,
               t.from_token,
               t.want_token,
               t.amount_taken_raw,
               t.amount_paid_raw,
               t.expected_amount_paid_raw,
               tp.market_quote_out_raw,
               tp.market_quote_out_usd,
               tp.priced_volume_usd,
               tp.want_token_price_usd,
               tp.auction_profit_raw,
               tp.auction_profit_bps,
               tp.auction_profit_usd,
               tp.pricing_status,
               tp.provider_success_count,
               tp.quote_spread_bps,
               t.timestamp,
               t.tx_hash,
               e.block_number,
               e.block_hash,
               t.log_index,
               kick.block_hash AS snapshot_block_hash,
               rs.snapshot_tx_hash,
               rs.snapshot_log_index,
               {_CONFIRMED_CASE},
               ft.symbol AS from_token_symbol,
               ft.name AS from_token_name,
               ft.decimals AS from_token_decimals,
               wt.symbol AS to_token_symbol,
               wt.name AS to_token_name,
               wt.decimals AS to_token_decimals
          FROM takes t
          JOIN domain_events e
            ON e.chain_id = t.chain_id
           AND e.tx_hash = t.tx_hash
           AND e.log_index = t.log_index

          JOIN round_param_snapshot rs
            ON rs.chain_id = t.chain_id AND rs.auction_address = t.auction_address AND rs.round_id = t.round_id
          JOIN domain_events kick
            ON kick.chain_id = rs.chain_id AND kick.tx_hash = rs.snapshot_tx_hash AND kick.log_index = rs.snapshot_log_index
          {_CONFIRMED_JOIN}
          LEFT JOIN take_pricing tp
            ON tp.chain_id = t.chain_id
           AND tp.auction_address = t.auction_address
           AND tp.round_id = t.round_id
           AND tp.take_seq = t.take_seq
          LEFT JOIN address_aliases ra
            ON ra.chain_id = t.chain_id
           AND ra.address = t.receiver
          LEFT JOIN tokens ft
            ON ft.chain_id = t.chain_id
           AND ft.token_address = t.from_token
          LEFT JOIN tokens wt
            ON wt.chain_id = t.chain_id
           AND wt.token_address = t.want_token
         WHERE t.chain_id = ?
           AND t.auction_address = ?
           AND (? IS NULL OR t.round_id = ?)
         ORDER BY t.timestamp DESC, t.take_seq DESC
         LIMIT ?
    """
    return list(
        conn.execute(
            sql,
            (
                chain_id,
                normalize_address(auction_address),
                round_id,
                round_id,
                limit,
            ),
        ).fetchall()
    )


def get_take(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
    round_id: int,
    take_seq: int,
) -> sqlite3.Row | None:
    sql = f"""
        SELECT t.chain_id,
               t.auction_address,
               t.round_id,
               t.take_seq,
               t.taker,
               t.receiver,
               ra.alias_text AS receiver_name,
               t.from_token,
               t.want_token,
               t.amount_taken_raw,
               t.amount_paid_raw,
               t.expected_amount_paid_raw,
               tp.market_quote_out_raw,
               tp.market_quote_out_usd,
               tp.priced_volume_usd,
               tp.want_token_price_usd,
               tp.auction_profit_raw,
               tp.auction_profit_bps,
               tp.auction_profit_usd,
               tp.pricing_status,
               tp.provider_success_count,
               tp.quote_spread_bps,
               t.timestamp,
               t.tx_hash,
               e.block_number,
               e.block_hash,
               t.log_index,
               kick.block_hash AS snapshot_block_hash,
               rs.snapshot_tx_hash,
               rs.snapshot_log_index,
               {_CONFIRMED_CASE},
               ft.symbol AS from_token_symbol,
               ft.name AS from_token_name,
               ft.decimals AS from_token_decimals,
               wt.symbol AS to_token_symbol,
               wt.name AS to_token_name,
               wt.decimals AS to_token_decimals
          FROM takes t
          JOIN domain_events e
            ON e.chain_id = t.chain_id
           AND e.tx_hash = t.tx_hash
           AND e.log_index = t.log_index

          JOIN round_param_snapshot rs
            ON rs.chain_id = t.chain_id AND rs.auction_address = t.auction_address AND rs.round_id = t.round_id
          JOIN domain_events kick
            ON kick.chain_id = rs.chain_id AND kick.tx_hash = rs.snapshot_tx_hash AND kick.log_index = rs.snapshot_log_index
          {_CONFIRMED_JOIN}
          LEFT JOIN take_pricing tp
            ON tp.chain_id = t.chain_id
           AND tp.auction_address = t.auction_address
           AND tp.round_id = t.round_id
           AND tp.take_seq = t.take_seq
          LEFT JOIN address_aliases ra
            ON ra.chain_id = t.chain_id
           AND ra.address = t.receiver
          LEFT JOIN tokens ft
            ON ft.chain_id = t.chain_id
           AND ft.token_address = t.from_token
          LEFT JOIN tokens wt
            ON wt.chain_id = t.chain_id
           AND wt.token_address = t.want_token
         WHERE t.chain_id = ?
           AND t.auction_address = ?
           AND t.round_id = ?
           AND t.take_seq = ?
    """
    return conn.execute(
        sql,
        (chain_id, normalize_address(auction_address), round_id, take_seq),
    ).fetchone()


def load_sync_state(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM sync_state ORDER BY chain_id ASC").fetchall())


def load_as_of(conn: sqlite3.Connection) -> dict[int, dict]:
    rows = conn.execute("""
        SELECT s.chain_id, s.last_live_processed AS indexed_block,
               b.block_hash AS indexed_block_hash, b.timestamp AS indexed_timestamp,
               s.last_confirmed_processed AS confirmed_block,
               s.last_confirmed_hash AS confirmed_block_hash, s.finality_mode
          FROM sync_state s LEFT JOIN indexed_blocks b
            ON b.chain_id = s.chain_id AND b.block_number = s.last_live_processed
    """).fetchall()
    return {int(row["chain_id"]): {key: row[key] for key in row.keys() if key != "chain_id"} for row in rows}


def list_take_pricing_sources_for_keys(
    conn: sqlite3.Connection,
    *,
    take_keys: list[tuple[int, str, int, int]],
) -> list[sqlite3.Row]:
    if not take_keys:
        return []
    values_sql = ",".join("(?, ?, ?, ?)" for _ in take_keys)
    params: list[Any] = []
    for chain_id, auction_address, round_id, take_seq in take_keys:
        params.extend([chain_id, normalize_address(auction_address), round_id, take_seq])
    return list(
        conn.execute(
            f"""
            WITH target(chain_id, auction_address, round_id, take_seq) AS (
                VALUES {values_sql}
            )
            SELECT source.*
              FROM take_pricing_source source
              JOIN target
                ON target.chain_id = source.chain_id
               AND target.auction_address = source.auction_address
               AND target.round_id = source.round_id
               AND target.take_seq = source.take_seq
             ORDER BY source.chain_id ASC,
                      source.auction_address ASC,
                      source.round_id ASC,
                      source.take_seq ASC,
                      source.source_id ASC
            """,
            tuple(params),
        ).fetchall()
    )


def list_round_pricing_sources(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
    round_id: int,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT *
              FROM round_pricing_source
             WHERE chain_id = ?
               AND auction_address = ?
               AND round_id = ?
             ORDER BY source_id ASC
            """,
            (chain_id, normalize_address(auction_address), round_id),
        ).fetchall()
    )


def list_take_quote_facts(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
    round_id: int,
    take_seq: int,
) -> list[sqlite3.Row]:
    sql = """
        SELECT q.*,
               t.auction_address AS current_auction_address,
               t.round_id AS current_round_id,
               t.take_seq AS current_take_seq
          FROM pricing_quote_facts q
          JOIN takes t
            ON t.chain_id = q.chain_id
           AND t.tx_hash = q.source_tx_hash
           AND t.log_index = q.source_log_index
         WHERE q.chain_id = ?
           AND t.auction_address = ?
           AND t.round_id = ?
           AND t.take_seq = ?
           AND q.context_kind = 'take'
         ORDER BY q.captured_at ASC, q.id ASC
    """
    return list(
        conn.execute(
            sql,
            (chain_id, normalize_address(auction_address), round_id, take_seq),
        ).fetchall()
    )


def list_take_quote_provider_facts(
    conn: sqlite3.Connection,
    *,
    quote_fact_ids: list[int],
) -> list[sqlite3.Row]:
    if not quote_fact_ids:
        return []
    placeholders = ",".join("?" for _ in quote_fact_ids)
    sql = f"""
        SELECT *
          FROM pricing_quote_provider_facts
         WHERE quote_fact_id IN ({placeholders})
         ORDER BY quote_fact_id ASC, provider_position ASC
    """
    return list(conn.execute(sql, tuple(quote_fact_ids)).fetchall())


def list_take_price_facts(
    conn: sqlite3.Connection,
    *,
    chain_id: int,
    auction_address: str,
    round_id: int,
    take_seq: int,
) -> list[sqlite3.Row]:
    sql = """
        SELECT p.*,
               t.auction_address AS current_auction_address,
               t.round_id AS current_round_id,
               t.take_seq AS current_take_seq
          FROM pricing_price_facts p
          JOIN takes t
            ON t.chain_id = p.chain_id
           AND t.tx_hash = p.source_tx_hash
           AND t.log_index = p.source_log_index
         WHERE p.chain_id = ?
           AND t.auction_address = ?
           AND t.round_id = ?
           AND t.take_seq = ?
           AND p.context_kind = 'take'
           AND p.price_role = 'want_token'
         ORDER BY p.captured_at ASC, p.id ASC
    """
    return list(
        conn.execute(
            sql,
            (chain_id, normalize_address(auction_address), round_id, take_seq),
        ).fetchall()
    )


def list_take_price_provider_facts(
    conn: sqlite3.Connection,
    *,
    price_fact_ids: list[int],
) -> list[sqlite3.Row]:
    if not price_fact_ids:
        return []
    placeholders = ",".join("?" for _ in price_fact_ids)
    sql = f"""
        SELECT *
          FROM pricing_price_provider_facts
         WHERE price_fact_id IN ({placeholders})
         ORDER BY price_fact_id ASC, provider_position ASC
    """
    return list(conn.execute(sql, tuple(price_fact_ids)).fetchall())


def occurrence_from_row(row, *, kick: bool = False) -> dict[str, Any]:
    return {
        "chain_id": int(row["chain_id"]),
        "block_hash": str(row["snapshot_block_hash"] if kick else row["block_hash"]).lower(),
        "tx_hash": str(row["snapshot_tx_hash"] if kick else row["tx_hash"]).lower(),
        "log_index": int(row["snapshot_log_index"] if kick else row["log_index"]),
    }


def get_round_by_occurrence(conn, *, chain_id: int, block_hash: str, tx_hash: str, log_index: int):
    return conn.execute(
        _round_select_clause() + " WHERE r.chain_id = ? AND kick.block_hash = ? AND rs.snapshot_tx_hash = ? AND rs.snapshot_log_index = ?",
        (chain_id, block_hash.lower(), tx_hash.lower(), log_index),
    ).fetchone()


def get_take_by_occurrence(conn, *, chain_id: int, block_hash: str, tx_hash: str, log_index: int):
    row = conn.execute(
        """SELECT t.auction_address, t.round_id, t.take_seq FROM takes t
           JOIN domain_events e ON e.chain_id = t.chain_id AND e.tx_hash = t.tx_hash AND e.log_index = t.log_index
           WHERE t.chain_id = ? AND e.block_hash = ? AND t.tx_hash = ? AND t.log_index = ?""",
        (chain_id, block_hash.lower(), tx_hash.lower(), log_index),
    ).fetchone()
    if row is None:
        return None
    return get_take(conn, chain_id=chain_id, auction_address=row["auction_address"], round_id=row["round_id"], take_seq=row["take_seq"])


def _round_destination(conn, row, *, take=None):
    round_row = get_round(conn, chain_id=row["chain_id"], auction_address=row["auction_address"], round_id=row["round_id"])
    if round_row is None:
        return None
    return {
        "kind": "round",
        "chain_id": int(round_row["chain_id"]),
        "auction_address": round_row["auction_address"],
        "round_id": int(round_row["round_id"]),
        "occurrence": occurrence_from_row(round_row, kick=True),
        "take_occurrence": occurrence_from_row(take) if take is not None else None,
    }


def resolve_transaction(conn: sqlite3.Connection, *, tx_hash: str, chain_id: int | None = None, block_hash: str | None = None, log_index: int | None = None) -> dict[str, Any]:
    normalized_tx_hash = normalize_tx_hash_query(tx_hash)
    if normalized_tx_hash is None:
        return {
            "normalized_tx_hash": None,
            "outcome": "invalid",
            "kind": None,
            "destination": None,
        }

    if any(value is not None for value in (chain_id, block_hash, log_index)):
        normalized_block_hash = normalize_tx_hash_query(block_hash)
        if chain_id is None or normalized_block_hash is None or log_index is None or log_index < 0:
            return {"normalized_tx_hash": normalized_tx_hash, "outcome": "invalid", "kind": None, "destination": None}
        occurrence = dict(chain_id=chain_id, block_hash=normalized_block_hash, tx_hash=normalized_tx_hash, log_index=log_index)
        take = get_take_by_occurrence(conn, **occurrence)
        round_row = get_round_by_occurrence(conn, **occurrence) if take is None else None
        row = take if take is not None else round_row
        destination = _round_destination(conn, row, take=take) if row is not None else None
        return {
            "normalized_tx_hash": normalized_tx_hash,
            "outcome": "resolved" if destination is not None else "not_found",
            "kind": ("take" if take is not None else "kick") if destination is not None else None,
            "destination": destination,
        }

    take_rows = conn.execute(
        """
        SELECT DISTINCT chain_id, auction_address, round_id
          FROM takes
         WHERE LOWER(tx_hash) = ?
         ORDER BY chain_id ASC, auction_address ASC, round_id ASC
        """,
        (normalized_tx_hash,),
    ).fetchall()
    if len(take_rows) == 1:
        row = take_rows[0]
        return {
            "normalized_tx_hash": normalized_tx_hash,
            "outcome": "resolved",
            "kind": "take",
            "destination": _round_destination(conn, row),
        }
    if len(take_rows) > 1:
        return {
            "normalized_tx_hash": normalized_tx_hash,
            "outcome": "ambiguous",
            "kind": "take",
            "destination": None,
        }

    kick_rows = conn.execute(
        """
        SELECT DISTINCT chain_id, auction_address, round_id
          FROM round_param_snapshot
         WHERE LOWER(snapshot_tx_hash) = ?
         ORDER BY chain_id ASC, auction_address ASC, round_id ASC
        """,
        (normalized_tx_hash,),
    ).fetchall()
    if len(kick_rows) == 1:
        row = kick_rows[0]
        return {
            "normalized_tx_hash": normalized_tx_hash,
            "outcome": "resolved",
            "kind": "kick",
            "destination": _round_destination(conn, row),
        }
    if len(kick_rows) > 1:
        return {
            "normalized_tx_hash": normalized_tx_hash,
            "outcome": "ambiguous",
            "kind": "kick",
            "destination": None,
        }

    deployment_rows = conn.execute(
        """
        SELECT chain_id, auction_address, MIN(log_index) AS first_log_index
          FROM domain_events
         WHERE LOWER(tx_hash) = ?
           AND event_name = 'DeployedNewAuction'
         GROUP BY chain_id, auction_address
         ORDER BY first_log_index ASC, chain_id ASC, auction_address ASC
        """,
        (normalized_tx_hash,),
    ).fetchall()
    if deployment_rows:
        row = deployment_rows[0]
        return {
            "normalized_tx_hash": normalized_tx_hash,
            "outcome": "resolved",
            "kind": "deployment",
            "destination": {
                "kind": "auction",
                "chain_id": int(row["chain_id"]),
                "auction_address": str(row["auction_address"]),
            },
        }

    return {
        "normalized_tx_hash": normalized_tx_hash,
        "outcome": "not_found",
        "kind": None,
        "destination": None,
    }


def search_index(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return []
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    def add(item: dict[str, Any]) -> None:
        key = (str(item["type"]), int(item["chain_id"]), str(item["address_or_hash"]).lower())
        if key in seen or len(results) >= limit:
            return
        seen.add(key)
        results.append(item)

    if q.startswith("0x"):
        prefix = f"{q}%"
        auction_rows = conn.execute(
            """
            SELECT chain_id, auction_address
              FROM auctions
             WHERE auction_address LIKE ? COLLATE NOCASE
             ORDER BY deployment_block DESC
             LIMIT ?
            """,
            (prefix, limit),
        ).fetchall()
        for row in auction_rows:
            add(
                {
                    "type": "auction",
                    "chain_id": int(row["chain_id"]),
                    "address_or_hash": row["auction_address"],
                    "metadata": None,
                }
            )

        taker_rows = conn.execute(
            """
            SELECT taker, MIN(chain_id) AS chain_id
              FROM taker_summary
             WHERE taker LIKE ? COLLATE NOCASE
             GROUP BY taker
             ORDER BY MAX(last_seen_at) DESC
             LIMIT ?
            """,
            (prefix, limit),
        ).fetchall()
        for row in taker_rows:
            add(
                {
                    "type": "taker",
                    "chain_id": int(row["chain_id"]),
                    "address_or_hash": row["taker"],
                    "metadata": None,
                }
            )

        take_tx_rows = conn.execute(
            """
            SELECT chain_id, tx_hash, auction_address, round_id, timestamp
              FROM takes
             WHERE tx_hash LIKE ? COLLATE NOCASE
             ORDER BY timestamp DESC
             LIMIT ?
            """,
            (prefix, limit),
        ).fetchall()
        for row in take_tx_rows:
            add(
                {
                    "type": "transaction",
                    "chain_id": int(row["chain_id"]),
                    "address_or_hash": row["tx_hash"],
                    "metadata": {
                        "auction_address": row["auction_address"],
                        "round_id": int(row["round_id"]),
                        "timestamp": int(row["timestamp"]),
                    },
                }
            )

        kick_rows = conn.execute(
            """
            SELECT chain_id, snapshot_tx_hash, auction_address, round_id
              FROM round_param_snapshot
             WHERE snapshot_tx_hash LIKE ? COLLATE NOCASE
             ORDER BY snapshot_block DESC
             LIMIT ?
            """,
            (prefix, limit),
        ).fetchall()
        for row in kick_rows:
            add(
                {
                    "type": "kick_transaction",
                    "chain_id": int(row["chain_id"]),
                    "address_or_hash": row["snapshot_tx_hash"],
                    "metadata": {
                        "auction_address": row["auction_address"],
                        "round_id": int(row["round_id"]),
                    },
                }
            )

        token_address_rows = conn.execute(
            """
            SELECT chain_id, token_address, symbol, name, decimals
              FROM tokens
             WHERE token_address LIKE ? COLLATE NOCASE
             ORDER BY chain_id ASC, token_address ASC
             LIMIT ?
            """,
            (prefix, limit),
        ).fetchall()
        for row in token_address_rows:
            add(
                {
                    "type": "token",
                    "chain_id": int(row["chain_id"]),
                    "address_or_hash": row["token_address"],
                    "metadata": {
                        "symbol": row["symbol"],
                        "name": row["name"],
                        "decimals": int(row["decimals"] or 0),
                    },
                }
            )

    token_text_rows = conn.execute(
        """
        SELECT chain_id, token_address, symbol, name, decimals
          FROM tokens
         WHERE symbol LIKE ? COLLATE NOCASE
            OR name LIKE ? COLLATE NOCASE
         ORDER BY CASE
                      WHEN symbol = ? COLLATE NOCASE THEN 0
                      WHEN symbol LIKE ? COLLATE NOCASE THEN 1
                      WHEN name LIKE ? COLLATE NOCASE THEN 2
                      ELSE 3
                  END,
                  symbol COLLATE NOCASE ASC,
                  chain_id ASC,
                  token_address ASC
         LIMIT ?
        """,
        (f"%{q}%", f"%{q}%", q, f"{q}%", f"{q}%", limit),
    ).fetchall()
    for row in token_text_rows:
        add(
            {
                "type": "token",
                "chain_id": int(row["chain_id"]),
                "address_or_hash": row["token_address"],
                "metadata": {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "decimals": int(row["decimals"] or 0),
                },
            }
        )

    return results[:limit]
