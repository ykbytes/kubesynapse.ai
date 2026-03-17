import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Save, Play, ArrowLeft, LayoutGrid, Circle } from "lucide-react";

interface ComposerToolbarProps {
  workflowName: string;
  description: string;
  input: string;
  isNew: boolean;
  isDirty: boolean;
  isSaving: boolean;
  isRunning: boolean;
  onNameChange: (name: string) => void;
  onDescriptionChange: (desc: string) => void;
  onInputChange: (input: string) => void;
  onSave: () => void;
  onRun: () => void;
  onAutoLayout: () => void;
  onBack: () => void;
}

export function ComposerToolbar({
  workflowName,
  description,
  input,
  isNew,
  isDirty,
  isSaving,
  isRunning,
  onNameChange,
  onDescriptionChange,
  onInputChange,
  onSave,
  onRun,
  onAutoLayout,
  onBack,
}: ComposerToolbarProps) {
  return (
    <div className="flex items-center gap-2 border-b px-3 py-2 bg-background shrink-0 flex-wrap">
      <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onBack} title="Back to workflows">
        <ArrowLeft className="h-4 w-4" />
      </Button>

      <Input
        value={workflowName}
        onChange={(e) => onNameChange(e.target.value)}
        placeholder="Workflow name"
        className="h-7 text-xs w-40"
        disabled={!isNew}
      />

      <Input
        value={description}
        onChange={(e) => onDescriptionChange(e.target.value)}
        placeholder="Description"
        className="h-7 text-xs w-48"
      />

      <Input
        value={input}
        onChange={(e) => onInputChange(e.target.value)}
        placeholder="Input / prompt"
        className="h-7 text-xs flex-1 min-w-[120px]"
      />

      {isDirty && (
        <span className="flex items-center gap-1 text-[10px] text-amber-500 shrink-0" title="Unsaved changes">
          <Circle className="h-2 w-2 fill-current" /> Unsaved
        </span>
      )}

      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs gap-1 shrink-0"
        onClick={onAutoLayout}
        title="Auto-arrange all nodes"
      >
        <LayoutGrid className="h-3 w-3" /> Auto-layout
      </Button>

      <Button
        variant="default"
        size="sm"
        className="h-7 text-xs gap-1 shrink-0"
        onClick={onSave}
        disabled={isSaving || !workflowName.trim()}
        title={!workflowName.trim() ? "Enter a workflow name first" : "Save workflow"}
      >
        <Save className="h-3 w-3" /> {isSaving ? "Saving…" : "Save"}
      </Button>

      <Button
        variant="secondary"
        size="sm"
        className="h-7 text-xs gap-1 shrink-0"
        onClick={onRun}
        disabled={isRunning || !workflowName.trim() || isNew || isDirty}
        title={isNew ? "Save the workflow first" : isDirty ? "Save changes before running" : "Trigger workflow run"}
      >
        <Play className="h-3 w-3" /> {isRunning ? "Running…" : "Run"}
      </Button>
    </div>
  );
}
