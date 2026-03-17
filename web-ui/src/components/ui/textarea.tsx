import * as React from "react";
import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          "flex min-h-[60px] w-full rounded-lg border border-border/60 bg-background/50 px-3 py-2 text-sm shadow-sm transition-all duration-200 placeholder:text-muted-foreground hover:border-border hover:bg-background/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:border-primary/40 focus-visible:bg-background disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Textarea.displayName = "Textarea";

export { Textarea };
