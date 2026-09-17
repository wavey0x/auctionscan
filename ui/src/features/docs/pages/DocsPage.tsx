import Panel from "../../../shared/ui/Panel";

export default function DocsPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-heading text-primary">Docs</h1>
        <p className="max-w-2xl text-data text-secondary">
          Auctionscan measures execution quality by comparing auction outcomes to market
          benchmarks around the same time.
        </p>
      </header>

      <Panel className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="text-data font-medium text-primary">Method</h2>
          <ul className="list-disc space-y-1 pl-5 text-data text-secondary">
            <li>At round kick, we capture a baseline quote for the full lot.</li>
            <li>At each take, we capture a quote for the exact amount that was sold.</li>
            <li>Quotes are the primary benchmark because takes are sized executions, not spot marks.</li>
            <li>Token prices are secondary and mainly used to express values and deltas in USD.</li>
            <li>We compare actual auction proceeds to the market quote to estimate execution edge.</li>
          </ul>
        </div>

        <div className="border-t border-divider-subtle pt-3 text-data text-secondary">
          Summary views use one canonical benchmark per event. More detailed views may expose the
          full set of pricing observations.
        </div>
      </Panel>
    </div>
  );
}
