from __future__ import annotations

import sqlite3
from typing import Any

from backend.indexer.types import normalize_address


def _taker_ctes(
    *,
    chain_id: int | None,
    taker_query: str | None,
) -> tuple[str, tuple[Any, ...]]:
    summary_filter = ""
    auction_filter = ""
    params: list[Any] = []
    if chain_id is not None:
        summary_filter = "WHERE ts.chain_id = ?"
        auction_filter = "WHERE chain_id = ?"
        params.extend([chain_id, chain_id])
    normalized_query = (taker_query or "").strip().lower()
    params.extend([normalized_query, f"%{normalized_query}%"])
    return (
        f"""
        WITH chain_summaries AS (
            SELECT ts.chain_id,
                   ts.taker,
                   ts.take_count,
                   ts.first_seen_at,
                   ts.last_seen_at,
                   tps.total_actual_paid_usd,
                   tps.total_taker_profit_usd,
                   COALESCE(tps.priced_take_count, 0) AS priced_take_count,
                   COALESCE(tps.paid_usd_take_count, 0) AS paid_usd_take_count,
                   COALESCE(tps.priced_volume_usd, '0') AS priced_volume_usd,
                   COALESCE(tps.total_volume_usd_for_share, '0') AS total_volume_usd_for_share
              FROM taker_summary ts
              LEFT JOIN taker_pricing_summary tps
                ON tps.chain_id = ts.chain_id
               AND tps.taker = ts.taker
              {summary_filter}
        ),
        auction_keys AS (
            SELECT DISTINCT chain_id, taker, auction_address
              FROM takes
              {auction_filter}
        ),
        auction_counts AS (
            SELECT taker, COUNT(*) AS unique_auctions
              FROM auction_keys
             GROUP BY taker
        ),
        aggregates AS (
            SELECT cs.taker,
                   SUM(cs.take_count) AS total_takes,
                   COUNT(*) AS unique_chains,
                   GROUP_CONCAT(cs.chain_id) AS active_chains_csv,
                   MIN(cs.first_seen_at) AS first_take,
                   MAX(cs.last_seen_at) AS last_take,
                   SUM(cs.priced_take_count) AS priced_take_count,
                   SUM(cs.paid_usd_take_count) AS paid_usd_take_count,
                   CASE
                       WHEN SUM(cs.total_actual_paid_usd IS NOT NULL) > 0
                       THEN SUM(CAST(cs.total_actual_paid_usd AS REAL))
                       ELSE NULL
                   END AS total_actual_paid_usd,
                   CASE
                       WHEN SUM(cs.total_taker_profit_usd IS NOT NULL) > 0
                       THEN SUM(CAST(cs.total_taker_profit_usd AS REAL))
                       ELSE NULL
                   END AS total_taker_profit_usd,
                   SUM(CAST(cs.priced_volume_usd AS REAL)) AS priced_volume_usd,
                   SUM(CAST(cs.total_volume_usd_for_share AS REAL)) AS total_volume_usd_for_share
              FROM chain_summaries cs
             GROUP BY cs.taker
        ),
        metrics AS (
            SELECT a.*,
                   COALESCE(ac.unique_auctions, 0) AS unique_auctions,
                   CASE
                       WHEN a.priced_take_count > 0 AND a.total_taker_profit_usd IS NOT NULL
                       THEN a.total_taker_profit_usd / a.priced_take_count
                       ELSE NULL
                   END AS avg_taker_profit_usd,
                   CASE
                       WHEN a.total_volume_usd_for_share > 0
                       THEN a.priced_volume_usd / a.total_volume_usd_for_share
                       ELSE NULL
                   END AS priced_volume_share
              FROM aggregates a
              LEFT JOIN auction_counts ac ON ac.taker = a.taker
        ),
        filtered AS (
            SELECT *
              FROM metrics
             WHERE (? = '' OR taker LIKE ? COLLATE NOCASE)
        )
        """,
        tuple(params),
    )


