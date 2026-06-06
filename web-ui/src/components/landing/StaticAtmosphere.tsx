import { forwardRef } from "react";
import { cn } from "@/lib/utils";

export const StaticAtmosphere = forwardRef<HTMLDivElement, { className?: string }>(
  ({ className }, ref) => (
    <div
      ref={ref}
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className
      )}
      aria-hidden="true"
    >
      {/* Gradient orbs - static positions matching hero */}
      <div
        className="absolute left-1/4 top-0 h-[500px] w-[500px] rounded-full bg-[oklch(0.708_0.101_188/0.03)] blur-[100px]"
      />
      <div
        className="absolute right-1/4 top-1/3 h-[400px] w-[400px] rounded-full bg-[oklch(0.708_0.101_188/0.025)] blur-[100px]"
      />
      <div
        className="absolute left-1/2 -translate-x-1/2 -translate-y-1/3 h-[420px] w-[min(800px,100vw)] rounded-full bg-[oklch(0.708_0.101_188/0.04)] blur-[100px] sm:h-[600px]"
      />
      {/* Subtle radial dot grid */}
      <div
        className="absolute inset-0 opacity-[0.015]"
        style={{
          backgroundImage: "radial-gradient(oklch(0.708_0.101_188) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />
    </div>
  )
);

StaticAtmosphere.displayName = "StaticAtmosphere";