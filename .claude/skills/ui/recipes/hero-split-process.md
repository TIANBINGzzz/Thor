# recipes/hero-split-process.md — Split Hero with Sticky Process Column

**Adapted from shahidux PivotQ.** Asymmetric split hero where the LEFT column shows a clean dashboard preview with floating capability pills, and the RIGHT column shows a sticky process list (Step 1/2/3/4) that scrolls in tandem with a calm illustration card.

Different from `hero-fintech.md` (which is left-copy + right-widget) — this hero is left-product + right-narrative. Use when the product has a clear sequential process worth narrating up-front.

## When to use

- Edtech, course platforms, onboarding-heavy SaaS
- Service-business platforms (where "how it works" is part of the value prop)
- AI products where "what does it do" needs explanation alongside "what does it look like"
- DO NOT use for: pure-product fintech, dev tools (use `hero-saas.md`), agencies (use `hero-agency.md`)

## Structure

- **Left (~55%)**: Bordered/elevated dashboard mockup with 2-3 floating capability pills overlapping its edge
- **Right (~45%)**: Sticky-positioned process list — 3-4 steps, each = `[icon chip] [step number + title] [one-line description]`, divided by hairlines
- **Below the right column**: A calm illustration card / outcome card that comes into view as the process list "completes"

## Code

```tsx
import { motion } from "framer-motion";
import {
  Search, Wand2, BookOpen, Trophy, ArrowUpRight, Sparkles,
} from "lucide-react";

const STEPS = [
  { n: "01", icon: Search, title: "Discover", desc: "Find the right course in seconds with AI-curated paths." },
  { n: "02", icon: Wand2, title: "Personalize", desc: "Adaptive lessons calibrate to your pace and gaps." },
  { n: "03", icon: BookOpen, title: "Learn", desc: "Live cohorts + replays. Mentor support when you're stuck." },
  { n: "04", icon: Trophy, title: "Apply", desc: "Build your portfolio. Get verified credentials." },
];

const ENTRANCE = { duration: 0.6, ease: [0.16, 1, 0.3, 1] as const };

export function HeroSplitProcess() {
  return (
    <section className="relative px-6 pt-24 md:pt-32 pb-32">
      <div className="max-w-7xl mx-auto">
        {/* TOP BLOCK: pill + headline + subtitle */}
        <div className="max-w-3xl mb-16">
          <span className="inline-flex items-center gap-2 rounded-full border border-black/8 bg-white px-3 py-1 text-xs font-medium text-[var(--text)]">
            <Sparkles className="size-3 text-[var(--accent)]" />
            For ambitious learners
          </span>
          <h1 className="mt-6 font-sans text-5xl md:text-6xl font-extrabold tracking-tight leading-[1.05] text-[var(--text)]">
            Skills that{" "}
            <span className="font-serif italic font-medium">compound.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-[var(--text-muted)]">
            An AI-paced learning platform built for the people the old internet left behind.
          </p>
        </div>

        {/* SPLIT: left product / right sticky process */}
        <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-12 lg:gap-16 items-start">
          {/* LEFT: dashboard preview with floating capability pills */}
          <div className="relative">
            <div
              className="absolute inset-x-12 -bottom-6 h-32 blur-3xl opacity-40"
              style={{ background: "var(--accent)" }}
              aria-hidden
            />
            <motion.div
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={ENTRANCE}
              className="relative rounded-3xl border border-black/8 bg-white shadow-2xl overflow-hidden"
            >
              <img
                src="https://picsum.photos/seed/dashboard-preview/1200/800"
                alt="Product dashboard"
                className="w-full"
              />
            </motion.div>

            {/* Floating capability pills — overlap top + bottom edges */}
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...ENTRANCE, delay: 0.2 }}
              className="absolute top-6 -left-4 inline-flex items-center gap-2 rounded-full bg-white border border-black/8 px-3.5 py-2 text-xs font-medium shadow-lg"
            >
              <span className="size-1.5 rounded-full bg-emerald-500" />
              AI tutor active
            </motion.div>
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...ENTRANCE, delay: 0.3 }}
              className="absolute bottom-6 -right-4 inline-flex items-center gap-2 rounded-full bg-[var(--text)] text-[var(--bg)] px-3.5 py-2 text-xs font-medium shadow-lg"
            >
              <Trophy className="size-3.5 text-[var(--accent)]" />
              Verified credential
            </motion.div>
          </div>

          {/* RIGHT: sticky process list */}
          <div className="lg:sticky lg:top-24 self-start">
            <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-muted)]">
              How it works
            </span>
            <ul className="mt-4 divide-y divide-black/5 border-t border-b border-black/5">
              {STEPS.map((s, i) => {
                const Icon = s.icon;
                return (
                  <motion.li
                    key={s.n}
                    initial={{ opacity: 0, x: 12 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true, amount: 0.6 }}
                    transition={{ ...ENTRANCE, delay: i * 0.05 }}
                    className="flex items-start gap-4 py-5"
                  >
                    <div className="grid place-items-center size-10 shrink-0 rounded-xl bg-[var(--text)]/[0.04] border border-black/5">
                      <Icon className="size-4 text-[var(--text)]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline gap-3">
                        <span className="text-xs font-mono text-[var(--text-muted)]">{s.n}</span>
                        <h3 className="font-sans text-base font-semibold text-[var(--text)]">{s.title}</h3>
                      </div>
                      <p className="mt-1 text-sm text-[var(--text-muted)] leading-relaxed">
                        {s.desc}
                      </p>
                    </div>
                  </motion.li>
                );
              })}
            </ul>

            {/* Outcome card — gives the sticky column a defined end */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.4 }}
              transition={ENTRANCE}
              className="mt-6 rounded-2xl border border-black/8 bg-white p-5 flex items-start gap-4"
            >
              <div className="grid place-items-center size-10 shrink-0 rounded-xl bg-[var(--accent)]/10">
                <Sparkles className="size-4 text-[var(--accent)]" />
              </div>
              <div className="flex-1">
                <div className="text-sm font-semibold text-[var(--text)]">
                  See it in action
                </div>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  4-min walkthrough. No signup required.
                </p>
              </div>
              <ArrowUpRight className="size-4 text-[var(--text-muted)]" />
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  );
}
```

