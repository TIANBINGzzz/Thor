# recipes/features-bento.md — Bento Grid Features

**Modern asymmetric grid for feature sections.** Replaces the dead "3 cards in a row" pattern. Adapted from Linear, Vercel, Apple keynote moments, and shahidux dashboards.

## When to use

- 4-7 features that aren't all equal weight
- When you want visual interest without losing density
- Default features section unless user wants linear "how it works" (use `features-3step.md` instead)

## Code

```tsx
import { motion } from "framer-motion";

export function FeaturesBento() {
  return (
    <section className="px-6 py-32 max-w-7xl mx-auto">
      <div className="text-center mb-16">
        <span className="text-sm font-medium text-[var(--accent)] uppercase tracking-wider">Features</span>
        <h2 className="mt-3 font-sans text-4xl md:text-5xl font-bold tracking-tight">
          Everything you need. <span className="font-serif italic font-medium">Nothing you don't.</span>
        </h2>
      </div>

      {/* Bento grid — mixed sizes, NEVER 3 equal columns */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5 auto-rows-[minmax(220px,auto)]">
        {/* Big card spanning 2 columns */}
        <BentoCard className="md:col-span-2 md:row-span-2 bg-[var(--text)] text-[var(--bg)]">
          <Tag>HERO FEATURE</Tag>
          <h3 className="text-2xl md:text-3xl font-bold mt-3">The thing that matters most.</h3>
          <p className="mt-2 text-sm opacity-80 max-w-xs">One sentence about why this is the centerpiece.</p>
          <div className="mt-auto pt-6">
            {/* Live demo widget or product screenshot bleeds in */}
            <div className="aspect-[16/9] rounded-xl bg-white/10" />
          </div>
        </BentoCard>

        {/* Tall card */}
        <BentoCard className="md:row-span-2 bg-white">
          <Tag>SECOND FEATURE</Tag>
          <h3 className="text-xl font-bold mt-3 text-[var(--text)]">Quick verb-action.</h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">One sentence why.</p>
          <div className="mt-auto pt-6">
            {/* Tall illustration / animated chart */}
            <div className="aspect-[3/4] rounded-xl bg-neutral-100" />
          </div>
        </BentoCard>

        {/* Wide card */}
        <BentoCard className="md:col-span-2 bg-white">
          <div className="flex items-start gap-6">
            <div className="flex-1">
              <Tag>FAST FEATURE</Tag>
              <h3 className="text-xl font-bold mt-3 text-[var(--text)]">Built for speed.</h3>
              <p className="mt-2 text-sm text-[var(--text-muted)]">One sentence why.</p>
            </div>
            <div className="size-32 rounded-xl bg-neutral-100 shrink-0" />
          </div>
        </BentoCard>

        {/* Small card with accent gradient */}
        <BentoCard className="bg-white">
          <Tag>EXTRA FEATURE</Tag>
          <h3 className="text-xl font-bold mt-3 text-[var(--text)]">Third value prop.</h3>
          <p className="mt-2 text-sm text-[var(--text-muted)]">One sentence.</p>
        </BentoCard>
      </div>
    </section>
  );
}

function BentoCard({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return (
    <motion.div
      whileHover={{ y: -2 }}
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
      className={`group relative flex flex-col rounded-2xl border border-black/8 p-6 md:p-8 overflow-hidden ${className}`}
    >
      {/* Color-matched glow on hover (subtle) */}
      <div
        className="absolute -bottom-12 right-0 size-48 blur-3xl opacity-0 group-hover:opacity-30 transition-opacity"
        style={{ background: "var(--accent)" }}
        aria-hidden
      />
      <div className="relative z-10 flex flex-col h-full">{children}</div>
    </motion.div>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block text-[10px] font-semibold uppercase tracking-[0.12em] text-current opacity-60">
      {children}
    </span>
  );
}
```

## Customization rules

- **Bento = mixed sizes.** If you make all cards the same size, you've made a generic 3-column grid. The whole point is asymmetry.
- **Hero card spans 2x2** (or at least col-span-2). It's the most important feature.
- **Use the dark accent card sparingly** — typically just the hero card, dark on cream.
- **Each card has a tiny tag, then headline, then one-line subtext.** Not paragraphs.
- **Color-matched hover glow** is the premium signal — see `tokens.md` `--shadow-glow`.

## What NOT to change

- Don't make all 4-6 cards the same size
- Don't add icons to every card (visual clutter)
- Don't use shadcn `<Card>` defaults (rounded-md, default border) — use rounded-2xl and subtle border
- Don't use `transition-all duration-300` — use Framer Motion `whileHover` with spring

## Cross-references

- See `tokens.md` for `--shadow-glow` and color tokens
- See `anti-slop.md` "3-column feature grid with identical card sizes" anti-pattern
- See `recipes/features-3step.md` for the linear/sequential alternative
