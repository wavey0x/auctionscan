import { expect, it } from "vitest";
import { buildRoundPath, buildTakePath, occurrenceKey, parseOccurrence } from "./routes";

const kick = { chain_id: 1, block_hash: `0x${"a".repeat(64)}`, tx_hash: `0x${"b".repeat(64)}`, log_index: 4 };
const transfer = { ...kick, tx_hash: `0x${"c".repeat(64)}`, log_index: 9 };

it("keeps the occurrence in round and take links after display numbers change", () => {
  const take = { chain_id: 1, auction_address: "0xauction", occurrence: transfer, round_occurrence: kick, round_id: 1, take_seq: 1 };
  const link = buildTakePath(take);
  const renumbered = { ...take, round_id: 7, take_seq: 12 };
  expect(buildTakePath(renumbered)).toBe(link);
  const url = new URL(link, "https://auctionscan.info");
  expect(parseOccurrence(1, url.pathname.split("/").at(-1))).toEqual(kick);
  expect(parseOccurrence(1, url.searchParams.get("take"))).toEqual(transfer);
  expect(buildRoundPath(1, take.auction_address, kick)).toBe(url.pathname);
});

it("distinguishes logs and branches and rejects ordinal identifiers", () => {
  expect(occurrenceKey({ ...transfer, log_index: 10 })).not.toBe(occurrenceKey(transfer));
  expect(occurrenceKey({ ...transfer, block_hash: `0x${"d".repeat(64)}` })).not.toBe(occurrenceKey(transfer));
  expect(parseOccurrence(1, "29")).toBeNull();
  expect(parseOccurrence(1, `${transfer.block_hash}.${transfer.tx_hash}.-1`)).toBeNull();
});
