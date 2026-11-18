import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import {
  buildAuctionPath,
  buildRoundPathFromTransaction,
  buildTxFilterSearch,
  normalizeTransactionHash,
} from "../../../shared/lib/routes";

function normalizeResolvedHash(txHash: string | undefined, resolvedHash: string | null | undefined): string | null {
  return normalizeTransactionHash(resolvedHash) ?? normalizeTransactionHash(txHash);
}

export default function TxResolveRoute() {
  const navigate = useNavigate();
  const { txHash = "" } = useParams<{ txHash: string }>();
  const resolutionQuery = useQuery({
    queryKey: ["tx-resolve", txHash],
    queryFn: ({ signal }) => api.resolveTransaction(txHash, signal),
    enabled: txHash.length > 0,
    retry: false,
  });

  useEffect(() => {
    const resolution = resolutionQuery.data;
    if (!resolution) {
      return;
    }

    const normalizedTxHash = normalizeResolvedHash(txHash, resolution.normalized_tx_hash);
    if (resolution.outcome === "resolved" && resolution.destination) {
      if (resolution.destination.kind === "auction") {
        navigate(
          buildAuctionPath(resolution.destination.chain_id, resolution.destination.auction_address),
          { replace: true },
        );
        return;
      }

      if (resolution.destination.kind === "round" && resolution.destination.round_id != null) {
        navigate(
          buildRoundPathFromTransaction(
            resolution.destination.chain_id,
            resolution.destination.auction_address,
            resolution.destination.round_id,
            normalizedTxHash || txHash,
            resolution.destination.take_occurrence,
          ),
          { replace: true },
        );
        return;
      }

      navigate("/", { replace: true });
      return;
    }

    if (resolution.outcome === "ambiguous") {
      navigate(normalizedTxHash ? `/${buildTxFilterSearch(normalizedTxHash)}` : "/", { replace: true });
      return;
    }

    if (resolution.outcome === "invalid" || resolution.outcome === "not_found") {
      navigate("/", { replace: true });
    }
  }, [navigate, resolutionQuery.data, txHash]);

  if (resolutionQuery.isError) {
    return (
      <section className="card space-y-2 px-4 py-4">
        <div className="text-body text-primary">Unable to resolve transaction.</div>
        <Link to="/" className="text-data text-tertiary transition-colors hover:text-primary">
          Return to rounds
        </Link>
      </section>
    );
  }

  return (
    <section className="card flex items-center gap-3 px-4 py-4" aria-busy="true">
      <span className="skeleton-bar w-24" />
      <span className="text-data text-tertiary">Resolving transaction…</span>
    </section>
  );
}
