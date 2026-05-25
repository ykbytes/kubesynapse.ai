import { BrainCircuit, Clock, Coins, Hash } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import type { LLMCallRecord } from "@/types";

interface LLMCallViewerProps {
  llmCall: LLMCallRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function LLMCallViewer({ llmCall, open, onOpenChange }: LLMCallViewerProps) {
  if (!llmCall) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BrainCircuit className="h-4 w-4 text-violet-500" />
            {llmCall.model}
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-3">
            <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
              <Clock className="h-3 w-3" />
              {llmCall.latency_ms} ms
            </span>
            <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
              <Hash className="h-3 w-3" />
              {llmCall.total_tokens} tokens
            </span>
            {llmCall.estimated_cost_usd !== null && llmCall.estimated_cost_usd !== undefined && (
              <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                <Coins className="h-3 w-3" />
                ${llmCall.estimated_cost_usd.toFixed(4)}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 space-y-4">
          <div className="space-y-1.5">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Prompt</h4>
            <pre className="max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100">
              {llmCall.prompt_preview ?? "No preview available."}
            </pre>
          </div>

          <div className="space-y-1.5">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Response</h4>
            <pre className="max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100">
              {llmCall.response_preview ?? "No preview available."}
            </pre>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
