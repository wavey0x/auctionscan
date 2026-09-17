from yoyo import step


COLUMNS = {
    "finality_mode": "TEXT",
    "finality_warning": "TEXT",
    "confirmed_head_hash": "TEXT",
    "confirmed_head_timestamp": "INTEGER",
    "last_confirmed_hash": "TEXT",
    "latest_rpc_head_timestamp": "INTEGER",
    "last_finality_advance_at": "INTEGER",
}


def apply(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sync_state)")}
    for name, definition in COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE sync_state ADD COLUMN {name} {definition}")


steps = [step(apply)]
