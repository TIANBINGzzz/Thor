# recipes/double-bezel-card.md — Double-Bezel (Doppelrand) Nested Architecture

**The "Doppelrand" pattern from premium taste-driven UI.** A primitive container architecture where an OUTER thin shell wraps an INNER core with a tight reveal of the outer surface around the edge — like a beveled picture frame, or a hardware bezel around a screen. The outer shell is calm and recessive (a soft tint with a hairline ring); the inner core carries the content and the highlight.

Use this as a **wrapper primitive** — wrap cards, inputs, even buttons inside it for a uniform "premium-feel object" language across the page.

## When to use

- Premium card surfaces (pricing tier, feature card, KPI tile)
- Search inputs / command palettes that need to feel "engineered"
- Embedded CTAs that need extra physical presence
- Anywhere the page already has plenty of `rounded-2xl bg-white border` cards and they look generic

**Don't use** for: dense table rows, mobile-only surfaces (the bezel reveal eats precious px), low-density marketing pages that already have plenty of breathing room.

## The signature

- **Outer shell:** `rounded-[2rem] bg-black/5 ring-1 ring-black/5 p-1.5`
- **Inner core:** `rounded-[calc(2rem-0.375rem)] bg-white shadow-[inset_0_1px_0_rgba(255,255,255,0.15)]`
- The `p-1.5` reveal on the outer shell is the bezel — it's the entire trick. Without it, you have a regular card.
- The inner radius is the outer radius minus the bezel padding so corners stay concentric.

## Code (wrapper primitive)

```tsx
import { ReactNode } from "react";

export function DoubleBezel({
  children,
  className = "",
  innerClassName = "",
}: {
  children: ReactNode;
  className?: string;
  innerClassName?: string;
}) {
  return (
    <div
      className={`rounded-[2rem] bg-black/5 ring-1 ring-black/5 p-1.5 ${className}`}
    >
      <div
        className={`
          rounded-[calc(2rem-0.375rem)]
          bg-white
          shadow-[inset_0_1px_0_rgba(255,255,255,0.15)]
          ${innerClassName}
        `}
      >
        {children}
      </div>
    </div>
  );
}
```

## Variant 1 — Card

```tsx
import { Sparkles } from "lucide-react";

export function FeatureCardBezeled() {
  return (
    <DoubleBezel className="max-w-sm">
      <div className="p-6">
        <div className="grid place-items-center size-10 rounded-xl bg-[var(--accent)]/10">
          <Sparkles className="size-5 text-[var(--accent)]" />
        </div>
        <h3 className="mt-4 text-lg font-semibold tracking-tight">
          Tasted, not generated
        </h3>
        <p className="mt-2 text-sm text-[var(--text-muted)] leading-relaxed">
          Every primitive in the system was hand-tuned. None of it shipped because a model said it was fine.
        </p>
      </div>
    </DoubleBezel>
  );
}
```

## Variant 2 — Input

```tsx
import { Search } from "lucide-react";

export function SearchInputBezeled() {
  return (
    <DoubleBezel
      className="w-full max-w-md"
      innerClassName="flex items-center gap-3 px-4 py-3"
    >
      <Search className="size-4 text-[var(--text-muted)]" />
      <input
        type="text"
        placeholder="Search the catalog..."
        className="flex-1 min-w-0 bg-transparent outline-none text-sm placeholder:text-[var(--text-muted)]"
      />
      <kbd className="text-[10px] font-mono text-[var(--text-muted)] bg-black/5 rounded px-1.5 py-0.5">
        ⌘K
      </kbd>
    </DoubleBezel>
  );
}
```

## Variant 3 — Button-in-button (CTA inside a bezeled chassis)

The bezel becomes a hardware-style frame around a primary button. Same shell architecture but the inner core is the button.

```tsx
import { ArrowRight } from "lucide-react";

export function BezeledCTA({ children = "Start free" }: { children?: React.ReactNode }) {
  return (
    <div className="inline-block rounded-full bg-black/5 ring-1 ring-black/5 p-1">
      <button
        className="
          inline-flex items-center gap-2
          rounded-full bg-[var(--text)] text-[var(--bg)]
          px-5 py-2.5 text-sm font-medium
          shadow-[inset_0_1px_0_rgba(255,255,255,0.15)]
          transition-transform duration-150 hover:-translate-y-px
        "
      >
        {children}
        <ArrowRight className="size-4" />
      </button>
    </div>
  );
}
```

## Why it works

1. **The bezel is a quiet signal of intentionality.** Most cards are a single rounded rect. The double-rect reads as "engineered," like a device screen inside a chassis.
2. **The inner highlight (`inset 0 1px 0 rgba(255,255,255,0.15)`) catches the same light** as the outer shell's calm tint — a tiny consistency that the eye notices unconsciously.
3. **Concentric radii** (`outer - bezel padding`) is the physics-correct shape. Off-by-one radii break the illusion instantly.
4. **The outer shell is `bg-black/5`, not white** — it has to be slightly darker than its surroundings for the bezel to read at all. White-on-white shells disappear.

## Customization rules

- **Bezel padding is `p-1.5` (6px).** Not `p-1` (too tight, looks like a border bug), not `p-2` (looks like a separate card-in-card).
- **Outer radius is `2rem`** (32px) for cards/inputs, `9999px` for pill buttons. Inner radius is always `calc(outer - 0.375rem)`.
- **Outer fill is `bg-black/5` on light themes, `bg-white/5` on dark themes.** Same idea: slightly contrast against the surroundings.
- **Outer ring is `ring-1 ring-black/5`** — same hue as the fill, but the ring adds a precise edge the fill alone can't.
- **Inner highlight (`inset 0 1px 0 rgba(255,255,255,0.15)`)** is mandatory on the inner core — without it the inner surface looks flat against the bezel.
- **Use the same DoubleBezel component for cards AND inputs AND CTAs on the same page** — uniformity is the entire payoff. Mixing bezeled and non-bezeled surfaces breaks the language.

## What NOT to change

- Don't use `border` on the outer shell — must be `ring`. Border eats into the bezel padding and breaks corner geometry.
- Don't make the outer shell a different color from the surroundings — it must be a tinted version of the page bg, never the accent color
- Don't add a shadow to the outer shell — flat tint only. The depth comes from the bezel + inner highlight, not from an outer drop shadow.
- Don't nest a DoubleBezel inside another DoubleBezel — it reads as Russian-doll, not engineered
- Don't use `rounded-md` or `rounded-lg` — calibrated for `rounded-[2rem]`. Smaller radii make the bezel look like a CSS bug.

## Cross-references

- See `recipes/button-premium.md` — the kargul shadow stack works as the inner core of a bezeled CTA
- See `recipes/bento-archetypes.md` — bento cards can be wrapped in DoubleBezel for "premium taste" mode
- See `tokens.md` "Shadows" — the inner highlight token
- See `anti-slop.md` "single rounded-rect card with shadow-lg" anti-pattern
