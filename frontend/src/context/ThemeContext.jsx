import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const ThemeContext = createContext(null);
const STORAGE_KEY = "ekeekrta_theme_preference";
const personalThemes = new Set(["institution", "light", "dark", "system"]);
const institutionThemes = new Set(["light", "dark", "system"]);

function browserPreference() {
  if (typeof localStorage === "undefined") return "institution";
  const saved = localStorage.getItem(STORAGE_KEY);
  return personalThemes.has(saved) ? saved : "institution";
}

export function ThemeProvider({ children }) {
  const [preference, setPreferenceState] = useState(browserPreference);
  const [institutionDefault, setInstitutionDefaultState] = useState("light");

  const setPreference = useCallback((value) => {
    if (!personalThemes.has(value)) return;
    if (typeof localStorage !== "undefined") localStorage.setItem(STORAGE_KEY, value);
    setPreferenceState(value);
  }, []);

  const setInstitutionDefault = useCallback((value) => {
    setInstitutionDefaultState(institutionThemes.has(value) ? value : "light");
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const requested = preference === "institution" ? institutionDefault : preference;
      const resolved = requested === "system" ? (media.matches ? "dark" : "light") : requested;
      document.documentElement.dataset.theme = resolved;
      document.documentElement.style.colorScheme = resolved;
    };
    applyTheme();
    media.addEventListener?.("change", applyTheme);
    return () => media.removeEventListener?.("change", applyTheme);
  }, [preference, institutionDefault]);

  const value = useMemo(() => ({ preference, setPreference, institutionDefault, setInstitutionDefault }),
    [preference, setPreference, institutionDefault, setInstitutionDefault]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside a ThemeProvider");
  return context;
}
