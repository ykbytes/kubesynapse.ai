import type { LucideIcon } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const statusBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium transition-colors duration-200",
  {
    variants: {
      status: {
        success: "bg-emerald-500/10 text-emerald-400",
        warning: "bg-amber-500/10 text-amber-400",
        error: "bg-red-500/10 text-red-400",
        info: "bg-blue-500/10 text-blue-400",
        neutral: "bg-muted text-muted-foreground",
        running: "bg-primary/10 text-primary animate-glow-pulse",
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
}

export function StatusBadge({ icon: Icon, status, children, className }: StatusBadgeProps) {
  return (
    <span className={cn(statusBadgeVariants({ status }), className)}>
      {Icon && (
        <Icon
          className={cn("h-3 w-3 transition-transform duration-200", status === "running" && "animate-spin")}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}
