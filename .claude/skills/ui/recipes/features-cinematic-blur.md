# recipes/features-cinematic-blur.md — Cinematic Blur Feature Grid

**Adapted from shubhdsgn.** A blurred motion-streak / photographic backdrop sits behind a 4-quadrant feature grid. Cards are borderless, transparent-on-glass, and the blur does the heavy visual lifting so the cards stay calm and informational.

This is the alternative to `features-bento.md` when the section needs a cinematic mood (premium fintech, EV, luxury, AI products) instead of crisp grid energy.

## When to use

- Product is premium / cinematic / mood-driven (EV, luxury, premium AI, music)
- You have a strong photographic asset (motion blur, abstract texture, light-streak photo)
- 4 features that are roughly equal weight (the 2×2 grid is the structure)
- DO NOT use for dense 6-7 feature bento or step-driven "how it works"

## Structure (single section, three layers)

1. **Layer 1 (back):** Full-bleed blurred image (motion streak, mesh gradient, abstract texture). `filter: blur(60-100px) saturate(1.2)`.
2. **Layer 2 (mid):** Subtle dark scrim if needed for text contrast — `bg-black/20` or color-matched gradient.
3. **Layer 3 (front):** 2×2 grid of borderless feature cards over a translucent glass container.

The cards have NO borders, NO shadows, NO backgrounds of their own. The only visual frame is the soft glass container holding the grid.

## Code

```tsx
import { motion } from "framer-motion";
import { Zap, Shield, Layers, Sparkles } from "lucide-react";

const FEATURES = [
  { icon: Zap, title: "Instant", desc: "Sub-100ms response from any region." },
  { icon: Shield, title: "Secure", desc: "SOC 2 Type II. End-to-end encryption." },
  { icon: Layers, title: "Composable", desc: "Drop into any stack. No lock-in." },
  { icon: Sparkles, title: "Magical", desc: "Defaults that feel hand-tuned." },
];

const ENTRANCE = { duration: 0.6, ease: [0.16, 1, 0.3, 1] as const };

export function FeaturesCinematicBlur() {
  return (
    <section className="relative py-32 md:py-40 px-6 overflow-hidden">
      {/* LAYER 1: blurred backdrop */}
      <div className="absolute inset-0 -z-20">
        <img
          src="https://picsum.photos/seed/motion-streak/1920/1080"
          alt=""
          aria-hidden
          className="w-full h-full object-cover"
          style={{ filter: "blur(80px) saturate(1.2)", transform: "scale(1.15)" }}
        />
      </div>

      {/* LAYER 2: subtle scrim for contrast */}
      <div className="absolute inset-0 -z-10 bg-gradient-to-b from-[var(--bg)]/0 via-[var(--bg)]/20 to-[var(--bg)]/40" />

      {/* Section header */}
      <div className="relative max-w-4xl mx-auto text-center mb-16">
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
          Built different
        </span>
        <h2 className="mt-4 font-sans text-4xl md:text-5xl font-bold tracking-tight text-[var(--text)]">
          Power without the noise.
        </h2>
      </div>

      {/* LAYER 3: glass container holding the borderless 2×2 grid */}
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={ENTRANCE}
        className="
          relative max-w-5xl mx-auto
          rounded-3xl
          bg-[var(--bg)]/60 backdrop-blur-xl
          border border-white/10
          p-8 md:p-12
        "
        style={{ boxShadow: "0 40px 80px -20px rgb(0 0 0 / 0.25)" }}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-y-12 gap-x-16">
          {FEATURES.map((f) => {
            const Icon = f.icon;
            return (
              <div key={f.title} className="flex items-start gap-5">
                <div className="grid place-items-center size-12 shrink-0 rounded-2xl bg-white/80 backdrop-blur border border-black/5">
                  <Icon className="size-5 text-[var(--text)]" />
                </div>
                <div>
                  <h3 className="font-sans text-xl font-semibold text-[var(--text)]">
                    {f.title}
                  </h3>
                  <p className="mt-2 text-sm text-[var(--text-muted)] max-w-xs leading-relaxed">
                    {f.desc}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </motion.div>
    </section>
  );
}
```

## The blur asset

The backdrop image should be:
- Photographic with high color saturation (sunset, neon, motion-blurred lights)
- 1920×1080+ source (it gets scaled 115% to hide blur edge crop)
- Heavy compression OK (~60kb WebP) — it's blurred, detail is destroyed anyway
- Color-coordinated with `--accent` token (the accent should "live" in the blur)

If you don't have a photo, use a CSS mesh-gradient or pick from `assets/backgrounds/`.

## The "borderless cards" rule

Each feature is just `<icon> <title> <desc>` — no card wrapper, no border, no individual shadow. The glass container is the only frame in the grid. Adding per-card borders kills the cinematic effect because the eye starts grouping by card edge instead of reading the content.

## Customization rules

- **2×2 grid only.** 1×4 (single row) loses the cinematic-grid feel; 3×3 over-fills the glass container.
- **Glass container `bg-[var(--bg)]/60 backdrop-blur-xl`** — the 60% bg-tint prevents the blur from making text unreadable.
- **Icon chip background is `bg-white/80`** even on dark sections — the chip is a calm anchor against the moody backdrop.
- **Section padding `py-32 md:py-40`** — cinematic needs breathing room above and below.
- **`scale(1.15)` on the blurred image** — prevents the blur halo from showing the image edge.
- **One `whileInView` entrance** for the whole glass container — animating individual cards splits attention away from the blur.

## What NOT to change

- Do not give cards their own `bg-white` — that's `features-bento.md`'s job
- Do not use `backdrop-blur-sm` — must be `backdrop-blur-xl` or higher
- Do not use a video as the backdrop (file size, autoplay UX, blurred video is wasted bandwidth)
- Do not stagger card entrances — the glass container animates as a single object
- Do not put a CTA inside the glass container — the section above or below carries the CTA
- Do not use this AND `features-bento.md` in the same page — pick one features pattern

## Cross-references

- See `recipes/features-bento.md` for the crisp-grid alternative
- See `recipes/backgrounds-catalog.md` for backdrop options if no photographic asset
- See `tokens.md` "Shadows" for the soft 0/40/80/-20 container shadow
- See `recipes/hero-fintech.md` — same blur+glass language can layer behind the converter widget
