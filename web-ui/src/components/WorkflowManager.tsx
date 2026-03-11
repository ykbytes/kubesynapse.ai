import { PlusCircle, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

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

function defaultSteps(): WorkflowStep[] {
  return [
    {
      name: "step-1",
      agent_ref: "",
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
  const [steps, setSteps] = useState<WorkflowStep[]>(defaultSteps());

  useEffect(() => {
    if (workflow) {
      setName(workflow.name);
      setDescription(workflow.description);
      setInput(workflow.input);
      setMessageBus(workflow.message_bus);
      setSteps(workflow.steps.length > 0 ? workflow.steps : defaultSteps());
      return;
    }

    setName("");
    setDescription("");
    setInput("");
    setMessageBus("in-memory");
    setSteps(defaultSteps());
  }, [workflow]);

  function updateStep(index: number, updater: (current: WorkflowStep) => WorkflowStep) {
    setSteps((current) => current.map((step, stepIndex) => (stepIndex === index ? updater(step) : step)));
  }

  const canSubmit = Boolean(name.trim()) && steps.length > 0 && steps.every((step) => step.name.trim() && step.agent_ref.trim());

  return (
    <section className="panel panel-setup">
      <div className="panel-header panel-header-chat">
        <div>
          <p className="eyebrow">Workflow Builder</p>
          <h2>{workflow ? workflow.name : "Create workflow"}</h2>
        </div>
        <span className={`mode-pill ${workflow?.phase === "running" ? "live" : "sync"}`}>{workflow?.phase ?? "draft"}</span>
      </div>

      <div className="resource-grid">
        <div className="setup-form">
          <label>
            <span>Name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="research-report-pipeline" disabled={Boolean(workflow)} />
          </label>
          <label>
            <span>Description</span>
            <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Research to report pipeline" />
          </label>
          <label>
            <span>Workflow input</span>
            <textarea className="prompt-input compact-input" rows={4} value={input} onChange={(event) => setInput(event.target.value)} />
          </label>
          <label>
            <span>Message bus</span>
            <select value={messageBus} onChange={(event) => setMessageBus(event.target.value)}>
              <option value="in-memory">in-memory</option>
              <option value="nats">nats</option>
              <option value="redis">redis</option>
            </select>
          </label>
        </div>

        <div className="setup-form">
          <div className="resource-section-header">
            <span>Steps</span>
            <button
              className="secondary-button"
              type="button"
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
              <PlusCircle size={16} />
              <span>Add step</span>
            </button>
          </div>

          <div className="subresource-stack">
            {steps.map((step, index) => (
              <article key={`${step.name}-${index}`} className="subresource-card">
                <div className="resource-section-header">
                  <strong>Step {index + 1}</strong>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => setSteps((current) => current.filter((_, stepIndex) => stepIndex !== index))}
                    disabled={steps.length === 1}
                  >
                    <Trash2 size={14} />
                    <span>Remove</span>
                  </button>
                </div>
                <label>
                  <span>Name</span>
                  <input value={step.name} onChange={(event) => updateStep(index, (current) => ({ ...current, name: event.target.value }))} />
                </label>
                <label>
                  <span>Agent</span>
                  <select
                    value={step.agent_ref}
                    onChange={(event) => updateStep(index, (current) => ({ ...current, agent_ref: event.target.value }))}
                  >
                    <option value="">Select agent</option>
                    {agents.map((agent) => (
                      <option key={agent.name} value={agent.name}>
                        {agent.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Depends on</span>
                  <input
                    value={step.depends_on.join(", ")}
                    onChange={(event) =>
                      updateStep(index, (current) => ({
                        ...current,
                        depends_on: event.target.value
                          .split(",")
                          .map((item) => item.trim())
                          .filter(Boolean),
                      }))
                    }
                    placeholder="research, analysis"
                  />
                </label>
                <label>
                  <span>Prompt</span>
                  <textarea
                    className="prompt-input compact-input"
                    rows={4}
                    value={step.prompt}
                    onChange={(event) => updateStep(index, (current) => ({ ...current, prompt: event.target.value }))}
                  />
                </label>
                <label className="toggle-chip align-start">
                  <input
                    checked={step.require_approval}
                    type="checkbox"
                    onChange={(event) => updateStep(index, (current) => ({ ...current, require_approval: event.target.checked }))}
                  />
                  <span>Require approval before this step runs</span>
                </label>
              </article>
            ))}
          </div>

          {error ? <p className="error-banner">{error}</p> : null}
          <div className="approval-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => {
                const payload = {
                  description,
                  input,
                  message_bus: messageBus,
                  steps,
                };
                if (workflow) {
                  onUpdate(workflow.name, payload as WorkflowUpdatePayload);
                  return;
                }
                onCreate({ name, ...payload });
              }}
              disabled={!canSubmit || isSaving}
            >
              <Save size={16} />
              <span>{isSaving ? "Saving" : workflow ? "Save workflow" : "Create workflow"}</span>
            </button>
            {workflow ? (
              <button className="secondary-button danger-button" type="button" onClick={() => onDelete(workflow.name)} disabled={isDeleting}>
                <Trash2 size={16} />
                <span>{isDeleting ? "Deleting" : "Delete workflow"}</span>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
