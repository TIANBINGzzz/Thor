# architecture.md — React Architecture for /ui Recipes

**Read this only if you're shipping into Next.js App Router (RSC).** Vite, CRA, and Next Pages Router users can use the recipes as-is — skip this file.

This is a reference doc, not a recipe. It explains where `'use client'` belongs, why putting it in the wrong place destroys the build, and how to keep premium motion components without dragging your whole tree into the client bundle.

---

## When this matters — quick decision tree

- **Vite / CRA project?** → Skip this file. Recipes work as-is. Everything is "client" by default.
- **Next.js Pages Router (`pages/` directory)?** → Skip this file. Same as above.
- **Next.js App Router (`app/` directory, RSC)?** → Read on. This is where the wrong default kills performance.
- **Remix, TanStack Start, Astro islands?** → Read on, the principles apply. Names of the directives differ.

---

## The RSC client/server boundary

In App Router, **every component is a Server Component by default.** That's a good thing — they ship zero JS to the browser. But Server Components have hard limits.

Server Components CANNOT:
- Use `useState`, `useEffect`, `useRef`, `useReducer`, `useMemo`, `useCallback`
- Use `useMotionValue`, `useScroll`, `useTransform`, `useSpring` (Framer Motion hooks)
- Use any browser API (`window`, `document`, `localStorage`, `IntersectionObserver`)
- Attach event handlers (`onClick`, `onMouseMove`, `onChange`, etc.)
- Render `motion.div`, `<AnimatePresence>`, or anything from `framer-motion` that needs the runtime

If a component needs ANY of the above, the FILE that defines it must start with:

```tsx
'use client';
```

That directive marks the file (and everything it imports as part of its tree) as a Client Component boundary.

**Every recipe in this skill that uses Framer Motion needs `'use client'`** at the top of the file the component lives in. The recipes already include it. Don't strip it.

---

## Isolation pattern (CRITICAL for performance)

The mistake that kills RSC builds: putting `'use client'` at the top of `page.tsx` or `layout.tsx`. This pulls the ENTIRE page tree into the client bundle — every static section, every paragraph, every footer link — even though only the hero needs interactivity. You lose the whole point of RSC.

**The right pattern:** keep pages and layouts as Server Components. Extract every interactive piece into its own client file. Import client components from server pages — Next.js handles the boundary automatically.

```
app/
├── page.tsx                    ← Server Component (renders layout)
└── components/
    ├── Hero.tsx                ← 'use client' (Framer Motion entrance)
    ├── MagneticCTA.tsx         ← 'use client' (cursor-driven motion)
    ├── Pricing.tsx             ← Server Component (static markup)
    ├── FeaturesGrid.tsx        ← Server Component (static markup)
    └── SpotlightCard.tsx       ← 'use client' (used inside FeaturesGrid)
```

A Server Component can import and render a Client Component. A Client Component can render Server Components passed to it as `children` props (but cannot import them directly). Use the children-prop pattern when you need a client wrapper around server content.

```tsx
// app/page.tsx — Server Component (NO 'use client')
import { Hero } from './components/Hero';
import { FeaturesGrid } from './components/FeaturesGrid';
import { Pricing } from './components/Pricing';

export default function Page() {
  return (
    <>
      <Hero />
      <FeaturesGrid />
      <Pricing />
    </>
  );
}
```

```tsx
// app/components/Hero.tsx — Client Component
'use client';

import { motion } from 'framer-motion';

export function Hero() {
  return (
    <motion.section initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      {/* ... */}
    </motion.section>
  );
}
```

Result: only `Hero.tsx` ships JS. `Pricing` and `FeaturesGrid` are HTML-only.

---

## Continuous-input animations

(cursor tracking / parallax / magnetic hover / scroll-driven transforms)

For anything driven by `mousemove`, `scroll`, or `requestAnimationFrame`, **you MUST use Framer Motion's `useMotionValue` + `useTransform`** — never `useState`.

Why: `useState` triggers a React re-render on every change. `mousemove` fires 60–200 times per second. Re-rendering the component subtree every mousemove tanks fps on mobile and burns battery on desktop.

`useMotionValue` writes directly to a motion value that the GPU compositor reads — no React render involved. The DOM updates without React knowing.

**Wrong:**

```tsx
const [pos, setPos] = useState({ x: 0, y: 0 });
function onMove(e) {
  setPos({ x: e.clientX, y: e.clientY }); // re-renders 100x/sec — DON'T
}
return <div style={{ transform: `translate(${pos.x}px, ${pos.y}px)` }} />;
```

**Right:**

```tsx
const x = useMotionValue(0);
const y = useMotionValue(0);
function onMove(e) {
  x.set(e.clientX); // no re-render — DOM updated by Framer
  y.set(e.clientY);
}
return <motion.div style={{ x, y }} />;
```

This rule applies to: magnetic buttons, spotlight borders, cursor parallax, mouse-driven gradients, scroll-bound transforms, drag interactions.

---

## Where data fetching lives

In App Router, async data fetching belongs in Server Components. Never `fetch` in a client component unless the data is real-time (chat, stock prices, presence).

```tsx
// app/page.tsx — Server Component
async function Page() {
  const plans = await db.plans.findAll(); // server-side, cached
  return <Pricing plans={plans} />;       // pass DOWN as props
}
```

```tsx
// app/components/Pricing.tsx — can be Server or Client; receives data as prop
export function Pricing({ plans }: { plans: Plan[] }) {
  return <ul>{plans.map(p => <li key={p.id}>{p.name}</li>)}</ul>;
}
```

For real-time / mutating data on the client, reach for SWR or TanStack Query inside a Client Component. Don't `useEffect(fetch, [])` — that's the 2020 pattern and it leaks.

---

## Performance

### Backdrop-blur on scrolling content

`backdrop-filter: blur()` is GPU-expensive on every paint. When applied to a scrolling element (a card mid-page, a section background that moves with scroll), the GPU repaints the blurred region every frame the user scrolls — fps tanks, especially on mobile.

Apply backdrop-blur ONLY on elements that don't move with scroll: `position: fixed` / `position: sticky` nav bars, modal overlays, floating tooltips. Never on cards, sections, or any container inside the normal document flow.

For Liquid Glass specifically, see `tokens.md` § Liquid Glass recipe — it's only valid on sticky nav and floating overlays.

---

## Common mistakes

- **"I'll just put `'use client'` at the top of `layout.tsx`."** Wrong — defeats RSC entirely. Every page in the app becomes client-rendered. Extract interactive pieces into leaf components instead.
- **"I need state for hover."** Wrong — use Tailwind `hover:` utilities or Framer's `whileHover` prop. State on hover causes unnecessary renders.
- **"I need `useState` for mouse position."** Wrong — use `useMotionValue`. See above.
- **"I need `useEffect` to fetch data."** Wrong in App Router — use a Server Component with `async` directly. Reserve `useEffect` for true side effects (subscriptions, listeners).
- **"My client component imports a server component directly."** Not allowed. Pass server components as `children` props to client wrappers.
- **"I marked one component `'use client'` and now its imports are also client."** Correct — that's how the boundary works. Keep client components as leaves, not roots.

---

## Cross-references

- `SKILL.md` — the procedure (recipes you compose into a page)
- `tokens.md` — design tokens (CSS variables work in both server and client components)
- `anti-slop.md` — `useState` for continuous input is BANNED
- `recipes/magnetic-button.md`, `recipes/spotlight-border-card.md`, `recipes/sticky-scroll-stack.md` — recipes that depend on the isolation pattern documented here
