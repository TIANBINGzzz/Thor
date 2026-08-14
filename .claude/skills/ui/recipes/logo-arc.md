# recipes/logo-arc.md — Logo Arc (Fan / Wreath Around Centerpiece)

**Adapted from itspeterdesign (Stealth).** Logo bricks arranged in an arc on either side of a centerpiece badge. Replaces the horizontal scrolling logo-ticker for builds where social proof IS the hero (or sits directly under it). The arrangement says "constellation of partners around our product," not "scrolling feed of clients."

## When to use

- Hero social-proof anchor — "trusted by 40+ teams" but visual instead of text
- "Integrations" section centerpiece (the rosette is your product, the arc logos are integrations)
- Conference / community page where the centerpiece is your event and arcs are sponsors
- Awards / press section — centerpiece "FEATURED IN", arc of publications

**Don't use** for: simple trust bar (use a horizontal grayscale row), comparison vs competitors (use a table).

## Structure

- Centerpiece — a hexagon, rosette, badge, or product mark (one large element, ~120-160px)
- 6-12 logos per side, arc swept ~140° from top to bottom
- Logo bricks are uniform-sized rounded squares with the partner mark inset (NOT raw transparent logos)
- Slight rotation per logo (~ -8° to +8°) keeps the arc feeling organic
- One subtle radial scrim behind the centerpiece for depth

## Code

```tsx
import { motion } from "framer-motion";

type LogoArcProps = {
  logos: { src: string; name: string }[];   // ideally 12-20 total
  centerpiece: React.ReactNode;
  className?: string;
};

const ARC_RADIUS = 280;       // px from center
const ARC_SWEEP = 140;        // total degrees of arc, per side
const BRICK_SIZE = 56;        // px
const TILT_RANGE = 8;         // ± degrees rotation

export function LogoArc({ logos, centerpiece, className = "" }: LogoArcProps) {
  // Split logos: even index → left, odd → right (alternating keeps balanced)
  const left  = logos.filter((_, i) => i % 2 === 0);
  const right = logos.filter((_, i) => i % 2 === 1);

  return (
    <div className={`relative mx-auto grid place-items-center min-h-[520px] ${className}`}>
      {/* radial scrim behind centerpiece */}
      <div
        aria-hidden
        className="absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(circle at center, var(--bg-elevated) 0%, transparent 60%)",
        }}
      />

      {/* LEFT arc (logos sweep top-left → bottom-left) */}
      {left.map((logo, i) => {
        const t = i / Math.max(left.length - 1, 1);
        const angleDeg = -90 - ARC_SWEEP / 2 + t * ARC_SWEEP;
        const rad = (angleDeg * Math.PI) / 180;
        const x = Math.cos(rad) * ARC_RADIUS;
        const y = Math.sin(rad) * ARC_RADIUS;
        const tilt = ((i * 37) % (TILT_RANGE * 2)) - TILT_RANGE;
        return (
          <ArcBrick
            key={`L-${logo.name}`}
            logo={logo}
            x={x} y={y} tilt={tilt}
            delay={0.1 + i * 0.04}
          />
        );
      })}

      {/* RIGHT arc */}
      {right.map((logo, i) => {
        const t = i / Math.max(right.length - 1, 1);
        const angleDeg = -90 + ARC_SWEEP / 2 - t * ARC_SWEEP;
        const rad = (angleDeg * Math.PI) / 180;
        const x = Math.cos(rad) * ARC_RADIUS;
        const y = Math.sin(rad) * ARC_RADIUS;
        const tilt = ((i * 53) % (TILT_RANGE * 2)) - TILT_RANGE;
        return (
          <ArcBrick
            key={`R-${logo.name}`}
            logo={logo}
            x={x} y={y} tilt={tilt}
            delay={0.1 + i * 0.04}
          />
        );
      })}

      {/* CENTERPIECE */}
      <motion.div
        initial={{ opacity: 0, scale: 0.94 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10"
      >
        {centerpiece}
      </motion.div>
    </div>
  );
}

function ArcBrick({
  logo, x, y, tilt, delay,
}: {
  logo: { src: string; name: string };
  x: number; y: number; tilt: number; delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: x * 0.7, y: y * 0.7, rotate: 0 }}
      animate={{ opacity: 1, x, y, rotate: tilt }}
      transition={{ delay, type: "spring", stiffness: 220, damping: 26 }}
      className="absolute"
      style={{ width: BRICK_SIZE, height: BRICK_SIZE }}
    >
      <div className="size-full rounded-xl border border-black/8 bg-[var(--bg-elevated)] shadow-sm grid place-items-center">
        <img
          src={logo.src}
          alt={logo.name}
          className="size-7 object-contain opacity-80"
          loading="lazy"
        />
      </div>
    </motion.div>
  );
}
```

## Example centerpiece — hexagonal rosette

```tsx
<LogoArc
  logos={partnerLogos}
  centerpiece={
    <div
      className="size-32 rounded-2xl bg-[var(--accent)] grid place-items-center"
      style={{ boxShadow: "0 24px 48px -12px var(--accent)" }}
    >
      <YourBrandMark className="size-12 text-[var(--accent-fg)]" />
    </div>
  }
/>
```

## What makes it premium

1. **Logos are inside uniform bricks**, not free-floating — solves "Mailchimp huge, Stripe tiny"
2. **The arc is mathematical** — `cos`/`sin` placement on a circle, never hand-positioned
3. **Per-logo tilt is deterministic-from-index** (`i * 37 % range`) — looks random, stable across renders
4. **Stagger flies in from inner positions** — logos start 30% closer to center, then spring out
5. **Scrim behind centerpiece** layers the composition — without it the centerpiece looks pasted on top
6. **Balanced split by even/odd index** — left and right arcs are visually balanced even with odd total

## Customization rules

- **12-20 logos total.** Fewer than 8 = sparse-looking. More than 24 = ring instead of arc.
- **`ARC_RADIUS` scales with viewport** — at mobile, drop to 180px and reduce sweep to 110°.
- **`ARC_SWEEP` ≤ 160°** — past that, top and bottom logos overlap the centerpiece
- **Brick background must be `--bg-elevated`** with subtle border. Logos themselves don't get borders.
- **Centerpiece shadow uses `--accent` color** — color-matched glow, not gray
- **Mobile fallback:** when viewport < 640px, fall back to a 2-row horizontal grid

## What NOT to change

- Don't randomize tilt with `Math.random()` — it'll re-jitter on every re-render. Use deterministic `i * prime % range`.
- Don't use raw transparent logos at varied sizes — they'll fight each other. Bricks are mandatory.
- Don't animate the arc on scroll (parallax) — the entrance stagger is enough
- Don't replace `cos`/`sin` math with manually-positioned divs — you'll get one looking off and never figure out which
- Don't add a "View all integrations" link below — the arc is the answer; a link breaks the gestalt

## Cross-references

- See `tokens.md` `--bg-elevated`, `--accent` tokens
- See `anti-slop.md` "scrolling marquee logo bar" anti-pattern (this is the alternative)
- See `recipes/hero-saas.md` for the hero this can sit beneath as social proof
- See `recipes/features-bento.md` "Integrations" tile pattern
