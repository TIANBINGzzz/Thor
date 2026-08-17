"use client";

import { useSyncExternalStore } from "react";

type Theme = "dark" | "light";
const THEME_KEY = "thor-theme";
const LEGACY_THEME_KEY = "ccsdkscribe-theme";
const THEME_EVENT = "thor-theme-change";

function getThemeSnapshot(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function getServerThemeSnapshot(): Theme {
  return "dark";
}

function subscribeTheme(onStoreChange: () => void) {
  const onThemeChange = () => onStoreChange();
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_KEY && event.key !== LEGACY_THEME_KEY) return;
    document.documentElement.dataset.theme = event.newValue === "light" ? "light" : "dark";
    onStoreChange();
  };

  window.addEventListener(THEME_EVENT, onThemeChange);
  window.addEventListener("storage", onStorage);

  return () => {
    window.removeEventListener(THEME_EVENT, onThemeChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, getThemeSnapshot, getServerThemeSnapshot);
  const nextThemeLabel = theme === "dark" ? "切换到浅色主题" : "切换到深色主题";
  const nextThemeTitle = theme === "dark" ? "浅色主题" : "深色主题";

  function toggleTheme() {
    const nextTheme: Theme = getThemeSnapshot() === "dark" ? "light" : "dark";
    window.localStorage.setItem(THEME_KEY, nextTheme);
    document.documentElement.dataset.theme = nextTheme;
    window.dispatchEvent(new Event(THEME_EVENT));
  }

  return (
    <button
      type="button"
      className="icon-btn theme-toggle"
      onClick={toggleTheme}
      aria-label={nextThemeLabel}
      title={nextThemeTitle}
    >
      <svg
        id="themeIcon"
        viewBox="0 0 24 24"
        width="18"
        height="18"
        aria-hidden="true"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {theme === "dark" ? (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2.5v2M12 19.5v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2.5 12h2M19.5 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42" />
          </>
        ) : (
          <path d="M20.7 13.2A8.6 8.6 0 1 1 10.8 3.3a6.8 6.8 0 0 0 9.9 9.9Z" />
        )}
      </svg>
    </button>
  );
}
