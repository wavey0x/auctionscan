from __future__ import annotations

import json
import logging
import time
from typing import Any

from web3 import HTTPProvider, Web3

from .address_aliases import (
    AddressAliasBackfillSummary,
    apply_address_alias_updates,
    load_address_alias_backfill_candidates,
    resolve_address_alias_updates_multicall,
)
from . import collection, replay
from .chains import ChainState
from .config import load_settings
from .decode import AbiRegistry
from .discovery import FactoryDiscoverer
from .hydration import Hydrator
from .observations import BlockReader, BranchChanged, MissingObservation
from .pricing import (
    PricingCaptureRuntime,
    delete_orphaned_pricing_queue_rows,
    enqueue_pricing_work,
    refresh_event_pricing,
)
from .pricing_projections import rebuild_pricing_projections
from .projections import (
    apply_batch,
    apply_batch_with_results,
    apply_native_event_projections,
    apply_take_event_projections,
    chain_start_block,
    clear_rebuildable_chain_state,
    clear_projection_state,
    clear_take_state,
    ensure_sync_state,
    load_tracked_auctions,
    load_tracked_factories,
    reconcile_round_statuses,
    rebuild_token_metadata,
    update_sync_state,
    upsert_tracked_factories,
)
from .facts import (
    delete_derived_take_events,
    persist_snapshot_facts,
    delete_fact_blocks_above,
    load_indexed_blocks,
    persist_raw_logs,
    upsert_indexed_blocks,
)
from .takes import TRANSFER_TOPIC, TakeDetector
from .types import (
    FactorySeed,
    IndexedBlockRecord,
    PreparedEvent,
    RawLogRecord,
    prepared_event_from_domain_row,
)
from .writer import ProcessLock, Writer


logger = logging.getLogger(__name__)
FACTORY_REFRESH_INTERVAL_SECONDS = 300.0


