# recipes/hero-image-reveal.md — Image-Reveal Display Type

**Adapted from Skiper-UI.** Massive headline letters are masked with photographic content that reveals on cursor proximity. The headline IS the gallery — typography and imagery are fused into one element.

This is the highest-effort hero in the skill. Use sparingly — when used right it's a portfolio centerpiece; when used badly it's gimmick. Reserve for editorial brands, agencies, photographers, type-forward products.

## When to use

- Editorial brand site, agency portfolio, photography studio
- Music / film / fashion brand where imagery IS the brand
- Any moment the user says "I want a hero that wows" or "no boring landing page"
- DO NOT use for: B2B SaaS, fintech, dashboards, dev tools (mismatch with audience)

## The signature

Two layered passes:
1. **Base:** Headline rendered in solid text-color (off-white on dark, deep on light)
2. **Reveal:** Same headline rendered with `background-clip: text` over an image; opacity-masked by a soft circular gradient that follows the cursor via `useMotionValue` + `useSpring`

The image is always there. The cursor is the spotlight that reveals it through the letterforms.

## Code

```tsx
import {
  motion,
  useMotionValue,
  useSpring,
  useTransform,
} from "framer-motion";
import { useEffect, useRef } from "react";

const SPRING = { stiffness: 280, damping: 40, mass: 1 };

export function HeroImageReveal() {
  const ref = useRef<HTMLDivElement>(null);
  const mx = useMotionValue(-9999);
  const my = useMotionValue(-9999);
  const x = useSpring(mx, SPRING);
  const y = useSpring(my, SPRING);

  // Build the radial mask CSS string from the spring-tracked cursor
  const mask = useTransform(
    [x, y],
    ([xv, yv]) =>
      `radial-gradient(280px 280px at ${xv}px ${yv}px, black 0%, black 40%, transparent 80%)`
  );

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    mx.set(e.clientX - rect.left);
    my.set(e.clientY - rect.top);
  }

  function onLeave() {
    mx.set(-9999);
    my.set(-9999);
  }

  // Touch / no-hover fallback — auto-orbit the spotlight
  useEffect(() => {
    if (typeof window === "undefined") return;
    const isTouch = window.matchMedia("(hover: none)").matches;
    if (!isTouch || !ref.current) return;
    let frame = 0;
    const start = performance.now();
    const tick = () => {
      const t = (performance.now() - start) / 1000;
      const cx = ref.current!.clientWidth / 2 + Math.cos(t * 0.6) * 180;
      const cy = ref.current!.clientHeight / 2 + Math.sin(t * 0.6) * 120;
      mx.set(cx);
      my.set(cy);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [mx, my]);

  return (
    <section
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className="relative min-h-[100dvh] overflow-hidden bg-[var(--bg)] cursor-crosshair"
    >
      {/* BASE: solid headline */}
      <div className="absolute inset-0 grid place-items-center px-6 pointer-events-none">
        <h1 className="font-sans font-extrabold tracking-[-0.04em] leading-[0.85] text-center text-[clamp(80px,18vw,260px)] text-[var(--text)]">
          MAKE
          <br />
          IT REAL
        </h1>
      </div>

      {/* REVEAL: same headline, image-clipped, masked by cursor radial */}
      <motion.div
        className="absolute inset-0 grid place-items-center px-6 pointer-events-none"
        style={{ maskImage: mask, WebkitMaskImage: mask }}
      >
        <h1
          className="font-sans font-extrabold tracking-[-0.04em] leading-[0.85] text-center text-[clamp(80px,18vw,260px)]"
          style={{
            backgroundImage:
              "url('https://picsum.photos/seed/hero-collage/2400/1600')",
            backgroundSize: "cover",
            backgroundPosition: "center",
            WebkitBackgroundClip: "text",
            backgroundClip: "text",
            WebkitTextFillColor: "transparent",
            color: "transparent",
          }}
        >
          MAKE
          <br />
          IT REAL
        </h1>
      </motion.div>

      {/* Bottom credibility — calm because the H1 is loud */}
      <div className="absolute bottom-8 inset-x-0 px-8 flex items-end justify-between text-xs uppercase tracking-[0.12em] text-[var(--text-muted)]">
        <span>Studio · 2024–25</span>
        <span>Move cursor →</span>
        <span>Selected work</span>
      </div>
    </section>
  );
}
```

## The image asset

The background image should be a single composite — either:
- A single editorial photograph (portrait, product shot, abstract texture) — simplest
- A 3×3 grid of 9 small images composited into one file — most premium, gives the "gallery in the type" effect

Recommended source dims: **2400×1600px**, optimized to WebP, ~120kb. Use `picsum.photos` only as a placeholder during prototyping; replace with a real asset before shipping.

## Customization rules

- **Headline must be ≥80px on mobile, scaling to ≥200px on desktop** — image-reveal needs surface area
- **Letter-spacing `-0.04em`** is mandatory — wider tracking puts gaps between letters where image disappears
- **Use `clamp()` for the font-size** — viewport-driven sizing keeps the effect proportional across screens
- **Spring stiffness 280, damping 40** — slightly heavier than UI springs because the spotlight should feel like a deliberate movement, not a twitch
- **Reveal radius (280px) scales with viewport.** On mobile, drop to 180px or use the auto-orbit fallback above
- **`cursor-crosshair`** signals "interactive" — `cursor-default` makes users miss the effect

## What NOT to change

- Do not use `clip-path` instead of `mask-image` — clip-path is rectangular, mask-image gives the soft radial fade
- Do not animate the mask without `useSpring` smoothing — raw cursor coords cause jitter
- Do not use a video instead of a static image (file size + autoplay UX issues for ~3% gain in wow)
- Do not put a button inside this section — interaction is the cursor; the CTA goes in the next section
- Do not wrap the H1 in a `<motion.h1>` with entrance animation — the reveal IS the entrance; double-animating fights it
- Do not use thin/medium font weight — must be `font-extrabold` or heavier for the image to read inside the strokes

## Cross-references

- See `tokens.md` "MOTION PRESETS" — uses `useSpring` from Framer Motion
- See `recipes/text-roll.md` for the simpler typography-effect alternative
- See `recipes/hero-agency.md` — pair this as the FIRST hero with hero-agency as the second scroll-in section
- See `anti-slop.md` "Hero with parallax background image" — image-reveal is the premium replacement for parallax
