# tokens.md — Design System

**Read this every build. Never invent your own tokens.**

Four palette presets. Three font stacks. Three motion presets. That's it.

---

> If on Next.js App Router (RSC), read `architecture.md` first.

---

## COLOR PALETTES — pick ONE per build

You commit to one palette upfront. The accent color is used **only on**: primary CTAs, status dots, key-emphasis spans in headlines, focus rings. Everything else is neutral.

### Palette 1 — WARM (default for editorial / agency / wellness)

```css
--bg:             oklch(98% 0.005 90);    /* warm off-white #faf8f3 */
--bg-elevated:    oklch(100% 0 0);         /* pure white only for cards on top */
--text:           oklch(20% 0.01 90);      /* deep brown-black #1d1a14 */
--text-muted:     oklch(45% 0.01 90);      /* muted gray-brown */
--border:         oklch(90% 0.005 90);     /* subtle warm gray */
--accent:         oklch(63% 0.18 38);      /* warm coral/terracotta */
--accent-fg:      oklch(98% 0.005 90);     /* off-white text on accent */
```

Use for: Claura-style AI agencies, wellness brands, editorial sites, premium agencies.

### Palette 2 — COOL (default for SaaS / fintech / tech)

```css
--bg:             oklch(98% 0.002 250);   /* cool off-white #f7f8fa */
--bg-elevated:    oklch(100% 0 0);
--text:           oklch(22% 0.01 250);     /* deep navy-black */
--text-muted:     oklch(48% 0.015 250);    /* slate-gray */
--border:         oklch(91% 0.005 250);
--accent:         oklch(58% 0.18 260);     /* indigo / violet */
--accent-fg:      oklch(98% 0.002 250);
```

Use for: SaaS landing pages, fintech, dashboards, B2B products. (This is the Kruz/Linear vibe.)

### Palette 3 — DARK (default for premium / cinematic / EV / luxury)

```css
--bg:             oklch(12% 0.005 260);    /* near-black #0a0c12 */
--bg-elevated:    oklch(18% 0.01 260);     /* slightly lifted card */
--text:           oklch(96% 0.005 90);     /* warm off-white text */
--text-muted:     oklch(65% 0.01 90);
--border:         oklch(25% 0.01 260);
--accent:         oklch(70% 0.16 60);      /* warm amber/orange */
--accent-fg:      oklch(12% 0.005 260);    /* dark text on amber */
```

Use for: Electric.-style luxury, cinematic landing pages, premium fintech (revenue dashboards), EV brands.

### Palette 4 — STONE (warm-grey + cream natural-minimalism)

```css
--bg:             oklch(94% 0.005 70);    /* warm stone #ebe7df */
--bg-elevated:    oklch(98% 0.005 70);
--text:           oklch(20% 0.01 70);
--text-muted:     oklch(45% 0.01 70);
--border:         oklch(86% 0.005 70);
--accent:         oklch(55% 0.12 30);     /* burnt sienna */
--accent-fg:      oklch(98% 0.005 70);
```

Use for: natural-minimalism brands, wellness, agriculture, slow-craft, ceramics, food/farm.

For forbidden colors (teal, purple-to-blue gradient, pure `#fff`/`#000`), see `anti-slop.md` § COLOR.

---

## ATMOSPHERE & SURFACE DETAIL

The single biggest gap between AI-generated and Awwwards-tier output. Every elevated surface, every hero, every dark-mode card uses these. See `visual-thinking.md` Phase 2 (Light) for the reasoning.

### Two-part shadow system

Every elevated card needs BOTH a tight contact shadow AND a wide ambient shadow. Single-layer shadows look CGI-fake.

```css
--shadow-card-contact:  0 1px 2px 0 rgb(0 0 0 / 0.06);           /* anchors element to surface */
--shadow-card-ambient:  0 20px 40px -12px rgb(0 0 0 / 0.10);     /* ground shadow with directional offset */
--shadow-card-stacked:
  0 1px 2px 0 rgb(0 0 0 / 0.06),
  0 20px 40px -12px rgb(0 0 0 / 0.10);
```

