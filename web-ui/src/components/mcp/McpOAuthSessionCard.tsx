import { CheckCircle2, Link2, Loader2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { McpConnection, McpRegistryServer } from "@/types";
import {
  OAUTH_STATE_STYLES,
  formatOauthExpiry,
  formatOauthScopeLabel,
  formatOauthStateLabel,
} from "./mcp-helpers";

interface McpOAuthSessionCardProps {
  server: McpRegistryServer;
  connection: McpConnection | null;
  busy: boolean;
  onStart: () => void;
  onRefresh: () => void;
}

export function McpOAuthSessionCard({ server, connection, busy, onStart, onRefresh }: McpOAuthSessionCardProps) {
  const oauth = connection?.oauth ?? null;
  const expiryLabel = formatOauthExpiry(oauth?.expires_at);

  return (
    <div className="rounded-2xl border border-border/60 bg-card/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-background text-foreground/80">
            <Link2 className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground">OAuth session</p>
            <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
              {!server.attachable
                ? "This provider still needs extra OAuth support before agents can attach it. Keep the saved connection as a draft for now."
                : !connection
                  ? "Save the connection first, then complete the browser sign-in once to store the runtime token on this namespace-scoped connection."
                  : oauth?.state === "connected"
                    ? "The saved connection has a usable OAuth token. Reconnect if you need a different account or refresh if the provider issues renewable sessions."
                    : oauth?.state === "expired"
                      ? "The saved OAuth session expired. Refresh it if a refresh token is available, or reconnect through the browser sign-in flow."
                      : "This saved connection still needs a browser-based OAuth sign-in before it can be attached to agents."}
            </p>
          </div>
        </div>
        {server.attachable && (
          <Badge variant="outline" className={`text-xs ${OAUTH_STATE_STYLES[oauth?.state ?? "required"]}`}>
            {formatOauthStateLabel(oauth?.state ?? "required")}
          </Badge>
        )}
      </div>

      {oauth?.scope.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {oauth.scope.map((scope) => (
            <Badge key={scope} variant="outline" className="rounded-full px-2.5 py-0.5 text-xs text-muted-foreground">
              {formatOauthScopeLabel(scope)}
            </Badge>
          ))}
        </div>
      ) : null}

      {expiryLabel ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          <span>Current token expiry: {expiryLabel}</span>
        </div>
      ) : null}

      {connection?.binding_count ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Refreshing or reconnecting restarts bound agents so they pick up the updated token.
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {connection && server.attachable ? (
          <>
            <Button size="sm" onClick={onStart} disabled={busy} className="gap-1.5">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
              {oauth?.connected ? "Reconnect OAuth" : "Connect OAuth"}
            </Button>
            {oauth?.refresh_available ? (
              <Button size="sm" variant="outline" onClick={onRefresh} disabled={busy} className="gap-1.5">
                <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
                Refresh session
              </Button>
            ) : null}
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-border/60 bg-background/40 px-3 py-2 text-sm text-muted-foreground">
            {server.attachable
              ? "Save this connection before launching OAuth."
              : "OAuth actions will appear here once this provider is attachable."}
          </div>
        )}
      </div>
    </div>
  );
}
