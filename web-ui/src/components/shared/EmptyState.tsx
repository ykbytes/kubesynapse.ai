import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
  className?: string;
}

export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      role="region"
      aria-label={title}
      className={cn(
        "flex flex-col items-center justify-center gap-3 py-12 text-center animate-scale-in",
        className
      )}
    >
      <div className="rounded-2xl bg-gradient-to-br from-primary/15 to-primary/5 p-4 animate-icon-float shadow-md shadow-primary/10 border border-primary/10">
        <Icon className="h-6 w-6 text-primary/85" aria-hidden="true" />
      </div>
      <div className="space-y-1">
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        {description && (
          <p className="text-sm text-muted-foreground max-w-[280px]">{description}</p>
        )}
      </div>
      {action && (
        <Button variant="outline" size="sm" className="hover-lift" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}
