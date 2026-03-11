import { Bot, LoaderCircle, PlusCircle } from "lucide-react";

import { A2A_ALLOWED_CALLERS_PLACEHOLDER } from "../lib/a2a";
import { GOOSE_CONFIG_FILES_PLACEHOLDER } from "../lib/gooseConfig";
import type { RuntimeKind } from "../types";

interface CreateAgentPanelProps {
  name: string;
  model: string;
  systemPrompt: string;
  runtimeKind: RuntimeKind;
  a2aAllowedCallersText: string;
  gooseConfigFilesText: string;
  isCreating: boolean;
  error: string;
  onNameChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onSystemPromptChange: (value: string) => void;
  onRuntimeKindChange: (value: RuntimeKind) => void;
  onA2AAllowedCallersTextChange: (value: string) => void;
  onGooseConfigFilesTextChange: (value: string) => void;
  onCreate: () => void;
}

export function CreateAgentPanel({
  name,
  model,
  systemPrompt,
  runtimeKind,
  a2aAllowedCallersText,
  gooseConfigFilesText,
  isCreating,
  error,
  onNameChange,
  onModelChange,
  onSystemPromptChange,
  onRuntimeKindChange,
  onA2AAllowedCallersTextChange,
  onGooseConfigFilesTextChange,
  onCreate,
}: CreateAgentPanelProps) {
  return (
    <section className="panel panel-setup">
      <div className="panel-header panel-header-chat">
        <div>
          <p className="eyebrow">First Run Setup</p>
          <h2>Create your first agent</h2>
        </div>
        <span className="mode-pill sync">empty workspace</span>
      </div>

      <div className="setup-grid">
        <div className="setup-copy">
          <div className="setup-icon">
            <Bot size={22} />
          </div>
          <p>
            The cluster is reachable, but this namespace has no agents yet. Create one here and the operator will provision
            the runtime pod, service, storage, and control-plane wiring.
          </p>
          <p className="muted-copy">Use a model name that your LiteLLM gateway already exposes.</p>
        </div>

        <div className="setup-form">
          <label>
            <span>Agent name</span>
            <input value={name} onChange={(event) => onNameChange(event.target.value)} placeholder="workspace-assistant" />
          </label>
          <label>
            <span>Model</span>
            <input value={model} onChange={(event) => onModelChange(event.target.value)} placeholder="gpt-4" />
          </label>
          <label>
            <span>Runtime</span>
            <select value={runtimeKind} onChange={(event) => onRuntimeKindChange(event.target.value as RuntimeKind)}>
              <option value="langgraph">LangGraph runtime</option>
              <option value="goose">Goose runtime</option>
            </select>
          </label>
          <label>
            <span>System prompt</span>
            <textarea
              className="prompt-input compact-input"
              rows={5}
              value={systemPrompt}
              onChange={(event) => onSystemPromptChange(event.target.value)}
              placeholder="You are a helpful enterprise assistant. Be concise, factual, and do not fabricate information."
            />
          </label>
          <label>
            <span>Allowed caller agents (A2A)</span>
            <textarea
              className="prompt-input compact-input"
              rows={4}
              value={a2aAllowedCallersText}
              onChange={(event) => onA2AAllowedCallersTextChange(event.target.value)}
              placeholder={A2A_ALLOWED_CALLERS_PLACEHOLDER}
            />
          </label>
          {runtimeKind === "goose" ? (
            <label>
              <span>Goose config files (JSON)</span>
              <textarea
                className="prompt-input compact-input"
                rows={8}
                value={gooseConfigFilesText}
                onChange={(event) => onGooseConfigFilesTextChange(event.target.value)}
                placeholder={GOOSE_CONFIG_FILES_PLACEHOLDER}
              />
            </label>
          ) : null}

          {runtimeKind === "goose" ? (
            <p className="hint-text">
              Use a JSON object keyed by relative Goose config-root paths such as <code>config.yaml</code> or <code>prompts/review.md</code>.
            </p>
          ) : null}

          <p className="hint-text">List one caller per line as <code>namespace/name</code>. Only listed agents can invoke this agent over A2A.</p>

          {error ? <p className="error-banner">{error}</p> : null}

          <div className="composer-actions">
            <p className="hint-text">
              After creation, the agent may stay in an unknown state briefly while the operator starts the runtime pod.
            </p>
            <button className="primary-button" type="button" onClick={onCreate} disabled={!name.trim() || !model.trim() || isCreating}>
              {isCreating ? <LoaderCircle size={16} className="spin" /> : <PlusCircle size={16} />}
              <span>{isCreating ? "Creating" : "Create agent"}</span>
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}