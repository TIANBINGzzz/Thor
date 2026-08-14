# /ui — Premium UI skill for Claude Code

Built from analysis of **58 manually curated premium designs** (Awwwards-tier sites, viral X design tweets, Framer templates, fintech apps).

Drops the AI-tell defaults: no `<Loader2 />`, no purple-to-blue gradients, no "MOST POPULAR" banners, no centered-everything, no `text-3xl` heroes, no Inter (without Tight), no Space Grotesk.

Produces output that competes with award-winning sites — instead of generic SaaS templates.

---

## Install

```sh
npx @theylovlj/ui-skill
```

Installs to `~/.claude/skills/ui/`. Existing skill (if any) is backed up.

---

## Use

In Claude Code:

```
/ui build me a fintech landing page for a currency exchange called PennyJar
```

Or just:

```
/ui make me a beautiful pricing page
```

The skill:
1. Loads the procedure (3 rules + 5-step build process)
2. Picks the right recipes from `recipes/` based on what you described
3. Reads `tokens.md` (colors/fonts/motion presets) so it doesn't invent
4. Reads `anti-slop.md` so it doesn't fall back to AI defaults
5. Builds by adapting battle-tested recipe blocks
6. Reviews against `review.md` (Playwright checks if available)

---

## What's inside

```
ui/
├── SKILL.md                 The procedure + 3 rules (loaded every build)
├── tokens.md                Color/font/motion presets (loaded every build)
├── anti-slop.md             AI-tell patterns to avoid (loaded every build)
├── review.md                Pre-ship checklist (loaded in step 4)
├── recipes/                 14 ready-to-adapt React blocks
│   ├── README.md            Decision tree — which recipe for which page type
│   ├── hero-saas.md         Universal B2B SaaS hero
│   ├── hero-agency.md       Editorial center-aligned with corner stickers
│   ├── hero-fintech.md      Split layout with live converter widget
│   ├── features-bento.md    Mixed-size asymmetric grid
│   ├── features-3step.md    "How it works" with sticky bracket tracker
│   ├── features-tabs.md     Persistent stage tab tour
│   ├── pricing-2col.md      Two-tier with subtle popular indicator
│   ├── faq-pillrows.md      Pill rows, never accordion
│   ├── footer-modern.md     Multi-column + ghost wordmark
│   ├── dashboard-shell.md   Sidebar + page header + content area
│   ├── mobile-onboarding.md One-task-per-screen flow
│   ├── morphing-button.md   Click-to-expand pill (Framer Motion layout)
│   ├── text-roll.md         Brand-swap word in headline
│   └── backgrounds-catalog.md  How to use the 26 bundled BGs
└── assets/
    └── backgrounds/         26 premium WebP backgrounds (1.6MB total)
```

---

## The 3 rules

### Rule 1 — RESTRAINT IS THE SIGNAL
Hero copy ≤ 8 words. ONE accent color. Off-white backgrounds (never `#fff`). 50%+ whitespace. No default components (no `Loader2`, no "MOST POPULAR" banner).

### Rule 2 — TYPOGRAPHY IS THE DESIGN
Bold grotesque sans (Inter Tight, Geist) + ONE italic-serif accent word per headline (Instrument Serif). Hero size `text-5xl` to `text-6xl`. Headlines are the visual — no icons, no decoration around them.

### Rule 3 — MOTION VIA SHARED ELEMENTS
Same surface morphs between states. Framer Motion `layout` + `layoutId`. Springs, never cubic-bezier. Sub-300ms. Wild visuals always inside calm containers.

---

## Why a v2

The v1 skill (12,400 lines, 52 files) failed because Claude couldn't read it all during builds — it kept falling back to AI defaults. v2 is **76% smaller** (2,930 lines, 19 files) and uses Claude Code's progressive disclosure model: the foundation is small, recipes load only when needed.

---

## Source

[github.com/theylovlj/ui-skill](https://github.com/theylovlj/ui-skill)

MIT license.
