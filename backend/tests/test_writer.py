from __future__ import annotations

import pytest

from backend.indexer.writer import Writer


class _InterruptSignal(BaseException):
    pass


def test_transaction_rolls_back_on_base_exception(tmp_path):
    writer = Writer(str(tmp_path / "auctionscan.sqlite3"))

    with pytest.raises(_InterruptSignal):
        writer.transaction(
            lambda conn: (
                conn.execute(
                    """
                    INSERT INTO sync_state (
                        chain_id, network_name, latest_rpc_head, confirmed_head,
                        last_confirmed_processed, last_live_processed, reorg_count, health
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (1, "ethereum", 100, 99, 98, 98, 0, "ok"),
                ),
                (_ for _ in ()).throw(_InterruptSignal()),
            )[-1]
        )

    row = writer.fetchone("SELECT * FROM sync_state WHERE chain_id = 1")
    assert row is None

    writer.transaction(
        lambda conn: conn.execute(
            """
            INSERT INTO sync_state (
                chain_id, network_name, latest_rpc_head, confirmed_head,
                last_confirmed_processed, last_live_processed, reorg_count, health
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "ethereum", 100, 99, 98, 98, 0, "ok"),
        )
    )
    row = writer.fetchone("SELECT health FROM sync_state WHERE chain_id = 1")
    assert row["health"] == "ok"


def test_process_lock_excludes_live_and_maintenance_writers(tmp_path):
    from backend.indexer.writer import ProcessLock

    path = str(tmp_path / "auctionscan.sqlite3")
    live = ProcessLock(path, 1)
    with pytest.raises(RuntimeError, match="stop its indexer"):
        ProcessLock(path, 1)
    another_network = ProcessLock(path, 2)
    another_network.close()
    live.close()
    maintenance = ProcessLock(path, 1)
    maintenance.close()
