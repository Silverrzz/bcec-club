import { computed, onBeforeUnmount, ref } from "vue";

import type { ThemePreference } from "@/types/ui";

const STORAGE_KEY = "cope-theme";
function readStoredTheme(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

const stored = readStoredTheme();
const preference = ref<ThemePreference>(stored === "light" ? "light" : "dark");
const media = window.matchMedia("(prefers-color-scheme: dark)");
const systemDark = ref(media.matches);
let subscribers = 0;

function applyTheme(): void {
  const resolved = preference.value === "system" ? (systemDark.value ? "dark" : "light") : preference.value;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (themeColor) themeColor.content = resolved === "dark" ? "#0b1017" : "#f3f6fa";
}

function onSystemTheme(event: MediaQueryListEvent): void {
  systemDark.value = event.matches;
  applyTheme();
}

export function useTheme() {
  if (subscribers++ === 0) media.addEventListener("change", onSystemTheme);
  applyTheme();

  onBeforeUnmount(() => {
    subscribers -= 1;
    if (subscribers === 0) media.removeEventListener("change", onSystemTheme);
  });

  const resolvedTheme = computed<"light" | "dark">(() =>
    preference.value === "system" ? (systemDark.value ? "dark" : "light") : preference.value,
  );

  function setTheme(next: ThemePreference): void {
    preference.value = next;
    try {
      if (next === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Theme changes still apply when storage is unavailable.
    }
    applyTheme();
  }

  function toggleTheme(): void {
    setTheme(resolvedTheme.value === "dark" ? "light" : "dark");
  }

  return { preference, resolvedTheme, setTheme, toggleTheme };
}
