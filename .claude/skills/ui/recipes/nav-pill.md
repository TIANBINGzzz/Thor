# recipes/nav-pill.md — Pill-Grouped Top Nav

**Adapted from Mistral, Twenty, Ruul, IntegratedBio.** The current standard for premium SaaS navigation — three groups (logo / center links / right CTA) where the center links live inside a single pill-shaped container with a `layoutId` indicator that slides between active items. The whole nav floats inside a `max-w-6xl mx-auto` rounded container with subtle border + soft shadow — it does NOT span edge-to-edge.

## When to use

- Default top nav for any SaaS, agency, or marketing site
- When the user says "navbar", "header", "top nav"
- ANY time you'd otherwise reach for a flat horizontal `<nav>` with underline-on-hover (the AI default)

## Structure (three groups, single row)

1. **Left:** Logo wordmark or icon (16-32px height)
2. **Center:** Pill-grouped link list with sliding `layoutId` background
3. **Right:** Optional secondary link + primary CTA pill (use the dark CTA from `recipes/button-premium.md`)

## Code

```tsx
import { motion } from "framer-motion";
import { useState } from "react";

const LINKS = ["Product", "Customers", "Pricing", "Docs", "Blog"];

export function NavPill() {
  const [active, setActive] = useState("Product");

  return (
    <header className="sticky top-4 z-50 px-4">
      <nav
        className="
          mx-auto flex max-w-6xl items-center justify-between
          rounded-full border border-black/8 bg-white/80 backdrop-blur-md
          px-3 py-2 shadow-[0_4px_24px_-8px_rgba(0,0,0,0.08)]
        "
      >
        {/* LEFT: logo */}
        <a
          href="/"
          className="pl-3 pr-6 font-sans font-bold tracking-tight text-[var(--text)]"
        >
          Brand
        </a>

        {/* CENTER: pill-grouped links with layoutId indicator */}
        <ul className="hidden md:flex items-center gap-1">
          {LINKS.map((label) => {
            const isActive = active === label;
            return (
              <li key={label} className="relative">
                <button
                  onMouseEnter={() => setActive(label)}
                  className="relative z-10 px-4 py-2 text-sm font-medium text-[var(--text)]"
                >
                  {label}
                </button>
                {isActive && (
                  <motion.div
                    layoutId="nav-pill-bg"
                    className="absolute inset-0 rounded-full bg-[var(--text)]/[0.06]"
                    transition={{ type: "spring", stiffness: 380, damping: 30 }}
                  />
                )}
              </li>
            );
          })}
        </ul>

        {/* RIGHT: ghost link + primary CTA pill */}
        <div className="flex items-center gap-1">
          <a
            href="/login"
            className="hidden sm:inline-flex px-4 py-2 text-sm font-medium text-[var(--text)]/70 hover:text-[var(--text)]"
          >
            Log in
          </a>
          <a
            href="/start"
            className="inline-flex items-center gap-1.5 rounded-full bg-[var(--text)] px-5 py-2 text-sm font-medium text-[var(--bg)] hover:bg-[var(--text)]/90"
          >
            Get started
            <span aria-hidden>→</span>
          </a>
        </div>
      </nav>
    </header>
  );
}
```

## Customization rules

- **`layoutId="nav-pill-bg"` is the entire trick.** Without it, hover state is a mounted/unmounted background that flickers. With it, one persistent surface slides between links.
- **`sticky top-4`** + **`max-w-6xl`** = floating nav, NOT full-width sticky. Edge-to-edge sticky nav is the cheap default.
- **`bg-white/80 backdrop-blur-md`** = nav reads through scrolled content. Solid `bg-white` looks heavy.
- **CTA on the right is the premium pill** from `recipes/button-premium.md` (or the simpler dark pill above for lighter weight).
- **Hover, not click, drives the indicator** for marketing nav. Click is for actual navigation.

## What NOT to change

- Do not span the nav edge-to-edge — must be `max-w-6xl mx-auto` floating
- Do not use `transition: all` on the indicator — must be Framer Motion `layoutId`
- Do not use underline-on-hover (the most-shipped AI default; reads as 2014 Bootstrap)
- Do not stack the CTA below the links on desktop — three-group horizontal is the pattern
- Do not omit `backdrop-blur-md` — flat nav over scrolled content kills the floating effect

## Cross-references

- See `recipes/nav-megamenu.md` for the dropdown extension (Mistral / Twenty patterns)
- See `recipes/button-premium.md` for the right-side CTA pill
- See `tokens.md` "Motion presets" — `layoutId` section
- See `recipes/features-tabs.md` for related `layoutId` slider pattern
