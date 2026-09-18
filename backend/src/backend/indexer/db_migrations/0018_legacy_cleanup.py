from yoyo import step


def apply(conn):
    removed_columns = {
        "take_pricing": ("canonical_from_price_fact_id", "from_token_price_usd"),
        "round_pricing": ("kick_contract_expected_out_raw", "kick_start_premium_bps"),
        "rounds": (
            "minimum_price_raw", "starting_price_raw", "step_decay_rate_raw",
            "step_duration_raw", "auction_length_raw",
        ),
        "auctions": ("has_enabled_tokens",),
    }
    for table, columns in removed_columns.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column in columns:
            if column in existing:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    conn.execute("DROP TABLE IF EXISTS auction_param_history")


steps = [step(apply)]
