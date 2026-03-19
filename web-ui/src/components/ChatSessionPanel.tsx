import { memo, useState } from "react";
import { Clock, MessageSquare, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import type { ChatSessionInfo } from "@/lib/api";

interface ChatSessionPanelProps {
  sessions: ChatSessionInfo[];
  activeSessionId: string | null;
  loading: boolean;
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
      className={`group flex items-center gap-2 rounded-md px-2.5 py-2 text-sm cursor-pointer transition-colors ${
        isActive
          ? "bg-primary/10 border border-primary/20 text-foreground"
          : "hover:bg-muted/50 text-muted-foreground hover:text-foreground"
      }`}
      onClick={() => !editing && onLoad()}
      onKeyDown={(e) => { if (e.key === "Enter" && !editing) onLoad(); }}
      role="button"
      tabIndex={0}
    >
      <MessageSquare className="h-3.5 w-3.5 shrink-0" />
      <div className="flex-1 min-w-0">
        {editing ? (
          <Input
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={() => { setEditing(false); if (editTitle.trim() && editTitle !== session.title) onRename(editTitle.trim()); }}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); setEditing(false); if (editTitle.trim() && editTitle !== session.title) onRename(editTitle.trim()); }
              if (e.key === "Escape") { setEditing(false); setEditTitle(session.title); }
            }}
            className="h-6 text-xs px-1"
            autoFocus
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <>
            <div className="truncate text-xs font-medium">{session.title}</div>
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground/60">
              <Clock className="h-2.5 w-2.5" />
              {formatRelativeTime(session.updated_at)}
            </div>
          </>
        )}
      </div>
      {!editing && (
        <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={(e) => { e.stopPropagation(); setEditing(true); }} title="Rename">
            <Pencil className="h-3 w-3" />
          </Button>
          <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive" onClick={(e) => { e.stopPropagation(); onDelete(); }} title="Delete">
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      )}
    </div>
  );
});

export const ChatSessionPanel = memo(function ChatSessionPanel({
  sessions,
  activeSessionId,
  loading,
  onNewSession,
  onLoadSession,
  onDeleteSession,
  onRenameSession,
  onSaveCurrent,
}: ChatSessionPanelProps) {
  return (
    <div className="flex h-full w-52 shrink-0 flex-col border-r border-border bg-background/50 xl:w-56">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Sessions</span>
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onSaveCurrent} title="Save current session">
            <Clock className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onNewSession} title="New session">
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {loading && sessions.length === 0 && (
            <div className="flex items-center justify-center py-6 text-xs text-muted-foreground">Loading...</div>
          )}
          {!loading && sessions.length === 0 && (
            <div className="flex flex-col items-center justify-center py-6 text-xs text-muted-foreground gap-1">
              <MessageSquare className="h-5 w-5 opacity-40" />
              <span>No saved sessions</span>
            </div>
          )}
          {sessions.map((s) => (
            <SessionItem
              key={s.session_id}
              session={s}
              isActive={activeSessionId === s.session_id}
              onLoad={() => onLoadSession(s.session_id)}
              onDelete={() => onDeleteSession(s.session_id)}
              onRename={(title) => onRenameSession(s.session_id, title)}
            />
          ))}
        </div>
      </ScrollArea>
    </div>
  );
});
