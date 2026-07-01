import { useMemo, useState } from "react";
import {
  Archive,
  CalendarClock,
  Check,
  ChevronRight,
  Code2,
  Download,
  FlaskConical,
  Search,
  Tag,
  X,
} from "lucide-react";
import { Highlight, type Language } from "prism-react-renderer";

import { KubeSynapseTheme } from "@/components/docs/shared";
import { CopyButton } from "@/components/shared/CopyButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { OptimizationCandidate } from "@/types";

type CandidateRegistryPanelProps = {
  candidates: OptimizationCandidate[];
  selectedCandidateId: string | null;
  loading: boolean;
  includeArchived: boolean;
  actionLoading: string | null;
  manifest: string;
  manifestLoading: boolean;
  onIncludeArchivedChange: (value: boolean) => void;
  onSelect: (candidate: OptimizationCandidate) => void;
  onUpdateTags: (candidate: OptimizationCandidate, tags: string[]) => void;
  onArchive: (candidate: OptimizationCandidate) => void;
  onDownload: () => void;
};

function expectedGain(candidate: OptimizationCandidate) {
  const metrics: Array<[string, string]> = [
    ["time", "duration_saved_percent"],
    ["tokens", "tokens_saved_percent"],
    ["tools", "tool_calls_saved_percent"],
    ["cost", "cost_saved_percent"],
  ];
  const gains = metrics.flatMap(([label, key]) => {
    const value = candidate.expected_savings?.[key];
    return typeof value === "number" && Number.isFinite(value)
      ? [`${Math.round(value)}% ${label}`]
      : [];
  });
  return gains.length > 0 ? gains.slice(0, 3).join(" · ") : "Awaiting trial estimate";
}

