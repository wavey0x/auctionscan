"""Price what live capture missed, from the chain at the event's block.

Live capture quotes an event within minutes or not at all: a later quote
describes a different market. A replay instead asks the prices service's Curve
provider for its route today, evaluates that route with Curve Router NG's
`get_dy` at the block before the event, and values the want token through
crvUSD's USD price aggregator at the same block. Only the route is found now;
every amount comes from the chain as it stood when the event happened.

The quote is the lot's best exit at that block, as an aggregator's would have
been: the route is one exit among others, because a thin pool can pay far less
for a lot than its other exits do. An LP lot is also withdrawn from its pool,
into one coin or into all of them in proportion. A token that redeems is also
redeemed: a matured principal token for its underlying or its yield-bearing
token, a Spectra wrapper for the token it wraps, a vault share for its asset
(ERC-4626, or the older vaults that only withdraw). A redemption counts for
what it delivers, not what a view promises:
it is simulated with `eth_simulateV1` as the holder that has the tokens at the
block (the pool, or the auction holding the lot), and the holder's balance is
read before and after. A redemption that reverts, queues or delivers nothing
is no exit.

Replays are stored as ordinary pricing facts with capture_origin
'block_replay' and provider 'curve'. They are 'fresh' because they describe
the event's own block, so projections select them like a live quote: after
any live quote, and the newest replay of an event in place of an older one.
Reproject keeps them. Network, chain and provider errors leave no fact, so a
later run retries them; an event with no exit, or none that can absorb the
lot, is recorded as a failed replay and not retried.

The indexer runs the same replay beside live capture (ReplayCapture), so an
event the capture window left unquoted is priced without a maintenance run,
and one an older method quoted is quoted again by the current one.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from collections.abc import Callable
from typing import Any, Protocol

from eth_abi import encode
from eth_utils import keccak
from web3 import HTTPProvider, Web3
from web3.exceptions import ContractLogicError, Web3RPCError

from .prices_api import PricesApiError, PricesApiRateLimitError, PricingApiClient, ProviderCapability
from .pricing import (
    DEFAULT_MAX_CAPTURE_LAG_SECONDS,
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_TIMEOUT_MS,
    PricingQueueJob,
    _persist_price_fact,
    _persist_quote_fact,
)
from .pricing_projections import REPLAY_ORIGIN, rebuild_pricing_projections
from .types import ChainConfig, ReplayPricingConfig, normalize_address


logger = logging.getLogger(__name__)

REPLAY_PROVIDER = "curve"
# Recorded on every replayed quote. Raise it when the replay would answer the
# same event differently, so --requote knows which answers an older method gave.
METHOD_VERSION = 4
# How nodes name a call that ran and broke instead of reverting: a bad jump (how
# old Solidity threw), an undefined opcode, no gas left. Asking a token whether
# it is a pool or a vault runs into these, and they are answers, not outages.
EVM_HALTS = ("evm error", "invalid jump", "opcode", "out of gas", "stack underflow", "stack limit", "stack overflow",
             "write protection", "return data out of bounds")
CHUNK_SIZE = 32
# Beside live capture, which shares the prices service and its rate limit: one
# batch per IDLE_SECONDS, which is also the rest when nothing is left to
# replay. An event a network or provider error deferred is asked about again
# after DEFERRED_RETRY_SECONDS. When the service says to slow down, that is
# about the pace and not the events: everything waits THROTTLED_SECONDS.
IDLE_SECONDS = 60
DEFERRED_RETRY_SECONDS = 3600
THROTTLED_SECONDS = 300
# The prices service allows a key 300 requests a minute, and an event can take
# one request or nine (an LP lot whose coins need the routes for larger sizes).
# After a batch the replay waits as long as its requests would take at this
# rate, so what it leaves for live capture does not depend on what it replayed.
REQUESTS_PER_MINUTE = 100
# The best exit must absorb the lot: the lot is checked against the price of a
# 1/PROBE_DIVISOR slice of it, and has to fetch ABSORBED_PERCENT of that price.
# A lot that moves its own market further is one a seller with other venues
# would not have sold whole here, and what they would have had is unknown. Set
# beside live quotes of the same takes, every replay that fell short of this
# was below the market, by up to half; none that met it was moved by its size.
PROBE_DIVISOR = 100
ABSORBED_PERCENT = 95
# Today's route is one sample of what Curve would use now, and it changes from
# hour to hour: for a small amount it can name a pool that did not exist, or
# held next to nothing, at the event's block. Where the route for the amount
# will not do there, the routes for these multiples of it are tried in turn:
# larger sizes lean on deeper pools, and deeper pools are older.
ROUTE_SCALES = (1, 10, 100)
ZERO_ADDRESS = "0x" + "00" * 20
GET_DY_TYPES = ["address[11]", "uint256[5][5]", "uint256", "address[5]"]
GET_DY_SELECTOR = keccak(text=f"get_dy({','.join(GET_DY_TYPES)})")[:4]
PRICE_SELECTOR = keccak(text="price()")[:4]
ETH = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
POOL_FROM_LP_SELECTOR = keccak(text="get_pool_from_lp_token(address)")[:4]
MINTER_SELECTOR = keccak(text="minter()")[:4]
# Curve pools index coins by uint256, the oldest stableswap pools by int128.
COINS_SELECTORS = (keccak(text="coins(uint256)")[:4], keccak(text="coins(int128)")[:4])
WITHDRAW_SELECTORS = (keccak(text="calc_withdraw_one_coin(uint256,uint256)")[:4],
                      keccak(text="calc_withdraw_one_coin(uint256,int128)")[:4])
BALANCES_SELECTORS = (keccak(text="balances(uint256)")[:4], keccak(text="balances(int128)")[:4])
TOTAL_SUPPLY_SELECTOR = keccak(text="totalSupply()")[:4]
BALANCE_OF_SELECTOR = keccak(text="balanceOf(address)")[:4]
# Redemptions take (amount, receiver, owner); what each delivers is named by a view.
REDEEM_SELECTOR = keccak(text="redeem(uint256,address,address)")[:4]
REDEEM_FOR_IBT_SELECTOR = keccak(text="redeemForIBT(uint256,address,address)")[:4]
UNWRAP_SELECTOR = keccak(text="unwrap(uint256,address,address)")[:4]
# Vaults from before ERC-4626 (iearn's yTokens, Yearn's v2) take the shares alone and pay the caller.
VAULT_WITHDRAW_SELECTOR = keccak(text="withdraw(uint256)")[:4]
TOKEN_SELECTOR = keccak(text="token()")[:4]
MATURITY_SELECTOR = keccak(text="maturity()")[:4]
UNDERLYING_SELECTOR = keccak(text="underlying()")[:4]
GET_IBT_SELECTOR = keccak(text="getIBT()")[:4]
VAULT_SHARE_SELECTOR = keccak(text="vaultShare()")[:4]
ASSET_SELECTOR = keccak(text="asset()")[:4]
# A matured principal token redeems into a vault share, which redeems in turn.
MAX_REDEMPTIONS = 2


class ReplayFailed(Exception):
    """The chain or the router answered, and the answer is that there is no price."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BlockReads(Protocol):
    def header(self, number: int) -> tuple[str, int]: ...

    def call(self, to: str, data: bytes, block_hash: str) -> bytes: ...

    def simulate(self, calls: list[tuple[str, str, bytes]], block_hash: str) -> list[bytes | None]:
        """(sender, to, data) calls in sequence on the block's state; None for a call that reverts."""
        ...


