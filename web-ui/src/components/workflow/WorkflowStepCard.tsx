import { Repeat, ShieldCheck, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ExpandableMarkdownEditor } from "../shared/ExpandableMarkdownEditor";
import type { AgentInfo, WorkflowStep } from "../../types";

interface WorkflowStepCardProps {
  step: WorkflowStep;
  index: number;
  agents: AgentInfo[];
  allSteps: WorkflowStep[];
  canRemove: boolean;
  onRename: (index: number, name: string) => void;
  onUpdate: (index: number, updater: (current: WorkflowStep) => WorkflowStep) => void;
  onRemove: (index: number) => void;
  onToggleDependency: (index: number, dependency: string) => void;
}

export function WorkflowStepCard({
  step,
  index,
  agents,
  allSteps,
  canRemove,
  onRename,
  onUpdate,
  onRemove,
  onToggleDependency,
}: WorkflowStepCardProps) {
  const otherSteps = allSteps.filter(
    (s, i) => i !== index && s.name.trim()
  );

  return (
    <div className="rounded-2xl border border-border/70 bg-card/55 p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-xs">
            Step {index + 1}
          </Badge>
          {step.require_approval && (
            <Badge
              variant="outline"
              className="border-amber-500/30 bg-amber-500/10 text-amber-300 text-xs"
            >
              <ShieldCheck className="mr-1 h-3 w-3" />
              Approval gate
            </Badge>
          )}
          {step.step_type === "loop" && (
            <Badge
              variant="outline"
              className="border-violet-500/30 bg-violet-500/10 text-violet-300 text-xs"
            >
              <Repeat className="mr-1 h-3 w-3" />
              Loop
            </Badge>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 rounded-lg text-xs text-destructive hover:text-destructive hover:bg-destructive/10"
          disabled={!canRemove}
          onClick={() => onRemove(index)}
        >
          <Trash2 className="mr-1.5 h-3.5 w-3.5" />
          Remove
        </Button>
      </div>

      {/* Name + Type */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label className="text-sm font-medium">Step name</Label>
          <Input
            className="h-10 rounded-xl text-sm"
            value={step.name}
            onChange={(e) => onRename(index, e.target.value)}
            placeholder="analyze-requirements"
          />
        </div>
        <div className="space-y-2">
          <Label className="text-sm font-medium">Step type</Label>
          <Select
            value={step.step_type ?? "agent"}
            onValueChange={(v) =>
              onUpdate(index, (current) => ({
                ...current,
                step_type: v as "agent" | "loop" | "review",
                loop_config:
                  v === "loop" && !current.loop_config
                    ? {
                        maxIterations: 20,
                        planSource: "inline",
                        plan: "",
                        commitAfterEachItem: true,
                        circuitBreaker: {
                          noProgressThreshold: 3,
                          cooldownMinutes: 2,
                        },
                      }
                    : v === "loop"
                      ? current.loop_config
                      : null,
              }))
            }
          >
            <SelectTrigger className="h-10 rounded-xl text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="agent">Agent (single run)</SelectItem>
              <SelectItem value="loop">Dev-loop (iterative)</SelectItem>
              <SelectItem value="review">Review</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Agent */}
      <div className="space-y-2">
        <Label className="text-sm font-medium">Agent</Label>
        <Select
          value={step.agent_ref || "__none__"}
          onValueChange={(v) =>
            onUpdate(index, (current) => ({
              ...current,
              agent_ref: v === "__none__" ? "" : v,
            }))
          }
        >
          <SelectTrigger className="h-10 rounded-xl text-sm">
            <SelectValue placeholder="Select agent" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">Select agent</SelectItem>
            {agents.map((agent) => (
              <SelectItem key={agent.name} value={agent.name}>
                {agent.name} · {agent.model}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Dependencies */}
      <div className="space-y-2">
        <Label className="text-sm font-medium">Depends on</Label>
        <div className="flex flex-wrap gap-2 rounded-xl border border-border/60 bg-background/50 p-3">
          {otherSteps.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Add another step to create explicit dependencies.
            </p>
          ) : (
            otherSteps.map((candidate) => {
              const active = step.depends_on.includes(candidate.name);
              return (
                <button
                  key={candidate.name}
                  type="button"
                  onClick={() => onToggleDependency(index, candidate.name)}
                  className={`rounded-full border px-3 py-1 text-xs transition ${
                    active
                      ? "border-primary/40 bg-primary/10 text-foreground"
                      : "border-border/70 bg-background text-muted-foreground hover:border-primary/25 hover:text-foreground"
                  }`}
                >
                  {candidate.name}
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* Prompt */}
      <ExpandableMarkdownEditor
        value={step.prompt}
        onChange={(v) => onUpdate(index, (current) => ({ ...current, prompt: v }))}
        label="Prompt"
        rows={4}
        placeholder="Explain what this step should do, what context it receives, and what output it should pass to the next step."
        dialogTitle={`Step Prompt — ${step.name || `Step ${index + 1}`}`}
        dialogDescription="Write the instruction for this workflow step. Supports Markdown formatting."
      />

      {/* Verification / Review criteria */}
      {step.step_type !== "review" ? (
        <div className="space-y-2">
          <Label className="text-sm font-medium">Verification criteria</Label>
          <Textarea
            rows={3}
            className="text-sm"
            value={step.verify ?? ""}
            onChange={(e) =>
              onUpdate(index, (current) => ({
                ...current,
                verify: e.target.value || null,
              }))
            }
            placeholder="Optional verification prompt to run after the step completes."
          />
        </div>
      ) : (
        <div className="space-y-2">
          <Label className="text-sm font-medium">Review criteria</Label>
          <Textarea
            rows={3}
            className="text-sm"
            value={step.review_criteria ?? ""}
            onChange={(e) =>
              onUpdate(index, (current) => ({
                ...current,
                review_criteria: e.target.value || null,
              }))
            }
            placeholder="What should this review step evaluate in the previous output?"
          />
        </div>
      )}

      {/* Loop config */}
      {step.step_type === "loop" && (
        <div className="space-y-4 rounded-2xl border border-violet-500/20 bg-violet-500/5 p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-violet-300">
            <Repeat className="h-4 w-4" />
            Loop configuration
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-2">
              <Label className="text-xs">Max iterations</Label>
              <Input
                type="number"
                min={1}
                max={200}
                className="h-9 rounded-xl text-xs"
                value={step.loop_config?.maxIterations ?? 20}
                onChange={(e) =>
                  onUpdate(index, (current) => ({
                    ...current,
                    loop_config: {
                      ...current.loop_config,
                      maxIterations: parseInt(e.target.value) || 20,
                    },
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label className="text-xs">Plan source</Label>
              <Select
                value={step.loop_config?.planSource ?? "inline"}
                onValueChange={(v) =>
                  onUpdate(index, (current) => ({
                    ...current,
                    loop_config: {
                      ...current.loop_config,
                      planSource: v as "inline" | "prompt",
                    },
                  }))
                }
              >
                <SelectTrigger className="h-9 rounded-xl text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="inline">Inline checklist</SelectItem>
                  <SelectItem value="prompt">Agent generates plan</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="text-xs">No-progress threshold</Label>
              <Input
                type="number"
                min={1}
                max={10}
                className="h-9 rounded-xl text-xs"
                value={step.loop_config?.circuitBreaker?.noProgressThreshold ?? 3}
                onChange={(e) =>
                  onUpdate(index, (current) => ({
                    ...current,
                    loop_config: {
                      ...current.loop_config,
                      circuitBreaker: {
                        ...current.loop_config?.circuitBreaker,
                        noProgressThreshold: parseInt(e.target.value) || 3,
                      },
                    },
                  }))
                }
              />
            </div>
          </div>
          {(step.loop_config?.planSource ?? "inline") === "inline" && (
            <div className="space-y-2">
              <Label className="text-xs">Plan checklist</Label>
              <Textarea
                rows={6}
                className="font-mono text-xs"
                value={step.loop_config?.plan ?? ""}
                onChange={(e) =>
                  onUpdate(index, (current) => ({
                    ...current,
                    loop_config: {
                      ...current.loop_config,
                      plan: e.target.value,
                    },
                  }))
                }
                placeholder={"- [ ] Implement user authentication\n- [ ] Add unit tests for auth module\n- [ ] Update API documentation"}
              />
            </div>
          )}
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id={`commit-after-${index}`}
              checked={step.loop_config?.commitAfterEachItem ?? true}
              onChange={(e) =>
                onUpdate(index, (current) => ({
                  ...current,
                  loop_config: {
                    ...current.loop_config,
                    commitAfterEachItem: e.target.checked,
                  },
                }))
              }
              className="h-4 w-4 rounded border-border"
            />
            <Label htmlFor={`commit-after-${index}`} className="text-xs">
              Commit after each item
            </Label>
          </div>
        </div>
      )}

      {/* Approval toggle */}
      <div className="flex items-center justify-between gap-4 rounded-xl border border-border/60 bg-background/50 px-4 py-3">
        <div>
          <p className="text-sm font-medium text-foreground">Human approval</p>
          <p className="text-xs text-muted-foreground">
            Pause before this step and wait for operator approval.
          </p>
        </div>
        <Button
          type="button"
          variant={step.require_approval ? "default" : "outline"}
          size="sm"
          className={`h-8 rounded-full px-4 text-xs ${
            step.require_approval
              ? "bg-amber-600 hover:bg-amber-500"
              : ""
          }`}
          onClick={() =>
            onUpdate(index, (current) => ({
              ...current,
              require_approval: !current.require_approval,
            }))
          }
        >
          {step.require_approval ? (
            <>
              <ShieldCheck className="mr-1.5 h-3.5 w-3.5" />
              Enabled
            </>
          ) : (
            "Enable"
          )}
        </Button>
      </div>
    </div>
  );
}
