import type { ComponentType } from "react";

import { cn } from "@/lib/utils";

type RuntimeBrandIconProps = {
  className?: string;
};

function OpenCodeBrandIcon({ className }: RuntimeBrandIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("h-4 w-4", className)}
      aria-hidden="true"
    >
      <rect x="4" y="2.5" width="16" height="19" rx="2.5" fill="#585252" />
      <path d="M4 5C4 3.61929 5.11929 2.5 6.5 2.5H17.5C18.8807 2.5 20 3.61929 20 5V8.75H4V5Z" fill="#050505" />
    </svg>
  );
}

function PiBrandIcon({ className }: RuntimeBrandIconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("h-4 w-4", className)}
      aria-hidden="true"
    >
      <path d="M1 1H11.7692V7.9999H8.17942V11.4999H4.58982V15H1V1ZM4.58982 4.50005V7.9999H8.17942V4.50005H4.58982Z" fill="currentColor" />
      <path d="M11.7692 7.46154H15V15H11.7692V7.46154Z" fill="currentColor" />
    </svg>
  );
}

function MistralBrandIcon({ className }: RuntimeBrandIconProps) {
  return (
    <svg
      viewBox="0 0 191 135"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("h-4 w-4", className)}
      aria-hidden="true"
    >
      <path d="M54.322 0H27.153v27.089h27.169V0Z" fill="#FFD800" />
      <path d="M162.984 0h-27.169v27.089h27.169V0Z" fill="#FFD800" />
      <path d="M81.482 27.091H27.153V54.18h54.329V27.09Z" fill="#FFAF00" />
      <path d="M162.99 27.091h-54.329V54.18h54.329V27.09Z" fill="#FFAF00" />
      <path d="M162.971 54.168H27.153v27.089h135.818V54.168Z" fill="#FF8205" />
      <path d="M54.322 81.259H27.153v27.09h27.169v-27.09Z" fill="#FA500F" />
      <path d="M108.661 81.259H81.492v27.09h27.169v-27.09Z" fill="#FA500F" />
      <path d="M162.984 81.259h-27.169v27.09h27.169v-27.09Z" fill="#FA500F" />
      <path d="M81.488 108.339H-.001v27.09h81.489v-27.09Z" fill="#E10500" />
      <path d="M190.159 108.339h-81.498v27.09h81.498v-27.09Z" fill="#E10500" />
    </svg>
  );
}

export const RUNTIME_BRAND_ICONS = {
  opencode: OpenCodeBrandIcon,
  pi: PiBrandIcon,
  "mistral-vibe": MistralBrandIcon,
} satisfies Record<string, ComponentType<{ className?: string }>>;