class Web3BlockReads:
    """Archive reads by block hash, one connection per worker thread."""

    def __init__(self, config: ChainConfig) -> None:
        self._config = config
        self._local = threading.local()

    def _w3(self) -> Web3:
        w3 = getattr(self._local, "w3", None)
        if w3 is None:
            w3 = Web3(HTTPProvider(self._config.rpc_url, request_kwargs={"timeout": self._config.request_timeout_seconds}))
            self._local.w3 = w3
        return w3

    def header(self, number: int) -> tuple[str, int]:
        block = self._w3().eth.get_block(number)
        return Web3.to_hex(block["hash"]), int(block["timestamp"])

    def call(self, to: str, data: bytes, block_hash: str) -> bytes:
        try:
            return bytes(self._w3().eth.call(
                {"to": Web3.to_checksum_address(to), "data": Web3.to_hex(data)},
                block_identifier={"blockHash": block_hash, "requireCanonical": True},
            ))
        except ContractLogicError as exc:
            raise ReplayFailed("reverted", str(exc)) from exc
        except Web3RPCError as exc:
            if any(halt in str(exc).lower() for halt in EVM_HALTS):
                raise ReplayFailed("reverted", str(exc)) from exc
            raise

    def simulate(self, calls: list[tuple[str, str, bytes]], block_hash: str) -> list[bytes | None]:
        payload = {"blockStateCalls": [{"calls": [
            {"from": Web3.to_checksum_address(sender), "to": Web3.to_checksum_address(to), "data": Web3.to_hex(data)}
            for sender, to, data in calls
        ]}], "validation": False}
        response = self._w3().provider.make_request("eth_simulateV1", [payload, {"blockHash": block_hash, "requireCanonical": True}])
        if "error" in response:
            raise RuntimeError(f"eth_simulateV1 failed: {response['error']}")
        results = response["result"][0]["calls"]
        if len(results) != len(calls):
            raise RuntimeError("eth_simulateV1 returned a different number of calls")
        return [bytes.fromhex(result["returnData"][2:]) if result.get("status") == "0x1" else None for result in results]


@dataclass(frozen=True)
class ReplayTarget:
    """One event to price, and the block whose closing state was its market."""

    context_kind: str  # "take" or "round_kick"
    auction_address: str
    round_id: int
    take_seq: int | None
    from_token: str
    want_token: str
    want_decimals: int | None
    amount_in_raw: str
    event_timestamp: int
    source_tx_hash: str
    source_log_index: int
    source_event_name: str
    source_block_number: int
    source_block_hash: str
    market_block: int | None  # None: the last block before event_timestamp
    needs_quote: bool
    needs_price: bool

    @property
    def round_key(self) -> tuple[str, int]:
        return (self.auction_address, self.round_id)


@dataclass(frozen=True)
class Observation:
    state: str  # "fresh" or "failed"
    payload: dict[str, Any]
    error: dict[str, Any] | None


@dataclass(frozen=True)
class ReplayOutcome:
    target: ReplayTarget
    quote: Observation | None  # None: not needed, or deferred to a later run
    price: Observation | None
    waiting: bool = False  # a staged window not yet open below the confirmed head


def _covered(conn, table: str, *, chain_id: int, context_kind: str, extra: str = "", retry_failed: bool = False,
             requote: bool = False) -> set[tuple]:
    """Sources a replay has nothing to add to.

    A live observation settles its event. So does a replay, until asked
    again: retry_failed reopens the events a replay found no price for, and
    requote the events whose replays all came from an older method.
    """
    return {
        tuple(row)
        for row in conn.execute(
            f"""
            SELECT source_block_hash, source_tx_hash, source_log_index{', amount_in_raw' if table == 'pricing_quote_facts' else ''}
              FROM {table}
             WHERE chain_id = ? AND context_kind = ? {extra}
               AND CASE WHEN capture_origin = ?
                        THEN (NOT ? OR json_extract(aggregate_response_json, '$.method_version') = ?)
                             AND (capture_state = 'fresh' OR NOT ?)
                        ELSE capture_state = 'fresh' END
            """,
            (chain_id, context_kind, REPLAY_ORIGIN, requote, METHOD_VERSION, retry_failed),
        )
    }


