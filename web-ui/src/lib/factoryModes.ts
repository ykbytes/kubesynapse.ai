import type { FactoryMode } from "@/types";

export const FACTORY_AGENT_NAME = "kubesynapse-factory";
export const FACTORY_WORKFLOW_NAME = "kubesynapse-factory-pipeline";
export const DEFAULT_FACTORY_MODE: FactoryMode = "governed-bundle";

export const FACTORY_MODE_OPTIONS: Array<{
  value: FactoryMode;
  label: string;
  shortLabel: string;
  description: string;
}> = [
  {
    value: "lightweight-draft",
    label: "Lightweight draft",
    shortLabel: "Draft",
    description: "Fast first-pass blueprint with the leanest useful bundle. Stops before governed review and deployment branches.",
  },
  {
    value: "governed-bundle",
    label: "Governed bundle",
    shortLabel: "Governed",
    description: "Runs the governed review and bounded rework flow, then produces a reviewed bundle without entering the deploy branch.",
  },
  {
    value: "fully-autonomous",
    label: "Fully autonomous",
    shortLabel: "Autonomous",
    description: "Runs the full review and bounded rework flow, then enters the deploy branch when the reviewed bundle is deployable. Workflow approval gates still apply.",
  },
];

export function isFactoryAgentName(name?: string | null): boolean {
  return (name ?? "").trim() === FACTORY_AGENT_NAME;
}

export function isFactoryWorkflowName(name?: string | null): boolean {
  return (name ?? "").trim() === FACTORY_WORKFLOW_NAME;
}

export function factoryModeLabel(mode: FactoryMode): string {
  return FACTORY_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? "Governed bundle";
}

export function factoryModeShortLabel(mode: FactoryMode): string {
  return FACTORY_MODE_OPTIONS.find((option) => option.value === mode)?.shortLabel ?? "Governed";
}