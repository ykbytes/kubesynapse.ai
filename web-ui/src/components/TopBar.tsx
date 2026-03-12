import { LayoutPanelTop } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ConnectionDialog } from "./ConnectionDialog";
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
  onConnect: () => void;
  onPasswordSubmit: () => void;
  onStartOidc: (providerId: string) => void;
  onStartSaml: (providerId: string) => void;
  onLogout: () => void;
  onRefreshCurrentUser: () => Promise<void>;
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
  onConnect,
  onPasswordSubmit,
  onStartOidc,
  onStartSaml,
  onLogout,
  onRefreshCurrentUser,
}: TopBarProps) {
  const gatewayStatus = gatewayError ? "offline" : health?.status ?? "loading";
  const isHealthy = gatewayStatus === "ok" || gatewayStatus === "healthy";

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-sidebar px-4">
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

      <div className="flex items-center gap-3">
        <Badge
          variant={isHealthy ? "default" : gatewayStatus === "offline" ? "destructive" : "secondary"}
        >
          {gatewayStatus}
        </Badge>
        {token.trim() && (
          <Badge variant="outline" className="font-mono text-xs">
            {namespace}
          </Badge>
        )}
        {currentUser ? <Badge variant="secondary">{currentUser.role}</Badge> : null}
        <ConnectionDialog
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
  );
}