class IndexerRuntime:
    def __init__(self, *, db_path: str | None = None, target_network: str) -> None:
        self.settings = load_settings(db_path=db_path, target_network=target_network)
        self.network_name, self.chain_config = next(iter(self.settings.chains.items()))
        self._process_lock = ProcessLock(str(self.settings.paths.db_path), self.chain_config.chain_id)
        self.writer = Writer(str(self.settings.paths.db_path))
        self.abi_registry = AbiRegistry(self.settings)
        self.discoverer = FactoryDiscoverer(self.abi_registry)
        self.hydrator = Hydrator(self.abi_registry)
        self.take_detector = TakeDetector(self.abi_registry, self.hydrator)
        self.pricing = PricingCaptureRuntime()
        self.chain = ChainState.from_config(self.chain_config)
        self.discovery_chain = ChainState(self.chain_config, Web3(HTTPProvider(
            self.chain_config.rpc_url, request_kwargs={"timeout": 5}, exception_retry_configuration=None,
        ), middleware=[]))
        self._factory_seeds: tuple[FactorySeed, ...] | None = None
        self._factory_refresh_attempted_at: float | None = None
        self._factory_refresh_interval_seconds = FACTORY_REFRESH_INTERVAL_SECONDS

    def sync_once(self, *, max_blocks: int | None = None) -> int:
        return self.sync_chain_once(max_blocks=max_blocks)

    def watch(self, *, max_blocks: int | None = None) -> None:
        sleep_seconds = self.chain.config.poll_interval_seconds
        while True:
            try:
                self.sync_chain_once(max_blocks=max_blocks)
                state = self._load_sync_state_row()
                if any(factory.enabled for factory in self._factory_seeds or ()) and state["latest_rpc_head"] is not None and int(state["last_live_processed"]) < int(state["latest_rpc_head"]):
                    continue
            except Exception as exc:
                logger.exception("watch loop failed for chain %s", self.network_name)
                self._mark_chain_error(exc)
            time.sleep(sleep_seconds)

    def reproject(self, *, takes_only: bool = False) -> int:
        return self.reproject_chain(takes_only=takes_only)


    def backfill_receiver_aliases(
        self,
        *,
        force: bool = False,
    ) -> AddressAliasBackfillSummary:
        chain_id = self.chain.config.chain_id
        candidates = load_address_alias_backfill_candidates(
            self.writer.connection,
            chain_id=chain_id,
            force=force,
        )
        if not candidates:
            logger.info(
                "receiver alias backfill idle network=%s chain_id=%d",
                self.network_name,
                chain_id,
            )
            return AddressAliasBackfillSummary(checked=0, updated=0)

        logger.info(
            "receiver alias backfill start network=%s chain_id=%d candidates=%d",
            self.network_name,
            chain_id,
            len(candidates),
        )
        try:
            updates = resolve_address_alias_updates_multicall(
                self.chain,
                [item.address for item in candidates],
            )
        except Exception as exc:
            logger.warning(
                "receiver alias backfill failed network=%s chain_id=%d error=%s",
                self.network_name,
                chain_id,
                exc,
            )
            return AddressAliasBackfillSummary(checked=0, updated=0)

        updated_count = self.writer.transaction(
            lambda conn: apply_address_alias_updates(conn, updates)
        )
        logger.info(
            "receiver alias backfill complete network=%s chain_id=%d checked=%d updated=%d",
            self.network_name,
            chain_id,
            len(updates),
            updated_count,
        )
        return AddressAliasBackfillSummary(checked=len(updates), updated=updated_count)

    def sync_chain_once(self, *, max_blocks: int | None = None) -> int:
        chain = self.chain
        chain.reader = None
        latest_head = chain.latest_head()
        self._observed_head = chain.block_header(latest_head)
        self._observed_finality = chain.confirmed_header(latest_head)
        self._finality_warning = None
        confirmed_head = self._observed_finality.block_number
        if confirmed_head > latest_head:
            raise BranchChanged("RPC finality head exceeds its latest head")
        existing_state = self.writer.fetchone("SELECT finality_mode, last_success_at FROM sync_state WHERE chain_id = ?", (chain.config.chain_id,))
        if existing_state is not None and existing_state["finality_mode"] is None and existing_state["last_success_at"] is not None:
            raise MissingObservation("Prepare this database with its saved previous application revision before using the current indexer")
        verified_finality = existing_state is not None and existing_state["finality_mode"] == "finalized"
        if verified_finality:
            self._verify_finality_anchors()
            confirmed_head = self._observed_finality.block_number
        factory_seeds = self._refresh_factory_seeds(self.discovery_chain, confirmed_head=confirmed_head)
        if not any(factory.enabled for factory in factory_seeds):
            # Do not advance an empty scan past history we have not discovered yet.
            return 0
        start_block = chain_start_block(chain.config, factory_seeds)
        known_factories = {
            row["factory_address"]: row for row in self.writer.fetchall(
                "SELECT factory_address, start_block, active_flag FROM tracked_factories WHERE chain_id = ?",
                (chain.config.chain_id,),
            )
        }
        reset_from = min((factory.start_block for factory in factory_seeds
                          if factory.enabled and (factory.address not in known_factories
                          or not known_factories[factory.address]["active_flag"]
                          or factory.start_block < int(known_factories[factory.address]["start_block"]))),
                         default=None)
        previous_state = self.writer.fetchone("SELECT last_live_processed, last_confirmed_processed FROM sync_state WHERE chain_id = ?",
                                              (chain.config.chain_id,))
        rewind = (reset_from is not None and previous_state is not None
                  and reset_from <= int(previous_state["last_live_processed"]))
        boundary = min(reset_from - 1, int(previous_state["last_confirmed_processed"])) if rewind else -1
        rewind_header = chain.block_header(boundary) if boundary >= 0 else None

        def bootstrap(conn) -> list[Any]:
            ensure_sync_state(conn, chain.config, start_block)
            inserted_factories = upsert_tracked_factories(
                conn, chain.config.chain_id, factory_seeds
            )
            if rewind:
                if rewind_header is not None:
                    upsert_indexed_blocks(conn, [rewind_header])
                self._recover_live_tail_reorg(
                    conn, ancestor_block=boundary, latest_rpc_head=latest_head,
                    confirmed_head=confirmed_head, last_confirmed_processed=boundary,
                    record_reorg=False,
                )
            return inserted_factories

        inserted_factories = self.writer.transaction(bootstrap)
        self._log_inserted_factories(inserted_factories)
        if not verified_finality:
            self._verify_finality_anchors()
        confirmed_head = self._observed_finality.block_number
        reorg_recovered = self._verify_live_tail(
            latest_rpc_head=latest_head,
            confirmed_head=confirmed_head,
        )
        state = self._load_sync_state_row()
        last_confirmed_processed = int(state["last_confirmed_processed"])
        last_live_processed = int(state["last_live_processed"])
        next_block = last_live_processed + 1

        native_inserted_events: list[PreparedEvent] = []
        take_inserted_events: list[PreparedEvent] = []
        batch_mode: str | None = None
        sync_target: dict[str, int | float] | None = None
        batch_from: int | None = None
        batch_to: int | None = None

        if next_block <= latest_head:
            batch_mode = "confirmed" if next_block <= confirmed_head else "live"
            upper_bound = confirmed_head if batch_mode == "confirmed" else latest_head
            to_block = min(upper_bound, next_block + chain.config.block_batch_size - 1)
            if max_blocks is not None:
                to_block = min(to_block, next_block + max_blocks - 1)
            sync_target = self._progress_snapshot(
                start_block=start_block,
                confirmed_head=confirmed_head,
                processed_block=min(to_block, confirmed_head),
            )
            batch_from = next_block
            batch_to = to_block
            logger.info(
                "indexer sync network=%s mode=%s blocks=%d-%d confirmed_head=%d latest_rpc_head=%d progress_target=%.2f%% done=%d/%d remaining=%d",
                self.network_name,
                batch_mode,
                next_block,
                to_block,
                confirmed_head,
                latest_head,
                sync_target["percent"],
                sync_target["done"],
                sync_target["total"],
                sync_target["remaining"],
            )

            live_headers = self._load_block_headers(next_block, to_block) if batch_mode == "live" else []
            reader = BlockReader(
                self.writer.connection, chain_id=chain.config.chain_id,
                w3=getattr(chain, "w3", None), header_reader=chain.block_header, headers=live_headers,
            )
            reader.log_hashes = {header.block_number: header.block_hash for header in live_headers} if live_headers else None
            chain.reader = reader
            batch_tip = reader.header(to_block)
            if live_headers:
                previous = chain.block_header(next_block - 1) if next_block > 0 else None
                stored_parent = self.writer.fetchone(
                    "SELECT block_hash FROM indexed_blocks WHERE chain_id = ? AND block_number = ?",
                    (chain.config.chain_id, next_block - 1),
                )
                if stored_parent is not None and previous.block_hash != stored_parent["block_hash"]:
                    raise BranchChanged("Indexed parent changed during batch preparation")
                for header in live_headers:
                    if previous is not None and header.parent_hash != previous.block_hash:
                        raise BranchChanged("Incoming block headers do not form one branch")
                    previous = header

            tracked_factories = load_tracked_factories(self.writer.connection, chain.config.chain_id)
            factory_events = collection.scan_factory_events(
                chain, self.abi_registry, self.hydrator, tracked_factories, next_block, to_block
            )
            tracked_auctions = load_tracked_auctions(self.writer.connection, chain.config.chain_id)
            for prepared in factory_events:
                if prepared.domain_event.event_name == "DeployedNewAuction":
                    tracked_auctions.append(
                        {
                            "auction_address": prepared.domain_event.auction_address,
                            "version": prepared.domain_event.version,
                        }
                    )
            auction_events = collection.scan_auction_events(
                chain, self.abi_registry, self.hydrator, tracked_auctions, next_block, to_block
            )
            prepared_events = sorted(
                factory_events + auction_events,
                key=lambda item: (
                    item.raw_log.block_number,
                    item.raw_log.tx_index,
                    item.raw_log.log_index,
                ),
            )
            transfer_logs, take_events = self.take_detector.scan_window(
                chain, self.writer.connection, from_block=next_block, to_block=to_block,
                native_events=prepared_events,
            )
            for prepared in prepared_events + take_events:
                reader.header(prepared.raw_log.block_number, expected_hash=prepared.raw_log.block_hash)
            for raw_log in transfer_logs:
                reader.header(raw_log.block_number, expected_hash=raw_log.block_hash)
            if chain.block_header(to_block).block_hash != batch_tip.block_hash:
                raise BranchChanged("Canonical branch changed during collection")
            # Headers observed outside the live contiguous tail (historical facts)
            # must also still agree with the provider before adopting their inputs.
            for number, header in reader.headers.items():
                if number != to_block and not live_headers and chain.block_header(number).block_hash != header.block_hash:
                    raise BranchChanged(f"Canonical branch changed at block {number}")

            def persist_batch(conn) -> tuple[list[PreparedEvent], list[PreparedEvent]]:
                inserted_native_events = apply_batch_with_results(conn, prepared_events)
                reader.persist(conn)
                persist_raw_logs(conn, transfer_logs)
                inserted_take_events = apply_batch_with_results(conn, take_events)
                enqueue_pricing_work(conn, inserted_native_events + inserted_take_events)
                refresh_event_pricing(conn, chain_id=chain.config.chain_id,
                                      events=inserted_native_events + inserted_take_events)
                if batch_mode == "confirmed":
                    reconcile_round_statuses(
                        conn,
                        chain.config.chain_id,
                        batch_tip.timestamp,
                    )
                    self._update_state(
                        conn,
                        chain_id=chain.config.chain_id,
                        network_name=chain.config.name,
                        latest_rpc_head=latest_head,
                        confirmed_head=confirmed_head,
                        last_confirmed_processed=to_block,
                        last_live_processed=to_block,
                        health="ok",
                        last_error=None,
                    )
                else:
                    reconcile_round_statuses(conn, chain.config.chain_id, batch_tip.timestamp)
                    self._update_state(
                        conn,
                        chain_id=chain.config.chain_id,
                        network_name=chain.config.name,
                        latest_rpc_head=latest_head,
                        confirmed_head=confirmed_head,
                        last_confirmed_processed=last_confirmed_processed,
                        last_live_processed=to_block,
                        health="ok",
                        last_error=None,
                    )
                return inserted_native_events, inserted_take_events

            native_inserted_events, take_inserted_events = self.writer.transaction(persist_batch)
            self._log_inserted_events(native_inserted_events)
            self._log_inserted_events(take_inserted_events)

        promoted_blocks = self._promote_confirmed_blocks(
            latest_rpc_head=latest_head,
            confirmed_head=confirmed_head,
        )
        inserted_events = native_inserted_events + take_inserted_events
        pricing = getattr(self, "pricing", None)
        if pricing is not None:
            pricing.poll(self.writer, chain_id=chain.config.chain_id)

        total_inserted = len(inserted_events)
        if total_inserted == 0 and promoted_blocks == 0 and not reorg_recovered:
            state = self._load_sync_state_row()
            idle_progress = self._progress_snapshot(
                start_block=start_block,
                confirmed_head=confirmed_head,
                processed_block=min(int(state["last_confirmed_processed"]), confirmed_head),
            )
            self.writer.transaction(
                lambda conn: self._update_state(
                    conn,
                    chain_id=chain.config.chain_id,
                    network_name=chain.config.name,
                    latest_rpc_head=latest_head,
                    confirmed_head=confirmed_head,
                    last_confirmed_processed=int(state["last_confirmed_processed"]),
                    last_live_processed=int(state["last_live_processed"]),
                    health="idle",
                    last_error=None,
                )
            )
            logger.info(
                "indexer idle network=%s confirmed_head=%d latest_rpc_head=%d live_processed=%d progress=%.2f%% done=%d/%d",
                self.network_name,
                confirmed_head,
                latest_head,
                int(state["last_live_processed"]),
                idle_progress["percent"],
                idle_progress["done"],
                idle_progress["total"],
            )
            return 0

        final_state = self._load_sync_state_row()
        if sync_target is None:
            sync_target = self._progress_snapshot(
                start_block=start_block,
                confirmed_head=confirmed_head,
                processed_block=min(int(final_state["last_confirmed_processed"]), confirmed_head),
            )
        logger.info(
            "indexer synced network=%s mode=%s blocks=%s-%s confirmed_head=%d latest_rpc_head=%d last_confirmed=%d last_live=%d progress=%.2f%% done=%d/%d remaining=%d inserted_native=%d inserted_take=%d promoted=%d reorg_recovered=%s",
            self.network_name,
            batch_mode or "promotion_only",
            batch_from if batch_from is not None else "-",
            batch_to if batch_to is not None else "-",
            confirmed_head,
            latest_head,
            int(final_state["last_confirmed_processed"]),
            int(final_state["last_live_processed"]),
            sync_target["percent"],
            sync_target["done"],
            sync_target["total"],
            sync_target["remaining"],
            len(native_inserted_events),
            len(take_inserted_events),
            promoted_blocks,
            reorg_recovered,
        )
        return total_inserted

    def _refresh_factory_seeds(
        self,
        chain: ChainState,
        *,
        confirmed_head: int,
    ) -> list[FactorySeed]:
        now = time.monotonic()
        cached = getattr(self, "_factory_seeds", None)
        refreshed_at = getattr(self, "_factory_refresh_attempted_at", None)
        refresh_interval = getattr(
            self,
            "_factory_refresh_interval_seconds",
            FACTORY_REFRESH_INTERVAL_SECONDS,
        )
        if (
            cached is not None
            and refreshed_at is not None
            and now - refreshed_at < refresh_interval
        ):
            return list(cached)

        known = list(cached) if cached is not None else [FactorySeed(
            address=row["factory_address"], version=row["version"], capability_family=row["capability_family"],
            start_block=row["start_block"], deploy_block=row["deploy_block"], deploy_block_source=row["deploy_block_source"],
            discovery_source=row["discovery_source"], enabled=bool(row["active_flag"]),
        ) for row in self.writer.fetchall("SELECT * FROM tracked_factories WHERE chain_id = ?", (chain.config.chain_id,))]
        previous_row = self.writer.fetchone("SELECT discovery_status_json FROM sync_state WHERE chain_id = ?", (chain.config.chain_id,))
        previous = json.loads(previous_row[0]) if previous_row and previous_row[0] else {}
        self._factory_refresh_attempted_at = now
        result = self.discoverer.refresh_factories(chain, confirmed_head=confirmed_head, known_factories=known)
        seeds = result.factories
        problems = {(problem["factory_address"], problem["code"]): problem for problem in previous.get("problems", [])} if result.error else {}
        problems.update({(problem["factory_address"], problem["code"]): problem for problem in result.problems})
        attempted_at = int(time.time())
        status = {
            "last_attempt_at": attempted_at,
            "last_success_at": previous.get("last_success_at") if result.error else attempted_at,
            "last_error": result.error,
            "known_factory_count": sum(factory.enabled for factory in seeds),
            "problems": sorted(problems.values(), key=lambda problem: (problem["factory_address"], problem["code"])),
        }

        def save_status(conn):
            ensure_sync_state(conn, chain.config, chain_start_block(chain.config, seeds))
            conn.execute("UPDATE sync_state SET discovery_status_json = ? WHERE chain_id = ?",
                         (json.dumps(status, separators=(",", ":")), chain.config.chain_id))

        self.writer.transaction(save_status)
        self._factory_seeds = tuple(seeds)
        return list(seeds)

    def reproject_chain(self, *, takes_only: bool = False) -> int:
        chain = self.chain
        pricing = getattr(self, "pricing", None)
        if pricing is not None:
            pricing.discard()
        state = self.writer.fetchone("SELECT * FROM sync_state WHERE chain_id = ?", (chain.config.chain_id,))
        reader = BlockReader(
            self.writer.connection, chain_id=chain.config.chain_id,
            w3=getattr(chain, "w3", None), header_reader=None, offline=True,
        )
        chain.reader = reader
        checkpoint = int(state["last_live_processed"]) if state and state["last_live_processed"] is not None else -1
        checkpoint_timestamp = reader.header(checkpoint).timestamp if checkpoint >= 0 else None
        # Prepare and validate every required input before touching the current projections.
        native_events = replay.load_native_events(self.writer.connection, chain, self.hydrator)
        take_events = self.take_detector.replay_chain(chain, self.writer.connection)

        def replace_projections(conn):
            delete_derived_take_events(conn, chain.config.chain_id)
            if takes_only:
                clear_take_state(conn, chain.config.chain_id)
                rebuild_token_metadata(conn, chain.config.chain_id, native_events)
            else:
                clear_projection_state(conn, chain.config.chain_id)
                apply_native_event_projections(conn, native_events)
            inserted = apply_batch(conn, take_events)
            if checkpoint_timestamp is not None:
                reconcile_round_statuses(conn, chain.config.chain_id, checkpoint_timestamp)
            rebuild_pricing_projections(conn, chain_id=chain.config.chain_id)
            # Maintenance does not assert anything about RPC freshness or clear sync errors.
            return inserted

        take_count = self.writer.transaction(replace_projections)
        return (0 if takes_only else len(native_events)) + take_count

    def _update_state(self, conn, **kwargs) -> None:
        update_sync_state(
            conn, **kwargs, observed_head=getattr(self, "_observed_head", None),
            observed_finality=getattr(self, "_observed_finality", None),
            finality_mode=self.chain.finality_mode,
            finality_warning=getattr(self, "_finality_warning", None),
        )

    def _verify_finality_anchors(self) -> None:
        state = self._load_sync_state_row()
        if self.chain.finality_mode != "finalized":
            return
        anchors = [(state["last_confirmed_processed"], state["last_confirmed_hash"]),
                   (state["confirmed_head"], state["confirmed_head_hash"])]
        verified_headers = {}
        for number, block_hash in set(anchors):
            if number is None or block_hash is None:
                continue
            if int(number) > self._observed_head.block_number:
                raise RuntimeError("RPC head is behind a previously verified finalized anchor")
            header = self.chain.block_header(int(number))
            if header.block_hash != block_hash:
                raise RuntimeError(f"Conflicting finalized anchor at block {number}; advancement stopped")
            verified_headers[int(number)] = header
        canonical = self.chain.block_header(self._observed_finality.block_number)
        if canonical.block_hash != self._observed_finality.block_hash:
            raise RuntimeError("RPC finalized block is not on its canonical branch")
        if state["confirmed_head"] is not None and state["confirmed_head_hash"] is not None and self._observed_finality.block_number < int(state["confirmed_head"]):
            self._finality_warning = f"RPC finalized head regressed to {self._observed_finality.block_number}"
            # Keep the last verified, monotonic finality observation. Its hash
            # was checked above; a stale tag must not erase a trusted anchor.
            self._observed_finality = verified_headers[int(state["confirmed_head"])]

    def _load_sync_state_row(self):
        row = self.writer.fetchone(
            "SELECT * FROM sync_state WHERE chain_id = ?",
            (self.chain.config.chain_id,),
        )
        if row is None:
            raise RuntimeError(f"missing sync_state row for chain_id={self.chain.config.chain_id}")
        return row

    def _load_block_headers(self, from_block: int, to_block: int) -> list[IndexedBlockRecord]:
        return [self.chain.block_header(block_number) for block_number in range(from_block, to_block + 1)]

    def _validate_live_tail_rows(
        self,
        *,
        last_confirmed_processed: int,
        last_live_processed: int,
        rows,
    ) -> None:
        expected_count = last_live_processed - last_confirmed_processed
        if expected_count <= 0:
            if rows:
                raise RuntimeError(
                    f"live-tail integrity error: expected no indexed_blocks rows for chain_id={self.chain.config.chain_id}"
                )
            return
        if len(rows) != expected_count:
            raise RuntimeError(
                f"live-tail integrity error: chain_id={self.chain.config.chain_id} expected_rows={expected_count} actual_rows={len(rows)}"
            )
        expected_block = last_confirmed_processed + 1
        previous_hash = None
        for row in rows:
            block_number = int(row["block_number"])
            if block_number != expected_block:
                raise RuntimeError(
                    f"live-tail integrity error: chain_id={self.chain.config.chain_id} expected_block={expected_block} actual_block={block_number}"
                )
            if previous_hash is not None and row["parent_hash"] != previous_hash:
                raise RuntimeError("Stored live headers do not form one branch")
            previous_hash = row["block_hash"]
            expected_block += 1

    def _verify_live_tail(
        self,
        *,
        latest_rpc_head: int,
        confirmed_head: int,
    ) -> bool:
        state = self._load_sync_state_row()
        last_confirmed_processed = int(state["last_confirmed_processed"])
        last_live_processed = int(state["last_live_processed"])
        if last_live_processed <= last_confirmed_processed:
            stale_count = self.writer.connection.execute(
                "SELECT COUNT(*) AS cnt FROM indexed_blocks WHERE chain_id = ? AND block_number > ?",
                (self.chain.config.chain_id, last_live_processed),
            ).fetchone()["cnt"]
            if stale_count:
                raise RuntimeError(
                    f"live-tail integrity error: expected no indexed_blocks rows for chain_id={self.chain.config.chain_id}"
                )
            return False

        rows = load_indexed_blocks(
            self.writer.connection,
            chain_id=self.chain.config.chain_id,
            descending=False,
            from_block=last_confirmed_processed + 1,
        )
        self._validate_live_tail_rows(
            last_confirmed_processed=last_confirmed_processed,
            last_live_processed=last_live_processed,
            rows=rows,
        )
        if latest_rpc_head >= last_live_processed:
            current_tip = self.chain.block_header(last_live_processed)
            if current_tip.block_hash == rows[-1]["block_hash"]:
                return False

        ancestor_block: int | None = None
        for row in reversed(rows):
            if int(row["block_number"]) > latest_rpc_head:
                continue
            current_header = self.chain.block_header(int(row["block_number"]))
            if current_header.block_hash == row["block_hash"]:
                ancestor_block = int(row["block_number"])
                break
        if ancestor_block is None:
            if last_confirmed_processed >= 0:
                boundary_header = self.chain.block_header(last_confirmed_processed)
                if boundary_header.block_hash == rows[0]["parent_hash"]:
                    ancestor_block = last_confirmed_processed
                else:
                    ancestor_block = last_confirmed_processed - 1
            else:
                ancestor_block = -1
        if ancestor_block < last_confirmed_processed:
            raise RuntimeError(
                "live-tail divergence crossed the confirmed boundary "
                f"chain_id={self.chain.config.chain_id} ancestor={ancestor_block} last_confirmed={last_confirmed_processed}"
            )

        logger.warning(
            "live-tail reorg detected network=%s chain_id=%d ancestor=%d last_confirmed=%d last_live=%d",
            self.network_name,
            self.chain.config.chain_id,
            ancestor_block,
            last_confirmed_processed,
            last_live_processed,
        )
        self.writer.transaction(
            lambda conn: self._recover_live_tail_reorg(
                conn,
                ancestor_block=ancestor_block,
                latest_rpc_head=latest_rpc_head,
                confirmed_head=confirmed_head,
                last_confirmed_processed=last_confirmed_processed,
            )
        )
        return True

    def _recover_live_tail_reorg(
        self,
        conn,
        *,
        ancestor_block: int,
        latest_rpc_head: int,
        confirmed_head: int,
        last_confirmed_processed: int,
        record_reorg: bool = True,
    ) -> None:
        started = time.perf_counter()
        # Maintenance must repair the prefix even when its removed suffix is empty.
        replay_skipped = (
            record_reorg
            and conn.execute(
                "SELECT 1 FROM domain_events WHERE chain_id = ? AND block_number > ? LIMIT 1",
                (self.chain.config.chain_id, ancestor_block),
            ).fetchone()
            is None
        )
        delete_fact_blocks_above(
            conn,
            chain_id=self.chain.config.chain_id,
            ancestor_block=ancestor_block,
        )
        self.chain.reader = BlockReader(
            conn,
            chain_id=self.chain.config.chain_id,
            w3=getattr(self.chain, "w3", None),
            header_reader=None,
            offline=True,
        )
        if not replay_skipped:
            clear_rebuildable_chain_state(conn, self.chain.config.chain_id)
            native_events = replay.load_native_events(conn, self.chain, self.hydrator)
            apply_native_event_projections(conn, native_events)
            take_events = replay.load_take_events(conn, self.chain, self.hydrator)
            apply_take_event_projections(conn, take_events)
        delete_orphaned_pricing_queue_rows(conn, chain_id=self.chain.config.chain_id)
        if ancestor_block >= 0:
            header = conn.execute(
                "SELECT timestamp FROM indexed_blocks WHERE chain_id = ? AND block_number = ?",
                (self.chain.config.chain_id, ancestor_block),
            ).fetchone()
            if header is None:
                raise MissingObservation(f"Missing ancestor timestamp at {ancestor_block}")
            reconcile_round_statuses(conn, self.chain.config.chain_id, int(header["timestamp"]))
        pricing_seconds = 0.0
        if not replay_skipped:
            pricing_started = time.perf_counter()
            rebuild_pricing_projections(conn, chain_id=self.chain.config.chain_id)
            pricing_seconds = time.perf_counter() - pricing_started
        state_row = conn.execute(
            "SELECT reorg_count FROM sync_state WHERE chain_id = ?",
            (self.chain.config.chain_id,),
        ).fetchone()
        reorg_count = (int(state_row["reorg_count"]) if state_row is not None else 0) + int(record_reorg)
        self._update_state(
            conn,
            chain_id=self.chain.config.chain_id,
            network_name=self.chain.config.name,
            latest_rpc_head=latest_rpc_head,
            confirmed_head=confirmed_head,
            last_confirmed_processed=last_confirmed_processed,
            last_live_processed=ancestor_block,
            last_reorg_at=int(time.time()) if record_reorg else None,
            reorg_count=reorg_count,
            health="ok",
            last_error=None,
        )
        logger.info(
            "live-tail recovery prepared network=%s ancestor=%d replay_skipped=%s "
            "elapsed_seconds=%.6f pricing_rebuild_seconds=%.6f",
            self.network_name,
            ancestor_block,
            replay_skipped,
            time.perf_counter() - started,
            pricing_seconds,
        )

    def _promote_confirmed_blocks(
        self,
        *,
        latest_rpc_head: int,
        confirmed_head: int,
    ) -> int:
        state = self._load_sync_state_row()
        old_confirmed = int(state["last_confirmed_processed"])
        last_live_processed = int(state["last_live_processed"])
        new_confirmed = min(last_live_processed, confirmed_head)
        if new_confirmed <= old_confirmed:
            return 0

        stored = self.writer.fetchone(
            "SELECT * FROM indexed_blocks WHERE chain_id = ? AND block_number = ?",
            (self.chain.config.chain_id, new_confirmed),
        )
        if stored is None or self.chain.block_header(new_confirmed).block_hash != stored["block_hash"]:
            raise BranchChanged("Cannot finalize an unverified indexed block")

        def promote(conn) -> None:
            self._update_state(
                conn,
                chain_id=self.chain.config.chain_id,
                network_name=self.chain.config.name,
                latest_rpc_head=latest_rpc_head,
                confirmed_head=confirmed_head,
                last_confirmed_processed=new_confirmed,
                last_live_processed=last_live_processed,
                health="ok",
                last_error=None,
            )

        self.writer.transaction(promote)
        return new_confirmed - old_confirmed


    def backfill_observations(self, *, check_only: bool = False, max_blocks: int | None = None) -> dict:
        """Resume from missing facts; no separate job or coverage state is needed."""
        chain = self.chain
        conn = self.writer.connection
        state = conn.execute("SELECT * FROM sync_state WHERE chain_id = ?", (chain.config.chain_id,)).fetchone()
        fact_blocks = {int(row[0]) for row in conn.execute("SELECT DISTINCT block_number FROM chain_logs WHERE chain_id = ?", (chain.config.chain_id,))}
        if state is not None and state["finality_mode"] is None and (state["last_success_at"] is not None or fact_blocks):
            raise MissingObservation("Prepare this database with its saved previous application revision before observation backfill")
        for table in ("auction_snapshot_facts", "round_param_snapshot"):
            if conn.execute(f"SELECT 1 FROM {table} WHERE chain_id = ? AND (block_hash IS NULL OR param_schema IS NULL) LIMIT 1", (chain.config.chain_id,)).fetchone():
                raise MissingObservation(f"Unprepared {table} provenance; use the saved previous application revision")
        blocks = set(fact_blocks)
        if state and state["last_live_processed"] is not None and int(state["last_live_processed"]) >= 0:
            blocks.add(int(state["last_live_processed"]))
        complete = captured = 0
        first_missing = None
        for number in sorted(blocks):
            native_rows = conn.execute("SELECT * FROM domain_events WHERE chain_id = ? AND block_number = ? AND event_name != 'Take' ORDER BY tx_index, log_index", (chain.config.chain_id, number)).fetchall()
            raw_rows = conn.execute("SELECT * FROM chain_logs WHERE chain_id = ? AND block_number = ? AND topic0 = ? ORDER BY tx_index, log_index", (chain.config.chain_id, number, TRANSFER_TOPIC)).fetchall()
            raw_logs = [RawLogRecord(**dict(row)) for row in raw_rows]

            def prepare(offline):
                reader = BlockReader(conn, chain_id=chain.config.chain_id, w3=getattr(chain, "w3", None),
                                     header_reader=chain.block_header, offline=offline)
                chain.reader = reader
                reader.header(number)
                for row in conn.execute("SELECT DISTINCT block_hash FROM chain_logs WHERE chain_id = ? AND block_number = ?",
                                        (chain.config.chain_id, number)):
                    reader.header(number, expected_hash=row[0])
                native = []
                for row in native_rows:
                    reader.header(number, expected_hash=row["block_hash"])
                    native.append(
                        replay.prepared_from_domain_event_row(conn, chain, self.hydrator, row)
                        if offline
                        else collection.hydrate_native_event(
                            chain, self.hydrator, prepared_event_from_domain_row(row)
                        )
                    )
                self.take_detector._token_metadata_cache.clear()
                self.take_detector._derive_take_events(chain, conn, raw_logs, native_events=native)
                return reader, native

            try:
                reader, native = prepare(True)
                needs_capture = False
            except MissingObservation as exc:
                first_missing = first_missing or str(exc)
                if check_only or (max_blocks is not None and captured >= max_blocks):
                    continue
                reader, native = prepare(False)
                needs_capture = True
            if not check_only and chain.block_header(number).block_hash != reader.header(number).block_hash:
                raise BranchChanged(f"Stored observations changed branch at {number}")
            if not needs_capture:
                complete += 1
                continue

            def persist(conn):
                reader.persist(conn)
                persist_snapshot_facts(conn, native)
                # Validate the captured inputs before committing the block.
                prepare(True)
            self.writer.transaction(persist)
            captured += 1
            complete += 1
            logger.info("observation backfill network=%s block=%d complete=%d/%d", self.network_name, number, complete, len(blocks))
        return {"blocks": len(blocks), "complete": complete, "missing": len(blocks) - complete,
                "captured": captured, "first_missing": first_missing if complete < len(blocks) else None}


    def _mark_chain_error(self, exc: Exception) -> None:
        chain = self.chain
        state = self.writer.fetchone(
            "SELECT last_confirmed_processed, last_live_processed FROM sync_state WHERE chain_id = ?",
            (chain.config.chain_id,),
        )
        last_confirmed_processed = (
            int(state["last_confirmed_processed"])
            if state and state["last_confirmed_processed"] is not None
            else -1
        )
        last_live_processed = (
            int(state["last_live_processed"])
            if state and state["last_live_processed"] is not None
            else last_confirmed_processed
        )
        previous = self.writer.fetchone("SELECT latest_rpc_head, confirmed_head FROM sync_state WHERE chain_id = ?", (chain.config.chain_id,))
        latest_head = int(previous["latest_rpc_head"]) if previous and previous["latest_rpc_head"] is not None else last_live_processed
        confirmed_head = int(previous["confirmed_head"]) if previous and previous["confirmed_head"] is not None else last_confirmed_processed
        self.writer.transaction(
            lambda conn: update_sync_state(
                conn,
                chain_id=chain.config.chain_id,
                network_name=chain.config.name,
                latest_rpc_head=latest_head,
                confirmed_head=confirmed_head,
                last_confirmed_processed=last_confirmed_processed,
                last_live_processed=last_live_processed,
                health="error",
                last_error=str(exc),
                touch_success_at=False,
            )
        )

    def _log_inserted_factories(self, factories: list[Any]) -> None:
        for factory in factories:
            logger.info(
                "factory discovered network=%s chain_id=%d factory=%s version=%s start_block=%d source=%s",
                self.network_name,
                self.chain.config.chain_id,
                factory.address,
                factory.version,
                factory.start_block,
                factory.discovery_source,
            )

    def _log_inserted_events(self, prepared_events: list[PreparedEvent]) -> None:
        for prepared in prepared_events:
            event = prepared.domain_event
            if event.event_name == "DeployedNewAuction":
                logger.info(
                    "auction deployed network=%s block=%d auction=%s version=%s tx=%s",
                    self.network_name,
                    event.block_number,
                    event.auction_address,
                    event.version,
                    event.tx_hash,
                )
            elif event.event_name == "AuctionKicked":
                logger.info(
                    "round kicked network=%s block=%d auction=%s round_id=%s from_token=%s available=%s tx=%s",
                    self.network_name,
                    event.block_number,
                    event.auction_address,
                    event.payload.get("roundId", "?"),
                    event.payload.get("from"),
                    event.payload.get("available"),
                    event.tx_hash,
                )
            elif event.event_name == "Take":
                logger.info(
                    "take detected network=%s block=%d auction=%s round_id=%s taker=%s amount_taken=%s amount_paid=%s matching_method=%s tx=%s",
                    self.network_name,
                    event.block_number,
                    event.auction_address,
                    event.payload.get("roundId"),
                    event.payload.get("taker"),
                    event.payload.get("amountTaken"),
                    event.payload.get("amountPaid") or event.payload.get("expectedAmountPaid"),
                    event.payload.get("matchingMethod"),
                    event.tx_hash,
                )

    def _progress_snapshot(
        self,
        *,
        start_block: int,
        confirmed_head: int,
        processed_block: int,
    ) -> dict[str, int | float]:
        if confirmed_head < start_block:
            return {
                "done": 0,
                "total": 0,
                "remaining": 0,
                "percent": 100.0,
            }
        total = confirmed_head - start_block + 1
        if processed_block < start_block:
            done = 0
        else:
            done = min(total, processed_block - start_block + 1)
        remaining = max(0, total - done)
        percent = 100.0 if total == 0 else (done * 100.0) / total
        return {
            "done": done,
            "total": total,
            "remaining": remaining,
            "percent": percent,
        }
