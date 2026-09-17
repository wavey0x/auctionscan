from dataclasses import replace

import pytest
from web3 import Web3
from web3.providers import BaseProvider

from backend.indexer.observations import BlockReader, BranchChanged, MissingObservation
from backend.indexer.types import IndexedBlockRecord
from backend.indexer.writer import Writer
from .test_replay_and_takes import _make_transfer_raw


class _Provider(BaseProvider):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.failure = None
        self.results = {}

    def make_request(self, method, params):
        self.calls.append((method, params))
        if self.failure is not None:
            if isinstance(self.failure, Exception):
                raise self.failure
            return {"jsonrpc": "2.0", "id": 1, "error": self.failure}
        if method != "eth_call":
            raise AssertionError(method)
        result = self.results.get(params[0]["data"], "0x" + (18).to_bytes(32, "big").hex())
        return {"jsonrpc": "2.0", "id": 1, "result": result}


def _reader(tmp_path):
    writer = Writer(str(tmp_path / "facts.sqlite3"))
    provider = _Provider()
    w3 = Web3(provider)
    w3.middleware_onion.clear()
    header = IndexedBlockRecord(1, 103, "0x" + "aa" * 32, "0x" + "bb" * 32, 1700000103)
    reader = BlockReader(writer.connection, chain_id=1, w3=w3, header_reader=lambda _: header)
    fn = w3.eth.contract(address="0x" + "11" * 20, abi=[{
        "type": "function", "name": "decimals", "inputs": [],
        "outputs": [{"type": "uint8"}], "stateMutability": "view",
    }]).functions.decimals()
    return writer, reader, provider, header, fn


def test_calls_use_block_hash_and_replay_without_network(tmp_path):
    writer, reader, provider, header, fn = _reader(tmp_path)
    assert reader.call(fn, 103) == 18
    assert provider.calls[0][1][1] == {"blockHash": header.block_hash, "requireCanonical": True}
    writer.transaction(reader.persist)
    provider.failure = AssertionError("Replay contacted RPC")
    offline = BlockReader(writer.connection, chain_id=1, w3=reader.w3, header_reader=None, offline=True)
    assert offline.call(fn, 103) == 18
    assert len(provider.calls) == 1
    with pytest.raises(MissingObservation, match="block header"):
        offline.call(fn, 104)


def test_optional_getter_records_revert_but_transport_failure_is_fatal(tmp_path):
    writer, reader, provider, header, fn = _reader(tmp_path)
    provider.failure = TimeoutError("RPC unavailable")
    with pytest.raises(TimeoutError):
        reader.call(fn, 103, optional=True)
    assert not reader.pending
    provider.failure = {"code": 3, "message": "execution reverted", "data": "0x"}
    assert reader.call(fn, 103, optional=True) is None
    with pytest.raises(ValueError, match="Required contract call reverted"):
        reader.call(fn, 103)
    writer.transaction(reader.persist)
    assert writer.fetchone("SELECT status FROM rpc_observations")[0] == "reverted"


def test_missing_observation_is_not_a_legitimate_empty_value(tmp_path):
    writer, reader, provider, header, fn = _reader(tmp_path)
    offline = BlockReader(writer.connection, chain_id=1, w3=reader.w3, header_reader=None, headers=[header], offline=True)
    with pytest.raises(MissingObservation, match="Missing call"):
        offline.call(fn, 103, optional=True)
    assert provider.calls == []


def test_receipt_must_match_selected_branch_even_when_stored(tmp_path):
    writer, reader, provider, header, fn = _reader(tmp_path)
    raw = replace(_make_transfer_raw(), block_hash=header.block_hash)
    reader.pending[(header.block_hash, "receipt", raw.tx_hash)] = (header, "ok", Web3.to_json({
        "blockHash": "0x" + "cc" * 32, "transactionHash": raw.tx_hash, "logs": [],
    }))
    with pytest.raises(BranchChanged):
        reader.receipt(raw)


def test_metadata_reads_reuse_observations_captured_by_the_contract_abi(tmp_path):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from backend.indexer.hydration import Hydrator
    from backend.indexer.types import TokenMetadata

    writer, reader, provider, header, fn = _reader(tmp_path)
    abi = json.loads((Path(__file__).parents[1] / "abis" / "ERC20.json").read_text())
    contract = reader.w3.eth.contract(address=fn.address, abi=abi)
    values = {"symbol": "TOKEN", "name": "Token name", "decimals": 6}
    for name, value in values.items():
        getter = getattr(contract.functions, name)()
        output_types = [item["type"] for item in getter.abi["outputs"]]
        provider.results[getter._encode_transaction_data()] = Web3.to_hex(reader.w3.codec.encode(output_types, [value]))
        assert reader.call(getter, 103, optional=name != "decimals") == value
    writer.transaction(reader.persist)
    provider.failure = AssertionError("Offline metadata read contacted RPC")
    offline = BlockReader(writer.connection, chain_id=1, w3=reader.w3, header_reader=None, offline=True)
    chain = SimpleNamespace(config=SimpleNamespace(chain_id=1), reader=offline)
    assert Hydrator(None).read_token_metadata(chain, fn.address, block_number=103) == TokenMetadata(
        1, fn.address.lower(), "TOKEN", "Token name", 6,
    )
    assert len(provider.calls) == 3