function formatDate(value?: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "--"
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function statusClass(candidate: OptimizationCandidate) {
  if (candidate.lifecycle_state === "archived") return "border-border bg-muted text-muted-foreground";
  if (candidate.status === "promoted") return "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300";
  if (candidate.approval_status === "approved") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  return "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300";
}

export function CandidateRegistryPanel({
  candidates,
  selectedCandidateId,
  loading,
  includeArchived,
  actionLoading,
  manifest,
  manifestLoading,
  onIncludeArchivedChange,
  onSelect,
  onUpdateTags,
  onArchive,
  onDownload,
}: CandidateRegistryPanelProps) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [tagInput, setTagInput] = useState("");
  const [archiveTarget, setArchiveTarget] = useState<OptimizationCandidate | null>(null);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return candidates.filter((candidate) => {
      if (status !== "all") {
        const state = candidate.lifecycle_state === "archived"
          ? "archived"
          : candidate.status === "promoted"
            ? "promoted"
            : candidate.approval_status === "approved"
              ? "approved"
              : "pending";
        if (state !== status) return false;
      }
      if (!query) return true;
      return [
        candidate.name,
        candidate.candidate_workflow_name,
        candidate.workflow_name,
        candidate.id,
        ...(candidate.tags ?? []),
      ].some((value) => String(value ?? "").toLowerCase().includes(query));
    });
  }, [candidates, search, status]);

  const selected = candidates.find((candidate) => candidate.id === selectedCandidateId) ?? null;

  const addTag = () => {
    const tag = tagInput.trim();
    if (!selected || !tag) return;
    const exists = selected.tags.some((item) => item.toLowerCase() === tag.toLowerCase());
    if (!exists) onUpdateTags(selected, [...selected.tags, tag]);
    setTagInput("");
  };

  return (
    <section className="min-h-0 min-w-0 max-w-full overflow-hidden rounded-lg border border-border/60 bg-card">
      <header className="flex flex-wrap items-center gap-2 border-b border-border/50 px-3 py-2.5">
        <div className="min-w-0 basis-[13rem] flex-1">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-primary" />
            <h4 className="text-sm font-semibold">Candidate registry</h4>
            <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">{candidates.length}</Badge>
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Versioned candidates across every study for this workflow.
          </p>
        </div>
        <div className="relative min-w-0 basis-[14rem] flex-1 md:max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            aria-label="Search candidates"
            className="h-8 pl-8 text-xs"
            placeholder="Search name, ID, or tag"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="h-8 w-[9rem] text-xs" aria-label="Filter candidate status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All states</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="promoted">Promoted</SelectItem>
            <SelectItem value="archived">Archived</SelectItem>
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant={includeArchived ? "secondary" : "outline"}
          size="sm"
          className="h-8 text-xs"
          onClick={() => onIncludeArchivedChange(!includeArchived)}
        >
          <Archive className="mr-1.5 h-3.5 w-3.5" />
          {includeArchived ? "Hide archived" : "Show archived"}
        </Button>
      </header>

      <div className="min-h-[16rem] max-h-[24rem] max-w-full overflow-y-auto overflow-x-hidden">
        <div className="hidden xl:grid-cols-[minmax(0,2fr)_minmax(0,0.75fr)_minmax(0,1.25fr)_minmax(0,0.5fr)_minmax(0,0.9fr)_1.5rem] gap-3 border-b border-border/50 bg-muted/25 px-3 py-2 text-[10px] font-semibold uppercase text-muted-foreground xl:grid">
          <span>Candidate</span>
          <span>State</span>
          <span>Expected gain</span>
          <span>Trials</span>
          <span>Created</span>
          <span />
        </div>

        {loading && candidates.length === 0 ? (
          <div className="flex min-h-[16rem] items-center justify-center text-xs text-muted-foreground">
            Loading candidate inventory…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex min-h-[16rem] flex-col items-center justify-center px-5 text-center">
            <FlaskConical className="mb-2 h-7 w-7 text-muted-foreground/50" />
            <p className="text-sm font-medium">No matching candidates</p>
            <p className="mt-1 max-w-md text-xs text-muted-foreground">
              Run an ROI study to create the first isolated candidate, or adjust the current filters.
            </p>
          </div>
        ) : (
          filtered.map((candidate) => {
            const active = candidate.id === selectedCandidateId;
            return (
              <button
                type="button"
                key={candidate.id}
                className={cn(
                  "grid min-w-0 w-full max-w-full gap-2 border-b border-border/40 px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-muted/40",
                  "xl:grid-cols-[minmax(0,2fr)_minmax(0,0.75fr)_minmax(0,1.25fr)_minmax(0,0.5fr)_minmax(0,0.9fr)_1.5rem] xl:items-center xl:gap-3",
                  active && "bg-primary/[0.06] shadow-[inset_3px_0_0_hsl(var(--primary))]",
                )}
                onClick={() => onSelect(candidate)}
              >
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-xs font-semibold text-foreground">
                      {candidate.candidate_workflow_name || candidate.name}
                    </span>
                    {active && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                  </span>
                  <span className="mt-0.5 block truncate font-mono text-[10px] text-muted-foreground">
                    {candidate.workflow_name ?? "workflow"} · {candidate.id}
                  </span>
                  {candidate.tags.length > 0 && (
                    <span className="mt-1 flex flex-wrap gap-1">
                      {candidate.tags.slice(0, 3).map((tag) => (
                        <Badge key={tag} variant="outline" className="h-4 px-1 text-[9px] font-normal">{tag}</Badge>
                      ))}
                      {candidate.tags.length > 3 && (
                        <span className="text-[9px] text-muted-foreground">+{candidate.tags.length - 3}</span>
                      )}
                    </span>
                  )}
                </span>
                <span>
                  <Badge variant="outline" className={cn("h-5 text-[9px]", statusClass(candidate))}>
                    {candidate.lifecycle_state === "archived"
                      ? "archived"
                      : candidate.status === "promoted"
                        ? "promoted"
                        : candidate.approval_status}
                  </Badge>
                </span>
                <span className="text-[11px] text-foreground">
                  <span className="xl:hidden text-muted-foreground">Expected gain: </span>
                  {expectedGain(candidate)}
                </span>
                <span className="flex items-center gap-1 text-[11px]">
                  <FlaskConical className="h-3 w-3 text-muted-foreground" />
                  {candidate.trial_count ?? 0}
                </span>
                <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                  <CalendarClock className="h-3 w-3 shrink-0" />
                  {formatDate(candidate.created_at)}
                </span>
                <ChevronRight className="hidden h-4 w-4 text-muted-foreground xl:block" />
              </button>
            );
          })
        )}
      </div>

      {selected && (
        <footer className="border-t border-border/60 bg-muted/15 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <div className="mr-auto min-w-0 basis-[12rem]">
              <p className="text-[10px] font-semibold uppercase text-muted-foreground">Selected candidate</p>
              <p className="truncate text-xs font-medium">{selected.candidate_workflow_name}</p>
            </div>
            <div className="flex min-w-0 basis-[16rem] flex-1 flex-wrap items-center gap-1 md:max-w-xl">
              <Tag className="mr-1 h-3.5 w-3.5 text-muted-foreground" />
              {selected.tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="h-6 gap-1 pl-2 pr-1 text-[10px]">
                  {tag}
                  {selected.lifecycle_state === "active" && (
                    <span
                      role="button"
                      tabIndex={0}
                      aria-label={`Remove tag ${tag}`}
                      className="rounded p-0.5 hover:bg-background"
                      onClick={(event) => {
                        event.stopPropagation();
                        onUpdateTags(selected, selected.tags.filter((item) => item !== tag));
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onUpdateTags(selected, selected.tags.filter((item) => item !== tag));
                        }
                      }}
                    >
                      <X className="h-3 w-3" />
                    </span>
                  )}
                </Badge>
              ))}
              {selected.lifecycle_state === "active" && (
                <div className="flex min-w-0 basis-[11rem] flex-1 items-center gap-1">
                  <Input
                    aria-label="Candidate tag"
                    className="h-7 min-w-0 text-xs"
                    maxLength={40}
                    placeholder="Add tag"
                    value={tagInput}
                    onChange={(event) => setTagInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        addTag();
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    disabled={!tagInput.trim() || actionLoading === `tags:${selected.id}`}
                    onClick={addTag}
                  >
                    Add tag
                  </Button>
                </div>
              )}
            </div>
            {selected.lifecycle_state === "active" && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 text-xs text-destructive hover:text-destructive"
                onClick={() => setArchiveTarget(selected)}
              >
                <Archive className="mr-1.5 h-3.5 w-3.5" />
                Archive
              </Button>
            )}
          </div>
        </footer>
      )}

      {selected && (
        <section className="border-t border-border/60">
          <header className="flex flex-wrap items-center gap-2 px-3 py-2">
            <Code2 className="h-4 w-4 text-primary" />
            <div className="min-w-0 flex-1">
              <h5 className="text-xs font-semibold">Candidate manifest</h5>
              <p className="truncate text-[10px] text-muted-foreground">
                Exact validated bundle for {selected.candidate_workflow_name}
              </p>
            </div>
            <Badge variant="outline" className="h-5 text-[9px]">
              {selected.manifest_bundle.length} resources
            </Badge>
            <CopyButton value={manifest} className="h-7 w-7" />
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 px-2 text-[10px]"
              disabled={!manifest || actionLoading === "manifest-download"}
              onClick={onDownload}
            >
              <Download className="h-3.5 w-3.5" />
              YAML
            </Button>
          </header>
          <div className="max-h-[32rem] max-w-full overflow-auto border-t border-border/50 bg-slate-950">
            {manifestLoading ? (
              <div className="flex min-h-40 items-center justify-center text-xs text-slate-400">
                Loading validated manifest…
              </div>
            ) : manifest ? (
              <Highlight theme={KubeSynapseTheme} code={manifest.trimEnd()} language={"yaml" as Language}>
                {({ className, style, tokens, getLineProps, getTokenProps }) => (
                  <pre
                    className={cn(className, "w-max min-w-full p-3 font-mono text-[11px] leading-5")}
                    style={{ ...style, margin: 0, background: "transparent" }}
                  >
                    {tokens.map((line, index) => (
                      <div key={index} {...getLineProps({ line })} className="table-row">
                        <span className="table-cell select-none pr-4 text-right text-slate-600">{index + 1}</span>
                        <span className="table-cell">
                          {line.map((token, tokenIndex) => (
                            <span key={tokenIndex} {...getTokenProps({ token })} />
                          ))}
                        </span>
                      </div>
                    ))}
                  </pre>
                )}
              </Highlight>
            ) : (
              <div className="flex min-h-40 items-center justify-center px-4 text-center text-xs text-slate-400">
                The persisted manifest could not be loaded. Refresh the registry to retry.
              </div>
            )}
          </div>
        </section>
      )}

      <Dialog open={Boolean(archiveTarget)} onOpenChange={(open) => { if (!open) setArchiveTarget(null); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Archive candidate</DialogTitle>
            <DialogDescription>
              Remove {archiveTarget?.candidate_workflow_name} from the active registry. Its manifest, optimizer trace,
              trials, approvals, and audit history remain available under “Show archived.”
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setArchiveTarget(null)}>Cancel</Button>
            <Button
              type="button"
              variant="destructive"
              disabled={actionLoading === `archive:${archiveTarget?.id}`}
              onClick={() => {
                if (archiveTarget) onArchive(archiveTarget);
                setArchiveTarget(null);
              }}
            >
              Archive candidate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
