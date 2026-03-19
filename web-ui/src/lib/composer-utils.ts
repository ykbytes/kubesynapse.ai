import type { Node, Edge } from "@xyflow/react";
import type {
  WorkflowInfo,
  WorkflowStep,
  WorkflowPayload,
  WorkflowStepState,
  AgentInfo,
  LoopConfig,
} from "@/types";

/* ── Constants ── */

export const TRIGGER_NODE_ID = "__trigger__";

const NODE_W = 280;
const NODE_H = 100;
const GAP_X = 80;
const GAP_Y = 180;

/* ── Node data contracts ── */

export interface TriggerNodeData extends Record<string, unknown> {
  label: string;
}

export interface AgentStepNodeData extends Record<string, unknown> {
  stepName: string;
  agentRef: string;
  prompt: string;
  requireApproval: boolean;
  stepType: "agent" | "loop" | "conditional";
  loopConfig?: LoopConfig | null;
  conditionExpr?: string | null;
  thenSteps?: string[] | null;
  elseSteps?: string[] | null;
  stepState?: WorkflowStepState | null;
  runtimeKind?: string | null;
}

/* ── Composite type for all composer nodes ── */

export type TriggerNode = Node<TriggerNodeData, "trigger">;
export type AgentStepNode = Node<AgentStepNodeData, "agentStep">;
export type ComposerNode = TriggerNode | AgentStepNode;

/* ── Workflow ↔ Canvas conversion ── */

export function workflowToCanvas(
  workflow: WorkflowInfo,
  _agents: AgentInfo[],
): { nodes: ComposerNode[]; edges: Edge[] } {
  const nodes: ComposerNode[] = [];
  const edges: Edge[] = [];

  const agentMap = new Map(_agents.map((a) => [a.name, a]));

  // Trigger node
  nodes.push({
    id: TRIGGER_NODE_ID,
    type: "trigger",
    position: { x: 0, y: 0 },
    data: { label: workflow.name },
    deletable: false,
  });

  for (const step of workflow.steps) {
    const ex = step.execution as Record<string, unknown> | null | undefined;
    const x = (ex?._composerX as number) ?? undefined;
    const y = (ex?._composerY as number) ?? undefined;
    const stepState = workflow.step_states?.[step.name] ?? null;
    const agent = agentMap.get(step.agent_ref);

    nodes.push({
      id: step.name,
      type: "agentStep",
      position: { x: x ?? 0, y: y ?? 0 },
      data: {
        stepName: step.name,
        agentRef: step.agent_ref,
        prompt: step.prompt,
        requireApproval: step.require_approval,
        stepType: step.step_type ?? "agent",
        loopConfig: step.loop_config,
        conditionExpr: step.condition_expr ?? null,
        thenSteps: step.then_steps ?? null,
        elseSteps: step.else_steps ?? null,
        stepState,
        runtimeKind: agent?.runtime_kind ?? null,
      },
    });

    if (step.depends_on.length === 0) {
      edges.push({
        id: `e-${TRIGGER_NODE_ID}-${step.name}`,
        source: TRIGGER_NODE_ID,
        target: step.name,
        type: "dependency",
      });
    } else {
      for (const dep of step.depends_on) {
        edges.push({
          id: `e-${dep}-${step.name}`,
          source: dep,
          target: step.name,
          type: "dependency",
        });
      }
    }
  }

  // Auto-layout when no stored positions exist
  const hasPositions = workflow.steps.some((s) => {
    const ex = s.execution as Record<string, unknown> | null | undefined;
    return ex?._composerX != null;
  });
  if (!hasPositions) autoLayout(nodes, edges);

  return { nodes, edges };
}

/* ── Simple topological auto-layout ── */

