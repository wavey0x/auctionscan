from __future__ import annotations

import json

import pytest
from eth_abi import decode

from backend.indexer import pricing_replay
from backend.indexer.config import _replay_pricing
from backend.indexer.prices_api import PricesApiError
from backend.indexer.pricing_projections import rebuild_pricing_projections
from backend.indexer.pricing_replay import (
    ASSET_SELECTOR,
    BALANCE_OF_SELECTOR,
    BALANCES_SELECTORS,
    COINS_SELECTORS,
    GET_DY_SELECTOR,
    GET_DY_TYPES,
    GET_IBT_SELECTOR,
    MATURITY_SELECTOR,
    POOL_FROM_LP_SELECTOR,
    PRICE_SELECTOR,
    REDEEM_FOR_IBT_SELECTOR,
    REDEEM_SELECTOR,
    TOTAL_SUPPLY_SELECTOR,
    UNDERLYING_SELECTOR,
    UNWRAP_SELECTOR,
    VAULT_SHARE_SELECTOR,
    WITHDRAW_SELECTORS,
    Replayer,
    ReplayFailed,
    backfill_pricing,
    last_block_before,
    load_replay_targets,
)
from backend.indexer.types import ReplayPricingConfig

from .helpers import DEFAULT_AUCTION, DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN
from .test_pricing import ONE_USDC, _seed_pricing_db

# Pricing the live capture missed: today's Curve route, evaluated at the block
# before the event, stored as ordinary facts that projections select.

CONFIG = ReplayPricingConfig(
    curve_router="0x0000000000000000000000000000000000000f01",
    crvusd="0x0000000000000000000000000000000000000f02",
    crvusd_price_aggregator="0x0000000000000000000000000000000000000f03",
    curve_meta_registry="0x0000000000000000000000000000000000000f06",
)
POOL = "0x0000000000000000000000000000000000000f04"
NOW = 2_000_000_000
TAKE_BLOCK, KICK_BLOCK = 103, 102


def _route(token_in: str, token_out: str) -> dict:
    return {"swap_addresses": [POOL], "pool_addresses": [POOL], "swap_params": [[0, 1, 1, 1, 2]],
            "coins": [[token_in, token_out]]}


class FakeClient:
    """The prices service's Curve provider: a route, or the error it names."""

    def __init__(self, *, failures: dict[str, Exception | str] | None = None) -> None:
        self.failures = failures or {}
        self.requests: list[tuple[str, str, str]] = []

    def fetch_quote(self, *, chain_id, token_in, token_out, amount_in, providers, use_underlying, timeout_ms):
        assert providers == ["curve"] and use_underlying is False
        self.requests.append((token_in, token_out, amount_in))
        failure = self.failures.get(token_in)
        if isinstance(failure, Exception):
            raise failure
        if failure:
            return {"request_id": "r", "providers": {"curve": {"success": False, "error": {"type": failure, "message": "none"}}}}
        return {"request_id": "r", "providers": {"curve": {"success": True, "route": _route(token_in, token_out)}}}


