import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // In production, wire this to an error reporting service (Sentry, Datadog, etc.)
    // rather than logging to the browser console.
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.error("[ErrorBoundary]", error, info.componentStack);
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex min-h-[50dvh] flex-col items-center justify-center gap-4 p-8 text-center animate-scale-in">
          <div className="rounded-xl bg-destructive/10 p-3.5 animate-bounce-in">
            <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden="true" />
          </div>
          <div className="space-y-1">
            <h2 className="text-sm font-medium text-foreground">Something went wrong</h2>
            <p className="text-sm text-muted-foreground max-w-[320px]">
              {this.state.error?.message || "An unexpected error occurred."}
            </p>
          </div>
          <Button variant="outline" size="sm" className="hover-lift" onClick={this.handleReset}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Try again
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
