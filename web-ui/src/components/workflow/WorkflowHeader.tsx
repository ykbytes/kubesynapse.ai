import {
  Blocks,
  LoaderCircle,
  Play,
  Save,
  Square,
  Trash2,
  Workflow,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { factoryModeLabel } from "@/lib/factoryModes";
import { useManifestViewer } from "@/hooks/useManifestViewer";
import type { FactoryMode } from "../../types";

interface WorkflowHeaderProps {
  workflowName: string | null;
  phase: string;
  isActive: boolean;
  isFactoryWorkflow: boolean;
  factoryMode: FactoryMode;
  isRunning: boolean;
  isCancelling?: boolean;
  isSaving: boolean;
  canSubmit: boolean;
  canMutate: boolean;
  namespace?: string;
  token?: string;
  onRun: () => void;
  onCancel: () => void;
  onSave: () => void;
  onDelete: () => void;
  onOpenComposer?: () => void;
}

export function WorkflowHeader({
  workflowName,
  phase,
  isActive,
  isFactoryWorkflow,
  factoryMode,
  isRunning,
  isCancelling,
  isSaving,
  canSubmit,
  canMutate,
  namespace = "default",
  token = "",
  onRun,
  onCancel,
  onSave,
  onDelete,
  onOpenComposer,
}: WorkflowHeaderProps) {
  const {
    ManifestButton,
    ManifestModalComponent,
  } = useManifestViewer({
    resourceType: "workflow",
    resourceName: workflowName || "",
    namespace,
    token,
  });

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary shadow-sm">
            <Workflow className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h1 className="text-base font-semibold leading-tight text-foreground">
              {workflowName ?? "Create workflow"}
            </h1>
            <div className="mt-1 flex items-center gap-2">
              <Badge
                variant={
                  isActive
                    ? "default"
                    : phase === "failed" || phase === "cancelled"
                      ? "destructive"
                      : "secondary"
                }
                className="text-xs capitalize"
              >
                {phase}
              </Badge>
              {isFactoryWorkflow && (
                <Badge
                  variant="outline"
                  className="text-xs border-primary/20 bg-primary/5 text-primary/80"
                >
                  {factoryModeLabel(factoryMode)}
                </Badge>
              )}
            </div>
          </div>
        </div>

      <div className="flex flex-wrap items-center gap-2">
        {workflowName && (
          <Button
            variant="outline"
            size="sm"
            className="h-9 rounded-lg text-xs"
            onClick={onRun}
            disabled={isRunning || isActive}
          >
            {isRunning ? (
              <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="mr-1.5 h-3.5 w-3.5" />
            )}
            {isRunning ? "Running…" : "Run"}
          </Button>
        )}

        {isActive && (
          <Button
            variant="destructive"
            size="sm"
            className="h-9 rounded-lg text-xs"
            onClick={onCancel}
            disabled={isCancelling}
          >
            {isCancelling ? (
              <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Square className="mr-1.5 h-3.5 w-3.5" />
            )}
            {isCancelling ? "Cancelling…" : "Cancel"}
          </Button>
        )}

        {canMutate && (
          <Button
            size="sm"
            className="h-9 rounded-lg text-xs"
            onClick={onSave}
            disabled={!canSubmit || isSaving}
          >
            {isSaving ? (
              <LoaderCircle className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="mr-1.5 h-3.5 w-3.5" />
            )}
            {isSaving ? "Saving…" : workflowName ? "Save" : "Create"}
          </Button>
        )}

        {onOpenComposer && workflowName && (
          <Button
            variant="outline"
            size="sm"
            className="h-9 rounded-lg text-xs"
            onClick={onOpenComposer}
          >
            <Blocks className="mr-1.5 h-3.5 w-3.5" />
            Composer
          </Button>
        )}

        {workflowName && (
          <ManifestButton />
        )}

        {workflowName && canMutate && (
          <Button
            variant="ghost"
            size="sm"
            className="h-9 rounded-lg text-xs text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={onDelete}
          >
            <Trash2 className="mr-1.5 h-3.5 w-3.5" />
            Delete
          </Button>
        )}
      </div>
    </div>
      <ManifestModalComponent />
    </>
  );
}
