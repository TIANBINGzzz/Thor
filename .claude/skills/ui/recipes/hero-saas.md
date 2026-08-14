# recipes/hero-saas.md — Universal B2B SaaS Hero

**The single most reused pattern across premium SaaS landing pages.** Adapted from analysis of zahragr8r, Ora AI, samtwtss, Filo, Flow AI, Taskzen, Focused, Devpilot, and ~12 others. Personality changes — structure does not.

## When to use

- B2B SaaS, AI products, dev tools, fintech-adjacent
- User says: "landing page", "marketing site", "saas hero", "build a hero section"
- Default choice when in doubt

## Structure (the 5 elements)

1. **Tiny credibility pill** above headline (5-star + count, "New" badge, status dot, or icon-label)
2. **Giant centered headline** (≤8 words, with ONE italic-serif accent word)
3. **One-line subtitle** (concrete promise — quantification, distinction, or audience)
4. **Dual CTA**: filled pill + outlined pill, centered
5. **Bleeding product mockup** with soft accent glow underneath

> **For the product mockup**: see `recipes/mockups.md`. If you have a real screenshot, drop it in. Otherwise use `<BrowserFrame>` containing a `<Sidebar>` + `<KPIStrip>` + `<LineChart>` for SaaS dashboards. **Do NOT invent a fake UI with divs + gradients** — that's the #1 AI tell.

## Code (React + Tailwind + Framer Motion)

```tsx
import { motion } from "framer-motion";
import { ArrowRight, Sparkles } from "lucide-react";

const ENTRANCE = { duration: 0.6, ease: [0.16, 1, 0.3, 1] };
const stagger = { hidden: {}, visible: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } } };
const child = { hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0, transition: ENTRANCE } };

export function HeroSaas() {
  return (
    <section className="relative pt-24 md:pt-32 pb-24 px-6 overflow-hidden">
      {/* OPTIONAL: bundled background — see recipes/backgrounds-catalog.md */}
      {/* <img src="/bg.webp" className="absolute inset-0 w-full h-full object-cover -z-10 opacity-60" /> */}

      <motion.div
        variants={stagger}
        initial="hidden"
        animate="visible"
        className="max-w-4xl mx-auto text-center"
      >
        {/* 1. Credibility pill */}
        <motion.div
          variants={child}
          className="inline-flex items-center gap-2 rounded-full border border-black/8 bg-white px-3.5 py-1.5 text-xs font-medium text-neutral-700 shadow-sm"
        >
          <Sparkles className="size-3.5 text-[var(--accent)]" />
          Trusted by 6,000+ teams
        </motion.div>

        {/* 2. Giant headline w/ italic-serif accent */}
        <motion.h1
          variants={child}
          className="mt-6 font-sans text-5xl md:text-6xl font-extrabold tracking-tight text-[var(--text)] leading-[1.05]"
        >
          Build websites that{" "}
          <span className="font-serif italic font-medium">don't look AI.</span>
        </motion.h1>

        {/* 3. Concrete subtitle */}
        <motion.p
          variants={child}
          className="mt-6 max-w-xl mx-auto text-lg text-[var(--text-muted)]"
        >
          Production-grade components, motion presets, and the discipline that makes UI feel premium.
        </motion.p>

        {/* 4. Dual CTA (filled + outlined pill) */}
        <motion.div variants={child} className="mt-8 flex items-center justify-center gap-3">
          <a
            href="#start"
            className="inline-flex items-center gap-2 rounded-full bg-[var(--text)] px-6 py-3 text-sm font-medium text-[var(--bg)] hover:bg-[var(--text)]/90 transition-colors"
          >
            Get started <ArrowRight className="size-4" />
          </a>
          <a
            href="#demo"
            className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white px-6 py-3 text-sm font-medium text-[var(--text)] hover:bg-neutral-50 transition-colors"
          >
            Watch demo
          </a>
        </motion.div>
      </motion.div>

      {/* 5. Bleeding product mockup w/ accent glow */}
      <motion.div
        initial={{ opacity: 0, y: 40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...ENTRANCE, delay: 0.4 }}
        className="relative mt-16 max-w-5xl mx-auto"
      >
        {/* Glow under mockup — color-matched to accent */}
        <div
          className="absolute inset-x-12 -bottom-4 h-32 blur-3xl opacity-40"
          style={{ background: "var(--accent)" }}
          aria-hidden
        />
        <div className="relative -mb-32 mx-auto overflow-hidden rounded-2xl border border-black/8 shadow-2xl bg-white">
          <img
            src="/dashboard-preview.png"
            alt="Product dashboard"
            className="w-full"
          />
        </div>
      </motion.div>
    </section>
  );
}
```

## Customization rules

- **Headline**: Replace text BUT keep ≤8 words AND keep one italic-serif word
- **Pill text**: Replace with real social proof. NEVER fake numbers.
- **CTA labels**: Replace with verb-action. ("Start free", "Book demo", "Try it free")
- **Mockup image**: Replace with real product screenshot. Don't ship without one.
- **Background image**: OPTIONAL. If brand needs more visual weight, pick from `assets/backgrounds/` — see `backgrounds-catalog.md` for which works best for SaaS.

## What NOT to change

- Don't add a third button
- Don't shrink headline below `text-5xl`
- Don't remove the pill above the headline
- Don't add icons inside the H1
- Don't make the CTA buttons the same color (filled vs outlined hierarchy is required)
- Don't remove the glow under the mockup (color-matched glow > neutral shadow)

## When NOT to use this recipe

- For agencies/studios → use `recipes/hero-agency.md` (centered editorial serif, scattered decoration)
- For fintech/wallets → use `recipes/hero-fintech.md` (split layout with live converter widget)
- For consumer apps → use `recipes/hero-app.md` (asymmetric with phone mockup)
