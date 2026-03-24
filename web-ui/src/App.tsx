import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/700.css";

import { PanelLeftClose, PanelLeftOpen, PanelRightOpen } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Toaster } from "sonner";

const AgentManagementPanel = lazy(() => import("./components/AgentManagementPanel").then((m) => ({ default: m.AgentManagementPanel })));
const AdminPanel = lazy(() => import("./components/AdminPanel").then((m) => ({ default: m.AdminPanel })));
const HealthDashboard = lazy(() => import("./components/HealthDashboard").then((m) => ({ default: m.HealthDashboard })));
const AuditLogPanel = lazy(() => import("./components/AuditLogPanel").then((m) => ({ default: m.AuditLogPanel })));
const UsageDashboard = lazy(() => import("./components/UsageDashboard"));
const AgentTemplateWizard = lazy(() => import("./components/AgentTemplateWizard").then((m) => ({ default: m.AgentTemplateWizard })));
const OnboardingTour = lazy(() => import("./components/OnboardingTour").then((m) => ({ default: m.OnboardingTour })));
const AppSidebar = lazy(() => import("./components/AppSidebar").then((m) => ({ default: m.AppSidebar })));
const AuthPage = lazy(() => import("./components/AuthPage").then((m) => ({ default: m.AuthPage })));
const ChatSessionPanel = lazy(() => import("./components/ChatSessionPanel").then((m) => ({ default: m.ChatSessionPanel })));
const ChatWorkbench = lazy(() => import("./components/ChatWorkbench").then((m) => ({ default: m.ChatWorkbench })));
const TeamView = lazy(() => import("./components/TeamView").then((m) => ({ default: m.TeamView })));
const CreateAgentPanel = lazy(() => import("./components/CreateAgentPanel").then((m) => ({ default: m.CreateAgentPanel })));
const ConfirmDialog = lazy(() => import("./components/ConfirmDialog").then((m) => ({ default: m.ConfirmDialog })));
const EvalManager = lazy(() => import("./components/EvalManager").then((m) => ({ default: m.EvalManager })));
const PolicyEditor = lazy(() => import("./components/PolicyEditor").then((m) => ({ default: m.PolicyEditor })));
import { AgentInspectorDrawer, ResourceInspectorDrawer } from "./components/InspectorDrawer";
const SettingsPanel = lazy(() => import("./components/SettingsPanel").then((m) => ({ default: m.SettingsPanel })));
const SkillsCatalogPanel = lazy(() => import("./components/SkillsCatalogPanel").then((m) => ({ default: m.SkillsCatalogPanel })));
const TopBar = lazy(() => import("./components/TopBar").then((m) => ({ default: m.TopBar })));
const CommandPalette = lazy(() => import("./components/CommandPalette").then((m) => ({ default: m.CommandPalette })));
const MobileNav = lazy(() => import("./components/MobileNav").then((m) => ({ default: m.MobileNav })));
const WorkflowManager = lazy(() => import("./components/WorkflowManager").then((m) => ({ default: m.WorkflowManager })));
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const WorkflowComposer = lazy(() =>
  import("./components/WorkflowComposer").then((m) => ({ default: m.WorkflowComposer })),
);

import { ConnectionProvider, useConnection } from "./contexts/ConnectionContext";
import { WorkspaceProvider, useWorkspace } from "./contexts/WorkspaceContext";
import { ChatProvider, useChat } from "./contexts/ChatContext";
import { ThemeProvider } from "./contexts/ThemeContext";
import { NotificationProvider } from "./contexts/NotificationContext";

import type { EvalInfo, UiMessage, WorkflowInfo, WorkspaceView } from "./types";
import { cloneAgent, downloadAgentArtifact, exportBundleUrl, importBundle, listAgentArtifacts } from "./lib/api";
import { toast } from "sonner";

// ── Pure utility functions ──

function createId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

function workflowSpecFromResource(resource: WorkflowInfo | null): Record<string, unknown> | null {
  if (!resource) return null;
  return { description: resource.description, input: resource.input, message_bus: resource.message_bus, steps: resource.steps };
}

function workflowStatusFromResource(resource: WorkflowInfo | null): Record<string, unknown> | null {
  if (!resource) return null;
  return {
    phase: resource.phase, current_step: resource.current_step, observed_generation: resource.observed_generation,
    pending_approval: resource.pending_approval, artifact_ref: resource.artifact_ref,
    worker_job: resource.worker_job, created_at: resource.created_at,
  };
}

function evalSpecFromResource(resource: EvalInfo | null): Record<string, unknown> | null {
  if (!resource) return null;
  return { agent_ref: resource.agent_ref, schedule: resource.schedule, test_suite: resource.test_suite, failure_threshold: resource.failure_threshold };
}