def load_replay_targets(
    conn, *, chain_id: int, confirmed_block: int, before_timestamp: int, auction: str | None = None,
    retry_failed: bool = False, requote: bool = False,
) -> list[ReplayTarget]:
    """Confirmed takes and kicks that live capture left without a quote or a want price.

    Only events older than the live capture window: a newer one may still be
    quoted live. requote adds the events whose replayed quote came from an
    older method, so a better one can replace its answers; a want price is
    one on-chain read either way and is not taken again.
    """
    auction_params = (normalize_address(auction),) if auction else ()
    take_scope = "AND t.auction_address = ?" if auction else ""
    round_scope = "AND r.auction_address = ?" if auction else ""
    targets: list[ReplayTarget] = []

    quoted = _covered(conn, "pricing_quote_facts", chain_id=chain_id, context_kind="take", retry_failed=retry_failed,
                      requote=requote)
    quoted = {key[:3] for key in quoted}
    priced = _covered(conn, "pricing_price_facts", chain_id=chain_id, context_kind="take", extra="AND price_role = 'want_token'",
                      retry_failed=retry_failed)
    for row in conn.execute(
        f"""
        SELECT t.auction_address, t.round_id, t.take_seq, t.from_token, t.want_token, t.amount_taken_raw,
               e.timestamp, e.block_number, e.block_hash, e.tx_hash, e.log_index, wt.decimals AS want_decimals
          FROM takes t
          JOIN domain_events e
            ON e.chain_id = t.chain_id AND e.tx_hash = t.tx_hash AND e.log_index = t.log_index
           AND e.event_name = 'Take'
          LEFT JOIN tokens wt ON wt.chain_id = t.chain_id AND wt.token_address = t.want_token
         WHERE t.chain_id = ? AND e.block_number <= ? AND e.timestamp < ? {take_scope}
         ORDER BY e.block_number, e.log_index
        """,
        (chain_id, confirmed_block, before_timestamp, *auction_params),
    ):
        source = (str(row["block_hash"]), str(row["tx_hash"]), int(row["log_index"]))
        needs_quote = source not in quoted and row["amount_taken_raw"] not in (None, "0")
        needs_price = source not in priced
        if not (row["from_token"] and row["want_token"]) or not (needs_quote or needs_price):
            continue
        targets.append(ReplayTarget(
            context_kind="take", auction_address=str(row["auction_address"]), round_id=int(row["round_id"]),
            take_seq=int(row["take_seq"]), from_token=str(row["from_token"]), want_token=str(row["want_token"]),
            want_decimals=row["want_decimals"], amount_in_raw=str(row["amount_taken_raw"]),
            event_timestamp=int(row["timestamp"]), source_tx_hash=source[1], source_log_index=source[2],
            source_event_name="Take", source_block_number=int(row["block_number"]), source_block_hash=source[0],
            market_block=int(row["block_number"]) - 1, needs_quote=needs_quote, needs_price=needs_price,
        ))

    # A kick quote prices the lot as finally offered, linked to the round's
    # first kick; a staged window's market is the block before it opens.
    kick_quoted = _covered(conn, "pricing_quote_facts", chain_id=chain_id, context_kind="round_kick", retry_failed=retry_failed,
                           requote=requote)
    kick_priced = _covered(conn, "pricing_price_facts", chain_id=chain_id, context_kind="round_kick", extra="AND price_role = 'want_token'",
                           retry_failed=retry_failed)
    for row in conn.execute(
        f"""
        SELECT r.auction_address, r.round_id, r.kicked_at, r.from_token, r.want_token, r.initial_available_raw,
               s.snapshot_tx_hash, s.snapshot_log_index, e.block_number, e.block_hash,
               json_extract(e.payload_json, '$.startsAt') AS starts_at, wt.decimals AS want_decimals
          FROM rounds r
          JOIN round_param_snapshot s
            ON s.chain_id = r.chain_id AND s.auction_address = r.auction_address AND s.round_id = r.round_id
          JOIN domain_events e
            ON e.chain_id = s.chain_id AND e.tx_hash = s.snapshot_tx_hash
           AND e.log_index = s.snapshot_log_index AND e.event_name = 'AuctionKicked'
          LEFT JOIN tokens wt ON wt.chain_id = r.chain_id AND wt.token_address = r.want_token
         WHERE r.chain_id = ? AND e.block_number <= ? AND r.kicked_at < ? {round_scope}
         ORDER BY r.kicked_at, r.auction_address, r.round_id
        """,
        (chain_id, confirmed_block, before_timestamp, *auction_params),
    ):
        lot = row["initial_available_raw"]
        if not (row["from_token"] and row["want_token"]) or lot in (None, "0"):
            continue
        source = (str(row["block_hash"]), str(row["snapshot_tx_hash"]), int(row["snapshot_log_index"]))
        needs_quote = (*source, str(lot)) not in kick_quoted
        needs_price = source not in kick_priced
        if not (needs_quote or needs_price):
            continue
        targets.append(ReplayTarget(
            context_kind="round_kick", auction_address=str(row["auction_address"]), round_id=int(row["round_id"]),
            take_seq=None, from_token=str(row["from_token"]), want_token=str(row["want_token"]),
            want_decimals=row["want_decimals"], amount_in_raw=str(lot), event_timestamp=int(row["kicked_at"]),
            source_tx_hash=source[1], source_log_index=source[2], source_event_name="AuctionKicked",
            source_block_number=int(row["block_number"]), source_block_hash=source[0],
            market_block=None if row["starts_at"] is not None else int(row["block_number"]) - 1,
            needs_quote=needs_quote, needs_price=needs_price,
        ))
    return targets


def last_block_before(reads: BlockReads, timestamp: int, *, low: int, high: int) -> int | None:
    """The last block mined before `timestamp`, between low and high; None if neither brackets it."""
    if reads.header(high)[1] < timestamp or reads.header(low)[1] >= timestamp:
        return None  # The window had not opened by the confirmed head, or low is not before it.
    while high - low > 1:
        middle = (low + high) // 2
        if reads.header(middle)[1] < timestamp:
            low = middle
        else:
            high = middle
    return low


def _router_route(route: dict[str, Any], *, from_token: str, to_token: str) -> tuple[list[str], list[list[int]], list[str]]:
    """The provider's route as Curve Router NG's get_dy arguments, checked end to end."""
    coins = [[normalize_address(coin) for coin in hop] for hop in route.get("coins") or []]
    swaps = [normalize_address(address) for address in route.get("swap_addresses") or []]
    params = [[int(value) for value in hop] for hop in route.get("swap_params") or []]
    pools = [normalize_address(address) for address in route.get("pool_addresses") or [ZERO_ADDRESS] * len(swaps)]
    hops = len(swaps)
    linked = all(coins[index][1] == coins[index + 1][0] for index in range(hops - 1)) if len(coins) == hops else False
    if not (0 < hops <= 5 and len(params) == hops and len(pools) == hops and linked
            and coins[0][0] == from_token and coins[-1][1] == to_token):
        raise ReplayFailed("bad_route", "provider route does not lead from the lot to the want token")
    path = [coins[0][0]]
    for swap, hop in zip(swaps, coins):
        path += [swap, hop[1]]
    path += [ZERO_ADDRESS] * (11 - len(path))
    params += [[0] * 5] * (5 - hops)
    pools += [ZERO_ADDRESS] * (5 - hops)
    return path, params, pools


def _absorbed(amount: int, out: int, probe: int, probe_out: int) -> bool:
    """Whether an amount fetched ABSORBED_PERCENT of the price its probe, a small slice of it, fetched."""
    return out * probe * 100 >= probe_out * amount * ABSORBED_PERCENT


def _uint(result: bytes, *, what: str) -> int:
    if len(result) < 32:
        raise ReplayFailed("no_code", f"{what} returned nothing at this block")
    return int.from_bytes(result[:32], "big")


def _address(result: bytes, *, what: str) -> str:
    return "0x" + _uint(result, what=what).to_bytes(32, "big")[12:].hex()


def _word(value: int | str) -> bytes:
    return encode(["address" if isinstance(value, str) else "uint256"], [value])


@dataclass(frozen=True)
class LpPool:
    pool: str
    coins: tuple[str, ...]
    withdraw_selector: bytes
    balances_selector: bytes


