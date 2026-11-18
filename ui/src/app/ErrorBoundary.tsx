import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Without this, a render-time exception anywhere in the tree unmounts the whole
 * app and leaves a blank page with no way back.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }
    return (
      <div role="alert" className="mx-auto max-w-prose p-6 text-body">
        <h1 className="text-heading text-primary">Something went wrong</h1>
        <p className="mt-2 text-secondary">
          This page failed to render. Reloading usually clears it.
        </p>
        <p className="mt-2 font-mono text-caption text-negative">{error.message}</p>
        <button
          type="button"
          className="plain-button mt-4"
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </div>
    );
  }
}
