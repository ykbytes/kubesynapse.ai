import { PlusCircle, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import type { AgentInfo, EvalInfo, EvalPayload, EvalTestCase, EvalUpdatePayload } from "../types";

interface EvalManagerProps {
  evalResource: EvalInfo | null;
  agents: AgentInfo[];
  isSaving: boolean;
  isDeleting: boolean;
  error: string;
  onCreate: (payload: EvalPayload) => void;
  onUpdate: (name: string, payload: EvalUpdatePayload) => void;
  onDelete: (name: string) => void;
}

type ThresholdDraft = {
  maxToxicity: string;
  minRelevance: string;
  maxLatencyMs: string;
};

type ThresholdBuildResult = {
  values: Record<string, unknown>;
  error: string | null;
};

const METRIC_OPTIONS = ["relevance", "faithfulness", "toxicity", "latency"];

function defaultCases(): EvalTestCase[] {
  return [{ input: "", expected_output: "", metrics: ["relevance"] }];
}

function thresholdsFromResource(evalResource: EvalInfo | null): ThresholdDraft {
  return {
    maxToxicity: evalResource?.failure_threshold.maxToxicity ? String(evalResource.failure_threshold.maxToxicity) : "",
    minRelevance: evalResource?.failure_threshold.minRelevance ? String(evalResource.failure_threshold.minRelevance) : "",
    maxLatencyMs: evalResource?.failure_threshold.maxLatencyMs ? String(evalResource.failure_threshold.maxLatencyMs) : "",
  };
}

export function EvalManager({
  evalResource,
  agents,
  isSaving,
  isDeleting,
  error,
  onCreate,
  onUpdate,
  onDelete,
}: EvalManagerProps) {
  const [name, setName] = useState("");
  const [agentRef, setAgentRef] = useState("");
  const [schedule, setSchedule] = useState("");
  const [testSuite, setTestSuite] = useState<EvalTestCase[]>(defaultCases());
  const [thresholds, setThresholds] = useState<ThresholdDraft>(thresholdsFromResource(null));
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    if (evalResource) {
      setName(evalResource.name);
      setAgentRef(evalResource.agent_ref);
      setSchedule(evalResource.schedule ?? "");
      setTestSuite(evalResource.test_suite.length > 0 ? evalResource.test_suite : defaultCases());
      setThresholds(thresholdsFromResource(evalResource));
      setValidationError("");
      return;
    }

    setName("");
    setAgentRef(agents[0]?.name ?? "");
    setSchedule("");
    setTestSuite(defaultCases());
    setThresholds(thresholdsFromResource(null));
    setValidationError("");
  }, [evalResource, agents]);

  function updateCase(index: number, updater: (current: EvalTestCase) => EvalTestCase) {
    setTestSuite((current) => current.map((item, itemIndex) => (itemIndex === index ? updater(item) : item)));
  }

  function parseThresholdValue(label: string, rawValue: string): number | null {
    const trimmed = rawValue.trim();
    if (!trimmed) {
      return null;
    }

    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) {
      throw new Error(`${label} must be a valid number.`);
    }
    return parsed;
  }

  function buildFailureThreshold(): ThresholdBuildResult {
    const next: Record<string, unknown> = {};
    try {
      const maxToxicity = parseThresholdValue("Max toxicity", thresholds.maxToxicity);
      const minRelevance = parseThresholdValue("Min relevance", thresholds.minRelevance);
      const maxLatencyMs = parseThresholdValue("Max latency ms", thresholds.maxLatencyMs);

      if (maxToxicity !== null) {
        next.maxToxicity = maxToxicity;
      }
      if (minRelevance !== null) {
        next.minRelevance = minRelevance;
      }
      if (maxLatencyMs !== null) {
        next.maxLatencyMs = maxLatencyMs;
      }
    } catch (error) {
      return {
        values: {},
        error: error instanceof Error ? error.message : String(error),
      };
    }

    return { values: next, error: null };
  }

  const canSubmit = Boolean(name.trim()) && Boolean(agentRef.trim()) && testSuite.every((item) => item.input.trim());

  return (
    <section className="panel panel-setup">
      <div className="panel-header panel-header-chat">
        <div>
          <p className="eyebrow">Evaluation Suite</p>
          <h2>{evalResource ? evalResource.name : "Create evaluation"}</h2>
        </div>
        <span className={`mode-pill ${evalResource?.phase === "running" ? "live" : "sync"}`}>{evalResource?.phase ?? "draft"}</span>
      </div>

      <div className="resource-grid">
        <div className="setup-form">
          <label>
            <span>Name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="research-assistant-eval" disabled={Boolean(evalResource)} />
          </label>
          <label>
            <span>Agent</span>
            <select value={agentRef} onChange={(event) => setAgentRef(event.target.value)}>
              <option value="">Select agent</option>
              {agents.map((agent) => (
                <option key={agent.name} value={agent.name}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Schedule</span>
            <input value={schedule} onChange={(event) => setSchedule(event.target.value)} placeholder="0 */6 * * *" />
          </label>

          <div className="threshold-grid">
            <label>
              <span>Max toxicity</span>
              <input
                value={thresholds.maxToxicity}
                onChange={(event) => {
                  setValidationError("");
                  setThresholds((current) => ({ ...current, maxToxicity: event.target.value }));
                }}
              />
            </label>
            <label>
              <span>Min relevance</span>
              <input
                value={thresholds.minRelevance}
                onChange={(event) => {
                  setValidationError("");
                  setThresholds((current) => ({ ...current, minRelevance: event.target.value }));
                }}
              />
            </label>
            <label>
              <span>Max latency ms</span>
              <input
                value={thresholds.maxLatencyMs}
                onChange={(event) => {
                  setValidationError("");
                  setThresholds((current) => ({ ...current, maxLatencyMs: event.target.value }));
                }}
              />
            </label>
          </div>
        </div>

        <div className="setup-form">
          <div className="resource-section-header">
            <span>Test cases</span>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setTestSuite((current) => [...current, { input: "", expected_output: "", metrics: ["relevance"] }])}
            >
              <PlusCircle size={16} />
              <span>Add case</span>
            </button>
          </div>

          <div className="subresource-stack">
            {testSuite.map((testCase, index) => (
              <article key={`${index}-${testCase.input}`} className="subresource-card">
                <div className="resource-section-header">
                  <strong>Case {index + 1}</strong>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => setTestSuite((current) => current.filter((_, caseIndex) => caseIndex !== index))}
                    disabled={testSuite.length === 1}
                  >
                    <Trash2 size={14} />
                    <span>Remove</span>
                  </button>
                </div>
                <label>
                  <span>Input</span>
                  <textarea
                    className="prompt-input compact-input"
                    rows={3}
                    value={testCase.input}
                    onChange={(event) => updateCase(index, (current) => ({ ...current, input: event.target.value }))}
                  />
                </label>
                <label>
                  <span>Expected output</span>
                  <textarea
                    className="prompt-input compact-input"
                    rows={3}
                    value={testCase.expected_output}
                    onChange={(event) => updateCase(index, (current) => ({ ...current, expected_output: event.target.value }))}
                  />
                </label>
                <div className="metric-grid">
                  {METRIC_OPTIONS.map((metric) => (
                    <label key={metric} className="toggle-chip align-start">
                      <input
                        checked={testCase.metrics.includes(metric)}
                        type="checkbox"
                        onChange={(event) =>
                          updateCase(index, (current) => ({
                            ...current,
                            metrics: event.target.checked
                              ? [...current.metrics, metric]
                              : current.metrics.filter((item) => item !== metric),
                          }))
                        }
                      />
                      <span>{metric}</span>
                    </label>
                  ))}
                </div>
              </article>
            ))}
          </div>

          {validationError ? <p className="error-banner">{validationError}</p> : null}
          {!validationError && error ? <p className="error-banner">{error}</p> : null}
          <div className="approval-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => {
                const thresholdResult = buildFailureThreshold();
                if (thresholdResult.error) {
                  setValidationError(thresholdResult.error);
                  return;
                }

                setValidationError("");
                const payload = {
                  agent_ref: agentRef,
                  schedule: schedule.trim() || undefined,
                  test_suite: testSuite,
                  failure_threshold: thresholdResult.values,
                };
                if (evalResource) {
                  onUpdate(evalResource.name, payload as EvalUpdatePayload);
                  return;
                }
                onCreate({ name, ...payload });
              }}
              disabled={!canSubmit || isSaving}
            >
              <Save size={16} />
              <span>{isSaving ? "Saving" : evalResource ? "Save evaluation" : "Create evaluation"}</span>
            </button>
            {evalResource ? (
              <button className="secondary-button danger-button" type="button" onClick={() => onDelete(evalResource.name)} disabled={isDeleting}>
                <Trash2 size={16} />
                <span>{isDeleting ? "Deleting" : "Delete evaluation"}</span>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
