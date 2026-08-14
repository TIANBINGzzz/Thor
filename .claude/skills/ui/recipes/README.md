# recipes/ — Decision Tree

Read this first when picking which recipes to use. Each recipe is a complete React component you adapt — you do NOT build from scratch.

---

## Step 1 — Identify the page type

| User says... | Page type | Hero recipe |
|---|---|---|
| "landing page", "marketing site", "SaaS" | SaaS | `hero-saas.md` |
| "agency", "studio", "portfolio", "freelance" | Agency | `hero-agency.md` |
| "fintech", "currency", "money", "wallet", "crypto", "banking", "payments" | Fintech | `hero-fintech.md` |
| "dashboard", "analytics", "admin", "control panel" | Dashboard | `dashboard-shell.md` |
| "mobile app", "iOS", "onboarding", "sign-up flow" | Mobile | `mobile-onboarding.md` |

---

## Step 2 — Compose your page from blocks

Most landing pages need 4-6 blocks. Pick from this menu:

### Navigation (always 1 if marketing site)
- `nav-pill.md` — sticky pill-capsule nav (default)
- `nav-megamenu.md` — when nav item needs a multi-column dropdown panel

### Heroes (always 1)
- `hero-saas.md` — SaaS, B2B, AI products
- `hero-agency.md` — Agencies, studios, portfolios
- `hero-fintech.md` — Money/payment products
- `hero-split-process.md` — Edtech, course platforms, onboarding-heavy SaaS (sticky process column)
- `hero-image-reveal.md` — Editorial brands, type-forward products, design studios

### Features (usually 1)
- `features-bento.md` — 4-7 mixed-importance features (default)
- `features-3step.md` — Sequential "how it works" (3 steps only)
- `features-tabs.md` — Product tour with persistent stage (4-6 features)
- `features-cinematic-blur.md` — Cinematic / luxury / EV mood (4 features, 2×2 grid over blurred photo)
- `bento-archetypes.md` — Five named bento archetypes (Intelligent List, Command Input, Live Status, Wide Data Stream, Focus Mode) — pair with `features-bento.md`

### Social proof (optional, 0-1)
- `logo-arc.md` — premium centerpiece arrangement (replaces horizontal marquee)
- Or use the testimonials pattern from `dashboard-shell.md`'s KPI strip, or a horizontal grayscale logo bar after the hero

### Dashboard content blocks
- `dashboard-status-quadrant.md` — 2×2 status-count summary (NEW / IN PROGRESS / RESOLVED / DEEP FIX)
- `dashboard-audit-log.md` — audit log table with inline diff-row expansion

### Primitives (drop into any other recipe)
- `button-premium.md` — 4-layer shadow-stack CTA + circular icon partner
- `double-bezel-card.md` — Doppelrand nested wrapper for cards / inputs / CTAs

### Mockups (drop into any hero or feature section)
- `mockups.md` — **Device frames** (BrowserFrame, MacBookFrame, iPhoneFrame, AppleWatchFrame, TabletFrame, CardFrame) + **content primitives** (LineChart, BarChart, KPIStrip, Sidebar, TableRows, ChatThread, CalendarGrid, CodeEditor, TerminalWindow). Use whenever you'd otherwise invent a fake dashboard with `<div>`s. The single most important file for hero quality.
- `image-generation.md` — optional power-up: real AI-generated product photos via fal.ai / Replicate / OpenAI

### Pricing (only if relevant, 0-1)
- `pricing-2col.md` — 2 tiers + "Talk to sales" link

### FAQ (always 1 if pre-purchase)
- `faq-pillrows.md` — Thin pill rows, never accordion

### Footer (always 1)
- `footer-modern.md` — With ghost wordmark

### Micro-interactions (sprinkled in any block)
- `morphing-button.md` — Click-to-expand pill (newsletter signup)
- `text-roll.md` — Brand-swap word in headline
- `button-premium.md` — Premium dark/light pill CTA + circular icon partner

---

## Recipes index

| File | Use for | Key technique |
|---|---|---|
| `nav-pill.md` | Default top nav | Floating max-w container, pill-grouped links with `layoutId` indicator, right-side CTA |
| `nav-megamenu.md` | Multi-section nav dropdown | Multi-column link list (Mistral) or screenshot preview (Twenty) anchored under nav-pill |
| `hero-saas.md` | B2B SaaS / AI heroes | Centered headline + dual CTA + bleeding mockup with color-matched glow |
| `hero-agency.md` | Agency / portfolio heroes | Editorial serif, scattered decoration |
| `hero-fintech.md` | Money / payments heroes | Split layout with live converter widget |
| `hero-split-process.md` | Edtech / onboarding-heavy SaaS | Asymmetric split: left product preview with floating pills, right sticky process list |
| `hero-image-reveal.md` | Editorial / agency / type-forward | Massive headline with cursor-tracked image reveal via `mask-image` + `useSpring` |
| `features-bento.md` | Mixed-importance features | Variable cell sizes in a grid |
| `features-3step.md` | Sequential "how it works" | 3 steps with progress connectors |
| `features-tabs.md` | Product tour with stage | `layoutId` slider + persistent product stage |
| `features-cinematic-blur.md` | Cinematic / luxury feature sections | Blurred photo backdrop + 2×2 borderless cards inside glass container |
| `bento-archetypes.md` | Live bento cells | 5 named archetypes with infinite-loop micro-animations |
| `logo-arc.md` | Social-proof centerpiece | Cos/sin radial placement + uniform logo bricks + spring entrance |
| `pricing-2col.md` | 2-tier pricing | Filled featured tier + outlined alternative |
| `faq-pillrows.md` | FAQ section | Thin pill rows, never accordion |
| `footer-modern.md` | Footer | Ghost wordmark + meta-typography |
| `mobile-onboarding.md` | Mobile / iOS flows | Sheet patterns, swipe gestures |
| `dashboard-shell.md` | Dashboard chrome | Sidebar + page header + KPI strip + comparison line chart |
| `dashboard-audit-log.md` | Activity / audit log | Inline expand-row + verb-family color chips + git-style diff |
| `dashboard-status-quadrant.md` | "Summary by status" 2×2 | Pastel-tint mini-cards keyed to status, with dot + meta-label + count |
| `button-premium.md` | Primary CTA buttons | 4-layer shadow + gradient fill + matched stroke; partner circular icon-only secondary |
| `double-bezel-card.md` | Premium card / input / CTA chassis | Outer thin shell + inner core with concentric radii (Doppelrand) |
| `morphing-button.md` | Click-to-expand pill | Framer Motion `layout` + spring |
| `text-roll.md` | Brand-swap headline word | Vertical text marquee |
| `backgrounds-catalog.md` | Hero backgrounds | 26 WebP backdrops + CSS-only Stone Dotted Grid + Pastel Gradient Stripes |
| `mockups.md` | Product mockups in heroes/features | Device frames (Browser/MacBook/iPhone/AppleWatch/Tablet/Card) + content primitives (LineChart, KPIStrip, Sidebar, TableRows, ChatThread, CalendarGrid, CodeEditor, TerminalWindow). Replaces fake-dashboard div soup. |
| `image-generation.md` | Real AI image gen (optional) | fal.ai / Replicate / OpenAI integration for genuine product photos |

