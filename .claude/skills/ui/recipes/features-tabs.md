# recipes/features-tabs.md — Persistent Stage Tab Tour

**The TwelveMei pattern.** Same surface (image stage) stays mounted while floating UI cards swap. Premium product tour.

## When to use

- Product has multiple distinct features that share a common "stage" (e.g. screenshots/dashboard)
- You want to show 4-6 features without 6 separate sections
- User says: "feature tour", "product walkthrough", "explore features"

## Structure

- Left column (~50%): tabs (text labels) + active tab body copy + CTA
- Right column (~50%): persistent image/photo stage with floating UI overlay that swaps per tab
- Sliding underline indicator between tabs (`layoutId`)
- Floating UI uses `AnimatePresence` to swap with stagger; the stage stays mounted

## Code

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";

const SPRING = { type: "spring" as const, stiffness: 320, damping: 30 };

const TABS = [
  { id: "automation", label: "Automation", title: "Effortless workflows.", body: "Set it once.", overlay: "chat" },
  { id: "integrations", label: "Integrations", title: "Connects to everything.", body: "200+ apps.", overlay: "grid" },
  { id: "analytics", label: "Analytics", title: "See what matters.", body: "Real-time dashboards.", overlay: "chart" },
  { id: "security", label: "Security", title: "Bank-level safe.", body: "SOC2 + audit logs.", overlay: "lock" },
];

export function FeaturesTabs() {
  const [active, setActive] = useState(TABS[0].id);
  const tab = TABS.find((t) => t.id === active)!;

  return (
    <section className="px-6 py-32 max-w-7xl mx-auto">
      <div className="grid lg:grid-cols-2 gap-16 items-start">
        {/* LEFT: tabs + body */}
        <div>
          {/* Tab strip with sliding underline */}
          <div className="relative flex gap-8 border-b border-black/10 pb-3">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setActive(t.id)}
                className={`relative pb-3 text-sm font-medium transition-colors ${
                  t.id === active ? "text-[var(--text)]" : "text-[var(--text-muted)] hover:text-[var(--text)]"
                }`}
              >
                {t.label}
                {t.id === active && (
                  <motion.div
                    layoutId="features-tab-underline"
                    transition={SPRING}
                    className="absolute -bottom-3 left-0 right-0 h-px bg-[var(--text)]"
                  />
                )}
              </button>
            ))}
          </div>

          {/* Body content swaps with crossfade */}
          <AnimatePresence mode="wait">
            <motion.div
              key={tab.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.25 }}
              className="mt-8"
            >
              <h3 className="font-sans text-3xl md:text-4xl font-bold tracking-tight">{tab.title}</h3>
              <p className="mt-3 text-[var(--text-muted)]">{tab.body}</p>
              <a className="mt-6 inline-flex rounded-full bg-[var(--text)] px-5 py-2.5 text-sm font-medium text-[var(--bg)]">
                Learn more
              </a>
            </motion.div>
          </AnimatePresence>
        </div>

        {/* RIGHT: persistent stage with swapping overlay */}
        <div className="relative aspect-[4/5] rounded-2xl overflow-hidden border border-black/8">
          {/* Stage stays mounted — image never re-renders */}
          <img src="/stage-bg.jpg" alt="" className="absolute inset-0 w-full h-full object-cover" />

          {/* Floating UI overlay swaps per tab */}
          <AnimatePresence mode="wait">
            <motion.div
              key={tab.id}
              initial={{ opacity: 0, scale: 0.9, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -8 }}
              transition={SPRING}
              className="absolute inset-0 grid place-items-center p-8"
            >
              <div className="rounded-xl bg-white/90 backdrop-blur-md border border-white/40 shadow-2xl p-6 max-w-sm">
                {/* Render different content per tab.overlay value */}
                {tab.overlay === "chat" && <ChatOverlay />}
                {tab.overlay === "grid" && <GridOverlay />}
                {tab.overlay === "chart" && <ChartOverlay />}
                {tab.overlay === "lock" && <LockOverlay />}
              </div>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

const ChatOverlay = () => <div className="text-sm">Sample chat UI...</div>;
const GridOverlay = () => <div className="grid grid-cols-3 gap-2">{[...Array(6)].map((_, i) => <div key={i} className="aspect-square rounded bg-neutral-100" />)}</div>;
const ChartOverlay = () => <div className="aspect-video rounded bg-neutral-100" />;
const LockOverlay = () => <div className="text-sm">Security details...</div>;
```

## The premium signal

The stage image **stays mounted**. Only the floating overlay re-renders. This costs nothing in performance but feels distinctly premium because there's no "flash" between feature switches.

## Customization rules

- **Use real photos for the stage**, not gradient placeholders. The TwelveMei pattern uses photoreal 3D objects (rocks, trees) — the stage is the brand mood.
- **Sliding underline** uses `layoutId="features-tab-underline"` — single instance, tweens between positions
- **Body crossfade** uses `AnimatePresence mode="wait"` — exit before enter
- **Overlay slide-in** uses spring + slight scale to feel physical

## What NOT to change

- Don't unmount the stage image
- Don't swap the underline by mounting/unmounting (use `layoutId`)
- Don't use ease-in-out cubic-beziers — use spring
- Don't skip `mode="wait"` (otherwise body content stacks)

## Cross-references

- See `tokens.md` SPRING_SMOOTH preset
- See `anti-slop.md` "mounting/unmounting cards" anti-pattern
