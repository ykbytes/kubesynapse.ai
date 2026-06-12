import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  ReactFlowProvider,
  useReactFlow,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useWorkspace } from "@/contexts/WorkspaceContext";
import { useConnection } from "@/contexts/ConnectionContext";
import type { AgentInfo, WorkflowInfo } from "@/types";
import { decideApproval } from "@/lib/api";
import {
  type ComposerNode,
  type AgentStepNodeData,
  type LayoutDirection,
  TRIGGER_NODE_ID,
  workflowToCanvas,
  canvasToPayload,
  autoLayout,
  makeStepId,
  hasCycle,
  setCurrentDirection,
  getCurrentDirection,
} from "@/lib/composer-utils";
import { anyStepUsesInput } from "@/lib/template-utils";

import { AgentNode } from "../composer/AgentNode";
import { TriggerNode } from "../composer/TriggerNode";
import { DependencyEdge } from "../composer/DependencyEdge";
import { NodePalette } from "../composer/NodePalette";
import { PropertiesPanel } from "../composer/PropertiesPanel";
import { ComposerToolbar } from "../composer/ComposerToolbar";
import { RunHistoryPanel } from "../composer/RunHistoryPanel";
import { WorkspaceFileBrowser } from "../workflows/WorkspaceFileBrowser";
import { LiveActivityStream, useWorkflowActivities } from "../intelligence/LiveActivityStream";
import { toast } from "sonner";
import { AlertCircle, MousePointerClick } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/* ── Static styles ── */

const SVG_DEFS_STYLE: React.CSSProperties = { position: "absolute", width: 0, height: 0 };

/* ── Inner canvas (needs ReactFlowProvider parent) ── */

