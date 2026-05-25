import {
  Activity,
  AlertTriangle,
  BookOpen,
  Box,
  Brain,
  Cloud,
  Code,
  Database,
  Folder,
  Globe,
  GitBranch,
  Layers,
  LayoutList,
  Mail,
  MessageSquare,
  Monitor,
  Package,
  Palette,
  Plug,
  Search,
  Server,
  Sparkles,
  Users,
} from "lucide-react";
import { useState } from "react";

import { getMcpServerBrandIconPath } from "@/lib/mcp";
import type { McpTransport } from "@/types";

const ICON_MAP: Record<string, typeof Code> = {
  activity: Activity,
  "alert-triangle": AlertTriangle,
  "book-open": BookOpen,
  box: Box,
  brain: Brain,
  cloud: Cloud,
  code: Code,
  database: Database,
  folder: Folder,
  globe: Globe,
  "git-branch": GitBranch,
  layers: Layers,
  "layout-list": LayoutList,
  mail: Mail,
  "message-square": MessageSquare,
  monitor: Monitor,
  palette: Palette,
  search: Search,
  server: Server,
  sparkles: Sparkles,
  users: Users,
};

const TRANSPORT_ICON_MAP: Record<McpTransport, typeof Code> = {
  remote: Globe,
  hub: GitBranch,
  sidecar: Package,
};

const TRANSPORT_SHELL_STYLES: Record<McpTransport, string> = {
  remote: "border-sky-500/30 bg-sky-500/10",
  hub: "border-violet-500/30 bg-violet-500/10",
  sidecar: "border-amber-500/30 bg-amber-500/10",
};

const TRANSPORT_ICON_STYLES: Record<McpTransport, string> = {
  remote: "text-sky-400",
  hub: "text-violet-400",
  sidecar: "text-amber-400",
};

type McpServerBadgeIconSize = "xs" | "sm" | "md";

interface McpServerBadgeIconProps {
  serverId: string;
  serverName: string;
  transport: McpTransport;
  iconName?: string | null;
  size?: McpServerBadgeIconSize;
}

export function McpServerBadgeIcon({
  serverId,
  serverName,
  transport,
  iconName,
  size = "sm",
}: McpServerBadgeIconProps) {
  const [imageFailed, setImageFailed] = useState(false);
  const brandIcon = getMcpServerBrandIconPath(serverId);
  const FallbackIcon = (iconName ? ICON_MAP[iconName] : null) ?? TRANSPORT_ICON_MAP[transport] ?? Plug;
  const hasBrandIcon = Boolean(brandIcon) && !imageFailed;

  const shellClassName =
    size === "md"
      ? "h-12 w-12 rounded-2xl"
      : size === "xs"
        ? "h-7 w-7 rounded-lg"
        : "h-10 w-10 rounded-xl";
  const iconClassName =
    size === "md"
      ? "h-6 w-6"
      : size === "xs"
        ? "h-3.5 w-3.5"
        : "h-5 w-5";

  return (
    <div
      className={`flex shrink-0 items-center justify-center border ${shellClassName} ${
        hasBrandIcon ? "border-border/60 bg-white/95 shadow-inner shadow-black/5" : TRANSPORT_SHELL_STYLES[transport]
      }`}
      aria-hidden="true"
      title={serverName}
    >
      {hasBrandIcon ? (
        <img
          src={brandIcon ?? undefined}
          alt={`${serverName} logo`}
          className={`${iconClassName} object-contain`}
          loading="lazy"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <FallbackIcon className={`${iconClassName} ${TRANSPORT_ICON_STYLES[transport]}`} />
      )}
    </div>
  );
}