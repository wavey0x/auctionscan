import { createContext, useCallback, useContext, useEffect, type KeyboardEvent, type MouseEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { cn } from "./format";
import { handleRowNavigation } from "./rowNavigation";
import { buildRoundPathWithSource, roundModalSourceFromLocation, withBackgroundLocation } from "./routes";

export interface OpenRound {
  chainId: number;
  auctionAddress: string;
  roundId: number;
  /** Router state of the drawer's own history entry, kept when stepping between rows. */
  state: unknown;
}

const OpenRoundContext = createContext<OpenRound | null>(null);

export const OpenRoundProvider = OpenRoundContext.Provider;

export function useOpenRound(): OpenRound | null {
  return useContext(OpenRoundContext);
}

type RoundKey = { chain_id: number; auction_address: string; round_id: number };

function sameRound(open: OpenRound | null, round: RoundKey): boolean {
  return Boolean(
    open
      && open.chainId === round.chain_id
      && open.roundId === round.round_id
      && open.auctionAddress.toLowerCase() === round.auction_address.toLowerCase(),
  );
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
}

function focusSibling(row: HTMLElement, direction: 1 | -1) {
  let next = direction === 1 ? row.nextElementSibling : row.previousElementSibling;
  while (next && !(next instanceof HTMLElement && next.hasAttribute("data-row"))) {
    next = direction === 1 ? next.nextElementSibling : next.previousElementSibling;
  }
  if (next instanceof HTMLElement) next.focus();
}

/**
 * Rows that open a round in the drawer. A row click opens it; with the drawer
 * already open, another row or ↑/↓ moves it there, replacing the history entry
 * so Back still closes the drawer.
 */
export function useRoundRows<T extends RoundKey>(rounds: T[] | undefined) {
  const open = useOpenRound();
  const location = useLocation();
  const navigate = useNavigate();
  const source = roundModalSourceFromLocation(location);

  const hrefFor = useCallback(
    (round: T) => buildRoundPathWithSource(round.chain_id, round.auction_address, round.round_id, source),
    [source],
  );

  const openRound = useCallback(
    (round: T) => {
      if (open) {
        navigate(hrefFor(round), { replace: true, state: open.state });
        return;
      }
      navigate(hrefFor(round), { state: withBackgroundLocation(location) });
    },
    [open, navigate, hrefFor, location],
  );

  useEffect(() => {
    if (!open || !rounds?.length) return undefined;
    const index = rounds.findIndex((round) => sameRound(open, round));
    if (index < 0) return undefined;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      if (event.metaKey || event.ctrlKey || event.altKey || isTypingTarget(event.target)) return;
      const next = rounds[index + (event.key === "ArrowDown" ? 1 : -1)];
      if (!next) return;
      event.preventDefault();
      openRound(next);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, rounds, openRound]);

  const rowProps = (round: T, className?: string) => {
    const href = hrefFor(round);
    const isOpen = sameRound(open, round);
    return {
      className: cn("data-row", isOpen && "is-open", className),
      tabIndex: 0,
      "data-row": "",
      "aria-current": isOpen ? ("true" as const) : undefined,
      onClick: (event: MouseEvent<HTMLElement>) => handleRowNavigation(event, href, () => openRound(round)),
      onAuxClick: (event: MouseEvent<HTMLElement>) => handleRowNavigation(event, href, () => openRound(round)),
      onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter") {
          event.preventDefault();
          openRound(round);
        } else if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
          event.preventDefault();
          focusSibling(event.currentTarget, event.key === "ArrowDown" ? 1 : -1);
        }
      },
    };
  };

  return { rowProps, openRound, isOpen: (round: T) => sameRound(open, round), hrefFor };
}

/** Keyboard reach for a row that navigates somewhere else: Enter follows it, ↑/↓ move between rows. */
export function linkRowKeyDown(onOpen: () => void) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter") {
      event.preventDefault();
      onOpen();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusSibling(event.currentTarget, event.key === "ArrowDown" ? 1 : -1);
    }
  };
}