function evalStatusFromResource(resource: EvalInfo | null): Record<string, unknown> | null {
  if (!resource) return null;
  return {
    phase: resource.phase, passed: resource.passed, last_run: resource.last_run,
    observed_generation: resource.observed_generation, artifact_ref: resource.artifact_ref,
    worker_job: resource.worker_job, created_at: resource.created_at,
  };
}

function supportsInspector(view: WorkspaceView): boolean {
  return view === "agents" || view === "workflows" || view === "composer" || view === "evals";
}

// ── NotificationShell — NotificationProvider needs Connection values ──

function NotificationShell({ children }: { children: React.ReactNode }) {
  const { token, namespace } = useConnection();
  return (
    <NotificationProvider token={token} namespace={namespace}>
      {children}
    </NotificationProvider>
  );
}

function LoadingPanel() {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="flex flex-col items-center gap-3 animate-fade-in">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading workspace...</p>
      </div>
    </div>
  );
}

function SidebarShell({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<div className="w-16 border-r border-border bg-background" />}>{children}</Suspense>;
}

function ContentShell({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<LoadingPanel />}>{children}</Suspense>;
}

// ── App — Provider shell ──

export default function App() {
  return (
    <ThemeProvider>
      <ConnectionProvider>
        <WorkspaceProvider>
          <ChatProvider>
            <NotificationShell>
              <AppLayout />
            </NotificationShell>
          </ChatProvider>
        </WorkspaceProvider>
      </ConnectionProvider>
    </ThemeProvider>
  );
}

// ── AppLayout — thin orchestration + JSX ──

