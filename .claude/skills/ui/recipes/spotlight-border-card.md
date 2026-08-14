# recipes/spotlight-border-card.md — Spotlight Border Card

**The shadcn-showcase / Aceternity / Framer-template pattern.** A card whose border lights up dynamically under the cursor — a soft radial glow tracks the mouse along the perimeter, creating a "spotlight under glass" effect. The card surface stays calm; only the border-layer glows. Used on every premium feature grid you've envied.

## When to use

- Features grid (3–6 cards) on a marketing page — **subtle** variant
- Single hero CTA card or "join the beta" call-out — **intense** variant
- Pricing tier cards (only the highlighted tier — never all of them)
- Integration / logos grid where each tile is interactive

**Do NOT use on:** dashboards, app UI, any context with ≥10 cards in view (visual noise compounds), cards smaller than ~240px (the gradient looks blocky).

## The signature: pseudo-element renders the gradient, not the card

The card itself is plain — border + background + content. A `::before` pseudo-element (or sibling absolutely-positioned div) sits behind/over the border with a `radial-gradient` whose center is driven by two CSS variables: `--spotlight-x` and `--spotlight-y`. Mouse movement updates those variables via Framer Motion's `useMotionValue`. **No re-renders. No `useState`. No layout thrash.** Only the GPU compositor moves the gradient.

## Code — Subtle variant (features grid)

```tsx
'use client';

import { motion, useMotionTemplate, useMotionValue } from 'framer-motion';
import { useRef } from 'react';

export function SpotlightCard({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mx = useMotionValue(-200);
  const my = useMotionValue(-200);

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    mx.set(e.clientX - r.left);
    my.set(e.clientY - r.top);
  }

  function onLeave() {
    mx.set(-200);
    my.set(-200);
  }

  // Build the gradient string from the live motion values
  const bg = useMotionTemplate`radial-gradient(220px circle at ${mx}px ${my}px, var(--accent), transparent 40%)`;

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className={`group relative rounded-3xl bg-[var(--bg-elevated)] p-px ${className}`}
    >
      {/* Spotlight layer — sits behind the inner card, only the rim shows through */}
      <motion.div
        aria-hidden
        style={{ background: bg }}
        className="pointer-events-none absolute inset-0 rounded-3xl opacity-60 transition-opacity duration-300 group-hover:opacity-100"
      />
      {/* Inner card — covers the spotlight except for the 1px rim */}
      <div className="relative rounded-[calc(1.5rem-1px)] bg-[var(--bg-elevated)] p-8">
        {children}
      </div>
    </div>
  );
}
```

### Usage in a 3-up features grid

```tsx
<div className="grid gap-6 md:grid-cols-3">
  <SpotlightCard>
    <h3 className="text-xl font-semibold tracking-tight">Composable schemas</h3>
    <p className="mt-3 text-sm text-[var(--text-muted)]">
      Define once, reuse across services. Type-safe end-to-end without code generation.
    </p>
  </SpotlightCard>
  <SpotlightCard>
    <h3 className="text-xl font-semibold tracking-tight">Replays in production</h3>
    <p className="mt-3 text-sm text-[var(--text-muted)]">
      Every request is replayable. Debug a customer's exact session in your IDE.
    </p>
  </SpotlightCard>
  <SpotlightCard>
    <h3 className="text-xl font-semibold tracking-tight">Cold-start &lt; 40ms</h3>
    <p className="mt-3 text-sm text-[var(--text-muted)]">
      Edge-deployed by default. No warm-up cron, no provisioned concurrency.
    </p>
  </SpotlightCard>
</div>
```

## Code — Intense variant (hero CTA card)

Same component, three changes: the spotlight is larger (380px), runs at full opacity, and a second outer glow blooms outside the card.

```tsx
'use client';

import { motion, useMotionTemplate, useMotionValue } from 'framer-motion';
import { useRef } from 'react';

export function SpotlightCardIntense({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const mx = useMotionValue(-400);
  const my = useMotionValue(-400);

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    mx.set(e.clientX - r.left);
    my.set(e.clientY - r.top);
  }
  function onLeave() {
    mx.set(-400);
    my.set(-400);
  }

  const rim = useMotionTemplate`radial-gradient(380px circle at ${mx}px ${my}px, var(--accent), transparent 45%)`;
  const bloom = useMotionTemplate`radial-gradient(500px circle at ${mx}px ${my}px, color-mix(in oklch, var(--accent) 35%, transparent), transparent 60%)`;

  return (
    <div className="relative">
      {/* Outer bloom — leaks beyond the card edges */}
      <motion.div
        aria-hidden
        style={{ background: bloom }}
        className="pointer-events-none absolute -inset-12 rounded-[3rem] blur-2xl"
      />
      <div
        ref={ref}
        onMouseMove={onMove}
        onMouseLeave={onLeave}
        className="relative rounded-3xl bg-[var(--bg-elevated)] p-px"
      >
        <motion.div
          aria-hidden
          style={{ background: rim }}
          className="pointer-events-none absolute inset-0 rounded-3xl"
        />
        <div className="relative rounded-[calc(1.5rem-1px)] bg-[var(--bg-elevated)] p-12">
          {children}
        </div>
      </div>
    </div>
  );
}
```

## Why this is the right implementation

1. **Two stacked divs (`p-px` outer + inner)** create the rim — the spotlight bleeds through a 1px gap. Cleaner than `border-image` and CSS-variable-friendly.
2. **`useMotionTemplate`** stitches the gradient string from live motion values — no re-render, the browser just recomputes the background paint.
3. **Initial position off-canvas (`-200`)** ensures the spotlight is invisible until the cursor enters. No flash on mount.
4. **Group-hover opacity transition** fades the whole spotlight in/out — sharper than transitioning the gradient itself.
5. **`pointer-events-none`** on the spotlight layer — clicks pass through to the inner card content.

## Why most clones look bad

1. They use `useState` for mouse position → re-render every mousemove → janky.
2. They put the gradient on the card itself, not a sibling layer → can't fade independently and ruins border treatments.
3. Spotlight too big (>40% of card width) → looks like a flashlight, not a rim glow.
4. They animate the gradient stops instead of position → hardware can't optimize, fps drops.
5. They forget `pointer-events-none` → spotlight layer eats clicks on inner buttons.

## Customization rules

- **Spotlight radius:** 200–250px for subtle, 350–450px for intense. Match to card size.
- **`transparent X%`:** 35–45%. Lower = sharper rim. Higher = softer halo.
- **Always use `var(--accent)`** as the spotlight color. Never a hardcoded hex.
- **Don't apply to >6 cards in view** — visual noise compounds.
- **Outer bloom is intense-variant only.** Don't add to features-grid cards (looks desperate).

## RSC / Next.js App Router

`'use client'` at the top of the file. Import the component into a server page; do not mark the page client. See `architecture.md` for the isolation pattern.

## What NOT to change

- Don't replace `useMotionValue` + `useMotionTemplate` with `useState` + template literal — destroys the perf win
- Don't put the gradient on the card surface — must be a sibling layer
- Don't use a square card — the radial gradient needs `rounded-3xl` or larger to feel right
- Don't add a colored border in addition to the spotlight — competing edges
- Don't animate the spotlight color (rainbow effect) — looks like a 2014 portfolio

## Cross-references

- `tokens.md` — accent color, `--bg-elevated` token
- `recipes/features-bento.md` — alternative card treatment for mixed-size grids
- `anti-slop.md` — "useState for continuous-input is BANNED"
- `architecture.md` — `'use client'` isolation
