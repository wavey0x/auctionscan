from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from .chains import ChainState
from .decode import AbiRegistry
from .types import FactorySeed, normalize_address


@dataclass(frozen=True)
class DiscoveryResult:
    factories: list[FactorySeed]
    problems: list[dict]
    error: str | None = None


class FactoryDiscoverer:
    def __init__(self, abi_registry: AbiRegistry) -> None:
        self.abi_registry = abi_registry
        self._code_cache: dict[tuple[int, str, int], bool] = {}

    def _has_code(self, chain: ChainState, address: str, block_number: int) -> bool:
        cache_key = (chain.config.chain_id, address, block_number)
        if cache_key in self._code_cache:
            return self._code_cache[cache_key]
        code = chain.w3.eth.get_code(chain.w3.to_checksum_address(address), block_identifier=block_number)
        has_code = bool(code and bytes(code) != b"")
        self._code_cache[cache_key] = has_code
        return has_code

    def resolve_contract_deploy_block(
        self,
        chain: ChainState,
        address: str,
        *,
        upper_bound: int,
    ) -> int:
        normalized_address = normalize_address(address)
        if upper_bound < 0:
            raise ValueError("upper_bound must be non-negative")
        if not self._has_code(chain, normalized_address, upper_bound):
            raise ValueError(
                f"contract {normalized_address} has no runtime code at block {upper_bound}"
            )

        low = 0
        high = upper_bound
        while low < high:
            midpoint = (low + high) // 2
            if self._has_code(chain, normalized_address, midpoint):
                high = midpoint
            else:
                low = midpoint + 1
        return low

    def refresh_factories(
        self, chain: ChainState, *, confirmed_head: int, known_factories: Sequence[FactorySeed] = (),
    ) -> DiscoveryResult:
        merged = {factory.address: factory for factory in known_factories
                  if factory.version in self.abi_registry.settings.versions}
        merged.update({factory.address: factory for factory in chain.config.factories})
        problems = []
        error = None

        def result():
            return DiscoveryResult(sorted(merged.values(), key=lambda item: (item.start_block, item.address)), problems, error)

        if chain.config.registry is None:
            return result()

        registry = self.abi_registry.registry_contract(chain.w3, chain.config.registry.address)
        try:
            addresses = registry.functions.getAllFactories().call(block_identifier=confirmed_head)
        except Exception:
            error = "Registry lookup failed"
            return result()
        for raw_address in addresses:
            address = normalize_address(raw_address)
            existing = merged.get(address)
            try:
                info = registry.functions.factoryInfo(chain.w3.to_checksum_address(address)).call(block_identifier=confirmed_head)
            except Exception:
                problems.append({"factory_address": address, "code": "lookup_failed", "version": None})
                error = "Some factory lookups failed"
                continue

            version = str(info[0])
            is_retired = bool(info[2])
            if is_retired:
                continue
            if version not in self.abi_registry.settings.versions:
                problems.append({"factory_address": address, "code": "unsupported_version", "version": version})
                continue

            capability_family = self.abi_registry.version_definition(version).capability_family
            if existing and existing.start_block > 0:
                merged[address] = replace(
                    existing,
                    version=version,
                    capability_family=capability_family,
                    deploy_block=existing.deploy_block or existing.start_block,
                    deploy_block_source=existing.deploy_block_source or "config",
                    discovery_source="registry",
                )
                continue

            try:
                deploy_block = self.resolve_contract_deploy_block(
                    chain,
                    address,
                    upper_bound=confirmed_head,
                )
            except Exception:
                problems.append({"factory_address": address, "code": "deployment_unresolved", "version": version})
                error = "Some factory deployment blocks could not be resolved"
                continue
            merged[address] = FactorySeed(
                address=address,
                version=version,
                capability_family=capability_family,
                start_block=deploy_block,
                deploy_block=deploy_block,
                deploy_block_source="binary_search",
                discovery_source="registry",
                enabled=True,
            )

        return result()
