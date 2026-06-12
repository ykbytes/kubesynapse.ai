import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Save,
  Play,
  ArrowLeft,
  LayoutGrid,
  Circle,
  CheckCircle2,
  LoaderCircle,
  Hash,
  Maximize2,
  Minimize2,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Radio,
  ArrowDownUp,
  ArrowLeftRight,
} from "lucide-react";
import { ExpandableMarkdownEditor } from "@/components/shared/ExpandableMarkdownEditor";
import { cn } from "@/lib/utils";

import type { WorkflowSummary, WorkflowPendingApproval } from "@/types";
import type { LayoutDirection } from "@/lib/composer-utils";

interface ComposerToolbarProps {
  workflowName: string;
  description: string;
  input: string;
  isNew: boolean;
  isDirty: boolean;
  isSaving: boolean;
  isRunning: boolean;
  summary?: WorkflowSummary | null;
  phase?: string;
  pendingApproval?: WorkflowPendingApproval | null;
  stepsUseInput?: boolean;
  onApprove?: () => void;
  onDeny?: () => void;
  onNameChange: (name: string) => void;
  onDescriptionChange: (desc: string) => void;
  onInputChange: (input: string) => void;
  onSave: () => void;
  onRun: () => void;
  isMaximized: boolean;
  onAutoLayout: () => void;
  onToggleDirection: () => void;
  layoutDirection: LayoutDirection;
  onToggleMaximize: () => void;
  onBack: () => void;
  onToggleLivePanel?: () => void;
  livePanelCollapsed?: boolean;
  hasLiveActivity?: boolean;
}

