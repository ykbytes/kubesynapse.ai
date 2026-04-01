import type { LucideIcon } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const statusBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-all duration-200",
  {
    variants: {
      status: {
        success: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-sm shadow-emerald-500/15",
        warning: "bg-amber-500/10 text-amber-400 border border-amber-500/20 shadow-sm shadow-amber-500/15",
        error: "bg-red-500/10 text-red-400 border border-red-500/20 shadow-sm shadow-red-500/15",
        info: "bg-blue-500/10 text-blue-400 border border-blue-500/20 shadow-sm shadow-blue-500/15",
        neutral: "bg-muted text-muted-foreground border border-border/40",
        running: "bg-primary/10 text-primary border border-primary/20 animate-glow-pulse shadow-md shadow-primary/15",
      },
    },
    defaultVariants: {
      status: "neutral",
    },
  }
);

interface StatusBadgeProps extends VariantProps<typeof statusBadgeVariants> {
  icon?: LucideIcon;
  children: React.ReactNode;
  className?: string;
  "aria-label"?: string;
}

export function StatusBadge({ icon: Icon, status, children, className, "aria-label": ariaLabel }: StatusBadgeProps) {
  return (
    <span className={cn(statusBadgeVariants({ status }), className)} aria-label={ariaLabel}>
      {Icon && (
        <Icon
          className={cn("h-3 w-3 transition-all duration-200", status === "running" && "animate-spin")}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}
