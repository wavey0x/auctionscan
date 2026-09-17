from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from web3 import HTTPProvider, Web3

from .config import load_settings
from .decode import AbiRegistry
from .versioning import auction_token_key

API_RPC_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class LiveRoundPriceResult:
    is_active: bool
    current_price_raw: str | None


@lru_cache(maxsize=None)
def _network_runtime(network_key: str) -> tuple[AbiRegistry, Web3]:
    settings = load_settings(target_network=network_key)
    provider = HTTPProvider(
        settings.chains[network_key].rpc_url,
        request_kwargs={"timeout": API_RPC_TIMEOUT_SECONDS},
        exception_retry_configuration=None,
    )
    # This client only sends fully encoded reads. Default validation adds an
    # unrelated eth_chainId request to each call and extends its timeout budget.
    return AbiRegistry(settings), Web3(provider, middleware=[])


def read_live_round_price(
    *,
    network_key: str,
    version: str,
    auction_address: str,
    from_token: str,
    want_token: str,
    block_hash: str,
) -> LiveRoundPriceResult:
    registry, w3 = _network_runtime(network_key)
    contract = registry.auction_contract(w3, auction_address, version)
    key = auction_token_key(w3, version=version, auction_address=auction_address,
                            from_token=from_token, want_token=want_token)
    fn = contract.functions.price(key)
    # ContractFunction.call can resolve hashes back to heights; keep EIP-1898 intact.
    raw = w3.eth.call(
        {"to": fn.address, "data": fn._encode_transaction_data()},
        block_identifier={"blockHash": block_hash, "requireCanonical": True},
        ccip_read_enabled=False,
    )
    current_price = int(w3.codec.decode(["uint256"], raw)[0])
    return LiveRoundPriceResult(
        is_active=current_price > 0,
        current_price_raw=str(current_price) if current_price > 0 else None,
    )
