import { useCallback, useMemo, useRef, useState, type DragEvent } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type NodeTypes,
  type EdgeTypes,
  ReactFlowProvider,
  useReactFlow,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useWorkspace } from "@/contexts/WorkspaceContext";
import type { AgentInfo, WorkflowInfo } from "@/types";
import {
  type ComposerNode,
  type AgentStepNodeData,
  TRIGGER_NODE_ID,
  workflowToCanvas,
  canvasToPayload,
  autoLayout,
  makeStepId,
} from "@/lib/composer-utils";

import { AgentNode } from "./composer/AgentNode";
import { TriggerNode } from "./composer/TriggerNode";
import { DependencyEdge } from "./composer/DependencyEdge";
import { NodePalette } from "./composer/NodePalette";
import { PropertiesPanel } from "./composer/PropertiesPanel";
import { ComposerToolbar } from "./composer/ComposerToolbar";
import { toast } from "sonner";
import { AlertCircle } from "lucide-react";

/* ── Custom node/edge registration ── */

const nodeTypes: NodeTypes = {
  trigger: TriggerNode,
  agentStep: AgentNode,
};

const edgeTypes: EdgeTypes = {
  dependency: DependencyEdge,
};

/* ── Inner canvas (needs ReactFlowProvider parent) ── */

