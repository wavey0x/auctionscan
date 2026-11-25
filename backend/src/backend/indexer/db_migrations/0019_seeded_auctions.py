"""Auctions seeded from config, and Curve lot floors.

Config-seeded auctions (Curve's DutchAuctionBurner) are not deployed by a
factory, so their tracked and projected rows have no factory or discovery
transaction. Curve lots also decay to a floor they hold until the window ends,
which is a lot total rather than Yearn's per-unit cutoff.
"""

from yoyo import step


def _rebuild_without_not_null(conn, table: str, columns: tuple[str, ...]) -> None:
    # SQLite cannot drop NOT NULL in place. Rebuild from the table's own SQL so
    # column order and every index are kept.
    original = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
    changed = original
    for column in columns:
        changed = changed.replace(f"{column} TEXT NOT NULL", f"{column} TEXT")
    if changed == original:
        return
    indexes = [row[0] for row in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,),
    )]
    conn.execute(changed.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_new", 1))
    conn.execute(f"INSERT INTO {table}_new SELECT * FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
    for sql in indexes:
        conn.execute(sql)


def apply(conn):
    _rebuild_without_not_null(conn, "tracked_auctions", ("factory_address", "discovered_tx_hash"))
    _rebuild_without_not_null(conn, "auctions", ("factory_address",))
    for table in ("rounds", "auction_current_params"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "floor_price" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN floor_price TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_round_param_snapshot_token "
        "ON round_param_snapshot (chain_id, auction_address, from_token)"
    )


steps = [step(apply)]