Apply: `box-shadow: var(--shadow-card-stacked);` — never use `--shadow-md` alone for an elevated card.

For dark mode, tint shadows toward the bg hue, never pure black:

```css
--shadow-card-stacked-dark:
  0 1px 2px 0 oklch(0.06 0.02 250 / 0.5),
  0 20px 40px -12px oklch(0.06 0.02 250 / 0.4);
```

### Key-light inset highlight

The "MacOS Big Sur key light" — 1px inset top highlight at white/8%. Most-cited premium tell on raised dark surfaces. Stack ABOVE the two-part shadow.

```css
--shadow-key-light-inset: inset 0 1px 0 rgb(255 255 255 / 0.08);

/* Combined: */
box-shadow:
  var(--shadow-key-light-inset),
  var(--shadow-card-stacked);
```

Pairs with a top-left light source so the highlight reads as a real caught edge.

### Grain overlay class

SVG turbulence noise at 4-8% opacity, fixed and pointer-events-none, mix-blend-mode overlay. Site-wide subtle texture. Single biggest "expensive" tell.

```css
.grain-overlay::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 100;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' /></filter><rect width='100%25' height='100%25' filter='url(%23n)' opacity='0.06'/></svg>");
  mix-blend-mode: overlay;
}
```

Apply once on `<body>` or root layout. Test 4 / 6 / 8% — pick the lowest where grain just barely registers.

### Atmospheric vignette

Subtle radial darkening at corners — focuses the eye, mimics camera lens fall-off. Heroes only.

```css
--bg-vignette: radial-gradient(ellipse at center, transparent 40%, rgb(0 0 0 / 0.4) 100%);
```

Layer ABOVE hero content with `pointer-events: none`.

### Warm-cool split background

Cross-page subliminal depth. Hero bg goes cool bottom-left → warm top-right (or inverse). Reads as physical 3D space.

```css
--bg-split-gradient: linear-gradient(
  to top right,
  oklch(0.16 0.02 250) 0%,    /* cool side */
  oklch(0.18 0.02 30) 100%    /* warm side */
);
```

Subtle is the point — if anyone notices it directly, it's too strong.

---

## FONT STACKS — pick ONE per build

Always pair a **bold grotesque sans** (body + UI + bulk of headlines) with **ONE italic-serif accent** (used for one word per headline, max).

