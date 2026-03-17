import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-gradient-to-b from-primary to-primary/85 text-primary-foreground shadow-md shadow-primary/20 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97]",
        destructive: "bg-gradient-to-b from-destructive to-destructive/85 text-destructive-foreground shadow-md shadow-destructive/20 hover:shadow-lg hover:shadow-destructive/25 active:scale-[0.97]",
        outline: "border border-border/60 bg-background/50 shadow-sm hover:bg-accent hover:text-accent-foreground hover:shadow-md hover:border-border active:scale-[0.97]",
        secondary: "bg-secondary/80 text-secondary-foreground shadow-sm hover:bg-secondary hover:shadow-md active:scale-[0.97]",
        ghost: "hover:bg-accent/80 hover:shadow-sm active:scale-[0.97]",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-lg px-3 text-xs",
        lg: "h-10 rounded-lg px-8",
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
