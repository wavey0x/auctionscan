export default function RequestError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex items-center gap-3 p-3 text-body text-negative">
      <span>{message}</span>
      <button type="button" className="plain-button shrink-0" onClick={onRetry}>Retry</button>
    </div>
  );
}
