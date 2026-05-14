import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import { AlertTriangle, Bot, MessageSquare, PanelRightOpen, RefreshCw } from "lucide-react";
import React, { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Toaster } from "sonner";
import { SkipToContent } from "./components/SkipToContent";
import { AriaLiveRegion } from "./components/AriaLiveRegion";

const LandingPage = lazy(() => import("./components/LandingPage").then((m) => ({ default: m.LandingPage })));

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
const PolicyEditor = lazy(() => import("./components/PolicyEditor").then((m) => ({ default: m.PolicyEditor })));
const CatalogPanel = lazy(() => import("./components/CatalogPanel").then((m) => ({ default: m.CatalogPanel })));
import { AgentInspectorDrawer, ResourceInspectorDrawer } from "./components/InspectorDrawer";
const SettingsPanel = lazy(() => import("./components/SettingsPanel").then((m) => ({ default: m.SettingsPanel })));
const TopBar = lazy(() => import("./components/TopBar").then((m) => ({ default: m.TopBar })));
const CommandPalette = lazy(() => import("./components/CommandPalette").then((m) => ({ default: m.CommandPalette })));
const MobileNav = lazy(() => import("./components/MobileNav").then((m) => ({ default: m.MobileNav })));
const WorkflowManager = lazy(() => import("./components/WorkflowManager").then((m) => ({ default: m.WorkflowManager })));
const IntelligencePanel = lazy(() => import("./components/IntelligencePanel").then((m) => ({ default: m.IntelligencePanel })));
const DocumentationPanel = lazy(() => import("./components/DocumentationPanel").then((m) => ({ default: m.DocumentationPanel })));
const EventTriggersPanel = lazy(() => import("./components/EventTriggersPanel").then((m) => ({ default: m.EventTriggersPanel })));
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/EmptyState";

const WorkflowComposer = lazy(() =>
  import("./components/WorkflowComposer").then((m) => ({ default: m.WorkflowComposer })),
);

import { ConnectionProvider, useConnection } from "./contexts/ConnectionContext";
import { WorkspaceProvider, useWorkspace } from "./contexts/WorkspaceContext";
import { ChatProvider, useChat } from "./contexts/ChatContext";
import { ThemeProvider } from "./contexts/ThemeContext";
import { NotificationProvider } from "./contexts/NotificationContext";

import type { UiMessage, WorkflowInfo, WorkspaceView } from "./types";
import { cloneAgent, downloadAgentArtifact, downloadAgentArtifactZip, exportBundleUrl, importBundle, listAgentArtifacts, previewAgentArtifact } from "./lib/api";
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

function supportsInspector(view: WorkspaceView): boolean {
  return view === "agents" || view === "chat" || view === "workflows" || view === "composer";
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
  return <Suspense fallback={<div className="h-full w-full border-r border-border bg-background" />}>{children}</Suspense>;
}

function ContentShell({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<LoadingPanel />}>{children}</Suspense>;
}

// ── ErrorBoundary — catches lazy-load and render failures ──

interface ErrorBoundaryState { hasError: boolean; error: Error | null }

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-4 bg-background p-8 text-center">
          <div className="rounded-2xl bg-red-500/10 p-4 border border-red-500/20">
            <AlertTriangle className="h-8 w-8 text-red-400" />
          </div>
          <h2 className="text-lg font-semibold text-foreground">Something went wrong</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            {this.state.error?.message || "An unexpected error occurred while loading the application."}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="inline-flex items-center gap-2 rounded-xl border border-border/60 bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            <RefreshCw className="h-4 w-4" />
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── App — Provider shell ──

export default function App() {
  return (
    <ErrorBoundary>
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
    </ErrorBoundary>
  );
}

// ── AppLayout — thin orchestration + JSX ──

