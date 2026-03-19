import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpDown, Check, Pencil, Plus, Search, Shield, ShieldCheck, UserCog, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
      return <Badge variant="default" className="gap-1"><ShieldCheck className="h-3 w-3" />Admin</Badge>;
    case "operator":
      return <Badge variant="secondary" className="gap-1"><Shield className="h-3 w-3" />Operator</Badge>;
    default:
      return <Badge variant="outline">Viewer</Badge>;
  }
}

function statusBadge(active: boolean) {
  return active
    ? <Badge variant="outline" className="border-emerald-500/40 text-emerald-500">Active</Badge>
    : <Badge variant="outline" className="border-red-500/40 text-red-500">Locked</Badge>;
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
      const created = await createUser(token, { ...createForm, allowed_namespaces: ns.length ? ns : ["default"] });
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
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
            <UserCog className="h-5 w-5" />
            User Management
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">{users.length} user{users.length !== 1 ? "s" : ""} registered</p>
        </div>
        <Button size="sm" className="gap-1.5" onClick={() => setCreateOpen(true)}>
          <Plus className="h-3.5 w-3.5" />
          Create User
        </Button>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search users..."
          className="h-8 pl-8 text-xs"
        />
      </div>

      {/* Table */}
      <Card className="overflow-hidden">
        <ScrollArea className="max-h-[calc(100vh-280px)]">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/50 sticky top-0">
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
                <tr key={u.id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-2.5 font-medium text-foreground">{u.username}</td>
                  <td className="px-4 py-2.5 text-muted-foreground">{u.email ?? "—"}</td>
                  <td className="px-4 py-2.5">{roleBadge(u.role)}</td>
                  <td className="px-4 py-2.5">{statusBadge(u.is_active)}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {u.allowed_namespaces.map((ns) => (
                        <Badge key={ns} variant="outline" className="text-[10px] px-1.5 py-0">{ns}</Badge>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground text-xs">{formatDate(u.created_at)}</td>
                  <td className="px-4 py-2.5 text-muted-foreground text-xs">{formatDate(u.last_login_at)}</td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(u)} title="Edit user">
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className={`h-7 w-7 ${u.is_active ? "text-red-500 hover:text-red-600" : "text-emerald-500 hover:text-emerald-600"}`}
                        onClick={() => void handleToggleActive(u)}
                        title={u.is_active ? "Lock user" : "Activate user"}
                      >
                        {u.is_active ? <X className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollArea>
      </Card>

      {/* ── Create User Dialog ── */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create User</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
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
              <Label className="text-xs">Allowed Namespaces</Label>
              <Input
                value={createNamespaces}
                onChange={(e) => setCreateNamespaces(e.target.value)}
                placeholder="default, ai-platform (comma-separated)"
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
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit User — {editUser?.username}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
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
