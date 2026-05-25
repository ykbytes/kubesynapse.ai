import * as React from "react";
import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          "flex min-h-[60px] w-full rounded-[calc(var(--radius-md)-1px)] border border-input/80 bg-card/78 px-3 py-2.5 text-sm text-foreground shadow-xs transition-[background-color,border-color,box-shadow] duration-150 ease-productive placeholder:text-muted-foreground/85 hover:border-border hover:bg-card/92 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 focus-visible:border-ring/60 focus-visible:bg-popover disabled:cursor-not-allowed disabled:opacity-50",
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
