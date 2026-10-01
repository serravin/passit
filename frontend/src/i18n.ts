import { useSyncExternalStore } from "react";
import de from "./locales/de.json";
import fr from "./locales/fr.json";
import it from "./locales/it.json";

export const languages = [
  { code: "en", name: "English" },
  { code: "de", name: "Deutsch" },
  { code: "fr", name: "Français" },
  { code: "it", name: "Italiano" },
] as const;
export type Language = (typeof languages)[number]["code"];
const catalogs: Record<string, Record<string, string>> = { de, fr, it };
const storageKey = "passit.language";
const listeners = new Set<() => void>();

export function supportedLanguage(
  value: string | null | undefined,
): Language | null {
  const code = value?.toLowerCase().split(/[-_]/)[0];
  return languages.some((language) => language.code === code)
    ? (code as Language)
    : null;
}

function initialLanguage(): Language {
  try {
    const saved = supportedLanguage(localStorage.getItem(storageKey));
    if (saved) return saved;
  } catch {
    /* A browser can disable local storage. */
  }
  for (const preferred of navigator.languages) {
    const language = supportedLanguage(preferred);
    if (language) return language;
  }
  return "en";
}
let currentLanguage = initialLanguage();

export function setLanguage(value: string): void {
  const language = supportedLanguage(value);
  if (!language) return;
  currentLanguage = language;
  document.documentElement.lang = language;
  try {
    localStorage.setItem(storageKey, language);
  } catch {
    /* Keep the in-memory preference. */
  }
  listeners.forEach((listener) => listener());
}

export function useLanguage(): Language {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => currentLanguage,
  );
}

const singular: Record<string, string> = {
  "{count} players": "{count} player",
  "{count} passes": "{count} pass",
  "{count} people": "{count} person",
  "{count} attempts": "{count} attempt",
};

export function t(
  key: string,
  values: Record<string, string | number> = {},
): string {
  if (values.count === 1 && singular[key]) key = singular[key];
  const catalog = catalogs[currentLanguage];
  const text = catalog && Object.hasOwn(catalog, key) ? catalog[key] : key;
  return text.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    values[name] === undefined ? placeholder : String(values[name]),
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof SyntaxError)
    return "Invalid JSON. Check the generation parameters.";
  if (error instanceof TypeError)
    return "Unable to reach the server. Please try again.";
  return error instanceof Error ? error.message : "Something went wrong";
}

export function translateError(message: string): string {
  const limits = /^Use 2 ≤ minimum ≤ maximum ≤ (\d+)$/.exec(message);
  if (limits) return t("Use 2 ≤ minimum ≤ maximum ≤ {cap}", { cap: limits[1] });
  const validation =
    /^AI validation failed \((\w+)\); check connectivity and model parameters$/.exec(
      message,
    );
  if (validation)
    return t(
      "AI validation failed ({error}); check connectivity and model parameters",
      { error: validation[1] },
    );
  return t(message);
}
