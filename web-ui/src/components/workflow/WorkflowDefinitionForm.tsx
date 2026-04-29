import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ExpandableMarkdownEditor } from "../ExpandableMarkdownEditor";

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
    <div className="space-y-6">
      {/* Identity */}
      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Identity</h3>
          <p className="text-xs text-muted-foreground">Name and describe what this workflow does.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="wf-name" className="text-sm font-medium">
              Name
            </Label>
            <Input
              id="wf-name"
              className="h-10 text-sm"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="research-report-pipeline"
              disabled={isEditing}
            />
            {!isEditing && (
              <p className="text-xs text-muted-foreground">The workflow name cannot be changed after creation.</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="wf-description" className="text-sm font-medium">
              Description
            </Label>
            <Input
              id="wf-description"
              className="h-10 text-sm"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Research to report pipeline"
            />
          </div>
        </div>
      </section>

      {/* Input */}
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Workflow input</h3>
          <p className="text-xs text-muted-foreground">
            The starting prompt or context passed to the first step. Available in prompts as{" "}
            <code className="rounded bg-primary/10 px-1 py-0.5 text-xs font-mono text-primary">{"{{input}}"}</code>.
          </p>
        </div>
        <ExpandableMarkdownEditor
          value={input}
          onChange={setInput}
          rows={4}
          placeholder="Describe the task, desired output, and constraints the first step should receive."
          dialogTitle="Workflow Input"
          dialogDescription="This value is available in step prompts as {{input}}. Supports full Markdown."
        />
      </section>

      {/* Configuration */}
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Configuration</h3>
          <p className="text-xs text-muted-foreground">Optional context and infrastructure settings.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="wf-context" className="text-sm font-medium">
              Context ConfigMap
            </Label>
            <Input
              id="wf-context"
              className="h-10 text-sm"
              value={contextRef}
              onChange={(e) => setContextRef(e.target.value)}
              placeholder="project-rules"
            />
            <p className="text-xs text-muted-foreground">Optional ConfigMap reference for shared context.</p>
          </div>
        </div>
      </section>
    </div>
  );
}