export function autoLayout(nodes: ComposerNode[], edges: Edge[]): void {
  if (nodes.length === 0) return;

  const parentMap = new Map<string, string[]>();
  for (const edge of edges) {
    const list = parentMap.get(edge.target) ?? [];
    list.push(edge.source);
    parentMap.set(edge.target, list);
  }

  const depthMap = new Map<string, number>();
  depthMap.set(TRIGGER_NODE_ID, 0);

  let changed = true;
  while (changed) {
    changed = false;
    for (const node of nodes) {
      if (depthMap.has(node.id)) continue;
      const parents = parentMap.get(node.id) ?? [];
      if (parents.length === 0) {
        depthMap.set(node.id, 1);
        changed = true;
      } else if (parents.every((p) => depthMap.has(p))) {
        const maxDepth = Math.max(...parents.map((p) => depthMap.get(p)!));
        depthMap.set(node.id, maxDepth + 1);
        changed = true;
      }
    }
  }

  // Unreachable nodes fallback
  for (const node of nodes) {
    if (!depthMap.has(node.id)) depthMap.set(node.id, 1);
  }

  const depthGroups = new Map<number, ComposerNode[]>();
  for (const node of nodes) {
    const d = depthMap.get(node.id) ?? 0;
    const group = depthGroups.get(d) ?? [];
    group.push(node);
    depthGroups.set(d, group);
  }

  const maxDepth = Math.max(...depthGroups.keys(), 0);
  for (let d = 0; d <= maxDepth; d++) {
    const group = depthGroups.get(d) ?? [];
    const totalWidth = group.length * NODE_W + (group.length - 1) * GAP_X;
    const startX = -totalWidth / 2 + NODE_W / 2;
    group.forEach((node, i) => {
      node.position = { x: startX + i * (NODE_W + GAP_X), y: d * (NODE_H + GAP_Y) };
    });
  }
}

/* ── Canvas → WorkflowPayload ── */

export function canvasToPayload(
  nodes: ComposerNode[],
  edges: Edge[],
  name: string,
  description: string,
  input: string,
): WorkflowPayload {
  const steps: WorkflowStep[] = [];

  for (const node of nodes) {
    if (node.type === "trigger") continue;
    const d = node.data as AgentStepNodeData;

    const deps = edges
      .filter((e) => e.target === node.id && e.source !== TRIGGER_NODE_ID)
      .map((e) => e.source);

    steps.push({
      name: d.stepName,
      agent_ref: d.agentRef,
      prompt: d.prompt,
      depends_on: deps,
      require_approval: d.requireApproval,
      step_type: d.stepType,
      loop_config: d.loopConfig,
      condition_expr: d.conditionExpr,
      then_steps: d.thenSteps,
      else_steps: d.elseSteps,
      execution: {
        _composerX: node.position.x,
        _composerY: node.position.y,
      },
    });
  }

  return { name, description, input, steps };
}

/* ── Helpers ── */

export function makeStepId(agentName: string, existingIds: Set<string>): string {
  let base = agentName.replace(/[^a-z0-9-]/gi, "-").toLowerCase();
  if (!base) base = "step";
  let id = base;
  let n = 2;
  while (existingIds.has(id)) {
    id = `${base}-${n++}`;
  }
  return id;
}

/* ── Cycle detection (DFS) ── */

export function hasCycle(
  edges: Edge[],
  proposedSource: string,
  proposedTarget: string,
): boolean {
  // Build adjacency list including the proposed edge
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    const list = adj.get(e.source) ?? [];
    list.push(e.target);
    adj.set(e.source, list);
  }
  const srcList = adj.get(proposedSource) ?? [];
  srcList.push(proposedTarget);
  adj.set(proposedSource, srcList);

  // DFS from proposedTarget to see if we can reach proposedSource
  const visited = new Set<string>();
  const stack = [proposedTarget];
  while (stack.length > 0) {
    const node = stack.pop()!;
    if (node === proposedSource) return true;
    if (visited.has(node)) continue;
    visited.add(node);
    for (const neighbor of adj.get(node) ?? []) {
      stack.push(neighbor);
    }
  }
  return false;
}

/* ── Runtime kind → display helpers ── */

export type RuntimeKindKey = "langgraph" | "goose" | "opencode" | "codex" | string;

const RUNTIME_COLORS: Record<string, string> = {
  langgraph: "border-l-violet-500",
  goose: "border-l-amber-500",
  opencode: "border-l-sky-500",
  codex: "border-l-emerald-500",
};

export function runtimeAccentClass(kind?: string | null): string {
  if (!kind) return "border-l-muted-foreground/40";
  return RUNTIME_COLORS[kind] ?? "border-l-primary/60";
}
