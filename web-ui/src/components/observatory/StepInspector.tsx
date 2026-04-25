import { Clock, Bot, Wrench, BrainCircuit } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import type { StepTrace } from "@/types";

interface StepInspectorProps {
  step: StepTrace | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function statusBadgeClasses(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded") return "bg-emerald-500/10 text-emerald-500 border-emerald-500/20";
  if (s === "failed" || s === "error") return "bg-red-500/10 text-red-500 border-red-500/20";
  if (s === "running" || s === "in_progress") return "bg-amber-500/10 text-amber-500 border-amber-500/20";
  return "bg-muted text-muted-foreground border-border/60";
}

export function StepInspector({ step, open, onOpenChange }: StepInspectorProps) {
  if (!step) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" />
            {step.name}
          </SheetTitle>
          <SheetDescription>
            <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", statusBadgeClasses(step.status))}>
              {step.status}
            </span>
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-5">
          {/* Metadata */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-border/50 bg-card/55 p-3">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Clock className="h-3.5 w-3.5" />
                Duration
              </div>
              <p className="mt-1 text-sm font-medium text-foreground">
                {step.latency_ms !== null && step.latency_ms !== undefined ? `${step.latency_ms} ms` : "—"}
              </p>
            </div>
            <div className="rounded-xl border border-border/50 bg-card/55 p-3">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Wrench className="h-3.5 w-3.5" />
                Calls
              </div>
              <p className="mt-1 text-sm font-medium text-foreground">
                {step.llm_calls.length + step.tool_calls.length}
              </p>
            </div>
          </div>

          {/* Input */}
          {step.input_preview && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Input</h4>
              <pre className="max-h-48 overflow-auto rounded-lg border border-border/40 bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100">
                {step.input_preview}
              </pre>
            </div>
          )}

          {/* Output */}
          {step.output_preview && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Output</h4>
              <pre className="max-h-48 overflow-auto rounded-lg border border-border/40 bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100">
                {step.output_preview}
              </pre>
            </div>
          )}

          {/* Error */}
          {step.error && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-red-400">Error</h4>
              <pre className="max-h-48 overflow-auto rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-[11px] leading-relaxed text-red-300">
                {step.error}
              </pre>
            </div>
          )}

          {/* LLM Calls */}
          {step.llm_calls.length > 0 && (
            <div className="space-y-2">
              <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <BrainCircuit className="h-3.5 w-3.5" />
                LLM Calls ({step.llm_calls.length})
              </h4>
              <div className="space-y-2">
                {step.llm_calls.map((llm) => (
                  <div key={llm.id} className="rounded-xl border border-border/50 bg-card/55 p-3 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-foreground">{llm.model}</span>
                      <span className="text-[10px] text-muted-foreground">{llm.latency_ms} ms</span>
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      Tokens: {llm.total_tokens} {llm.estimated_cost_usd !== null && llm.estimated_cost_usd !== undefined ? `· $${llm.estimated_cost_usd.toFixed(4)}` : ""}
                    </div>
                    {llm.prompt_preview && (
                      <pre className="max-h-32 overflow-auto rounded-md bg-slate-950 p-2 text-[10px] text-slate-100">
                        {llm.prompt_preview}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tool Calls */}
          {step.tool_calls.length > 0 && (
            <div className="space-y-2">
              <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Wrench className="h-3.5 w-3.5" />
                Tool Calls ({step.tool_calls.length})
              </h4>
              <div className="space-y-2">
                {step.tool_calls.map((tc) => (
                  <div key={tc.id} className="rounded-xl border border-border/50 bg-card/55 p-3 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-foreground">{tc.tool_name}</span>
                      <span className="text-[10px] text-muted-foreground">{tc.latency_ms} ms</span>
                    </div>
                    {tc.args_preview && (
                      <pre className="max-h-32 overflow-auto rounded-md bg-slate-950 p-2 text-[10px] text-slate-100">
                        {tc.args_preview}
                      </pre>
                    )}
                    {tc.result_preview && (
                      <pre className="max-h-32 overflow-auto rounded-md border border-border/40 bg-muted/30 p-2 text-[10px] text-muted-foreground">
                        {tc.result_preview}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