function ComposerCanvas({
  workflow,
  agents,
}: {
  workflow: WorkflowInfo | null;
  agents: AgentInfo[];
}) {
  const ws = useWorkspace();
  const { token, namespace } = useConnection();
  const reactFlowInstance = useReactFlow();
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Node/edge type registrations (must be stable references)
  const nodeTypes: NodeTypes = useMemo(() => ({
    trigger: TriggerNode,
    agentStep: AgentNode,
  }), []);

  const edgeTypes: EdgeTypes = useMemo(() => ({
    dependency: DependencyEdge,
  }), []);

  // Form state
  const [wfName, setWfName] = useState(workflow?.name ?? "");
  const [wfDesc, setWfDesc] = useState(workflow?.description ?? "");
  const [wfInput, setWfInput] = useState(workflow?.input ?? "");
  const [wfContextRef] = useState(workflow?.context_ref ?? "");

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
  const [isMaximized, setIsMaximized] = useState(false);
  const [paletteCollapsed, setPaletteCollapsed] = useState(false);
  const [propertiesCollapsed, setPropertiesCollapsed] = useState(false);
  const [runHistoryCollapsed, setRunHistoryCollapsed] = useState(true);
  const [runHistoryExpanded, setRunHistoryExpanded] = useState(false);
  const [filesCollapsed, setFilesCollapsed] = useState(true);
  const [livePanelCollapsed, setLivePanelCollapsed] = useState(true);
  const [layoutDirection, setLayoutDirection] = useState<LayoutDirection>(() => getCurrentDirection());

  // Live activity stream
  const {
    activities,
    isConnected,
    isActive,
    phase: livePhase,
    error: liveError,
    reconnect: liveReconnect,
  } = useWorkflowActivities(token, namespace, workflow?.name ?? null);

  // Live summary stats
  const { activeStepName, toolActivityCount, warningCount, errorCount } = useMemo(() => {
    let activeStep = "";
    let tools = 0;
    let warnings = 0;
    let errors = 0;
    for (const a of activities) {
      if (a.step) activeStep = a.step;
      if (a.type === "warning") warnings += 1;
      if (a.type === "error") errors += 1;
      const d = a.details;
      if (d.tool || d.tool_name) tools += 1;
    }
    return { activeStepName: activeStep, toolActivityCount: tools, warningCount: warnings, errorCount: errors };
  }, [activities]);

  // Sync step states from workflow polling to node data
  useEffect(() => {
    if (!workflow?.step_states) return;
    setNodes((nds) => {
      let changed = false;
      const next = nds.map((n) => {
        if (n.type !== "agentStep") return n;
        const data = n.data as AgentStepNodeData;
        const latestState = workflow.step_states?.[data.stepName] ?? null;
        // Deep-compare to avoid unnecessary re-renders from polling
        if (JSON.stringify(latestState) === JSON.stringify(data.stepState)) return n;
        changed = true;
        return { ...n, data: { ...data, stepState: latestState } };
      });
      return changed ? next : nds;
    });
  }, [workflow?.step_states, setNodes]);

  // Auto-collapse panels on small viewports
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 768px)");
    function handle(e: MediaQueryList | MediaQueryListEvent) {
      if (e.matches) {
        setPaletteCollapsed(true);
        setPropertiesCollapsed(true);
      }
    }
    handle(mql);
    mql.addEventListener("change", handle);
    return () => mql.removeEventListener("change", handle);
  }, []);

  const selectedNode = useMemo(
    () => (nodes as ComposerNode[]).find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  );

  // Handle edge deletion
  const handleEdgeDelete = useCallback(
    (edgeId: string) => {
      setEdges((eds) => eds.filter((e) => e.id !== edgeId));
      setIsDirty(true);
    },
    [setEdges],
  );

  // Inject execution state into edge data so DependencyEdge can animate
  const edgesWithData = useMemo(() => {
    if (!workflow?.step_states) return edges;
    return edges.map((e) => {
      const sourceStatus =
        e.source === TRIGGER_NODE_ID
          ? workflow.phase === "running"
            ? "running"
            : workflow.phase === "completed"
              ? "completed"
              : null
          : workflow.step_states?.[e.source]?.status ?? null;
      return {
        ...e,
        data: {
          ...(e.data ?? {}),
          sourceStatus,
          onDelete: handleEdgeDelete,
        },
      };
    });
  }, [edges, workflow?.step_states, workflow?.phase, handleEdgeDelete]);

  // Connection validation
  const isValidConnection = useCallback(
    (connection: Edge | Connection) => {
      if (!connection.source || !connection.target) return false;
      // No self-connections
      if (connection.source === connection.target) return false;
      // No connecting TO trigger
      if (connection.target === TRIGGER_NODE_ID) return false;
      // No duplicates
      if (edges.some((e) => e.source === connection.source && e.target === connection.target)) return false;
      // No cycles
      if (hasCycle(edges, connection.source, connection.target)) return false;
      return true;
    },
    [edges],
  );

  // Handle new connection
  const onConnect = useCallback(
    (params: Connection) => {
      if (!params.source || !params.target) return;
      // Double-check validation (in case isValidConnection was bypassed)
      if (params.source === params.target) {
        toast.error("Cannot connect a node to itself");
        return;
      }
      if (params.target === TRIGGER_NODE_ID) {
        toast.error("Cannot connect to the trigger node");
        return;
      }
      if (edges.some((e) => e.source === params.source && e.target === params.target)) {
        toast.error("Connection already exists");
        return;
      }
      if (hasCycle(edges, params.source, params.target)) {
        toast.error("Connection would create a cycle");
        return;
      }
      setEdges((eds) => addEdge({ ...params, type: "dependency" }, eds));
      setIsDirty(true);
    },
    [edges, setEdges],
  );

  // Handle node selection
  const onSelectionChange = useCallback(
    ({ nodes: sel }: { nodes: ComposerNode[] }) => {
      const newId = sel.length === 1 ? sel[0].id : null;
      setSelectedNodeId(newId);
      // Auto-expand properties panel when a node is selected
      if (newId && propertiesCollapsed) {
        setPropertiesCollapsed(false);
      }
    },
    [propertiesCollapsed],
  );

  // Handle selecting a node from properties panel
  const handleSelectNodeFromPanel = useCallback(
    (nodeId: string) => {
      setSelectedNodeId(nodeId);
      const node = nodes.find((n) => n.id === nodeId);
      if (node) {
        reactFlowInstance.setCenter(node.position.x + 140, node.position.y + 50, {
          duration: 300,
          zoom: reactFlowInstance.getZoom(),
        });
      }
    },
    [nodes, reactFlowInstance],
  );

  // Add agent step from palette click
  const handleAddAgentFromPalette = useCallback(
    (agentName: string) => {
      const agent = agents.find((a) => a.name === agentName);
      const canvasRect = wrapperRef.current?.getBoundingClientRect();
      const centerX = canvasRect ? canvasRect.width / 2 : 400;
      const centerY = canvasRect ? canvasRect.height / 2 : 300;
      const position = reactFlowInstance.screenToFlowPosition({
        x: centerX,
        y: centerY,
      });

      setNodes((nds) => {
        const existingIds = new Set(nds.map((n) => n.id));
        const stepId = makeStepId(agentName, existingIds);
        // Offset slightly if multiple nodes at same position
        const offsetCount = nds.filter((n) => Math.abs(n.position.x - position.x) < 20 && Math.abs(n.position.y - position.y) < 20).length;
        const finalPosition = {
          x: position.x + offsetCount * 40,
          y: position.y + offsetCount * 40,
        };

        const newNode: ComposerNode = {
          id: stepId,
          type: "agentStep",
          position: finalPosition,
          data: {
            stepName: stepId,
            agentRef: agentName,
            prompt: "",
            requireApproval: false,
            stepType: "agent",
            loopConfig: null,
            conditionExpr: null,
            thenSteps: null,
            elseSteps: null,
            stepState: null,
            runtimeKind: agent?.runtime_kind ?? null,
          },
        };
        return [...nds, newNode];
      });
      setIsDirty(true);
      toast.success(`Added step "${agentName}"`);
    },
    [reactFlowInstance, setNodes, agents],
  );

  // Handle drop of agent from palette
  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      const agentName = e.dataTransfer.getData("application/kubesynapse-agent");
      if (!agentName || !wrapperRef.current) return;

      const position = reactFlowInstance.screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      });

      // Look up runtime kind
      const agent = agents.find((a) => a.name === agentName);

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
            conditionExpr: null,
            thenSteps: null,
            elseSteps: null,
            stepState: null,
            runtimeKind: agent?.runtime_kind ?? null,
          },
        };

        return [...nds, newNode];
      });
      setIsDirty(true);
    },
    [reactFlowInstance, setNodes, agents],
  );

  // Update node data from properties panel
  const handleNodeDataChange = useCallback(
    (nodeId: string, patch: Partial<AgentStepNodeData>) => {
      setNodes((nds) => {
        // If renaming, validate FIRST before any state mutation
        const target = nds.find((n) => n.id === nodeId);
        if (target && patch.stepName !== undefined) {
          const oldName = (target.data as AgentStepNodeData).stepName;
          const newName = patch.stepName;
          if (newName !== oldName) {
            if (!newName.trim()) {
              toast.error("Step name cannot be empty");
              return nds; // no change
            }
            if (nds.some((other) => other.id !== nodeId && other.id === newName)) {
              toast.error("Step name must be unique");
              return nds; // no change
            }
            // Validation passed — update node AND edges atomically
            setEdges((eds) =>
              eds.map((e) => {
                const newSource = e.source === nodeId ? newName : e.source;
                const newTarget = e.target === nodeId ? newName : e.target;
                return {
                  ...e,
                  id: `e-${newSource}-${newTarget}`,
                  source: newSource,
                  target: newTarget,
                };
              }),
            );
            return nds.map((n): ComposerNode => {
              if (n.id !== nodeId || n.type !== "agentStep") {
                return n as ComposerNode;
              }
              return {
                ...n,
                id: newName,
                data: { ...(n.data as AgentStepNodeData), ...patch },
              };
            });
          }
        }
        // Non-rename property change
        return nds.map((n): ComposerNode => {
          if (n.id !== nodeId || n.type !== "agentStep") {
            return n as ComposerNode;
          }
          return {
            ...n,
            data: { ...(n.data as AgentStepNodeData), ...patch },
          };
        });
      });
      setIsDirty(true);
    },
    [setNodes, setEdges],
  );

  // Auto-layout
  const handleAutoLayout = useCallback((dir?: LayoutDirection) => {
    const d = dir ?? layoutDirection;
    setNodes((nds) => {
      const copy = nds.map((n) => ({ ...n })) as ComposerNode[];
      autoLayout(copy, edges, d);
      return copy;
    });
    setTimeout(() => reactFlowInstance.fitView({ padding: 0.2 }), 50);
  }, [edges, setNodes, reactFlowInstance, layoutDirection]);

  // Toggle layout direction and re-layout
  const handleToggleDirection = useCallback(() => {
    setLayoutDirection((prev) => {
      const next = prev === "vertical" ? "horizontal" : "vertical";
      setCurrentDirection(next);
      handleAutoLayout(next);
      return next;
    });
  }, [handleAutoLayout]);

  // Save — context handlers already show toast.success/toast.error
  const handleSave = useCallback(async () => {
    if (!wfName.trim()) { toast.error("Workflow name is required"); return; }
    const payload = canvasToPayload(nodes as ComposerNode[], edges, wfName, wfDesc, wfInput, wfContextRef);
    if (isNew) {
      await ws.handleCreateWorkflow(payload);
    } else {
      const { name: _, ...updatePayload } = payload;
      await ws.handleUpdateWorkflow(wfName, updatePayload);
    }
    setIsDirty(false);
  }, [nodes, edges, wfName, wfDesc, wfInput, wfContextRef, isNew, ws]);

  // Run — context handlers already show toast.success/toast.error
  const handleRun = useCallback(async () => {
    if (isNew) { toast.info("Save the workflow first before running"); return; }
    if (!wfName.trim()) return;
    await ws.handleTriggerWorkflow(wfName, wfInput || undefined);
  }, [wfName, wfInput, isNew, ws]);

  // Approval actions
  const handleApproval = useCallback(async (decision: "approved" | "denied") => {
    const approvalName = workflow?.pending_approval?.name;
    if (!approvalName || !token.trim()) return;
    try {
      await decideApproval(token, namespace, approvalName, decision);
      await ws.refreshWorkspaceData({ silent: false });
      toast.success(`Workflow step ${decision}`);
    } catch (err) {
      toast.error(`Failed to ${decision === "approved" ? "approve" : "deny"}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [workflow?.pending_approval?.name, token, namespace, ws]);

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

  // Toggle maximize with fitView after animation
  const toggleMaximize = useCallback(() => {
    setIsMaximized((prev) => !prev);
    setTimeout(() => reactFlowInstance.fitView({ padding: 0.2 }), 350);
  }, [reactFlowInstance]);

  // Keep latest callbacks in refs so the keyboard listener never needs re-binding
  const handleSaveRef = useRef(handleSave);
  const handleAutoLayoutRef = useRef(handleAutoLayout);
  const toggleMaximizeRef = useRef(toggleMaximize);
  const isMaximizedRef = useRef(isMaximized);
  useEffect(() => { handleSaveRef.current = handleSave; }, [handleSave]);
  useEffect(() => { handleAutoLayoutRef.current = handleAutoLayout; }, [handleAutoLayout]);
  useEffect(() => { toggleMaximizeRef.current = toggleMaximize; }, [toggleMaximize]);
  useEffect(() => { isMaximizedRef.current = isMaximized; }, [isMaximized]);

  // Keyboard shortcuts
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const ctrl = e.ctrlKey || e.metaKey;
      // Ctrl+S → Save
      if (ctrl && e.key === "s") {
        e.preventDefault();
        void handleSaveRef.current();
      }
      // Ctrl+Shift+L → Auto-layout
      if (ctrl && e.shiftKey && e.key.toLowerCase() === "l") {
        e.preventDefault();
        handleAutoLayoutRef.current();
      }
      // F11 → Toggle maximize
      if (e.key === "F11") {
        e.preventDefault();
        toggleMaximizeRef.current();
      }
      // Escape → Exit maximize
      if (e.key === "Escape" && isMaximizedRef.current) {
        e.preventDefault();
        setIsMaximized(false);
        setTimeout(() => reactFlowInstance.fitView({ padding: 0.2 }), 350);
      }
      // Ctrl+B → Toggle palette
      if (ctrl && !e.shiftKey && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setPaletteCollapsed((prev) => !prev);
      }
      // Ctrl+J → Toggle properties
      if (ctrl && !e.shiftKey && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setPropertiesCollapsed((prev) => !prev);
      }
      // Ctrl+L → Toggle live activity panel
      if (ctrl && !e.shiftKey && e.key.toLowerCase() === "l") {
        e.preventDefault();
        setLivePanelCollapsed((prev) => !prev);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [reactFlowInstance]);

  return (
    <div className={cn(
      "flex flex-col h-full w-full",
      isMaximized && "fixed inset-0 z-50 bg-background composer-maximized",
    )}>
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
        isMaximized={isMaximized}
        summary={workflow?.summary}
        phase={workflow?.phase}
        pendingApproval={workflow?.pending_approval}
        stepsUseInput={anyStepUsesInput(
          (nodes as ComposerNode[])
            .filter((n) => n.type === "agentStep")
            .map((n) => ({ data: { prompt: (n.data as AgentStepNodeData).prompt } })),
        )}
        onNameChange={(v) => { setWfName(v); setIsDirty(true); }}
        onDescriptionChange={(v) => { setWfDesc(v); setIsDirty(true); }}
        onInputChange={(v) => { setWfInput(v); setIsDirty(true); }}
        onSave={handleSave}
        onRun={handleRun}
        onApprove={() => handleApproval("approved")}
        onDeny={() => handleApproval("denied")}
        onAutoLayout={handleAutoLayout}
        onToggleDirection={handleToggleDirection}
        layoutDirection={layoutDirection}
        onToggleMaximize={toggleMaximize}
        onBack={handleBack}
        onToggleLivePanel={() => setLivePanelCollapsed((p) => !p)}
        livePanelCollapsed={livePanelCollapsed}
        hasLiveActivity={activities.length > 0 || isActive}
      />

      <div className="flex flex-1 min-h-0 overflow-hidden">
        <NodePalette agents={agents} collapsed={paletteCollapsed} onToggleCollapse={() => setPaletteCollapsed((p) => !p)} onAddAgent={handleAddAgentFromPalette} />

        <div ref={wrapperRef} className="flex-1 relative composer-canvas-wrapper">
          {/* Empty state helper */}
          {nodes.length <= 1 && (
            <div className="composer-empty-state absolute inset-0 z-10 flex items-center justify-center pointer-events-none bg-gradient-to-br from-primary/5 via-transparent to-transparent">
              <div className="text-center space-y-4 max-w-sm px-6">
                <div className="composer-empty-state-icon">
                  <MousePointerClick className="h-7 w-7" />
                </div>
                <div className="space-y-2">
                  <p className="text-base font-semibold text-foreground">Build your workflow</p>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    Create automated processes by connecting agents. Drag agents from the left panel, or click the + button to add steps.
                  </p>
                </div>
                <div className="flex flex-col gap-2">
                  <div className="inline-flex items-center justify-center gap-4 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-2"><span className="inline-block h-1.5 w-1.5 rounded-full bg-primary/60" />Search agents</span>
                    <span className="text-border/40">•</span>
                    <span className="inline-flex items-center gap-2"><span className="inline-block h-1.5 w-1.5 rounded-full bg-primary/60" />Drag to canvas</span>
                  </div>
                  <div className="inline-flex items-center justify-center gap-4 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-2"><span className="inline-block h-1.5 w-1.5 rounded-full bg-primary/60" />Connect steps</span>
                    <span className="text-border/40">•</span>
                    <span className="inline-flex items-center gap-2"><span className="inline-block h-1.5 w-1.5 rounded-full bg-primary/60" />Auto-arrange</span>
                  </div>
                </div>
              </div>
            </div>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edgesWithData}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onSelectionChange={onSelectionChange}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onNodesDelete={onNodesDelete}
            isValidConnection={isValidConnection}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            snapToGrid
            snapGrid={[20, 20]}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            deleteKeyCode={["Backspace", "Delete"]}
            connectionLineStyle={{ stroke: "oklch(0.65 0.13 175)", strokeWidth: 2, strokeDasharray: "6 3" }}
            className="composer-canvas"
          >
            <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="var(--color-border)" />
            <Controls className="!bg-card !border-border !shadow-md !rounded-lg" />
            <MiniMap
              className="!bg-card/70 !border-border !rounded-xl !shadow-lg"
              style={{ width: 160, height: 100 }}
              nodeColor={(n) => {
                if (n.type === "trigger") return "oklch(0.65 0.13 175)";
                const state = (n.data as AgentStepNodeData)?.stepState?.status;
                if (state === "completed") return "#22c55e";
                if (state === "running") return "#eab308";
                if (state === "continued") return "#f59e0b";
                if (state === "waiting_approval") return "#f97316";
                if (state === "failed") return "#ef4444";
                if (state === "denied") return "#ef4444";
                if (state === "cancelled") return "#fb923c";
                return "oklch(0.65 0.015 274)";
              }}
              maskColor="oklch(0.145 0.008 274 / 0.7)"
            />
            {/* Custom arrow markers */}
            <svg style={SVG_DEFS_STYLE}>
              <defs>
                <marker
                  id="dependency-arrow"
                  viewBox="0 0 14 14"
                  refX="12"
                  refY="7"
                  markerWidth="10"
                  markerHeight="10"
                  orient="auto-start-reverse"
                >
                  <path
                    d="M 1 2 L 11 7 L 1 12 Q 3.5 7 1 2"
                    fill="oklch(0.50 0.04 264)"
                    stroke="oklch(0.50 0.04 264)"
                    strokeWidth="0.5"
                    strokeLinejoin="round"
                  />
                </marker>
              </defs>
            </svg>
          </ReactFlow>
        </div>

        <PropertiesPanel
          selectedNode={selectedNode}
          agents={agents}
          edges={edges}
          nodes={nodes as ComposerNode[]}
          collapsed={propertiesCollapsed}
          onToggleCollapse={() => setPropertiesCollapsed((p) => !p)}
          onNodeDataChange={handleNodeDataChange}
          onSelectNode={handleSelectNodeFromPanel}
          onDeleteNode={(nodeId) => {
            setNodes((nds) => nds.filter((n) => n.id !== nodeId));
            setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
            setSelectedNodeId(null);
            setIsDirty(true);
          }}
        />

        {/* Live Activity Panel */}
        {!livePanelCollapsed && workflow?.name && (
          <div className="w-96 border-l bg-background shrink-0 flex flex-col">
            {/* Live run summary */}
            <div className="px-3 py-2 border-b shrink-0 bg-muted/20">
              <div className="flex items-center gap-2 text-[10px]">
                <div className={cn(
                  "h-1.5 w-1.5 rounded-full shrink-0",
                  isActive ? "bg-emerald-500 animate-pulse" : isConnected ? "bg-sky-500" : "bg-red-500",
                )} />
                <span className="font-semibold text-foreground">{workflow.name}</span>
                {livePhase && (
                  <Badge variant="outline" className="text-[9px] h-4 px-1">{livePhase}</Badge>
                )}
              </div>
              <div className="flex items-center gap-2 mt-1 text-[9px] text-muted-foreground">
                {isActive && activeStepName && (
                  <span>Current: {activeStepName}</span>
                )}
                <span>{activities.length} events</span>
                {toolActivityCount > 0 && <span>{toolActivityCount} tools</span>}
                {warningCount > 0 && <span className="text-amber-400">{warningCount} warnings</span>}
                {errorCount > 0 && <span className="text-red-400">{errorCount} errors</span>}
              </div>
            </div>
            <LiveActivityStream
              workflowName={workflow.name}
              activities={activities}
              isConnected={isConnected}
              isActive={isActive}
              phase={livePhase}
              error={liveError}
              onReconnect={liveReconnect}
            />
          </div>
        )}
      </div>

      {/* Bottom panels — Files above Runs */}
      {!isNew && (
        <div className="border-t border-border/40 bg-background/60 shrink-0 max-h-[45vh] overflow-hidden flex flex-col">
          {/* Workspace File Browser */}
          {selectedNode?.data && "agentRef" in (selectedNode.data as object) && (
            <div className={cn("shrink-0", filesCollapsed ? "" : "flex-1 min-h-0 overflow-hidden border-b border-border/20")}>
              <WorkspaceFileBrowser
                agentName={String((selectedNode.data as Record<string, unknown>).agentRef ?? "")}
                collapsed={filesCollapsed}
                onToggle={() => setFilesCollapsed((p) => !p)}
              />
            </div>
          )}

          {/* Run History */}
          <div className={cn("shrink-0", runHistoryCollapsed ? "" : "flex-1 min-h-0 overflow-hidden")}>
            <RunHistoryPanel
              workflowName={wfName}
              collapsed={runHistoryCollapsed}
              onToggle={() => setRunHistoryCollapsed((p) => !p)}
              expanded={runHistoryExpanded}
              onExpandedChange={setRunHistoryExpanded}
            />
          </div>
        </div>
      )}
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
