import { useEffect, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Shield, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { changePassword, createUser, listUsers, updateUser } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { AdminUser, AuthConfig, AuthenticatedUser, UserRole } from "@/types";

type EditableUserDraft = {
  displayName: string;
  role: UserRole;
  allowedNamespaces: string;
  isActive: boolean;
};

const USER_ROLES: UserRole[] = ["viewer", "operator", "admin"];

function namespacesToText(namespaces: string[]): string {
  return namespaces.join(", ");
}

function parseNamespaces(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function draftFromUser(user: AdminUser): EditableUserDraft {
  return {
    displayName: user.display_name,
    role: user.role,
    allowedNamespaces: namespacesToText(user.allowed_namespaces),
    isActive: user.is_active,
  };
}

function sortUsers(users: AdminUser[]): AdminUser[] {
  return [...users].sort((left, right) => left.username.localeCompare(right.username));
}

interface ConnectionDialogProps {
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

export function ConnectionDialog({
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
}: ConnectionDialogProps) {
  const [open, setOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordError, setPasswordError] = useState("");

  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([]);
  const [adminUserDrafts, setAdminUserDrafts] = useState<Record<string, EditableUserDraft>>({});
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminError, setAdminError] = useState("");
  const [adminSavingUserId, setAdminSavingUserId] = useState<number | null>(null);
  const [createUserBusy, setCreateUserBusy] = useState(false);
  const [createUsername, setCreateUsername] = useState("");
  const [createUserPassword, setCreateUserPassword] = useState("");
  const [createDisplayName, setCreateDisplayName] = useState("");
  const [createEmail, setCreateEmail] = useState("");
  const [createRole, setCreateRole] = useState<UserRole>("viewer");
  const [createAllowedNamespaces, setCreateAllowedNamespaces] = useState("default");

  const isAdmin = currentUser?.role === "admin";
  const canChangePassword = currentUser?.auth_provider === "local";

  useEffect(() => {
    if (!open || !token.trim() || !isAdmin) {
      return;
    }

    let cancelled = false;
    async function loadAdminUsers() {
      setAdminLoading(true);
      setAdminError("");
      try {
        const users = sortUsers(await listUsers(token));
        if (cancelled) {
          return;
        }
        setAdminUsers(users);
        setAdminUserDrafts(Object.fromEntries(users.map((user) => [String(user.id), draftFromUser(user)])));
      } catch (error) {
        if (!cancelled) {
          setAdminError(error instanceof Error ? error.message : String(error));
        }
      } finally {
        if (!cancelled) {
          setAdminLoading(false);
        }
      }
    }

    void loadAdminUsers();
    return () => {
      cancelled = true;
    };
  }, [open, token, isAdmin]);

  async function handleConnect() {
    const ok = await onConnect();
    if (ok) setOpen(false);
  }

  const [registerError, setRegisterError] = useState("");

  const isBootstrapping = authConfig != null && !authConfig.bootstrap_complete && authConfig.registration_enabled;

  async function handlePasswordSubmit() {
    setRegisterError("");
    if (registerMode && passwordProvider === "local") {
      if (authUsername.trim().length < 3) {
        setRegisterError("Username must be at least 3 characters.");
        return;
      }
      if (authPassword.length < 8) {
        setRegisterError("Password must be at least 8 characters.");
        return;
      }
      if (authPassword !== authPasswordConfirm) {
        setRegisterError("Passwords do not match.");
        return;
      }
    }
    const ok = await onPasswordSubmit();
    if (ok) setOpen(false);
  }

  function applyUserUpdate(user: AdminUser) {
    setAdminUsers((current) =>
      sortUsers(current.some((item) => item.id === user.id) ? current.map((item) => (item.id === user.id ? user : item)) : [...current, user]),
    );
    setAdminUserDrafts((current) => ({
      ...current,
      [String(user.id)]: draftFromUser(user),
    }));
  }

  function resetCreateUserForm() {
    setCreateUsername("");
    setCreateUserPassword("");
    setCreateDisplayName("");
    setCreateEmail("");
    setCreateRole("viewer");
    setCreateAllowedNamespaces("default");
  }

  async function handleChangePassword() {
    if (!token.trim()) {
      return;
    }
    setPasswordBusy(true);
    setPasswordError("");
    try {
      await changePassword(token, currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      toast.success("Password updated.");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPasswordError(message);
      toast.error(message);
    } finally {
      setPasswordBusy(false);
    }
  }

  async function handleRefreshUsers() {
    if (!token.trim() || !isAdmin) {
      return;
    }
    setAdminLoading(true);
    setAdminError("");
    try {
      const users = sortUsers(await listUsers(token));
      setAdminUsers(users);
      setAdminUserDrafts(Object.fromEntries(users.map((user) => [String(user.id), draftFromUser(user)])));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setAdminError(message);
      toast.error(message);
    } finally {
      setAdminLoading(false);
    }
  }

  async function handleCreateUser() {
    if (!token.trim()) {
      return;
    }
    setCreateUserBusy(true);
    setAdminError("");
    try {
      const createdUser = await createUser(token, {
        username: createUsername,
        password: createUserPassword,
        email: createEmail,
        display_name: createDisplayName,
        role: createRole,
        allowed_namespaces: parseNamespaces(createAllowedNamespaces),
      });
      applyUserUpdate(createdUser);
      resetCreateUserForm();
      toast.success(`Created user ${createdUser.username}.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setAdminError(message);
      toast.error(message);
    } finally {
      setCreateUserBusy(false);
    }
  }

  async function handleSaveUser(user: AdminUser) {
    if (!token.trim()) {
      return;
    }
    const draft = adminUserDrafts[String(user.id)] ?? draftFromUser(user);
    setAdminSavingUserId(user.id);
    setAdminError("");
    try {
      const updatedUser = await updateUser(token, user.id, {
        display_name: draft.displayName,
        role: draft.role,
        is_active: draft.isActive,
        allowed_namespaces: parseNamespaces(draft.allowedNamespaces),
      });
      applyUserUpdate(updatedUser);
      if (currentUser && updatedUser.username === currentUser.username) {
        await onRefreshCurrentUser();
      }
      toast.success(`Saved ${updatedUser.username}.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setAdminError(message);
      toast.error(message);
    } finally {
      setAdminSavingUserId(null);
    }
  }

  const passwordProviders = authConfig?.password_providers ?? [];
  const oidcProviders = authConfig?.oidc_providers ?? [];
  const samlProviders = authConfig?.saml_providers ?? [];

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { setOpen(nextOpen); if (nextOpen) onClearConnectionError(); }}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Shield className="h-4 w-4" />
          <span>{token.trim() ? (currentUser ? currentUser.display_name : "Connected") : "Connect"}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Gateway Access</DialogTitle>
          <DialogDescription>
            Use a bearer token, sign in with a managed account, or launch an enterprise identity provider.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="namespace">Namespace</Label>
            <Input
              id="namespace"
              value={namespace}
              onChange={(e) => onNamespaceChange(e.target.value)}
              placeholder="default"
            />
          </div>
          {currentUser ? (
            <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
              <div className="font-semibold text-foreground">{currentUser.display_name}</div>
              <div className="text-muted-foreground">{currentUser.username}</div>
              <div className="text-muted-foreground">
                {currentUser.role} via {currentUser.auth_provider}
              </div>
              <div className="mt-2 text-xs text-muted-foreground">
                Allowed namespaces: {currentUser.allowed_namespaces.length > 0 ? namespacesToText(currentUser.allowed_namespaces) : "none"}
              </div>
              <div className="mt-3 flex justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    onLogout();
                    setOpen(false);
                  }}
                >
                  Sign out
                </Button>
              </div>
            </div>
          ) : null}
          <div className="grid gap-2">
            <Label htmlFor="token">API Token</Label>
            <Input
              id="token"
              type="password"
              value={token}
              onChange={(e) => onTokenChange(e.target.value)}
              placeholder="Bearer token"
            />
          </div>
          {!currentUser && (authConfig?.browser_auth_enabled || passwordProviders.length > 0 || oidcProviders.length > 0 || samlProviders.length > 0) && (
            <>
              <Separator />
              {passwordProviders.length > 0 && (
                <div className="grid gap-3">
                  {isBootstrapping && (
                    <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-3 text-sm">
                      <div className="flex items-center gap-2 font-medium text-primary">
                        <UserPlus className="h-4 w-4" />
                        Welcome — create the first admin account
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        No users exist yet. Register below to become the administrator.
                      </p>
                    </div>
                  )}
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <div className="text-sm font-medium">Password Sign-In</div>
                      <div className="text-xs text-muted-foreground">
                        {registerMode ? "Create a local account or bootstrap the first admin." : "Sign in with local or LDAP credentials."}
                      </div>
                    </div>
                    {passwordProviders.includes("local") && authConfig?.registration_enabled ? (
                      <Button variant="ghost" size="sm" onClick={() => { setRegisterError(""); onRegisterModeChange(!registerMode); }}>
                        {registerMode ? "Use sign in" : "Create account"}
                      </Button>
                    ) : null}
                  </div>
                  {passwordProviders.length > 1 && (
                    <div className="flex gap-2">
                      {passwordProviders.map((provider) => {
                        const providerValue = provider === "ldap" ? "ldap" : "local";
                        const active = passwordProvider === providerValue;
                        return (
                          <Button
                            key={provider}
                            type="button"
                            variant={active ? "default" : "outline"}
                            size="sm"
                            onClick={() => onPasswordProviderChange(providerValue)}
                          >
                            {providerValue === "ldap" ? "LDAP / AD" : "Local"}
                          </Button>
                        );
                      })}
                    </div>
                  )}
                  <div className="grid gap-2">
                    <Label htmlFor="auth-username">Username</Label>
                    <Input
                      id="auth-username"
                      value={authUsername}
                      onChange={(e) => onAuthUsernameChange(e.target.value)}
                      placeholder={passwordProvider === "ldap" ? "directory username" : "username"}
                    />
                  </div>
                  {registerMode && passwordProvider === "local" ? (
                    <div className="grid gap-2">
                      <Label htmlFor="auth-email">Email</Label>
                      <Input
                        id="auth-email"
                        type="email"
                        value={authEmail}
                        onChange={(e) => onAuthEmailChange(e.target.value)}
                        placeholder="name@example.com"
                      />
                    </div>
                  ) : null}
                  {registerMode && passwordProvider === "local" ? (
                    <div className="grid gap-2">
                      <Label htmlFor="auth-display-name">Display Name</Label>
                      <Input
                        id="auth-display-name"
                        value={authDisplayName}
                        onChange={(e) => onAuthDisplayNameChange(e.target.value)}
                        placeholder="How you want to be known (optional)"
                      />
                    </div>
                  ) : null}
                  <div className="grid gap-2">
                    <Label htmlFor="auth-password">Password</Label>
                    <Input
                      id="auth-password"
                      type="password"
                      value={authPassword}
                      onChange={(e) => onAuthPasswordChange(e.target.value)}
                      placeholder={registerMode ? "Create a password" : "Enter password"}
                    />
                  </div>
                  {registerMode && passwordProvider === "local" ? (
                    <div className="grid gap-2">
                      <Label htmlFor="auth-password-confirm">Confirm Password</Label>
                      <Input
                        id="auth-password-confirm"
                        type="password"
                        value={authPasswordConfirm}
                        onChange={(e) => onAuthPasswordConfirmChange(e.target.value)}
                        placeholder="Re-enter your password"
                      />
                    </div>
                  ) : null}
                  {registerError && (
                    <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive flex items-center gap-2">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                      {registerError}
                    </div>
                  )}
                  <Button onClick={handlePasswordSubmit} disabled={authBusy}>
                    {authBusy ? "Working..." : registerMode && passwordProvider === "local" ? "Create account" : "Sign in"}
                  </Button>
                </div>
              )}
              {(oidcProviders.length > 0 || samlProviders.length > 0) && (
                <div className="grid gap-2">
                  <div className="text-sm font-medium">Enterprise SSO</div>
                  <div className="flex flex-wrap gap-2">
                    {oidcProviders.map((provider) => (
                      <Button key={provider.id} variant="outline" size="sm" onClick={() => onStartOidc(provider.id)}>
                        {provider.name}
                      </Button>
                    ))}
                    {samlProviders.map((provider) => (
                      <Button key={provider.id} variant="outline" size="sm" onClick={() => onStartSaml(provider.id)}>
                        {provider.name} SAML
                      </Button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          {currentUser && (
            <>
              <Separator />
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="grid gap-3 rounded-lg border border-border bg-muted/30 p-4">
                  <div>
                    <div className="text-sm font-medium text-foreground">Account</div>
                    <div className="text-xs text-muted-foreground">
                      Manage your current session and local password settings.
                    </div>
                  </div>
                  {canChangePassword ? (
                    <>
                      <div className="grid gap-2">
                        <Label htmlFor="current-password">Current password</Label>
                        <Input
                          id="current-password"
                          type="password"
                          value={currentPassword}
                          onChange={(e) => setCurrentPassword(e.target.value)}
                          placeholder="Enter current password"
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="new-password">New password</Label>
                        <Input
                          id="new-password"
                          type="password"
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          placeholder="At least 8 characters"
                        />
                      </div>
                      {passwordError ? (
                        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {passwordError}
                        </div>
                      ) : null}
                      <div className="flex justify-end">
                        <Button onClick={() => void handleChangePassword()} disabled={passwordBusy}>
                          {passwordBusy ? "Updating..." : "Change password"}
                        </Button>
                      </div>
                    </>
                  ) : (
                    <div className="rounded-md border border-border bg-background/60 px-3 py-2 text-sm text-muted-foreground">
                      Password changes are managed by your {currentUser.auth_provider} identity provider.
                    </div>
                  )}
                </div>

                {isAdmin ? (
                  <div className="grid gap-4 rounded-lg border border-border bg-muted/30 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-foreground">Local users</div>
                        <div className="text-xs text-muted-foreground">
                          Create local accounts and adjust roles, namespace scope, or active state.
                        </div>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => void handleRefreshUsers()} disabled={adminLoading}>
                        <RefreshCw className={adminLoading ? "animate-spin" : ""} />
                        <span>{adminLoading ? "Refreshing" : "Refresh"}</span>
                      </Button>
                    </div>
                    {adminError ? (
                      <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                        {adminError}
                      </div>
                    ) : null}

                    <div className="grid gap-3 rounded-md border border-border bg-background/70 p-3">
                      <div className="text-sm font-medium text-foreground">Create user</div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="grid gap-2">
                          <Label htmlFor="create-username">Username</Label>
                          <Input
                            id="create-username"
                            value={createUsername}
                            onChange={(e) => setCreateUsername(e.target.value)}
                            placeholder="new-user"
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label htmlFor="create-password">Password</Label>
                          <Input
                            id="create-password"
                            type="password"
                            value={createUserPassword}
                            onChange={(e) => setCreateUserPassword(e.target.value)}
                            placeholder="At least 8 characters"
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label htmlFor="create-display-name">Display name</Label>
                          <Input
                            id="create-display-name"
                            value={createDisplayName}
                            onChange={(e) => setCreateDisplayName(e.target.value)}
                            placeholder="Jane Doe"
                          />
                        </div>
                        <div className="grid gap-2">
                          <Label htmlFor="create-email">Email</Label>
                          <Input
                            id="create-email"
                            type="email"
                            value={createEmail}
                            onChange={(e) => setCreateEmail(e.target.value)}
                            placeholder="jane@example.com"
                          />
                        </div>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-[minmax(0,160px)_minmax(0,1fr)]">
                        <div className="grid gap-2">
                          <Label htmlFor="create-role">Role</Label>
                          <Select value={createRole} onValueChange={(v) => setCreateRole(v as UserRole)}>
                            <SelectTrigger id="create-role" className="h-9">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {USER_ROLES.map((role) => (
                                <SelectItem key={role} value={role}>
                                  {role}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="grid gap-2">
                          <Label htmlFor="create-namespaces">Allowed namespaces</Label>
                          <Input
                            id="create-namespaces"
                            value={createAllowedNamespaces}
                            onChange={(e) => setCreateAllowedNamespaces(e.target.value)}
                            placeholder="default, team-a"
                          />
                        </div>
                      </div>
                      <div className="flex justify-end">
                        <Button onClick={() => void handleCreateUser()} disabled={createUserBusy}>
                          {createUserBusy ? "Creating..." : "Create local user"}
                        </Button>
                      </div>
                    </div>

                    <div className="grid gap-3">
                      {adminUsers.length === 0 ? (
                        <div className="rounded-md border border-border bg-background/60 px-3 py-2 text-sm text-muted-foreground">
                          No local or federated users are registered yet.
                        </div>
                      ) : (
                        adminUsers.map((user) => {
                          const draft = adminUserDrafts[String(user.id)] ?? draftFromUser(user);
                          return (
                            <div key={user.id} className="grid gap-3 rounded-md border border-border bg-background/70 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <div className="text-sm font-medium text-foreground">{user.username}</div>
                                  <div className="text-xs text-muted-foreground">
                                    {user.auth_provider} {user.last_login_at ? `· last login ${user.last_login_at}` : "· never logged in"}
                                  </div>
                                </div>
                                <div className="text-xs text-muted-foreground">
                                  {user.is_active ? "active" : "disabled"}
                                </div>
                              </div>

                              <div className="grid gap-3 sm:grid-cols-2">
                                <div className="grid gap-2">
                                  <Label htmlFor={`user-display-${user.id}`}>Display name</Label>
                                  <Input
                                    id={`user-display-${user.id}`}
                                    value={draft.displayName}
                                    onChange={(e) =>
                                      setAdminUserDrafts((current) => ({
                                        ...current,
                                        [String(user.id)]: { ...draft, displayName: e.target.value },
                                      }))
                                    }
                                  />
                                </div>
                                <div className="grid gap-2">
                                  <Label htmlFor={`user-role-${user.id}`}>Role</Label>
                                  <Select
                                    value={draft.role}
                                    onValueChange={(v) =>
                                      setAdminUserDrafts((current) => ({
                                        ...current,
                                        [String(user.id)]: { ...draft, role: v as UserRole },
                                      }))
                                    }
                                  >
                                    <SelectTrigger id={`user-role-${user.id}`} className="h-9">
                                      <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {USER_ROLES.map((role) => (
                                        <SelectItem key={role} value={role}>
                                          {role}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                              </div>

                              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_120px] sm:items-end">
                                <div className="grid gap-2">
                                  <Label htmlFor={`user-namespaces-${user.id}`}>Allowed namespaces</Label>
                                  <Input
                                    id={`user-namespaces-${user.id}`}
                                    value={draft.allowedNamespaces}
                                    onChange={(e) =>
                                      setAdminUserDrafts((current) => ({
                                        ...current,
                                        [String(user.id)]: { ...draft, allowedNamespaces: e.target.value },
                                      }))
                                    }
                                    placeholder="default, team-a"
                                  />
                                </div>
                                <label className="flex items-center gap-2 text-sm text-foreground">
                                  <input
                                    type="checkbox"
                                    checked={draft.isActive}
                                    onChange={(e) =>
                                      setAdminUserDrafts((current) => ({
                                        ...current,
                                        [String(user.id)]: { ...draft, isActive: e.target.checked },
                                      }))
                                    }
                                    className="h-4 w-4 rounded border-input"
                                  />
                                  Active
                                </label>
                              </div>

                              <div className="flex items-center justify-between gap-3">
                                <div className="text-xs text-muted-foreground">{user.email || "No email"}</div>
                                <Button size="sm" onClick={() => void handleSaveUser(user)} disabled={adminSavingUserId === user.id}>
                                  {adminSavingUserId === user.id ? "Saving..." : "Save"}
                                </Button>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>
        {connectionError && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {connectionError}
          </div>
        )}
        <DialogFooter>
          <Button onClick={handleConnect} disabled={isConnecting} className="gap-2">
            {isConnecting && <Loader2 className="h-4 w-4 animate-spin" />}
            {isConnecting ? "Connecting..." : currentUser ? "Refresh access" : "Connect"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
