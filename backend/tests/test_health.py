import pytest

from backend.api.routes.health import chain_health


NOW = 1_800_000_000


@pytest.mark.parametrize("changes, expected, detail", [
    ({}, "ok", None),
    ({"last_success_at": NOW - 61}, "stale", "recent sync"),
    ({"latest_rpc_head_timestamp": NOW - 91}, "stale", "old chain head"),
    ({"last_live_processed": 99}, "indexing", "Catching up"),
    ({"confirmed_head_timestamp": NOW - 1801}, "degraded", "Finality"),
    ({"finality_warning": "RPC finalized head regressed"}, "degraded", "regressed"),
    ({"last_error": "Conflicting finalized anchor", "last_success_at": NOW - 1000}, "error", "Indexer sync failed"),
    ({"finality_mode": "confirmations", "confirmed_head_timestamp": NOW - 1801}, "ok", None),
])
def test_health_distinguishes_live_freshness_finality_and_errors(changes, expected, detail):
    row = {
        "health": "ok", "last_error": None, "finality_warning": None,
        "last_success_at": NOW, "latest_rpc_head_timestamp": NOW - 12,
        "latest_rpc_head": 100, "last_live_processed": 100,
        "finality_mode": "finalized", "confirmed_head_timestamp": NOW - 800,
    }
    health, reason, warning = chain_health({**row, **changes}, now=NOW)
    assert health == expected
    if detail:
        assert detail in reason
    else:
        assert reason is None
