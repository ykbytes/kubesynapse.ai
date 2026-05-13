import type { LucideIcon } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const statusBadgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-[0.02em] transition-[background-color,border-color,color,box-shadow] duration-150 ease-productive",
  {
    variants: {
      status: {
        success: "border-success/25 bg-success/12 text-success",
        warning: "border-warning/28 bg-warning/14 text-warning",
        error: "border-destructive/25 bg-destructive/12 text-destructive",
        info: "border-info/25 bg-info/12 text-info",
        neutral: "border-border/65 bg-secondary/72 text-muted-foreground",
        running: "border-primary/25 bg-primary/14 text-primary shadow-sm",
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
          className={cn("h-2.5 w-2.5 transition-all duration-200", status === "running" && "animate-spin")}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}
