---
name: ui
description: Use when the user asks to build a landing page, hero section, marketing site, dashboard, mobile app screen, pricing page, or any frontend they want to feel premium and not look AI-generated. Triggers on phrases like "build me a UI", "design a landing page", "make a hero", "make this look premium", "create a dashboard", "build a marketing site", or when output needs to compete with award-winning sites (Awwwards, SiteInspire, SEESAW caliber).
---

# /ui — Premium UI Build

You are about to build production-grade UI that looks like an award-winning designer made it, not an AI. This skill enforces three rules and gives you ready-to-adapt component blocks. **You do not invent layouts from scratch — you adapt blocks from `recipes/` and apply the rules.**

---

## CONFIGURATION (override per request)

- **RESTRAINT** (1-10, default 8): How aggressive the cut-everything discipline is. 1 = packed dashboard, 10 = art gallery hero.
- **MOTION** (1-10, default 7): How much animation. 1 = static, 10 = scroll-driven cinematic. **Default 7 = motion is mandatory, not optional.**

These dials override individual rules where conflicts arise. The user can override in their prompt ("with motion=8" or "low restraint").

### What MOTION = 7 means in practice

- Every interactive element has a hover state (use `recipes/animations.md` patterns)
- Every section has scroll-triggered entrance animation (`fade-up`, `stagger children`, `scale-up`)
- Every button has `:active` press feedback
- Headlines/numbers use `pop-in` or `word-by-word` reveal
- Tab/dropdown/menu uses one of the swap animations from `recipes/animations.md`
- Loading states use skeleton shimmer, never static placeholder
- A page with NO motion is a failed build — animation is the difference between "AI demo" and "premium product"

---

## THE THREE RULES (non-negotiable)

These came from analyzing 58 premium designs the owner manually curated. Every premium reference follows all three. Every AI-generated landing page violates them.

### Rule 1 — RESTRAINT IS THE SIGNAL

The most consistent finding across every premium reference. AI piles on; premium designers strip away.

- **Hero copy ≤ 8 words.** Subtext explains. Hero just confirms.
- **One accent color, used sparingly.** Only on CTAs, status dots, key emphasis.
- **Backgrounds are off-white/cream, never `#ffffff`.** Use `#fafaf7`, `#f7f5f0`, or `oklch(98% 0.005 90)`.
- **50%+ whitespace is the luxury signal.** Empty space is a feature, not a gap.
- **Default components are AI tells.** No `<Loader2 />`. No "MOST POPULAR" pricing banners. No symmetric centered everything.

> **Red flag:** If you're adding more, you're going wrong direction. Discipline is what you cut.

### Rule 2 — TYPOGRAPHY IS THE DESIGN

Headlines are the primary visual element. Build the page around them, not vice versa.

- **Stack:** Bold grotesque sans (Inter Tight or Geist) + ONE italic-serif accent word per headline (Instrument Serif).
- **Headline size:** 5xl to 7xl (~60-90px). No timid 32px headlines.
- **One italic word for emphasis.** Inside the bold sans headline. Pick the word that carries meaning.
- **Two-tone trick:** Muted-gray phrase + bold-black phrase ("Ideas to Results" / "AI-Powered Marketing.").
- **No icons in headlines. No decorative flourishes.** The type does the work.

See `tokens.md` for exact font stacks, sizes, and weights.

### Rule 3 — MOTION VIA SHARED ELEMENTS

Same surface morphs between states. Never hard cuts. Never separate components mounted/unmounted.

- **Framer Motion `layout` + `layoutId` is the primary tool.** One persistent surface morphs between states.
- **Springs over easings.** Never `cubic-bezier` for primary motion. Exact spring values in `tokens.md` § MOTION PRESETS.
- **Sub-300ms transitions.** Snappy, not slow.
- **Wild visuals always inside a calm container.** Mesh gradient inside a white card. Halftone over a steady serif headline. Containment is what makes it feel premium.
- **Per-element stagger** via `AnimatePresence`, never bulk swap.
- **Motion floor:** every build at MOTION ≥ 5 must satisfy Step 7's minimum motion checklist.

---

## THE PROCEDURE

Follow these steps **in order**. Do not skip steps.

### Step 1 — IDENTIFY page type

Pick ONE primary type. Don't mix.

