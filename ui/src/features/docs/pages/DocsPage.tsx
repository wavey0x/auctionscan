export default function DocsPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-1">
        <div className="text-[11px] text-tertiary">Docs</div>
        <h1 className="page-title m-0">Pricing method</h1>
        <p className="m-0 max-w-2xl text-body text-secondary">
          Auctionscan measures execution quality by comparing auction outcomes to market
          benchmarks around the same time.
        </p>
      </header>

      <section className="card card-clip">
        <div className="card-title"><span>Method</span></div>
        <ul className="m-0 list-disc space-y-1.5 py-4 pl-9 pr-5 text-body text-secondary">
          <li>At round kick, we capture a baseline quote for the full lot.</li>
          <li>At each take, we capture a quote for the exact amount that was sold.</li>
          <li>Quotes are the primary benchmark because takes are sized executions, not spot marks.</li>
          <li>Token prices are secondary and mainly used to express values and deltas in USD.</li>
          <li>We compare actual auction proceeds to the market quote to estimate execution edge.</li>
        </ul>
        <div className="border-t border-divider-subtle px-5 py-3.5 text-body text-secondary">
          Summary views use one canonical benchmark per event. More detailed views may expose the
          full set of pricing observations.
        </div>
      </section>
    </div>
  );
}
