from yoyo import step


def apply(conn):
    conn.execute("DROP INDEX IF EXISTS idx_pricing_capture_queue_source_entity")
    conn.execute("""
        CREATE UNIQUE INDEX idx_pricing_capture_queue_source_entity
        ON pricing_capture_queue (chain_id, source_block_hash, source_tx_hash, source_log_index, entity_kind)
    """)


steps = [step(apply)]
