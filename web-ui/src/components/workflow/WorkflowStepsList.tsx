import { PlusCircle, Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WorkflowStepCard } from "./WorkflowStepCard";
import type { AgentInfo, WorkflowStep } from "../../types";

interface WorkflowStepsListProps {
  steps: WorkflowStep[];
  agents: AgentInfo[];
  onAddStep: () => void;
  onRenameStep: (index: number, name: string) => void;
  onUpdateStep: (index: number, updater: (current: WorkflowStep) => WorkflowStep) => void;
  onRemoveStep: (index: number) => void;
  onToggleDependency: (index: number, dependency: string) => void;
}

export function WorkflowStepsList({
  steps,
  agents,
  onAddStep,
  onRenameStep,
  onUpdateStep,
  onRemoveStep,
  onToggleDependency,
}: WorkflowStepsListProps) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-border/60 bg-card/40">
            <Workflow className="h-4 w-4 text-muted-foreground" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-foreground">Steps</h2>
            <p className="text-xs text-muted-foreground">
              {steps.length} step{steps.length === 1 ? "" : "s"} · model the sequence, assign agents, and set dependencies
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-9 rounded-xl text-xs"
          onClick={onAddStep}
        >
          <PlusCircle className="mr-1.5 h-4 w-4" />
          Add step
        </Button>
      </div>

      <div className="space-y-4">
        {steps.map((step, index) => (
          <WorkflowStepCard
            key={`${step.name}-${index}`}
            step={step}
            index={index}
            agents={agents}
            allSteps={steps}
            canRemove={steps.length > 1}
            onRename={onRenameStep}
            onUpdate={onUpdateStep}
            onRemove={onRemoveStep}
            onToggleDependency={onToggleDependency}
          />
        ))}
      </div>
    </section>
  );
}
