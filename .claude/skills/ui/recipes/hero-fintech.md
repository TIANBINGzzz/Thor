# recipes/hero-fintech.md — Fintech Split Hero with Live Widget

**For currency exchange, payment apps, banking, crypto.** Adapted from longjohn-currency, adrian-paypal, Wise/Revolut patterns, samtwtss-1.

## When to use

- User says: fintech, currency, money, wallet, crypto, banking, payments
- Product has a primary "do something with money" action

## Structure (asymmetric split)

- **Left (~50%)**: pill + headline + subtitle + dual CTA
- **Right (~50%)**: live functional converter widget (not a screenshot — actual interactive component)

The widget IS the marketing. Users can play with it before signing up.

## Code

```tsx
import { motion } from "framer-motion";
import { useState } from "react";
import { ArrowDown, Sparkles } from "lucide-react";

const SPRING_SMOOTH = { type: "spring" as const, stiffness: 320, damping: 30, mass: 1 };

export function HeroFintech() {
  const [send, setSend] = useState("1000");
  const [from, setFrom] = useState("USD");
  const [to, setTo] = useState("EUR");
  const rate = 0.9234;
  const receive = (parseFloat(send || "0") * rate).toFixed(2);
  const savings = (parseFloat(send || "0") * 0.035).toFixed(0); // ~3.5% bank markup avoided

  return (
    <section className="relative px-6 py-24 md:py-32 overflow-hidden bg-[var(--bg)]">
      <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
        {/* LEFT: copy */}
        <div>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <span className="inline-flex items-center gap-2 rounded-full bg-white border border-black/8 px-3 py-1 text-xs font-medium">
              <Sparkles className="size-3 text-[var(--accent)]" />
              Live mid-market rates
            </span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="mt-6 font-sans text-5xl md:text-6xl font-extrabold tracking-tight leading-[1.05] text-[var(--text)]"
          >
            Move money. <span className="font-serif italic font-medium">Anywhere.</span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="mt-6 text-lg text-[var(--text-muted)] max-w-md"
          >
            0.5% fee. 60+ currencies. Settled in 24 hours.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="mt-8 flex gap-3"
          >
            <a href="#start" className="rounded-full bg-[var(--text)] px-6 py-3 text-sm font-medium text-[var(--bg)]">
              Send your first transfer
            </a>
            <a href="#how" className="rounded-full border border-black/10 bg-white px-6 py-3 text-sm font-medium text-[var(--text)]">
              How it works
            </a>
          </motion.div>
        </div>

        {/* RIGHT: live converter widget */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="relative"
        >
          {/* Color-matched glow underneath — the premium signal */}
          <div className="absolute inset-x-8 -bottom-8 h-32 blur-3xl opacity-50" style={{ background: "var(--accent)" }} aria-hidden />

          {/* Containment is critical — overflow-hidden + relative + max-w prevent the dropdown overflow bug */}
          <div className="relative bg-white rounded-2xl border border-black/8 shadow-2xl p-6 md:p-8 max-w-md mx-auto overflow-hidden">
            {/* Mid-market rate header */}
            <div className="flex items-center justify-between text-xs font-medium text-[var(--text-muted)]">
              <span className="inline-flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-emerald-500" />
                MID-MARKET RATE
              </span>
              <span className="font-mono">1 {from} = {rate} {to}</span>
            </div>

            {/* SEND row */}
            <div className="mt-6">
              <label className="text-xs uppercase tracking-wider text-[var(--text-muted)]">You send</label>
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="text"
                  value={send}
                  onChange={(e) => setSend(e.target.value)}
                  className="flex-1 min-w-0 text-3xl md:text-4xl font-bold tabular-nums bg-transparent outline-none"
                />
                <CurrencyChip code={from} flag="🇺🇸" onClick={() => {/* open dropdown */}} />
              </div>
            </div>

            {/* Swap divider */}
            <div className="my-5 flex items-center">
              <div className="flex-1 h-px bg-black/5" />
              <button className="mx-3 grid place-items-center size-9 rounded-full border border-black/10 hover:bg-neutral-50">
                <ArrowDown className="size-4" />
              </button>
              <div className="flex-1 h-px bg-black/5" />
            </div>

            {/* RECEIVE row */}
            <div>
              <label className="text-xs uppercase tracking-wider text-[var(--text-muted)]">They receive</label>
              <div className="mt-2 flex items-center gap-2">
                <div className="flex-1 min-w-0 text-3xl md:text-4xl font-bold tabular-nums text-[var(--accent)]">
                  {receive}
                </div>
                <CurrencyChip code={to} flag="🇪🇺" onClick={() => {/* open dropdown */}} />
              </div>
            </div>

            {/* Savings highlight */}
            <div className="mt-5 flex items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2.5">
              <div className="grid place-items-center size-7 rounded-md bg-white border border-emerald-200">
                <ArrowDown className="size-3.5 -rotate-90 text-emerald-700" />
              </div>
              <span className="text-sm text-emerald-900">
                You save <strong>~${savings}</strong> vs your bank
              </span>
            </div>

            {/* Convert CTA */}
            <button className="mt-5 w-full rounded-full bg-[var(--accent)] py-3.5 text-sm font-semibold text-[var(--accent-fg)]">
              Convert now
            </button>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function CurrencyChip({ code, flag, onClick }: { code: string; flag: string; onClick: () => void }) {
  // CRITICAL: button uses shrink-0 + max-w — prevents the "USD floats outside card" overflow bug
  return (
    <button
      onClick={onClick}
      className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-black/10 bg-white px-3 py-2 text-sm font-semibold hover:bg-neutral-50"
    >
      <span className="text-base leading-none">{flag}</span>
      {code}
      <span className="text-xs text-[var(--text-muted)]">▾</span>
    </button>
  );
}
```

## CRITICAL: Containment rules (this fixes the "USD floats outside the card" bug)

The widget MUST use:
1. `overflow-hidden` on the outer card
2. `max-w-md` (or whatever) on the outer card
3. `min-w-0` on flex inputs (prevents forced overflow)
4. `shrink-0` on currency-chip buttons (so they don't get pushed out)

If currency dropdown floats outside the card, you missed one of these.

## Customization rules

- **The widget should be functional.** Even if it's just local state (no API), users can interact. This is what separates fintech sites from generic SaaS.
- **Color-matched glow under widget** — see `tokens.md` `--shadow-glow` token. Never neutral gray shadow.
- **Concrete numbers in subtitle.** "0.5% fee. 60+ currencies. 24h." NOT "Low fees. Many currencies. Fast."
- **The "You save ~$X" callout is critical** — it's the value-prop instantly visible without signup.

## What NOT to change

- Don't move CTA INSIDE the widget (the primary CTA stays in the left column — widget has its own "Convert now" secondary)
- Don't remove the rate header
- Don't ship without the savings highlight
- Don't use traditional dropdowns (no `<select>`) — use the chip pattern shown

## Note on mockups

This recipe is the **EXCEPTION** to the "no fake UI" rule in `recipes/mockups.md`. The right-side widget here is a **real, interactive component** — users can change the amount and see the converted total. That's the whole pitch. Real interactive UI demoing the actual product is always allowed.

For *other* fintech mockups in this same page (a dashboard preview lower down, a card-product shot, etc.), use `recipes/mockups.md` device frames + primitives. **Do NOT invent additional fake fintech UIs with divs + gradients.**
