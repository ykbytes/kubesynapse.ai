import { memo, useCallback, useMemo, useState } from "react";
import { CheckCircle2, MessageCircleQuestion, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { QuestionRequest } from "@/types";

/* ── Types ── */

interface QuestionDockProps {
  request: QuestionRequest;
  responding?: boolean;
  onReply: (requestId: string, answers: string[][]) => void;
  onReject: (requestId: string) => void;
}

/* ── Helpers ── */

function OptionButton({
  label,
  description,
  selected,
  onToggle,
}: {
  label: string;
  description: string;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`group rounded-xl border-2 px-4 py-3 text-left transition-all duration-150 cursor-pointer ${
        description ? "w-full" : ""
      } ${
        selected
          ? "border-primary bg-primary/10 shadow-md ring-1 ring-primary/30"
          : "border-border/50 bg-card hover:border-primary/50 hover:bg-primary/5 hover:shadow-sm"
      }`}
    >
      <div className="flex items-center gap-2.5">
        <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center">
          {selected ? (
            <CheckCircle2 className="h-5 w-5 text-primary" />
          ) : (
            <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/30 group-hover:border-primary/60 transition-colors" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className={`text-sm font-semibold leading-snug ${selected ? "text-primary" : "text-foreground"}`}>
            {label}
          </div>
          {description && (
            <div className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
              {description}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}

/* ── QuestionStep ── */

function QuestionStep({
  info,
  selectedLabels,
  customText,
  onToggleLabel,
  onCustomTextChange,
}: {
  info: QuestionRequest["questions"][0];
  selectedLabels: Set<string>;
  customText: string;
  onToggleLabel: (label: string) => void;
  onCustomTextChange: (text: string) => void;
}) {
  const allowMultiple = info.multiple ?? false;
  const allowCustom = info.custom !== false;
  const hasDescriptions = info.options.some((opt) => !!opt.description);

  return (
    <div className="space-y-3">
      <p className="text-[15px] font-medium text-foreground leading-relaxed">
        {info.question}
      </p>

      <div className={hasDescriptions ? "space-y-2" : "flex flex-wrap gap-2"}>
        {info.options.map((opt) => (
          <OptionButton
            key={opt.label}
            label={opt.label}
            description={opt.description}
            selected={selectedLabels.has(opt.label)}
            onToggle={() => onToggleLabel(opt.label)}
          />
        ))}
      </div>

      {allowCustom && (
        <div className="pt-1">
          <input
            type="text"
            placeholder="Type your own answer…"
            value={customText}
            onChange={(e) => onCustomTextChange(e.target.value)}
            className="w-full rounded-lg border border-border/60 bg-background/80 px-3 py-2 text-sm placeholder:text-muted-foreground/50 focus:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/20 transition-colors"
          />
        </div>
      )}

      {allowMultiple && (
        <p className="text-[11px] text-muted-foreground/70">
          Select multiple options
        </p>
      )}
    </div>
  );
}

/* ── Main Component ── */

export const QuestionDock = memo(function QuestionDock({
  request,
  responding,
  onReply,
  onReject,
}: QuestionDockProps) {
  const questions = request.questions;
  const isMultiStep = questions.length > 1;

  // State: per-question selected labels and custom text
  const [selections, setSelections] = useState<Map<number, Set<string>>>(() => new Map());
  const [customTexts, setCustomTexts] = useState<Map<number, string>>(() => new Map());
  const [activeStep, setActiveStep] = useState(0);

  const handleToggleLabel = useCallback(
    (stepIndex: number, label: string) => {
      setSelections((prev) => {
        const next = new Map(prev);
        const current = new Set(next.get(stepIndex) ?? []);
        const allowMultiple = questions[stepIndex]?.multiple ?? false;

        if (current.has(label)) {
          current.delete(label);
        } else {
          if (!allowMultiple) current.clear();
          current.add(label);
        }
        next.set(stepIndex, current);
        return next;
      });
    },
    [questions],
  );

  const handleCustomTextChange = useCallback((stepIndex: number, text: string) => {
    setCustomTexts((prev) => {
      const next = new Map(prev);
      next.set(stepIndex, text);
      return next;
    });
  }, []);

  const canSubmit = useMemo(() => {
    return questions.every((_, i) => {
      const selected = selections.get(i);
      const custom = customTexts.get(i)?.trim();
      return (selected && selected.size > 0) || !!custom;
    });
  }, [questions, selections, customTexts]);

  const handleSubmit = useCallback(() => {
    if (!canSubmit || responding) return;
    const answers: string[][] = questions.map((_, i) => {
      const selected = selections.get(i);
      const custom = customTexts.get(i)?.trim();
      const result: string[] = [];
      if (selected) result.push(...Array.from(selected));
      if (custom) result.push(custom);
      return result;
    });
    onReply(request.id, answers);
  }, [canSubmit, responding, questions, selections, customTexts, request.id, onReply]);

  const handleReject = useCallback(() => {
    if (responding) return;
    onReject(request.id);
  }, [responding, request.id, onReject]);

  const currentQuestion = questions[activeStep];
  if (!currentQuestion) return null;

  return (
    <div className="rounded-2xl border border-primary/25 bg-gradient-to-b from-primary/[0.03] to-transparent p-4 shadow-sm space-y-3 animate-in slide-in-from-bottom-2 duration-200">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
          <MessageCircleQuestion className="h-3.5 w-3.5 text-primary" />
          Agent question
          {isMultiStep && (
            <Badge variant="outline" className="ml-1 px-1.5 py-0 text-[10px]">
              {activeStep + 1}/{questions.length}
            </Badge>
          )}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-muted-foreground hover:text-foreground"
          onClick={handleReject}
          disabled={responding}
          title="Dismiss question"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Multi-step tabs */}
      {isMultiStep && (
        <div className="flex gap-1">
          {questions.map((q, i) => {
            const answered = (selections.get(i)?.size ?? 0) > 0 || !!customTexts.get(i)?.trim();
            return (
              <button
                key={i}
                type="button"
                onClick={() => setActiveStep(i)}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  i === activeStep
                    ? "bg-primary/10 text-primary"
                    : answered
                      ? "bg-emerald-500/10 text-emerald-600"
                      : "bg-muted/30 text-muted-foreground hover:bg-muted/50"
                }`}
              >
                {q.header || `Q${i + 1}`}
              </button>
            );
          })}
        </div>
      )}

      {/* Question content */}
      <QuestionStep
        info={currentQuestion}
        selectedLabels={selections.get(activeStep) ?? new Set()}
        customText={customTexts.get(activeStep) ?? ""}
        onToggleLabel={(label) => handleToggleLabel(activeStep, label)}
        onCustomTextChange={(text) => handleCustomTextChange(activeStep, text)}
      />

      {/* Actions */}
      <div className="flex items-center justify-end gap-2 pt-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 px-3 text-xs"
          onClick={handleReject}
          disabled={responding}
        >
          Dismiss
        </Button>
        <Button
          type="button"
          size="sm"
          className="h-8 gap-1.5 px-4 text-xs"
          onClick={handleSubmit}
          disabled={!canSubmit || responding}
        >
          {responding ? (
            <>Sending…</>
          ) : (
            <>
              <Send className="h-3 w-3" />
              Submit answer
            </>
          )}
        </Button>
      </div>
    </div>
  );
});
