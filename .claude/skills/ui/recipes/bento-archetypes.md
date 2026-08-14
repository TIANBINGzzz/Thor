# recipes/bento-archetypes.md — Five Named Bento Card Archetypes

**The taste-skill bento system.** A bento section is rarely just "4 cards in a grid" — premium bentos contain 5 recurring micro-archetypes, each with a signature interior layout AND a signature infinite-loop micro-animation. This recipe documents all five so you can mix-and-match instead of reinventing the same "icon + text" tile per cell.

Use alongside `features-bento.md` (which gives you the grid skeleton) — this recipe gives you the *contents* of the cells.

## When to use

- Inside any `features-bento.md` grid where some cells are dynamic / animated
- Product-tour sections where each card demonstrates a different capability
- Above-the-fold "everything we do" surface where each card is a glance-able teaser

**Don't use** all five in one section — pick 2-3 archetypes per bento. Five at once is a circus.

## The five archetypes

1. **The Intelligent List** — vertical stack with infinite auto-sorting via `layoutId`
2. **The Command Input** — search/AI bar cycling typewriter prompts + shimmer
3. **The Live Status** — scheduling/notification interface with breathing dots + overshoot popups
4. **The Wide Data Stream** — horizontal infinite carousel
5. **The Contextual UI (Focus Mode)** — staggered text-block highlight + float-in toolbar

---

## Archetype 1 — The Intelligent List

A vertical list that re-sorts itself every few seconds. The `layoutId` on each item makes Framer Motion animate the position swap as a smooth rearrangement, not a re-render.

```tsx
import { motion } from "framer-motion";
import { useEffect, useState } from "react";

const SEED = [
  { id: "a", label: "Onboarding flow", score: 92 },
  { id: "b", label: "Pricing page",    score: 87 },
  { id: "c", label: "Hero section",    score: 78 },
  { id: "d", label: "Footer redesign", score: 64 },
];

export function IntelligentList() {
  const [items, setItems] = useState(SEED);

  useEffect(() => {
    const id = setInterval(() => {
      setItems((cur) =>
        [...cur]
          .map((x) => ({ ...x, score: x.score + (Math.random() * 6 - 3) }))
          .sort((a, b) => b.score - a.score)
      );
    }, 2200);
    return () => clearInterval(id);
  }, []);

  return (
    <ul className="flex flex-col gap-2">
      {items.map((it) => (
        <motion.li
          key={it.id}
          layoutId={`il-${it.id}`}
          transition={{ type: "spring", stiffness: 380, damping: 30 }}
          className="flex items-center justify-between rounded-xl bg-white/80 backdrop-blur ring-1 ring-black/5 px-3 py-2 text-sm"
        >
          <span className="font-medium text-[var(--text)]">{it.label}</span>
          <span className="font-mono tabular-nums text-xs text-[var(--text-muted)]">
            {Math.round(it.score)}
          </span>
        </motion.li>
      ))}
    </ul>
  );
}
```

---

## Archetype 2 — The Command Input

A static-looking search/AI input that cycles through a list of prompts via the typewriter effect, with a subtle shimmer over the bar to signal "live."

```tsx
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

const PROMPTS = [
  "Summarize last week's sales calls",
  "Draft a follow-up to the design review",
  "What changed in the staging deploy?",
  "Find unanswered customer questions",
];

export function CommandInput() {
  const [pIdx, setPIdx] = useState(0);
  const [typed, setTyped] = useState("");

  useEffect(() => {
    const target = PROMPTS[pIdx];
    let i = 0;
    const tick = setInterval(() => {
      i++;
      setTyped(target.slice(0, i));
      if (i >= target.length) {
        clearInterval(tick);
        setTimeout(() => {
          setTyped("");
          setPIdx((x) => (x + 1) % PROMPTS.length);
        }, 1400);
      }
    }, 38);
    return () => clearInterval(tick);
  }, [pIdx]);

  return (
    <div className="relative overflow-hidden rounded-2xl bg-white ring-1 ring-black/5 p-3 flex items-center gap-3">
      <Sparkles className="size-4 text-[var(--accent)] shrink-0" />
      <div className="flex-1 min-w-0 text-sm font-medium text-[var(--text)] truncate">
        {typed}
        <span className="inline-block w-[1px] h-3 ml-0.5 bg-[var(--text)] animate-pulse align-middle" />
      </div>
      <kbd className="text-[10px] font-mono text-[var(--text-muted)] bg-black/5 rounded px-1.5 py-0.5 shrink-0">
        ⌘K
      </kbd>
      {/* shimmer */}
      <motion.div
        aria-hidden
        initial={{ x: "-120%" }}
        animate={{ x: "120%" }}
        transition={{ duration: 2.4, repeat: Infinity, ease: "linear" }}
        className="absolute inset-y-0 w-1/3 pointer-events-none"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.6) 50%, transparent 100%)",
        }}
      />
    </div>
  );
}
```

