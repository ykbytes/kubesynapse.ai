import { forwardRef } from "react";
import { cn } from "@/lib/utils";

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
      {/* Mesh gradient background */}
      <div
        className="absolute inset-0 mesh-animated motion-safe:animate-[mesh-wave_28s_ease-in-out_infinite]"
        style={{
          background: `
            radial-gradient(ellipse 85% 55% at 15% 5%,  var(--wave-1) 0%, transparent 50%),
            radial-gradient(ellipse 70% 50% at 85% 15%, var(--wave-2) 0%, transparent 50%),
            radial-gradient(ellipse 60% 65% at 35% 85%, var(--wave-3) 0%, transparent 50%),
            radial-gradient(ellipse 75% 40% at 90% 75%, var(--wave-4) 0%, transparent 50%)
          `,
        }}
      />

      {hero && (
        <>
          {/* Hero floating orbs */}
          <div className="pointer-events-none absolute inset-0 overflow-hidden">
            <div className="absolute left-1/4 top-0 h-[500px] w-[500px] rounded-full bg-[oklch(0.708_0.101_188/0.07)] blur-[120px] motion-safe:animate-[float-orb-1_18s_ease-in-out_infinite]" />
            <div className="absolute right-1/4 top-1/3 h-[400px] w-[400px] rounded-full bg-[oklch(0.742_0.132_233/0.06)] blur-[100px] motion-safe:animate-[float-orb-2_22s_ease-in-out_infinite]" />
            <div className="absolute left-1/2 -translate-x-1/2 -translate-y-1/3 h-[420px] w-[min(800px,100vw)] rounded-full bg-[oklch(0.708_0.101_188/0.08)] blur-[100px] sm:h-[600px]" />
          </div>
        </>
      )}
    </div>
  )
);

StaticAtmosphere.displayName = "StaticAtmosphere";