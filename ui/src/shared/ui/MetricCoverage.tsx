export default function MetricCoverage({ count, total, label = "takes" }: {
  count: number;
  total: number;
  label?: string;
}) {
  if (count >= total) return null;
  return <span className="whitespace-nowrap font-mono text-[10px] leading-none text-tertiary" title={`${count} of ${total} takes contribute`}>{count}/{total} {label}</span>;
}
