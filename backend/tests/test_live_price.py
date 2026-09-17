import pytest
from web3 import Web3

from backend.indexer import live_price
from .helpers import DEFAULT_AUCTION, DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN
from .test_observations import _Provider


@pytest.mark.parametrize("version", ["0.0.1", "1.0.4", "1.0.5"])
def test_live_call_keeps_canonical_hash_and_uses_the_deployed_abi(monkeypatch, version):
    monkeypatch.setenv("ETHEREUM_RPC_URL", "http://localhost:8545")
    provider = _Provider()
    monkeypatch.setattr(live_price, "HTTPProvider", lambda *args, **kwargs: provider)
    live_price._network_runtime.cache_clear()
    _, w3 = live_price._network_runtime("ethereum")
    block_hash = "0x" + "ab" * 32
    result = live_price.read_live_round_price(network_key="ethereum", version=version, auction_address=DEFAULT_AUCTION, from_token=DEFAULT_FROM_TOKEN, want_token=DEFAULT_WANT_TOKEN, block_hash=block_hash)
    assert result.current_price_raw == "18"
    assert len(provider.calls) == 1
    method, params = provider.calls[0]
    assert method == "eth_call"
    assert params[1] == {"blockHash": block_hash, "requireCanonical": True}
    signature = "price(bytes32)" if version == "0.0.1" else "price(address)"
    assert params[0]["data"][:10] == "0x" + Web3.keccak(text=signature)[:4].hex()
    argument = bytes.fromhex(params[0]["data"][10:])
    if version == "0.0.1":
        assert argument == Web3.solidity_keccak(["address"] * 3, [Web3.to_checksum_address(a) for a in (DEFAULT_FROM_TOKEN, DEFAULT_WANT_TOKEN, DEFAULT_AUCTION)])
    else:
        assert w3.codec.decode(["address"], argument)[0] == DEFAULT_FROM_TOKEN
    provider.failure = {"code": -32000, "message": "block is not canonical"}
    with pytest.raises(Exception, match="canonical"):
        live_price.read_live_round_price(network_key="ethereum", version=version, auction_address=DEFAULT_AUCTION, from_token=DEFAULT_FROM_TOKEN, want_token=DEFAULT_WANT_TOKEN, block_hash=block_hash)
    assert len(provider.calls) == 2  # No retry at another hash or height.
    live_price._network_runtime.cache_clear()


def test_api_rpc_timeout_disables_provider_retries(monkeypatch):
    monkeypatch.setenv("ETHEREUM_RPC_URL", "http://localhost:8545")
    live_price._network_runtime.cache_clear()
    _, w3 = live_price._network_runtime("ethereum")
    assert w3.provider.get_request_kwargs()["timeout"] == 5
    assert w3.provider.exception_retry_configuration is None
    live_price._network_runtime.cache_clear()
