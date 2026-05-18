import { cn } from "@/lib/utils";

interface KubeSynapseLogoProps {
  className?: string;
  animated?: boolean;
}

export function KubeSynapseLogo({ className, animated }: KubeSynapseLogoProps) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("h-5 w-5 shrink-0", className)}
      aria-label="KubeSynapse"
    >
      <defs>
        {animated && (
          <>
            <radialGradient id="ks-pulse-grad" cx="50%" cy="46.9%" r="15%">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.8">
                <animate attributeName="stopOpacity" values="0.8;0.3;0.8" dur="2s" repeatCount="indefinite" />
              </stop>
              <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
            </radialGradient>
            <filter id="ks-glow">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </>
        )}
      </defs>

      <polygon
        points="32,10 47.5,19 47.5,37 32,46 16.5,37 16.5,19"
        fill="currentColor"
        fillOpacity="0.12"
        stroke="currentColor"
        strokeWidth="2.3"
        strokeLinejoin="round"
      />
      <path
        d="M22 23 C 26 26, 28 27, 31 30"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        className={animated ? "ks-path-left" : undefined}
      />
      <path
        d="M42 23 C 38 26, 36 27, 33 30"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        className={animated ? "ks-path-right" : undefined}
      />
      <path
        d="M32 43 C 32 39, 32 36, 32 33"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        className={animated ? "ks-path-down" : undefined}
      />

      {animated && (
        <>
          <circle cx="32" cy="30" r="12" fill="url(#ks-pulse-grad)">
            <animate attributeName="r" values="8;14;8" dur="2.5s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.6;0.2;0.6" dur="2.5s" repeatCount="indefinite" />
          </circle>
          <circle cx="32" cy="30" r="3.2" fill="currentColor" filter="url(#ks-glow)">
            <animate attributeName="r" values="3.2;4;3.2" dur="2s" repeatCount="indefinite" />
          </circle>
        </>
      )}

      {!animated && <circle cx="32" cy="30" r="3.2" fill="currentColor" />}

      <circle cx="32" cy="30" r="7" stroke="currentColor" strokeWidth="1" opacity={animated ? 0.4 : 0.3}>
        {animated && <animate attributeName="opacity" values="0.4;0.15;0.4" dur="2s" repeatCount="indefinite" />}
      </circle>
    </svg>
  );
}