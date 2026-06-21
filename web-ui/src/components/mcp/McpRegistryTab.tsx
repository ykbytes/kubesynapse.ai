import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import type { McpCategory, McpRegistryServer, McpTransport } from "@/types";
import { TRANSPORT_STYLES } from "./mcp-helpers";
import { McpServerCard } from "./McpServerCard";
import { McpServerDetail } from "./McpServerDetail";

interface McpRegistryTabProps {
  registry: McpRegistryServer[];
  categories: McpCategory[];
  onCreateConnection: (serverId?: string) => void;
}

export function McpRegistryTab({ registry, categories, onCreateConnection }: McpRegistryTabProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTransport, setActiveTransport] = useState<McpTransport | "all">("all");
  const [activeCategory, setActiveCategory] = useState("all");
  const [selectedServer, setSelectedServer] = useState<McpRegistryServer | null>(null);

  const transportCounts = useMemo(() => {
    const counts = { all: registry.length, remote: 0, hub: 0, sidecar: 0 };
    for (const s of registry) {
      if (s.transport in counts) counts[s.transport as McpTransport]++;
    }
    return counts;
  }, [registry]);

  const filteredServers = useMemo(() => {
    let result = registry;
    if (activeTransport !== "all") {
      result = result.filter((s) => s.transport === activeTransport);
    }
    if (activeCategory !== "all") {
      result = result.filter((s) => s.category === activeCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q) ||
          s.id.toLowerCase().includes(q) ||
          s.tags.some((t) => t.toLowerCase().includes(q)),
      );
    }
    return result;
  }, [registry, activeTransport, activeCategory, searchQuery]);

  const readyServers = useMemo(() => filteredServers.filter((s) => s.support_level === "ready"), [filteredServers]);
  const deferredServers = useMemo(() => filteredServers.filter((s) => s.support_level !== "ready"), [filteredServers]);

  return (
    <div className="animate-fade-in space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1 rounded-xl border border-border/60 bg-background/75 p-1">
          {(["all", "remote", "hub", "sidecar"] as const).map((t) => {
            const isActive = activeTransport === t;
            const count = transportCounts[t];
            return (
              <button
                key={t}
                onClick={() => setActiveTransport(t)}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                  isActive
                    ? "bg-primary/15 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                }`}
                aria-pressed={isActive}
              >
                {t === "all" ? "All" : TRANSPORT_STYLES[t].label}
                <span
                  className={`rounded-full px-1.5 py-0.5 text-xs tabular-nums ${
                    isActive ? "bg-primary/20" : "bg-muted"
                  }`}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search servers, tools, or tags..."
            className="h-10 bg-background/90 pl-9"
          />
        </div>

        <select
          value={activeCategory}
          onChange={(e) => setActiveCategory(e.target.value)}
          className="h-10 rounded-xl border border-border/60 bg-background/90 px-3 text-sm text-foreground"
        >
          <option value="all">All categories</option>
          {categories.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.name} ({cat.count})
            </option>
          ))}
        </select>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-sky-500" />
          Remote
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-indigo-500" />
          Hub
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-amber-500" />
          Sidecar
        </span>
      </div>

      {/* Grid */}
      {filteredServers.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/60 bg-card/30 py-16 text-center">
          <Search className="h-10 w-10 text-muted-foreground/50" />
          <p className="mt-3 font-medium text-foreground">No servers match your filters</p>
          <p className="mt-1 text-sm text-muted-foreground">Try adjusting the transport type, category, or search query.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {readyServers.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-foreground">Ready now</p>
                <span className="text-xs text-muted-foreground">
                  {readyServers.length} server{readyServers.length === 1 ? "" : "s"}
                </span>
              </div>
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                {readyServers.map((server) => (
                  <McpServerCard
                    key={server.id}
                    server={server}
                    isSelected={selectedServer?.id === server.id}
                    onSelect={() => setSelectedServer(selectedServer?.id === server.id ? null : server)}
                  />
                ))}
              </div>
            </section>
          )}

          {deferredServers.length > 0 && (
            <section className="space-y-3">
              <p className="text-sm font-semibold text-foreground">Needs setup</p>
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                {deferredServers.map((server) => (
                  <McpServerCard
                    key={server.id}
                    server={server}
                    isSelected={selectedServer?.id === server.id}
                    onSelect={() => setSelectedServer(selectedServer?.id === server.id ? null : server)}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      {/* Detail modal */}
      <McpServerDetail
        server={selectedServer}
        onClose={() => setSelectedServer(null)}
        onCreateConnection={onCreateConnection}
      />
    </div>
  );
}
