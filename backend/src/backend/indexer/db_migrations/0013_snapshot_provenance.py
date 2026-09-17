from yoyo import step


def apply(conn):
    for table in ("round_param_snapshot", "auction_snapshot_facts"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "block_hash" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN block_hash TEXT")


steps = [step(apply)]