function ComposerCanvas({
  workflow,
  agents,
}: {
  workflow: WorkflowInfo | null;
  agents: AgentInfo[];
}) {
  const ws = useWorkspace();
  const reactFlowInstance = useReactFlow();
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Form state
  const [wfName, setWfName] = useState(workflow?.name ?? "");
  const [wfDesc, setWfDesc] = useState(workflow?.description ?? "");
  const [wfInput, setWfInput] = useState(workflow?.input ?? "");

  const isNew = !workflow;

  // Build initial nodes/edges from workflow
  const initial = useMemo(() => {
    if (workflow) return workflowToCanvas(workflow, agents);
    return {
      nodes: [
        {
          id: TRIGGER_NODE_ID,
          type: "trigger" as const,
          position: { x: 0, y: 0 },
          data: { label: "New Workflow" },
          deletable: false,
        },
      ] as ComposerNode[],
      edges: [],
    };
  }, [workflow, agents]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);

  const selectedNode = useMemo(
    () => (nodes as ComposerNode[]).find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  );

  // Handle new connection
  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds) =>
        addEdge({ ...params, type: "dependency" }, eds),
      );
      setIsDirty(true);
    },
    [setEdges],
  );

  // Handle node selection
  const onSelectionChange = useCallback(
    ({ nodes: sel }: { nodes: ComposerNode[] }) => {
      setSelectedNodeId(sel.length === 1 ? sel[0].id : null);
    },
    [],
  );

  // Handle drop of agent from palette
  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      const agentName = e.dataTransfer.getData("application/kubemininions-agent");
      if (!agentName || !wrapperRef.current) return;

      const position = reactFlowInstance.screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      });

      setNodes((nds) => {
        const existingIds = new Set(nds.map((n) => n.id));
        const stepId = makeStepId(agentName, existingIds);

        const newNode: ComposerNode = {
          id: stepId,
          type: "agentStep",
          position,
          data: {
            stepName: stepId,
            agentRef: agentName,
            prompt: "",
            requireApproval: false,
            stepType: "agent",
            loopConfig: null,
            stepState: null,
          },
        };

        return [...nds, newNode];
      });
      setIsDirty(true);
    },
    [reactFlowInstance, setNodes],
  );

  // Update node data from properties panel
  const handleNodeDataChange = useCallback(
    (nodeId: string, patch: Partial<AgentStepNodeData>) => {
      setNodes((nds) => {
        const updated = nds.map((n) => {
          if (n.id !== nodeId) return n;
          const oldName = (n.data as AgentStepNodeData).stepName;
          const newName = patch.stepName;
          if (newName && newName !== oldName) {
            // Validate uniqueness
            if (!newName.trim() || nds.some((other) => other.id !== n.id && other.id === newName)) {
              toast.error("Step name must be unique and non-empty");
              return { ...n, data: { ...n.data, ...patch, stepName: oldName } };
            }
            const oldNodeId = n.id;
            // Update edges to reference the new node id
            setEdges((eds) =>
              eds.map((e) => {
                const newSource = e.source === oldNodeId ? newName : e.source;
                const newTarget = e.target === oldNodeId ? newName : e.target;
                return {
                  ...e,
                  id: `e-${newSource}-${newTarget}`,
                  source: newSource,
                  target: newTarget,
                };
              }),
            );
            return { ...n, id: newName, data: { ...n.data, ...patch } };
          }
          return { ...n, data: { ...n.data, ...patch } };
        });
        return updated;
      });
      setIsDirty(true);
    },
    [setNodes, setEdges],
  );

  // Auto-layout
  const handleAutoLayout = useCallback(() => {
    setNodes((nds) => {
      const copy = nds.map((n) => ({ ...n })) as ComposerNode[];
      autoLayout(copy, edges);
      return copy;
    });
    setTimeout(() => reactFlowInstance.fitView({ padding: 0.2 }), 50);
    toast.success("Layout applied");
  }, [edges, setNodes, reactFlowInstance]);

  // Save — context handlers already show toast.success/toast.error
  const handleSave = useCallback(async () => {
    if (!wfName.trim()) { toast.error("Workflow name is required"); return; }
    const payload = canvasToPayload(nodes as ComposerNode[], edges, wfName, wfDesc, wfInput);
    if (isNew) {
      await ws.handleCreateWorkflow(payload);
    } else {
      const { name: _, ...updatePayload } = payload;
      await ws.handleUpdateWorkflow(wfName, updatePayload);
    }
    setIsDirty(false);
  }, [nodes, edges, wfName, wfDesc, wfInput, isNew, ws]);

  // Run — context handlers already show toast.success/toast.error
  const handleRun = useCallback(async () => {
    if (isNew) { toast.info("Save the workflow first before running"); return; }
    if (!wfName.trim()) return;
    await ws.handleTriggerWorkflow(wfName, wfInput || undefined);
  }, [wfName, wfInput, isNew, ws]);

  // Back — warn if unsaved changes
  const handleBack = useCallback(() => {
    if (isDirty) {
      const leave = window.confirm("You have unsaved changes. Leave without saving?");
      if (!leave) return;
    }
    ws.setActiveView("workflows");
  }, [ws, isDirty]);

  // Delete selected nodes (except trigger)
  const onNodesDelete = useCallback(
    (deleted: ComposerNode[]) => {
      const deletedIds = new Set(deleted.map((n) => n.id));
      setEdges((eds) => eds.filter((e) => !deletedIds.has(e.source) && !deletedIds.has(e.target)));
      setIsDirty(true);
    },
    [setEdges],
  );

  return (
    <div className="flex flex-col h-full w-full">
      {ws.workflowError && (
        <div className="flex items-center gap-2 border-b border-destructive/30 bg-destructive/10 px-3 py-1.5 text-xs text-destructive shrink-0">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{ws.workflowError}</span>
        </div>
      )}

      <ComposerToolbar
        workflowName={wfName}
        description={wfDesc}
        input={wfInput}
        isNew={isNew}
        isDirty={isDirty}
        isSaving={ws.savingWorkflow}
        isRunning={ws.runningWorkflow}
        onNameChange={(v) => { setWfName(v); setIsDirty(true); }}
        onDescriptionChange={(v) => { setWfDesc(v); setIsDirty(true); }}
        onInputChange={(v) => { setWfInput(v); setIsDirty(true); }}
        onSave={handleSave}
        onRun={handleRun}
        onAutoLayout={handleAutoLayout}
        onBack={handleBack}
      />

      <div className="flex flex-1 min-h-0 overflow-hidden">
        <NodePalette agents={agents} />

        <div ref={wrapperRef} className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onSelectionChange={onSelectionChange}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onNodesDelete={onNodesDelete}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            deleteKeyCode={["Backspace", "Delete"]}
            className="bg-background"
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
            <Controls className="!bg-card !border-border !shadow-sm" />
            <MiniMap
              className="!bg-muted/50 !border-border"
              nodeColor={(n) => {
                if (n.type === "trigger") return "hsl(var(--primary))";
                const state = (n.data as AgentStepNodeData)?.stepState?.status;
                if (state === "completed") return "#22c55e";
                if (state === "running") return "#eab308";
                if (state === "failed") return "#ef4444";
                return "hsl(var(--muted-foreground))";
              }}
            />
            {/* Custom arrow marker */}
            <svg style={{ position: "absolute", width: 0, height: 0 }}>
              <defs>
                <marker
                  id="dependency-arrow"
                  viewBox="0 0 10 10"
                  refX="10"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="hsl(var(--primary))" />
                </marker>
              </defs>
            </svg>
          </ReactFlow>
        </div>

        <PropertiesPanel
          selectedNode={selectedNode}
          agents={agents}
          onNodeDataChange={handleNodeDataChange}
        />
      </div>
    </div>
  );
}

/* ── Outer wrapper with ReactFlowProvider ── */

export function WorkflowComposer() {
  const ws = useWorkspace();

  return (
    <ReactFlowProvider>
      <ComposerCanvas
        key={ws.selectedWorkflow?.name ?? "__new__"}
        workflow={ws.selectedWorkflow}
        agents={ws.agents}
      />
    </ReactFlowProvider>
  );
}
