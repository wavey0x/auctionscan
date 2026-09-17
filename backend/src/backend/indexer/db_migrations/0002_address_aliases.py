from yoyo import step


def ensure_address_aliases(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS address_aliases (
            chain_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            alias_text TEXT,
            checked_at INTEGER,
            PRIMARY KEY (chain_id, address)
        )
        """
    )


steps = [step(ensure_address_aliases)]
