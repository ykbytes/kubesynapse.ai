import { Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { A2A_ALLOWED_CALLERS_PLACEHOLDER, stringifyA2APeerRefs } from "../lib/a2a";
import { GOOSE_CONFIG_FILES_PLACEHOLDER, stringifyGooseConfigFiles } from "../lib/gooseConfig";
import type { AgentDetail, PolicyInfo, RuntimeKind, UpdateAgentPayload } from "../types";

interface AgentManagementPanelProps {
  agent: AgentDetail;
  policies: PolicyInfo[];
  isSaving: boolean;
  isDeleting: boolean;
  error: string;
  onSave: (payload: UpdateAgentPayload, gooseConfigFilesText: string, a2aAllowedCallersText: string) => void;
  onDelete: () => void;
}

export function AgentManagementPanel({
  agent,
  policies,
  isSaving,
  isDeleting,
  error,
  onSave,
  onDelete,
}: AgentManagementPanelProps) {
  const [model, setModel] = useState(agent.model);
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt);
  const [policyRef, setPolicyRef] = useState(agent.policy_ref ?? "");
  const [storageSize, setStorageSize] = useState(agent.storage_size ?? "1Gi");
  const [runtimeKind, setRuntimeKind] = useState<RuntimeKind>(agent.runtime_kind ?? "langgraph");
  const [enableGvisor, setEnableGvisor] = useState(agent.enable_gvisor);
  const [a2aAllowedCallersText, setA2aAllowedCallersText] = useState(stringifyA2APeerRefs(agent.a2a_config.allowed_callers));
  const [gooseConfigFilesText, setGooseConfigFilesText] = useState(stringifyGooseConfigFiles(agent.goose_config_files));

  useEffect(() => {
    setModel(agent.model);
    setSystemPrompt(agent.system_prompt);
    setPolicyRef(agent.policy_ref ?? "");
    setStorageSize(agent.storage_size ?? "1Gi");
    setRuntimeKind(agent.runtime_kind ?? "langgraph");
    setEnableGvisor(agent.enable_gvisor);
    setA2aAllowedCallersText(stringifyA2APeerRefs(agent.a2a_config.allowed_callers));
    setGooseConfigFilesText(stringifyGooseConfigFiles(agent.goose_config_files));
  }, [agent]);

  return (
    <section className="panel panel-setup">
      <div className="panel-header panel-header-chat">
        <div>
          <p className="eyebrow">Agent Settings</p>
          <h2>{agent.name}</h2>
        </div>
        <span className={`mode-pill ${agent.status === "running" ? "live" : "sync"}`}>{agent.status}</span>
      </div>

      <div className="resource-grid resource-grid-agent">
        <div className="setup-form">
          <label>
            <span>Model</span>
            <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="gpt-4" />
          </label>
          <label>
            <span>Policy</span>
            <select value={policyRef} onChange={(event) => setPolicyRef(event.target.value)}>
              <option value="">No policy</option>
              {policies.map((policy) => (
                <option key={policy.name} value={policy.name}>
                  {policy.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Storage size</span>
            <input value={storageSize} onChange={(event) => setStorageSize(event.target.value)} placeholder="1Gi" />
          </label>
          <label>
            <span>Runtime</span>
            <select value={runtimeKind} onChange={(event) => setRuntimeKind(event.target.value as RuntimeKind)}>
              <option value="langgraph">LangGraph runtime</option>
              <option value="goose">Goose runtime</option>
            </select>
          </label>
          <label className="toggle-chip align-start">
            <input checked={enableGvisor} type="checkbox" onChange={(event) => setEnableGvisor(event.target.checked)} />
            <span>Enable gVisor runtime class</span>
          </label>
        </div>

        <div className="setup-form">
          <label>
            <span>System prompt</span>
            <textarea
              className="prompt-input compact-input"
              rows={8}
              value={systemPrompt}
              onChange={(event) => setSystemPrompt(event.target.value)}
            />
          </label>
          <label>
            <span>Allowed caller agents (A2A)</span>
            <textarea
              className="prompt-input compact-input"
              rows={5}
              value={a2aAllowedCallersText}
              onChange={(event) => setA2aAllowedCallersText(event.target.value)}
              placeholder={A2A_ALLOWED_CALLERS_PLACEHOLDER}
            />
          </label>
          {runtimeKind === "goose" ? (
            <label>
              <span>Goose config files (JSON)</span>
              <textarea
                className="prompt-input compact-input"
                rows={10}
                value={gooseConfigFilesText}
                onChange={(event) => setGooseConfigFilesText(event.target.value)}
                placeholder={GOOSE_CONFIG_FILES_PLACEHOLDER}
              />
            </label>
          ) : null}
          {runtimeKind === "goose" ? (
            <p className="hint-text">
              Keys must be relative Goose config-root paths such as <code>config.yaml</code> or <code>prompts/review.md</code>.
            </p>
          ) : null}
          <p className="hint-text">List one caller per line as <code>namespace/name</code>. These entries drive inbound A2A access and ingress policy generation.</p>
          {error ? <p className="error-banner">{error}</p> : null}
          <div className="composer-actions wrap-actions">
            <p className="hint-text">Saving updates the agent spec and triggers the operator to reconcile the runtime.</p>
            <div className="approval-actions">
              <button
                className="primary-button"
                type="button"
                onClick={() =>
                  onSave({
                    model: model.trim(),
                    system_prompt: systemPrompt,
                    policy_ref: policyRef.trim() || undefined,
                    storage_size: storageSize.trim() || undefined,
                    runtime_kind: runtimeKind,
                    enable_gvisor: enableGvisor,
                  }, gooseConfigFilesText, a2aAllowedCallersText)
                }
                disabled={!model.trim() || isSaving}
              >
                <Save size={16} />
                <span>{isSaving ? "Saving" : "Save changes"}</span>
              </button>
              <button className="secondary-button danger-button" type="button" onClick={onDelete} disabled={isDeleting}>
                <Trash2 size={16} />
                <span>{isDeleting ? "Deleting" : "Delete agent"}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