---

## Archetype 3 — The Live Status

A "what's happening right now" surface — breathing status dots + an overshoot-spring notification popup that arrives every few seconds.

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";

const NOTIFS = [
  "Build #4821 deployed to prod",
  "New signup from acme.io",
  "PR #312 ready for review",
];

export function LiveStatus() {
  const [n, setN] = useState<string | null>(null);

  useEffect(() => {
    let i = 0;
    const id = setInterval(() => {
      setN(NOTIFS[i % NOTIFS.length]);
      i++;
      setTimeout(() => setN(null), 2400);
    }, 3600);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="relative h-full min-h-[180px] rounded-2xl bg-white ring-1 ring-black/5 p-4">
      {/* breathing dots row */}
      <div className="flex items-center gap-3 text-xs text-[var(--text-muted)]">
        <span className="relative grid place-items-center size-2">
          <span className="absolute inset-0 rounded-full bg-emerald-500 animate-ping opacity-60" />
          <span className="relative size-2 rounded-full bg-emerald-500" />
        </span>
        Live · 3 services healthy
      </div>

      {/* overshoot-spring notification */}
      <AnimatePresence>
        {n && (
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.96 }}
            animate={{
              opacity: 1, y: 0, scale: 1,
              transition: { type: "spring", stiffness: 320, damping: 18, mass: 0.7 },
            }}
            exit={{ opacity: 0, y: 8, transition: { duration: 0.18 } }}
            className="absolute left-3 right-3 bottom-3 rounded-xl bg-[var(--text)] text-[var(--bg)] px-3 py-2.5 shadow-lg flex items-center gap-2 text-xs font-medium"
          >
            <CheckCircle2 className="size-4 text-emerald-400" />
            {n}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
```

---

## Archetype 4 — The Wide Data Stream

A spans-2-columns bento card with a horizontal infinite carousel — logos, tickers, recent activity. Use `x: ["0%", "-100%"]` with `repeat: Infinity` for the seamless loop. Duplicate the content track so the loop doesn't show a seam.

```tsx
import { motion } from "framer-motion";

const TICKER = [
  "+ Stripe → integrated",
  "+ Linear → synced",
  "+ Notion → indexed",
  "+ Figma → connected",
  "+ Slack → live",
  "+ GitHub → mirrored",
];

export function WideDataStream() {
  const items = [...TICKER, ...TICKER]; // duplicate for seamless loop

  return (
    <div className="relative overflow-hidden rounded-2xl bg-white ring-1 ring-black/5 py-5">
      {/* edge fades */}
      <div
        aria-hidden
        className="absolute inset-y-0 left-0 w-12 z-10 pointer-events-none"
        style={{
          background:
            "linear-gradient(to right, rgb(255 255 255), transparent)",
        }}
      />
      <div
        aria-hidden
        className="absolute inset-y-0 right-0 w-12 z-10 pointer-events-none"
        style={{
          background:
            "linear-gradient(to left, rgb(255 255 255), transparent)",
        }}
      />

      <motion.div
        className="flex gap-6 whitespace-nowrap text-sm font-mono text-[var(--text-muted)] w-max"
        animate={{ x: ["0%", "-50%"] }}
        transition={{ duration: 22, repeat: Infinity, ease: "linear" }}
      >
        {items.map((t, i) => (
          <span key={i} className="shrink-0">
            {t}
          </span>
        ))}
      </motion.div>
    </div>
  );
}
```

---

## Archetype 5 — The Contextual UI (Focus Mode)

A snippet of "your real interface" — text blocks where one paragraph highlights on a stagger, then a floating action toolbar slides in offering an action on the highlighted region.

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState } from "react";
import { Wand2, MessageSquare } from "lucide-react";

const PARAS = [
  "Last quarter's launch missed its target by 12%, primarily because retention dropped after week two.",
  "The data team flagged a correlation between onboarding length and 30-day churn.",
  "We should test a shorter onboarding variant before the next campaign.",
];

export function FocusMode() {
  const [active, setActive] = useState(0);
  const [showBar, setShowBar] = useState(false);

  useEffect(() => {
    const id = setInterval(() => {
      setShowBar(false);
      setActive((x) => (x + 1) % PARAS.length);
      setTimeout(() => setShowBar(true), 600);
    }, 3400);
    setTimeout(() => setShowBar(true), 600);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="relative rounded-2xl bg-white ring-1 ring-black/5 p-5">
      <div className="flex flex-col gap-3 text-sm leading-relaxed">
        {PARAS.map((p, i) => (
          <motion.p
            key={i}
            animate={{
              opacity: i === active ? 1 : 0.35,
              backgroundColor:
                i === active ? "rgba(250, 204, 21, 0.18)" : "rgba(0,0,0,0)",
            }}
            transition={{ duration: 0.4 }}
            className="rounded-md px-2 py-1 -mx-2"
          >
            {p}
          </motion.p>
        ))}
      </div>

      <AnimatePresence>
        {showBar && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            transition={{ type: "spring", stiffness: 360, damping: 26 }}
            className="absolute left-1/2 -translate-x-1/2 bottom-3 inline-flex items-center gap-1 rounded-full bg-[var(--text)] text-[var(--bg)] px-1 py-1 shadow-lg"
          >
            <button className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium hover:bg-white/10">
              <Wand2 className="size-3.5" /> Rewrite
            </button>
            <button className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium hover:bg-white/10">
              <MessageSquare className="size-3.5" /> Comment
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
```

---

## Customization rules

- **Pick 2-3 archetypes per bento.** Five at once = circus. The rule of thumb: one "loud" archetype (Wide Data Stream OR Live Status) + one "quiet" archetype (Intelligent List OR Focus Mode) + one "input-shaped" archetype (Command Input).
- **All animations are infinite-loop or auto-cycling** — these are demos, not buttons. Don't wait for user interaction.
- **Animation durations 2-4 seconds per cycle.** Faster reads as flicker, slower reads as broken.
- **Transform + opacity only.** Never animate `width`, `height`, `top`, `left`, `box-shadow` (use `layoutId` if you need positional change).
- **Edge fades on horizontal carousels** — without them the loop looks like a janky cut at the viewport edge.
- **Wrap any of these in `recipes/double-bezel-card.md`** to graduate from "good bento" to "premium taste" mode.

## What NOT to change

- Don't make any of them interactive (these are passive demos in a bento — interaction belongs in the actual product)
- Don't add hover effects that pause the loop (users won't hover; they'll keep scrolling)
- Don't use `Math.random()` outside `useEffect` — it'll re-jitter on every render
- Don't stack 4+ infinite animations in one section — performance dies, attention dies
- Don't replace `layoutId` on the Intelligent List with manual position interpolation — `layoutId` is the only thing that makes the rearrangement smooth

## Cross-references

- See `recipes/features-bento.md` for the grid skeleton these cells live in
- See `recipes/double-bezel-card.md` to wrap an archetype for "premium taste" mode
- See `tokens.md` "Motion presets" — `SPRING_OVERSHOOT` for the Live Status popup
- See `anti-slop.md` "static bento cards" anti-pattern (most AI bentos ship cells that never animate)
