import sqlite3

from yoyo import step

from backend.indexer.db_migrations.helpers.schema_v0001 import _column_names, _table_exists


SYNC_STATE_SQL = """
CREATE TABLE IF NOT EXISTS sync_state (
    chain_id INTEGER PRIMARY KEY,
    network_name TEXT NOT NULL,
    latest_rpc_head INTEGER,
    confirmed_head INTEGER,
    last_confirmed_processed INTEGER,
    last_live_processed INTEGER,
    last_reorg_at INTEGER,
    reorg_count INTEGER NOT NULL DEFAULT 0,
    last_success_at INTEGER,
    last_error TEXT,
    health TEXT NOT NULL DEFAULT 'unknown'
)
"""

INDEXED_BLOCKS_SQL = """
CREATE TABLE IF NOT EXISTS indexed_blocks (
    chain_id INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    parent_hash TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    PRIMARY KEY (chain_id, block_number)
)
"""

INDEXED_BLOCKS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_indexed_blocks_chain_number
    ON indexed_blocks (chain_id, block_number)
"""


def migrate_confirmed_live_reorg_state(conn) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute(INDEXED_BLOCKS_SQL)
    conn.execute(INDEXED_BLOCKS_INDEX_SQL)

    if not _table_exists(conn, "sync_state"):
        conn.execute(SYNC_STATE_SQL)
        return

    columns = _column_names(conn, "sync_state")
    required = {
        "confirmed_head",
        "last_confirmed_processed",
        "last_live_processed",
        "last_reorg_at",
        "reorg_count",
    }
    if required <= columns:
        conn.execute(
            "UPDATE sync_state SET reorg_count = COALESCE(reorg_count, 0) WHERE reorg_count IS NULL"
        )
        return

    rows = list(conn.execute("SELECT * FROM sync_state").fetchall())
    conn.execute(SYNC_STATE_SQL.replace("sync_state", "sync_state_new", 1))
    for row in rows:
        latest_rpc_head = int(row["latest_rpc_head"]) if "latest_rpc_head" in row.keys() and row["latest_rpc_head"] is not None else None
        confirmed_head = (
            int(row["confirmed_head"])
            if "confirmed_head" in row.keys() and row["confirmed_head"] is not None
            else int(row["latest_finalized_head"])
            if "latest_finalized_head" in row.keys() and row["latest_finalized_head"] is not None
            else None
        )
        last_confirmed_processed = (
            int(row["last_confirmed_processed"])
            if "last_confirmed_processed" in row.keys() and row["last_confirmed_processed"] is not None
            else int(row["last_finalized_processed"])
            if "last_finalized_processed" in row.keys() and row["last_finalized_processed"] is not None
            else None
        )
        last_live_processed = (
            int(row["last_live_processed"])
            if "last_live_processed" in row.keys() and row["last_live_processed"] is not None
            else last_confirmed_processed
        )
        last_reorg_at = (
            int(row["last_reorg_at"])
            if "last_reorg_at" in row.keys() and row["last_reorg_at"] is not None
            else None
        )
        reorg_count = (
            int(row["reorg_count"])
            if "reorg_count" in row.keys() and row["reorg_count"] is not None
            else 0
        )
        last_success_at = (
            int(row["last_success_at"])
            if "last_success_at" in row.keys() and row["last_success_at"] is not None
            else None
        )
        conn.execute(
            """
            INSERT INTO sync_state_new (
                chain_id, network_name, latest_rpc_head, confirmed_head,
                last_confirmed_processed, last_live_processed, last_reorg_at,
                reorg_count, last_success_at, last_error, health
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(row["chain_id"]),
                str(row["network_name"]),
                latest_rpc_head,
                confirmed_head,
                last_confirmed_processed,
                last_live_processed,
                last_reorg_at,
                reorg_count,
                last_success_at,
                row["last_error"] if "last_error" in row.keys() else None,
                str(row["health"]) if "health" in row.keys() else "unknown",
            ),
        )

    conn.execute("DROP TABLE sync_state")
    conn.execute("ALTER TABLE sync_state_new RENAME TO sync_state")


steps = [step(migrate_confirmed_live_reorg_state)]
