"use client";

import React from "react";

interface Props {
  children: React.ReactNode;
  /** Module name for error logging */
  module?: string;
  /** Custom fallback UI */
  fallback?: React.ReactNode;
  /** Error callback for monitoring integration */
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    const tag = this.props.module ? `[${this.props.module}]` : "[App]";
    console.error(`${tag} ErrorBoundary caught:`, error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const label = this.props.module ? `${this.props.module} error` : "Something went wrong";

      return (
        <div className="flex flex-col items-center justify-center gap-3 p-6">
          <p className="text-sm font-medium text-red-500">{label}</p>
          <p className="max-w-md text-center text-xs text-muted-foreground">
            {this.state.error?.message || "An unexpected error occurred"}
          </p>
          <div className="flex gap-2">
            <button
              onClick={this.handleRetry}
              className="rounded bg-primary px-4 py-2 text-xs text-primary-foreground"
            >
              Retry
            </button>
            <button
              onClick={() => window.location.reload()}
              className="rounded bg-muted px-4 py-2 text-xs text-muted-foreground hover:text-app-text-primary"
            >
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * Lightweight inline error boundary for individual UI blocks.
 * Shows a compact error message instead of the full retry/reload UI.
 */
export class InlineErrorBoundary extends React.Component<
  { children: React.ReactNode; label?: string },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode; label?: string }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: true } {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(
      `[InlineErrorBoundary${this.props.label ? `:${this.props.label}` : ""}]`,
      error,
      info,
    );
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-400">
          {this.props.label ? `${this.props.label}: ` : ""}Failed to render this item
        </div>
      );
    }
    return this.props.children;
  }
}
