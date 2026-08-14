# recipes/mobile-onboarding.md — Mobile App Onboarding Flow

**One screen per task, vast whitespace, pill CTAs, cross-fade transitions.** Adapted from Kruz, marcelkargul mobile app showcase, ashik onboarding.

## When to use

- Mobile app onboarding (sign-up, profile setup, preferences)
- Mobile-first product flows
- User says: "mobile app", "iOS", "onboarding flow", "sign-up screens"

## Core principles for mobile

1. **One task per screen.** Never combine.
2. **50%+ whitespace** — mobile screens look luxe with big empty space
3. **Single accent color** for CTA — everything else neutral
4. **Pill CTAs at the bottom** (full-width, 56px height min for touch)
5. **Cross-fade between screens**, not slide (slides feel cheap)

## Code (single screen example)

```tsx
import { motion } from "framer-motion";

export function OnboardingScreen({
  step,
  title,
  subtitle,
  primaryLabel,
  onPrimary,
  secondaryLabel,
  onSecondary,
}: {
  step: { current: number; total: number };
  title: string;
  subtitle: string;
  primaryLabel: string;
  onPrimary: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
}) {
  return (
    <motion.div
      key={`${step.current}`}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
      className="flex flex-col h-screen bg-[var(--bg)] px-6"
    >
      {/* Top: progress dots */}
      <div className="pt-12 flex justify-center gap-1.5">
        {Array.from({ length: step.total }).map((_, i) => (
          <span
            key={i}
            className={`h-1 rounded-full transition-all ${
              i === step.current ? "w-8 bg-[var(--accent)]" : "w-1 bg-[var(--border)]"
            }`}
          />
        ))}
      </div>

      {/* Center: minimal content (single task) */}
      <div className="flex-1 flex flex-col justify-center text-center">
        <h1 className="font-sans text-3xl font-extrabold tracking-tight leading-tight max-w-xs mx-auto">
          {title}
        </h1>
        <p className="mt-3 text-sm text-[var(--text-muted)] max-w-xs mx-auto">
          {subtitle}
        </p>
      </div>

      {/* Bottom: pill CTAs */}
      <div className="pb-10 space-y-3">
        <button
          onClick={onPrimary}
          className="w-full h-14 rounded-full bg-[var(--accent)] text-[var(--accent-fg)] font-semibold transition-transform active:scale-[0.98]"
        >
          {primaryLabel}
        </button>
        {secondaryLabel && (
          <button
            onClick={onSecondary}
            className="w-full h-14 rounded-full text-[var(--text-muted)] font-medium"
          >
            {secondaryLabel}
          </button>
        )}
      </div>
    </motion.div>
  );
}
```

## Multi-screen flow with cross-fades

```tsx
import { AnimatePresence } from "framer-motion";
import { useState } from "react";

const SCREENS = [
  { title: "Welcome to Kruz.", subtitle: "Let's get you set up in under a minute." },
  { title: "What should we call you?", subtitle: "This is how you'll appear to other members." },
  { title: "Pick your interests.", subtitle: "We'll personalize your feed." },
  { title: "All set!", subtitle: "Let's go." },
];

export function OnboardingFlow() {
  const [step, setStep] = useState(0);

  return (
    <AnimatePresence mode="wait">
      <OnboardingScreen
        key={step}
        step={{ current: step, total: SCREENS.length }}
        title={SCREENS[step].title}
        subtitle={SCREENS[step].subtitle}
        primaryLabel={step === SCREENS.length - 1 ? "Get started" : "Continue"}
        onPrimary={() => setStep((s) => Math.min(s + 1, SCREENS.length - 1))}
        secondaryLabel={step > 0 ? "Back" : undefined}
        onSecondary={() => setStep((s) => Math.max(s - 1, 0))}
      />
    </AnimatePresence>
  );
}
```

## Customization rules

- **Cross-fade only** (no slides). Use `<AnimatePresence mode="wait">` + opacity transition
- **Progress dots at top** — current dot is wider AND accent-colored
- **CTA at bottom uses `var(--accent)` filled pill** with `active:scale-[0.98]` for tap feedback
- **Single task per screen** — don't combine "name + email + password" on one screen, split into 3
- **Center the content vertically** — use `flex-1` between top and bottom

## What NOT to change

- Don't use slide transitions (`x: 100` → `x: 0`) — looks cheap
- Don't shrink CTA below `h-14` (mobile touch target minimum)
- Don't add icons in the headline
- Don't use shadcn `<Card>` — it adds borders that don't belong on mobile

## Cross-references

- See `tokens.md` for accent + spacing
- See `anti-slop.md` for default mobile patterns to avoid
- See `recipes/morphing-button.md` if onboarding has email signup at the end
