import { LoaderCircle, PlusCircle, Save, ShieldCheck, Sparkles, Trash2, Workflow } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import type { AgentInfo, WorkflowInfo, WorkflowPayload, WorkflowStep, WorkflowUpdatePayload } from "../types";

interface WorkflowManagerProps {
  workflow: WorkflowInfo | null;
  agents: AgentInfo[];
  isSaving: boolean;
  isDeleting: boolean;
  error: string;
  onCreate: (payload: WorkflowPayload) => void;
  onUpdate: (name: string, payload: WorkflowUpdatePayload) => void;
  onDelete: (name: string) => void;
}

function defaultStepsForAgent(agentName?: string): WorkflowStep[] {
  return [
    {
      name: "step-1",
      agent_ref: agentName ?? "",
      prompt: "",
      depends_on: [],
      require_approval: false,
    },
  ];
}

export function WorkflowManager({
  workflow,
  agents,
  isSaving,
  isDeleting,
  error,
  onCreate,
  onUpdate,
  onDelete,
}: WorkflowManagerProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [input, setInput] = useState("");
  const [messageBus, setMessageBus] = useState("in-memory");
  const [steps, setSteps] = useState<WorkflowStep[]>(() => defaultStepsForAgent(agents[0]?.name));

  useEffect(() => {
    if (workflow) {
      setName(workflow.name);
      setDescription(workflow.description);
      setInput(workflow.input);
      setMessageBus(workflow.message_bus);
      setSteps(workflow.steps.length > 0 ? workflow.steps : defaultStepsForAgent(agents[0]?.name));
      return;
    }
    setName("");
    setDescription("");
    setInput("");
    setMessageBus("in-memory");
    setSteps(defaultStepsForAgent(agents[0]?.name));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow?.name]);

  function updateStep(index: number, updater: (current: WorkflowStep) => WorkflowStep) {
    setSteps((current) => current.map((step, stepIndex) => (stepIndex === index ? updater(step) : step)));
  }

  function renameStep(index: number, nextName: string) {
    setSteps((current) => {
      const previousName = current[index]?.name ?? "";
      return current.map((step, stepIndex) => {
        const renamedStep =
          stepIndex === index
            ? {
                ...step,
                name: nextName,
              }
            : step;

        if (!previousName || previousName === nextName) {
          return renamedStep;
        }

        return {
          ...renamedStep,
          depends_on: renamedStep.depends_on.map((dependency) => (dependency === previousName ? nextName : dependency)),
        };
      });
    });
  }

  function removeStep(index: number) {
    setSteps((current) => {
      const removedName = current[index]?.name ?? "";
      return current
        .filter((_, stepIndex) => stepIndex !== index)
        .map((step) => ({
          ...step,
          depends_on: step.depends_on.filter((dependency) => dependency !== removedName),
        }));
    });
  }

  function toggleDependency(index: number, dependency: string) {
    updateStep(index, (current) => {
      const active = current.depends_on.includes(dependency);
      return {
        ...current,
        depends_on: active
          ? current.depends_on.filter((item) => item !== dependency)
          : [...current.depends_on, dependency],
      };
    });
  }

  const canSubmit = Boolean(name.trim()) && steps.length > 0 && steps.every((step) => step.name.trim() && step.agent_ref.trim());
  const uniqueAgentCount = new Set(steps.map((step) => step.agent_ref).filter(Boolean)).size;
  const approvalStepCount = steps.filter((step) => step.require_approval).length;

  return (
    <Card className="border-border/70 bg-card/95 shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
      <CardHeader className="pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner shadow-primary/10">
            <Workflow className="h-5 w-5" />
          </div>
          <div className="flex-1 space-y-1">
            <CardTitle className="text-lg">{workflow ? workflow.name : "Create workflow"}</CardTitle>
            <CardDescription>
              {workflow
                ? "Refine the orchestration, approvals, and step wiring for this workflow."
                : "Compose a multi-step agent pipeline with clearer sequencing, dependencies, and review gates."}
            </CardDescription>
          </div>
          <Badge variant={workflow?.phase === "running" ? "default" : "secondary"}>
            {workflow?.phase ?? "draft"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Status</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{workflow?.phase ?? "draft"}</p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Steps</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{steps.length}</p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Agents</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{uniqueAgentCount}</p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Approvals</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{approvalStepCount}</p>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <Card className="shadow-none">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Workflow details</CardTitle>
              <CardDescription>Name the flow, describe its purpose, and define the initial instruction payload.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label className="text-xs">Name</Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="research-report-pipeline"
                    disabled={Boolean(workflow)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Description</Label>
                  <Input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Research to report pipeline"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Workflow input</Label>
                <Textarea
                  rows={4}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Describe the task, desired output, and constraints the first step should receive."
                />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-none">
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
                  <Sparkles className="h-4 w-4" />
                </div>
                <div>
                  <CardTitle className="text-sm">Execution profile</CardTitle>
                  <CardDescription>Keep orchestration simple, then add review gates only where the flow truly needs human control.</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-xs">Message bus</Label>
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  value={messageBus}
                  onChange={(e) => setMessageBus(e.target.value)}
                >
                  <option value="in-memory">in-memory</option>
                </select>
                <p className="text-[11px] text-muted-foreground">The current gateway API supports the in-memory workflow bus only.</p>
              </div>
              <Separator />
              <div className="rounded-2xl border border-border/60 bg-background/60 p-3 text-sm text-muted-foreground">
                <p className="font-medium text-foreground">Operator-friendly defaults</p>
                <p className="mt-1 leading-6">Each step is independently targetable, dependencies stay explicit, and approval gates are visible directly on the step card instead of hidden in free-form text.</p>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="flex items-center justify-between border-t border-border pt-4">
          <div>
            <h3 className="text-sm font-medium text-foreground">Workflow steps</h3>
            <p className="text-xs text-muted-foreground">Model the sequence, assign each step to an agent, and toggle dependencies with buttons instead of comma parsing.</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-8 rounded-xl text-xs"
            onClick={() =>
              setSteps((current) => [
                ...current,
                {
                  name: `step-${current.length + 1}`,
                  agent_ref: agents[0]?.name ?? "",
                  prompt: "",
                  depends_on: [],
                  require_approval: false,
                },
              ])
            }
          >
            <PlusCircle className="mr-1 h-3 w-3" />
            Add step
          </Button>
        </div>

        <div className="space-y-3">
          {steps.map((step, index) => (
            <Card key={index} className="shadow-none">
              <CardContent className="space-y-4 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">Step {index + 1}</Badge>
                    {step.require_approval ? (
                      <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-300">
                        <ShieldCheck className="mr-1 h-3 w-3" /> Approval gate
                      </Badge>
                    ) : null}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 rounded-xl text-xs text-destructive hover:text-destructive"
                    disabled={steps.length === 1}
                    onClick={() => removeStep(index)}
                  >
                    <Trash2 className="mr-1 h-3 w-3" />
                    Remove
                  </Button>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label className="text-[11px]">Step name</Label>
                    <Input
                      className="h-9 rounded-xl text-xs"
                      value={step.name}
                      onChange={(e) => renameStep(index, e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[11px]">Agent</Label>
                    <select
                      className="flex h-9 w-full rounded-xl border border-input bg-transparent px-3 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      value={step.agent_ref}
                      onChange={(e) =>
                        updateStep(index, (current) => ({ ...current, agent_ref: e.target.value }))
                      }
                    >
                      <option value="">Select agent</option>
                      {agents.map((agent) => (
                        <option key={agent.name} value={agent.name}>
                          {agent.name} · {agent.model}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label className="text-[11px]">Depends on</Label>
                  <div className="flex flex-wrap gap-2 rounded-2xl border border-border/60 bg-background/50 p-3">
                    {steps
                      .filter((candidate, candidateIndex) => candidateIndex !== index && candidate.name.trim())
                      .map((candidate) => {
                        const active = step.depends_on.includes(candidate.name);
                        return (
                          <button
                            key={candidate.name}
                            type="button"
                            onClick={() => toggleDependency(index, candidate.name)}
                            className={`rounded-full border px-3 py-1 text-xs transition ${
                              active
                                ? "border-primary/40 bg-primary/10 text-foreground"
                                : "border-border/70 bg-background text-muted-foreground hover:border-primary/25 hover:text-foreground"
                            }`}
                          >
                            {candidate.name}
                          </button>
                        );
                      })}
                    {steps.filter((candidate, candidateIndex) => candidateIndex !== index && candidate.name.trim()).length === 0 ? (
                      <p className="text-xs text-muted-foreground">Add another step to create explicit dependencies.</p>
                    ) : null}
                  </div>
                </div>

                <div className="space-y-1">
                  <Label className="text-[11px]">Prompt</Label>
                  <Textarea
                    rows={4}
                    className="text-xs"
                    value={step.prompt}
                    onChange={(e) =>
                      updateStep(index, (current) => ({ ...current, prompt: e.target.value }))
                    }
                    placeholder="Explain what this step should do, what context it receives, and what output it should pass to the next step."
                  />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/60 bg-background/50 p-3">
                  <div>
                    <p className="text-sm font-medium text-foreground">Human approval</p>
                    <p className="text-xs text-muted-foreground">Pause the workflow before this step starts and wait for an approval decision.</p>
                  </div>
                  <Button
                    type="button"
                    variant={step.require_approval ? "default" : "outline"}
                    size="sm"
                    className="rounded-xl"
                    onClick={() =>
                      updateStep(index, (current) => ({
                        ...current,
                        require_approval: !current.require_approval,
                      }))
                    }
                  >
                    {step.require_approval ? "Approval enabled" : "Enable approval"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-border pt-4">
          <Button
            onClick={() => {
              const payload = { description, input, message_bus: messageBus, steps };
              if (workflow) {
                onUpdate(workflow.name, payload as WorkflowUpdatePayload);
                return;
              }
              onCreate({ name, ...payload });
            }}
            disabled={!canSubmit || isSaving}
          >
            {isSaving ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
            {isSaving ? "Saving..." : workflow ? "Save workflow" : "Create workflow"}
          </Button>
          {workflow && (
            <Button
              variant="destructive"
              onClick={() => onDelete(workflow.name)}
              disabled={isDeleting}
            >
              {isDeleting ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1.5 h-4 w-4" />}
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
