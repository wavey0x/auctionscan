import type { Location } from "react-router-dom";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import RoundModal from "../components/RoundModal";
import RoundModalContent from "../components/RoundModalContent";
import {
  buildLocationHref,
  parseRoundModalSource,
  resolveRoundModalBackgroundLocation,
} from "../../../shared/lib/routes";

type RoundRouteState = {
  backgroundLocation?: Location;
};

export default function RoundModalRoute() {
  const navigate = useNavigate();
  const location = useLocation();
  const { chainId, auctionAddress } = useParams<{
    chainId: string;
    auctionAddress: string;
  }>();

  const routeState = location.state as RoundRouteState | null;
  const hasRealBackground = Boolean(routeState?.backgroundLocation);
  const searchParams = new URLSearchParams(location.search);
  const roundModalSource = parseRoundModalSource(searchParams.get("from"));
  const roundModalTxHash = searchParams.get("tx");
  const fallbackPath =
    chainId && auctionAddress
      ? buildLocationHref(
          resolveRoundModalBackgroundLocation(roundModalSource, chainId, auctionAddress, roundModalTxHash),
        )
      : "/";

  const handleClose = () => {
    if (hasRealBackground) {
      navigate(-1);
      return;
    }

    navigate(fallbackPath, { replace: true });
  };

  return (
    <RoundModal ariaLabel="Round detail" onClose={handleClose}>
      <RoundModalContent onClose={handleClose} />
    </RoundModal>
  );
}
