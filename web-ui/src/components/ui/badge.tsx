import * as React from "react";
import { cn } from "@/lib/utils";

const Badge = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    variant?: "default" | "secondary" | "destructive" | "outline";
  }
>(({ className, variant = "default", ...props }, ref) => {
  return (
    <div
      ref={ref}
      className={cn(
        "inline-flex min-w-0 max-w-full shrink items-center overflow-hidden text-ellipsis whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-[0.02em] transition-[background-color,border-color,color] duration-150 ease-productive focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
        {
          "border-primary/25 bg-primary/14 text-primary": variant === "default",
          "border-border/60 bg-secondary/80 text-secondary-foreground": variant === "secondary",
          "border-destructive/25 bg-destructive/12 text-destructive": variant === "destructive",
          "border-border/65 bg-transparent text-muted-foreground": variant === "outline",
        },
        className
      )}
      {...props}
    />
  );
});
Badge.displayName = "Badge";

export { Badge };