class FakeChain:
    """A lot is worth (1000 + block) / 1000 want per 1e12 raw units, so the block used shows."""

    def __init__(self, *, depth: int | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self.depth = depth  # the most WANT the lot's route can pay out, like a LLAMMA's bands

    def header(self, number: int) -> tuple[str, int]:
        return f"0x{number:064x}", 1_700_000_000 + number

    def call(self, to: str, data: bytes, block_hash: str) -> bytes:
        block = int(block_hash, 16)
        self.calls.append((to, block))
        if to == CONFIG.crvusd_price_aggregator:
            assert data == PRICE_SELECTOR
            return (99 * 10**16).to_bytes(32, "big")  # crvUSD at $0.99
        if to != CONFIG.curve_router:
            raise ReplayFailed("reverted", "no such function")  # the registry knows no pool, the lot is no pool
        assert data[:4] == GET_DY_SELECTOR
        path, _params, amount, _pools = decode(GET_DY_TYPES, data[4:])
        if path[0] == DEFAULT_WANT_TOKEN:
            return (10**18).to_bytes(32, "big")  # one want unit buys one crvUSD
        out = amount // 10**12 * (1000 + block) // 1000
        return (out if self.depth is None else min(out, self.depth)).to_bytes(32, "big")


def _replay(writer, *, client=None, chain=None, auction=None):
    replayer = Replayer(chain_id=1, config=CONFIG, client=client or FakeClient(), reads=chain or FakeChain())
    return backfill_pricing(writer, chain_id=1, replayer=replayer, confirmed_block=200, auction=auction, now=NOW)


def test_replay_prices_a_take_and_its_kick_at_the_blocks_before_them(tmp_path):
    writer, _ = _seed_pricing_db(tmp_path / "replay.sqlite3")
    chain = FakeChain()

    summary = _replay(writer, chain=chain)

    assert summary["take_quote"] == {"fresh": 1, "failed": 0, "deferred": 0}
    assert summary["kick_quote"] == {"fresh": 1, "failed": 0, "deferred": 0}
    assert {block for _, block in chain.calls} == {TAKE_BLOCK - 1, KICK_BLOCK - 1}
    take = writer.fetchone("SELECT * FROM take_pricing")
    # 200 FROM at block 102 is 220.4 WANT; the want token is $0.99 through crvUSD.
    assert take["market_quote_out_raw"] == str(220_400_000)
    assert take["want_token_price_usd"] == "0.99"
    assert take["auction_profit_raw"] == str(150 * ONE_USDC - 220_400_000)
    assert take["pricing_status"] == "priced"
    kick = writer.fetchone("SELECT * FROM round_pricing")
    assert kick["kick_market_quote_out_raw"] == str(500 * ONE_USDC * 1101 // 1000)
    facts = writer.fetchall("SELECT context_kind, capture_origin, capture_state, capture_lag_seconds FROM pricing_quote_facts ORDER BY context_kind")
    assert [tuple(row) for row in facts] == [("round_kick", "block_replay", "fresh", 0), ("take", "block_replay", "fresh", 0)]
    providers = writer.fetchall("SELECT provider_id, participation_status FROM pricing_quote_provider_facts")
    assert {tuple(row) for row in providers} == {("curve", "ok")}

    # Facts are the record: rebuilding projections from them changes nothing.
    before = [tuple(row) for row in writer.fetchall("SELECT * FROM take_pricing")]
    writer.transaction(lambda conn: rebuild_pricing_projections(conn, chain_id=1))
    assert [tuple(row) for row in writer.fetchall("SELECT * FROM take_pricing")] == before

    # A second run finds nothing left to price.
    assert _replay(writer)["targets"] == 0


def test_replay_leaves_live_quotes_alone(tmp_path):
    writer, events = _seed_pricing_db(tmp_path / "live.sqlite3")
    _replay(writer)
    conn = writer.connection
    conn.execute("UPDATE pricing_quote_facts SET capture_origin = 'native' WHERE context_kind = 'take'")
    conn.commit()

    targets = load_replay_targets(conn, chain_id=1, confirmed_block=200, before_timestamp=NOW)
    assert targets == []

    # Nor does it reach events that live capture may still quote, or beyond the confirmed head.
    conn.execute("DELETE FROM pricing_quote_facts")
    conn.execute("DELETE FROM pricing_price_facts")
    conn.commit()
    take_time = events["take"].domain_event.timestamp
    assert [t.context_kind for t in load_replay_targets(conn, chain_id=1, confirmed_block=200, before_timestamp=take_time)] == ["round_kick"]
    assert load_replay_targets(conn, chain_id=1, confirmed_block=TAKE_BLOCK - 2, before_timestamp=NOW) == []


def test_missing_routes_are_recorded_and_network_errors_retried(tmp_path):
    writer, _ = _seed_pricing_db(tmp_path / "failures.sqlite3")

    for failure in (PricesApiError("prices API request failed: timed out"), "UPSTREAM_HTTP"):
        summary = _replay(writer, client=FakeClient(failures={DEFAULT_FROM_TOKEN: failure}))
        assert summary["take_quote"] == {"fresh": 0, "failed": 0, "deferred": 1}
        assert writer.fetchone("SELECT COUNT(*) AS n FROM pricing_quote_facts")["n"] == 0
    assert writer.fetchone("SELECT COUNT(*) AS n FROM pricing_price_facts WHERE context_kind = 'take'")["n"] == 1

    no_route = FakeClient(failures={DEFAULT_FROM_TOKEN: "NO_ROUTE"})
    summary = _replay(writer, client=no_route)
    assert summary["take_quote"] == {"fresh": 0, "failed": 1, "deferred": 0}
    failed = writer.fetchone("SELECT * FROM pricing_quote_facts WHERE context_kind = 'take'")
    assert (failed["capture_origin"], failed["capture_state"]) == ("block_replay", "failed")
    assert writer.fetchone("SELECT error_code FROM pricing_quote_provider_facts WHERE quote_fact_id = ?", (failed["id"],))["error_code"] == "no_route"
    assert writer.fetchone("SELECT pricing_status FROM take_pricing")["pricing_status"] != "priced"

    # A recorded failure is an answer; the next run does not ask again.
    assert _replay(writer)["targets"] == 0


def test_a_route_that_cannot_absorb_the_lot_prices_nothing(tmp_path):
    writer, _ = _seed_pricing_db(tmp_path / "shallow.sqlite3")

    summary = _replay(writer, chain=FakeChain(depth=ONE_USDC))

    assert summary["take_quote"] == {"fresh": 0, "failed": 1, "deferred": 0}
    failed = writer.fetchone("SELECT id FROM pricing_quote_facts WHERE context_kind = 'take'")
    assert writer.fetchone("SELECT error_code FROM pricing_quote_provider_facts WHERE quote_fact_id = ?", (failed["id"],))["error_code"] == "route_exhausted"
    assert writer.fetchone("SELECT market_quote_out_raw FROM take_pricing")["market_quote_out_raw"] is None


LP_POOL = "0x0000000000000000000000000000000000000f07"
VAULT = "0x0000000000000000000000000000000000000f08"  # coin 0: a vault with no route, worth more on paper
COIN = "0x0000000000000000000000000000000000000f09"  # coin 1: routes to the want token


class LpChain(FakeChain):
    """The lot is an LP token of LP_POOL, which Curve cannot route but can withdraw from."""

    def call(self, to: str, data: bytes, block_hash: str) -> bytes:
        selector, args = data[:4], data[4:]
        if to == CONFIG.curve_meta_registry and selector == POOL_FROM_LP_SELECTOR:
            assert decode(["address"], args)[0] == DEFAULT_FROM_TOKEN
            return encode_address(LP_POOL)
        if to == LP_POOL and selector == COINS_SELECTORS[0]:
            index = decode(["uint256"], args)[0]
            if index > 1:
                raise ReplayFailed("reverted", "no such coin")
            return encode_address((VAULT, COIN)[index])
        if to == LP_POOL and selector == WITHDRAW_SELECTORS[0]:
            amount, index = decode(["uint256", "uint256"], args)
            return (amount * 2 if index == 0 else amount).to_bytes(32, "big")
        if to in (DEFAULT_FROM_TOKEN, COIN, VAULT):
            raise ReplayFailed("reverted", "not that kind of contract")
        if to == CONFIG.curve_router and decode(GET_DY_TYPES, data[4:])[0][0] == COIN:
            return (decode(GET_DY_TYPES, data[4:])[2] // 10**12).to_bytes(32, "big")
        return super().call(to, data, block_hash)


def encode_address(address: str) -> bytes:
    return bytes(12) + bytes.fromhex(address[2:])


def test_an_lp_lot_without_a_route_is_withdrawn_into_its_best_coin(tmp_path):
    writer, _ = _seed_pricing_db(tmp_path / "lp.sqlite3")
    no_route = FakeClient(failures={DEFAULT_FROM_TOKEN: "NO_ROUTE", VAULT: "NO_ROUTE"})

    # Without the pool, the lot has no price; a retry once the pool is known finds one.
    assert _replay(writer, client=no_route)["take_quote"] == {"fresh": 0, "failed": 1, "deferred": 0}
    assert _replay(writer, client=no_route, chain=LpChain())["targets"] == 0
    replayer = Replayer(chain_id=1, config=CONFIG, client=no_route, reads=LpChain())
    summary = backfill_pricing(writer, chain_id=1, replayer=replayer, confirmed_block=200, retry_failed=True, now=NOW)
    assert summary["take_quote"] == {"fresh": 1, "failed": 0, "deferred": 0}

    # 200 LP withdraws into 400 vault shares, which no route sells, or 200 COIN (200 WANT).
    take = writer.fetchone("SELECT market_quote_out_raw, pricing_status FROM take_pricing")
    assert (take["market_quote_out_raw"], take["pricing_status"]) == (str(200 * ONE_USDC), "priced")
    fact = writer.fetchone("SELECT aggregate_response_json FROM pricing_quote_facts WHERE context_kind = 'take' AND capture_state = 'fresh'")
    detail = json.loads(fact["aggregate_response_json"])
    assert (detail["method"], detail["pool"], detail["coin_index"], detail["coin"]) == ("withdraw_one_coin", LP_POOL, 1, COIN)
    # The earlier failure stays beside the new attempt.
    assert writer.fetchone("SELECT COUNT(*) AS n FROM pricing_quote_facts WHERE context_kind = 'take'")["n"] == 2


IBT = "0x0000000000000000000000000000000000000f10"  # a vault share worth 2 UNDERLYING
PT = "0x0000000000000000000000000000000000000f11"  # a principal token redeeming 1:1 for UNDERLYING
UNDERLYING = "0x0000000000000000000000000000000000000f12"  # routes to the want token 1:1
WRAPPER = "0x0000000000000000000000000000000000000f13"  # a Spectra wrapper unwrapping into 1.5 UNDERLYING
ETHER = 10**18
REPLAY_TIME = 1_700_000_000 + TAKE_BLOCK - 1


def _uint(value: int) -> bytes:
    return value.to_bytes(32, "big")


class RedeemChain(FakeChain):
    """Tokens that redeem: views answer from a table, redemptions move simulated balances.

    `redeems` maps (token, selector) to (delivers, numerator, denominator); a
    queued redemption reports its amount and delivers nothing.
    """

    def __init__(self, *, views: dict, redeems: dict, balances: dict, pool: str | None = None,
                 pool_balances: tuple[int, ...] = (), queued: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.views, self.redeems, self.balances = views, redeems, balances
        self.pool, self.pool_balances, self.queued = pool, pool_balances, queued
        self.simulated: list[int] = []

    def call(self, to: str, data: bytes, block_hash: str) -> bytes:
        selector, args = data[:4], data[4:]
        if self.pool and to == CONFIG.curve_meta_registry and selector == POOL_FROM_LP_SELECTOR:
            return encode_address(self.pool)
        if to == self.pool and selector == COINS_SELECTORS[0]:
            index = decode(["uint256"], args)[0]
            if index >= len(self.pool_balances):
                raise ReplayFailed("reverted", "no such coin")
            return encode_address((IBT, PT)[index])
        if to == self.pool and selector == WITHDRAW_SELECTORS[0]:
            amount, _index = decode(["uint256", "uint256"], args)
            return _uint(amount * 9 // 10)  # one coin alone pays a tenth less than its share
        if to == self.pool and selector == BALANCES_SELECTORS[0]:
            return _uint(self.pool_balances[decode(["uint256"], args)[0]])
        if (to, selector) in self.views:
            value = self.views[(to, selector)]
            return encode_address(value) if isinstance(value, str) else _uint(value)
        if to == CONFIG.curve_router and decode(GET_DY_TYPES, data[4:])[0][0] == UNDERLYING:
            return _uint(decode(GET_DY_TYPES, data[4:])[2] // 10**12)
        if to != CONFIG.curve_router and to != CONFIG.crvusd_price_aggregator:
            raise ReplayFailed("reverted", "no such function")
        return super().call(to, data, block_hash)

    def simulate(self, calls, block_hash):
        self.simulated.append(int(block_hash, 16))
        balances = dict(self.balances)
        results = []
        for sender, to, data in calls:
            selector, args = data[:4], data[4:]
            if selector == BALANCE_OF_SELECTOR:
                results.append(_uint(balances.get((to, decode(["address"], args)[0]), 0)))
                continue
            if (to, selector) not in self.redeems:
                results.append(None)
                continue
            amount, receiver, owner = decode(["uint256", "address", "address"], args)
            delivers, numerator, denominator = self.redeems[(to, selector)]
            if sender != owner or balances.get((to, owner), 0) < amount:
                results.append(None)
                continue
            balances[(to, owner)] -= amount
            out = amount * numerator // denominator
            if to not in self.queued:
                balances[(delivers, receiver)] = balances.get((delivers, receiver), 0) + out
            results.append(_uint(out))
        return results


def _spectra_chain(*, matured: bool = True, queued: tuple[str, ...] = ()) -> RedeemChain:
    """The lot is the LP of a pool holding 1000 IBT and 1000 PT, with 1000 LP in all."""
    return RedeemChain(
        pool=LP_POOL, pool_balances=(1000 * ETHER, 1000 * ETHER), queued=queued,
        views={(DEFAULT_FROM_TOKEN, TOTAL_SUPPLY_SELECTOR): 1000 * ETHER,
               (IBT, ASSET_SELECTOR): UNDERLYING,
               (PT, MATURITY_SELECTOR): REPLAY_TIME - (1 if matured else -1),
               (PT, UNDERLYING_SELECTOR): UNDERLYING, (PT, GET_IBT_SELECTOR): IBT},
        redeems={(IBT, REDEEM_SELECTOR): (UNDERLYING, 2, 1), (PT, REDEEM_SELECTOR): (UNDERLYING, 1, 1),
                 (PT, REDEEM_FOR_IBT_SELECTOR): (IBT, 1, 2)},
        balances={(IBT, LP_POOL): 1000 * ETHER, (PT, LP_POOL): 1000 * ETHER, (UNDERLYING, LP_POOL): 5 * ETHER},
    )


def _no_routes(*tokens: str) -> FakeClient:
    return FakeClient(failures={token: "NO_ROUTE" for token in (DEFAULT_FROM_TOKEN, *tokens)})


def test_a_principal_token_pool_lot_is_withdrawn_and_redeemed_at_the_block(tmp_path):
    writer, _ = _seed_pricing_db(tmp_path / "spectra.sqlite3")
    chain = _spectra_chain()

    summary = _replay(writer, client=_no_routes(IBT, PT), chain=chain)

    assert summary["take_quote"] == {"fresh": 1, "failed": 0, "deferred": 0}
    assert TAKE_BLOCK - 1 in chain.simulated
    # 200 of 1000 LP withdraws in proportion into 200 IBT and 200 PT, redeemed
    # into 400 and 200 UNDERLYING: 600 WANT. One coin alone fetches at most 360.
    take = writer.fetchone("SELECT market_quote_out_raw, auction_profit_raw FROM take_pricing")
    assert take["market_quote_out_raw"] == str(600 * ONE_USDC)
    assert take["auction_profit_raw"] == str(150 * ONE_USDC - 600 * ONE_USDC)
    fact = writer.fetchone("SELECT aggregate_response_json FROM pricing_quote_facts WHERE context_kind = 'take'")
    detail = json.loads(fact["aggregate_response_json"])
    assert (detail["method"], detail["pool"]) == ("withdraw_balanced", LP_POOL)
    assert [(leg["coin"], [step["kind"] for step in leg["redemptions"]]) for leg in detail["legs"]] == [
        (IBT, ["erc4626_redeem"]), (PT, ["pt_redeem"])]
    assert detail["probe"]["amount_out"] == str(6 * ONE_USDC)


@pytest.mark.parametrize(("matured", "queued", "expected"), [
    (True, (IBT,), ("withdraw_one_coin", 180)),  # a vault that queues delivers nothing: only the PT redeems
    (False, (), ("withdraw_one_coin", 360)),  # before maturity a PT has no redemption, and no route
    (False, (IBT,), None),  # nothing redeems: no exit at all
])
def test_a_redemption_counts_for_what_it_delivers(tmp_path, matured, queued, expected):
    writer, _ = _seed_pricing_db(tmp_path / "delivered.sqlite3")

    _replay(writer, client=_no_routes(IBT, PT), chain=_spectra_chain(matured=matured, queued=queued))

    fact = writer.fetchone("SELECT id, capture_state, aggregate_response_json FROM pricing_quote_facts WHERE context_kind = 'take'")
    take = writer.fetchone("SELECT market_quote_out_raw FROM take_pricing")
    if expected is None:
        assert fact["capture_state"] == "failed"
        error = writer.fetchone("SELECT error_code, error_message FROM pricing_quote_provider_facts WHERE quote_fact_id = ?", (fact["id"],))
        assert error["error_code"] == "no_route" and "sold or redeemed" in error["error_message"]
        assert take["market_quote_out_raw"] is None
        return
    method, want = expected
    assert json.loads(fact["aggregate_response_json"])["method"] == method
    assert take["market_quote_out_raw"] == str(want * ONE_USDC)


def test_a_redeemable_lot_is_redeemed_by_the_auction_holding_it(tmp_path):
    writer, _ = _seed_pricing_db(tmp_path / "held.sqlite3")
    # The lot is a matured principal token whose redeem reverts, as a Spectra PT
    # over a wrapper does; it redeems for the wrapper instead, which unwraps.
    chain = RedeemChain(
        views={(DEFAULT_FROM_TOKEN, MATURITY_SELECTOR): REPLAY_TIME - 1,
               (DEFAULT_FROM_TOKEN, UNDERLYING_SELECTOR): UNDERLYING, (DEFAULT_FROM_TOKEN, GET_IBT_SELECTOR): WRAPPER,
               (WRAPPER, VAULT_SHARE_SELECTOR): UNDERLYING},
        redeems={(DEFAULT_FROM_TOKEN, REDEEM_FOR_IBT_SELECTOR): (WRAPPER, 1, 1), (WRAPPER, UNWRAP_SELECTOR): (UNDERLYING, 3, 2)},
        balances={(DEFAULT_FROM_TOKEN, DEFAULT_AUCTION): 1000 * ETHER},
    )

    _replay(writer, client=_no_routes(WRAPPER), chain=chain)

    take = writer.fetchone("SELECT market_quote_out_raw FROM take_pricing")
    assert take["market_quote_out_raw"] == str(300 * ONE_USDC)  # 200 PT -> 200 wrapper -> 300 UNDERLYING
    fact = writer.fetchone("SELECT aggregate_response_json FROM pricing_quote_facts WHERE context_kind = 'take'")
    detail = json.loads(fact["aggregate_response_json"])
    assert (detail["method"], detail["holder"]) == ("redeem", DEFAULT_AUCTION)
    assert [step["kind"] for step in detail["redemptions"]] == ["pt_redeem_for_ibt", "unwrap"]


def test_window_open_block_is_the_last_block_before_it():
    chain = FakeChain()
    opens_at = 1_700_000_000 + 150
    assert last_block_before(chain, opens_at, low=100, high=200) == 149
    assert last_block_before(chain, opens_at, low=100, high=140) is None  # not open by the confirmed head
    assert last_block_before(chain, opens_at, low=160, high=200) is None  # the search must start before it


def test_router_arguments_follow_the_route_end_to_end():
    other = "0x0000000000000000000000000000000000000f05"
    path, params, pools = pricing_replay._router_route(
        {"swap_addresses": [POOL, other], "pool_addresses": [pricing_replay.ZERO_ADDRESS, other],
         "swap_params": [[0, 0, 6, 3, 3], [0, 1, 1, 1, 2]], "coins": [[DEFAULT_FROM_TOKEN, CONFIG.crvusd], [CONFIG.crvusd, DEFAULT_WANT_TOKEN]]},
        from_token=DEFAULT_FROM_TOKEN, to_token=DEFAULT_WANT_TOKEN,
    )
    assert path[:5] == [DEFAULT_FROM_TOKEN, POOL, CONFIG.crvusd, other, DEFAULT_WANT_TOKEN]
    assert len(path) == 11 and set(path[5:]) == {pricing_replay.ZERO_ADDRESS}
    assert params[:2] == [[0, 0, 6, 3, 3], [0, 1, 1, 1, 2]] and len(params) == 5
    assert pools[:2] == [pricing_replay.ZERO_ADDRESS, other] and len(pools) == 5
    with pytest.raises(ReplayFailed, match="lead from the lot"):
        pricing_replay._router_route(_route(DEFAULT_FROM_TOKEN, CONFIG.crvusd), from_token=DEFAULT_FROM_TOKEN, to_token=DEFAULT_WANT_TOKEN)


def test_replay_pricing_config_needs_every_contract():
    assert _replay_pricing(None) is None
    parsed = _replay_pricing({"curve_router": CONFIG.curve_router.upper().replace("0X", "0x"), "crvusd": CONFIG.crvusd,
                              "crvusd_price_aggregator": CONFIG.crvusd_price_aggregator,
                              "curve_meta_registry": CONFIG.curve_meta_registry})
    assert parsed == CONFIG
    with pytest.raises(ValueError, match="crvusd_price_aggregator"):
        _replay_pricing({"curve_router": CONFIG.curve_router, "crvusd": CONFIG.crvusd})
