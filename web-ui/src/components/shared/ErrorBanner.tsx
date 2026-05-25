import { AlertTriangle, ShieldAlert, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ApiError } from "@/lib/api";

// ─── Props ───

export interface ErrorBannerProps {
  error: ApiError | Error | string | null;
  onDismiss?: () => void;
  /** When true, the banner takes minimal height — good for inline use */
  compact?: boolean;
  className?: string;
}

// ─── Helpers ───

function extractMessage(error: ApiError | Error | string): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) {
    // Try to parse structured detail
    if ("detail" in error && typeof (error as ApiError).detail === "string") {
      try {
        const parsed = JSON.parse((error as ApiError).detail);
        if (parsed?.message) return parsed.message;
      } catch { /* not JSON */ }
    }
    return error.message || "An error occurred";
  }
  return "An error occurred";
}

function extractSuggestion(error: ApiError | Error | string): string | undefined {
  if (typeof error === "string") return undefined;
  if (error instanceof Error && "detail" in error) {
    try {
      const parsed = JSON.parse((error as ApiError).detail);
      if (parsed?.suggestion) return parsed.suggestion;
    } catch { /* not JSON */ }
  }
  return undefined;
}

function isAuthError(error: ApiError | Error | string): boolean {
  if (typeof error === "string") return false;
  if (error instanceof Error && "code" in error) {
    const code = (error as ApiError).code;
    return code === 401 || code === 403;
  }
  return false;
}

// ─── Component ───

export function ErrorBanner({ error, onDismiss, compact, className }: ErrorBannerProps) {
  if (!error) return null;

  const message = extractMessage(error);
  const suggestion = extractSuggestion(error);
  const auth = isAuthError(error);

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border bg-[oklch(0.21_0.015_264)] px-4 shadow-lg",
        auth
          ? "border-red-500/30 bg-red-500/5"
          : "border-amber-500/20 bg-amber-500/5",
        compact ? "py-2.5" : "py-4",
        className,
      )}
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center">
        {auth ? (
          <ShieldAlert className="h-4 w-4 text-red-400" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-amber-400" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className={cn("font-medium text-[oklch(0.92_0.004_264)]", compact ? "text-xs" : "text-sm")}>
          {message}
        </p>
        {suggestion && !compact && (
          <p className="mt-1 text-xs text-[oklch(0.72_0.01_264)]">{suggestion}</p>
        )}
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[oklch(0.55_0.01_264)] hover:bg-[oklch(0.3_0.01_264)] hover:text-[oklch(0.82_0.01_264)] transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