### Stack A — INTER TIGHT + INSTRUMENT (default)

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;700;800&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
```

```css
--font-sans:   'Inter Tight', system-ui, sans-serif;
--font-serif:  'Instrument Serif', Georgia, serif;
```

The default. Used everywhere from Vercel to Linear-adjacent products.

### Stack B — GEIST + EDITORIAL (for tech-forward / dev tools)

```css
--font-sans:   'Geist', system-ui, sans-serif;
--font-serif:  'PP Editorial New', 'Instrument Serif', Georgia, serif;
```

Use for developer tools, AI products, technical SaaS.

### Stack C — UNCUT SANS + REPLY (for editorial / agency)

```css
--font-sans:   'Uncut Sans', 'Inter Tight', system-ui, sans-serif;
--font-serif:  'Reply', 'Instrument Serif', serif;
```

Use for agencies, portfolios, fashion-adjacent brands.

### Dashboard font pairings (Sans + Mono, hard rule)

Dashboards use a Sans + Mono pair. Numeric data and code-like fields go in mono. Pick ONE pairing:

- **Geist + Geist Mono** (default)
- **Satoshi + JetBrains Mono**
- **Inter Tight + IBM Plex Mono**

```css
--font-mono: 'Geist Mono', ui-monospace, monospace;
```

For banned fonts (Inter without Tight, Space Grotesk, Roboto/Arial/Helvetica, multi-serif, all-italic), see `anti-slop.md` § TYPOGRAPHY. Hard rule still applies: no serif on dashboard body text or numeric data — single italic-serif emphasis word in section headers is the only exception.

---

## TYPE SCALE

```css
--text-xs:    0.75rem;    /* 12px — meta labels, badges */
--text-sm:    0.875rem;   /* 14px — body small */
--text-base:  1rem;       /* 16px — body */
--text-lg:    1.125rem;   /* 18px — large body / lead */
--text-xl:    1.5rem;     /* 24px — H4 */
--text-2xl:   2rem;       /* 32px — H3 */
--text-3xl:   2.75rem;    /* 44px — H2 */
--text-4xl:   3.75rem;    /* 60px — H1 default */
--text-5xl:   5rem;       /* 80px — hero default */
--text-6xl:   6.5rem;     /* 104px — mega hero */
--text-7xl:   8rem;       /* 128px — display only */
```

**Hero headlines should use `--text-4xl` to `--text-6xl`.** Below `text-4xl` and your hero feels timid. Above `text-6xl` and it stops being readable.

**Letter spacing for huge type:**
```css
.headline { letter-spacing: -0.02em; }   /* tight, signals confidence */
.display  { letter-spacing: -0.04em; }   /* extra tight for display */
```

---

## TYPOGRAPHY PATTERNS

### Meta labels (bracketed corner labels)

Used for sub-section markers, "filed under" tags, technical metadata in corners.

```css
.meta-label-bracket {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  opacity: 0.6;
  text-transform: uppercase;
}
/* Usage: <span class="meta-label-bracket">[LINEAR]</span> */
```

### Eyebrow tags (microscopic uppercase pill above H1/H2)

Every section heading gets one. The accent color goes here, not in the H1 itself.

```html
<span class="rounded-full px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-medium text-[var(--accent)]">
  Pricing
</span>
<h2>...</h2>
```

Spec: `rounded-full px-3 py-1 text-[10px] uppercase tracking-[0.2em] font-medium text-[var(--accent)]`

---

## TYPOGRAPHY DETAIL (editorial-tier moves)

These are the moves that separate "good type" from "Awwwards-tier type". Apply to display headlines and editorial sections. See `visual-thinking.md` for when to invoke them.

### Negative tracking on display

Display headlines must use NEGATIVE letter-spacing. Default tracking looks loose at scale.

```css
.display-headline {
  font-size: clamp(3rem, 6vw, 6rem);
  letter-spacing: -0.04em;   /* MANDATORY for display */
  font-weight: 700;
  line-height: 0.95;          /* tight leading on big type */
}
```

Mid-weights (32-48px) at `-0.02em`. Body at default. Most templates miss this.

### Mono eyebrow + serif headline (editorial-tier pairing)

The single most-cited "premium" type pairing. Mono uppercase microscopic eyebrow above a serif (or italic-serif accent) headline.

```html
<div class="space-y-3">
  <span class="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--text-muted)]">
    Vol. 04 — Field Notes
  </span>
  <h1 class="font-serif text-6xl italic leading-[0.95] tracking-[-0.04em]">
    The shape of <em>memory</em>.
  </h1>
</div>
```

The contrast — mono technical kicker + serif human headline — does the work. Use for editorial sites, agency portfolios, premium long-form.

### Drop cap

For long-form intros and editorial spreads. The first letter of the first paragraph drops 3 lines.

```css
.drop-cap::first-letter {
  float: left;
  font-family: var(--font-serif);
  font-size: 4.5em;
  line-height: 0.85;
  padding: 0.05em 0.1em 0 0;
  font-weight: 600;
  color: var(--text);
}
```

Use sparingly — once per editorial article, never on marketing sections.

---

## SPACING SCALE

Use the standard Tailwind scale. Never invent gaps like `gap-[13px]`.

```
0.5 → 2px     2 → 8px      6 → 24px     16 → 64px
1   → 4px     3 → 12px     8 → 32px     20 → 80px
1.5 → 6px     4 → 16px     12 → 48px    24 → 96px
                                         32 → 128px
