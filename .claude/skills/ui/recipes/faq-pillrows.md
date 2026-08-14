# recipes/faq-pillrows.md — Pill-Row FAQ

**Replaces shadcn/ui `<Accordion>` defaults.** Adapted from Ora AI, Finora, Linear, Vercel.

## When to use

- Pre-purchase FAQ section
- Documentation overview
- User says: FAQ, common questions, help, support

## Structure

- Vertical stack of thin pill rows
- Subtle hover state (background tint shift)
- Plus/minus icon on the right that rotates on expand
- Expanded answer slides down with `layout` motion
- Maximum 6-7 questions (more = noise)

## Code

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import { Plus } from "lucide-react";

const SPRING = { type: "spring" as const, stiffness: 320, damping: 30 };

const FAQS = [
  { q: "How is pricing calculated?", a: "By the seat per month. You can add or remove seats anytime — we prorate." },
  { q: "Can I cancel anytime?", a: "Yes. No contracts. We refund prorated for unused time." },
  { q: "Do you offer a free trial?", a: "14 days free, no credit card required. Full access to all features." },
  { q: "Where is my data stored?", a: "EU and US regions, your choice. SOC2 Type II compliant." },
  { q: "Can I export my data?", a: "Always. CSV, JSON, or direct API access. Your data, your call." },
  { q: "Do you have an API?", a: "REST + GraphQL. Free tier includes 1,000 requests/day. Docs at /api." },
];

export function FaqPillRows() {
  const [open, setOpen] = useState<number | null>(0);

  return (
    <section className="px-6 py-32 bg-[var(--bg)]">
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-12">
          <span className="text-sm font-medium text-[var(--accent)] uppercase tracking-wider">FAQ</span>
          <h2 className="mt-3 font-sans text-4xl md:text-5xl font-bold tracking-tight">
            Got <span className="font-serif italic font-medium">questions?</span>
          </h2>
        </div>

        <div className="space-y-2">
          {FAQS.map((faq, i) => (
            <motion.div
              key={faq.q}
              layout
              transition={SPRING}
              className="rounded-2xl bg-white border border-black/8 overflow-hidden"
            >
              <button
                onClick={() => setOpen(open === i ? null : i)}
                className="w-full flex items-center justify-between gap-4 px-6 py-5 text-left hover:bg-neutral-50 transition-colors"
              >
                <span className="font-medium text-[var(--text)]">{faq.q}</span>
                <motion.div
                  animate={{ rotate: open === i ? 45 : 0 }}
                  transition={SPRING}
                  className="shrink-0 grid place-items-center size-7 rounded-full border border-black/8"
                >
                  <Plus className="size-3.5" />
                </motion.div>
              </button>

              <AnimatePresence initial={false}>
                {open === i && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={SPRING}
                    className="overflow-hidden"
                  >
                    <p className="px-6 pb-5 text-sm text-[var(--text-muted)] leading-relaxed">
                      {faq.a}
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          ))}
        </div>

        <p className="mt-8 text-center text-sm text-[var(--text-muted)]">
          Still have questions?{" "}
          <a href="#contact" className="font-medium text-[var(--text)] underline underline-offset-4">
            Talk to us →
          </a>
        </p>
      </div>
    </section>
  );
}
```

## Customization rules

- **Plus icon rotates 45° = becomes X.** Smooth via spring.
- **Container morphs height** via `motion.div layout` + `AnimatePresence` — same surface morphs, no jarring jump.
- **Max 7 questions.** If you need more, organize them into multiple sections.
- **Real, helpful answers** — not "Lorem ipsum" or "Yes / No".

## What NOT to change

- Don't use boxy `<Accordion>` from shadcn defaults
- Don't use chevron icons (use plus → x rotation)
- Don't use cubic-bezier for the height animation — use spring
- Don't make all questions one-line — vary natural length

## Cross-references

- See `tokens.md` SPRING_SMOOTH preset
- See `anti-slop.md` "Modal accordions for FAQ" anti-pattern
