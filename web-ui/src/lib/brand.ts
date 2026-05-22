/**
 * Central brand configuration.
 * All user-facing brand strings are sourced from Vite env vars
 * (prefixed VITE_BRAND_*), falling back to defaults.
 */

export interface BrandConfig {
  /** Top-line brand name, e.g. "kubesynapse" */
  name: string;
  /** Subtitle / product line, e.g. "AI Agent Platform" */
  tagline: string;
  /** HTML page title */
  pageTitle: string;
  /** Optional URL to a logo image (replaces the icon in TopBar) */
  logoUrl: string;
  /** Optional accent color override (CSS color value) */
  accentColor: string;
  /** Optional favicon URL */
  faviconUrl: string;
  /** Default theme preference */
  defaultTheme: string;
}

export const BRAND: BrandConfig = {
  name: import.meta.env.VITE_BRAND_NAME?.trim() || "kubesynapse",
  tagline: import.meta.env.VITE_BRAND_TAGLINE?.trim() || "AI Agent Platform",
  pageTitle: import.meta.env.VITE_BRAND_PAGE_TITLE?.trim() || "kubesynapse - AI Agent Platform",
  logoUrl: import.meta.env.VITE_BRAND_LOGO_URL?.trim() || "",
  accentColor: import.meta.env.VITE_BRAND_ACCENT_COLOR?.trim() || "",
  faviconUrl: import.meta.env.VITE_BRAND_FAVICON_URL?.trim() || "",
  defaultTheme: import.meta.env.VITE_BRAND_DEFAULT_THEME?.trim() || "dark",
};