## The sticky behavior

`lg:sticky lg:top-24 self-start` on the right column makes the process list pin to the viewport while the user scrolls past the (taller) dashboard preview on the left. This is the entire reason the pattern works — without sticky, the right column scrolls offscreen and you've just made an asymmetric grid.

`self-start` is critical inside a CSS grid — without it, the grid stretches the cell and `position: sticky` has nothing to stick within.

## Customization rules

- **Grid ratio is `[1.2fr_1fr]`** — left product gets ~55%, right narrative ~45%. Don't make them equal.
- **3-4 steps only.** 5+ steps overwhelm the right column and break the sticky height calc.
- **Each step is `[icon chip] [number + title] [one-liner]`** — no body copy, no sub-bullets.
- **Floating capability pills overlap the dashboard edge** (`-left-4`, `-right-4`) — overlapping reads as a product detail callout.
- **One pill is white-on-dark; the other dark-on-white.** Same shadow, opposite color — high-contrast pair signal.
- **Outcome card under the process** is the "Step 5 / payoff" anchor — it gives the sticky column a defined end.

## What NOT to change

- Do not put text in the LEFT column. The product is the only thing on the left.
- Do not animate the sticky column on scroll — `position: sticky` IS the animation
- Do not use accordion / expand-collapse for the steps — they must all be visible at once
- Do not add a CTA inside the right column (the page CTA is in the top block above the split)
- Do not skip the "outcome card" — the sticky column needs a footer or it floats forever
- Do not stack vertically on tablet — needs ≥1024px; below that, fall back to: top headline → product mockup → process list as plain stacked sections

## Cross-references

- See `recipes/hero-saas.md` for the simpler centered-hero alternative
- See `recipes/hero-fintech.md` for the split-with-widget variant (different structure)
- See `recipes/features-3step.md` — sister pattern as a standalone section
- See `recipes/button-premium.md` — the floating capability pills can use the same shadow stack
- See `tokens.md` "MOTION PRESETS" for the `ENTRANCE` ease used here
