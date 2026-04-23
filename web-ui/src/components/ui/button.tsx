import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[calc(var(--radius-md)-1px)] border border-transparent text-sm font-medium tracking-[0.01em] shadow-xs transition-[background-color,border-color,color,box-shadow,transform] duration-150 ease-productive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-primary/45 bg-primary text-primary-foreground hover:bg-primary/92 hover:shadow-sm active:translate-y-px",
        destructive: "border-destructive/45 bg-destructive text-destructive-foreground hover:bg-destructive/92 hover:shadow-sm active:translate-y-px",
        outline: "border-border/70 bg-card/72 text-foreground hover:border-border hover:bg-accent/70 hover:text-accent-foreground",
        secondary: "border-border/70 bg-secondary/82 text-secondary-foreground hover:border-border hover:bg-secondary",
        ghost: "border-transparent bg-transparent text-muted-foreground shadow-none hover:bg-accent/72 hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-11 px-6 text-sm",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
