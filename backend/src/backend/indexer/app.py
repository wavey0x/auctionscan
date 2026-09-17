from __future__ import annotations

import argparse
import json
import logging

from .runtime import IndexerRuntime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Auctionscan indexer")
    mode = parser.add_mutually_exclusive_group()
    parser.add_argument("--db", help="Path to the SQLite database file")
    parser.add_argument(
        "--network",
        required=True,
        help="Configured network name this process will own",
    )
    mode.add_argument(
        "--watch",
        action="store_true",
        help="Run continuously instead of a single sync pass",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=None,
        help="Cap the number of blocks processed per chain in one pass",
    )
    mode.add_argument(
        "--reproject",
        action="store_true",
        help="Rebuild projections from stored facts instead of syncing new blocks",
    )
    mode.add_argument("--backfill-observations", action="store_true", help="Capture missing historical RPC facts for offline replay")
    mode.add_argument("--check-observations", action="store_true", help="Report replay input coverage without RPC calls")
    mode.add_argument(
        "--backfill-receiver-aliases",
        action="store_true",
        help="Fill missing receiver aliases from on-chain name() lookups",
    )
    parser.add_argument(
        "--takes-only",
        action="store_true",
        help="When reprojecting, rebuild only derived takes and take rollups",
    )
    parser.add_argument(
        "--force-alias-backfill",
        action="store_true",
        help="Ignore alias retry throttling and recheck receiver aliases now",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Runtime log level",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    if args.takes_only and not args.reproject:
        raise SystemExit("--takes-only requires --reproject")
    if args.force_alias_backfill and not args.backfill_receiver_aliases:
        raise SystemExit("--force-alias-backfill requires --backfill-receiver-aliases")
    runtime = IndexerRuntime(db_path=args.db, target_network=args.network)
    if args.backfill_observations or args.check_observations:
        result = runtime.backfill_observations(check_only=args.check_observations, max_blocks=args.max_blocks)
        print(json.dumps({args.network: result}, indent=2, sort_keys=True))
        return 0 if result["missing"] == 0 else 1
    if args.reproject:
        result = runtime.reproject(takes_only=args.takes_only)
        print(json.dumps({args.network: result}, indent=2, sort_keys=True))
        return 0
    if args.backfill_receiver_aliases:
        result = runtime.backfill_receiver_aliases(force=args.force_alias_backfill)
        print(
            json.dumps(
                {
                    args.network: {
                        "checked": result.checked,
                        "updated": result.updated,
                    }
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.watch:
        runtime.watch(max_blocks=args.max_blocks)
        return 0
    result = runtime.sync_once(max_blocks=args.max_blocks)
    print(json.dumps({args.network: result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
