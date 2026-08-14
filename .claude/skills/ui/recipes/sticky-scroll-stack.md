# recipes/sticky-scroll-stack.md — Sticky Scroll Card Stack

**The Apple product-page / Stripe Sessions pattern.** A vertical sequence of full-bleed cards where each one sticks to the top of the viewport as the user scrolls, then gets covered by the next card sliding up over it. Previous cards subtly recede (scale down + slight blur) so the active card always feels foreground. The mechanic is pure `position: sticky` with staggered `top` values — no scroll listeners, no `IntersectionObserver`.

## When to use

- "How it works" / multi-step product walkthrough (3–5 steps)
- Feature reveal where each feature deserves a full-screen moment
- Onboarding marketing section ("Sign up → Connect → Build → Ship")
- Comparison narrative (problem → old way → our way → result)

**Do NOT use:** with more than 5 cards (scroll fatigue), on mobile-only pages (the effect is desktop-leading), or as a replacement for a real features grid (use `features-bento.md` for parallel content).

## The signature: stacked sticky, not animated

The trick is CSS, not JS. Each card has `position: sticky` with `top` increasing per index — card 0 sticks at `top: 4rem`, card 1 at `top: 5rem`, card 2 at `top: 6rem`. As you scroll, card 0 sticks first; card 1 reaches its sticky point and slides over card 0 (because it sticks lower); same for card 2. Framer Motion only adds the recede effect (scale + blur) on the cards being covered.

## Code

```tsx
'use client';

import { motion, useScroll, useTransform } from 'framer-motion';
import { useRef } from 'react';

const CARD_HEIGHT_VH = 80; // each card occupies ~80vh of scroll

const STEPS = [
  {
    eyebrow: 'Step 01',
    title: 'Onboard in 90 seconds',
    body: 'Sign in with GitHub. We pull your repos, infer your stack, and pre-fill a workspace. No CSV uploads, no IT tickets.',
    image: '/walkthrough/onboard.png',
    accent: 'oklch(70% 0.15 145)',
  },
  {
    eyebrow: 'Step 02',
    title: 'Build with one prompt',
    body: 'Describe the change. We open a draft PR with passing tests and a preview URL. You review the diff, not the boilerplate.',
    image: '/walkthrough/build.png',
    accent: 'oklch(68% 0.18 250)',
  },
  {
    eyebrow: 'Step 03',
    title: 'Test against production traffic',
    body: 'Replay last week of real requests against your branch. See latency deltas, error budgets, and breaking schema changes before merge.',
    image: '/walkthrough/test.png',
    accent: 'oklch(72% 0.16 60)',
  },
  {
    eyebrow: 'Step 04',
    title: 'Ship with the rollback baked in',
    body: 'Progressive rollout, automatic canary analysis, one-click revert. Deploy on Friday afternoon — we mean it.',
    image: '/walkthrough/ship.png',
    accent: 'oklch(63% 0.18 38)',
  },
];

export function StickyScrollStack() {
  const wrapRef = useRef<HTMLDivElement>(null);

  return (
    <section
      ref={wrapRef}
      className="relative px-6"
      style={{ height: `calc(${STEPS.length * CARD_HEIGHT_VH}vh + 100vh)` }}
    >
      <div className="mx-auto max-w-5xl">
        {STEPS.map((step, i) => (
          <StackCard key={i} index={i} total={STEPS.length} step={step} wrapRef={wrapRef} />
        ))}
      </div>
    </section>
  );
}

function StackCard({
  index,
  total,
  step,
  wrapRef,
}: {
  index: number;
  total: number;
  step: (typeof STEPS)[number];
  wrapRef: React.RefObject<HTMLElement>;
}) {
  const cardRef = useRef<HTMLDivElement>(null);

  // Track scroll progress of THIS card relative to the section
  const { scrollYProgress } = useScroll({
    target: cardRef,
    offset: ['start 20%', 'end start'],
  });

  // Cards being covered scale down + blur slightly. Active card stays at 1.
  const scale = useTransform(scrollYProgress, [0, 1], [1, 0.92 - index * 0.01]);
  const blur = useTransform(scrollYProgress, [0, 1], ['0px', '2px']);
  const opacity = useTransform(scrollYProgress, [0, 0.6, 1], [1, 1, 0.6]);

  // Stagger the sticky offset so cards layer instead of replace
  const top = `calc(4rem + ${index * 1}rem)`;

  return (
    <div
      ref={cardRef}
      style={{ position: 'sticky', top, marginBottom: `${CARD_HEIGHT_VH * 0.5}vh` }}
    >
      <motion.article
        style={{ scale, opacity, filter: useTransform(blur, (b) => `blur(${b})`) }}
        className="relative overflow-hidden rounded-3xl border border-black/8 bg-[var(--bg-elevated)] shadow-[0_30px_80px_-30px_rgba(0,0,0,0.35)] will-change-transform"
      >
        {/* Accent glow tied to this step's color */}
        <div
          aria-hidden
          className="pointer-events-none absolute -top-24 right-0 h-72 w-72 rounded-full blur-3xl opacity-30"
          style={{ background: step.accent }}
        />

        <div className="grid gap-10 p-10 md:grid-cols-2 md:p-14 md:gap-14">
          <div className="flex flex-col justify-center">
            <span
              className="inline-flex w-fit items-center gap-2 rounded-full border border-black/8 px-3 py-1 text-xs font-medium tracking-wide text-[var(--text-muted)]"
            >
              <span
                className="size-1.5 rounded-full"
                style={{ background: step.accent }}
              />
              {step.eyebrow}
            </span>
            <h3 className="mt-5 font-sans text-3xl md:text-4xl font-extrabold tracking-tight leading-[1.1] text-[var(--text)]">
              {step.title}
            </h3>
            <p className="mt-4 text-base text-[var(--text-muted)] max-w-md">
              {step.body}
            </p>
          </div>

          <div className="relative aspect-[4/3] overflow-hidden rounded-2xl bg-[var(--bg)] border border-black/5">
            <img
              src={step.image}
              alt=""
              className="absolute inset-0 h-full w-full object-cover"
            />
          </div>
        </div>
      </motion.article>
    </div>
  );
}
```

