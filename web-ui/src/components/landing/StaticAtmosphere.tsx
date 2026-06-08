import { forwardRef } from "react";
import { cn } from "@/lib/utils";

/**
 * Static atmosphere background — purely static gradients, zero animations.
 * Provides a subtle dark ambient glow without any CPU/GPU cost.
 */
export const StaticAtmosphere = forwardRef<HTMLDivElement, { className?: string; hero?: boolean }>(
  ({ className, hero = false }, ref) => (
    <div
      ref={ref}
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className
      )}
      aria-hidden="true"
    >
      {/* Static mesh gradient — no animation */}
      <div
        className="absolute inset-0"
        style={{
          background: `
            radial-gradient(ellipse 85% 55% at 15% 5%,  oklch(0.708 0.101 188 / 0.03) 0%, transparent 50%),
            radial-gradient(ellipse 70% 50% at 85% 15%, oklch(0.742 0.132 233 / 0.02) 0%, transparent 50%),
            radial-gradient(ellipse 60% 65% at 35% 85%, oklch(0.68 0.15 280 / 0.015) 0%, transparent 50%),
            radial-gradient(ellipse 75% 40% at 90% 75%, oklch(0.72 0.12 200 / 0.012) 0%, transparent 50%)
          `,
        }}
      />

      {hero && (
        <>
          {/* Hero static orbs — no animation, just positioned blurred elements */}
          <div className="pointer-events-none absolute inset-0 overflow-hidden">
            <div className="absolute left-1/4 top-0 h-[500px] w-[500px] rounded-full bg-[oklch(0.708_0.101_188/0.06)] blur-[120px]" />
            <div className="absolute right-1/4 top-1/3 h-[400px] w-[400px] rounded-full bg-[oklch(0.742_0.132_233/0.05)] blur-[100px]" />
            <div className="absolute left-1/2 -translate-x-1/2 -translate-y-1/3 h-[420px] w-[min(800px,100vw)] rounded-full bg-[oklch(0.708_0.101_188/0.07)] blur-[100px] sm:h-[600px]" />
          </div>
        </>
      )}
    </div>
  )
);

StaticAtmosphere.displayName = "StaticAtmosphere";
