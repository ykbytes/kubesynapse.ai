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
      <path d="M1.846 17.143H0V6.857h1.846v10.286Z" fill="#B7B1B1" />
      <path d="M5.538 17.143H1.846v-1.714h3.692v1.714Zm0-8.572H1.846V6.857h3.692v1.714Z" fill="#4B4646" />
      <path d="M10.154 21.429H8.308v-8.572h1.846v8.572Z" fill="#B7B1B1" />
      <path d="M8.308 12.857H6.462V8.571h1.846v4.286Zm3.692 0h-1.846v-1.714H12v1.714Zm0 8.572h-1.846v-1.715H12v1.715Z" fill="#4B4646" />
      <path d="M17.538 17.143h-5.077v-1.714h5.077v1.714Z" fill="#B7B1B1" />
      <path d="M17.538 8.571h-3.692V6.857h5.538v10.286h-1.846V8.571Zm-5.077 0h1.846v1.715h-1.846V8.57Z" fill="#F1ECEC" />
      <path d="M24 17.143h-1.846V8.571H24v8.572Z" fill="#B7B1B1" />
      <path d="M22.154 8.571h-1.846V6.857H24V8.57h-1.846Zm-1.846 8.572h1.846v1.714h-1.846v-1.714Zm3.692 1.714H22.154v-1.714H24v1.714Z" fill="#F1ECEC" />
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