def _ranked_taker_cte(ctes: str) -> str:
    return (
        ctes
        + """,
        ranked AS (
            SELECT filtered.*,
                   ROW_NUMBER() OVER (
                       ORDER BY (total_actual_paid_usd IS NULL) ASC,
                                total_actual_paid_usd DESC,
                                priced_take_count DESC,
                                total_takes DESC,
                                taker ASC
                   ) AS rank_by_volume,
                   ROW_NUMBER() OVER (
                       ORDER BY total_takes DESC, taker ASC
                   ) AS rank_by_takes
              FROM filtered
        )
        """
    )


def _taker_item_from_row(row: sqlite3.Row) -> dict[str, Any]:
    active_chains = sorted(
        {
            int(value)
            for value in str(row["active_chains_csv"] or "").split(",")
            if value
        }
    )
    return {
        "taker": str(row["taker"]),
        "total_takes": int(row["total_takes"] or 0),
        "unique_auctions": int(row["unique_auctions"] or 0),
        "unique_chains": int(row["unique_chains"] or 0),
        "total_actual_paid_usd": (
            float(row["total_actual_paid_usd"])
            if row["total_actual_paid_usd"] is not None
            else None
        ),
        "total_taker_profit_usd": (
            float(row["total_taker_profit_usd"])
            if row["total_taker_profit_usd"] is not None
            else None
        ),
        "avg_taker_profit_usd": (
            float(row["avg_taker_profit_usd"])
            if row["avg_taker_profit_usd"] is not None
            else None
        ),
        "priced_take_count": int(row["priced_take_count"] or 0),
        "paid_usd_take_count": int(row["paid_usd_take_count"] or 0),
        "priced_volume_share": (
            float(row["priced_volume_share"])
            if row["priced_volume_share"] is not None
            else None
        ),
        "active_chains": active_chains,
        "first_take": int(row["first_take"]) if row["first_take"] is not None else None,
        "last_take": int(row["last_take"]) if row["last_take"] is not None else None,
        "rank_by_volume": int(row["rank_by_volume"]),
        "rank_by_takes": int(row["rank_by_takes"]),
    }


