import { expect, it } from "vitest";
import { buildRoundPath, buildRoundPathFromTransaction, buildTakePath, occurrenceKey, parseOccurrence, parseRoundId } from "./routes";

const kick = { chain_id: 1, block_hash: `0x${"a".repeat(64)}`, tx_hash: `0x${"b".repeat(64)}`, log_index: 4 };
const transfer = { ...kick, tx_hash: `0x${"c".repeat(64)}`, log_index: 9 };

it("uses the round number in the path while preserving the exact selected take", () => {
  const take = { chain_id: 1, auction_address: "0xauction", occurrence: transfer, round_occurrence: kick, round_id: 1, take_seq: 1 };
  const link = buildTakePath(take);
  const renumbered = { ...take, round_id: 7, take_seq: 12 };
  expect(buildTakePath(renumbered)).not.toBe(link);
  const url = new URL(link, "https://auctionscan.info");
  expect(url.pathname).toBe("/round/1/0xauction/1");
  expect(parseOccurrence(1, url.searchParams.get("take"))).toEqual(transfer);
  expect(buildRoundPath(1, take.auction_address, take.round_id)).toBe(url.pathname);
  expect(new URL(buildTakePath(renumbered), url).search).toBe(url.search);
});

it("builds transaction destinations with numbered rounds and exact take selection", () => {
  const url = new URL(buildRoundPathFromTransaction(1, "0xauction", 28, transfer.tx_hash, transfer), "https://auctionscan.info");
  expect(url.pathname).toBe("/round/1/0xauction/28");
  expect(url.searchParams.get("from")).toBe("tx");
  expect(url.searchParams.get("tx")).toBe(transfer.tx_hash);
  expect(parseOccurrence(1, url.searchParams.get("take"))).toEqual(transfer);
});

it("accepts only positive safe integer round numbers", () => {
  expect(parseRoundId("28")).toBe(28);
  for (const invalid of [null, "", "0", "-1", "1.5", "1e2", "01", "9007199254740992", occurrenceKey(kick)]) {
    expect(parseRoundId(invalid)).toBeNull();
  }
});

it("distinguishes logs and branches and rejects ordinal identifiers", () => {
  expect(occurrenceKey({ ...transfer, log_index: 10 })).not.toBe(occurrenceKey(transfer));
  expect(occurrenceKey({ ...transfer, block_hash: `0x${"d".repeat(64)}` })).not.toBe(occurrenceKey(transfer));
  expect(parseOccurrence(1, "29")).toBeNull();
  expect(parseOccurrence(1, `${transfer.block_hash}.${transfer.tx_hash}.-1`)).toBeNull();
});
