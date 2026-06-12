import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface PremiumBadgeProps {
  children: ReactNode;
  variant?: "success" | "error" | "warning" | "info" | "default" | "primary" | "secondary";
  icon?: ReactNode;
  size?: "sm" | "md" | "lg";
  className?: string;
  animated?: boolean;
}

export function PremiumBadge({
  children,
  variant = "default",
  icon,
  size = "md",
  className,
  animated = true,
}: PremiumBadgeProps) {
  const variantClasses = {
    success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    error: "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400",
    warning: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
    info: "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400",
    default: "border-border/40 bg-background/60 text-foreground/70",
    primary: "border-primary/30 bg-primary/10 text-primary",
    secondary: "border-secondary/30 bg-secondary/10 text-secondary",
  };

  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs gap-1",
    md: "px-2.5 py-1 text-sm gap-1.5",
    lg: "px-3 py-1.5 text-base gap-2",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border font-medium transition-all duration-200",
        variantClasses[variant],
        sizeClasses[size],
        animated && "hover:shadow-md hover:shadow-current/10",
        className
      )}
    >
      {icon && <span className="flex-shrink-0">{icon}</span>}
      {children}
    </span>
  );
}
