import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { McpProfile } from "@/types";
import {
  PROFILE_COLORS,
  SUPPORT_STYLES,
  TRANSPORT_STYLES,
  resolveIcon,
} from "./mcp-helpers";

interface McpProfilesTabProps {
  profiles: McpProfile[];
}

export function McpProfilesTab({ profiles }: McpProfilesTabProps) {
  return (
    <div className="animate-fade-in space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-foreground">Curated MCP Profiles</h2>
        <p className="text-sm text-muted-foreground">
          Pre-configured server bundles for common workflows. Apply a profile when creating an agent to instantly equip
          it with the right tools.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {profiles.map((profile) => {
          const colors = PROFILE_COLORS[profile.color] ?? PROFILE_COLORS.sky;
          const Icon = resolveIcon(profile.icon);

          return (
            <Card
              key={profile.id}
              className={`rounded-2xl border bg-card/55 transition-all hover:-translate-y-0.5 hover:shadow-lg ${colors.border} ${colors.bg}`}
            >
              <CardContent className="p-5 space-y-4">
                <div className="flex items-start gap-3">
                  <div
                    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border bg-background/80 ${colors.border}`}
                  >
                    <Icon className={`h-5 w-5 ${colors.accent}`} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-base font-semibold text-foreground">{profile.name}</h3>
                    <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">{profile.description}</p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl border border-border/40 bg-background/60 p-2.5 text-center">
                    <p className="text-lg font-bold tabular-nums text-foreground">{profile.resolved_servers.length}</p>
                    <p className="text-xs text-muted-foreground">Servers</p>
                  </div>
                  <div className="rounded-xl border border-border/40 bg-background/60 p-2.5 text-center">
                    <p className="text-lg font-bold tabular-nums text-foreground">{profile.total_tools}</p>
                    <p className="text-xs text-muted-foreground">Tools</p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline" className={`text-xs ${SUPPORT_STYLES[profile.support_level]}`}>
                    {profile.attachable_servers.length}/{profile.resolved_servers.length} attachable now
                  </Badge>
                  {profile.blocked_servers.length > 0 && (
                    <Badge variant="outline" className="text-xs border-amber-500/20 bg-amber-500/5 text-amber-500">
                      {profile.blocked_servers.length} blocked
                    </Badge>
                  )}
                </div>

                <div className="space-y-2">
                  <p className="text-xs font-medium uppercase text-muted-foreground">Included servers</p>
                  <div className="flex flex-wrap gap-2">
                    {profile.resolved_servers.map((s) => {
                      const tStyle = TRANSPORT_STYLES[s.transport];
                      return (
                        <Badge
                          key={s.id}
                          variant="outline"
                          className={`text-xs ${tStyle.bg} ${tStyle.color} ${tStyle.border}`}
                        >
                          {s.name}
                        </Badge>
                      );
                    })}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  {profile.tags.map((tag) => (
                    <span key={tag} className="rounded-full bg-background/60 px-2.5 py-0.5 text-xs text-muted-foreground">
                      {tag}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
