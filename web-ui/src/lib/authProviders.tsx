import { Building2 } from "lucide-react";
import type { AuthProviderSummary } from "@/types";
import { cn } from "@/lib/utils";

export type AuthProviderLaunchKind = "oidc" | "saml";
export type AuthProviderBrand = "generic" | "google" | "microsoft" | "okta" | "github";

export interface AuthProviderOption {
  id: string;
  name: string;
  kind: AuthProviderLaunchKind;
  brand: AuthProviderBrand;
  label: string;
  recommended: boolean;
}

const BRAND_PRIORITY: Record<AuthProviderBrand, number> = {
  google: 0,
  microsoft: 1,
  okta: 2,
  github: 3,
  generic: 4,
};

const KIND_PRIORITY: Record<AuthProviderLaunchKind, number> = {
  oidc: 0,
  saml: 1,
};

const BRAND_BADGE: Record<Exclude<AuthProviderBrand, "generic">, string> = {
  google: "G",
  microsoft: "M",
  okta: "O",
  github: "GH",
};

function normalizeBrand(brand: string | null | undefined): AuthProviderBrand {
  switch ((brand ?? "").trim().toLowerCase()) {
    case "google":
      return "google";
    case "microsoft":
      return "microsoft";
    case "okta":
      return "okta";
    case "github":
      return "github";
    default:
      return "generic";
  }
}

function inferBrand(provider: AuthProviderSummary): AuthProviderBrand {
  const explicitBrand = normalizeBrand(provider.brand);
  if (explicitBrand !== "generic") {
    return explicitBrand;
  }
  const fingerprint = `${provider.id} ${provider.name}`.toLowerCase();
  if (fingerprint.includes("google")) {
    return "google";
  }
  if (fingerprint.includes("microsoft") || fingerprint.includes("entra") || fingerprint.includes("azure")) {
    return "microsoft";
  }
  if (fingerprint.includes("okta")) {
    return "okta";
  }
  if (fingerprint.includes("github")) {
    return "github";
  }
  return "generic";
}

function toOption(provider: AuthProviderSummary): AuthProviderOption {
  const kind: AuthProviderLaunchKind = provider.kind === "saml" ? "saml" : "oidc";
  const brand = inferBrand(provider);
  return {
    id: provider.id,
    name: provider.name,
    kind,
    brand,
    label: brand === "google"
      ? "Continue with Google"
      : `Continue with ${provider.name}${kind === "saml" ? " (SAML)" : ""}`,
    recommended: kind === "oidc" && brand === "google",
  };
}

export function buildAuthProviderOptions(
  oidcProviders: AuthProviderSummary[],
  samlProviders: AuthProviderSummary[],
): AuthProviderOption[] {
  return [...oidcProviders, ...samlProviders]
    .map((provider) => toOption(provider))
    .sort((left, right) => (
      Number(right.recommended) - Number(left.recommended)
      || BRAND_PRIORITY[left.brand] - BRAND_PRIORITY[right.brand]
      || KIND_PRIORITY[left.kind] - KIND_PRIORITY[right.kind]
      || left.name.localeCompare(right.name)
    ));
}

export function recommendedAuthCopy(provider: AuthProviderOption | null): string {
  if (provider?.brand === "google") {
    return "Use Google to launch the managed browser sign-in flow. Keep API tokens for scripts, CI, or emergency access.";
  }
  return "Use managed sign-in for interactive access. Keep API tokens for scripts, CI, or emergency access.";
}

export function launchAuthProvider(
  provider: AuthProviderOption,
  handlers: { onOidcStart: (providerId: string) => void; onSamlStart: (providerId: string) => void },
): void {
  if (provider.kind === "saml") {
    handlers.onSamlStart(provider.id);
    return;
  }
  handlers.onOidcStart(provider.id);
}

export function AuthProviderBrandIcon({ brand, className }: { brand: AuthProviderBrand; className?: string }) {
  if (brand === "generic") {
    return <Building2 className={cn("h-4 w-4", className)} aria-hidden="true" />;
  }
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex h-5 min-w-5 items-center justify-center rounded-md border border-border/70 bg-background px-1.5 text-[10px] font-semibold leading-none text-foreground",
        className,
      )}
    >
      {BRAND_BADGE[brand]}
    </span>
  );
}