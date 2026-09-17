from yoyo import step


INDEX_SQL = """
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
CREATE INDEX IF NOT EXISTS idx_round_snapshot_tx_hash_search
    ON round_param_snapshot (snapshot_tx_hash COLLATE NOCASE, snapshot_block DESC);
"""


def migrate_taker_sql_search(conn) -> None:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(taker_pricing_summary)").fetchall()
    }
    if "priced_volume_usd" not in columns:
        conn.execute(
            "ALTER TABLE taker_pricing_summary "
            "ADD COLUMN priced_volume_usd TEXT NOT NULL DEFAULT '0'"
        )
    if "total_volume_usd_for_share" not in columns:
        conn.execute(
            "ALTER TABLE taker_pricing_summary "
            "ADD COLUMN total_volume_usd_for_share TEXT NOT NULL DEFAULT '0'"
        )
    conn.execute("DROP TABLE IF EXISTS search_documents")
    conn.executescript(INDEX_SQL)


steps = [step(migrate_taker_sql_search)]