def list_takers(
    conn: sqlite3.Connection,
    *,
    chain_id: int | None,
    sort_by: str,
    taker_query: str | None = None,
    page: int,
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    ctes, params = _taker_ctes(chain_id=chain_id, taker_query=taker_query)
    total = int(conn.execute(ctes + "SELECT COUNT(*) AS count FROM filtered", params).fetchone()["count"])
    order_by = {
        "taker": "taker ASC, COALESCE(last_take, 0) DESC",
        "chains": "unique_chains DESC, total_takes DESC, taker ASC",
        "auctions": "unique_auctions DESC, total_takes DESC, taker ASC",
        "takes": "total_takes DESC, COALESCE(last_take, 0) DESC, taker ASC",
        "recent": "COALESCE(last_take, 0) DESC, total_takes DESC, taker ASC",
        "volume": (
            "(total_actual_paid_usd IS NULL) ASC, total_actual_paid_usd DESC, "
            "priced_take_count DESC, total_takes DESC, taker ASC"
        ),
    }.get(sort_by, "rank_by_volume ASC")
    ranked_ctes = _ranked_taker_cte(ctes)
    rows = conn.execute(
        ranked_ctes
        + f"""
        SELECT *
          FROM ranked
         ORDER BY {order_by}
         LIMIT ? OFFSET ?
        """,
        (*params, limit, (page - 1) * limit),
    ).fetchall()
    return total, [_taker_item_from_row(row) for row in rows]


def get_taker_detail(conn: sqlite3.Connection, *, taker_address: str) -> dict[str, Any] | None:
    taker_norm = normalize_address(taker_address)
    ctes, params = _taker_ctes(chain_id=None, taker_query=None)
    row = conn.execute(
        _ranked_taker_cte(ctes) + "SELECT * FROM ranked WHERE taker = ?",
        (*params, taker_norm),
    ).fetchone()
    if row is None:
        return None
    target = _taker_item_from_row(row)
    breakdown_rows = conn.execute(
        """
        SELECT t.chain_id,
               t.auction_address,
               COUNT(*) AS takes_count,
               MIN(t.timestamp) AS first_take,
               MAX(t.timestamp) AS last_take,
               SUM(CAST(tp.priced_volume_usd AS REAL)) AS volume_usd,
               COUNT(tp.priced_volume_usd) AS paid_usd_take_count,
               COUNT(tp.auction_profit_usd) AS priced_take_count,
               -SUM(
                   CAST(
                       tp.auction_profit_usd
                       AS REAL
                   )
               ) AS taker_profit_usd
          FROM takes t
          LEFT JOIN take_pricing tp
            ON tp.chain_id = t.chain_id
           AND tp.auction_address = t.auction_address
           AND tp.round_id = t.round_id
           AND tp.take_seq = t.take_seq
         WHERE t.taker = ?
         GROUP BY t.chain_id, t.auction_address
         ORDER BY MAX(t.timestamp) DESC, t.auction_address ASC
        """,
        (taker_norm,),
    ).fetchall()
    target["auction_breakdown"] = [
        {
            "chain_id": int(row["chain_id"]),
            "auction_address": row["auction_address"],
            "takes_count": int(row["takes_count"]),
            "paid_usd_take_count": int(row["paid_usd_take_count"]),
            "priced_take_count": int(row["priced_take_count"]),
            "volume_usd": float(row["volume_usd"]) if row["volume_usd"] is not None else None,
            "taker_profit_usd": (
                float(row["taker_profit_usd"])
                if row["taker_profit_usd"] is not None
                else None
            ),
            "first_take": int(row["first_take"]) if row["first_take"] is not None else None,
            "last_take": int(row["last_take"]) if row["last_take"] is not None else None,
        }
        for row in breakdown_rows
    ]
    return target


def list_taker_takes(
    conn: sqlite3.Connection,
    *,
    taker_address: str,
    page: int,
    limit: int,
) -> tuple[int, list[sqlite3.Row]]:
    taker_norm = normalize_address(taker_address)
    total = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM takes WHERE taker = ?",
            (taker_norm,),
        ).fetchone()["count"]
    )
    rows = conn.execute(
        """
        SELECT t.chain_id,
               t.auction_address,
               t.round_id,
               t.take_seq,
               t.taker,
               t.timestamp,
               t.tx_hash,
               t.log_index,
               e.block_hash,
               kick.block_hash AS snapshot_block_hash,
               rs.snapshot_tx_hash,
               rs.snapshot_log_index,
               t.amount_taken_raw,
               t.amount_paid_raw,
               t.expected_amount_paid_raw,
               tp.market_quote_out_raw,
               tp.market_quote_out_usd,
               tp.priced_volume_usd,
               tp.want_token_price_usd,
               tp.pricing_status,
               tp.auction_profit_usd,
               tp.auction_profit_bps,
               ft.decimals AS from_token_decimals,
               wt.decimals AS want_token_decimals
          FROM takes t
          JOIN domain_events e ON e.chain_id = t.chain_id AND e.tx_hash = t.tx_hash AND e.log_index = t.log_index

          JOIN round_param_snapshot rs
            ON rs.chain_id = t.chain_id AND rs.auction_address = t.auction_address AND rs.round_id = t.round_id
          JOIN domain_events kick
            ON kick.chain_id = rs.chain_id AND kick.tx_hash = rs.snapshot_tx_hash AND kick.log_index = rs.snapshot_log_index
          LEFT JOIN take_pricing tp
            ON tp.chain_id = t.chain_id
           AND tp.auction_address = t.auction_address
           AND tp.round_id = t.round_id
           AND tp.take_seq = t.take_seq
          LEFT JOIN tokens ft
            ON ft.chain_id = t.chain_id
           AND ft.token_address = t.from_token
          LEFT JOIN tokens wt
            ON wt.chain_id = t.chain_id
           AND wt.token_address = t.want_token
         WHERE t.taker = ?
         ORDER BY t.timestamp DESC, t.take_seq DESC
         LIMIT ? OFFSET ?
        """,
        (taker_norm, limit, (page - 1) * limit),
    ).fetchall()
    return total, list(rows)


