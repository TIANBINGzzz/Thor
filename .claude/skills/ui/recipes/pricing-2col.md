# recipes/pricing-2col.md — Two-Tier Pricing Card Set

**Replaces the cliché 3-card "Basic / Pro / Enterprise" pattern.** Adapted from peter-pricing, Linear, Vercel.

## When to use

- 2-3 tier SaaS pricing
- User says: pricing, plans, tiers, subscription

**Note: 2 tiers > 3 tiers for most products.** Three-tier paralyzes choice. Use 2 with optional "Custom" link.

## Structure

- 2 cards side by side (NOT 3)
- One is highlighted (subtle bg tint, NOT a banner)
- "Currently Popular" pill with green dot — not "MOST POPULAR" banner
- Feature lists use thin dividers, NOT checkmark icons
- CTA at bottom of each card

## Code

```tsx
import { Sparkles } from "lucide-react";

export function Pricing2Col() {
  return (
    <section className="px-6 py-32 bg-[var(--bg)]">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-12">
          <span className="text-sm font-medium text-[var(--accent)] uppercase tracking-wider">Pricing</span>
          <h2 className="mt-3 font-sans text-4xl md:text-5xl font-bold tracking-tight">
            Simple, <span className="font-serif italic font-medium">honest</span> pricing.
          </h2>
        </div>

        <div className="grid md:grid-cols-2 gap-5">
          {/* Tier 1 — Plain */}
          <PriceCard
            name="Solo"
            price="$9"
            period="/ month"
            tagline="For individuals."
            cta="Start free"
            ctaStyle="outlined"
            features={[
              "1 workspace",
              "Up to 10 projects",
              "Basic analytics",
              "Community support",
            ]}
          />

          {/* Tier 2 — Highlighted (subtle) */}
          <PriceCard
            name="Team"
            price="$29"
            period="/ month / seat"
            tagline="For growing teams."
            cta="Get started"
            ctaStyle="filled"
            highlight
            features={[
              "Unlimited workspaces",
              "Unlimited projects",
              "Advanced analytics",
              "Priority support",
              "SSO + SCIM",
              "Audit log",
            ]}
          />
        </div>

        {/* Custom plan link — replaces "Enterprise" tier */}
        <p className="mt-8 text-center text-sm text-[var(--text-muted)]">
          Need something bigger?{" "}
          <a href="#contact" className="font-medium text-[var(--text)] underline underline-offset-4">
            Talk to sales →
          </a>
        </p>
      </div>
    </section>
  );
}

function PriceCard({
  name,
  price,
  period,
  tagline,
  cta,
  ctaStyle,
  features,
  highlight = false,
}: {
  name: string;
  price: string;
  period: string;
  tagline: string;
  cta: string;
  ctaStyle: "filled" | "outlined";
  features: string[];
  highlight?: boolean;
}) {
  return (
    <div
      className={`relative rounded-2xl border p-7 md:p-9 flex flex-col ${
        highlight
          ? "border-[var(--text)]/15 bg-[var(--bg-elevated)] shadow-lg"
          : "border-black/8 bg-white"
      }`}
    >
      {/* Subtle popular indicator — NOT a banner */}
      {highlight && (
        <span className="absolute -top-3 left-7 inline-flex items-center gap-1.5 rounded-full bg-[var(--accent)] px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--accent-fg)]">
          <span className="size-1.5 rounded-full bg-emerald-400" />
          Currently popular
        </span>
      )}

      <h3 className="font-sans text-xl font-bold">{name}</h3>
      <p className="mt-1 text-sm text-[var(--text-muted)]">{tagline}</p>

      <div className="mt-6 flex items-baseline gap-1.5">
        <span className="text-5xl font-extrabold tabular-nums tracking-tight">{price}</span>
        <span className="text-sm text-[var(--text-muted)]">{period}</span>
      </div>

      {/* Feature list — thin dividers, NO checkmarks */}
      <ul className="mt-8 flex-1 divide-y divide-black/5">
        {features.map((f) => (
          <li key={f} className="py-3 text-sm text-[var(--text)]">
            {f}
          </li>
        ))}
      </ul>

      <a
        href="#"
        className={`mt-8 inline-flex justify-center rounded-full px-6 py-3 text-sm font-medium transition-colors ${
          ctaStyle === "filled"
            ? "bg-[var(--text)] text-[var(--bg)] hover:bg-[var(--text)]/90"
            : "border border-black/10 bg-white text-[var(--text)] hover:bg-neutral-50"
        }`}
      >
        {cta}
      </a>
    </div>
  );
}
```

## Customization rules

- **Tier names:** Avoid "Basic / Pro / Enterprise". Use product-specific names ("Solo / Team / Studio", "Starter / Growth / Scale", or just price points)
- **2 tiers default**, with "Talk to sales" link for the 3rd
- **Subtle highlight:** Slightly different background (`var(--bg-elevated)`) + small accent pill. NEVER a giant "MOST POPULAR" banner.
- **Thin dividers between features**, not checkmarks
- **Real numbers only.** Don't use "$X" placeholders.

## What NOT to change

- Don't add a 3rd "Enterprise" card — use the link instead
- Don't put `<Check />` icons next to features
- Don't use a giant banner across the highlighted card
- Don't gradient the price number (the AI tell)
- Don't use rounded-md on the card — use rounded-2xl

## Cross-references

- See `anti-slop.md` for "MOST POPULAR" and "checkmark feature lists" anti-patterns
- See `tokens.md` for `--bg-elevated` and `--accent-fg` tokens