function AppLayout() {
  const conn = useConnection();
  const ws = useWorkspace();
  const chat = useChat();
  const [templateWizardOpen, setTemplateWizardOpen] = useState(false);
  const [sidebarDeleteTarget, setSidebarDeleteTarget] = useState<{ id: string; view: WorkspaceView } | null>(null);
  const inspectorSupported = supportsInspector(ws.activeView);

  // ⚠️  All hooks must be declared BEFORE any conditional returns (Rules of Hooks)
  useEffect(() => {
    if (!inspectorSupported && ws.inspectorOpen) {
      ws.setInspectorOpen(false);
    }
  }, [inspectorSupported, ws.inspectorOpen, ws.setInspectorOpen]);

  const handleSidebarDeleteRequest = useCallback((id: string) => {
    setSidebarDeleteTarget({ id, view: ws.activeView });
  }, [ws.activeView]);

  // Gate: show loading spinner while auth initializes, then AuthPage if not authenticated
  if (!conn.authReady) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3 animate-fade-in">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Initializing...</p>
        </div>
      </div>
    );
  }

  if (!conn.currentUser) {
    return (
      <Suspense fallback={<LoadingPanel />}>
        <AuthPage />
      </Suspense>
    );
  }

  // Cross-cutting: sidebar delete
  async function handleSidebarDeleteConfirm() {
    if (!sidebarDeleteTarget) return;
    const { id, view } = sidebarDeleteTarget;
    setSidebarDeleteTarget(null);
    try {
      if (view === "agents") {
        // Select the agent first so handleDeleteAgent knows which one
        ws.handleSelectResource(id);
        const deletedName = await ws.handleDeleteAgent();
        if (deletedName) chat.removeAgentChatState(deletedName);
      } else if (view === "workflows" || view === "composer") {
        await ws.handleDeleteWorkflow(id);
      } else if (view === "evals") {
        await ws.handleDeleteEval(id);
      }
    } catch (err) {
      ws.setWorkspaceError(err instanceof Error ? err.message : String(err));
    }
  }

  // Cross-cutting: create agent → init chat message
  async function handleCreateAgentFull() {
    try {
      const created = await ws.handleCreateAgent();
      if (created) {
        chat.setMessagesForAgent(created.name, (current: UiMessage[]) =>
          current.length > 0
            ? current
            : [{ id: createId(), role: "system" as const, content: "Agent created. Wait until the runtime status turns running, then start chatting.", status: "complete" as const }],
        );
      }
    } catch (err) {
      ws.setWorkspaceError(err instanceof Error ? err.message : String(err));
    }
  }

  // Cross-cutting: delete agent → clear chat state
  async function handleDeleteAgentFull() {
    try {
      const deletedName = await ws.handleDeleteAgent();
      if (deletedName) chat.removeAgentChatState(deletedName);
    } catch (err) {
      ws.setWorkspaceError(err instanceof Error ? err.message : String(err));
    }
  }

  // Derived display values
  const gatewayStatus = conn.gatewayError ? "offline" : conn.health?.status ?? "loading";

  const heroTitle =
    ws.activeView === "agents"
      ? ws.selectedAgent
        ? `${ws.selectedAgent.name} is ready for chat and management.`
        : ws.agentCreateMode
          ? "Create and provision a new agent."
          : "Connect, create, and manage your agents."
      : ws.activeView === "workflows" || ws.activeView === "composer"
        ? ws.selectedWorkflow
          ? `${ws.selectedWorkflow.name} workflow orchestration.`
          : ws.workflowCreateMode || ws.workflows.length === 0
            ? "Create a workflow and let the operator queue it."
            : "Select a workflow to inspect it."
        : ws.activeView === "catalog"
          ? "Browse pre-built skills and MCP tool sidecars."
          : ws.activeView === "settings"
            ? "Manage LLM providers, model routes, and API keys."
            : ws.selectedEval
            ? `${ws.selectedEval.name} evaluation suite.`
            : ws.evalCreateMode || ws.evals.length === 0
              ? "Create an evaluation suite and let the operator run it."
              : "Select an evaluation to inspect it.";

  const selectedResourceStatus =
    ws.activeView === "agents"
      ? ws.selectedAgent?.status ?? (ws.agentCreateMode ? "draft" : "none")
      : ws.activeView === "workflows" || ws.activeView === "composer"
        ? ws.selectedWorkflow?.phase ?? (ws.workflowCreateMode ? "draft" : "none")
        : ws.activeView === "catalog"
          ? "browse"
          : ws.activeView === "settings"
            ? "config"
            : ws.selectedEval?.phase ?? (ws.evalCreateMode ? "draft" : "none");

  const displayError = ws.workspaceError || conn.connectionError || conn.gatewayError;

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* ── TopBar ── */}
      <Suspense fallback={<div className="h-14 border-b border-border bg-background" />}>
        <TopBar
          health={conn.health}
          gatewayError={conn.gatewayError}
          token={conn.token}
          namespace={conn.namespace}
          isConnecting={conn.isConnecting}
          authConfig={conn.authConfig}
          currentUser={conn.currentUser}
          authBusy={conn.authBusy}
          authUsername={conn.authUsername}
          authPassword={conn.authPassword}
          authEmail={conn.authEmail}
          authDisplayName={conn.authDisplayName}
          authPasswordConfirm={conn.authPasswordConfirm}
          passwordProvider={conn.passwordProvider}
          registerMode={conn.registerMode}
          onTokenChange={conn.setToken}
          onNamespaceChange={conn.setNamespace}
          onAuthUsernameChange={conn.setAuthUsername}
          onAuthPasswordChange={conn.setAuthPassword}
          onAuthEmailChange={conn.setAuthEmail}
          onAuthDisplayNameChange={conn.setAuthDisplayName}
          onAuthPasswordConfirmChange={conn.setAuthPasswordConfirm}
          onPasswordProviderChange={conn.setPasswordProvider}
          onRegisterModeChange={conn.setRegisterMode}
          connectionError={conn.connectionError}
          onClearConnectionError={() => conn.setConnectionError("")}
          onConnect={() => conn.handleConnect()}
          onPasswordSubmit={() => conn.handlePasswordAuth()}
          onStartOidc={conn.handleOidcStart}
          onStartSaml={conn.handleSamlStart}
          onLogout={() => void conn.handleLogout()}
          onRefreshCurrentUser={async () => { await conn.refreshCurrentUserProfile(); }}
        />
      </Suspense>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Sidebar ── */}
        <div className="hidden md:flex">
          <SidebarShell>
            <AppSidebar
              collapsed={ws.sidebarCollapsed}
              onToggleCollapse={() => ws.setSidebarCollapsed((prev) => !prev)}
              activeView={ws.activeView}
              counts={ws.sidebarCounts}
              items={ws.sidebarItems}
              selectedId={ws.sidebarSelectedId}
              loading={ws.catalogLoading}
              emptyMessage={ws.emptySidebarMessage}
              isAdmin={conn.isAdmin}
              onViewChange={ws.setActiveView}
              onRefresh={() => void ws.refreshWorkspaceData({ silent: false })}
              onSelect={ws.handleSelectResource}
              onCreateNew={ws.handleCreateNew}
              onQuickRun={
                ws.activeView === "agents"
                  ? (id) => { ws.handleSelectResource(id); ws.setAgentViewTab("chat"); }
                  : ws.activeView === "workflows" || ws.activeView === "composer"
                    ? (id) => {
                        ws.handleSelectResource(id);
                        const wf = ws.workflows.find((w) => w.name === id);
                        if (wf) void ws.handleTriggerWorkflow(wf.name);
                      }
                    : undefined
              }
              quickRunLabel={
                ws.activeView === "agents"
                  ? "Chat with"
                  : ws.activeView === "workflows" || ws.activeView === "composer"
                    ? "Trigger"
                    : undefined
              }
              onDeleteItem={
                ws.activeView === "agents" || ws.activeView === "workflows" || ws.activeView === "composer" || ws.activeView === "evals"
                  ? handleSidebarDeleteRequest
                  : undefined
              }
            />
          </SidebarShell>
        </div>

        {/* ── Main content ── */}
        <main className={`flex flex-1 flex-col pb-16 md:pb-0 ${ws.activeView === "composer" ? "overflow-hidden" : "p-4 gap-4"} ${ws.activeView === "agents" && ws.selectedAgentName && !ws.agentCreateMode ? "overflow-hidden" : "overflow-auto"}`}>
          {ws.activeView !== "composer" && (
            <>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Workspace Status</p>
                  <h2 className="text-lg font-semibold text-foreground">{heroTitle}</h2>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={() => ws.setInspectorOpen(true)}
                  disabled={!inspectorSupported}
                  title={inspectorSupported ? undefined : "Inspector is available for agents, workflows, composer, and evaluations."}
                >
                  <PanelRightOpen className="h-4 w-4" />
                  Inspector
                </Button>
              </div>

              <div className="flex flex-wrap gap-2 text-xs">
                <span className="rounded-md border border-border bg-card px-3 py-1.5">
                  Gateway: <strong className="text-foreground">{gatewayStatus}</strong>
                </span>
                <span className="rounded-md border border-border bg-card px-3 py-1.5">
                  Auth: <strong className="text-foreground">{conn.health?.auth_mode ?? "unknown"}</strong>
                </span>
                <span className="rounded-md border border-border bg-card px-3 py-1.5">
                  View: <strong className="text-foreground">{ws.activeView}</strong>
                </span>
                <span className="rounded-md border border-border bg-card px-3 py-1.5">
                  Selected: <strong className="text-foreground">{selectedResourceStatus}</strong>
                </span>
              </div>
            </>
          )}

          {displayError && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
              {displayError}
            </div>
          )}

          {ws.activeView === "agents" ? (
            ws.agentCreateMode || (!ws.selectedAgentName && ws.agents.length === 0) ? (
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs gap-1 cursor-pointer"
                    onClick={() => setTemplateWizardOpen(true)}
                  >
                    <span className="text-primary">✦</span> From Template
                  </Button>
                </div>
                <ContentShell>
                  <CreateAgentPanel
                    token={conn.token}
                    isEmptyWorkspace={ws.agents.length === 0}
                    name={ws.createAgentName}
                    model={ws.createAgentModel}
                    systemPrompt={ws.createAgentSystemPrompt}
                    runtimeKind={ws.createAgentRuntimeKind}
                    mcpServersText={ws.createAgentMcpServersText}
                    mcpSidecarsText={ws.createAgentMcpSidecarsText}
                    a2aAllowedCallersText={ws.createAgentA2AAllowedCallersText}
                    agents={ws.agents}
                    workflows={ws.workflows}
                    skillFileDrafts={ws.createAgentSkillFileDrafts}
                    gooseConfigFileDrafts={ws.createAgentGooseConfigFileDrafts}
                    opencodeConfigFileDrafts={ws.createAgentOpenCodeConfigFileDrafts}
                    isCreating={ws.isCreatingAgent}
                    error={ws.createError}
                    onMcpServersTextChange={ws.setCreateAgentMcpServersText}
                    onMcpSidecarsTextChange={ws.setCreateAgentMcpSidecarsText}
                    onNameChange={ws.setCreateAgentName}
                    onModelChange={ws.setCreateAgentModel}
                    onSystemPromptChange={ws.setCreateAgentSystemPrompt}
                    onRuntimeKindChange={ws.setCreateAgentRuntimeKind}
                    onA2AAllowedCallersTextChange={ws.setCreateAgentA2AAllowedCallersText}
                    onSkillFileDraftsChange={ws.setCreateAgentSkillFileDrafts}
                    onGooseConfigFileDraftsChange={ws.setCreateAgentGooseConfigFileDrafts}
                    onOpenCodeConfigFileDraftsChange={ws.setCreateAgentOpenCodeConfigFileDrafts}
                    gitForm={ws.createAgentGitForm}
                    onGitFormChange={ws.setCreateAgentGitForm}
                    githubForm={ws.createAgentGitHubForm}
                    onGitHubFormChange={ws.setCreateAgentGitHubForm}
                    onCreate={() => void handleCreateAgentFull()}
                  />
                </ContentShell>
              </div>
            ) : (
              <>
                {ws.selectedAgentName && (
                  <div className="mb-2 flex gap-1 2xl:hidden">
                    <Button
                      variant={ws.agentViewTab === "config" ? "secondary" : "ghost"}
                      size="sm" className="h-7 text-xs"
                      onClick={() => ws.setAgentViewTab("config")}
                    >Config</Button>
                    <Button
                      variant={ws.agentViewTab === "chat" ? "secondary" : "ghost"}
                      size="sm" className="h-7 text-xs"
                      onClick={() => ws.setAgentViewTab("chat")}
                    >Chat</Button>
                  </div>
                )}

                <div className="flex min-h-0 flex-1 min-w-0 gap-0 overflow-hidden">
                  <div className={`${ws.selectedAgentName ? "hidden 2xl:flex" : "flex"} ${ws.agentViewTab === "config" ? "flex" : "hidden 2xl:flex"} ${ws.configPanelCollapsed ? "2xl:hidden" : "w-full 2xl:max-w-[48rem] 2xl:basis-[44%]"} min-w-0 flex-col overflow-auto`}>
                    {ws.selectedAgentDetail ? (
                      <ContentShell>
                        <AgentManagementPanel
                          token={conn.token}
                          agent={ws.selectedAgentDetail}
                          policies={ws.policies}
                          agents={ws.agents}
                          workflows={ws.workflows}
                          isSaving={ws.savingAgent}
                          isDeleting={ws.deletingAgent}
                          error={ws.agentManageError}
                          onSave={(payload, a2aText, skills, gooseFiles, opencodeFiles) => void ws.handleSaveAgent(payload, a2aText, skills, gooseFiles, opencodeFiles)}
                          onDelete={() => void handleDeleteAgentFull()}
                          onClone={async () => {
                            try {
                              await cloneAgent(conn.token, conn.namespace, ws.selectedAgentDetail!.name);
                              toast.success(`Cloned "${ws.selectedAgentDetail!.name}"`);
                              void ws.refreshWorkspaceData({ silent: true });
                            } catch (err) {
                              toast.error(err instanceof Error ? err.message : "Clone failed");
                            }
                          }}
                        />
                      </ContentShell>
                    ) : (
                      <div className="flex flex-1 items-center justify-center">
                        <p className="text-sm text-muted-foreground">Loading the selected agent settings...</p>
                      </div>
                    )}
                  </div>

                  {ws.selectedAgentName && (
                    <div className={`${ws.agentViewTab === "chat" ? "flex" : "hidden 2xl:flex"} w-full min-w-0 ${ws.configPanelCollapsed ? "2xl:w-full" : "2xl:flex-1"} flex-row min-h-0`}>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="hidden 2xl:flex h-full w-6 shrink-0 rounded-none border-r border-border hover:bg-muted/50 items-center justify-center"
                        onClick={() => ws.setConfigPanelCollapsed(!ws.configPanelCollapsed)}
                        title={ws.configPanelCollapsed ? "Show agent config" : "Hide agent config"}
                      >
                        {ws.configPanelCollapsed ? <PanelLeftOpen className="h-3.5 w-3.5" /> : <PanelLeftClose className="h-3.5 w-3.5" />}
                      </Button>
                      <ContentShell>
                        <ChatSessionPanel
                          sessions={chat.chatSessions}
                          activeSessionId={chat.activeSessionId}
                          loading={chat.sessionsLoading}
                          search={chat.sessionSearch}
                          onSearchChange={chat.setSessionSearch}
                          sessionDirty={chat.sessionDirty}
                          sessionSaving={chat.sessionSaving}
                          lastSessionSaveAt={chat.lastSessionSaveAt}
                          onNewSession={() => void chat.handleNewSession()}
                          onLoadSession={(id) => void chat.handleLoadSession(id)}
                          onDeleteSession={(id) => void chat.handleDeleteSession(id)}
                          onRenameSession={(id, title) => void chat.handleRenameSession(id, title)}
                          onSaveCurrent={() => void chat.handleSaveCurrentSession()}
                        />
                      </ContentShell>
                      <ContentShell>
                        <ChatWorkbench
                          agentName={ws.selectedAgentName}
                          runtimeKind={ws.selectedRuntimeKind}
                          prompt={chat.prompt}
                          messages={chat.messages}
                          activity={chat.activity}
                          isSending={chat.isSending}
                          tokenReady={Boolean(conn.token.trim())}
                          streamMode={chat.streamMode}
                          requireApproval={chat.requireApproval}
                          approvalSupported={chat.approvalSupported}
                          a2aTargetAgent={chat.a2aTargetAgent}
                          a2aTargetNamespace={chat.a2aTargetNamespace}
                          a2aTimeoutSeconds={chat.a2aTimeoutSeconds}
                          specialistSubagents={chat.specialistSubagents}
                          specialistTeamConfigured={chat.specialistTeamConfigured}
                          subagentStrategy={chat.subagentStrategy}
                          discoveryPeers={ws.discoverablePeers}
                          discoveryLoading={ws.discoveryLoading}
                          discoveryError={ws.discoveryError}
                          gooseMaxTurns={chat.selectedGooseChatSettings.maxTurns}
                          gooseWorkingDirectory={chat.selectedGooseChatSettings.workingDirectory}
                          gooseSystemPrompt={chat.gooseSystemPromptPreview}
                          emptyMessage={chat.chatEmptyMessage}
                          error={chat.chatError}
                          onPromptChange={chat.setPrompt}
                          onToggleStreamMode={chat.setStreamMode}
                          onToggleRequireApproval={chat.setRequireApproval}
                          onA2ATargetAgentChange={(v) => { chat.setChatError(""); chat.setA2ATargetAgent(v); }}
                          onA2ATargetNamespaceChange={(v) => { chat.setChatError(""); chat.setA2ATargetNamespace(v); }}
                          onA2ATimeoutSecondsChange={(v) => { chat.setChatError(""); chat.setA2ATimeoutSeconds(v); }}
                          onSubagentStrategyChange={(v) => { chat.setChatError(""); chat.setSubagentStrategy(v); }}
                          onAddSpecialistSubagent={chat.addSpecialistSubagent}
                          onUpdateSpecialistSubagent={(id, patch) => chat.updateSpecialistSubagent(id, patch)}
                          onRemoveSpecialistSubagent={(id) => chat.removeSpecialistSubagent(id)}
                          onClearSpecialistTeam={chat.clearSpecialistTeam}
                          onGooseMaxTurnsChange={chat.setGooseMaxTurns}
                          onGooseWorkingDirectoryChange={chat.setGooseWorkingDirectory}
                          opencodeOutputFormat={chat.selectedOpenCodeChatSettings.outputFormat}
                          opencodeAutonomous={chat.selectedOpenCodeChatSettings.autonomous}
                          opencodeMaxTurns={chat.selectedOpenCodeChatSettings.maxTurns}
                          opencodeWorkingDirectory={chat.selectedOpenCodeChatSettings.workingDirectory}
                          summary={chat.summary}
                          activeSessionId={chat.activeSessionId}
                          sessionDirty={chat.sessionDirty}
                          sessionSaving={chat.sessionSaving}
                          lastSessionSaveAt={chat.lastSessionSaveAt}
                          activeSessionSummary={chat.activeSessionSummary}
                          activeMemoryRecords={chat.activeMemoryRecords}
                          agentMemoryRecords={chat.agentMemoryRecords}
                          onPromoteMemoryRecord={(recordId, promoted) => void chat.handlePromoteMemoryRecord(recordId, promoted)}
                          onEditMemoryRecord={(recordId, patch) => void chat.handleEditMemoryRecord(recordId, patch)}
                          onDeleteMemoryRecord={(recordId) => void chat.handleDeleteMemoryRecord(recordId)}
                          onDownloadArtifact={(path, filename) => downloadAgentArtifact(conn.token, conn.namespace, ws.selectedAgentName, path, filename)}
                          onListArtifacts={() => listAgentArtifacts(conn.token, conn.namespace, ws.selectedAgentName)}
                          onOpenCodeOutputFormatChange={chat.setOpenCodeOutputFormat}
                          onOpenCodeAutonomousChange={chat.setOpenCodeAutonomous}
                          onOpenCodeMaxTurnsChange={chat.setOpenCodeMaxTurns}
                          onOpenCodeWorkingDirectoryChange={chat.setOpenCodeWorkingDirectory}
                          onSaveSession={() => void chat.handleSaveCurrentSession()}
                          canSubmit={chat.canSubmitChat}
                          onSubmit={() => void chat.handleSubmit()}
                          onCancel={chat.cancelStream}
                        />
                      </ContentShell>
                      <ContentShell>
                        <TeamView
                          specialistSubagents={chat.specialistSubagents}
                          specialistTeamConfigured={chat.specialistTeamConfigured}
                          subagentStrategy={chat.subagentStrategy}
                          summary={chat.summary}
                          isSending={chat.isSending}
                          activity={chat.activity}
                        />
                      </ContentShell>
                    </div>
                  )}
                </div>
              </>
            )
          ) : ws.activeView === "workflows" ? (
            <ContentShell>
              <WorkflowManager
                workflow={ws.workflowCreateMode || ws.workflows.length === 0 ? null : ws.selectedWorkflow}
                agents={ws.agents}
                isSaving={ws.savingWorkflow}
                isDeleting={ws.deletingWorkflow}
                isRunning={ws.runningWorkflow}
                error={ws.workflowError}
                onCreate={(payload) => void ws.handleCreateWorkflow(payload)}
                onUpdate={(name, payload) => void ws.handleUpdateWorkflow(name, payload)}
                onDelete={(name) => void ws.handleDeleteWorkflow(name)}
                onTrigger={(name, input) => void ws.handleTriggerWorkflow(name, input)}
                onCancel={(name) => void ws.handleCancelWorkflow(name)}
                isCancelling={ws.cancellingWorkflow}
                approvalReason={chat.approvalReason}
                approvalBusy={chat.approvalBusy}
                onApprovalReasonChange={chat.setApprovalReason}
                onApprovalDecision={(decision) => void chat.handleWorkflowApprovalDecision(decision)}
                onOpenComposer={() => ws.setActiveView("composer")}
              />
            </ContentShell>
          ) : ws.activeView === "composer" ? (
            <Suspense fallback={
              <div className="flex flex-1 items-center justify-center">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            }>
              <WorkflowComposer />
            </Suspense>
          ) : ws.activeView === "catalog" ? (
            <ContentShell>
              <SkillsCatalogPanel
                token={conn.token}
                onAttachSkill={(_skillId, files) => {
                  const newDrafts = Object.entries(files).map(([path, content]) => ({
                    id: createId(),
                    path,
                    content,
                  }));
                  ws.setCreateAgentSkillFileDrafts([...ws.createAgentSkillFileDrafts, ...newDrafts]);
                  ws.setAgentCreateMode(true);
                  ws.setActiveView("agents");
                  toast.success("Skill files added to the new agent form");
                }}
                onAttachTool={(toolId) => {
                  const prev = ws.createAgentMcpSidecarsText.trim();
                  ws.setCreateAgentMcpSidecarsText(prev ? `${prev}, ${toolId}` : toolId);
                  ws.setAgentCreateMode(true);
                  ws.setActiveView("agents");
                  toast.success(`MCP sidecar "${toolId}" added to the new agent form`);
                }}
              />
            </ContentShell>
          ) : ws.activeView === "policies" ? (
            <ContentShell>
              <PolicyEditor selectedPolicyName={ws.sidebarSelectedId || null} />
            </ContentShell>
          ) : ws.activeView === "settings" ? (
            <ContentShell>
              <SettingsPanel token={conn.token} isAdmin={conn.isAdmin} />
            </ContentShell>
          ) : ws.activeView === "admin" ? (
              <Tabs defaultValue="users" className="flex flex-col h-full">
                <TabsList className="mx-4 mt-2 shrink-0 w-fit">
                <TabsTrigger value="users" className="text-xs cursor-pointer">Users</TabsTrigger>
                <TabsTrigger value="audit" className="text-xs cursor-pointer">Audit Log</TabsTrigger>
                <TabsTrigger value="usage" className="text-xs cursor-pointer">Usage & Cost</TabsTrigger>
                <TabsTrigger value="health" className="text-xs cursor-pointer">Health</TabsTrigger>
                </TabsList>
                <TabsContent value="users" className="flex-1 min-h-0 mt-0">
                  <ContentShell>
                    <AdminPanel token={conn.token} />
                  </ContentShell>
                </TabsContent>
                <TabsContent value="audit" className="flex-1 min-h-0 mt-0">
                  <ContentShell>
                    <AuditLogPanel />
                  </ContentShell>
                </TabsContent>
                <TabsContent value="usage" className="flex-1 min-h-0 mt-0 overflow-y-auto">
                  <ContentShell>
                    <UsageDashboard />
                  </ContentShell>
                </TabsContent>
                <TabsContent value="health" className="flex-1 min-h-0 mt-0 overflow-y-auto">
                  <ContentShell>
                    <HealthDashboard />
                  </ContentShell>
                </TabsContent>
              </Tabs>
          ) : (
            <ContentShell>
              <EvalManager
                evalResource={ws.evalCreateMode || ws.evals.length === 0 ? null : ws.selectedEval}
                agents={ws.agents}
                isSaving={ws.savingEval}
                isDeleting={ws.deletingEval}
                error={ws.evalError}
                onCreate={(payload) => void ws.handleCreateEval(payload)}
                onUpdate={(name, payload) => void ws.handleUpdateEval(name, payload)}
                onDelete={(name) => void ws.handleDeleteEval(name)}
              />
            </ContentShell>
          )}
        </main>
      </div>

      {/* ── Inspector drawers ── */}
      {ws.activeView === "agents" ? (
        <AgentInspectorDrawer
          open={ws.inspectorOpen}
          onOpenChange={ws.setInspectorOpen}
          health={conn.health}
          gatewayError={conn.gatewayError}
          workspaceError={ws.workspaceError}
          selectedAgentName={ws.selectedAgentName}
          selectedAgentDetail={ws.selectedAgentDetail}
          discoverablePeers={ws.discoverablePeers}
          discoveryLoading={ws.discoveryLoading}
          discoveryError={ws.discoveryError}
          namespace={conn.namespace}
          logs={chat.logs}
          logsLoading={chat.logsLoading}
          logsStreaming={chat.logsStreaming}
          activity={chat.activity}
          summary={chat.summary}
          approvalReason={chat.approvalReason}
          approvalBusy={chat.approvalBusy}
          onApprovalReasonChange={chat.setApprovalReason}
          onApprove={() => void chat.handleAgentApprovalDecision("approved")}
          onDeny={() => void chat.handleAgentApprovalDecision("denied")}
          onLoadLogs={() => void chat.handleLoadLogs()}
          onStreamLogs={() => chat.handleStreamLogs()}
          onStopLogStream={() => chat.handleStopLogStream()}
        />
      ) : ws.activeView === "workflows" || ws.activeView === "composer" ? (
        <ResourceInspectorDrawer
          open={ws.inspectorOpen}
          onOpenChange={ws.setInspectorOpen}
          title="Workflow Inspector"
          selectedName={ws.selectedWorkflow?.name ?? ""}
          status={ws.selectedWorkflow?.phase ?? (ws.workflowCreateMode ? "draft" : "none")}
          summary={ws.selectedWorkflow?.summary as Record<string, unknown> | null | undefined}
          spec={workflowSpecFromResource(ws.selectedWorkflow)}
          details={workflowStatusFromResource(ws.selectedWorkflow)}
          emptyMessage="Select a workflow or create a new one."
          pendingApprovalName={chat.selectedWorkflowApprovalName}
          approvalReason={chat.approvalReason}
          approvalBusy={chat.approvalBusy}
          onApprovalReasonChange={chat.setApprovalReason}
          onApprove={() => void chat.handleWorkflowApprovalDecision("approved")}
          onDeny={() => void chat.handleWorkflowApprovalDecision("denied")}
        />
      ) : ws.activeView === "evals" ? (
        <ResourceInspectorDrawer
          open={ws.inspectorOpen}
          onOpenChange={ws.setInspectorOpen}
          title="Evaluation Inspector"
          selectedName={ws.selectedEval?.name ?? ""}
          status={ws.selectedEval?.phase ?? (ws.evalCreateMode ? "draft" : "none")}
          summary={ws.selectedEval?.summary}
          spec={evalSpecFromResource(ws.selectedEval)}
          details={evalStatusFromResource(ws.selectedEval)}
          emptyMessage="Select an evaluation or create a new one."
        />
      ) : null}

      <Suspense fallback={null}>
        <MobileNav
          activeView={ws.activeView}
          onViewChange={ws.setActiveView}
          sidebarContent={
            <AppSidebar
              collapsed={false}
              onToggleCollapse={() => {}}
              activeView={ws.activeView}
              counts={ws.sidebarCounts}
              items={ws.sidebarItems}
              selectedId={ws.sidebarSelectedId}
              loading={ws.catalogLoading}
              emptyMessage={ws.emptySidebarMessage}
              isAdmin={conn.isAdmin}
              onViewChange={ws.setActiveView}
              onRefresh={() => void ws.refreshWorkspaceData({ silent: false })}
              onSelect={ws.handleSelectResource}
              onCreateNew={ws.handleCreateNew}
              onDeleteItem={
                ws.activeView === "agents" || ws.activeView === "workflows" || ws.activeView === "composer" || ws.activeView === "evals"
                  ? handleSidebarDeleteRequest
                  : undefined
              }
            />
          }
        />
      </Suspense>

      <Toaster position="bottom-right" theme="dark" richColors />
      <Suspense fallback={null}>
        <CommandPalette
          onNavigate={ws.setActiveView}
          onCreateAgent={() => { ws.setActiveView("agents"); ws.setAgentCreateMode(true); }}
          onCreateWorkflow={() => { ws.setActiveView("workflows"); ws.setWorkflowCreateMode(true); }}
          onCreateEval={() => { ws.setActiveView("evals"); ws.setEvalCreateMode(true); }}
          onExportBundle={() => {
            const url = exportBundleUrl(conn.token, conn.namespace);
            window.open(url, "_blank");
          }}
          onImportBundle={() => {
            const input = document.createElement("input");
            input.type = "file";
            input.accept = ".yaml,.yml";
            input.onchange = async () => {
              const file = input.files?.[0];
              if (!file) return;
              const text = await file.text();
              try {
                const result = await importBundle(conn.token, conn.namespace, text);
                toast.success(`Imported ${result.imported} resource(s)`);
                void ws.refreshWorkspaceData({ silent: true });
              } catch (err) {
                toast.error(err instanceof Error ? err.message : "Import failed");
              }
            };
            input.click();
          }}
        />
        <AgentTemplateWizard open={templateWizardOpen} onOpenChange={setTemplateWizardOpen} />
        <ConfirmDialog
          open={sidebarDeleteTarget !== null}
          onOpenChange={(open) => { if (!open) setSidebarDeleteTarget(null); }}
          title={`Delete ${sidebarDeleteTarget?.id ?? ""}?`}
          description="This will permanently remove this resource and cannot be undone."
          confirmLabel="Delete"
          variant="destructive"
          onConfirm={() => void handleSidebarDeleteConfirm()}
        />
        <OnboardingTour />
      </Suspense>
    </div>
  );
}