```

**Section vertical padding:** `py-24` mobile, `py-32` or `py-40` desktop. Premium = breathing room.

**Container max widths:**
- `max-w-3xl` (768px) — hero copy, body sections
- `max-w-5xl` (1024px) — feature grids
- `max-w-7xl` (1280px) — dashboards, full-width content

---

## RESPONSIVE / FLUID SIZING

**Build the desktop view first, then enforce mobile collapse explicitly.** Mobile is NOT "the desktop view at smaller width" — it's a different composition.

### Breakpoint stack (Tailwind defaults — DON'T deviate)

```
sm:   640px   small phones / large phones landscape
md:   768px   tablets / iPad portrait
lg:   1024px  small laptops / iPad landscape
xl:   1280px  desktops
2xl:  1536px  large desktops
```

**Test at exactly these viewports** with Playwright `browser_resize`:
- **375px** — iPhone SE / 14 (the worst-case narrow modern phone)
- **390px** — iPhone 14 Pro
- **768px** — iPad portrait (md: breakpoint enters)
- **1024px** — iPad landscape / small laptop (lg: enters)
- **1280px** — standard desktop (xl: enters)

If any of those break, the page isn't shipped.

### Fluid type with `clamp()` for hero scale

The hero headline MUST scale fluidly between phones and desktops. Pure Tailwind text-XL classes jump in steps — premium uses fluid math.

```css
/* Hero headline — clamp(min, fluid, max) */
font-size: clamp(2.25rem, 5vw + 1rem, 5rem);
/* 36px on tiny phones → 80px on wide desktops, smooth in between */

/* H2 section heading */
font-size: clamp(1.875rem, 3vw + 0.5rem, 3rem);
/* 30px → 48px */

/* Body */
font-size: clamp(1rem, 0.5vw + 0.875rem, 1.125rem);
/* 16px → 18px */
```

In Tailwind via arbitrary values: `text-[clamp(2.25rem,5vw+1rem,5rem)]`.

### Hero scaling formula

When fluid clamp() isn't a fit (e.g. you want clean Tailwind classes):

| Element | mobile | tablet (md:) | desktop (lg:) | wide (xl:) |
|---|---|---|---|---|
| Hero H1 | `text-4xl` (36px) | `text-5xl` (48px) | `text-6xl` (60px) | `text-7xl` (72px) |
| Section H2 | `text-3xl` | `text-4xl` | `text-5xl` | `text-5xl` |
| Body | `text-base` | `text-base` | `text-lg` | `text-lg` |
| Section padding-y | `py-16` | `py-24` | `py-32` | `py-40` |
| Container px | `px-5` | `px-8` | `px-12` | `px-12` |

Tailwind: `text-4xl md:text-5xl lg:text-6xl xl:text-7xl`

### Mobile collapse contracts (HARD RULES)

- **Asymmetric grids MUST collapse to single-column.** Use `grid-cols-1 md:grid-cols-2 lg:grid-cols-3` — NEVER `md:grid-cols-3` alone (breaks below 768px).
- **Bento grids MUST become a single stack on mobile.** All `col-span-X` overrides reset to `col-span-1` below `md:`.
- **Side-by-side hero (text + image) MUST stack vertically on mobile.** Text always above image on mobile (selling-first), regardless of which side it sits on at desktop.
- **Tab interfaces stay horizontal until <640px**, then become a horizontal scroll strip OR collapse to a `<select>` dropdown.

### Touch targets (mobile)

Minimum `44x44px` for any tappable element on touch devices (Apple HIG / WCAG 2.5.5):

```css
button, a[role="button"], input[type="checkbox"], .clickable {
  min-width: 44px;
  min-height: 44px;
}
```

In Tailwind: `min-h-11 min-w-11` (11 × 4px = 44px).

CTAs / nav items / icon buttons should comfortably exceed this — `h-12` (48px) or `h-14` (56px) is the premium target.

### Viewport units — use `dvh` not `vh`

- `100vh` is BROKEN on iOS Safari (jumps when address bar collapses/expands).
- Use `100dvh` (dynamic viewport height) instead — always. See `anti-slop.md` § MOBILE.

### Responsive containers

```tsx
{/* Desktop wide content with tight phone padding */}
<div className="max-w-7xl mx-auto px-5 md:px-8 lg:px-12">
  ...
