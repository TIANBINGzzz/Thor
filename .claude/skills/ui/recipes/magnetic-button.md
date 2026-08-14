# recipes/magnetic-button.md — Magnetic Cursor Button

**The Linear / Vercel / Awwwards-tier pattern.** The button physically pulls toward the cursor as it approaches, then springs back when the cursor leaves. Inner content (text + icon) gets a second, smaller magnetic pull for a layered "the label catches up to the shell" effect. Used everywhere on premium product sites — and almost always implemented wrong (with `useState`, which kills mobile fps).

## When to use

- Primary hero CTA on a marketing site (one per page — not every button)
- "Book a call" / "Get started" on agency sites
- Final-CTA section before footer
- Pricing-card primary action on premium tiers

**Do NOT use on:** secondary buttons, nav links, dashboard / app buttons, anything with high click frequency. Magnetism is a moment, not a baseline.

## The signature: spring-smoothed motion values, never useState

The button tracks the cursor's position relative to its own center, scales that delta down to ~30%, smooths through a spring, and translates the surface. The inner content does the same with an even smaller scale (~15%) for parallax. **All of this runs through Framer Motion's `useMotionValue` — never `useState` — because re-rendering on every `mousemove` tanks performance and is explicitly banned in `anti-slop.md`.**

## Code

```tsx
'use client';

import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import { useRef } from 'react';

const SPRING = { stiffness: 200, damping: 20, mass: 0.5 };
const PULL_STRENGTH = 0.3;       // shell pulls 30% of cursor delta
const INNER_PULL = 0.15;         // label pulls 15% (half of shell)

export function MagneticButton({
  children = 'Get started',
  href = '#start',
}: {
  children?: React.ReactNode;
  href?: string;
}) {
  const ref = useRef<HTMLAnchorElement>(null);

  // Raw motion values — driven by mousemove, NEVER useState
  const x = useMotionValue(0);
  const y = useMotionValue(0);

  // Spring-smoothed shell translate
  const sx = useSpring(x, SPRING);
  const sy = useSpring(y, SPRING);

  // Inner content gets a softer pull (half the shell's)
  const ix = useTransform(sx, (v) => v * (INNER_PULL / PULL_STRENGTH));
  const iy = useTransform(sy, (v) => v * (INNER_PULL / PULL_STRENGTH));

  function onMove(e: React.MouseEvent<HTMLAnchorElement>) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    x.set((e.clientX - cx) * PULL_STRENGTH);
    y.set((e.clientY - cy) * PULL_STRENGTH);
  }

  function onLeave() {
    x.set(0);
    y.set(0);
  }

  return (
    <motion.a
      ref={ref}
      href={href}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      style={{ x: sx, y: sy }}
      className="relative inline-flex items-center gap-2 rounded-full bg-[var(--text)] px-7 py-3.5 text-sm font-medium text-[var(--bg)] shadow-[0_10px_30px_-10px_rgba(0,0,0,0.45)] hover:shadow-[0_18px_40px_-12px_rgba(0,0,0,0.55)] transition-shadow will-change-transform"
    >
      <motion.span
        style={{ x: ix, y: iy }}
        className="inline-flex items-center gap-2 will-change-transform"
      >
        {children}
        <ArrowRight className="size-4" />
      </motion.span>
    </motion.a>
  );
}
```

## Why most clones look bad

1. **They use `useState` for x/y.** Every `mousemove` re-renders the whole component subtree. Mobile fps craters, jank everywhere.
2. **No inner-content pull.** A monolithic translate looks robotic. The 2-layer parallax (shell + label) is what makes it feel physical.
3. **Linear easing or no spring.** The button snaps to the cursor like a magnet, then back like a slingshot — wrong feel. Spring gives it the "pulled through honey" quality.
4. **Pull strength too high (>0.5).** The button detaches from its slot and the layout breaks. 0.25–0.35 is the sweet spot.
5. **Forgot `will-change: transform`.** Browser doesn't promote to GPU layer; you get repaints instead of compositor frames.
6. **They animate `top/left`** instead of `transform`. See `anti-slop.md` — layout properties cause reflow on every frame.

## Customization rules

- **PULL_STRENGTH:** 0.25–0.35. Below 0.2 = invisible. Above 0.4 = button escapes.
- **Spring config:** stiffness 180–220, damping 18–24. Stiffer = snappier; softer = more "honeyed".
- **INNER_PULL:** keep at ~50% of shell pull. Equal pull = no parallax. Zero = monolithic.
- **Shadow stack:** must intensify on hover. The shadow shift sells the lift even when translate is small.
- **Use sparingly:** ONE magnetic button per page. Magnetism is hero-tier; everything else uses static `hover:` states.

## Pair with `recipes/button-premium.md`

The magnetic shell sits on top of a premium button (deep-tinted shadow + ring + slight gradient). Magnetism without the premium shadow stack feels light; the shadow stack without magnetism feels static. Layer both.

```tsx
// inside MagneticButton — replace the className with the button-premium stack
className="relative inline-flex items-center gap-2 rounded-full
  bg-gradient-to-b from-[var(--text)] to-[oklch(15%_0.01_250)]
  px-7 py-3.5 text-sm font-medium text-[var(--bg)]
  ring-1 ring-inset ring-white/10
  shadow-[0_10px_30px_-10px_rgba(0,0,0,0.45),inset_0_1px_0_rgba(255,255,255,0.12)]
  hover:shadow-[0_18px_40px_-12px_rgba(0,0,0,0.55),inset_0_1px_0_rgba(255,255,255,0.18)]
  transition-shadow will-change-transform"
```

## RSC / Next.js App Router

This component uses Framer Motion + event handlers, so the FILE that exports it MUST start with `'use client'`. Import it into a server `page.tsx`; do NOT mark the page itself as a client component (you'd pull the whole tree into the client bundle). See `architecture.md` for the isolation pattern.

## What NOT to change

- Don't replace `useMotionValue` with `useState` — performance critical (re-renders kill mobile fps)
- Don't remove the spring — raw motion values look mechanical
- Don't apply magnetism to multiple buttons in the same viewport — visual noise
- Don't animate `top`/`left` — must be `transform` (`x`/`y`)
- Don't forget `onMouseLeave` reset — button gets stuck offset on fast cursor exits
- Don't omit `will-change: transform` — without it the browser repaints instead of compositing

## Mobile / accessibility

- On touch devices `mousemove` doesn't fire; the button stays at its origin (correct fallback — no behavior change needed).
- Respect `prefers-reduced-motion` if you want extra polish: skip the spring and zero the pull.

```tsx
import { useReducedMotion } from 'framer-motion';
// inside the component:
const reduce = useReducedMotion();
const effectivePull = reduce ? 0 : PULL_STRENGTH;
```

## Cross-references

- `tokens.md` — `SPRING_SMOOTH` motion preset (stiffness 200 / damping 20 matches)
- `recipes/button-premium.md` — the shadow / ring / gradient stack to layer underneath
- `anti-slop.md` — "useState for continuous-input is BANNED"; "Animate ONLY transform + opacity"
- `architecture.md` — `'use client'` isolation pattern for App Router
