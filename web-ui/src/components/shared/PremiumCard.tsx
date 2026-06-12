import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { motion } from "framer-motion";

interface PremiumCardProps {
  children: ReactNode;
  className?: string;
  variant?: "default" | "elevated" | "gradient" | "subtle";
  hover?: boolean;
  animated?: boolean;
}

export function PremiumCard({
  children,
  className,
  variant = "default",
  hover = true,
  animated = true,
}: PremiumCardProps) {
  const variantClasses = {
    default: "border-border/40 bg-card/95 backdrop-blur-sm",
    elevated:
      "border-primary/20 bg-gradient-to-br from-primary/5 via-background to-primary/5 shadow-lg shadow-primary/10",
    gradient:
      "border-transparent bg-gradient-to-br from-primary/10 via-background to-secondary/10 shadow-md shadow-primary/5",
    subtle: "border-border/20 bg-background/50",
  };

  const baseClasses = "rounded-lg border transition-all duration-200";

  const Comp = animated ? motion.div : "div";

  return (
    <Comp
      className={cn(
        baseClasses,
        variantClasses[variant],
        hover && "hover:shadow-md hover:shadow-primary/10",
        className
      )}
      whileHover={animated && hover ? { y: -2 } : undefined}
      transition={{ duration: 0.2 }}
    >
      {children}
    </Comp>
  );
}