@dataclass(frozen=True)
class Redemption:
    """One way to redeem a token: the call, and the token it delivers."""

    kind: str  # "pt_redeem", "pt_redeem_for_ibt", "unwrap", "erc4626_redeem" or "vault_withdraw"
    token: str
    delivers: str
    selector: bytes

    def call(self, amount: int, holder: str) -> tuple[str, str, bytes]:
        if self.selector == VAULT_WITHDRAW_SELECTOR:
            return holder, self.token, self.selector + encode(["uint256"], [amount])
        return holder, self.token, self.selector + encode(["uint256", "address", "address"], [amount, holder, holder])

    def describe(self) -> dict[str, str]:
        return {"kind": self.kind, "token": self.token, "delivers": self.delivers}


# A token's redemptions, if it has any: the call, the view naming what it delivers, the kind.
PRINCIPAL_REDEMPTIONS = ((REDEEM_SELECTOR, UNDERLYING_SELECTOR, "pt_redeem"),
                         (REDEEM_FOR_IBT_SELECTOR, GET_IBT_SELECTOR, "pt_redeem_for_ibt"))
SHARE_REDEMPTIONS = ((UNWRAP_SELECTOR, VAULT_SHARE_SELECTOR, "unwrap"),
                     (REDEEM_SELECTOR, ASSET_SELECTOR, "erc4626_redeem"),
                     (VAULT_WITHDRAW_SELECTOR, TOKEN_SELECTOR, "vault_withdraw"))


