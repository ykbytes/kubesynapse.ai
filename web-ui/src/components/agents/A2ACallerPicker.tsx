import { useCallback, useMemo, useRef, useState } from "react";
import { Bot, ChevronDown, Plus, Search, Sparkles, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { AgentInfo, WorkflowInfo } from "@/types";

interface A2ACallerPickerProps {
  /** Current newline-separated caller text (namespace/name per line) */
  value: string;
  onChange: (value: string) => void;
  /** All agents in the workspace */
  agents: AgentInfo[];
  /** All workflows in the workspace (for auto-detect) */
  workflows: WorkflowInfo[];
  /** The name of the agent being edited (excluded from suggestions) */
  currentAgentName?: string;
  /** Placeholder for the textarea fallback */
  placeholder?: string;
}

/** Parse the text value into a Set of "namespace/name" strings */
function parseCallerLines(text: string): Set<string> {
  return new Set(
    text
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean),
  );
}

/** Serialize a Set back to newline-separated string */
function serializeCallers(callers: Set<string>): string {
  return Array.from(callers).join("\n");
}

export function A2ACallerPicker({
  value,
  onChange,
  agents,
  workflows,
  currentAgentName,
  placeholder,
}: A2ACallerPickerProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [showTextarea, setShowTextarea] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const currentCallers = useMemo(() => parseCallerLines(value), [value]);

  // Agents available to add (not already added, not self)
  const availableAgents = useMemo(() => {
    const q = search.toLowerCase().trim();
    return agents
      .filter((a) => {
        // Exclude self
        if (currentAgentName && a.name === currentAgentName) return false;
        // Exclude already-added
        const ref = `${a.namespace}/${a.name}`;
        if (currentCallers.has(ref)) return false;
        // Search filter
        if (q && !a.name.toLowerCase().includes(q) && !a.namespace.toLowerCase().includes(q)) return false;
        return true;
      });
  }, [agents, currentAgentName, currentCallers, search]);

  const addCaller = useCallback(
    (ref: string) => {
      const next = new Set(currentCallers);
      next.add(ref);
      onChange(serializeCallers(next));
    },
    [currentCallers, onChange],
  );

  const removeCaller = useCallback(
    (ref: string) => {
      const next = new Set(currentCallers);
      next.delete(ref);
      onChange(serializeCallers(next));
    },
    [currentCallers, onChange],
  );

  // Auto-detect: scan all workflows for steps that reference currentAgentName
  // and add those workflows' other agents as allowed callers
  const autoDetectCallers = useCallback(() => {
    if (!currentAgentName) return;
    const next = new Set(currentCallers);
    let added = 0;

    for (const wf of workflows) {
      // Check if this agent is used in the workflow
      const agentUsed = wf.steps.some((s) => s.agent_ref === currentAgentName);
      if (!agentUsed) continue;

      // Add all other agents in this workflow as callers
      for (const step of wf.steps) {
        if (step.agent_ref && step.agent_ref !== currentAgentName) {
          const agent = agents.find((a) => a.name === step.agent_ref);
          const ref = agent
            ? `${agent.namespace}/${agent.name}`
            : `${wf.namespace}/${step.agent_ref}`;
          if (!next.has(ref)) {
            next.add(ref);
            added++;
          }
        }
      }
    }

    // Also add agents that are peers (other agents in the same namespace)
    // if they have this agent listed in their workflows
    if (added > 0 || next.size !== currentCallers.size) {
      onChange(serializeCallers(next));
    }
    return added;
  }, [currentAgentName, currentCallers, workflows, agents, onChange]);

  const callerArray = useMemo(() => Array.from(currentCallers), [currentCallers]);

  return (
    <div className="space-y-2">
      {/* Caller chips */}
      {callerArray.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {callerArray.map((ref) => {
            const [ns, name] = ref.split("/");
            const agentMatch = agents.find((a) => a.name === name && a.namespace === ns);
            return (
              <Badge
                key={ref}
                variant="outline"
                className={cn(
                  "gap-1 pl-1.5 pr-1 py-0.5 text-[11px] font-mono transition-colors",
                  agentMatch
                    ? "border-primary/30 bg-primary/5 text-primary hover:bg-primary/10"
                    : "border-border bg-card text-muted-foreground hover:bg-accent",
                )}
              >
                {agentMatch && (
                  <Bot className="h-3 w-3 shrink-0 opacity-60" />
                )}
                <span className="text-muted-foreground/70">{ns}/</span>
                <span>{name}</span>
                <button
                  type="button"
                  onClick={() => removeCaller(ref)}
                  className="ml-0.5 rounded-sm p-0.5 hover:bg-destructive/20 hover:text-destructive transition-colors cursor-pointer"
                  aria-label={`Remove ${ref}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            );
          })}
        </div>
      )}

      {/* Action row */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Add from agents popover */}
        <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs gap-1.5 cursor-pointer"
            >
              <Plus className="h-3 w-3" />
              Add agent
              <ChevronDown className="h-3 w-3 opacity-50" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-64 p-0" align="start">
            <div className="p-2 border-b">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground/60" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search agents…"
                  className="h-7 text-xs pl-7"
                  autoFocus
                />
              </div>
            </div>
            <ScrollArea className="max-h-48">
              <div className="p-1">
                {availableAgents.length === 0 ? (
                  <div className="px-3 py-4 text-center">
                    <Bot className="h-5 w-5 text-muted-foreground/30 mx-auto mb-1" />
                    <p className="text-[11px] text-muted-foreground">
                      {agents.length === 0 ? "No agents in workspace" : "All agents already added"}
                    </p>
                  </div>
                ) : (
                  availableAgents.map((agent) => {
                    const ref = `${agent.namespace}/${agent.name}`;
                    const statusColor =
                      agent.status === "Running" || agent.status === "running"
                        ? "bg-emerald-500"
                        : agent.status === "Failed" || agent.status === "failed"
                          ? "bg-red-500"
                          : "bg-muted-foreground/40";
                    return (
                      <button
                        key={ref}
                        type="button"
                        className="flex items-center gap-2 w-full rounded-md px-2 py-1.5 text-xs hover:bg-accent transition-colors cursor-pointer text-left"
                        onClick={() => {
                          addCaller(ref);
                          setSearch("");
                        }}
                      >
                        <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", statusColor)} />
                        <div className="min-w-0 flex-1">
                          <div className="font-medium truncate">{agent.name}</div>
                          <div className="text-[10px] text-muted-foreground/60 font-mono">
                            {agent.namespace} · {agent.runtime_kind ?? "unknown"}
                          </div>
                        </div>
                        <Plus className="h-3 w-3 text-muted-foreground/40 shrink-0" />
                      </button>
                    );
                  })
                )}
              </div>
            </ScrollArea>
          </PopoverContent>
        </Popover>

        {/* Auto-detect from workflows */}
        {currentAgentName && workflows.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1.5 cursor-pointer text-muted-foreground hover:text-foreground"
            onClick={() => {
              const added = autoDetectCallers();
              // Visual feedback handled by chip list updating
              if (added === 0) {
                // No new callers found — could show a toast, but let's keep it simple
              }
            }}
            title="Scan workflows using this agent and auto-add co-participating agents as allowed callers"
          >
            <Sparkles className="h-3 w-3" />
            Auto-detect from workflows
          </Button>
        )}

        {/* Toggle textarea for manual entry */}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 text-xs gap-1 cursor-pointer text-muted-foreground hover:text-foreground ml-auto"
          onClick={() => {
            setShowTextarea((v) => !v);
            if (!showTextarea) {
              setTimeout(() => textareaRef.current?.focus(), 50);
            }
          }}
        >
          {showTextarea ? "Hide editor" : "Edit as text"}
        </Button>
      </div>

      {/* Manual textarea (collapsible) */}
      {showTextarea && (
        <textarea
          ref={textareaRef}
          rows={4}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cn(
            "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs",
            "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            "disabled:cursor-not-allowed disabled:opacity-50",
            "font-mono text-xs resize-none",
          )}
        />
      )}

      {/* Empty state hint */}
      {callerArray.length === 0 && !showTextarea && (
        <p className="text-[11px] text-muted-foreground/60 italic">
          No allowed callers configured. Add agents that should be able to invoke this agent via A2A.
        </p>
      )}
    </div>
  );
}
