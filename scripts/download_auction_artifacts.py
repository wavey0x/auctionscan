#!/usr/bin/env python3
"""Download ABI and verified source artifacts for tracked auction contracts.

This script uses the Etherscan v2 API and a checked-in manifest to build a
reference artifact set under `artifacts/auction_source/`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import requests


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "auction_source"
DEFAULT_MANIFEST = ARTIFACT_ROOT / "manifest.json"
ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"


def load_project_env() -> None:
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'} and len(value) >= 2:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_project_env()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to the tracked-auctions manifest JSON",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ARTIFACT_ROOT,
        help="Directory where artifacts should be written",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ETHERSCAN_API_KEY"),
        help="Etherscan API key. Defaults to ETHERSCAN_API_KEY from the environment.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.35,
        help="Delay between Etherscan requests to stay under rate limits",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Manifest must be a JSON array: {path}")
    return data


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)


def etherscan_request(
    session: requests.Session,
    *,
    api_key: str,
    chain_id: int,
    module: str,
    action: str,
    address: str,
) -> Dict[str, Any]:
    response = session.get(
        ETHERSCAN_V2_URL,
        params={
            "chainid": str(chain_id),
            "module": module,
            "action": action,
            "address": address,
            "apikey": api_key,
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "0":
        message = payload.get("message", "UNKNOWN")
        result = payload.get("result")
        raise RuntimeError(
            f"Etherscan {module}/{action} failed for {address}: {message} ({result})"
        )
    return payload


def parse_source_blob(source_blob: str) -> Tuple[str, Dict[str, Any] | None]:
    text = (source_blob or "").strip()
    if not text:
        return "empty", None

    candidates = []
    if text.startswith("{{") and text.endswith("}}"):
        candidates.append(text[1:-1])
    candidates.append(text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "sources" in parsed:
            return "standard-json", parsed

    return "flattened-solidity", None


def extract_sources(target_dir: Path, contract_name: str, source_blob: str) -> Dict[str, Any]:
    source_kind, source_json = parse_source_blob(source_blob)

    summary: Dict[str, Any] = {"source_kind": source_kind}
    sources_dir = target_dir / "sources"

    if source_kind == "standard-json" and source_json is not None:
        written_files = []
        for source_path, source_entry in source_json.get("sources", {}).items():
            if isinstance(source_entry, dict):
                content = source_entry.get("content", "")
            else:
                content = str(source_entry)
            destination = sources_dir / source_path
            write_text(destination, content)
            written_files.append(str(destination.relative_to(target_dir)))

        summary["source_files"] = sorted(written_files)
        return summary

    file_name = f"{contract_name or 'Auction'}.sol"
    write_text(sources_dir / file_name, source_blob)
    summary["source_files"] = [f"sources/{file_name}"]
    return summary


def process_entry(
    session: requests.Session,
    *,
    api_key: str,
    output_dir: Path,
    sleep_seconds: float,
    entry: Dict[str, Any],
) -> Dict[str, Any]:
    chain_id = int(entry["chain_id"])
    version = entry["version"]
    address = entry["auction_address"]
    entry_dir = output_dir / version / address
    entry_dir.mkdir(parents=True, exist_ok=True)

    source_payload = etherscan_request(
        session,
        api_key=api_key,
        chain_id=chain_id,
        module="contract",
        action="getsourcecode",
        address=address,
    )
    time.sleep(sleep_seconds)
    abi_payload = etherscan_request(
        session,
        api_key=api_key,
        chain_id=chain_id,
        module="contract",
        action="getabi",
        address=address,
    )
    time.sleep(sleep_seconds)

    source_row = source_payload["result"][0]
    abi_json = json.loads(abi_payload["result"])

    write_json(entry_dir / "abi.json", abi_json)

    source_summary = extract_sources(
        entry_dir,
        contract_name=source_row.get("ContractName") or "Auction",
        source_blob=source_row.get("SourceCode") or "",
    )

    metadata = {
        "chain_id": chain_id,
        "network": entry.get("network"),
        "version": version,
        "capability_family": entry.get("capability_family"),
        "auction_address": address,
        "factory_address": entry.get("factory_address"),
        "factory_source": entry.get("factory_source"),
        "reference_reason": entry.get("reference_reason"),
        "deployment_block": entry.get("deployment_block"),
        "deployment_tx_hash": entry.get("deployment_tx_hash"),
        "deployment_log_index": entry.get("deployment_log_index"),
        "contract_name": source_row.get("ContractName"),
        "compiler_version": source_row.get("CompilerVersion"),
        "optimization_used": source_row.get("OptimizationUsed"),
        "runs": source_row.get("Runs"),
        "evm_version": source_row.get("EVMVersion"),
        "license_type": source_row.get("LicenseType"),
        "proxy": source_row.get("Proxy"),
        "implementation": source_row.get("Implementation"),
        "constructor_arguments": source_row.get("ConstructorArguments"),
        "swarm_source": source_row.get("SwarmSource"),
        **source_summary,
    }
    return metadata


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print("ETHERSCAN_API_KEY is required", file=sys.stderr)
        return 1

    manifest = list(load_manifest(args.manifest))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    written = []
    for entry in manifest:
        written.append(
            process_entry(
                session,
                api_key=args.api_key,
                output_dir=args.output_dir,
                sleep_seconds=args.sleep_seconds,
                entry=entry,
            )
        )

    write_json(args.output_dir / "index.json", written)
    print(f"Wrote {len(written)} auction artifact bundles to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
