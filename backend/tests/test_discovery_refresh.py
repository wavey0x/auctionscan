from __future__ import annotations

from types import SimpleNamespace

from backend.indexer.discovery import FactoryDiscoverer
from backend.indexer.types import FactorySeed


CONFIGURED_FACTORY = "0x00000000000000000000000000000000000000aa"
DISCOVERED_FACTORY = "0x00000000000000000000000000000000000000bb"


class _FakeCall:
    def __init__(self, value):
        self._value = value

    def call(self, **kwargs):
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


class _FakeRegistryFunctions:
    def __init__(self, addresses, info_by_address):
        self._addresses = addresses
        self._info_by_address = info_by_address

    def getAllFactories(self):
        return _FakeCall(self._addresses)

    def factoryInfo(self, address):
        return _FakeCall(self._info_by_address[address])


class _FakeRegistryContract:
    def __init__(self, addresses, info_by_address):
        self.functions = _FakeRegistryFunctions(addresses, info_by_address)


class _FakeAbiRegistry:
    def __init__(self, registry_contract, versions: tuple[str, ...] = ("1.0.4",)):
        self._registry_contract = registry_contract
        self.settings = SimpleNamespace(versions={version: object() for version in versions})

    def registry_contract(self, _w3, _address):
        return self._registry_contract

    def version_definition(self, version: str):
        return SimpleNamespace(capability_family=version)


class _FakeWeb3:
    @staticmethod
    def to_checksum_address(address: str) -> str:
        return address


def test_refresh_factories_merges_configured_and_registry_factories():
    configured = FactorySeed(
        address=CONFIGURED_FACTORY,
        version="1.0.4",
        capability_family="1.0.4",
        start_block=123,
        deploy_block=123,
        deploy_block_source="config",
        discovery_source="config",
        enabled=True,
    )
    registry_contract = _FakeRegistryContract(
        [CONFIGURED_FACTORY, DISCOVERED_FACTORY],
        {
            CONFIGURED_FACTORY: ("1.0.4", "ignored", False),
            DISCOVERED_FACTORY: ("1.0.4", "ignored", False),
        },
    )
    discoverer = FactoryDiscoverer(_FakeAbiRegistry(registry_contract))
    resolve_calls = []

    def resolve_contract_deploy_block(chain, address, *, upper_bound):
        resolve_calls.append((chain.config.chain_id, address, upper_bound))
        return 456

    discoverer.resolve_contract_deploy_block = resolve_contract_deploy_block
    chain = SimpleNamespace(
        config=SimpleNamespace(
            chain_id=1,
            registry=SimpleNamespace(address="0x0000000000000000000000000000000000000abc"),
            factories=(configured,),
        ),
        w3=_FakeWeb3(),
    )

    result = discoverer.refresh_factories(chain, confirmed_head=2_000)
    seeds = result.factories

    assert resolve_calls == [(1, DISCOVERED_FACTORY, 2_000)]
    assert [(seed.address, seed.start_block, seed.deploy_block_source, seed.discovery_source) for seed in seeds] == [
        (CONFIGURED_FACTORY, 123, "config", "registry"),
        (DISCOVERED_FACTORY, 456, "binary_search", "registry"),
    ]


def test_refresh_factories_skips_unknown_registry_versions():
    registry_contract = _FakeRegistryContract(
        [DISCOVERED_FACTORY],
        {
            DISCOVERED_FACTORY: ("9.9.9", "ignored", False),
        },
    )
    discoverer = FactoryDiscoverer(_FakeAbiRegistry(registry_contract))
    chain = SimpleNamespace(
        config=SimpleNamespace(
            chain_id=1,
            registry=SimpleNamespace(address="0x0000000000000000000000000000000000000abc"),
            factories=(),
        ),
        w3=_FakeWeb3(),
    )

    result = discoverer.refresh_factories(chain, confirmed_head=2_000)
    seeds = result.factories

    assert seeds == []
    assert result.problems == [{"factory_address": DISCOVERED_FACTORY, "code": "unsupported_version", "version": "9.9.9"}]
    assert result.error is None


def test_refresh_factories_accepts_supported_1_0_5_registry_factory():
    registry_contract = _FakeRegistryContract(
        [DISCOVERED_FACTORY],
        {
            DISCOVERED_FACTORY: ("1.0.5", "ignored", False),
        },
    )
    discoverer = FactoryDiscoverer(_FakeAbiRegistry(registry_contract, versions=("1.0.5",)))
    discoverer.resolve_contract_deploy_block = lambda _chain, _address, *, upper_bound: 789
    chain = SimpleNamespace(
        config=SimpleNamespace(
            chain_id=1,
            registry=SimpleNamespace(address="0x0000000000000000000000000000000000000abc"),
            factories=(),
        ),
        w3=_FakeWeb3(),
    )

    result = discoverer.refresh_factories(chain, confirmed_head=2_000)
    seeds = result.factories

    assert len(seeds) == 1
    assert seeds[0].address == DISCOVERED_FACTORY
    assert seeds[0].version == "1.0.5"
    assert seeds[0].capability_family == "1.0.5"
    assert seeds[0].start_block == 789