@dataclass(frozen=True)
class Exit:
    """The want a lot or coin amount fetches, and how to evaluate the same path for another amount."""

    out: int
    value_of: Callable[[int], int]
    detail: dict[str, Any]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Replayer:
    """Prices targets; safe to share across worker threads."""

    def __init__(self, *, chain_id: int, config: ReplayPricingConfig, client: PricingApiClient, reads: BlockReads) -> None:
        self.chain_id = chain_id
        self.config = config
        self.client = client
        self.reads = reads
        self._lock = threading.Lock()
        self._headers: dict[int, tuple[str, int]] = {}
        self._opens: dict[int, int] = {}
        self._usd_routes: dict[tuple[str, int], dict[str, Any]] = {}
        self._crvusd_prices: dict[str, int] = {}
        self._coin_routes: dict[tuple[str, str, int], dict[str, Any] | None] = {}
        self._pools: dict[str, LpPool | None] = {}
        self._redemption_options: dict[tuple[str, str], list[Redemption]] = {}
        self._redeemed_amounts: dict[tuple[tuple[Redemption, ...], int, str, str], int] = {}
        self.throttled = False  # the prices service has refused a request for coming too fast
        self.requests = 0  # asked of the prices service

    def header(self, number: int) -> tuple[str, int]:
        with self._lock:
            cached = self._headers.get(number)
        if cached is None:
            cached = self.reads.header(number)
            with self._lock:
                self._headers[number] = cached
        return cached

    def market_block(self, target: ReplayTarget, *, confirmed_block: int) -> int | None:
        """The block whose closing state was the target's market; None while a staged window is not confirmed open.

        Every staged lot sharing a window shares the block before it opens.
        """
        if target.market_block is not None:
            return target.market_block
        with self._lock:
            found = self._opens.get(target.event_timestamp)
        if found is None:
            found = last_block_before(self, target.event_timestamp, low=target.source_block_number, high=confirmed_block)
            if found is not None:
                with self._lock:
                    self._opens[target.event_timestamp] = found
        return found

    def _route(self, *, token_in: str, token_out: str, amount_in: str) -> tuple[dict[str, Any], str | None]:
        """Today's Curve route; ReplayFailed when Curve has none, PricesApiError to retry later."""
        with self._lock:
            self.requests += 1
        response = self.client.fetch_quote(
            chain_id=self.chain_id, token_in=token_in, token_out=token_out, amount_in=amount_in,
            providers=[REPLAY_PROVIDER], use_underlying=False, timeout_ms=DEFAULT_TIMEOUT_MS,
        )
        entry = (response.get("providers") or {}).get(REPLAY_PROVIDER) or {}
        route = entry.get("route")
        if not entry.get("success") or not isinstance(route, dict):
            error = entry.get("error") if isinstance(entry.get("error"), dict) else {}
            code = str(error.get("type") or "no_route").lower()
            message = str(error.get("message") or "Curve has no route")
            if code != "no_route":
                raise PricesApiError(f"Curve provider {code}: {message}")
            raise ReplayFailed(code, message)
        return route, response.get("request_id")

    def _get_dy(self, route: dict[str, Any], *, token_in: str, token_out: str, amount: int, block_hash: str) -> int:
        path, params, pools = _router_route(route, from_token=token_in, to_token=token_out)
        data = GET_DY_SELECTOR + encode(GET_DY_TYPES, [path, params, amount, pools])
        return _uint(self.reads.call(self.config.curve_router, data, block_hash), what="Curve router")

    def _crvusd_price(self, block_hash: str) -> int:
        with self._lock:
            cached = self._crvusd_prices.get(block_hash)
        if cached is None:
            cached = _uint(self.reads.call(self.config.crvusd_price_aggregator, PRICE_SELECTOR, block_hash), what="crvUSD aggregator")
            with self._lock:
                self._crvusd_prices[block_hash] = cached
        return cached

    def _call(self, to: str, data: bytes, block_hash: str) -> bytes | None:
        """A read that may fail: None when the contract reverts or has nothing to say."""
        try:
            result = self.reads.call(to, data, block_hash)
        except ReplayFailed:
            return None
        return result if len(result) >= 32 else None

    def _lp_pool(self, token: str, block_hash: str) -> LpPool | None:
        """The Curve pool behind an LP token: registered, its minter, or the token itself."""
        with self._lock:
            if token in self._pools:
                return self._pools[token]
        candidates = []
        for data, to in ((POOL_FROM_LP_SELECTOR + _word(token), self.config.curve_meta_registry), (MINTER_SELECTOR, token)):
            result = self._call(to, data, block_hash)
            if result is not None and (address := _address(result, what="pool")) != ZERO_ADDRESS:
                candidates.append(address)
        candidates.append(token)
        found = None
        for pool in candidates:
            for coins_selector, withdraw_selector, balances_selector in zip(COINS_SELECTORS, WITHDRAW_SELECTORS, BALANCES_SELECTORS):
                coins = []
                for index in range(8):
                    result = self._call(pool, coins_selector + _word(index), block_hash)
                    if result is None:
                        break
                    coins.append(_address(result, what="coin"))
                if len(coins) >= 2:
                    found = LpPool(pool=pool, coins=tuple(coins), withdraw_selector=withdraw_selector,
                                   balances_selector=balances_selector)
                    break
            if found:
                break
        with self._lock:
            self._pools[token] = found
        return found

    def _sold(self, token_in: str, token_out: str, amount: int, *, block_hash: str,
              ask: Callable[[int], tuple[dict[str, Any], str | None]]) -> tuple[int, dict[str, Any], str | None, int]:
        """The most the amount fetches along today's routes at the block.

        `ask` gives today's route for a size. The route for the amount itself
        is tried first, and the routes for larger sizes only where that one
        does not exist at the block or cannot absorb the amount. Returns what
        the best one fetches, the route, its request id and the size it was
        asked for; raises the first failure when none works.
        """
        best: tuple[int, dict[str, Any], str | None, int] | None = None
        failure: ReplayFailed | None = None
        probe = amount // PROBE_DIVISOR
        for scale in ROUTE_SCALES:
            try:
                route, request_id = ask(amount * scale)
            except ReplayFailed as exc:
                failure = failure or exc
                break  # Curve has no route at this size, and will have none for more
            try:
                out = self._get_dy(route, token_in=token_in, token_out=token_out, amount=amount, block_hash=block_hash)
                absorbed = out > 0 and (probe == 0 or _absorbed(amount, out, probe, self._get_dy(
                    route, token_in=token_in, token_out=token_out, amount=probe, block_hash=block_hash)))
            except ReplayFailed as exc:
                failure = failure or exc  # not at this block: a pool that was not there, or a route one router call cannot express
                continue
            if best is None or out > best[0]:
                best = (out, route, request_id, amount * scale)
            if absorbed:
                break
        if best is None:
            raise failure
        return best

    def _coin_route(self, coin: str, want: str, amount: int) -> dict[str, Any] | None:
        # Today's route depends on the size: what suits a small amount can be a
        # pool too thin for a large one. Amounts within a factor of four share one.
        key = (coin, want, amount.bit_length() // 2)
        with self._lock:
            if key in self._coin_routes:
                return self._coin_routes[key]
        try:
            route, _ = self._route(token_in=coin, token_out=want, amount_in=str(amount))
        except ReplayFailed:
            route = None
        with self._lock:
            self._coin_routes[key] = route
        return route

    def _redemptions(self, token: str, block_hash: str, timestamp: int) -> list[Redemption]:
        """How a token redeems at the block: a matured principal token, a wrapper or a vault share."""
        key = (token, block_hash)
        with self._lock:
            if key in self._redemption_options:
                return self._redemption_options[key]
        maturity = self._call(token, MATURITY_SELECTOR, block_hash)
        if maturity is None:
            ways = SHARE_REDEMPTIONS
        else:
            # Before maturity a principal token's market is its pool, not its redemption.
            ways = PRINCIPAL_REDEMPTIONS if _uint(maturity, what="maturity") <= timestamp else ()
        found = []
        for selector, delivers_selector, kind in ways:
            result = self._call(token, delivers_selector, block_hash)
            if result is not None and (delivers := _address(result, what=kind)) not in (ZERO_ADDRESS, token):
                found.append(Redemption(kind=kind, token=token, delivers=delivers, selector=selector))
        with self._lock:
            self._redemption_options[key] = found
        return found

    def _redeemed(self, steps: tuple[Redemption, ...], amount: int, holder: str, block_hash: str) -> int:
        """What the last of the steps delivers to the holder, each redeeming what the one before delivered.

        Simulated on the block's state with the holder's balance read on either
        side, so a redemption that queues or pays less than it reports counts
        for what arrives.
        """
        key = (steps, amount, holder, block_hash)
        with self._lock:
            cached = self._redeemed_amounts.get(key)
        if cached is not None:
            return cached
        done: list[tuple[str, str, bytes]] = []
        value = amount
        for step in steps:
            balance = (holder, step.delivers, BALANCE_OF_SELECTOR + _word(holder))
            results = self.reads.simulate([*done, balance, step.call(value, holder), balance], block_hash)
            if any(result is None for result in results):
                raise ReplayFailed("reverted", f"{step.kind} of {step.token} reverts at this block")
            delivered = _uint(results[-1], what=step.delivers) - _uint(results[-3], what=step.delivers)
            if delivered <= 0:
                raise ReplayFailed("no_redemption", f"{step.kind} of {step.token} delivers nothing at this block")
            done.append(step.call(value, holder))
            value = delivered
        with self._lock:
            self._redeemed_amounts[key] = value
        return value

    def _coin_exit(self, coin: str, want: str, amount: int, *, holder: str, block_hash: str, timestamp: int,
                   steps: tuple[Redemption, ...] = (), start: int | None = None) -> Exit | None:
        """The most want a coin amount fetches: itself, or the better of today's route and redeeming it.

        `steps` are the redemptions that turned `start` of the first token into
        `amount` of this coin; the exit's value_of takes an amount of that first token.
        """
        coin = WETH if coin == ETH else coin
        final: Callable[[int], int] | None = None
        out = 0
        detail: dict[str, Any] = {}
        if coin == want:
            final, out = (lambda value: value), amount
        else:
            def ask(size: int) -> tuple[dict[str, Any], None]:
                route = self._coin_route(coin, want, size)
                if route is None:
                    raise ReplayFailed("no_route", f"Curve has no route for {coin}")
                return route, None

            try:
                out, route, _, asked = self._sold(coin, want, amount, block_hash=block_hash, ask=ask)
            except ReplayFailed:
                pass  # Curve has no route for the coin today, or none that works at this block
            else:
                final = lambda value: self._get_dy(route, token_in=coin, token_out=want, amount=value, block_hash=block_hash)  # noqa: E731
                detail["route"] = route
                if asked != amount:
                    detail["route_asked_for"] = str(asked)
        sold: Exit | None = None
        if final is not None and not steps:
            sold = Exit(out=out, value_of=final, detail=detail)
        elif final is not None:
            detail["redemptions"] = [step.describe() for step in steps]
            sold = Exit(out=out, detail=detail,
                        value_of=lambda value: final(self._redeemed(steps, value, holder, block_hash)))
        if coin == want:
            return sold
        redeemed = self._redeemed_exit(coin, want, amount, holder=holder, block_hash=block_hash, timestamp=timestamp,
                                       steps=steps, start=start)
        return max((found for found in (sold, redeemed) if found is not None), key=lambda found: found.out, default=None)

    def _redeemed_exit(self, token: str, want: str, amount: int, *, holder: str, block_hash: str, timestamp: int,
                       steps: tuple[Redemption, ...] = (), start: int | None = None) -> Exit | None:
        """The best exit through redeeming the token, if it redeems at the block."""
        start = amount if start is None else start
        if len(steps) >= MAX_REDEMPTIONS:
            return None
        best: Exit | None = None
        for step in self._redemptions(token, block_hash, timestamp):
            path = (*steps, step)
            try:
                delivered = self._redeemed(path, start, holder, block_hash)
                found = self._coin_exit(step.delivers, want, delivered, holder=holder, block_hash=block_hash,
                                        timestamp=timestamp, steps=path, start=start)
            except ReplayFailed:
                continue
            if found is not None and (best is None or found.out > best.out):
                best = found
        return best

    def _withdraw_exits(self, target: ReplayTarget, lp: LpPool, *, amount: int, block_hash: str, timestamp: int) -> list[Exit]:
        """An LP lot withdrawn into each of its pool's coins alone, and into all of them in proportion."""
        exits = []
        for index, coin in enumerate(lp.coins):
            def withdraw(value: int, index: int = index) -> int:
                result = self._call(lp.pool, lp.withdraw_selector + encode(["uint256", "uint256"], [value, index]), block_hash)
                if result is None:
                    raise ReplayFailed("no_route", f"pool {lp.pool} does not withdraw coin {index}")
                return _uint(result, what="pool")

            try:
                withdrawn = withdraw(amount)
                found = self._coin_exit(coin, target.want_token, withdrawn, holder=lp.pool, block_hash=block_hash,
                                        timestamp=timestamp) if withdrawn else None
            except ReplayFailed:
                continue
            if found is not None:
                exits.append(Exit(
                    out=found.out, value_of=lambda value, found=found, withdraw=withdraw: found.value_of(withdraw(value)),
                    detail={"method": "withdraw_one_coin", "pool": lp.pool, "coin_index": index,
                            "coin": WETH if coin == ETH else coin, **found.detail},
                ))
        try:
            balanced = self._balanced_exit(target, lp, amount=amount, block_hash=block_hash, timestamp=timestamp)
        except ReplayFailed:
            balanced = None
        if balanced is not None:
            exits.append(balanced)
        return exits

    def _balanced_exit(self, target: ReplayTarget, lp: LpPool, *, amount: int, block_hash: str, timestamp: int) -> Exit | None:
        """The lot withdrawn in proportion to the pool's balances, which costs no fee; every coin must have an exit."""
        supply = self._call(target.from_token, TOTAL_SUPPLY_SELECTOR, block_hash)
        if supply is None or not (supply := _uint(supply, what="LP supply")):
            return None
        legs = []
        for index, coin in enumerate(lp.coins):
            balance = self._call(lp.pool, lp.balances_selector + encode(["uint256"], [index]), block_hash)
            if balance is None:
                return None
            balance = _uint(balance, what="pool balance")
            if not (share := balance * amount // supply):
                continue
            found = self._coin_exit(coin, target.want_token, share, holder=lp.pool, block_hash=block_hash, timestamp=timestamp)
            if found is None:
                return None
            legs.append((index, coin, balance, found))
        if not legs:
            return None
        return Exit(
            out=sum(found.out for *_, found in legs),
            value_of=lambda value: sum(found.value_of(balance * value // supply) for _, _, balance, found in legs),
            detail={"method": "withdraw_balanced", "pool": lp.pool, "legs": [
                {"coin_index": index, "coin": WETH if coin == ETH else coin, **found.detail} for index, coin, _, found in legs
            ]},
        )

    def _routed_exit(self, target: ReplayTarget, *, amount: int, block_hash: str) -> Exit:
        """The lot sold along the best of today's routes, at the block."""
        out, route, request_id, asked = self._sold(
            target.from_token, target.want_token, amount, block_hash=block_hash,
            ask=lambda size: self._route(token_in=target.from_token, token_out=target.want_token, amount_in=str(size)),
        )

        def value_of(value: int) -> int:
            return self._get_dy(route, token_in=target.from_token, token_out=target.want_token, amount=value, block_hash=block_hash)

        detail = {"request_id": request_id, "route": route}
        if asked != amount:
            detail["route_asked_for"] = str(asked)
        return Exit(out=out, value_of=value_of, detail=detail)

    def _best_exit(self, target: ReplayTarget, *, amount: int, block_hash: str, timestamp: int) -> Exit:
        """The most the lot fetches at the block: sold along today's route, withdrawn from its pool, or redeemed.

        A quote is what a seller could have had, so a route is one exit among
        the others, not the answer whenever it exists: a thin pool can pay far
        less for a lot than redeeming it does.
        """
        exits = []
        unrouted: ReplayFailed | None = None
        lp = self._lp_pool(target.from_token, block_hash)
        try:
            exits.append(self._routed_exit(target, amount=amount, block_hash=block_hash))
        except ReplayFailed as exc:
            unrouted = exc
        except PricesApiRateLimitError:
            raise
        except PricesApiError as exc:
            # Asked to route some LP tokens, Curve answers with an error of its own, every time.
            # An LP lot is withdrawn from its pool whatever becomes of its own route, so only a
            # lot that is no LP token waits for Curve to answer.
            if lp is None:
                raise
            unrouted = ReplayFailed("no_route", f"Curve could not say whether the LP token has a route of its own ({exc})")
        if lp is not None:
            exits += self._withdraw_exits(target, lp, amount=amount, block_hash=block_hash, timestamp=timestamp)
        redeemed = self._redeemed_exit(target.from_token, target.want_token, amount, holder=target.auction_address,
                                       block_hash=block_hash, timestamp=timestamp)
        if redeemed is not None:
            exits.append(Exit(out=redeemed.out, value_of=redeemed.value_of,
                              detail={"method": "redeem", "holder": target.auction_address, **redeemed.detail}))
        if not exits:
            other = ("not a Curve LP token, and nothing redeems it" if lp is None
                     else f"no coin of pool {lp.pool} reaches the want token, sold or redeemed")
            raise ReplayFailed(unrouted.code, f"{unrouted}; {other}")
        return max(exits, key=lambda found: found.out)  # a route wins a tie

    def quote(self, target: ReplayTarget, *, block: int, block_hash: str) -> Observation:
        """The lot's best exit at the block, if that exit can absorb it."""
        started = time.monotonic()
        payload: dict[str, Any] = {"origin": REPLAY_ORIGIN, "method_version": METHOD_VERSION, "block_number": block,
                                   "block_hash": block_hash, "router": self.config.curve_router}
        amount = int(target.amount_in_raw)
        timestamp = self.header(block)[1]
        try:
            best = self._best_exit(target, amount=amount, block_hash=block_hash, timestamp=timestamp)
            payload.update(best.detail)
            amount_out = best.out
            probe = amount // PROBE_DIVISOR
            if probe > 0:
                probe_out = best.value_of(probe)
                payload["probe"] = {"amount_in": str(probe), "amount_out": str(probe_out)}
                if not _absorbed(amount, amount_out, probe, probe_out):
                    raise ReplayFailed("route_exhausted",
                                       f"the lot fetches {amount_out}, under {ABSORBED_PERCENT}% of the price of {probe} ({probe_out})")
            if amount_out == 0:
                raise ReplayFailed("route_exhausted", "the lot's best exit returns nothing for it")
        except ReplayFailed as exc:
            return _failed(payload, exc, started)
        payload["providers"] = {REPLAY_PROVIDER: {
            "status": "ok", "success": True, "amount_in": target.amount_in_raw, "amount_out": str(amount_out),
            "latency_ms": int((time.monotonic() - started) * 1000), "retrieved_at": _iso_now(),
        }}
        return Observation(state="fresh", payload=payload, error=None)

    def price(self, target: ReplayTarget, *, block: int, block_hash: str) -> Observation:
        """The want token in dollars: through crvUSD, valued by its aggregator."""
        started = time.monotonic()
        payload: dict[str, Any] = {"origin": REPLAY_ORIGIN, "block_number": block, "block_hash": block_hash,
                                   "aggregator": self.config.crvusd_price_aggregator}
        try:
            crvusd_usd = self._crvusd_price(block_hash)
            payload["crvusd_price_raw"] = str(crvusd_usd)
            if target.want_token == self.config.crvusd:
                crvusd_per_unit = 10**18
            else:
                if target.want_decimals is None:
                    raise ReplayFailed("unknown_decimals", "want token decimals are unknown")
                unit = 10 ** int(target.want_decimals)
                key = (target.want_token, unit)
                with self._lock:
                    route = self._usd_routes.get(key)
                if route is None:
                    route, _ = self._route(token_in=target.want_token, token_out=self.config.crvusd, amount_in=str(unit))
                    with self._lock:
                        self._usd_routes[key] = route
                payload["route"] = route
                crvusd_per_unit = self._get_dy(route, token_in=target.want_token, token_out=self.config.crvusd,
                                               amount=unit, block_hash=block_hash)
        except ReplayFailed as exc:
            return _failed(payload, exc, started)
        with localcontext() as context:
            context.prec = 60
            price = Decimal(crvusd_per_unit) / Decimal(10**18) * Decimal(crvusd_usd) / Decimal(10**18)
        payload["providers"] = {REPLAY_PROVIDER: {
            "status": "ok", "success": True, "price": format(price.normalize(), "f"),
            "latency_ms": int((time.monotonic() - started) * 1000), "retrieved_at": _iso_now(),
        }}
        return Observation(state="fresh", payload=payload, error=None)

    def replay(self, target: ReplayTarget, *, block: int | None = None, confirmed_block: int | None = None) -> ReplayOutcome:
        """Network and chain errors defer an observation; they are never recorded.

        Without a block, the target's own market block is found first, below the confirmed head.
        """
        try:
            if block is None:
                block = self.market_block(target, confirmed_block=confirmed_block)
                if block is None:
                    return ReplayOutcome(target=target, quote=None, price=None, waiting=True)
            block_hash, _ = self.header(block)
        except Exception as exc:  # noqa: BLE001 - any read failure defers the whole target
            logger.warning("pricing replay deferred block=%s error=%s", block, exc)
            return ReplayOutcome(target=target, quote=None, price=None)
        return ReplayOutcome(
            target=target,
            quote=self._deferring(lambda: self.quote(target, block=block, block_hash=block_hash)) if target.needs_quote else None,
            price=self._deferring(lambda: self.price(target, block=block, block_hash=block_hash)) if target.needs_price else None,
        )

    def _deferring(self, observe) -> Observation | None:
        try:
            return observe()
        except Exception as exc:  # noqa: BLE001 - transport, RPC and service errors are retried next run
            if isinstance(exc, PricesApiRateLimitError):
                self.throttled = True
            logger.warning("pricing replay deferred error=%s", exc)
            return None


def _failed(payload: dict[str, Any], exc: ReplayFailed, started: float) -> Observation:
    error = {"type": exc.code, "message": str(exc)[:500]}
    payload["providers"] = {REPLAY_PROVIDER: {
        "status": "error", "success": False, "error": error,
        "latency_ms": int((time.monotonic() - started) * 1000), "retrieved_at": _iso_now(),
    }}
    return Observation(state="failed", payload=payload, error=error)


def _job(target: ReplayTarget, *, chain_id: int, entity_kind: str, now: int) -> PricingQueueJob:
    """The job live capture would have run for this observation."""
    is_quote = entity_kind != "want_token_price"
    return PricingQueueJob(
        id=0, chain_id=chain_id, auction_address=target.auction_address, round_id=target.round_id,
        take_seq=target.take_seq, entity_kind=entity_kind, event_timestamp=target.event_timestamp,
        from_token=target.from_token if is_quote else None, to_token=target.want_token if is_quote else None,
        token=None if is_quote else target.want_token, amount_in_raw=target.amount_in_raw if is_quote else None,
        source_tx_hash=target.source_tx_hash, source_log_index=target.source_log_index,
        source_event_name=target.source_event_name, source_block_number=target.source_block_number,
        source_block_hash=target.source_block_hash, status="replayed", attempt_count=0, next_attempt_at=None,
        last_error=None, priority=0, created_at=now, updated_at=now,
    )


def persist_outcomes(conn, outcomes: list[ReplayOutcome], *, chain_id: int, now: int) -> set[tuple[str, int]]:
    scope = [ProviderCapability(id=REPLAY_PROVIDER, supports_price=True, supports_quote=True, supported_chains=(chain_id,),
                                requires_api_key=False, available=True, unavailable_reason=None)]
    rounds: set[tuple[str, int]] = set()
    for outcome in outcomes:
        target = outcome.target
        kick = target.context_kind == "round_kick"
        for observation, entity_kind, persist in (
            (outcome.quote, "round_kick_quote" if kick else "take_quote", _persist_quote_fact),
            (outcome.price, "want_token_price", _persist_price_fact),
        ):
            if observation is None:
                continue
            persist(
                conn, job=_job(target, chain_id=chain_id, entity_kind=entity_kind, now=now), provider_scope=scope,
                use_underlying=False, timeout_ms=DEFAULT_TIMEOUT_MS, captured_at=now,
                capture_state=observation.state, payload=observation.payload, aggregate_error=observation.error,
                # The observation is the state just before the event, not a late look at it.
                capture_origin=REPLAY_ORIGIN, capture_lag_seconds=0,
            )
            rounds.add(target.round_key)
    if rounds:
        rebuild_pricing_projections(conn, chain_id=chain_id, rounds=rounds)
    return rounds


def backfill_pricing(
    writer, *, chain_id: int, replayer: Replayer, confirmed_block: int, auction: str | None = None,
    retry_failed: bool = False, requote: bool = False, now: int | None = None,
    max_workers: int = DEFAULT_MAX_CONCURRENCY,
) -> dict[str, Any]:
    """Replay every missing quote and want price; resumable, commits as it goes.

    A recorded replay is final unless asked again, for when the method has
    learned something since: retry_failed where it found no price, requote
    wherever an older method answered. A new attempt is added beside the old
    one, and the newest fresh one is the one projections use.
    """
    now = int(time.time()) if now is None else now
    targets = load_replay_targets(
        writer.connection, chain_id=chain_id, confirmed_block=confirmed_block,
        before_timestamp=now - DEFAULT_MAX_CAPTURE_LAG_SECONDS, auction=auction, retry_failed=retry_failed,
        requote=requote,
    )
    planned = [(target, replayer.market_block(target, confirmed_block=confirmed_block)) for target in targets]
    planned = [(target, block) for target, block in planned if block is not None]
    logger.info("pricing replay start chain_id=%d targets=%d auction=%s", chain_id, len(planned), auction or "all")

    counts = {kind: {"fresh": 0, "failed": 0, "deferred": 0} for kind in ("take_quote", "take_price", "kick_quote", "kick_price")}
    rounds: set[tuple[str, int]] = set()
    with ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="pricing-replay") as pool:
        for start in range(0, len(planned), CHUNK_SIZE):
            chunk = planned[start:start + CHUNK_SIZE]
            outcomes = list(pool.map(lambda item: replayer.replay(item[0], block=item[1]), chunk))
            rounds |= writer.transaction(lambda conn: persist_outcomes(conn, outcomes, chain_id=chain_id, now=now))
            for outcome in outcomes:
                prefix = "kick" if outcome.target.context_kind == "round_kick" else "take"
                for needed, observation, kind in ((outcome.target.needs_quote, outcome.quote, f"{prefix}_quote"),
                                                  (outcome.target.needs_price, outcome.price, f"{prefix}_price")):
                    if needed:
                        counts[kind][observation.state if observation else "deferred"] += 1
            logger.info("pricing replay progress %d/%d", min(start + CHUNK_SIZE, len(planned)), len(planned))
    return {"targets": len(planned), "rounds": len(rounds), **counts}


class ReplayCapture:
    """The replay beside live capture: whatever the capture window left unquoted, a batch at a time.

    Live capture quotes an event within minutes or not at all, and some lots
    no live source quotes at any time. This prices those events once they are
    confirmed, so nobody has to run a backfill for them. It also quotes again
    whatever an older method quoted, so after a release that raises
    METHOD_VERSION every replayed event comes to rest on the one method by
    itself. Like live capture, poll never waits: a batch is replayed on
    worker threads, off the writer, and a later poll commits it. The current
    method's answer is final; an event that a network or provider error
    deferred rests for a while, so one that keeps failing does not hold up
    the rest. Each batch has a replayer of its own: what one remembers
    (today's routes above all) should not outlive the day it was true.

    It is paced, not fast: live capture has minutes to quote an event and
    asks the same prices service under the same rate limit, so a backlog is
    worked off a batch at a time, and when the service says to slow down the
    whole replay waits.
    """

    def __init__(self, make_replayer: Callable[[], Replayer], *, batch_size: int = CHUNK_SIZE, idle_seconds: int = IDLE_SECONDS,
                 retry_seconds: int = DEFERRED_RETRY_SECONDS, throttled_seconds: int = THROTTLED_SECONDS,
                 max_workers: int = DEFAULT_MAX_CONCURRENCY) -> None:
        self.make_replayer = make_replayer
        self.batch_size = batch_size
        self.idle_seconds = idle_seconds
        self.retry_seconds = retry_seconds
        self.throttled_seconds = throttled_seconds
        self.max_workers = max(1, max_workers)
        self._executor: ThreadPoolExecutor | None = None
        self._replayer: Replayer | None = None
        self._started_at = 0
        self._batch: list[Future[ReplayOutcome]] = []
        self._next_scan_at = 0
        self._resting: dict[tuple, int] = {}

    @staticmethod
    def _source(target: ReplayTarget) -> tuple:
        return (target.context_kind, target.source_block_hash, target.source_tx_hash, target.source_log_index)

    @property
    def in_flight(self) -> int:
        return len(self._batch)

    def poll(self, writer, *, chain_id: int, now: int | None = None) -> int:
        """Commit a finished batch and start the next; returns the rounds repriced."""
        now = int(time.time()) if now is None else now
        repriced = 0
        if self._batch:
            if not all(future.done() for future in self._batch):
                return 0
            outcomes = [future.result() for future in self._batch]
            self._batch = []
            throttled = self._replayer is not None and self._replayer.throttled
            deferred = 0
            for outcome in outcomes:
                target = outcome.target
                if outcome.waiting:
                    self._resting[self._source(target)] = now + self.idle_seconds
                elif (target.needs_quote and outcome.quote is None) or (target.needs_price and outcome.price is None):
                    self._resting[self._source(target)] = now + (self.throttled_seconds if throttled else self.retry_seconds)
                    deferred += 1
            if throttled:
                self._next_scan_at = max(self._next_scan_at, now + self.throttled_seconds)
            elif self._replayer is not None:
                spent = -(-self._replayer.requests * 60 // REQUESTS_PER_MINUTE)  # seconds this batch's requests are worth
                self._next_scan_at = max(self._next_scan_at, self._started_at + spent)
            repriced = len(writer.transaction(lambda conn: persist_outcomes(conn, outcomes, chain_id=chain_id, now=now)))
            logger.info("pricing replay batch events=%d deferred=%d rounds=%d requests=%d throttled=%s", len(outcomes), deferred,
                        repriced, self._replayer.requests if self._replayer is not None else 0, throttled)
        if now < self._next_scan_at:
            return repriced
        state = writer.fetchone("SELECT last_confirmed_processed FROM sync_state WHERE chain_id = ?", (chain_id,))
        confirmed_block = state["last_confirmed_processed"] if state is not None else None
        self._resting = {source: until for source, until in self._resting.items() if until > now}
        targets = [] if confirmed_block is None else [
            target for target in load_replay_targets(
                writer.connection, chain_id=chain_id, confirmed_block=int(confirmed_block),
                before_timestamp=now - DEFAULT_MAX_CAPTURE_LAG_SECONDS, requote=True,
            ) if self._source(target) not in self._resting
        ]
        # The newest first: they are what a reader is looking at, and a backlog should not keep them waiting.
        targets = sorted(targets, key=lambda target: target.event_timestamp, reverse=True)[:self.batch_size]
        if not targets:
            self._next_scan_at = now + self.idle_seconds
            return repriced
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="pricing-replay")
        self._replayer = self.make_replayer()
        self._batch = [
            self._executor.submit(self._replayer.replay, target, confirmed_block=int(confirmed_block)) for target in targets
        ]
        self._started_at = now
        self._next_scan_at = now + self.idle_seconds
        return repriced

    def wait_for_outstanding(self, *, timeout: float = 10.0) -> None:
        """Block until the batch in flight finishes; for fixtures."""
        for future in list(self._batch):
            future.result(timeout=timeout)

    def discard(self) -> None:
        """Maintenance discards a batch in flight; nothing was recorded, so its events are found again."""
        self._batch = []
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
