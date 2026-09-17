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
import Panel from "../../../shared/ui/Panel";

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

      if (resolution.destination.kind === "round" && resolution.destination.occurrence) {
        navigate(
          buildRoundPathFromTransaction(
            resolution.destination.chain_id,
            resolution.destination.auction_address,
            resolution.destination.occurrence,
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
      <Panel className="space-y-2">
        <div className="text-heading text-primary">Unable to resolve transaction.</div>
        <Link to="/" className="text-data text-tertiary underline-offset-4 hover:text-primary hover:underline">
          Return home
        </Link>
      </Panel>
    );
  }

  return (
    <Panel>
      <div className="text-data text-tertiary">Resolving transaction...</div>
    </Panel>
  );
}
