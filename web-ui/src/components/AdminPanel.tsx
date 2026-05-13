import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpDown, Check, Pencil, Plus, Search, Shield, ShieldCheck, UserCog, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

import { listUsers, createUser, updateUser, apiErrorMessage } from "@/lib/api";
import type { AdminUser, CreateUserPayload, UpdateUserPayload, UserRole } from "@/types";

interface AdminPanelProps {
  token: string;
}

type SortField = "username" | "role" | "created_at" | "is_active";
type SortDirection = "asc" | "desc";

const EMPTY_CREATE: CreateUserPayload = {
  username: "",
  password: "",
  email: "",
  display_name: "",
  role: "viewer",
  allowed_namespaces: [],
};

function roleBadge(role: UserRole) {
  switch (role) {
    case "admin":
      return <Badge variant="outline" className="gap-1 border-sky-500/25 bg-sky-500/10 text-sky-500"><ShieldCheck className="h-3 w-3" />Admin</Badge>;
    case "operator":
      return <Badge variant="outline" className="gap-1 border-amber-500/25 bg-amber-500/10 text-amber-500"><Shield className="h-3 w-3" />Operator</Badge>;
    default:
      return <Badge variant="outline" className="border-border/60 bg-background/80 text-foreground/70">Viewer</Badge>;
  }
}