function AppLayout() {
  const conn = useConnection();
  const ws = useWorkspace();
  const chat = useChat();
  const [templateWizardOpen, setTemplateWizardOpen] = useState(false);
  const [sidebarDeleteTarget, setSidebarDeleteTarget] = useState<{ id: string; view: WorkspaceView } | null>(null);
  const [showAuth, setShowAuth] = useState(false);
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

  const handleOpenChatView = useCallback((agentName?: string) => {
    const nextAgentName = agentName || ws.selectedAgentName || ws.agents[0]?.name || "";
    ws.navigateToResource("chat", nextAgentName);
  }, [ws]);

  const handleWorkspaceViewChange = useCallback((view: WorkspaceView) => {
    if (view === "chat") {
      handleOpenChatView();
      return;
    }
    if (view === "catalog") {
      ws.setCatalogTab("mcp");
    }
    if (view === "intelligence") {
      ws.setIntelligenceTab("observatory");
    }
    ws.setActiveView(view);
  }, [handleOpenChatView, ws]);

  const handleListSelectedAgentArtifacts = useCallback(async () => {
    if (!ws.selectedAgentName) {
      return { files: [], truncated: false, roots: [] };
    }
    return listAgentArtifacts(conn.token, conn.namespace, ws.selectedAgentName);
  }, [conn.namespace, conn.token, ws.selectedAgentName]);

  const handlePreviewSelectedAgentArtifact = useCallback(async (path: string) => {
    if (!ws.selectedAgentName) {
      throw new Error("Select an agent before previewing files.");
    }
    return previewAgentArtifact(conn.token, conn.namespace, ws.selectedAgentName, path);
  }, [conn.namespace, conn.token, ws.selectedAgentName]);

  const handleDownloadSelectedAgentArtifact = useCallback(async (path: string, filename?: string) => {
    if (!ws.selectedAgentName) {
      throw new Error("Select an agent before downloading files.");
    }
    await downloadAgentArtifact(conn.token, conn.namespace, ws.selectedAgentName, path, filename);
  }, [conn.namespace, conn.token, ws.selectedAgentName]);

  const handleDownloadSelectedAgentWorkspaceZip = useCallback(async () => {
    if (!ws.selectedAgentName) {
      throw new Error("Select an agent before downloading the workspace.");
    }
    await downloadAgentArtifactZip(conn.token, conn.namespace, ws.selectedAgentName);
  }, [conn.namespace, conn.token, ws.selectedAgentName]);

  // Gate: show loading spinner while auth initializes
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

  // Unauthenticated: show Landing Page or Auth Page
  if (!conn.currentUser) {
    if (showAuth) {
      return (
        <Suspense fallback={<LoadingPanel />}>
          <AuthPage onBack={() => setShowAuth(false)} />
        </Suspense>
      );
    }
    return (
      <Suspense fallback={<LoadingPanel />}>
        <LandingPage onLogin={() => setShowAuth(true)} showLogin={true} />
      </Suspense>
    );
  }

  // Cross-cutting: sidebar delete
  async function handleSidebarDeleteConfirm() {
    if (!sidebarDeleteTarget) return;
    const { id, view } = sidebarDeleteTarget;
    setSidebarDeleteTarget(null);
    try {
      if (view === "agents" || view === "chat") {
        // Select the agent first so handleDeleteAgent knows which one
        ws.handleSelectResource(id);
        const deletedName = await ws.handleDeleteAgent();
        if (deletedName) chat.removeAgentChatState(deletedName);
      } else if (view === "workflows" || view === "composer") {
        await ws.handleDeleteWorkflow(id);
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
        handleOpenChatView(created.name);
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
  const displayError = ws.workspaceError || conn.connectionError || conn.gatewayError;
  const pageHeader =
    ws.activeView === "agents"
      ? {
          title: "Agents",
          description: "Create agents, tune runtime behavior, and manage attached capabilities.",
        }
      : ws.activeView === "chat"
        ? {
            title: "Chat",
            description: "Use the dedicated conversation workspace for sessions, files, memory, and run details.",
          }
        : ws.activeView === "workflows" || ws.activeView === "composer"
          ? {
              title: "Workflows",
              description: "Design orchestration paths, inspect runs, and manage approval gates.",
            }
          : ws.activeView === "catalog"
            ? {
                title: "Catalog",
                description: "Browse reusable skills and manage MCP integrations from one catalog workspace.",
              }
            : ws.activeView === "policies"
              ? {
                  title: "Policies",
                  description: "Manage model access, guardrails, and runtime control policies.",
                }
              : ws.activeView === "intelligence"
                ? {
                    title: "Intelligence",
                    description: "Collect cluster intelligence and inspect execution traces from one observability workspace.",
                  }
                  : ws.activeView === "settings"
                  ? {
                      title: "Settings",
                      description: "Manage providers, model routes, and workspace defaults.",
                    }
                  : ws.activeView === "admin"
                    ? {
                        title: "Admin",
                        description: "Inspect users, audit activity, usage, and platform health.",
                      }
                      : ws.activeView === "docs"
                        ? {
                            title: "Documentation",
                            description: "Learn how to deploy, operate, and extend kubesynapse.",
                          }
                        : {
                            title: "Webhooks & Triggers",
                            description: "Configure webhook receivers and event-driven workflow triggers.",
                          };
  const showCompactPageHeader = ws.activeView !== "composer" && !(ws.activeView === "chat" && ws.selectedAgentName);
  const mainContentClasses = ws.activeView === "composer"
    ? "flex flex-1 flex-col overflow-hidden pb-20 md:pb-0"
    : ws.activeView === "chat" && ws.selectedAgentName
      ? "flex flex-1 overflow-hidden pb-20 md:pb-0"
      : "flex min-w-0 flex-1 flex-col gap-2 overflow-auto p-2 pb-20 sm:p-3 md:pb-0";

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <SkipToContent />
      <AriaLiveRegion />
      {/* ── TopBar ── */}
      <Suspense fallback={<div className="h-10 border-b border-border bg-background" />}>
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
        <div
          className={`hidden shrink-0 overflow-hidden transition-[width] duration-200 ease-productive md:flex ${ws.sidebarCollapsed
            ? "md:w-12"
            : "md:w-[clamp(10.5rem,14vw,13rem)] xl:w-[clamp(11rem,15vw,14rem)]"}`}
        >
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
              onViewChange={handleWorkspaceViewChange}
              onRefresh={() => void ws.refreshWorkspaceData({ silent: false })}
              onSelect={ws.handleSelectResource}
              onCreateNew={ws.handleCreateNew}
              onQuickRun={
                ws.activeView === "agents"
                  ? (id) => { ws.handleSelectResource(id); handleOpenChatView(id); }
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
                ws.activeView === "agents" || ws.activeView === "chat" || ws.activeView === "workflows" || ws.activeView === "composer"
                  ? handleSidebarDeleteRequest
                    : undefined
              }
            />
          </SidebarShell>
        </div>

        {/* ── Main content ── */}
        <main id="main-content" className={mainContentClasses} tabIndex={-1}>
          {showCompactPageHeader && (
            <div className="flex min-w-0 items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="break-words text-sm font-semibold leading-tight text-foreground">{pageHeader.title}</h2>
              </div>
              {inspectorSupported ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 shrink-0 gap-1.5"
                  onClick={() => ws.setInspectorOpen(true)}
                >
                  <PanelRightOpen className="h-4 w-4" />
                  Inspector
                </Button>
              ) : null}
            </div>
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
                    namespace={conn.namespace}
                    isEmptyWorkspace={ws.agents.length === 0}
                    name={ws.createAgentName}
                    model={ws.createAgentModel}
                    systemPrompt={ws.createAgentSystemPrompt}
                    runtimeKind={ws.createAgentRuntimeKind}
                    mcpConnectionIds={ws.createAgentMcpConnectionIds}
                    mcpServersText={ws.createAgentMcpServersText}
                    mcpSidecarsText={ws.createAgentMcpSidecarsText}
                    a2aAllowedCallersText={ws.createAgentA2AAllowedCallersText}
                    agents={ws.agents}
                    workflows={ws.workflows}
                    skillFileDrafts={ws.createAgentSkillFileDrafts}
                    opencodeConfigFileDrafts={ws.createAgentOpenCodeConfigFileDrafts}
                    isCreating={ws.isCreatingAgent}
                    error={ws.createError}
                    onMcpConnectionIdsChange={ws.setCreateAgentMcpConnectionIds}
                    onMcpServersTextChange={ws.setCreateAgentMcpServersText}
                    onMcpSidecarsTextChange={ws.setCreateAgentMcpSidecarsText}
                    onNameChange={ws.setCreateAgentName}
                    onModelChange={ws.setCreateAgentModel}
                    onSystemPromptChange={ws.setCreateAgentSystemPrompt}
                    onA2AAllowedCallersTextChange={ws.setCreateAgentA2AAllowedCallersText}
                    onSkillFileDraftsChange={ws.setCreateAgentSkillFileDrafts}
                    onOpenCodeConfigFileDraftsChange={ws.setCreateAgentOpenCodeConfigFileDrafts}
                    onRuntimeKindChange={ws.setCreateAgentRuntimeKind}
                    gitForm={ws.createAgentGitForm}
                    onGitFormChange={ws.setCreateAgentGitForm}
                    onCreate={() => void handleCreateAgentFull()}
                  />
                </ContentShell>
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col gap-4">
                <div className="min-h-0 flex-1 overflow-auto">
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
                        onSave={(payload, a2aText, skills, opencodeFiles) => void ws.handleSaveAgent(payload, a2aText, skills, opencodeFiles)}
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
                        onInjectPrompt={(text) => { chat.setPrompt(text); handleOpenChatView(ws.selectedAgentName); }}
                      />
                    </ContentShell>
                  ) : (
                    <div className="flex flex-1 items-center justify-center">
                      <p className="text-sm text-muted-foreground">Loading the selected agent settings...</p>
                    </div>
                  )}
                </div>
              </div>
            )
          ) : ws.activeView === "chat" ? (
            ws.agents.length === 0 ? (
              <div className="flex flex-1 items-center justify-center rounded-3xl border border-dashed border-border/70 bg-card/30">
                <EmptyState
                  icon={MessageSquare}
                  title="Chat needs an agent"
                  description={conn.canMutate ? "Create an agent in the management view, then return here for a roomier conversation workspace." : "Ask an admin to provision an agent, then select it from the sidebar to start chatting."}
                  action={conn.canMutate ? { label: "Create Agent", onClick: ws.handleCreateNew } : undefined}
                />
              </div>
            ) : !ws.selectedAgentName ? (
              <div className="flex flex-1 items-center justify-center rounded-3xl border border-dashed border-border/70 bg-card/30">
                <EmptyState
                  icon={Bot}
                  title="Select an agent"
                  description="Choose an agent from the sidebar to open the full chat workspace."
                />
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 min-w-0 flex-col overflow-hidden">
                  <div className="flex min-h-0 flex-1 min-w-0 flex-col gap-0 overflow-hidden lg:flex-row">
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

                  <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-none border border-border/70 bg-card/55 shadow-[0_18px_48px_-28px_rgba(15,23,42,0.45)] lg:flex-row">
                    <ContentShell>
                      <ChatWorkbench
                        agentName={ws.selectedAgentName}
                        runtimeKind={ws.selectedRuntimeKind}
                        prompt={chat.prompt}
                        messages={chat.messages}
                        activity={chat.activity}
                        todos={chat.todos}
                        phase={chat.phase}
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
                        agents={ws.agents}
                        discoveryPeers={ws.discoverablePeers}
                        discoveryLoading={ws.discoveryLoading}
                        discoveryError={ws.discoveryError}
                        emptyMessage={chat.chatEmptyMessage}
                        error={chat.chatError}
                        onPromptChange={chat.setPrompt}
                        onToggleStreamMode={chat.setStreamMode}
                        onToggleRequireApproval={chat.setRequireApproval}
                        onA2ATargetAgentChange={(v) => { chat.setChatError(""); chat.setA2ATargetAgent(v); }}
                        onA2ATargetNamespaceChange={(v) => { chat.setChatError(""); chat.setA2ATargetNamespace(v); }}
                        onA2ATimeoutSecondsChange={(v) => { chat.setChatError(""); chat.setA2ATimeoutSeconds(v); }}
                        opencodeOutputFormat={chat.selectedOpenCodeChatSettings.outputFormat}
                        opencodeAutonomous={chat.selectedOpenCodeChatSettings.autonomous}
                        opencodeMaxTurns={chat.selectedOpenCodeChatSettings.maxTurns}
                        opencodeWorkingDirectory={chat.selectedOpenCodeChatSettings.workingDirectory}
                        factoryMode={chat.selectedFactoryMode}
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
                        onDownloadArtifact={handleDownloadSelectedAgentArtifact}
                        onDownloadArtifactZip={handleDownloadSelectedAgentWorkspaceZip}
                        onListArtifacts={handleListSelectedAgentArtifacts}
                        onPreviewArtifact={handlePreviewSelectedAgentArtifact}
                        onOpenCodeOutputFormatChange={chat.setOpenCodeOutputFormat}
                        onOpenCodeAutonomousChange={chat.setOpenCodeAutonomous}
                        onOpenCodeMaxTurnsChange={chat.setOpenCodeMaxTurns}
                        onOpenCodeWorkingDirectoryChange={chat.setOpenCodeWorkingDirectory}
                        onFactoryModeChange={chat.setSelectedFactoryMode}
                        onSaveSession={() => void chat.handleSaveCurrentSession()}
                        canSubmit={chat.canSubmitChat}
                        onSubmit={(atts) => void chat.handleSubmit(atts)}
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
                        discoverablePeers={ws.discoverablePeers}
                      />
                    </ContentShell>
                  </div>
                </div>
              </div>
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
                onTrigger={(name, input, factoryMode) => void ws.handleTriggerWorkflow(name, input, factoryMode)}
                onCancel={(name) => void ws.handleCancelWorkflow(name)}
                isCancelling={ws.cancellingWorkflow}
                onRetryFailed={(name) => void ws.handleRetryFailedSteps(name)}
                isRetrying={ws.retryingWorkflow}
                factoryMode={ws.selectedFactoryWorkflowMode}
                onFactoryModeChange={ws.setSelectedFactoryWorkflowMode}
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
              <CatalogPanel
                token={conn.token}
                namespace={conn.namespace}
                activeTab={ws.catalogTab}
                onTabChange={ws.setCatalogTab}
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
              />
            </ContentShell>
          ) : ws.activeView === "policies" ? (
            <ContentShell>
              <PolicyEditor selectedPolicyName={ws.sidebarSelectedId || null} />
            </ContentShell>
          ) : ws.activeView === "intelligence" ? (
            <ContentShell>
              <IntelligencePanel activeTab={ws.intelligenceTab} onTabChange={ws.setIntelligenceTab} />
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
          ) : ws.activeView === "docs" ? (
            <ContentShell>
              <DocumentationPanel />
            </ContentShell>
          ) : ws.activeView === "webhooks" ? (
            <ContentShell>
              <Suspense fallback={<div className="h-screen" />}>
                <EventTriggersPanel />
              </Suspense>
            </ContentShell>
          ) : null}
        </main>
      </div>

      {/* ── Inspector drawers ── */}
      {ws.activeView === "agents" || ws.activeView === "chat" ? (
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
      ) : null}

      <Suspense fallback={null}>
        <MobileNav
          activeView={ws.activeView}
          onViewChange={handleWorkspaceViewChange}
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
              onViewChange={handleWorkspaceViewChange}
              onRefresh={() => void ws.refreshWorkspaceData({ silent: false })}
              onSelect={ws.handleSelectResource}
              onCreateNew={ws.handleCreateNew}
              onDeleteItem={
                ws.activeView === "agents" || ws.activeView === "chat" || ws.activeView === "workflows" || ws.activeView === "composer"
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
          onNavigate={handleWorkspaceViewChange}
          onCreateAgent={() => { ws.setActiveView("agents"); ws.setAgentCreateMode(true); }}
          onCreateWorkflow={() => { ws.setActiveView("workflows"); ws.setWorkflowCreateMode(true); }}
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
