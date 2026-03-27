import { memo } from "react";
import { Send, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface FollowupItem {
  id: string;
  text: string;
}

interface FollowupDockProps {
  items: FollowupItem[];
  sending?: string;
  onSend: (id: string) => void;
  onEdit: (id: string) => void;
}

export const FollowupDock = memo(function FollowupDock({
  items,
  sending,
  onSend,
  onEdit,
}: FollowupDockProps) {
  if (!items.length) return null;

  return (
    <div className="space-y-1.5 pb-2">
      <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground px-1">
        Suggested follow-ups
      </p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => {
          const isSending = sending === item.id;
          return (
            <div
              key={item.id}
              className="group flex items-center gap-1 rounded-xl border border-border/60 bg-muted/20 pl-3 pr-1 py-1.5 text-sm transition-colors hover:border-primary/30 hover:bg-primary/5"
            >
              <span className="text-foreground/85 text-[13px] leading-snug max-w-[24rem] truncate">
                {item.text}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-primary opacity-70 group-hover:opacity-100 transition-opacity"
                onClick={() => onSend(item.id)}
                disabled={!!sending}
                title="Send now"
              >
                {isSending ? (
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                ) : (
                  <Send className="h-3 w-3" />
                )}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-70 transition-opacity"
                onClick={() => onEdit(item.id)}
                disabled={!!sending}
                title="Edit before sending"
              >
                <Pencil className="h-3 w-3" />
              </Button>
            </div>
          );
        })}
      </div>
    </div>
  );
});
