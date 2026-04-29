import { Wrench } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { McpServerBadgeIcon } from "@/components/McpServerBadgeIcon";
import type { McpRegistryServer } from "@/types";
import {
  CATEGORY_COLORS,
  CATEGORY_STYLE,
  SUPPORT_STYLES,
  TRANSPORT_STYLES,
  formatSupportLabel,
} from "./mcp-helpers";

interface McpServerCardProps {
  server: McpRegistryServer;
  isSelected: boolean;
  onSelect: () => void;
}

export function McpServerCard({ server, isSelected, onSelect }: McpServerCardProps) {
  const transport = TRANSPORT_STYLES[server.transport];
  const categoryStyle = CATEGORY_COLORS[server.category] ?? CATEGORY_STYLE;
  const isDeferred = server.support_level !== "ready";

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group flex w-full flex-col gap-3 rounded-2xl border p-4 text-left transition-all duration-200 ${
        isSelected
          ? "border-primary/30 bg-primary/5 ring-1 ring-primary/20"
          : isDeferred
            ? "border-border/50 bg-card/40 hover:border-border/70 hover:bg-accent/20"
            : "border-border/60 bg-card/55 hover:border-primary/20 hover:bg-accent/20"
      }`}
      aria-label={`${server.name} (${transport.label})`}
    >
      <div className="flex items-start gap-3">
        <McpServerBadgeIcon
          serverId={server.id}
          serverName={server.name}
          transport={server.transport}
          iconName={server.icon}
          size="sm"
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-foreground">{server.name}</h3>
          </div>
          <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-muted-foreground">{server.description}</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={`text-xs ${transport.bg} ${transport.color} ${transport.border}`}>
          {transport.label}
        </Badge>
        <Badge variant="outline" className={`text-xs ${SUPPORT_STYLES[server.support_level]}`}>
          {formatSupportLabel(server.support_level)}
        </Badge>
        {server.auth_type !== "none" && (
          <Badge variant="outline" className="text-xs border-border/60 bg-background/80 text-foreground/70">
            {server.auth_type.replace(/_/g, " ")}
          </Badge>
        )}
        <Badge variant="outline" className={`text-xs ${categoryStyle}`}>
          {server.category}
        </Badge>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex gap-1.5">
          {server.tags.slice(0, 3).map((tag) => (
            <span key={tag} className="rounded-full bg-muted/60 px-2 py-0.5">
              {tag}
            </span>
          ))}
        </div>
        <span className="flex items-center gap-1">
          <Wrench className="h-3.5 w-3.5" />
          {server.tools_count}
        </span>
      </div>
    </button>
  );
}
