import { cn } from "@/lib/utils";

interface KubeSynapseLogoProps {
  className?: string;
  /** When true, renders the full horizontal wordmark (icon + "kubesynapse" text). */
  wordmark?: boolean;
}

/**
 * KubeSynapse logo — blue-purple hexagonal K synapse icon.
 * Set wordmark={true} for the full horizontal logo with text.
 */
export function KubeSynapseLogo({ className, wordmark = false }: KubeSynapseLogoProps) {
  if (wordmark) {
    return (
      <svg
        viewBox="0 0 1400 360"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={cn("shrink-0", className)}
        aria-label="KubeSynapse"
      >
        <defs>
          <linearGradient id="ks-badgeGrad" x1="80" y1="70" x2="310" y2="295" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#0B7CFF"/>
            <stop offset="0.52" stopColor="#2F5BFF"/>
            <stop offset="1" stopColor="#7A3FF2"/>
          </linearGradient>
          <linearGradient id="ks-synapseGrad" x1="620" y1="150" x2="1235" y2="150" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#0B7CFF"/>
            <stop offset="0.58" stopColor="#2F5BFF"/>
            <stop offset="1" stopColor="#7A3FF2"/>
          </linearGradient>
        </defs>
        {/* Icon badge */}
        <path d="M170 36L278 98C292 106 300 121 300 136V224C300 239 292 254 278 262L170 324C156 332 139 332 126 324L18 262C4 254 -4 239 -4 224V136C-4 121 4 106 18 98L126 36C139 28 156 28 170 36Z" transform="translate(74 0)" fill="url(#ks-badgeGrad)"/>
        {/* K mark */}
        <path d="M188 112V248" stroke="#FFFFFF" strokeWidth="26" strokeLinecap="round"/>
        <path d="M259 104L199 171" stroke="#FFFFFF" strokeWidth="24" strokeLinecap="round"/>
        <path d="M199 189L260 256" stroke="#FFFFFF" strokeWidth="24" strokeLinecap="round"/>
        {/* Synapse nodes */}
        <circle cx="246" cy="180" r="13" fill="#FFFFFF"/>
        <circle cx="293" cy="146" r="13" fill="#FFFFFF"/>
        <circle cx="294" cy="214" r="13" fill="#FFFFFF"/>
        <path d="M257 174L281 155" stroke="#FFFFFF" strokeWidth="8" strokeLinecap="round"/>
        <path d="M257 186L282 205" stroke="#FFFFFF" strokeWidth="8" strokeLinecap="round"/>
        {/* Wordmark */}
        <text x="390" y="226" fill="#FFFFFF" fontFamily="Inter, Avenir Next, Segoe UI, Arial, sans-serif" fontSize="116" fontWeight="800" letterSpacing="-5">kube</text>
        <text x="622" y="226" fill="url(#ks-synapseGrad)" fontFamily="Inter, Avenir Next, Segoe UI, Arial, sans-serif" fontSize="116" fontWeight="800" letterSpacing="-5">synapse</text>
      </svg>
    );
  }

  // Icon-only version (hexagonal badge with K + nodes)
  return (
    <svg
      viewBox="0 0 370 360"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("shrink-0", className)}
      aria-label="KubeSynapse"
    >
      <defs>
        <linearGradient id="ks-badgeGrad-icon" x1="80" y1="70" x2="310" y2="295" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#0B7CFF"/>
          <stop offset="0.52" stopColor="#2F5BFF"/>
          <stop offset="1" stopColor="#7A3FF2"/>
        </linearGradient>
      </defs>
      {/* Icon badge */}
      <path d="M170 36L278 98C292 106 300 121 300 136V224C300 239 292 254 278 262L170 324C156 332 139 332 126 324L18 262C4 254 -4 239 -4 224V136C-4 121 4 106 18 98L126 36C139 28 156 28 170 36Z" transform="translate(74 0)" fill="url(#ks-badgeGrad-icon)"/>
      {/* K mark */}
      <path d="M188 112V248" stroke="#FFFFFF" strokeWidth="26" strokeLinecap="round"/>
      <path d="M259 104L199 171" stroke="#FFFFFF" strokeWidth="24" strokeLinecap="round"/>
      <path d="M199 189L260 256" stroke="#FFFFFF" strokeWidth="24" strokeLinecap="round"/>
      {/* Synapse nodes */}
      <circle cx="246" cy="180" r="13" fill="#FFFFFF"/>
      <circle cx="293" cy="146" r="13" fill="#FFFFFF"/>
      <circle cx="294" cy="214" r="13" fill="#FFFFFF"/>
      <path d="M257 174L281 155" stroke="#FFFFFF" strokeWidth="8" strokeLinecap="round"/>
      <path d="M257 186L282 205" stroke="#FFFFFF" strokeWidth="8" strokeLinecap="round"/>
    </svg>
  );
}
