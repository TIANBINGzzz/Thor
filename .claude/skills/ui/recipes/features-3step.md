# recipes/features-3step.md — "How It Works" 3-Step Flow

**Linear narrative for explaining a process.** Adapted from jameslaurents "How it works section concept", longjohn-currency, Vercel.

## When to use

- Explaining a sequential process (sign up → upload → publish)
- Onboarding flow preview on a marketing page
- When the product has a clear before/after journey
- User says: "how it works", "process", "steps", "flow"

## Structure

- 3 cards, side by side on desktop / stacked mobile
- Sticky scroll-synced bracket tracker on the left margin (premium signal)
- Each card has: numbered badge + headline + 2-line description + visual

## Code (with sticky bracket tracker)

```tsx
import { motion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";

export function Features3Step() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start center", "end center"] });
  const bracketY = useTransform(scrollYProgress, [0, 1], ["0%", "66.67%"]);

  return (
    <section ref={ref} className="px-6 py-32 bg-[var(--bg)]">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <span className="text-sm font-medium text-[var(--accent)] uppercase tracking-wider">
            How it works
          </span>
          <h2 className="mt-3 font-sans text-4xl md:text-5xl font-bold tracking-tight">
            Three steps. <span className="font-serif italic font-medium">That's it.</span>
          </h2>
        </div>

        {/* Bracket tracker (desktop only) */}
        <div className="relative">
          <div className="hidden md:block absolute left-0 top-0 bottom-0 w-px bg-black/10" aria-hidden>
            <motion.div
              className="absolute left-0 w-1 -translate-x-px bg-[var(--accent)]"
              style={{ top: bracketY, height: "33%" }}
            />
          </div>

          <div className="grid md:grid-cols-3 gap-6 md:pl-12">
            <Step number="01" title="Sign up" body="Create an account in 30 seconds." visual={<Visual1 />} />
            <Step number="02" title="Connect" body="Plug into your existing tools." visual={<Visual2 />} />
            <Step number="03" title="Ship" body="Press deploy. We handle the rest." visual={<Visual3 />} />
          </div>
        </div>
      </div>
    </section>
  );
}

function Step({ number, title, body, visual }: any) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="relative flex flex-col rounded-2xl border border-black/8 bg-white p-7 overflow-hidden"
    >
      <span className="text-xs font-mono font-bold text-[var(--accent)]">{number}</span>
      <h3 className="mt-2 text-2xl font-bold text-[var(--text)]">{title}</h3>
      <p className="mt-2 text-sm text-[var(--text-muted)]">{body}</p>
      <div className="mt-6">{visual}</div>
    </motion.div>
  );
}

const Visual1 = () => <div className="aspect-video rounded-lg bg-neutral-100" />;
const Visual2 = () => <div className="aspect-video rounded-lg bg-neutral-100" />;
const Visual3 = () => <div className="aspect-video rounded-lg bg-neutral-100" />;
```

## Customization rules

- **Numbered badges (01, 02, 03)** are required — they signal sequence
- **Each step description = 1 sentence max.** Premium = restraint.
- **The bracket tracker is the premium signal.** Without it, this is just 3 cards.
- **Use real visuals**, not placeholders. Animated GIF, video, or live component.

## What NOT to change

- Don't add a 4th step. Three is the magic number for "how it works".
- Don't put icons in the badge (just numbers)
- Don't use `transition-all` — use `whileInView` for scroll-triggered

## Cross-references

- See `tokens.md` for spring presets and motion guidance
- See `recipes/features-bento.md` for the asymmetric alternative
- See `recipes/features-tabs.md` for product-tour alternative (persistent stage)
