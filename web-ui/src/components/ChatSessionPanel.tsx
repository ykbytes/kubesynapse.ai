import { memo, useMemo, useState } from "react";
import { Brain, Clock, MessageSquare, Pencil, Plus, Search, Trash2, Wrench } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ChatSessionInfo } from "@/lib/api";

interface ChatSessionPanelProps {
  sessions: ChatSessionInfo[];
  activeSessionId: string | null;
  loading: boolean;
  search: string;
  onSearchChange: (value: string) => void;
  sessionDirty: boolean;
  sessionSaving: boolean;
  lastSessionSaveAt: string | null;
  onNewSession: () => void;
  onLoadSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onRenameSession: (sessionId: string, title: string) => void;
  onSaveCurrent: () => void;
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function truncateText(value: string | null | undefined, maxChars = 72): string {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 1).trimEnd()}...`;
}

const SessionItem = memo(function SessionItem({
  session,
  isActive,
  onLoad,
  onDelete,
  onRename,
}: {
  session: ChatSessionInfo;
  isActive: boolean;
  onLoad: () => void;
  onDelete: () => void;
  onRename: (title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(session.title);

  return (
    <div
      className={`group cursor-pointer rounded-xl border px-2.5 py-2 text-sm transition-colors ${
        isActive
          ? "border-primary/30 bg-primary/8 text-foreground shadow-sm"
          : "border-transparent text-muted-foreground hover:border-border hover:bg-muted/40 hover:text-foreground"
      }`}
      onClick={() => !editing && onLoad()}
      onKeyDown={(e) => { if (e.key === "Enter" && !editing) onLoad(); }}
      role="button"
      tabIndex={0}
    >
      <div className="flex items-start gap-2">
        <div className={`mt-1 rounded-lg p-1 ${isActive ? "bg-primary/12 text-primary" : "bg-muted/60 text-muted-foreground"}`}>
          <MessageSquare className="h-3.5 w-3.5 shrink-0" />
        </div>
        <div className="min-w-0 flex-1">
          {editing ? (
            <Input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              onBlur={() => { setEditing(false); if (editTitle.trim() && editTitle !== session.title) onRename(editTitle.trim()); }}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); setEditing(false); if (editTitle.trim() && editTitle !== session.title) onRename(editTitle.trim()); }
                if (e.key === "Escape") { setEditing(false); setEditTitle(session.title); }
              }}
              className="h-7 text-xs"
              autoFocus
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <>
              <div className="truncate text-xs font-medium text-foreground">{session.title}</div>
              <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground/75">
                <Clock className="h-2.5 w-2.5" />
                {formatRelativeTime(session.updated_at)}
              </div>
              {!!session.summary && (
                <div className="mt-2 space-y-1.5 text-[10px] text-muted-foreground/80">
                  <div className="flex flex-wrap items-center gap-2">
                    <span>{session.summary.message_count} msg</span>
                    {session.summary.tool_names.length > 0 && (
                      <span className="inline-flex items-center gap-1">
                        <Wrench className="h-2.5 w-2.5" />
                        {truncateText(session.summary.tool_names.join(", "), 24)}
                      </span>
                    )}
                  </div>
                  {session.summary.last_assistant_message && (
                    <div className="line-clamp-2 text-[10px] leading-relaxed text-foreground/75">
                      {truncateText(session.summary.last_assistant_message, 96)}
                    </div>
                  )}
                  {session.summary.memory_candidates.procedural.length > 0 && (
                    <div className="inline-flex items-center gap-1 text-[10px] text-primary/80">
                      <Brain className="h-2.5 w-2.5" />
                      Memory signal
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
        {!editing && (
          <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); setEditing(true); }} title="Rename session">
              <Pencil className="h-3 w-3" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={(e) => { e.stopPropagation(); onDelete(); }} title="Delete session">
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
});

export const ChatSessionPanel = memo(function ChatSessionPanel({
  sessions,
  activeSessionId,
  loading,
  search,
  onSearchChange,
  sessionDirty,
  sessionSaving,
  lastSessionSaveAt,
  onNewSession,
  onLoadSession,
  onDeleteSession,
  onRenameSession,
  onSaveCurrent,
}: ChatSessionPanelProps) {
  const filteredSessions = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return sessions;
    return sessions.filter((session) => {
      const summary = session.summary;
      return [
        session.title,
        summary?.last_user_message,
        summary?.last_assistant_message,
        summary?.tool_names.join(" "),
      ].some((value) => String(value || "").toLowerCase().includes(query));
    });
  }, [search, sessions]);

  return (
    <div className="flex h-[20rem] w-full shrink-0 flex-col overflow-hidden rounded-[1.75rem] border border-border/70 bg-card/55 shadow-[0_18px_48px_-28px_rgba(15,23,42,0.45)] lg:h-full lg:w-[18rem] xl:w-[20rem]">
      <div className="border-b border-border px-3 py-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Sessions</span>
          <div className="flex gap-1">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onSaveCurrent} title="Save current session">
              <Clock className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onNewSession} title="Start empty session">
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        <div className="mt-3 space-y-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search sessions"
              className="h-8 pl-7 text-xs"
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
            <Badge variant={sessionSaving ? "default" : sessionDirty ? "secondary" : "outline"} className="h-5 px-1.5 text-[10px]">
              {sessionSaving ? "Saving" : sessionDirty ? "Unsaved" : "Saved"}
            </Badge>
            {lastSessionSaveAt && <span>Last save {formatRelativeTime(lastSessionSaveAt)}</span>}
            <span className="ml-auto">{filteredSessions.length}/{sessions.length}</span>
          </div>
        </div>
      </div>
      <ScrollArea className="flex-1">
        <div className="space-y-2 p-2">
          {loading && sessions.length === 0 && (
            <div className="flex items-center justify-center py-6 text-xs text-muted-foreground">Loading...</div>
          )}
          {!loading && sessions.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-1 py-6 text-xs text-muted-foreground">
              <MessageSquare className="h-5 w-5 opacity-40" />
              <span>No saved sessions</span>
            </div>
          )}
          {!loading && sessions.length > 0 && filteredSessions.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-1 py-6 text-xs text-muted-foreground">
              <Search className="h-5 w-5 opacity-40" />
              <span>No sessions match that search</span>
            </div>
          )}
          {filteredSessions.map((session) => (
            <SessionItem
              key={session.session_id}
              session={session}
              isActive={activeSessionId === session.session_id}
              onLoad={() => onLoadSession(session.session_id)}
              onDelete={() => onDeleteSession(session.session_id)}
              onRename={(title) => onRenameSession(session.session_id, title)}
            />
          ))}
        </div>
      </ScrollArea>
    </div>
  );
});
