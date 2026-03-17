import {
  type ComposerNode,
  type AgentStepNodeData,
  TRIGGER_NODE_ID,
} from "@/lib/composer-utils";
import type { AgentInfo } from "@/types";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { UserCheck, Repeat, MousePointerClick } from "lucide-react";

interface PropertiesPanelProps {
  selectedNode: ComposerNode | null;
  agents: AgentInfo[];
  onNodeDataChange: (nodeId: string, patch: Partial<AgentStepNodeData>) => void;
}

export function PropertiesPanel({ selectedNode, agents, onNodeDataChange }: PropertiesPanelProps) {
  if (!selectedNode || selectedNode.id === TRIGGER_NODE_ID) {
    return (
      <div className="w-64 border-l bg-muted/30 flex flex-col items-center justify-center p-4 shrink-0 gap-2">
        <MousePointerClick className="h-6 w-6 text-muted-foreground/40" />
        <p className="text-xs text-muted-foreground text-center">
          Click a step node on the canvas to edit its properties
        </p>
      </div>
    );
  }

  const d = selectedNode.data as AgentStepNodeData;

  return (
    <div className="w-64 border-l bg-muted/30 flex flex-col overflow-hidden shrink-0">
      <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b">
        Step Properties
      </div>
      <ScrollArea className="flex-1">
        <div className="p-3 space-y-3">
          {/* Step Name */}
          <div className="space-y-1">
            <Label className="text-[10px]">Step Name</Label>
            <Input
              value={d.stepName}
              onChange={(e) => onNodeDataChange(selectedNode.id, { stepName: e.target.value })}
              className="h-7 text-xs"
            />
          </div>

          {/* Agent */}
          <div className="space-y-1">
            <Label className="text-[10px]">Agent</Label>
            <Select
              value={d.agentRef}
              onValueChange={(v) => onNodeDataChange(selectedNode.id, { agentRef: v })}
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue placeholder="Select agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((a) => (
                  <SelectItem key={a.name} value={a.name}>
                    {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Prompt */}
          <div className="space-y-1">
            <Label className="text-[10px]">Prompt</Label>
            <Textarea
              value={d.prompt}
              onChange={(e) => onNodeDataChange(selectedNode.id, { prompt: e.target.value })}
              className="text-xs min-h-[60px]"
              rows={3}
            />
          </div>

          {/* Require Approval toggle */}
          <Button
            variant={d.requireApproval ? "secondary" : "outline"}
            size="sm"
            className="h-7 text-xs gap-1.5 w-full justify-start"
            onClick={() => onNodeDataChange(selectedNode.id, { requireApproval: !d.requireApproval })}
          >
            <UserCheck className="h-3 w-3" />
            {d.requireApproval ? "Approval Required" : "No Approval"}
          </Button>

          {/* Step Type */}
          <div className="space-y-1">
            <Label className="text-[10px]">Step Type</Label>
            <Select
              value={d.stepType}
              onValueChange={(v) =>
                onNodeDataChange(selectedNode.id, { stepType: v as "agent" | "loop" })
              }
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="agent">
                  <span className="flex items-center gap-1.5">Agent</span>
                </SelectItem>
                <SelectItem value="loop">
                  <span className="flex items-center gap-1.5">
                    <Repeat className="h-3 w-3" /> Loop
                  </span>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Loop Configuration (only visible for loop steps) */}
          {d.stepType === "loop" && (
            <div className="space-y-2 border rounded-md p-2 bg-blue-500/10">
              <Label className="text-[10px] text-blue-500 font-semibold">Loop Config</Label>
              <div className="space-y-1">
                <Label className="text-[10px]">Max Iterations</Label>
                <Input
                  type="number"
                  min={1}
                  max={10000}
                  value={d.loopConfig?.maxIterations ?? ""}
                  onChange={(e) => {
                    const raw = e.target.value;
                    if (!raw) {
                      onNodeDataChange(selectedNode.id, {
                        loopConfig: { ...d.loopConfig, maxIterations: undefined },
                      });
                      return;
                    }
                    const val = parseInt(raw, 10);
                    if (isNaN(val) || val < 1) return;
                    onNodeDataChange(selectedNode.id, {
                      loopConfig: { ...d.loopConfig, maxIterations: Math.min(val, 10000) },
                    });
                  }}
                  placeholder="e.g. 10"
                  className="h-7 text-xs"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px]">Plan Source</Label>
                <Select
                  value={d.loopConfig?.planSource ?? "prompt"}
                  onValueChange={(v) =>
                    onNodeDataChange(selectedNode.id, {
                      loopConfig: { ...d.loopConfig, planSource: v as "inline" | "prompt" },
                    })
                  }
                >
                  <SelectTrigger className="h-7 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="prompt">Prompt</SelectItem>
                    <SelectItem value="inline">Inline</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {d.loopConfig?.planSource === "inline" && (
                <div className="space-y-1">
                  <Label className="text-[10px]">Plan</Label>
                  <Textarea
                    value={d.loopConfig?.plan ?? ""}
                    onChange={(e) =>
                      onNodeDataChange(selectedNode.id, {
                        loopConfig: { ...d.loopConfig, plan: e.target.value },
                      })
                    }
                    className="text-xs min-h-[40px]"
                    rows={2}
                    placeholder="Inline plan..."
                  />
                </div>
              )}
            </div>
          )}

          {/* Status badge (read-only) */}
          {d.stepState?.status && (
            <div className="text-[10px] text-muted-foreground pt-1 border-t">
              Execution status: <span className="font-semibold">{d.stepState.status}</span>
              {d.stepState.error && (
                <div className="text-red-500 mt-0.5 break-words">{d.stepState.error}</div>
              )}
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
