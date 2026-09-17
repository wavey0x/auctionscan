from types import SimpleNamespace

from backend.indexer.discovery import FactoryDiscoverer


class FakeEth:
    def __init__(self, deploy_block: int) -> None:
        self.deploy_block = deploy_block

    def get_code(self, _address, block_identifier: int):
        return b"\x01" if block_identifier >= self.deploy_block else b""


class FakeWeb3:
    def __init__(self, deploy_block: int) -> None:
        self.eth = FakeEth(deploy_block)

    @staticmethod
    def to_checksum_address(address: str) -> str:
        return address


def test_resolve_contract_deploy_block_uses_binary_search():
    discoverer = FactoryDiscoverer.__new__(FactoryDiscoverer)
    discoverer._code_cache = {}
    chain = SimpleNamespace(
        config=SimpleNamespace(chain_id=1),
        w3=FakeWeb3(deploy_block=1234),
    )

    result = FactoryDiscoverer.resolve_contract_deploy_block(
        discoverer,
        chain,
        "0x00000000000000000000000000000000000000aa",
        upper_bound=5000,
    )

    assert result == 1234

