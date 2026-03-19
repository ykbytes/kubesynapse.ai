/**
 * Central brand configuration.
 * All user-facing brand strings are sourced from Vite env vars
 * (prefixed VITE_BRAND_*), falling back to defaults.
 */

export interface BrandConfig {
  /** Top-line brand name, e.g. "Kubemininions" */
  name: string;
  /** Subtitle / product line, e.g. "Agent Sandbox" */
  tagline: string;
  /** HTML page title */
  pageTitle: string;
  /** Optional URL to a logo image (replaces the icon in TopBar) */
  logoUrl: string;
}

export const BRAND: BrandConfig = {
  name: import.meta.env.VITE_BRAND_NAME?.trim() || "Kubemininions",
  tagline: import.meta.env.VITE_BRAND_TAGLINE?.trim() || "Agent Sandbox",
  pageTitle: import.meta.env.VITE_BRAND_PAGE_TITLE?.trim() || "Kubemininions – Agent Sandbox",
  logoUrl: import.meta.env.VITE_BRAND_LOGO_URL?.trim() || "",
};
