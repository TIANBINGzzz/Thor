# recipes/morphing-button.md — Click-to-Expand Pill Button

**The Nitish Khagwal pattern.** Single pill morphs from compact button to button + input. Uses Framer Motion `layout` + spring. Premium UX moment for newsletter signups, waitlists, search-on-click.

## When to use

- Newsletter / waitlist signup CTA
- Search reveal on click
- Comment composer on click
- Any "click to reveal an input inline" moment (replaces a modal)

## The signature: same surface morphs, no mount/unmount

The pill IS the input container. Click expands width and reveals the input. The button stays anchored to the right edge throughout. Spring physics make it feel physical.

## Code

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import { Bell, ArrowRight } from "lucide-react";

const SPRING = { type: "spring" as const, stiffness: 320, damping: 30, mass: 0.8 };

export function NotifyMorph() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");

  return (
    <motion.div
      layout
      transition={SPRING}
      onClick={() => !open && setOpen(true)}
      className="inline-flex items-center bg-neutral-100 rounded-full p-1.5 cursor-pointer"
      style={{ width: open ? 380 : 200 }}
    >
      {/* Email input — fades in on left */}
      <AnimatePresence mode="popLayout">
        {open && (
          <motion.input
            key="email"
            layout
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: { delay: 0.15 } }}
            exit={{ opacity: 0 }}
            type="email"
            placeholder="your@email.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            autoFocus
            className="flex-1 min-w-0 bg-transparent px-4 outline-none text-[var(--text)] placeholder-[var(--text-muted)]"
          />
        )}
      </AnimatePresence>

      {/* Inner button — stays right-pinned, content morphs */}
      <motion.button
        layout
        transition={SPRING}
        onClick={(e) => {
          e.stopPropagation();
          if (open && email) {
            // submit
            console.log("subscribe", email);
            setOpen(false);
            setEmail("");
          }
        }}
        className="shrink-0 inline-flex items-center gap-2 bg-white rounded-full px-5 py-2.5 shadow-sm font-semibold text-[var(--text)]"
      >
        <AnimatePresence mode="popLayout">
          {!open ? (
            <motion.span
              layout
              key="bell"
              initial={{ opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.6 }}
            >
              <Bell className="size-4 fill-current" />
            </motion.span>
          ) : (
            <motion.span
              layout
              key="arrow"
              initial={{ opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.6 }}
            >
              <ArrowRight className="size-4" />
            </motion.span>
          )}
        </AnimatePresence>
        <motion.span layout>{open ? "Notify me" : "Notify me"}</motion.span>
      </motion.button>
    </motion.div>
  );
}
```

## What makes it premium

1. **`layout` prop on the parent** animates width changes — no manual width interpolation
2. **`layout` on inner button** keeps it right-pinned during expansion
3. **Spring (320/30)** — snappy, physical, not slow
4. **Email input delayed 150ms** so the width animation finishes before content appears
5. **Inner button shadow** creates depth — pill looks like it has a button "inside" it
6. **`stopPropagation` on input click** — clicking the input field doesn't re-trigger the parent expand

## Customization rules

- **Width values** can change (200 → 380 here). Pick what fits your content.
- **Spring values** are tuned — don't change unless you have a reason
- **Always autofocus the input** when expanding (for accessibility + UX)
- **Always `stopPropagation`** on the input and submit button (or you'll re-trigger expand)

## What NOT to change

- Don't replace `layout` with manual width animation — `layout` is what makes it work
- Don't use cubic-bezier — must be spring
- Don't mount the input outside `AnimatePresence` — must be conditional
- Don't remove `mode="popLayout"` — without it the icon swap janks

## Cross-references

- See `tokens.md` `SPRING_SMOOTH` preset
- See `anti-slop.md` "mounting/unmounting" anti-pattern
- See `recipes/text-roll.md` for related "morph in place" pattern
