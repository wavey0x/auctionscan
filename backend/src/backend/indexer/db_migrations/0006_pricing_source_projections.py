from yoyo import step


CREATE_TABLES_SQL = """
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

CREATE TABLE IF NOT EXISTS round_pricing_source (
    chain_id INTEGER NOT NULL,
    auction_address TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    total_actual_paid_raw TEXT NOT NULL DEFAULT '0',
    total_market_quote_out_raw TEXT NOT NULL DEFAULT '0',
    total_actual_paid_usd TEXT,
    total_market_quote_usd TEXT,
    total_auction_profit_usd TEXT,
    total_auction_profit_bps INTEGER,
    priced_take_count INTEGER NOT NULL DEFAULT 0,
    total_take_count INTEGER NOT NULL DEFAULT 0,
    priced_volume_share TEXT,
    PRIMARY KEY (chain_id, auction_address, round_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_take_pricing_source_lookup
    ON take_pricing_source (chain_id, auction_address, round_id, take_seq, source_id);
CREATE INDEX IF NOT EXISTS idx_round_pricing_source_lookup
    ON round_pricing_source (chain_id, auction_address, round_id, source_id);
"""


def create_pricing_source_projections(conn) -> None:
    take_pricing_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(take_pricing)").fetchall()
    }
    if "market_quote_out_usd" not in take_pricing_columns:
        conn.execute("ALTER TABLE take_pricing ADD COLUMN market_quote_out_usd TEXT")
    if "priced_volume_usd" not in take_pricing_columns:
        conn.execute("ALTER TABLE take_pricing ADD COLUMN priced_volume_usd TEXT")
    conn.executescript(CREATE_TABLES_SQL)


steps = [step(create_pricing_source_projections)]
