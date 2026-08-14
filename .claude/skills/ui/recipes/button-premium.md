# recipes/button-premium.md — Premium Button Shadow Stack

**Adapted from kargul.studio + bitmapstudio.co.** A button is the most reused UI primitive on a landing page — and 99% of AI output ships flat, single-shadow buttons that read as a Tailwind default. This recipe documents the exact 4-layer shadow + gradient + stroke stack that makes a dark pill button look injection-molded instead of CSS-rendered, plus the bitmapstudio "primary pill + circular icon partner" pattern (shape-contrast secondary).

Treat this as the canonical button primitive — drop-in replacement for the dual-CTA block in `hero-saas.md`, the right-side CTA in `nav-pill.md`, and any pricing tier "Get Pro" button.

## When to use

- Primary CTA on dark or light heroes
- Pricing tier "Get Pro" / "Upgrade" / "Start free" buttons
- The right-side CTA inside `nav-pill.md`
- Any moment where the button is the visual anchor of the section
- ANY time you'd otherwise reach for `bg-black text-white rounded-full` (the AI tell)

## The four-layer stack (in source order)

1. **Inner highlight** — `inset 0 4px 4px rgba(255,255,255,0.15)` — fakes a top-edge bevel light
2. **Inner drop** — `inset 0 2px 4px rgba(1,1,1,0.15)` — depth shadow under the bevel
3. **Outer rim halo** — `0 4px 4px -3px rgba(180,178,189,1)` — soft halo lifting the button off the page
4. **Stroke** — `1px solid #18171C` — same hue as the gradient bottom, NOT pure black
5. **Fill** — `linear-gradient(180deg, #312F37 0%, #18171C 100%)` — top-lighter gradient sells the inset highlight

Combined with `border-radius: 9999px` and a contrast text label, the button reads as a physical, milled object.

## Code

```tsx
import { ArrowUpRight, Play } from "lucide-react";

export function ButtonPremium({
  children = "Get started",
  ...props
}: React.ComponentProps<"button">) {
  return (
    <button
      {...props}
      className="
        group relative inline-flex items-center gap-2
        rounded-full px-6 py-3
        text-sm font-medium text-white
        transition-transform duration-150
        hover:-translate-y-px active:translate-y-0
      "
      style={{
        background: "linear-gradient(180deg, #312F37 0%, #18171C 100%)",
        border: "1px solid #18171C",
        boxShadow: [
          "inset 0 4px 4px 0 rgba(255, 255, 255, 0.15)",
          "inset 0 2px 4px 0 rgba(1, 1, 1, 0.15)",
          "0 4px 4px -3px rgba(180, 178, 189, 1)",
        ].join(", "),
      }}
    >
      {children}
      <ArrowUpRight className="size-4 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
    </button>
  );
}
```

## Light variant (for dark hero backgrounds)

When the section is dark, invert the stack: white-to-cream gradient, dark inner shadow as the highlight, light rim halo.

```tsx
export function ButtonPremiumLight({
  children = "Get started",
}: { children?: React.ReactNode }) {
  return (
    <button
      className="group relative inline-flex items-center gap-2 rounded-full px-6 py-3 text-sm font-semibold text-[#18171C] transition-transform duration-150 hover:-translate-y-px"
      style={{
        background: "linear-gradient(180deg, #FFFFFF 0%, #ECEAEF 100%)",
        border: "1px solid #DAD7E1",
        boxShadow: [
          "inset 0 4px 4px 0 rgba(255, 255, 255, 0.6)",
          "inset 0 -2px 4px 0 rgba(24, 23, 28, 0.06)",
          "0 4px 4px -3px rgba(180, 178, 189, 1)",
        ].join(", "),
      }}
    >
      {children}
    </button>
  );
}
```

## Partner pattern: pill + circular icon-only secondary (bitmapstudio.co)

The premium pill rarely ships alone. Pair it with a circular icon-only secondary button — same height, same level of finish, but **shape contrast** (pill vs circle) instead of color contrast.

```tsx
export function CtaPair() {
  return (
    <div className="inline-flex items-center gap-2">
      {/* Primary pill */}
      <ButtonPremium>Start free</ButtonPremium>

      {/* Secondary circular icon-only — near-white, same shadow language */}
      <button
        aria-label="Watch demo"
        className="grid place-items-center size-12 rounded-full transition-transform duration-150 hover:-translate-y-px"
        style={{
          background: "linear-gradient(180deg, #FFFFFF 0%, #ECEAEF 100%)",
          border: "1px solid #DAD7E1",
          boxShadow: [
            "inset 0 4px 4px 0 rgba(255, 255, 255, 0.6)",
            "inset 0 -2px 4px 0 rgba(24, 23, 28, 0.06)",
            "0 4px 4px -3px rgba(180, 178, 189, 1)",
          ].join(", "),
        }}
      >
        <Play className="size-4 fill-[#18171C] text-[#18171C]" />
      </button>
    </div>
  );
}
```

**Why this works:** Most CTA pairs use color contrast (black pill + outlined pill, same shape). Premium designers use *shape* contrast (pill + circle). The eye reads it as "tool + accessory," which feels intentional instead of duplicative.

## Customization rules

- **The exact shadow values are non-negotiable.** Round them and the bevel collapses.
- **Always use a gradient fill, never flat `bg-neutral-900`.** Flat fills can't sell the inset highlight.
- **Stroke matches the gradient bottom color**, not `#000`. This is the difference between "premium" and "Tailwind default."
- **Hover = `-translate-y-px`**, not `scale(1.05)`. The button is heavy; it rises, it doesn't grow.
- **Pair with circular icon-only secondary** (the bitmapstudio.co partner) instead of an outlined-pill secondary when you want shape contrast over color contrast.

## What NOT to change

- Do not replace the 4-layer shadow with Tailwind `shadow-lg` / `shadow-xl` (single-layer, generic)
- Do not use `bg-black` — the gradient is what makes the bevel readable
- Do not use a thicker border than `1px` (turns into an outline, kills the depth)
- Do not animate `box-shadow` on hover (browsers paint it slowly — animate transform only)
- Do not use `rounded-md` or `rounded-lg` — calibrated for `rounded-full`
- Do not pair the dark pill with another dark pill — the partner is always near-white circular

## Cross-references

- See `tokens.md` "Shadows" — `--shadow-btn-premium` composite
- See `anti-slop.md` "flat single-shadow CTA" anti-pattern
- See `recipes/hero-saas.md` — drop-in replacement for the dual-CTA block
- See `recipes/nav-pill.md` — use as the right-side CTA pill
- See `recipes/morphing-button.md` for the click-to-expand variant (same shadow stack works there)