</div>

{/* Hero copy column — narrower max-w + center */}
<div className="max-w-3xl mx-auto px-5 md:px-8">
  ...
</div>
```

### Image sizing (responsive)

Use `<img>` with `srcSet` for fluid scaling:
```tsx
<img
  src="/hero.webp"
  srcSet="/hero-640.webp 640w, /hero-1280.webp 1280w, /hero-1920.webp 1920w"
  sizes="(max-width: 640px) 100vw, (max-width: 1280px) 50vw, 800px"
  alt=""
  loading="eager"
  fetchPriority="high"
/>
```

For Next.js: use `next/image` with explicit `sizes` prop.

### Mobile-only / desktop-only with Tailwind

```html
<!-- Hide on mobile, show on tablet+ -->
<div className="hidden md:block">...</div>

<!-- Show on mobile, hide on tablet+ -->
<div className="block md:hidden">...</div>

<!-- Different content per breakpoint (use sparingly) -->
<h1 className="md:hidden">Mobile headline</h1>
<h1 className="hidden md:block">Longer desktop headline with more nuance</h1>
```

Don't abuse this — keep ONE source of truth where possible.

### Common responsive failures

- **Text overflows on narrow phones** → use `break-words` or shrink font-size at `sm:` breakpoint
- **Image overflows container** → add `max-w-full h-auto`
- **Fixed-width components** (`w-[480px]`) → use `w-full max-w-[480px]` instead
- **Touch targets too small** → enforce `min-h-11 min-w-11`
- **Hover states broken on mobile** → use `active:` pseudo-class for press feedback, never rely on `hover:` for primary affordance

---

## MOTION PRESETS

Always import from this set. Never write `cubic-bezier()` manually for primary motion.

### Spring presets (Framer Motion)

```ts
// BASE — the canonical "premium spring" (Awwwards SOTD default).
// Use this for nearly every interaction unless you have a reason not to.
export const SPRING_BASE = { type: "spring", stiffness: 200, damping: 30 };

// Snappy — for buttons, hover, small UI
export const SPRING_SNAPPY = { type: "spring", stiffness: 400, damping: 28, mass: 0.8 };

// Smooth — for layout morphs, sheet open/close
export const SPRING_SMOOTH = { type: "spring", stiffness: 320, damping: 30, mass: 1 };

// Bouncy — for success states, playful interactions only
export const SPRING_BOUNCY = { type: "spring", stiffness: 220, damping: 14, mass: 1 };

// Page entrance — for hero / on-mount stagger
export const ENTRANCE = { duration: 0.6, ease: [0.16, 1, 0.3, 1] }; // ease-out-quint
```

### Stagger pattern

```tsx
const container = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};

const child = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: ENTRANCE },
};

<motion.div variants={container} initial="hidden" animate="visible">
  <motion.h1 variants={child}>...</motion.h1>
  <motion.p variants={child}>...</motion.p>
  <motion.div variants={child}>...</motion.div>
</motion.div>
```

### Layout / shared element

For ANY UI that morphs between states (button → input, card → expanded card, tab → tab):

```tsx
import { motion, AnimatePresence } from "framer-motion";

<motion.div layout transition={SPRING_SMOOTH}>
  <AnimatePresence mode="popLayout">
    {/* swap content via key, never mount/unmount sibling components */}
  </AnimatePresence>