| User says... | Page type | Hero recipe |
|---|---|---|
| "landing page", "marketing site", "SaaS site" | `saas` | `recipes/hero-saas.md` |
| "agency", "studio", "portfolio" | `agency` | `recipes/hero-agency.md` |
| "fintech", "currency", "money", "wallet" | `fintech` | `recipes/hero-fintech.md` |
| "dashboard", "analytics", "admin" | `dashboard` | `recipes/dashboard-shell.md` |
| "mobile app", "iOS", "onboarding" | `mobile` | `recipes/mobile-onboarding.md` |

If unsure, **stop and ask** — picking wrong page type wastes the build.

### Step 1.5 — ROLL THE DICE (anti-repetition)

Before writing a single line, **silently pick ONE option from each menu below**. This forces variation across builds and prevents falling into the same default composition every time.

**Vibe (pick 1):**
- Editorial Luxury — serif-led, generous whitespace, photo-driven
- Soft Structuralism — grid-disciplined, mono-accents, brutalist-light
- Ethereal Glass — translucent surfaces, soft glows, restrained Liquid Glass

**Hero alignment (pick 1):**
- Centered (only if vibe = Editorial Luxury, otherwise SKIP)
- Left-aligned text with right-side asset (mockup, image, or product shot)
- 50/50 split (text + asset on equal columns, asymmetric content density)

**Decoration (pick 1):**
- Photographic background (from `assets/backgrounds/`)
- Scattered corner stickers (small marks at 2-3 corners, never in dead center)
- Single contained accent (one shape, one glow, one element — bounded)

You do not show this menu to the user. You just pick and proceed.

### Step 1.6 — DESIGN PLAN PREAMBLE (forces visual thinking)

Before writing a single line of code, READ `visual-thinking.md` and silently answer its 5-phase Question Gate (Composition, Light, Depth, Materiality, Polish) in your `<thinking>` block.

The owner has tested: every build that skipped this step shipped with floating decorations overlapping content, inconsistent light direction, no depth layering, and no "expensive moment". Answering these questions before code is what separates "good attempt" from "Awwwards-tier".

**You do NOT show this thinking to the user.** It's an internal plan. But it MUST happen, and the answers MUST drive the code that follows.

### Step 2 — READ the recipe + tokens

```
Read recipes/{hero}.md          # hero block
Read recipes/{features}.md      # one of: features-bento, features-3step, features-tabs
Read recipes/pricing-2col.md    # if pricing needed
Read recipes/faq-pillrows.md    # if FAQ needed
Read recipes/footer-modern.md   # always
Read tokens.md                  # always — don't invent colors/fonts
Read anti-slop.md               # always — the patterns to NEVER use
```

Each recipe is a complete React component you adapt. **You don't write blocks from scratch. You adapt.**

### Step 3 — BUILD by composing recipes

```jsx
<HeroSaas {...props} />
<FeaturesBento {...props} />
<Pricing2Col {...props} />
<FaqPillRows {...props} />
<FooterModern {...props} />
```

Customizations allowed:
- Copy (headline, subtext, CTA labels) — must be ≤8 word headlines
- Accent color from tokens
- Background image from `assets/backgrounds/` (see `recipes/backgrounds-catalog.md`)

Customizations forbidden:
- Inventing new fonts (use stack from tokens)
- Adding more colors (one accent only)
- Removing whitespace
- Breaking recipe structure to "improve" it — recipes are battle-tested

### Step 4 — REVIEW with checklist

Run through `review.md` BEFORE shipping. If Playwright/browser available: take a screenshot, then verify against checklist. If anything fails — fix it, don't ship.

### Step 5 — SHIP

Only after Step 4 passes every item. State which checklist items passed in your final message.

### Step 6 — NO LAZY OUTPUT

Premium builds are reproduced FULLY, not summarized. The following are BANNED in any code output:

- `// ... rest of component`
- `// TODO: implement`
- `// implement here`
- `{/* similar pattern repeated */}`
- "for brevity..."
- "I can provide more details on request"
- Any ellipsis-style code skip
- **Stripping motion code from a recipe** — `motion.div` becoming `div`, removing `AnimatePresence`, deleting `whileHover`/`whileInView`, dropping `layout`/`layoutId` props. This counts as compression and is BANNED.
- **Omitting `recipes/animations.md` patterns** when the recipe references them. If a recipe says "use `t-fade-up` on entrance" and you ship plain divs without the class, you've stripped motion.

