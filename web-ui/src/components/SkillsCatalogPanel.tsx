import { useEffect, useState } from "react";
import { Search, Package, LoaderCircle, ChevronLeft, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { fetchSkillsCatalog, fetchCatalogSkillDetail } from "@/lib/api";
import type { CatalogSkill, CatalogSkillDetail } from "@/types";

const CATEGORY_COLORS: Record<string, string> = {
  design: "bg-violet-500/20 text-violet-300 border-violet-500/30",
  development: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  document: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  communication: "bg-green-500/20 text-green-300 border-green-500/30",
  productivity: "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
};

/* ── Props ── */

interface SkillsCatalogPanelProps {
  token: string;
  onAttachSkill?: (skillId: string, files: Record<string, string>) => void;
}

/* ── Component ── */

export function SkillsCatalogPanel({ token, onAttachSkill }: SkillsCatalogPanelProps) {
  const [skills, setSkills] = useState<CatalogSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<CatalogSkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (!token) {
      setSkills([]);
      return;
    }
    setLoading(true);
    setError("");
    fetchSkillsCatalog(token, categoryFilter || undefined, searchQuery || undefined)
      .then((skillsData) => {
        setSkills(skillsData);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [token, categoryFilter, searchQuery]);

  async function handleViewSkill(skillId: string) {
    setDetailLoading(true);
    try {
      const detail = await fetchCatalogSkillDetail(token, skillId);
      setSelectedSkill(detail);
    } catch (e) {
      setError(String(e));
    } finally {
      setDetailLoading(false);
    }
  }

  const categories = [...new Set(skills.map((s) => s.category))].sort();

  if (selectedSkill) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => setSelectedSkill(null)}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div className="flex-1">
              <CardTitle className="text-base">{selectedSkill.name}</CardTitle>
              <CardDescription>{selectedSkill.description}</CardDescription>
            </div>
            {onAttachSkill && (
              <Button
                size="sm"
                className="gap-1.5"
                onClick={() => onAttachSkill(selectedSkill.id, selectedSkill.assets)}
              >
                <Plus className="h-3.5 w-3.5" />
                Attach to Agent
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline" className={CATEGORY_COLORS[selectedSkill.category] ?? ""}>
              {selectedSkill.category}
            </Badge>
            {selectedSkill.tags.map((tag) => (
              <Badge key={tag} variant="secondary" className="text-xs">
                {tag}
              </Badge>
            ))}
          </div>

          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2">Files ({selectedSkill.files.length})</h4>
            <div className="space-y-2">
              {selectedSkill.files.map((file) => (
                <div key={file} className="rounded-md border border-border bg-card/50 p-3">
                  <p className="text-xs font-mono text-foreground">{file}</p>
                  {selectedSkill.assets[file] && (
                    <pre className="mt-2 text-xs text-muted-foreground overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                      {selectedSkill.assets[file].slice(0, 2000)}
                      {selectedSkill.assets[file].length > 2000 && "\n... (truncated)"}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Package className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <CardTitle className="text-base">Skills Catalog</CardTitle>
            <CardDescription>
              Browse reusable skills, templates, and starter assets for your agents.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search skills..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>
          <Select value={categoryFilter || "__all__"} onValueChange={(v) => setCategoryFilter(v === "__all__" ? "" : v)}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="All categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All categories</SelectItem>
              {categories.map((cat) => (
                <SelectItem key={cat} value={cat}>
                  {cat}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        {!token ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            Connect to a gateway to browse the skills catalog.
          </p>
        ) : loading ? (
          <div className="grid gap-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-start gap-3 rounded-md border border-border bg-card/50 p-3">
                <Skeleton className="h-8 w-8 rounded-md shrink-0" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-32 rounded" />
                  <Skeleton className="h-3 w-full rounded" />
                  <div className="flex gap-1.5">
                    <Skeleton className="h-4 w-14 rounded-full" />
                    <Skeleton className="h-4 w-14 rounded-full" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : skills.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            No skills found. Check your catalog configuration.
          </p>
        ) : (
          <ScrollArea className="max-h-[500px]">
            <div className="grid gap-2">
              {skills.map((skill) => (
                <div
                  key={skill.id}
                  className="group flex items-start gap-3 rounded-md border border-border bg-card/50 p-3 hover:bg-accent/50 cursor-pointer transition-colors"
                  onClick={() => void handleViewSkill(skill.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") void handleViewSkill(skill.id);
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-foreground truncate">{skill.name}</p>
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${CATEGORY_COLORS[skill.category] ?? ""}`}
                      >
                        {skill.category}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                      {skill.description}
                    </p>
                    <div className="flex items-center gap-2 mt-1.5">
                      <span className="text-[10px] text-muted-foreground">
                        {skill.files.length} file{skill.files.length !== 1 ? "s" : ""}
                      </span>
                      {skill.tags.slice(0, 3).map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-[10px] px-1 py-0">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  {onAttachSkill && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={(e) => {
                        e.stopPropagation();
                        void (async () => {
                          const detail = await fetchCatalogSkillDetail(token, skill.id);
                          onAttachSkill(skill.id, detail.assets);
                        })();
                      }}
                    >
                      <Plus className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
        {detailLoading && (
          <div className="flex items-center justify-center py-4">
            <LoaderCircle className="h-4 w-4 animate-spin text-muted-foreground mr-2" />
            <span className="text-sm text-muted-foreground">Loading skill details...</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
