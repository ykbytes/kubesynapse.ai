import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export const THEMES = ["dark", "light", "midnight", "forest"] as const;
export type Theme = (typeof THEMES)[number];

const THEME_LABELS: Record<Theme, string> = {
  dark: "Dark",
  light: "Light",
  midnight: "Midnight Blue",
  forest: "Forest",
};

interface ThemeContextValue {
  theme: Theme;
  setTheme: (t: Theme) => void;
  themeLabel: string;
  themes: readonly typeof THEMES[number][];
  labelFor: (t: Theme) => string;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem("app-theme");
    if (stored && (THEMES as readonly string[]).includes(stored)) return stored as Theme;
  } catch { /* SSR / private browsing */ }
  return "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  const applyTheme = useCallback((t: Theme) => {
    document.documentElement.setAttribute("data-theme", t);
    document.documentElement.classList.toggle("dark", t !== "light");
  }, []);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem("app-theme", t); } catch { /* ignore */ }
    applyTheme(t);
  }, [applyTheme]);

  useEffect(() => {
    applyTheme(theme);
  }, [theme, applyTheme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, themeLabel: THEME_LABELS[theme], themes: THEMES, labelFor: (t) => THEME_LABELS[t] }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
