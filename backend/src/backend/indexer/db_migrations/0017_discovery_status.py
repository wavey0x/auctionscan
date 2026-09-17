"""Persist discovery knowledge and refresh freshness separately from sync health."""
from yoyo import step


def apply(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sync_state)")}
    if "discovery_status_json" not in columns:
        conn.execute("ALTER TABLE sync_state ADD COLUMN discovery_status_json TEXT")


steps = [step(apply)]
