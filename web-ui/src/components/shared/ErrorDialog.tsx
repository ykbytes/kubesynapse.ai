import { AlertTriangle, Copy, ShieldAlert, ShieldX, WifiOff, X } from "lucide-react";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import type { ApiError } from "@/lib/api";

// ─── Types ───

export interface ErrorDialogProps {
  error: ApiError | Error | null;
  open: boolean;
  onClose: () => void;
  /** Optional retry callback — shown as a button when provided */
  onRetry?: () => void;
}

// ─── Error category config ───

interface ErrorDisplay {
  icon: typeof AlertTriangle;
  title: string;
  bgClass: string;
  iconClass: string;
  borderClass: string;
}

const ERROR_DISPLAY: Record<string, ErrorDisplay> = {
  auth: {
    icon: ShieldX,
    title: "Authentication Required",
    bgClass: "bg-red-500/10",
    iconClass: "text-red-400",
    borderClass: "border-red-500/30",
  },
  validation: {
    icon: AlertTriangle,
    title: "Validation Error",
    bgClass: "bg-amber-500/10",
    iconClass: "text-amber-400",
    borderClass: "border-amber-500/30",
  },
  network: {
    icon: WifiOff,
    title: "Connection Error",
    bgClass: "bg-orange-500/10",
    iconClass: "text-orange-400",
    borderClass: "border-orange-500/30",
  },
  server: {
    icon: ShieldAlert,
    title: "Server Error",
    bgClass: "bg-red-500/10",
    iconClass: "text-red-400",
    borderClass: "border-red-500/30",
  },
  timeout: {
    icon: WifiOff,
    title: "Request Timed Out",
    bgClass: "bg-orange-500/10",
    iconClass: "text-orange-400",
    borderClass: "border-orange-500/30",
  },
  unknown: {
    icon: AlertTriangle,
    title: "Unexpected Error",
    bgClass: "bg-red-500/10",
    iconClass: "text-red-400",
    borderClass: "border-red-500/30",
  },
};

// ─── Component ───

export function ErrorDialog({ error, open, onClose, onRetry }: ErrorDialogProps) {
  const [copied, setCopied] = useState(false);

  if (!error) return null;

  // Extract structured fields from ApiError or generic Error
  const isApiError = "code" in error && "category" in error;
  const display = ERROR_DISPLAY[isApiError ? (error as ApiError).category : "unknown"];

  // Try to parse structured error body from API
  let errorCode: string | undefined;
  let errorMessage: string;
  let errorDetail: string | undefined;
  let errorSuggestion: string | undefined;
  let httpStatus: number | undefined;

  if (isApiError) {
    const apiErr = error as ApiError;
    httpStatus = apiErr.code;
    errorMessage = apiErr.message;
    errorDetail = apiErr.detail || undefined;

    // Attempt to parse the detail as JSON (it may be our ErrorResponse)
    try {
      const parsed = JSON.parse(apiErr.detail);
      if (parsed && typeof parsed === "object") {
        errorCode = parsed.code || errorCode;
        errorMessage = parsed.message || errorMessage;
        errorDetail = parsed.detail || errorDetail;
        errorSuggestion = parsed.suggestion || errorSuggestion;
      }
    } catch {
      // Not JSON — use as-is
    }
  } else {
    errorMessage = error.message || "An unexpected error occurred";
  }

  const handleCopy = async () => {
    const text = [
      `Error: ${errorCode || "UNKNOWN"}`,
      `Message: ${errorMessage}`,
      errorDetail ? `Detail: ${errorDetail}` : null,
      httpStatus ? `HTTP Status: ${httpStatus}` : null,
    ]
      .filter(Boolean)
      .join("\n");

    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API not available
    }
  };

  const Icon = display.icon;

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Dialog */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ duration: 0.2 }}
            className={cn(
              "relative w-full max-w-md overflow-hidden rounded-2xl border bg-[oklch(0.21_0.015_264)] shadow-2xl shadow-black/50",
              display.borderClass,
            )}
          >
            {/* Header */}
            <div className={cn("flex items-start gap-4 px-6 pt-6 pb-4", display.bgClass)}>
              <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-xl", display.iconClass, "bg-current/10")}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-[oklch(0.958_0.004_264)]">
                  {display.title}
                </h2>
                {httpStatus && (
                  <p className="mt-0.5 text-xs text-[oklch(0.62_0.01_264)]">
                    HTTP {httpStatus}{errorCode ? ` · ${errorCode}` : ""}
                  </p>
                )}
              </div>
              <button
                onClick={onClose}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[oklch(0.62_0.01_264)] hover:bg-[oklch(0.3_0.01_264)] hover:text-[oklch(0.82_0.01_264)] transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Body */}
            <div className="px-6 py-4 space-y-3">
              <p className="text-sm text-[oklch(0.88_0.01_264)]">{errorMessage}</p>

              {errorDetail && (
                <div className="rounded-lg bg-[oklch(0.16_0.009_264)] px-3 py-2">
                  <p className="text-xs text-[oklch(0.72_0.01_264)] whitespace-pre-wrap break-words">
                    {errorDetail}
                  </p>
                </div>
              )}

              {errorSuggestion && (
                <div className="flex items-start gap-2 rounded-lg bg-[oklch(0.252_0.010_264)] px-3 py-2">
                  <span className="mt-0.5 text-xs">💡</span>
                  <p className="text-xs text-[oklch(0.78_0.01_264)]">{errorSuggestion}</p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between px-6 pb-5 pt-2">
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-[oklch(0.62_0.01_264)] hover:text-[oklch(0.82_0.01_264)] hover:bg-[oklch(0.3_0.01_264)] transition-colors"
              >
                <Copy className="h-3 w-3" />
                {copied ? "Copied!" : "Copy details"}
              </button>
              <div className="flex gap-2">
                <button
                  onClick={onClose}
                  className="rounded-lg border border-[oklch(0.35_0.015_264)] px-4 py-2 text-sm font-medium text-[oklch(0.82_0.01_264)] hover:bg-[oklch(0.3_0.01_264)] transition-colors"
                >
                  Dismiss
                </button>
                {onRetry && (
                  <button
                    onClick={onRetry}
                    className="rounded-lg bg-[oklch(0.708_0.101_188)] px-4 py-2 text-sm font-semibold text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.25)] hover:bg-[oklch(0.75_0.12_188)] transition-all"
                  >
                    Retry
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
