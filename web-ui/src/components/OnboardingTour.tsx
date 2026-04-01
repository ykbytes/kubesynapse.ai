import { useState, useEffect, useCallback } from "react";
import { Bot, GitBranch, FlaskConical, MessageSquare, ArrowRight, X } from "lucide-react";
import { Button } from "@/components/ui/button";

const STORAGE_KEY = "kubesynth/onboarding-done";

interface TourStep {
  title: string;
  description: string;
  icon: typeof Bot;
}

const STEPS: TourStep[] = [
  {
    title: "Create Agents",
    description: "Define an agent with a model, system prompt, and MCP tool sidecars. Hit create and it launches in its own sandboxed pod — ready to chat in seconds.",
    icon: Bot,
  },
  {
    title: "Build Workflows",
    description: "Chain agents into multi-step workflows using the visual Composer or YAML. Add verification gates, dev-loops, and conditional branching between steps.",
    icon: GitBranch,
  },
  {
    title: "Run Evaluations",
    description: "Create evaluation suites to test agent quality on repeatable inputs. Compare metrics across runs and catch regressions before they ship.",
    icon: FlaskConical,
  },
  {
    title: "Chat & Collaborate",
    description: "Talk to deployed agents in real time. Route requests across agents with A2A, approve or reject tool calls with Human-in-the-Loop, and inspect every step in the side panel.",
    icon: MessageSquare,
  },
];

export function OnboardingTour({ onComplete }: { onComplete?: () => void }) {
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!localStorage.getItem(STORAGE_KEY)) {
      setVisible(true);
    }
  }, []);

  const finish = useCallback(() => {
    localStorage.setItem(STORAGE_KEY, "1");
    setVisible(false);
    onComplete?.();
  }, [onComplete]);

  if (!visible) return null;

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in">
      <div className="relative w-full max-w-md mx-4 rounded-2xl border border-border bg-popover p-6 shadow-2xl">
        {/* Close */}
        <button
          type="button"
          className="absolute top-3 right-3 text-muted-foreground hover:text-foreground"
          onClick={finish}
          aria-label="Skip tour"
        >
          <X className="h-4 w-4" />
        </button>

        {/* Step indicator */}
        <div className="flex justify-center gap-1.5 mb-5">
          {STEPS.map((_, i) => (
            <span
              key={i}
              className={`h-1.5 rounded-full transition-all ${
                i === step ? "w-6 bg-primary" : "w-1.5 bg-muted-foreground/30"
              }`}
            />
          ))}
        </div>

        {/* Icon */}
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <current.icon className="h-7 w-7" />
        </div>

        {/* Content */}
        <h3 className="text-center text-lg font-semibold text-foreground">{current.title}</h3>
        <p className="mt-2 text-center text-sm text-muted-foreground leading-relaxed">
          {current.description}
        </p>

        {/* Actions */}
        <div className="mt-6 flex items-center justify-between">
          <Button variant="ghost" size="sm" onClick={finish} className="text-muted-foreground">
            Skip
          </Button>
          <Button
            size="sm"
            onClick={() => {
              if (isLast) finish();
              else setStep((s) => s + 1);
            }}
            className="gap-1.5"
          >
            {isLast ? "Get Started" : "Next"}
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