export function ComposerToolbar({
  workflowName,
  description,
  input,
  isNew,
  isDirty,
  isSaving,
  isRunning,
  summary,
  phase,
  pendingApproval,
  stepsUseInput,
  onApprove,
  onDeny,
  onNameChange,
  onDescriptionChange,
  onInputChange,
  isMaximized,
  onSave,
  onRun,
  onAutoLayout,
  onToggleDirection,
  layoutDirection,
  onToggleMaximize,
  onBack,
  onToggleLivePanel,
  livePanelCollapsed = true,
  hasLiveActivity = false,
}: ComposerToolbarProps) {
  const [inputExpanded, setInputExpanded] = useState(false);
  const [editorDialogOpen, setEditorDialogOpen] = useState(false);
  const hasStepProgress =
    summary && summary.totalSteps != null && summary.totalSteps > 0;

  return (
    <div className="composer-toolbar border-b bg-background shrink-0">
      {/* Main toolbar row */}
      <div className="flex items-center gap-3 px-3 py-2.5 flex-wrap">
        {/* Left: back + name + desc */}
        <div className="flex items-center gap-3 shrink-0">
          <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0 cursor-pointer transition-all hover:bg-muted" onClick={onBack} title="Back to workflows (Esc)">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex flex-col gap-0.5 min-w-0">
            <Input
              value={workflowName}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder="Workflow name"
              className="h-6 text-sm font-semibold w-40 sm:w-52 border-transparent bg-transparent hover:border-border/50 focus:border-primary/50 focus:bg-muted/20 px-2 rounded transition-all"
              disabled={!isNew}
            />
            <Input
              value={description}
              onChange={(e) => onDescriptionChange(e.target.value)}
              placeholder="Description"
              className="h-5 text-xs text-muted-foreground w-40 sm:w-52 border-transparent bg-transparent hover:border-border/50 focus:border-primary/50 focus:bg-muted/20 px-2 rounded transition-all hidden sm:block"
            />
          </div>
        </div>

        {/* Center: workflow input */}
        <div className="flex-1 min-w-0 space-y-1 order-last sm:order-none w-full sm:w-auto px-2 py-1.5 rounded-lg bg-muted/10 border border-border/20">
          <div className="flex items-center gap-2">
            <Label className="text-xs text-muted-foreground uppercase tracking-wider font-semibold hidden sm:block">Input</Label>
            <button
              type="button"
              className="flex items-center gap-1 text-xs text-muted-foreground/60 hover:text-muted-foreground transition-colors cursor-pointer hidden sm:flex"
              onClick={() => setInputExpanded(!inputExpanded)}
              title={inputExpanded ? "Collapse to single line" : "Expand inline"}
            >
              {inputExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>
          </div>
          {inputExpanded ? (
            <ExpandableMarkdownEditor
              value={input}
              onChange={onInputChange}
              placeholder="Enter prompt or input data… (supports Markdown)"
              rows={4}
              compact
              textareaClassName="text-xs"
              dialogTitle="Workflow Input"
              dialogDescription="Define the initial prompt or data payload passed to step prompts as {{input}}."
            />
          ) : (
            <div className="relative group flex gap-1">
              <Input
                value={input}
                onChange={(e) => onInputChange(e.target.value)}
                placeholder="Enter prompt or input data…"
                className="h-7 text-xs flex-1"
              />
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity cursor-pointer"
                onClick={() => setEditorDialogOpen(true)}
                title="Open full markdown editor"
              >
                <Maximize2 className="h-3 w-3" />
              </Button>
              <ExpandableMarkdownEditor
                value={input}
                onChange={onInputChange}
                placeholder="Enter prompt or input data… (supports Markdown)"
                dialogTitle="Workflow Input"
                dialogDescription="Define the initial prompt or data payload passed to step prompts as {{input}}."
                open={editorDialogOpen}
                onOpenChange={setEditorDialogOpen}
              />
            </div>
          )}
          <div className="flex items-center gap-2 hidden sm:flex">
            <span className="text-[8px] text-muted-foreground/50 font-mono">
              Referenced in step prompts as <code className="text-primary/60">{`{{input}}`}</code>
            </span>
            {stepsUseInput && !input.trim() && (
              <TooltipProvider delayDuration={200}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="flex items-center gap-0.5 text-[8px] text-amber-400">
                      <AlertTriangle className="h-2.5 w-2.5" /> empty
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="text-xs max-w-48">
                    One or more steps reference <code className="font-mono">{`{{input}}`}</code> but the workflow input is empty
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        </div>

        {/* Right: indicators + actions */}
        <div className="flex items-center gap-1.5 shrink-0 ml-auto">
          {isDirty && (
            <span className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-amber-500 bg-amber-500/10 border border-amber-500/20 rounded-lg font-medium" title="Unsaved changes">
              <Circle className="h-2 w-2 fill-current animate-pulse" /> Unsaved
            </span>
          )}

          {/* Layout controls group */}
          <div className="flex items-center gap-0.5 px-1.5 py-1 rounded-lg bg-muted/20 border border-border/40">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs gap-1.5 px-2 cursor-pointer transition-all hover:bg-primary/10 hover:text-primary"
              onClick={onAutoLayout}
              title="Auto-arrange all nodes (Ctrl+Shift+L)"
            >
              <LayoutGrid className="h-3.5 w-3.5" />
              <span className="hidden md:inline">Layout</span>
            </Button>
            <Button
              variant={layoutDirection === "horizontal" ? "secondary" : "ghost"}
              size="icon"
              className="h-7 w-7 cursor-pointer transition-all"
              onClick={onToggleDirection}
              title={layoutDirection === "vertical" ? "Switch to horizontal layout" : "Switch to vertical layout"}
            >
              {layoutDirection === "vertical"
                ? <ArrowDownUp className="h-3.5 w-3.5" />
                : <ArrowLeftRight className="h-3.5 w-3.5" />}
            </Button>
          </div>

          {/* Activity & display controls */}
          <div className="flex items-center gap-0.5 px-1.5 py-1 rounded-lg bg-muted/20 border border-border/40">
            {onToggleLivePanel && (
              <Button
                variant={livePanelCollapsed ? "ghost" : "secondary"}
                size="icon"
                className={cn(
                  "h-7 w-7 shrink-0 cursor-pointer relative transition-all",
                  !livePanelCollapsed && "bg-sky-500/15 text-sky-400 border-sky-500/30 hover:bg-sky-500/20",
                )}
                onClick={onToggleLivePanel}
                title={livePanelCollapsed ? "Show live activity (Ctrl+L)" : "Hide live activity (Ctrl+L)"}
              >
                <Radio className="h-3.5 w-3.5" />
                {hasLiveActivity && livePanelCollapsed && (
                  <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-emerald-500 animate-pulse border-2 border-background" />
                )}
              </Button>
            )}

            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0 cursor-pointer transition-all hover:bg-muted"
              onClick={onToggleMaximize}
              title={isMaximized ? "Exit fullscreen (Esc)" : "Maximize composer (F11)"}
            >
              {isMaximized ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            </Button>
          </div>

          {/* Primary actions */}
          <div className="flex items-center gap-1.5 px-1.5 py-1 rounded-lg bg-muted/20 border border-border/40 ml-auto">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs gap-1.5 px-3 cursor-pointer transition-all hover:bg-amber-500/10 hover:text-amber-500 hover:border-amber-500/30"
              onClick={onSave}
              disabled={isSaving || !workflowName.trim()}
              title={!workflowName.trim() ? "Enter a workflow name first" : "Save workflow (Ctrl+S)"}
            >
              <Save className="h-3.5 w-3.5" /> <span className="hidden sm:inline">{isSaving ? "Saving…" : "Save"}</span>
            </Button>

            <Button
              variant="default"
              size="sm"
              className="h-7 text-xs gap-1.5 px-3 cursor-pointer transition-all"
              onClick={onRun}
              disabled={isRunning || !workflowName.trim() || isNew || isDirty}
              title={isNew ? "Save the workflow first" : isDirty ? "Save changes before running" : "Trigger workflow run"}
            >
              <Play className="h-3.5 w-3.5" /> <span className="hidden sm:inline">{isRunning ? "Running…" : "Run"}</span>
            </Button>
          </div>
        </div>
      </div>

      {/* Status bar (only shown when workflow has execution data) */}
      {(phase || hasStepProgress) && (
        <div className="flex items-center gap-3 px-3 py-2 border-t border-border/40 bg-gradient-to-r from-muted/30 via-muted/20 to-muted/30 text-xs text-muted-foreground">
          {phase && (
            <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-background/40 border border-border/40">
              {phase === "running" ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin text-amber-400" />
              ) : phase === "completed" ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
              ) : null}
              <span className="font-semibold text-foreground capitalize">{phase}</span>
            </div>
          )}
          {summary?.runId && (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-background/40 border border-border/40 font-mono text-xs">
              <Hash className="h-3 w-3 shrink-0" />
              {summary.runId.slice(0, 12)}
            </span>
          )}
          {hasStepProgress && (
            <div className="flex-1 flex items-center gap-2">
              <Badge variant="outline" className="text-xs h-5 px-2 bg-background/40 border-border/40">
                {(summary.completedSteps ?? 0)}/{summary.totalSteps} steps
              </Badge>
              <div className="flex-1 max-w-xs flex items-center gap-2">
                <div className="h-1.5 flex-1 rounded-full bg-muted/40 border border-border/40 overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all duration-500",
                      phase === "completed" ? "bg-emerald-500" : (summary.failedSteps ?? 0) > 0 ? "bg-red-500" : "bg-primary",
                      phase === "running" && "animate-pulse",
                    )}
                    style={{ width: `${Math.round(((summary.completedSteps ?? 0) / (summary.totalSteps ?? 1)) * 100)}%` }}
                  />
                </div>
                <span className="text-xs font-mono tabular-nums w-7 text-right">
                  {Math.round(((summary.completedSteps ?? 0) / (summary.totalSteps ?? 1)) * 100)}%
                </span>
              </div>
            </div>
          )}
          {pendingApproval && (
            <div className="flex items-center gap-2 ml-auto px-2.5 py-1.5 rounded-lg bg-orange-500/10 border border-orange-500/20">
              <span className="text-orange-400 font-semibold text-xs">Approval: {pendingApproval.stepName}</span>
              <Button variant="outline" size="sm" className="h-5 text-xs px-2.5 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/10 cursor-pointer" onClick={onApprove}>
                Approve
              </Button>
              <Button variant="outline" size="sm" className="h-5 text-xs px-2.5 text-red-400 border-red-500/30 hover:bg-red-500/10 cursor-pointer" onClick={onDeny}>
                Deny
              </Button>
            </div>
          )}
          {!pendingApproval && summary?.queuedAt && (
            <span className="ml-auto font-mono">
              queued {new Date(summary.queuedAt).toLocaleTimeString()}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
