"""Current payment projections. Reproject stored facts after this migration."""

from yoyo import step


def apply(conn):
    additions = {
        "rounds": {"paid_sold_amount_raw": "TEXT NOT NULL DEFAULT '0'", "paid_take_count": "INTEGER NOT NULL DEFAULT 0"},
        "round_pricing": {"paid_usd_take_count": "INTEGER NOT NULL DEFAULT 0", "usd_priced_take_count": "INTEGER NOT NULL DEFAULT 0"},
        "round_pricing_source": {"usd_priced_take_count": "INTEGER NOT NULL DEFAULT 0"},
        "taker_pricing_summary": {"paid_usd_take_count": "INTEGER NOT NULL DEFAULT 0"},
    }
    for table, fields in additions.items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, declaration in fields.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    for table, removed in {"taker_summary": ("total_bought_raw", "total_paid_raw"), "round_pricing": ("total_expected_paid_raw",), "take_pricing": ("estimated_auction_profit_raw", "estimated_auction_profit_usd")}.items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column in removed:
            if column in columns:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    # SQLite cannot drop NOT NULL in place. Rebuild only these derived tables,
    # retaining every column and index; no fact table is changed.
    for table, fields in {"rounds": ("paid_amount_raw",), "round_pricing": ("total_actual_paid_raw", "total_market_quote_out_raw"), "round_pricing_source": ("total_actual_paid_raw", "total_market_quote_out_raw")}.items():
        original = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
        changed = original
        for field in fields:
            changed = changed.replace(f"{field} TEXT NOT NULL DEFAULT '0'", f"{field} TEXT").replace(f"{field} TEXT NOT NULL", f"{field} TEXT")
        if changed == original:
            continue
        indexes = [row[0] for row in conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,))]
        conn.execute(changed.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_new", 1))
        conn.execute(f"INSERT INTO {table}_new SELECT * FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        for sql in indexes:
            conn.execute(sql)


steps = [step(apply)]
