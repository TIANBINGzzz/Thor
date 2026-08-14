# recipes/nav-megamenu.md — Mega-Menu Dropdown Panel

**Extends `recipes/nav-pill.md` with a multi-column dropdown panel** that opens on hover/focus of a top-level nav link. Used by Mistral (product family + use-cases columns) and Twenty (single screenshot preview inside the dropdown — the most premium variant).

Use ONLY for nav items that have ≥4 sub-links OR a screenshot worth previewing. For 1-3 sublinks, use a simple dropdown — mega-menu over-promises and looks empty.

## When to use

- "Product" or "Solutions" nav items with multiple sub-products / use-cases
- Resources / Learn nav with mixed content types (docs, blog, changelog, community)
- Any moment where a nav item deserves a screenshot preview (Twenty pattern)

## The two variants

- **Variant A — Multi-column link list (Mistral / IntegratedBio).** Three columns max. Each column has a small uppercase label + 3-5 links. Optional 4th column for "Featured" with a thumbnail.
- **Variant B — Screenshot-preview dropdown (Twenty).** Two-column: left = grouped link list, right = live screenshot preview of whatever is hovered. Premium signal — most clones never ship this.

## Code (Variant A — multi-column)

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";

type MenuGroup = {
  label: string;
  items: { title: string; href: string; desc?: string }[];
};

const PRODUCT_MENU: MenuGroup[] = [
  {
    label: "Platform",
    items: [
      { title: "AI Studio", href: "/studio", desc: "Build agents visually" },
      { title: "Workflows", href: "/workflows", desc: "Trigger + automate" },
      { title: "Knowledge", href: "/knowledge", desc: "RAG that actually works" },
    ],
  },
  {
    label: "Use cases",
    items: [
      { title: "Customer support", href: "/cs" },
      { title: "Sales enablement", href: "/sales" },
      { title: "Internal search", href: "/search" },
    ],
  },
  {
    label: "By role",
    items: [
      { title: "Engineers", href: "/eng" },
      { title: "PMs", href: "/pm" },
      { title: "Operators", href: "/ops" },
    ],
  },
];

export function NavWithMega() {
  const [openMenu, setOpenMenu] = useState<string | null>(null);

  return (
    <header className="sticky top-4 z-50 px-4">
      <nav
        className="relative mx-auto max-w-6xl"
        onMouseLeave={() => setOpenMenu(null)}
      >
        <div className="flex items-center justify-between rounded-full border border-black/8 bg-white/80 backdrop-blur-md px-3 py-2 shadow-[0_4px_24px_-8px_rgba(0,0,0,0.08)]">
          <a href="/" className="pl-3 pr-6 font-bold">Brand</a>

          <ul className="hidden md:flex items-center gap-1">
            {["Product", "Customers", "Pricing", "Docs"].map((label) => (
              <li
                key={label}
                onMouseEnter={() =>
                  setOpenMenu(label === "Product" ? "Product" : null)
                }
              >
                <button className="px-4 py-2 text-sm font-medium text-[var(--text)]">
                  {label}
                </button>
              </li>
            ))}
          </ul>

          <a
            href="/start"
            className="rounded-full bg-[var(--text)] px-5 py-2 text-sm font-medium text-[var(--bg)]"
          >
            Get started
          </a>
        </div>

        {/* MEGA-MENU PANEL — anchored under the nav, animates from above */}
        <AnimatePresence>
          {openMenu === "Product" && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
              className="absolute left-1/2 top-full mt-2 -translate-x-1/2 w-[680px] rounded-2xl border border-black/8 bg-white shadow-[0_24px_48px_-12px_rgba(0,0,0,0.12)] p-6"
            >
              <div className="grid grid-cols-3 gap-8">
                {PRODUCT_MENU.map((group) => (
                  <div key={group.label}>
                    <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">
                      {group.label}
                    </div>
                    <ul className="mt-3 space-y-1">
                      {group.items.map((item) => (
                        <li key={item.title}>
                          <a
                            href={item.href}
                            className="block rounded-lg px-3 py-2 -mx-3 hover:bg-[var(--text)]/[0.04]"
                          >
                            <div className="text-sm font-medium text-[var(--text)]">
                              {item.title}
                            </div>
                            {item.desc && (
                              <div className="text-xs text-[var(--text-muted)]">
                                {item.desc}
                              </div>
                            )}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </nav>
    </header>
  );
}
```

## Code (Variant B — screenshot preview)

Replace the `grid grid-cols-3` block above with this two-column layout, and track the hovered item's preview image in state:

```tsx
const [preview, setPreview] = useState("https://picsum.photos/seed/studio/640/480");

<div className="grid grid-cols-[1fr_320px] gap-8">
  {/* Left: link list */}
  <ul className="space-y-1">
    {items.map((item) => (
      <li key={item.title}>
        <a
          href={item.href}
          onMouseEnter={() => setPreview(item.preview)}
          className="block rounded-lg px-3 py-2 -mx-3 hover:bg-[var(--text)]/[0.04]"
        >
          <div className="text-sm font-medium">{item.title}</div>
          <div className="text-xs text-[var(--text-muted)]">{item.desc}</div>
        </a>
      </li>
    ))}
  </ul>

  {/* Right: live screenshot preview — swaps via key */}
  <div className="rounded-xl bg-[var(--text)]/[0.03] border border-black/5 overflow-hidden aspect-[4/3]">
    <AnimatePresence mode="wait">
      <motion.img
        key={preview}
        src={preview}
        alt=""
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.18 }}
        className="w-full h-full object-cover"
      />
    </AnimatePresence>
  </div>
</div>
```

## Customization rules

- **Mega-menu width is fixed (`w-[680px]`).** Don't span the full nav width — must feel like a focused panel, not a takeover.
- **Open on hover, close on `onMouseLeave` of the parent nav** (NOT the panel itself, or the gap between nav and panel closes it).
- **`mt-2` gap** between nav and panel is critical — flush against the nav looks like a tooltip.
- **3 columns max** in Variant A. 4+ feels like a sitemap.
- **Variant B preview image** should be a real product screenshot, never a placeholder. If you don't have one, use Variant A.
- **Entrance is `y: -8 → 0` + opacity over 180ms.** Faster is jarring, slower feels laggy.

## What NOT to change

- Do not animate the panel from below — it's anchored under the nav; must come from above
- Do not make the panel `position: fixed` — must be `absolute` inside the nav (inherits the nav's centering)
- Do not use `<details>` / `<summary>` — must be hover-driven for desktop, with a separate mobile drawer
- Do not put more than 9 links total across all columns
- Do not add a bottom CTA inside the mega-menu (the nav already has the right-side CTA)

## Cross-references

- See `recipes/nav-pill.md` for the base nav pattern
- See `recipes/button-premium.md` for the right-side CTA
- See `tokens.md` "Motion presets" → `ENTRANCE` ease
- For mobile, the mega-menu collapses into the mobile drawer — see `recipes/mobile-onboarding.md` for sheet patterns