---

## Step 2.5 — Mockups (the fake-dashboard fix)

If your hero or feature section needs a product mockup and you don't have a real screenshot, **stop and read `mockups.md`**. It's the single biggest source of AI tells.

Decision flow:

1. **Real product screenshot exists?** → use it, optionally wrapped in `<BrowserFrame>` from `mockups.md`.
2. **No screenshot, web app product?** → `<BrowserFrame>` + 1-3 primitives (`Sidebar`, `KPIStrip`, `LineChart`, `TableRows`, `CodeEditor`, `TerminalWindow`, `CalendarGrid`).
3. **No screenshot, mobile app?** → `<IPhoneFrame>` + ONE primitive (`ChatThread`, `KPIStrip`, etc).
4. **No screenshot, desktop app / dev tool?** → `<MacBookFrame>` + composition.
5. **Wearable / health?** → `<AppleWatchFrame>` + simple stat.
6. **Conceptual product, no UI yet?** → use a hero photo from `assets/backgrounds/`. **Do NOT invent UI.**

The cardinal sin this section prevents: building a "fake dashboard" inline with `<div>`s + gradients + made-up "Sales / Revenue / Activity" cards. That's the #1 most-cited AI-tell after `<Loader2 />`.

---

## Step 3 — Always read these BEFORE building

```
Read SKILL.md           # the procedure (you're already here)
Read tokens.md          # colors, fonts, motion presets
Read anti-slop.md       # the patterns to NEVER use
```

These are required for EVERY build. They take ~10 seconds to scan.

---

## Step 4 — Optional reads based on need

| If you're using... | Also read... |
|---|---|
| Any hero with a background image | `recipes/backgrounds-catalog.md` |
| Layout morphs (button → input, card expand) | `tokens.md` "Motion presets" section + `recipes/morphing-button.md` |
| Tab UI / segmented control | `recipes/features-tabs.md` (for `layoutId` pattern) |

---

## Common page compositions

### B2B SaaS landing page (the standard)
```
<HeroSaas />
<TrustLogosBar />        // grayscale, scroll-hint
<FeaturesBento />
<Features3Step />        // "How it works" — only if process matters
<Pricing2Col />
<FaqPillRows />
<FooterModern />
```

### Agency / portfolio landing page
```
<HeroAgency />
<CaseStudiesGrid />      // adapt FeaturesBento — replace features with project tiles
<ServicesList />         // adapt Features3Step
<TestimonialQuote />     // single big quote, not 3-card carousel
<FooterModern />
```

### Fintech landing page
```
<HeroFintech />          // includes live converter widget
<Features3Step />        // "Sign up → Send → Done"
<TrustBar />             // banks, partners, regulators
<Pricing2Col />          // optional — many fintechs are free
<FaqPillRows />
<FooterModern />
```

### Mobile app marketing page (web)
```
<HeroSaas />             // with phone mockup as the product image
<FeaturesBento />        // each card shows a screen
<TestimonialQuote />     // user reviews
<DownloadCTA />          // app store + google play badges
<FooterModern />
```

### In-app dashboard (logged-in)
```
<DashboardShell>
  <KpiStrip />
  <RecentActivityList />
  <ProjectsGrid />
</DashboardShell>
```

---

## Anti-compositions (NEVER do these)

- ❌ Hero + 3 testimonials + features + 3 testimonials + features + footer (alternating reads as desperate)
- ❌ Multiple hero sections (only ONE per page)
- ❌ Pricing AND "talk to sales" big banner (redundant — Pricing has a Talk-to-sales link)
- ❌ FAQ with only 2 questions (combine with Pricing or skip)
- ❌ "How it works" with 5+ steps (use bento or features-tabs instead)

---

## Final check before building

Before you start writing code, confirm:

- [ ] I've identified the page type from the table above
- [ ] I've read SKILL.md, tokens.md, anti-slop.md
- [ ] I know which 4-6 recipe blocks I'll use
- [ ] I've read each chosen recipe file
- [ ] I have a real product context (no Lorem ipsum, no fake screenshots)

If any are NO — go back. Don't ship without all 5.
