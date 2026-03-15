import { CheckCircle2, LayoutPanelTop, Loader2, Palette, XCircle } from "lucide-react";
import { useRef, useState, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "./StatusBadge";
import { ConnectionDialog } from "./ConnectionDialog";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import { useTheme, THEMES } from "@/contexts/ThemeContext";
import type { AuthConfig, AuthenticatedUser, GatewayHealth } from "@/types";

interface TopBarProps {
  health: GatewayHealth | null;
  gatewayError: string;
  token: string;
  namespace: string;
  isConnecting: boolean;
  authConfig: AuthConfig | null;
  currentUser: AuthenticatedUser | null;
  authBusy: boolean;
  authUsername: string;
  authPassword: string;
  authEmail: string;
  authDisplayName: string;
  authPasswordConfirm: string;
  passwordProvider: "local" | "ldap";
  registerMode: boolean;
  onTokenChange: (value: string) => void;
  onNamespaceChange: (value: string) => void;
  onAuthUsernameChange: (value: string) => void;
  onAuthPasswordChange: (value: string) => void;
  onAuthEmailChange: (value: string) => void;
  onAuthDisplayNameChange: (value: string) => void;
  onAuthPasswordConfirmChange: (value: string) => void;
  onPasswordProviderChange: (value: "local" | "ldap") => void;
  onRegisterModeChange: (value: boolean) => void;
  connectionError: string;
  onClearConnectionError: () => void;
  onConnect: () => Promise<boolean>;
  onPasswordSubmit: () => Promise<boolean>;
  onStartOidc: (providerId: string) => void;
  onStartSaml: (providerId: string) => void;
  onLogout: () => void;
  onRefreshCurrentUser: () => Promise<void>;
}

const THEME_SWATCHES: Record<string, string> = {
  dark: "bg-zinc-700",
  light: "bg-zinc-200",
  midnight: "bg-blue-700",
  forest: "bg-emerald-700",
};

function ThemePicker() {
  const { theme, setTheme, labelFor } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="icon" className="h-8 w-8 border-border/60 text-foreground hover:bg-accent" onClick={() => setOpen((v) => !v)} aria-label="Change theme">
            <Palette className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">Theme</TooltipContent>
      </Tooltip>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[160px] rounded-md border border-border bg-popover p-1 shadow-lg animate-fade-in">
          {THEMES.map((t) => (
            <button
              key={t}
              className={`flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs text-popover-foreground hover:bg-accent ${t === theme ? "bg-accent font-medium" : ""}`}
              onClick={() => { setTheme(t); setOpen(false); }}
            >
              <span className={`inline-block h-3 w-3 rounded-full border border-border ${THEME_SWATCHES[t]}`} />
              {labelFor(t)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function TopBar({
  health,
  gatewayError,
  token,
  namespace,
  isConnecting,
  authConfig,
  currentUser,
  authBusy,
  authUsername,
  authPassword,
  authEmail,
  authDisplayName,
  authPasswordConfirm,
  passwordProvider,
  registerMode,
  onTokenChange,
  onNamespaceChange,
  onAuthUsernameChange,
  onAuthPasswordChange,
  onAuthEmailChange,
  onAuthDisplayNameChange,
  onAuthPasswordConfirmChange,
  onPasswordProviderChange,
  onRegisterModeChange,
  connectionError,
  onClearConnectionError,
  onConnect,
  onPasswordSubmit,
  onStartOidc,
  onStartSaml,
  onLogout,
  onRefreshCurrentUser,
}: TopBarProps) {
  const gatewayStatus = gatewayError ? "offline" : health?.status ?? "loading";
  const isHealthy = gatewayStatus === "ok" || gatewayStatus === "healthy";
  const isLoading = gatewayStatus === "loading";

  const healthStatusVariant = isHealthy ? "success" : gatewayStatus === "offline" ? "error" : isLoading ? "neutral" : "warning";
  const HealthIcon = isHealthy ? CheckCircle2 : gatewayStatus === "offline" ? XCircle : Loader2;

  return (
    <TooltipProvider delayDuration={200}>
      <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-border bg-sidebar px-4 shadow-sm animate-fade-in">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary">
            <LayoutPanelTop className="h-5 w-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Kubemininions
            </span>
            <span className="text-sm font-semibold text-foreground">Agent Sandbox</span>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <StatusBadge icon={HealthIcon} status={healthStatusVariant} className={isLoading ? "[&>svg]:animate-spin" : ""}>
                  {gatewayStatus}
                </StatusBadge>
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom">Gateway health: {gatewayStatus}</TooltipContent>
          </Tooltip>
          {token.trim() && (
            <Badge variant="outline" className="font-mono text-xs">
              {namespace}
            </Badge>
          )}
          {currentUser ? <Badge variant="secondary">{currentUser.role}</Badge> : null}
          <ThemePicker />
          <ConnectionDialog
          connectionError={connectionError}
          onClearConnectionError={onClearConnectionError}
          token={token}
          namespace={namespace}
          isConnecting={isConnecting}
          authConfig={authConfig}
          currentUser={currentUser}
          authBusy={authBusy}
          authUsername={authUsername}
          authPassword={authPassword}
          authEmail={authEmail}
          authDisplayName={authDisplayName}
          authPasswordConfirm={authPasswordConfirm}
          passwordProvider={passwordProvider}
          registerMode={registerMode}
          onTokenChange={onTokenChange}
          onNamespaceChange={onNamespaceChange}
          onAuthUsernameChange={onAuthUsernameChange}
          onAuthPasswordChange={onAuthPasswordChange}
          onAuthEmailChange={onAuthEmailChange}
          onAuthDisplayNameChange={onAuthDisplayNameChange}
          onAuthPasswordConfirmChange={onAuthPasswordConfirmChange}
          onPasswordProviderChange={onPasswordProviderChange}
          onRegisterModeChange={onRegisterModeChange}
          onConnect={onConnect}
          onPasswordSubmit={onPasswordSubmit}
          onStartOidc={onStartOidc}
          onStartSaml={onStartSaml}
          onLogout={onLogout}
          onRefreshCurrentUser={onRefreshCurrentUser}
        />
        </div>
      </header>
    </TooltipProvider>
  );
}