## Why this works

1. **`position: sticky` does the stacking** — the browser handles the hard part for free. Each card detaches from flow at its `top` value and rides the viewport.
2. **Staggered `top` (`4rem + i * 1rem`)** is the only reason cards layer instead of replacing each other. Without the stagger, each card displaces the previous.
3. **Section height is explicit** (`STEPS.length * 80vh + 100vh`) — gives the browser scroll room for each card to live through its sticky range.
4. **Framer Motion only handles the recede** — scale, blur, opacity. The stacking itself is CSS. This separation keeps it 60fps.
5. **`useScroll` with a target ref** scopes progress per card — no global listeners, no IO observers.
6. **`will-change: transform`** on the motion article promotes to a GPU layer; without it the blur causes repaints.

## Why most clones look bad

1. They use `IntersectionObserver` + manual `position: fixed` swaps → the swap moment is always janky.
2. All cards have identical `top` → they replace each other instead of stacking.
3. They scale up the active card instead of scaling down the covered ones → makes the active one feel cramped.
4. They animate `top` directly instead of letting `position: sticky` do it → fights the browser, jitters at scroll speed.
5. They use a heavy parallax library for what `sticky` does in 4 lines of CSS.

## Customization rules

- **3–5 cards.** 6+ becomes scroll fatigue.
- **`top` stagger:** 0.5rem–1.5rem per card. Smaller = tighter stack; larger = each card has its own pedestal.
- **Scale recede:** `0.92 - i * 0.01`. Don't go below `0.85` — the receded card disappears.
- **Blur:** 1–3px max. More than 3px and the receded cards become invisible mush.
- **Card content:** keep titles ≤6 words, body ≤2 sentences. The visual is the hero, not the text.
- **One accent per card.** Different accent colors per step is fine here (each card is its own scene) — but stay within `tokens.md` palette range.

## RSC / Next.js App Router

`'use client'` at the top of the file (uses `useScroll`, `useRef`). The data array (`STEPS`) can stay in this file or get passed in as a prop from a server component if it's CMS-driven. See `architecture.md`.

## What NOT to change

- Don't remove the `position: sticky` — it IS the mechanic
- Don't make every card the same `top` — kills the stack
- Don't animate `width` or `height` on the cards — must be `transform: scale`
- Don't omit the section's explicit height — the cards collapse out of order
- Don't add a snap-scroll modifier — fights the recede animation
- Don't put a video in the card image slot unless it auto-pauses when out of view (perf disaster otherwise)

## Cross-references

- `tokens.md` — palettes, accent ranges, motion presets
- `recipes/features-3step.md` — alternative if you want bracket-tracker treatment instead of stack
- `anti-slop.md` — "Animate ONLY transform + opacity"; "Never animate top/left/width/height"
- `architecture.md` — `'use client'` isolation pattern