function statusBadge(active: boolean) {
  return active
    ? <Badge variant="outline" className="border-emerald-500/25 bg-emerald-500/10 text-emerald-500">Active</Badge>
    : <Badge variant="outline" className="border-red-500/25 bg-red-500/10 text-red-500">Locked</Badge>;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function AdminPanel({ token }: AdminPanelProps) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [sortField, setSortField] = useState<SortField>("username");
  const [sortDir, setSortDir] = useState<SortDirection>("asc");

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<CreateUserPayload>({ ...EMPTY_CREATE });
  const [creating, setCreating] = useState(false);

  // Edit dialog
  const [editUser, setEditUser] = useState<AdminUser | null>(null);
  const [editForm, setEditForm] = useState<UpdateUserPayload>({});
  const [editNamespaces, setEditNamespaces] = useState("");
  const [saving, setSaving] = useState(false);

  // Namespace input for create
  const [createNamespaces, setCreateNamespaces] = useState("");

  const loadUsers = useCallback(async () => {
    try {
      setLoading(true);
      const data = await listUsers(token);
      setUsers(data);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { void loadUsers(); }, [loadUsers]);

  const filteredUsers = useMemo(() => {
    let list = users;
    if (filter.trim()) {
      const lower = filter.toLowerCase();
      list = list.filter(
        (u) =>
          u.username.toLowerCase().includes(lower) ||
          (u.email ?? "").toLowerCase().includes(lower) ||
          u.role.toLowerCase().includes(lower),
      );
    }
    list = [...list].sort((a, b) => {
      let cmp = 0;
      if (sortField === "username") cmp = a.username.localeCompare(b.username);
      else if (sortField === "role") cmp = a.role.localeCompare(b.role);
      else if (sortField === "is_active") cmp = Number(b.is_active) - Number(a.is_active);
      else if (sortField === "created_at") cmp = (a.created_at ?? "").localeCompare(b.created_at ?? "");
      return sortDir === "desc" ? -cmp : cmp;
    });
    return list;
  }, [users, filter, sortField, sortDir]);

  const summary = useMemo(() => ({
    total: users.length,
    active: users.filter((user) => user.is_active).length,
    admins: users.filter((user) => user.role === "admin").length,
    operators: users.filter((user) => user.role === "operator").length,
  }), [users]);

  const toggleSort = (field: SortField) => {
    if (sortField === field) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortField(field); setSortDir("asc"); }
  };

  // ── Create ──
  const handleCreate = async () => {
    setCreating(true);
    try {
      const ns = createNamespaces
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const created = await createUser(token, { ...createForm, allowed_namespaces: ns });
      setUsers((prev) => [...prev, created]);
      setCreateOpen(false);
      setCreateForm({ ...EMPTY_CREATE });
      setCreateNamespaces("");
      toast.success(`User "${created.username}" created`);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  // ── Edit ──
  const openEdit = (u: AdminUser) => {
    setEditUser(u);
    setEditForm({ display_name: u.display_name, role: u.role, is_active: u.is_active });
    setEditNamespaces(u.allowed_namespaces.join(", "));
  };

  const handleSaveEdit = async () => {
    if (!editUser) return;
    setSaving(true);
    try {
      const ns = editNamespaces
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const updated = await updateUser(token, editUser.id, { ...editForm, allowed_namespaces: ns });
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
      setEditUser(null);
      toast.success(`User "${updated.username}" updated`);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const handleToggleActive = async (u: AdminUser) => {
    try {
      const updated = await updateUser(token, u.id, { is_active: !u.is_active });
      setUsers((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      toast.success(`User "${updated.username}" ${updated.is_active ? "activated" : "locked"}`);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  };

  const SortButton = ({ field, children }: { field: SortField; children: React.ReactNode }) => (
    <button
      className="flex items-center gap-1 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
      onClick={() => toggleSort(field)}
    >
      {children}
      <ArrowUpDown className={`h-3 w-3 ${sortField === field ? "text-foreground" : "opacity-40"}`} />
    </button>
  );

  return (
    <div className="space-y-3">
      <div className="rounded-3xl border border-border/60 bg-gradient-to-br from-background/95 via-background/90 to-muted/35 p-3 shadow-sm shadow-black/5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="border-border/60 bg-background/80">Identity and access</Badge>
              <Badge variant="outline" className="border-emerald-500/25 bg-emerald-500/10 text-emerald-500">{summary.active} active accounts</Badge>
            </div>
            <div>
              <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground">
                <UserCog className="h-5 w-5" />
                User Management
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Manage platform access, roles, and namespace scope for each account from one operational surface.
              </p>
            </div>
          </div>
          <Button size="sm" className="gap-1.5" onClick={() => setCreateOpen(true)}>
            <Plus className="h-3.5 w-3.5" />
            Create User
          </Button>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
            <CardContent className="space-y-1 p-4">
              <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Total users</div>
              <div className="text-2xl font-semibold text-foreground">{summary.total}</div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
            <CardContent className="space-y-1 p-4">
              <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Active</div>
              <div className="text-2xl font-semibold text-foreground">{summary.active}</div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
            <CardContent className="space-y-1 p-4">
              <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Admins</div>
              <div className="text-2xl font-semibold text-foreground">{summary.admins}</div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
            <CardContent className="space-y-1 p-4">
              <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Operators</div>
              <div className="text-2xl font-semibold text-foreground">{summary.operators}</div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Search */}
      <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
        <CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
          <div className="relative max-w-sm flex-1">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search users..."
              className="h-9 bg-background/90 pl-8 text-xs"
            />
          </div>
          <div className="text-xs text-muted-foreground">
            Showing {filteredUsers.length} of {users.length} account{users.length === 1 ? "" : "s"}
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card className="overflow-hidden border-border/60 bg-background/80 shadow-sm shadow-black/5">
        <ScrollArea className="w-full max-h-[calc(100vh-280px)]" type="auto">
          <div className="overflow-x-auto">
            <table className="min-w-[960px] w-full text-sm">
            <thead className="sticky top-0 border-b border-border bg-background/95 backdrop-blur">
              <tr>
                <th className="px-4 py-2.5 text-left"><SortButton field="username">Username</SortButton></th>
                <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Email</th>
                <th className="px-4 py-2.5 text-left"><SortButton field="role">Role</SortButton></th>
                <th className="px-4 py-2.5 text-left"><SortButton field="is_active">Status</SortButton></th>
                <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Namespaces</th>
                <th className="px-4 py-2.5 text-left"><SortButton field="created_at">Created</SortButton></th>
                <th className="px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Last Login</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading && users.length === 0 && (
                <>
                  {[0, 1, 2, 3].map((i) => (
                    <tr key={i}>
                      {[0, 1, 2, 3, 4, 5, 6, 7].map((j) => (
                        <td key={j} className="px-4 py-3"><Skeleton className="h-4 w-full rounded" /></td>
                      ))}
                    </tr>
                  ))}
                </>
              )}
              {!loading && filteredUsers.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-sm text-muted-foreground">
                    {filter.trim() ? `No users match "${filter}"` : "No users registered."}
                  </td>
                </tr>
              )}
              {filteredUsers.map((u) => (
                <tr key={u.id} className="transition-colors hover:bg-accent/30">
                  <td className="px-4 py-2.5 font-medium text-foreground">{u.username}</td>
                  <td className="px-4 py-2.5 text-muted-foreground">{u.email ?? "—"}</td>
                  <td className="px-4 py-2.5">{roleBadge(u.role)}</td>
                  <td className="px-4 py-2.5">{statusBadge(u.is_active)}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {u.allowed_namespaces.map((ns) => (
                        <Badge key={ns} variant="outline" className="border-border/60 bg-background/90 px-1.5 py-0 text-[10px]">{ns}</Badge>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground text-xs">{formatDate(u.created_at)}</td>
                  <td className="px-4 py-2.5 text-muted-foreground text-xs">{formatDate(u.last_login_at)}</td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(u)} title="Edit user" aria-label="Edit user">
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className={`h-7 w-7 ${u.is_active ? "text-red-500 hover:text-red-600" : "text-emerald-500 hover:text-emerald-600"}`}
                        onClick={() => void handleToggleActive(u)}
                        title={u.is_active ? "Lock user" : "Activate user"}
                        aria-label={u.is_active ? "Lock user" : "Activate user"}
                      >
                        {u.is_active ? <X className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </ScrollArea>
      </Card>

      {/* ── Create User Dialog ── */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="border-border/60 bg-background/95 shadow-2xl sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create User</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 pt-2">
            <div className="space-y-1">
              <Label className="text-xs">Username</Label>
              <Input
                value={createForm.username}
                onChange={(e) => setCreateForm((f) => ({ ...f, username: e.target.value }))}
                placeholder="john.doe"
                className="h-8 text-sm"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Password</Label>
              <Input
                type="password"
                value={createForm.password}
                onChange={(e) => setCreateForm((f) => ({ ...f, password: e.target.value }))}
                placeholder="Min 8 characters"
                className="h-8 text-sm"
                autoComplete="new-password"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Email</Label>
              <Input
                type="email"
                value={createForm.email ?? ""}
                onChange={(e) => setCreateForm((f) => ({ ...f, email: e.target.value }))}
                placeholder="Optional"
                className="h-8 text-sm"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Display Name</Label>
              <Input
                value={createForm.display_name ?? ""}
                onChange={(e) => setCreateForm((f) => ({ ...f, display_name: e.target.value }))}
                placeholder="Optional"
                className="h-8 text-sm"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Role</Label>
              <Select value={createForm.role ?? "viewer"} onValueChange={(v) => setCreateForm((f) => ({ ...f, role: v as UserRole }))}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="viewer">Viewer</SelectItem>
                  <SelectItem value="operator">Operator</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Additional Namespaces</Label>
              <Input
                value={createNamespaces}
                onChange={(e) => setCreateNamespaces(e.target.value)}
                placeholder="team-a, ai-platform (optional)"
                className="h-8 text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button size="sm" onClick={() => void handleCreate()} disabled={creating || !createForm.username.trim() || !createForm.password}>
              {creating ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Edit User Dialog ── */}
      <Dialog open={!!editUser} onOpenChange={(open) => { if (!open) setEditUser(null); }}>
        <DialogContent className="border-border/60 bg-background/95 shadow-2xl sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit User — {editUser?.username}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 pt-2">
            <div className="space-y-1">
              <Label className="text-xs">Display Name</Label>
              <Input
                value={editForm.display_name ?? ""}
                onChange={(e) => setEditForm((f) => ({ ...f, display_name: e.target.value }))}
                className="h-8 text-sm"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Role</Label>
              <Select value={editForm.role ?? "viewer"} onValueChange={(v) => setEditForm((f) => ({ ...f, role: v as UserRole }))}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="viewer">Viewer</SelectItem>
                  <SelectItem value="operator">Operator</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Status</Label>
              <Select value={editForm.is_active ? "active" : "locked"} onValueChange={(v) => setEditForm((f) => ({ ...f, is_active: v === "active" }))}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="locked">Locked</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Allowed Namespaces</Label>
              <Input
                value={editNamespaces}
                onChange={(e) => setEditNamespaces(e.target.value)}
                placeholder="default, ai-platform"
                className="h-8 text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setEditUser(null)}>Cancel</Button>
            <Button size="sm" onClick={() => void handleSaveEdit()} disabled={saving}>
              {saving ? "Saving..." : "Save Changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
