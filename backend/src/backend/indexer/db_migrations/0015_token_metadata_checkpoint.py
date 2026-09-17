from yoyo import step


def apply(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tokens)")}
    if "metadata_block" not in columns:
        conn.execute("ALTER TABLE tokens ADD COLUMN metadata_block INTEGER NOT NULL DEFAULT -1")


steps = [step(apply)]
