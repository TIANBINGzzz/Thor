# recipes/footer-modern.md — Modern Footer with Ghost Wordmark

**Editorial-style footer with massive faded brand wordmark.** Adapted from Finora, Linear, Stripe.

## When to use

- Always. Every page needs a footer.
- Marketing site, product site, dashboard "about" page

## Structure

- Top: dense link grid (4 columns max — Product / Company / Resources / Legal)
- Middle: socials row + email signup (optional)
- Bottom: copyright + status pill ("All systems operational")
- **Below all that: massive ghost wordmark** that fades from the brand color into transparent

## Code

```tsx
import { Github, Twitter, Linkedin } from "lucide-react";

export function FooterModern({ brand = "FUTURE" }: { brand?: string }) {
  return (
    <footer className="relative overflow-hidden bg-[var(--bg-elevated)] border-t border-black/8">
      <div className="max-w-7xl mx-auto px-6 pt-20 pb-12">
        {/* Top: link grid */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-8 md:gap-12">
          {/* Brand col (bigger) */}
          <div className="col-span-2">
            <div className="text-lg font-bold tracking-tight">{brand.toLowerCase()}</div>
            <p className="mt-3 text-sm text-[var(--text-muted)] max-w-xs">
              Building the tools we wish existed.
            </p>
            <div className="mt-5 flex gap-3">
              <a href="#" className="grid place-items-center size-9 rounded-full border border-black/10 hover:bg-neutral-100">
                <Twitter className="size-4" />
              </a>
              <a href="#" className="grid place-items-center size-9 rounded-full border border-black/10 hover:bg-neutral-100">
                <Github className="size-4" />
              </a>
              <a href="#" className="grid place-items-center size-9 rounded-full border border-black/10 hover:bg-neutral-100">
                <Linkedin className="size-4" />
              </a>
            </div>
          </div>

          <FooterCol heading="Product" links={["Features", "Pricing", "Changelog", "Docs"]} />
          <FooterCol heading="Company" links={["About", "Careers", "Blog", "Contact"]} />
          <FooterCol heading="Legal" links={["Privacy", "Terms", "Security", "Cookies"]} />
        </div>

        {/* Middle: copyright + status */}
        <div className="mt-16 pt-8 border-t border-black/8 flex flex-col md:flex-row justify-between gap-4 text-sm text-[var(--text-muted)]">
          <p>© 2026 {brand}. All rights reserved.</p>
          <a href="#status" className="inline-flex items-center gap-2">
            <span className="size-2 rounded-full bg-emerald-500" />
            All systems operational
          </a>
        </div>
      </div>

      {/* GHOST WORDMARK — the premium signal */}
      <div
        className="-mt-12 pointer-events-none select-none text-center font-sans font-extrabold tracking-tighter overflow-hidden"
        style={{
          fontSize: "clamp(8rem, 20vw, 22rem)",
          lineHeight: 0.85,
          background: "linear-gradient(to bottom, var(--accent), transparent 80%)",
          WebkitBackgroundClip: "text",
          backgroundClip: "text",
          WebkitTextFillColor: "transparent",
        }}
      >
        {brand}
      </div>
    </footer>
  );
}

function FooterCol({ heading, links }: { heading: string; links: string[] }) {
  return (
    <div>
      <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">{heading}</h4>
      <ul className="mt-4 space-y-2.5">
        {links.map((l) => (
          <li key={l}>
            <a href="#" className="text-sm text-[var(--text)] hover:text-[var(--accent)] transition-colors">
              {l}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

## The premium signal: ghost wordmark

Massive brand wordmark at the bottom, color-faded with gradient to transparent. Cuts off bottom edge so it bleeds. Pure decoration. Never a link.

## Customization rules

- **4 columns max** for the link grid (Brand+3 utility columns)
- **Real links only** — no placeholder columns. If "Resources" only has 1 link, merge it with another column.
- **Status pill** is small but adds enormous trust signal
- **Ghost wordmark color** matches `--accent` for cohesion
- **Use `tracking-tighter`** for the ghost wordmark — letters touch slightly

## What NOT to change

- Don't add 5+ columns of mostly-empty link lists
- Don't link the ghost wordmark
- Don't use a separator between footer and ghost wordmark — they're one visual unit
- Don't use neutral gray for the wordmark — it must be tinted

## Cross-references

- See `tokens.md` `--accent` and `--bg-elevated` tokens
- See `anti-slop.md` "Footer with 5 columns of mostly-empty link lists" anti-pattern
