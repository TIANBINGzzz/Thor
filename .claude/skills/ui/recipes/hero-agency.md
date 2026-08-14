# recipes/hero-agency.md — Editorial Agency Hero

**For agencies, studios, portfolios, and editorial brands.** Adapted from Avnac, Claura, mishutkin Design Mate, oriku personal landing, lochieaxon TextMorph.

## When to use

- Agency, design studio, freelance portfolio
- Editorial brands (publications, blogs)
- Personal landing pages by designers/creatives
- User says: "agency", "studio", "portfolio", "editorial"

## Structure

1. **Center-aligned** (only place to use centered-everything — agency heroes earn it)
2. **Massive editorial serif headline** (5-7 words, often 2 lines)
3. **8-word subtitle** explaining what the studio does
4. **Two pill buttons** (filled black + outlined)
5. **Asymmetric scattered decoration** in the corners (sticker icons, sketches, product references)

## Code

```tsx
import { motion } from "framer-motion";

const ENTRANCE = { duration: 0.6, ease: [0.16, 1, 0.3, 1] };
const stagger = { hidden: {}, visible: { transition: { staggerChildren: 0.1, delayChildren: 0.15 } } };
const child = { hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0, transition: ENTRANCE } };

export function HeroAgency() {
  return (
    <section className="relative min-h-[80vh] flex items-center justify-center px-6 py-32 overflow-hidden">
      {/* Off-white radial bg */}
      <div
        className="absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse at center, oklch(99% 0.005 90) 0%, oklch(95% 0.01 90) 100%)",
        }}
      />

      {/* Asymmetric scattered decoration — corners only, varied rotations */}
      <Decoration top="8%" left="6%" rotate="-12deg">
        <div className="size-20 rounded-xl border border-dashed border-black/15 p-2 bg-white">
          <img src="/sticker-1.svg" alt="" className="size-full" />
        </div>
      </Decoration>
      <Decoration top="14%" right="8%" rotate="8deg">
        <div className="size-24 rounded-xl border border-dashed border-black/15 p-2 bg-white">
          <img src="/sticker-2.svg" alt="" className="size-full" />
        </div>
      </Decoration>
      <Decoration bottom="14%" left="10%" rotate="6deg">
        <div className="size-20 rounded-xl border border-dashed border-black/15 p-2 bg-white">
          <img src="/sticker-3.svg" alt="" className="size-full" />
        </div>
      </Decoration>
      <Decoration bottom="10%" right="6%" rotate="-8deg">
        <div className="size-24 rounded-xl border border-dashed border-black/15 p-2 bg-white">
          <img src="/sticker-4.svg" alt="" className="size-full" />
        </div>
      </Decoration>

      {/* Center content */}
      <motion.div variants={stagger} initial="hidden" animate="visible" className="relative z-10 max-w-3xl text-center">
        <motion.h1
          variants={child}
          className="font-serif text-6xl md:text-7xl font-medium tracking-tight text-[var(--text)] leading-[1.05]"
        >
          Design in the browser, <em className="not-italic font-bold font-sans">openly.</em>
        </motion.h1>

        <motion.p
          variants={child}
          className="mt-8 text-lg text-[var(--text-muted)] max-w-md mx-auto"
        >
          A studio for layouts, posters, and graphics.
        </motion.p>

        <motion.div variants={child} className="mt-10 flex items-center justify-center gap-3">
          <a
            href="#start"
            className="rounded-full bg-[var(--text)] px-7 py-3 text-sm font-medium text-[var(--bg)] hover:bg-[var(--text)]/90 transition-colors"
          >
            Open editor
          </a>
          <a
            href="#github"
            className="rounded-full border border-black/10 bg-white px-7 py-3 text-sm font-medium text-[var(--text)] hover:bg-neutral-50 transition-colors"
          >
            GitHub
          </a>
        </motion.div>
      </motion.div>
    </section>
  );
}

// Helper component for absolutely-positioned decoration
function Decoration({
  children,
  top,
  bottom,
  left,
  right,
  rotate,
}: {
  children: React.ReactNode;
  top?: string;
  bottom?: string;
  left?: string;
  right?: string;
  rotate: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.8, delay: 0.6, ease: [0.16, 1, 0.3, 1] }}
      style={{ position: "absolute", top, bottom, left, right, transform: `rotate(${rotate})` }}
    >
      {children}
    </motion.div>
  );
}
```

## Customization rules

- **Note the inversion:** Headline is SERIF with bold-sans accent (opposite of hero-saas which is sans+italic-serif). Both work because the contrast is what matters.
- **Decoration must reference the product/brand.** Avnac is a design tool, so corner stickers are inside design-tool selection bounding boxes (meta self-reference). Make the decoration mean something. Don't use random clip-art.
- **Rotations should be varied (-15° to +15°).** Symmetrically rotated decoration looks fake.

## What NOT to change

- Don't add icons in the headline
- Don't put decoration inside the center text area (keep it in the corners only)
- Don't use more than 4 decoration items (more = busy)
- Don't shrink the headline below `text-6xl` — agency = bold typography statement