If output approaches the token limit:
1. Stop at a clean breakpoint (end of a component / end of a section)
2. Output exactly: `[PAUSED — section X of Y complete. Send "continue" to resume from: <next section name>]`
3. NEVER compress or summarize what you've already written — pause and wait

When adapting a recipe, reproduce it FULLY in the output. **Including all motion.** The recipe is the floor, not a sketch to abbreviate.

### Step 7 — INJECT ANIMATIONS

Every interactive element + every section must have animation. Pull from `recipes/animations.md` (41 patterns).

**Minimum motion floor (for any build at MOTION ≥ 5):**
- Hero: word-by-word reveal OR fade-up + stagger entrance for headline/subtext/CTA
- Every CTA button: hover-glow OR shine-sweep OR magnetic, AND `:active` press-down
- Every section: scroll-triggered fade-up entrance (intersection observer)
- Every card: hover-tilt OR spotlight-border OR lift
- Stats / numbers: number pop-in (animations #2 or #35)
- Loading states: skeleton shimmer (animation #26), never static placeholder
- Tab/dropdown/menu: use the matching swap animation from animations.md

**If shipping a section with NO motion:** STOP. Re-read `recipes/animations.md`. Pick a pattern. Apply it. A static section is a failed section.

---

## QUICK REFERENCE — what the recipes contain

| Recipe | When to use | Key technique |
|---|---|---|
| `hero-saas.md` | B2B SaaS landing | Universal hero skeleton: pill+headline+subtitle+dual-CTA+bleeding mockup |
| `hero-agency.md` | Agency / studio | Centered editorial serif, asymmetric scattered decoration |
| `hero-fintech.md` | Fintech / money apps | Split layout, dashboard mockup with glow underneath |
| `features-bento.md` | Modern grid features | Mixed-size bento, rounded-3xl cards, color-matched shadows |
| `features-3step.md` | "How it works" sections | 3 cards with sticky scroll-synced bracket tracker |
| `features-tabs.md` | Product feature tour | Persistent stage tab system (image stays mounted, content swaps) |
| `pricing-2col.md` | SaaS pricing | Basic vs Pro with "Currently Popular" pill + dot, gradient CTA |
| `faq-pillrows.md` | FAQ section | Thin pill rows, never boxy accordions |
| `footer-modern.md` | Site footer | Multi-column with giant ghost wordmark fade at bottom |
| `dashboard-shell.md` | Admin dashboard | Page header + sidebar + content area, single-accent UI |
| `mobile-onboarding.md` | Mobile flows | Single task per screen, vast whitespace, pill CTAs, cross-fade transitions |
| `morphing-button.md` | Newsletter / signup CTA | Click-to-expand pill (200px → 420px) via Framer Motion `layout` |
| `text-roll.md` | Brand-swap headline word | Vertical word-roll inside an inline pill that resizes per brand |
| `mockups.md` | Product mockups in heroes (overview + decision tree) | Priority: bundled PNG > real screenshot > SVG frame > primitive |
| `device-mockups-catalog.md` | **DEFAULT for product mockups** — 17 photoreal device PNGs | iPhone 16 Pro, MacBook Pro/Air, iPad Air, Apple Watch, iMac, Pixel 9, Dell XPS. Transparent WebP, ~14KB each. With screen-area coordinates. |
| `backgrounds-catalog.md` | Hero backgrounds | 26 bundled WebP backgrounds with text-overlay strategy per category |
| `animations.md` | **EVERY BUILD** — animation library | **41 CSS animations** (transitions.dev style). Hover, scroll-entrance, ambient, loading, text effects, toggle. Pull from this for every interactive moment. |
| `visual-thinking.md` | EVERY BUILD — Step 1.6 forced reasoning | 5-phase Question Gate (composition / light / depth / materiality / polish), banned defaults, two-part shadow law, key-light inset, grain overlay, vignette, expensive-moment list, optical alignment notes, three pre-flight tests |

---

## RED FLAGS — STOP and start over

If you catch yourself doing any of these CATEGORIES, stop and re-open the referenced file for specifics.

- ❌ **Skipping motion** — any section/button/page with zero animation. See Step 7 minimum motion floor + `recipes/animations.md`.
- ❌ **AI-default visuals** — teal/purple accent, pure `#fff` background, purple→blue gradients, glassmorphism on cards. See `anti-slop.md` § COLOR + DECORATION.
- ❌ **Default components** — `<Loader2 />`, "MOST POPULAR" pricing banner, checkmark feature lists, boxy `<Accordion>`, `rounded-md` shadcn buttons. See `anti-slop.md` § COMPONENT.
- ❌ Faking a product dashboard / app screen inline with divs + gradients (use `recipes/mockups.md` device frames + primitives instead)
- ❌ **Lazy composition** — building hero from scratch instead of adapting `recipes/hero-*.md`, centered everything, 3-equal-card features grid, empty/sparse "spacing" sections, mounting/unmounting instead of morphing.
- ❌ **Mobile/perf killers** — `h-screen`, animating `top/left/width/height`, `useState` for continuous input, `cubic-bezier` for primary motion. See `anti-slop.md` § MOBILE + MOTION.
- ❌ **Generic content** — emojis in UI, hero copy >8 words / >3 lines, "Jane Doe" names, "Acme" brands, filler verbs (Elevate/Unleash/Empower), round-fake numbers, Unsplash URLs. See `anti-slop.md` § CONTENT + TYPOGRAPHY.
- ❌ **Stripping recipe motion** — removing `motion.div`, `whileHover`, `AnimatePresence`, `layout`/`layoutId`, or `t-*` classes from a recipe to "simplify".
- ❌ **Floating decoration overlapping focal content** — sticker/note/badge `position: absolute` on top of H1/H2/big-number/CTA. See `anti-slop.md` § COMPONENT for SAFE-ZONE rule.
- ❌ **Decorative stat-chip / metric-pill floats around mockups** — "P99 LATENCY · LIVE / 42ms" type chips dotted around the hero. Default = ZERO chips. Max 1 if it surfaces unique product info. See `anti-slop.md` § COMPONENT FLOATING-CHIP RULE.
- ❌ **Marquee with visible loop seam (N-shape)** — items appear/restart mid-band. Track must duplicate content + animate `-50%` + use pixel-based edge mask. See `recipes/animations.md` § 25 Marquee + `anti-slop.md` § COMPONENT.
- ❌ **Skipping responsive breakpoints** — desktop-only build that breaks at 375px / 390px / 768px. Test at all 5 breakpoints with Playwright `browser_resize`. See `tokens.md` § RESPONSIVE / FLUID SIZING.
- ❌ **Skipping `review.md`** because "it looks fine".
- ❌ **Skipping the `visual-thinking.md` Question Gate** (output ships visibly worse — flat depth, inconsistent light, no expensive moment).

**All of these mean: STOP. Re-read the relevant rule. Adapt the right recipe.**

---

## COMMON MISTAKES

### "I'll just build the hero from scratch, the recipes are too restrictive."

You will produce AI-generated output. The recipes are the discipline that prevents that. **Adapt them. Don't replace them.**

### "The user wants more than 8 words in the headline."

Push back. Suggest moving extra context to subtext. If they insist, log a comment in the code: `// HERO COPY EXCEEDS RULE 1 — explicit user request`. Then comply.

### "I need three accent colors for this brand."

You don't. Pick one. The other "colors" come from photography, gradients, and the off-white background — not flat color fills.

### "I need to add a section to fill space."

Empty space is the design. Don't fill it. If the page legitimately needs more content, add a *real* section (testimonials, integrations, FAQ) — not a decorative one.

### "Animation feels janky."

You used `cubic-bezier` or you're swapping components instead of morphing. Switch to spring + `layoutId`. See `recipes/morphing-button.md`. Also confirm you're animating ONLY `transform` and `opacity` — never `top/left/width/height`.

---

## WHY THIS WORKS

The patterns in these recipes were extracted from analyzing 58 premium designs the owner curated personally — every Awwwards-tier site, every viral X design tweet, every fintech that doesn't look like a template. Every one followed the three rules. Every AI-generated landing page violates them.

You do not have a creative choice here. You execute the discipline. The discipline is what looks expensive.

---

## REFERENCE FILES

- `tokens.md` — colors, fonts, spacing, motion presets (read every build)
- `anti-slop.md` — the AI-tell patterns to avoid in detail (read every build)
- `review.md` — pre-ship checklist (read in Step 4)
- `recipes/` — 14 ready-to-adapt component blocks
- `assets/backgrounds/` — 26 bundled WebP background images