</motion.div>
```

For tabs / segmented controls with sliding indicator:

```tsx
<motion.div layoutId="active-tab-pill" />  // single instance, tweens between segments
```

### Liquid Glass recipe

CSS for the Liquid Glass surface (principle and usage rules in `anti-slop.md` § DECORATION):

```css
backdrop-filter: blur(20px);
background: rgba(255, 255, 255, 0.05);
border: 1px solid rgba(255, 255, 255, 0.1);
box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1);
```

For motion anti-patterns (cubic-bezier, `transition: all`, animating layout props, useState for continuous input), see `anti-slop.md` § MOTION.

---

## BORDER RADIUS

```css
--radius-sm:  0.375rem;   /* 6px — input fields, small chips */
--radius-md:  0.75rem;    /* 12px — cards default */
--radius-lg:  1rem;       /* 16px — large cards */
--radius-xl:  1.5rem;     /* 24px — hero cards, page frames */
--radius-2xl: 2rem;       /* 32px — outer page-frame container */
--radius-full: 9999px;    /* pills — nav, CTAs, badges */
```

**Pill-everything default for nav/CTAs/badges.** When in doubt, `rounded-full`.

---

## SHADOWS

```css
--shadow-sm:   0 1px 2px 0 rgb(0 0 0 / 0.04);
--shadow-md:   0 4px 16px -4px rgb(0 0 0 / 0.08);
--shadow-lg:   0 24px 48px -12px rgb(0 0 0 / 0.12);
--shadow-xl:   0 40px 80px -20px rgb(0 0 0 / 0.15);
--shadow-glow: 0 0 80px -20px var(--accent);  /* color-matched glow under product mockups */
```

Color-matched shadows beat neutral gray. Under product mockups, use `--shadow-glow` not `--shadow-xl`.

### Premium button stack (kargul.studio 4-layer)

For dark CTA pills that need to feel pressable and physical (not flat). Use sparingly — primary CTA only.

```css
--shadow-btn-premium:
  inset 0 4px 4px 0 rgba(255, 255, 255, 0.15),
  inset 0 2px 4px 0 rgba(1, 1, 1, 0.15),
  0 4px 4px -3px rgba(180, 178, 189, 1);
--shadow-btn-premium-fill:   linear-gradient(180deg, #312F37 0%, #18171C 100%);
--shadow-btn-premium-stroke: 1px solid #18171C;
```

Apply: `background: var(--shadow-btn-premium-fill); border: var(--shadow-btn-premium-stroke); box-shadow: var(--shadow-btn-premium);`

---

## Z-INDEX DISCIPLINE

Reserve z-indexes strictly for systemic layer contexts: sticky nav, modals, overlays, tooltips, command palettes. NEVER use `z-50` arbitrarily for "vibes".

Standard stack:
- `z-40` — dropdowns, popovers
- `z-50` — sticky nav
- `z-60` — tooltips
- `z-100` — modals, dialogs, overlays
- `z-[200]` — toasts, command palette

If you find yourself adding `z-10` to a card "to make it stack right" — your layout reasoning is off. Fix the layout, don't paper over it with z-index.

---

## QUICK SUMMARY

| Decision | Default |
|---|---|
| Background | Off-white (Palette 1, 2, 4) or near-black (3) — NEVER `#fff` |
| Text | Slightly tinted black, never `#000` |
| Accent | ONE color, used only on CTAs / status / emphasis |
| Sans font | Inter Tight (or Geist for tech-forward) |
| Serif font | Instrument Serif (one italic word per headline) |
| Mono font | Geist Mono (dashboards, numeric data, meta labels) |
| Hero size | `text-5xl md:text-6xl` |
| Letter spacing | `tracking-tight` for headlines |
| Section padding | `py-32 md:py-40` |
| Card radius | `rounded-2xl` (cards) / `rounded-full` (pills) |
| Motion | Spring presets, `layout`/`layoutId`, never cubic-bezier |
| Animated props | `transform` + `opacity` only |
| Stagger | 80ms between children, 100ms entrance delay |
| Glass | Liquid Glass spec only, sticky/floating only |
| Z-index | Reserved for systemic contexts only |
