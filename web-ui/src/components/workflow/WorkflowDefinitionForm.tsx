import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ExpandableMarkdownEditor } from "../shared/ExpandableMarkdownEditor";
import { PremiumCard } from "../shared/PremiumCard";
import { FileText, Settings, Zap } from "lucide-react";

interface WorkflowDefinitionFormProps {
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  input: string;
  setInput: (v: string) => void;
  contextRef: string;
  setContextRef: (v: string) => void;
  isEditing: boolean;
}

export function WorkflowDefinitionForm({
  name,
  setName,
  description,
  setDescription,
  input,
  setInput,
  contextRef,
  setContextRef,
  isEditing,
}: WorkflowDefinitionFormProps) {
  return (
    <div className="space-y-5">
      {/* Identity Section */}
      <PremiumCard variant="subtle">
        <div className="space-y-4 p-4">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" />
            <div>
              <h3 className="text-sm font-semibold leading-tight text-foreground">Identity</h3>
              <p className="text-xs text-muted-foreground">Workflow name and purpose</p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="wf-name" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Name
              </Label>
              <Input
                id="wf-name"
                className="h-9 text-sm transition-colors placeholder:text-muted-foreground/50"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="research-report-pipeline"
                disabled={isEditing}
              />
              {!isEditing && (
                <p className="text-xs text-muted-foreground">
                  The workflow name cannot be changed after creation.
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="wf-description" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Description
              </Label>
              <Input
                id="wf-description"
                className="h-9 text-sm transition-colors placeholder:text-muted-foreground/50"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Research to report pipeline"
              />
            </div>
          </div>
        </div>
      </PremiumCard>

      {/* Input Section */}
      <PremiumCard variant="subtle">
        <div className="space-y-3 p-4">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-amber-500" />
            <div>
              <h3 className="text-sm font-semibold leading-tight text-foreground">Workflow Input</h3>
              <p className="text-xs text-muted-foreground">Starting prompt or context</p>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            The starting prompt or context passed to the first step. Available in prompts as{" "}
            <code className="rounded bg-primary/20 px-1.5 py-0.5 font-mono text-xs text-primary">
              {"{{input}}"}
            </code>
          </p>
          <ExpandableMarkdownEditor
            value={input}
            onChange={setInput}
            rows={4}
            placeholder="Describe the task, desired output, and constraints the first step should receive."
            dialogTitle="Workflow Input"
            dialogDescription="This value is available in step prompts as {{input}}. Supports full Markdown."
          />
        </div>
      </PremiumCard>

      {/* Configuration Section */}
      <PremiumCard variant="subtle">
        <div className="space-y-4 p-4">
          <div className="flex items-center gap-2">
            <Settings className="h-4 w-4 text-sky-500" />
            <div>
              <h3 className="text-sm font-semibold leading-tight text-foreground">Configuration</h3>
              <p className="text-xs text-muted-foreground">Infrastructure settings</p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="wf-context" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Context ConfigMap
              </Label>
              <Input
                id="wf-context"
                className="h-9 text-sm transition-colors placeholder:text-muted-foreground/50"
                value={contextRef}
                onChange={(e) => setContextRef(e.target.value)}
                placeholder="project-rules"
              />
              <p className="text-xs text-muted-foreground">Optional ConfigMap reference for shared context.</p>
            </div>
          </div>
        </div>
      </PremiumCard>
    </div>
  );
}
