# recipes/text-roll.md — Brand-Swap Word Roll

**The Amena pattern.** A noun in your headline rolls between values inside a fixed pill that resizes per word. Used for "we build for X" / agency hero patterns.

## When to use

- Agency hero: "We build for [ROTATING BRANDS]"
- Multi-vertical SaaS: "Built for [Designers/Engineers/Managers]"
- Pricing toggle moments
- Trust-by reels

## The signature: pill width animates with content

Most clones miss this — the pill width MUST animate with the layout prop to fit each word's natural width. Without that, all words have to be the same length.

## Code

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState } from "react";

const SPRING = { type: "spring" as const, stiffness: 320, damping: 30 };
const HOLD_MS = 1800; // hold each word 1.8s before swap

export function BrandRoll({ words = ["Designers", "Engineers", "Founders", "Studios"] }: { words?: string[] }) {
  const [i, setI] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setI((p) => (p + 1) % words.length), HOLD_MS);
    return () => clearInterval(t);
  }, [words.length]);

  return (
    <h1 className="font-sans text-5xl md:text-7xl font-extrabold tracking-tight leading-[1.05]">
      Built for{" "}
      {/* The pill — width animates via `layout` */}
      <motion.span
        layout
        transition={SPRING}
        className="inline-flex items-center justify-center bg-[var(--accent)] text-[var(--accent-fg)] rounded-2xl px-5 py-1.5 align-middle overflow-hidden"
      >
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={words[i]}
            initial={{ y: "100%", opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: "-100%", opacity: 0 }}
            transition={{ duration: 0.45, ease: [0.65, 0, 0.35, 1] }}
            className="block"
          >
            {words[i]}
          </motion.span>
        </AnimatePresence>
      </motion.span>
      .
    </h1>
  );
}
```

## With brand logos instead of text (the original Amena variant)

```tsx
import { YouTubeLogo, XLogo, InstagramLogo, TikTokLogo } from "./brand-logos";

const BRANDS = [
  { name: "YouTube", Logo: YouTubeLogo },
  { name: "X", Logo: XLogo },
  { name: "Instagram", Logo: InstagramLogo },
  { name: "TikTok", Logo: TikTokLogo },
];

export function BrandLogoRoll() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((p) => (p + 1) % BRANDS.length), 1800);
    return () => clearInterval(t);
  }, []);
  const { Logo, name } = BRANDS[i];

  return (
    <h1 className="font-sans text-5xl md:text-6xl font-bold leading-tight">
      Creating{" "}
      <motion.span
        layout
        transition={SPRING}
        className="inline-flex items-center justify-center bg-white border border-black/8 rounded-full px-6 py-2 align-middle overflow-hidden"
      >
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={name}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "-100%" }}
            transition={{ duration: 0.45, ease: [0.65, 0, 0.35, 1] }}
            className="flex items-center gap-2"
          >
            <Logo className="h-7" />
            <span className="text-2xl">{name}</span>
          </motion.span>
        </AnimatePresence>
      </motion.span>{" "}
      content.
    </h1>
  );
}
```

## Why most clones look bad

1. They animate `opacity` only (no vertical roll = no "physical reel" feel)
2. They don't use `layout` on the parent (so pill width can't change → all words must be same length)
3. They use `mode="wait"` (causes a gap between words instead of overlapping roll)
4. They use cubic ease-in-out (looks soft and AI-generated; want sharp slot-machine ease)

## Customization rules

- **Hold time:** 1500-2000ms. Shorter = readers can't keep up.
- **Transition duration:** 400-500ms.
- **Ease:** `[0.65, 0, 0.35, 1]` (sharp ease) OR spring with high stiffness
- **`mode="popLayout"`** is required (not `mode="wait"`)
- **`initial={false}`** on AnimatePresence — first word doesn't animate in

## What NOT to change

- Don't remove `layout` on the parent pill
- Don't change `mode="popLayout"` to `mode="wait"`
- Don't animate opacity only (must include vertical translate)
- Don't put more than 5-6 words in the rotation (cycle gets too long)

## Cross-references

- See `tokens.md` for accent color and motion principles
- See `recipes/morphing-button.md` for related layout-morph pattern
- See `recipes/hero-saas.md` to use this inside a hero section
