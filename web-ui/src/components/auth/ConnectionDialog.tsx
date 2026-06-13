import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Building2,
  KeyRound,
  Loader2,
  LockKeyhole,
  LogOut,
  RefreshCw,
  ShieldCheck,
  UserPlus,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { changePassword, createUser, listUsers, updateUser } from "@/lib/api";
import {
  AuthProviderBrandIcon,
  buildAuthProviderOptions,
  launchAuthProvider,
  recommendedAuthCopy,
} from "@/lib/authProviders";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

function providerLabel(provider: string): string {
  if (provider === "shared_token") return "Shared access";
  if (provider === "local") return "Local account";
  if (provider === "ldap") return "Directory account";
  if (provider === "oidc") return "Managed identity";
  if (provider === "saml") return "SAML identity";
  return provider.replace(/_/g, " ");
}

function accountDisplayLabel(currentUser: AuthenticatedUser | null, token: string): string {
  if (!token.trim()) return "Connect";
  if (!currentUser) return "Connected";
  const displayName = currentUser.display_name.trim();
  if (displayName && displayName.toLowerCase() !== "shared token") {
    return displayName;
  }
  if (currentUser.role === "admin") return "Platform Admin";
  return "Account";
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
  const [createAllowedNamespaces, setCreateAllowedNamespaces] = useState("");

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
    setCreateAllowedNamespaces("");
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
  const ssoProviders = useMemo(() => buildAuthProviderOptions(oidcProviders, samlProviders), [oidcProviders, samlProviders]);
  const primarySsoProvider = ssoProviders[0] ?? null;
  const secondarySsoProviders = ssoProviders.slice(1);
  const currentUserNamespaces = currentUser
    ? currentUser.allowed_namespaces.length > 0
      ? namespacesToText(currentUser.allowed_namespaces)
      : "No namespace scope assigned"
    : "";
  const accountLabel = accountDisplayLabel(currentUser, token);

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { setOpen(nextOpen); if (nextOpen) onClearConnectionError(); }}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 gap-2 rounded-lg border-border/70 bg-card/80 px-3 text-sm shadow-sm">
          <ShieldCheck className="h-4 w-4 text-primary" />
          <span className="max-w-[10rem] truncate">{accountLabel}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[88vh] overflow-hidden p-0 sm:max-w-5xl">
        {currentUser ? (
          <div className="flex max-h-[88vh] flex-col overflow-hidden bg-background text-foreground">
            <div className="border-b border-border/70 bg-muted/30 px-6 py-5">
              <DialogHeader className="pr-10">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <DialogTitle className="text-xl">Account & Access</DialogTitle>
                    <DialogDescription className="mt-2 max-w-2xl">
                      Manage your browser session, namespace context, and user access without exposing credentials.
                    </DialogDescription>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="gap-2"
                      onClick={() => void onRefreshCurrentUser()}
                    >
                      <RefreshCw className="h-4 w-4" />
                      Refresh
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="gap-2"
                      onClick={() => {
                        onLogout();
                        setOpen(false);
                      }}
                    >
                      <LogOut className="h-4 w-4" />
                      Sign out
                    </Button>
                  </div>
                </div>
              </DialogHeader>
            </div>

            <div className="min-h-0 overflow-y-auto px-6 py-5">
              <div className="grid gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
                <div className="space-y-4">
                  <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
                    <div className="flex items-start gap-3">
                      <div className="rounded-lg border border-primary/20 bg-primary/10 p-2 text-primary">
                        <ShieldCheck className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <div className="truncate text-base font-semibold text-foreground">{accountLabel}</div>
                        <div className="mt-1 truncate text-sm text-muted-foreground">{currentUser.username}</div>
                      </div>
                    </div>
                    <div className="mt-4 grid gap-2 text-sm">
                      <div className="flex items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2">
                        <span className="text-muted-foreground">Role</span>
                        <span className="font-medium capitalize text-foreground">{currentUser.role}</span>
                      </div>
                      <div className="flex items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2">
                        <span className="text-muted-foreground">Identity</span>
                        <span className="font-medium text-foreground">{providerLabel(currentUser.auth_provider)}</span>
                      </div>
                    </div>
                  </section>

                  <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
                    <div className="flex items-start gap-3">
                      <div className="rounded-lg border border-border bg-muted/50 p-2 text-muted-foreground">
                        <Building2 className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-foreground">Workspace context</div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Requests use this namespace unless a page overrides it.
                        </p>
                      </div>
                    </div>
                    <div className="mt-4 grid gap-2">
                      <Label htmlFor="namespace">Namespace</Label>
                      <Input
                        id="namespace"
                        value={namespace}
                        onChange={(e) => onNamespaceChange(e.target.value)}
                        placeholder="default"
                      />
                    </div>
                    <div className="mt-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                      Allowed namespaces: {currentUserNamespaces}
                    </div>
                  </section>

                  <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
                    <div className="flex items-start gap-3">
                      <div className="rounded-lg border border-border bg-muted/50 p-2 text-muted-foreground">
                        <LockKeyhole className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-foreground">Account security</div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Password changes are available for local accounts.
                        </p>
                      </div>
                    </div>
                    {canChangePassword ? (
                      <div className="mt-4 grid gap-3">
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
                        <Button className="justify-self-end" onClick={() => void handleChangePassword()} disabled={passwordBusy}>
                          {passwordBusy ? "Updating..." : "Change password"}
                        </Button>
                      </div>
                    ) : (
                      <div className="mt-4 rounded-lg border border-border bg-muted/30 px-3 py-3 text-sm text-muted-foreground">
                        Password policy is managed by {providerLabel(currentUser.auth_provider)}.
                      </div>
                    )}
                  </section>
                </div>

                {isAdmin ? (
                  <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex items-start gap-3">
                        <div className="rounded-lg border border-primary/20 bg-primary/10 p-2 text-primary">
                          <Users className="h-5 w-5" />
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-foreground">Team access</div>
                          <p className="mt-1 max-w-xl text-xs text-muted-foreground">
                            Create local users and adjust role, active state, or namespace scope.
                          </p>
                        </div>
                      </div>
                      <Button variant="outline" size="sm" className="gap-2" onClick={() => void handleRefreshUsers()} disabled={adminLoading}>
                        <RefreshCw className={adminLoading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
                        {adminLoading ? "Refreshing" : "Refresh"}
                      </Button>
                    </div>

                    {adminError ? (
                      <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                        {adminError}
                      </div>
                    ) : null}

                    <div className="mt-4 rounded-xl border border-border bg-muted/25 p-4">
                      <div className="mb-3 text-sm font-semibold text-foreground">Create local user</div>
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
                      <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
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
                          <Label htmlFor="create-namespaces">Additional namespaces</Label>
                          <Input
                            id="create-namespaces"
                            value={createAllowedNamespaces}
                            onChange={(e) => setCreateAllowedNamespaces(e.target.value)}
                            placeholder="team-a, finance"
                          />
                        </div>
                      </div>
                      <div className="mt-4 flex justify-end">
                        <Button onClick={() => void handleCreateUser()} disabled={createUserBusy}>
                          {createUserBusy ? "Creating..." : "Create user"}
                        </Button>
                      </div>
                    </div>

                    <div className="mt-4 grid max-h-[24rem] gap-3 overflow-y-auto pr-1">
                      {adminUsers.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-center text-sm text-muted-foreground">
                          No local or federated users are registered yet.
                        </div>
                      ) : (
                        adminUsers.map((user) => {
                          const draft = adminUserDrafts[String(user.id)] ?? draftFromUser(user);
                          return (
                            <div key={user.id} className="rounded-xl border border-border bg-background p-4">
                              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                                <div className="min-w-0">
                                  <div className="truncate text-sm font-semibold text-foreground">{user.username}</div>
                                  <div className="mt-1 text-xs text-muted-foreground">
                                    {providerLabel(user.auth_provider)} {user.last_login_at ? `- last login ${user.last_login_at}` : "- never logged in"}
                                  </div>
                                </div>
                                <div className={user.is_active ? "text-xs font-medium text-emerald-600" : "text-xs font-medium text-muted-foreground"}>
                                  {user.is_active ? "Active" : "Disabled"}
                                </div>
                              </div>

                              <div className="mt-3 grid gap-3 sm:grid-cols-2">
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

                              <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem] sm:items-end">
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
                                <label className="flex h-9 items-center gap-2 rounded-md border border-border bg-muted/30 px-3 text-sm text-foreground">
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

                              <div className="mt-3 flex items-center justify-between gap-3">
                                <div className="truncate text-xs text-muted-foreground">{user.email || "No email"}</div>
                                <Button size="sm" onClick={() => void handleSaveUser(user)} disabled={adminSavingUserId === user.id}>
                                  {adminSavingUserId === user.id ? "Saving..." : "Save changes"}
                                </Button>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </section>
                ) : (
                  <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
                    <div className="text-sm font-semibold text-foreground">Access level</div>
                    <p className="mt-2 text-sm text-muted-foreground">
                      Your current role can run and inspect workflows in the allowed namespace scope. User management is available to administrators.
                    </p>
                  </section>
                )}
              </div>
            </div>

            {connectionError ? (
              <div className="border-t border-border/70 px-6 py-3">
                <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                  {connectionError}
                </div>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="flex max-h-[88vh] flex-col overflow-hidden bg-background text-foreground">
            <div className="border-b border-border/70 bg-muted/30 px-6 py-5">
              <DialogHeader className="pr-10">
                <DialogTitle className="text-xl">Connect to KubeSynapse</DialogTitle>
                <DialogDescription className="mt-2 max-w-2xl">
                  Use managed sign-in for people, or a bearer token for automation and recovery access.
                </DialogDescription>
              </DialogHeader>
            </div>
            <div className="min-h-0 overflow-y-auto px-6 py-5">
              <div className="grid gap-5 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)]">
                <div className="space-y-4">
                  <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
                    <div className="flex items-start gap-3">
                      <div className="rounded-lg border border-border bg-muted/50 p-2 text-muted-foreground">
                        <Building2 className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-foreground">Workspace context</div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Choose the namespace for this console session.
                        </p>
                      </div>
                    </div>
                    <div className="mt-4 grid gap-2">
                      <Label htmlFor="namespace">Namespace</Label>
                      <Input
                        id="namespace"
                        value={namespace}
                        onChange={(e) => onNamespaceChange(e.target.value)}
                        placeholder="default"
                      />
                    </div>
                  </section>

                  {!currentUser ? (
                    <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
                      <div className="flex items-start gap-3">
                        <div className="rounded-lg border border-border bg-muted/50 p-2 text-muted-foreground">
                          <KeyRound className="h-5 w-5" />
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-foreground">Automation bearer token</div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            Intended for non-interactive access and bootstrap recovery.
                          </p>
                        </div>
                      </div>
                      <div className="mt-4 grid gap-2">
                        <Label htmlFor="token">Bearer token</Label>
                        <Input
                          id="token"
                          type="password"
                          value={token}
                          onChange={(e) => onTokenChange(e.target.value)}
                          placeholder="Paste bearer token"
                        />
                      </div>
                      <Button onClick={handleConnect} disabled={isConnecting} className="mt-4 w-full gap-2">
                        {isConnecting && <Loader2 className="h-4 w-4 animate-spin" />}
                        {isConnecting ? "Connecting..." : "Connect with token"}
                      </Button>
                    </section>
                  ) : null}
                </div>
                <div className="space-y-4">
                  {(authConfig?.browser_auth_enabled || passwordProviders.length > 0 || oidcProviders.length > 0 || samlProviders.length > 0) && (
            <>
              {ssoProviders.length > 0 && (
                <section className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm shadow-sm">
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-background/90 p-2 text-primary shadow-sm">
                      <ShieldCheck className="h-4 w-4" />
                    </div>
                    <div>
                      <div className="font-medium text-foreground">Recommended for browser access</div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {recommendedAuthCopy(primarySsoProvider)}
                      </p>
                    </div>
                  </div>
                </section>
              )}
              {passwordProviders.length > 0 && (
                <section className="grid gap-3 rounded-xl border border-border bg-card p-4 shadow-sm">
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
                </section>
              )}
              {ssoProviders.length > 0 && (
                <section className="grid gap-3 rounded-xl border border-border bg-card p-4 shadow-sm">
                  <div>
                    <div className="text-sm font-medium">Managed sign-in</div>
                    <div className="text-xs text-muted-foreground">
                      Browser flow for people. Returns here after authentication.
                    </div>
                  </div>
                  {primarySsoProvider && (
                    <Button
                      variant="outline"
                      className="h-11 w-full justify-center gap-3 rounded-xl"
                      onClick={() => launchAuthProvider(primarySsoProvider, {
                        onOidcStart: onStartOidc,
                        onSamlStart: onStartSaml,
                      })}
                    >
                      <AuthProviderBrandIcon brand={primarySsoProvider.brand} />
                      {primarySsoProvider.label}
                    </Button>
                  )}
                  {secondarySsoProviders.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {secondarySsoProviders.map((provider) => (
                        <Button
                          key={`${provider.kind}:${provider.id}`}
                          variant="outline"
                          size="sm"
                          className="justify-start gap-3"
                          onClick={() => launchAuthProvider(provider, {
                            onOidcStart: onStartOidc,
                            onSamlStart: onStartSaml,
                          })}
                        >
                          <AuthProviderBrandIcon brand={provider.brand} />
                          {provider.label}
                        </Button>
                      ))}
                    </div>
                  )}
                </section>
              )}
            </>
          )}
                  {connectionError ? (
                    <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                      {connectionError}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
