# anti-slop.md — The patterns to NEVER use

**Read this every build. These are the patterns that make UI look AI-generated.**

Each pattern below is a default that Claude (and other LLMs) gravitate toward when given a generic prompt. If you find yourself doing any of them — STOP and use the correction listed.

---

## THE GSTACK BANNED-DEFAULT BLACKLIST

Hard rejection list — if any of these are in the output, it's slop. Mirrored in `visual-thinking.md`.

### ❌ Purple/violet/indigo gradient backgrounds
**Why it's slop:** The AI-defaults-here color. Every cookie-cutter LLM landing page lands here.
**Fix:** No purple/violet/indigo as the bg gradient. Use one of the 4 palette presets in `tokens.md`. If you need depth, use a soft single-hue radial OR a warm-cool split (`tokens.md` § ATMOSPHERE).

### ❌ Blue→purple color schemes
**Why it's slop:** The default Tailwind+ChatGPT palette. Reads as "I picked the first two colors I thought of."
**Fix:** ONE accent color from the four palettes. Neutral text + neutral bg + ONE accent.

### ❌ 3-column feature grid with icon-in-circle + bold title + 2-line desc
**Why it's slop:** The cardinal sin. Single most-recognized AI tell on the internet. The literal Bootstrap 4 SaaS template.
**Fix:** Bento grid (`recipes/features-bento.md`) with mixed sizes. Or a sticky 3-step (`recipes/features-3step.md`). Or asymmetric split with one full-bleed feature + two small stacked.

### ❌ Emoji used as design elements
**Why it's slop:** Emojis are CONTENT, never decoration. Renders inconsistently across OS, instantly screams template.
**Fix:** Phosphor or Radix icons. Or no icon at all — typography does the work.

### ❌ Cookie-cutter section rhythm (hero → 3-features → testimonials → pricing → CTA)
**Why it's slop:** Literal Vercel Geist template structure. Every AI landing page from 2023-2026.
**Fix:** Vary the rhythm — Hero → Trust logos → Story → Demo → Pricing → FAQ → Footer, OR Hero → How-it-works → Features → Testimonials → Pricing → Footer. Mix it up section by section.

### ❌ Default font stacks (Inter regular, Roboto, Arial, system) without intent
**Why it's slop:** Picked the font because it's free, not because it serves the work.
**Fix:** One of the three named pairings in `tokens.md` § FONT STACKS. Inter Tight + Instrument Serif, Geist + PP Editorial, or Uncut Sans + Reply.

### ❌ Decorative blobs / SVG dividers as filler
**Why it's slop:** Used to hide that there's no content in the section.
**Fix:** If a section needs a divider, the section itself is wrong — either commit to real content or remove. Use bundled WebP backgrounds in `assets/backgrounds/` instead of SVG blob filler.

### ❌ Glassmorphism + neon glow + blurred orbs combo
**Why it's slop:** Peak 2021 AI aesthetic. Reads as "trying too hard."
**Fix:** Liquid Glass spec only (`tokens.md`). Glass for sticky nav and floating overlays, never for cards/sections. No orb stack.

### ❌ Monospace everywhere (the hackathon look)
**Why it's slop:** Mono is for code, data, labels — not body. Mono everywhere = "I learned dev tools yesterday."
**Fix:** Sans for body and headlines. Mono only for: code blocks, numeric data in dashboards, meta labels in corners, eyebrow kickers.

### ❌ Generic SaaS card grid as first impression
**Why it's slop:** Three identical rounded-2xl shadcn cards on white. Below-the-fold pattern shoved into the hero.
**Fix:** Hero is for ONE focal moment — headline + product visual + dual CTA. Save the card grid for after the fold.

### ❌ Beautiful imagery with weak brand presence
**Why it's slop:** The photo overpowers the brand and the page becomes a stock-photo gallery. Visitor remembers the photo, not you.
**Fix:** Brand wordmark / accent / type sits ON or IN the image. Photo serves the brand, not the other way around.

---

## MOBILE / VIEWPORT ANTI-PATTERNS

### ❌ `h-screen` for full-height hero sections
**Why it's slop:** Catastrophic iOS Safari bug. When the address bar collapses/expands, the layout JUMPS several hundred pixels mid-scroll. Looks broken.
**Fix:** Use `min-h-[100dvh]` (dynamic viewport height) instead. Always.

### ❌ Asymmetric layouts that don't collapse on mobile
**Why it's slop:** `md:col-span-2` patterns that stay broken at <768px. Forces horizontal scroll.
**Fix:** Every asymmetric layout MUST have explicit mobile reset to single-column (`grid-cols-1 px-4 py-8`).

### ❌ Backdrop-blur on scrolling content
See `architecture.md` § Performance for the rationale. Rule: backdrop-blur ONLY on fixed/sticky elements.

### ❌ Z-index spam (`z-50`, `z-[9999]` everywhere)
See `tokens.md` § Z-INDEX DISCIPLINE for the standard stack.

---

## COLOR ANTI-PATTERNS

### ❌ Teal `#14b8a6` as primary accent
**Why it's slop:** Default Tailwind palette + Claude's training bias = teal lands first. It immediately signals "AI made this."
**Fix:** Use one of the 4 palette presets in `tokens.md`. Warm coral, indigo-violet, amber, or burnt sienna.

### ❌ `bg-gradient-to-br from-purple-500 to-blue-500`
**Why it's slop:** The single most-recognized AI-generated gradient. Used by every cookie-cutter landing page.
**Fix:** No multi-color gradients. If you need depth, use a soft single-hue radial: `radial-gradient(ellipse at top, oklch(95% 0.05 60), transparent)`. Or skip gradient entirely — bundled backgrounds in `assets/backgrounds/` are better.

### ❌ Pure `#ffffff` background
**Why it's slop:** Pure white is harsh and budget. Premium designs use off-white.
**Fix:** `oklch(98% 0.005 90)` (warm) or `oklch(98% 0.002 250)` (cool).

### ❌ Pure `#000000` text
**Why it's slop:** Same reason — too clinical.
**Fix:** Slightly tinted: `oklch(20% 0.01 90)` for warm, `oklch(22% 0.01 250)` for cool.

### ❌ More than 3 colors total in the design
**Fix:** ONE accent + neutral text + neutral background. That's it. Photography and gradients introduce other colors *in images*, not as flat fills.

### ❌ Pure neutral grays (`gray-500`, `slate-500`, `zinc-500`)
**Why it's slop:** Pure neutral grays are lifeless. Premium designs tint grays toward the brand hue at low chroma, so the gray belongs to the palette instead of fighting it.
**Fix:** Use an HSL/OKLCH ramp where neutrals share the brand's hue at chroma 0.005-0.015. On a warm-coral-accent build, gray text becomes `oklch(45% 0.01 30)` — slightly warm. On a cool-indigo build, `oklch(45% 0.015 250)` — slightly cool. Same lightness, different micro-warmth.

---

## TYPOGRAPHY ANTI-PATTERNS

### ❌ Inter (without Tight) as headline font
**Why it's slop:** Default Vercel template font. Used by every "next.js + tailwind" tutorial.
**Fix:** Inter Tight, Geist, or Uncut Sans for headlines. Inter (regular) is fine for body if needed.

### ❌ Space Grotesk
**Why it's slop:** Specifically called out in research as "the AI defaults here" font.
**Fix:** See above.

### ❌ Headline + subhead in same font weight
**Why it's slop:** Flat hierarchy = AI didn't think about typographic contrast.
**Fix:** Headline `font-bold` (700) or `font-extrabold` (800). Subtext `font-normal` (400). Big jump.

### ❌ ALL HEADLINES ARE ITALIC
**Why it's slop:** The italic-serif move only works if used on ONE word per headline. All-italic = decorative.
**Fix:** `<h1>Build something <em>beautiful</em>.</h1>` — only the emphasis word italic.

### ❌ Headline with icons next to it
**Why it's slop:** AI defaults to "let me add an icon to make it pop." Premium typography stands alone.
**Fix:** No icon (and definitely no emoji) in or beside H1. Save icons for nav, buttons, feature cards.

### ❌ Emojis in product UI
**Why it's slop:** Renders inconsistently across OS. Reads as AI-generated content. Instantly unprofessional.
**Fix:** NEVER use emojis in code/markup/text/alt-text/headings/buttons/labels. Use Phosphor or Radix icons instead.

### ❌ `text-3xl` hero (or smaller)
**Why it's slop:** Timid. Premium heroes are `text-5xl` to `text-6xl`.
**Fix:** Always `text-5xl md:text-6xl` for primary hero. `text-4xl md:text-5xl` for section H2s.

---

## LAYOUT ANTI-PATTERNS

### ❌ Three-column feature grid with identical card sizes
**Why it's slop:** The single most generic SaaS landing page pattern. AI defaults here every time.
**Fix:** Bento grid (`features-bento.md`) with mixed sizes. Or a single asymmetric split (text left, illustration right).

### ❌ "Hero → Features → Pricing → CTA → Footer" in that exact order
**Why it's slop:** It's the literal Vercel Geist template structure.
**Fix:** Vary the rhythm. Some premium sites: Hero → Trust logos → Story → Demo → Pricing → FAQ → Footer. Or Hero → "How it works" → Features → Testimonials → Pricing → Footer. Mix it up.

### ❌ Centered everything (text-center on every section)
**Why it's slop:** Symmetric centering with no asymmetric tension reads as "I didn't think about composition."
**Fix:** Center the hero. After that, ALTERNATE between left-aligned and split-layout sections.

### ❌ Empty sections with only a heading and subtitle
**Why it's slop:** AI generated the structure but ran out of content. Maximum dead-space crime.
**Fix:** Every section must have meaningful content density. If you don't have content for a section, REMOVE the section. Don't ship a hollow shell.

### ❌ Linear spacing scale (4 / 8 / 12 / 16 / 20 / 24 in equal steps)
**Why it's slop:** Linear scales feel mechanical — every gap looks like the previous gap plus 4. Premium designs use NON-LINEAR scales where the gaps grow.
**Fix:** Use the non-linear scale: `4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96 / 128`. Notice the jumps — 16→24 (1.5x), 24→32 (1.33x), 32→48 (1.5x), 48→64 (1.33x), 64→96 (1.5x). The growth produces visual rhythm; linear produces monotone.

### ❌ Footer with 5 columns of mostly-empty link lists
**Why it's slop:** Default footer with placeholder columns ("Product / Company / Resources / Legal / Social") and 1-2 real links per column.
**Fix:** Either fewer, denser columns, OR an editorial-style footer with the giant ghost wordmark + sparse, real links.

---

## COMPONENT ANTI-PATTERNS

### ❌ Faking a dashboard / app screenshot inline with divs + gradients
**Why it's slop:** The single most-cited AI tell after `<Loader2 />`. Random rectangles labeled "Sales / Revenue / Activity" with chevron arrows and gradient backgrounds. Always looks worse than the actual product would.
**Fix:** Three valid options (NEVER invent UI from scratch):
1. Use a real screenshot of the product (`<img src="/dashboard.png" />`)
2. Use a device frame + clean content primitives from `recipes/mockups.md`
3. If product has no UI yet, use a single hero photo (no fake mockup at all)

### ❌ Floating decoration cards that overlap text, numbers, or CTAs
**Why it's slop:** The classic AI tell where a "playful" sticker/note/badge gets `position: absolute` placed without checking what's underneath. Result: the float lands on top of a stat number, a CTA button, or H1 — and it looks like a layout bug, not a deliberate composition. Owner saw this exact failure on a Vellum hero where a floating "notes/main" card sat on top of the "8,412" stat.

**Fix — the SAFE-ZONE rule:**

Floating decorative elements (stickers, note cards, badges, pills, accent shapes) are only allowed in the **margin safe zone** of the section, NEVER inside the focal content area.

- **Section anatomy:** every section has (a) a focal content rectangle (where text + CTAs live, max-w-4xl roughly centered) and (b) a margin safe zone (the space outside that focal rectangle but inside the section padding).
- **Decorations live ONLY in the safe zone.** Top-left corner, top-right corner, bottom-left corner, bottom-right corner. Or hugging the left/right edge mid-section. NEVER in the horizontal middle band where text lives.
- **Set explicit z-index ONLY on the focal content** (`z-10`) and leave decorations at default (`z-0`). If a decoration must sit at a higher z to be visible, it shouldn't be there in the first place.
- **Bounding-box check:** before placing any `absolute` decoration, mentally compute its bounding box. If that box intersects the bounding box of any H1, H2, big-number stat, or CTA button → move it. No exceptions.
- **Max 4 floating decorations per section.** More than 4 is clutter, not composition.
- **Asymmetric placement:** never place 2 decorations symmetrically (e.g. one top-left + one top-right at the same y). Vary y-offset and rotation per decoration.
- **Always rotate decorations** by `±6deg` to `±15deg` so they don't read as accidental UI.

**Verification (in `review.md` step):** at every section, run a Playwright `boundingBox()` overlap check between every `position: absolute` element and every `<h1>`, `<h2>`, `[data-stat]`, and `button` inside the section. Any intersection → flag and re-position.

### ❌ Decorative stat-chip / metric-pill / "live status" floating cards around a mockup
**Why it's slop:** The "P99 LATENCY · LIVE / 42ms ▼ 8.2%" floating chip pattern. Looks impressive at first glance — until you realize every AI-generated SaaS hero has 2-4 of them dotted around the product mockup, all communicating fake-real-time stats nobody asked for. Pure decoration that screams "I'm trying to look like Linear/Vercel."

**Fix — the FLOATING-CHIP RULE:**

- **Hero default = ZERO floating chips.** The product mockup speaks for itself. The dual CTA + headline + subtext do the selling.
- **Allowed: ONE chip MAX**, and only if it surfaces a critical product value the user CAN'T see otherwise (e.g. "Scanning… 247 services connected" because you literally couldn't tell that from the dashboard alone).
- **Banned: stat chips that DUPLICATE info already visible** ("P99 latency 42ms" when the dashboard mockup already shows latency).
- **Banned: stacks of 2-3 chips around the mockup** at varying corners. That's the literal AI tell.
- **Banned: fake "LIVE" / "ONLINE" / "SYNCING" status badges** that imply real-time data without actually doing anything.
- **Banned: chips with arrows + percentages** (`▼ 8.2%`, `▲ 12%`) unless they reflect actual product data the user is asking about.

If you wrote a chip and can't explain in one sentence what unique product truth it reveals — DELETE IT.

### ❌ Marquees / infinite-scroll bands with visible loop seam ("N-shaped" loop)
**Why it's slop:** The single most-recognized "broken animation" AI tell. The loop point is visible inside the viewport — you can see logos / text mid-loop fading out and restarting. Owner literally sent a screenshot of this failure with "Outlier" appearing twice in the visible band.

**Fix — the SEAMLESS LOOP RULES:**

1. **Duplicate the content INSIDE the marquee track.** The animation translates `-50%` (not `-100%`), and the track contains TWO copies of the items. So as the first set scrolls off-screen, the second set is already there to take its place — invisible loop point.
   ```jsx
   <div className="t-marquee-track">
     {items.map(...)}
     {items.map(...)}  {/* DUPLICATE — required for seamless loop */}
   </div>
   ```
   ```css
   @keyframes scroll {
     from { transform: translateX(0); }
     to   { transform: translateX(-50%); }  /* NOT -100% */
   }
   ```

2. **Edge mask gradient** that fully fades the leftmost and rightmost ~80px to the section background:
   ```css
   .t-marquee-container {
     mask-image: linear-gradient(90deg, transparent 0%, black 80px, black calc(100% - 80px), transparent 100%);
   }
   ```
   Without this mask, the entry/exit of items is visible — looks janky.

3. **Use `transform: translateX()` only** — never animate `left` or `margin-left` (layout reflow per frame, kills mobile fps).

4. **Speed:** 30-60 seconds for ONE full loop is the readable range. Faster = nausea, slower = nobody notices the motion.

5. **Pause on hover (optional)** if items are clickable — but never pause an ambient logo wall.

6. **No fewer than 8 items per copy** — if you have 4 logos, duplicate to 8 inside ONE copy, then the track has 16 total. Too few items = the seam is unavoidable.

7. **Width math:** the track must be wider than 200% of the visible container so there's always content to scroll into view. `width: max-content` + duplicated items handles this automatically.

See `recipes/animations.md` § Marquee for the canonical implementation.

### ❌ `<Loader2 className="animate-spin" />` for every loading state
**Why it's slop:** The most-cited AI tell. Recognized instantly by any designer.
**Fix:**
- Initial page/section load → skeleton screens (gray placeholder shapes matching content layout)
- Button submit → button text fades to ellipsis "..." or progress bar inside button
- Optimistic update → show the result immediately, mark with subtle pulse if not yet confirmed
- Long process → branded progress bar with stepped milestones

### ❌ "MOST POPULAR" pricing banner across the middle card
**Why it's slop:** Used by literally every Bootstrap pricing template since 2014.
**Fix:** Subtle indicator: small pill "Currently Popular" with a green dot, OR a slightly different background tint on the recommended card.

### ❌ Feature lists with checkmark icons (`<Check />` per row)
**Why it's slop:** The default shadcn/ui pricing template look.
**Fix:** Thin horizontal divider lines between features. Or no separators, just spacing.

### ❌ Modal accordions for FAQ (`<Accordion>` from shadcn defaults)
**Why it's slop:** Boxy borders, default chevron rotation, no design opinion.
**Fix:** Thin pill rows with hover hint, expanding inline. See `recipes/faq-pillrows.md`.

### ❌ Borders as the primary visual divider
**Why it's slop:** A 1px border around every card is the laziest divider. Refactoring UI rule: borders are the LAST resort. The default LLM move is `border border-gray-200` everywhere.
**Fix:** Banish borders. Use SHADOW (the two-part stack from `tokens.md` § ATMOSPHERE), SPACE (extra gap between groups), or BG CONTRAST (slight bg-color shift between sections) instead. Borders allowed only for: input fields, accent strips on active tabs, hairline dividers between table rows.

### ❌ Buttons with `rounded-md` and a chevron `<ArrowRight />`
**Why it's slop:** The most basic shadcn button pattern.
**Fix:** `rounded-full` pill buttons. Arrow optional, but if used, it should be a small circle-arrow that animates on hover (translates a few px right).

---

## MOTION ANTI-PATTERNS

### ❌ Animating `top`, `left`, `width`, `height` (Hardware-acceleration rule)
**Why it's slop:** Triggers layout reflow on every frame. ~5fps on mobile.
**Fix:** Animate ONLY `transform` and `opacity`. Use `transform: translate()` instead of `top:`, `transform: scale()` instead of `width:`. The compositor handles transform/opacity on the GPU; layout properties force the main thread to recalculate every frame.

### ❌ `transition: all 0.3s ease`
**Why it's slop:** Vague generic CSS transition fights with Framer Motion and produces janky results.
**Fix:** Use Framer Motion `layout` + spring preset. Or specify explicit properties: `transition-colors duration-200`.

### ❌ Hover: `hover:scale-105` with no easing
**Why it's slop:** Snaps instantly, feels cheap. Default Tailwind hover.
**Fix:** Wrap in `<motion.div whileHover={{ scale: 1.02 }} transition={SPRING_SNAPPY}>` — softer, springy.

### ❌ `cubic-bezier(0.68, -0.55, 0.265, 1.55)` (back-out / overshoot)
**Why it's slop:** The "bouncy" easing that designers laughed at in 2017.
**Fix:** Springs (stiffness 200-400, damping 20-30) or `ease-out-quint` `[0.16, 1, 0.3, 1]`.

### ❌ `animate-bounce` or `animate-pulse` for important UI
**Why it's slop:** Tailwind defaults, both look cheap. Pulse for skeletons is OK; pulse for "look at this!" is not.
**Fix:** Use entrance animations (fade + 12px slide-up via stagger). Use shared-element morph for state changes.

### ❌ Mounting/unmounting cards with `{condition && <Card />}`
**Why it's slop:** Hard cuts feel broken. Premium = morph one container.
**Fix:** Wrap in `<AnimatePresence mode="popLayout">` and use `motion.div` with `layout`. Same surface, different content.

### ❌ `useState` for cursor-tracking, magnetic, parallax, continuous-input animations
See `architecture.md` § Continuous-input animations. Rule: use `useMotionValue` + `useTransform`, never `useState`.

---

## CONTENT ANTI-PATTERNS

### ❌ "Empower your team to..."  /  "Unlock the power of..."  /  "Revolutionize..."
**Why it's slop:** ChatGPT marketing voice. Every AI-generated landing page.
**Fix:** Use the actual product's verb. "Move money across borders." "Ship code faster." "Plan your week." Direct, specific, declarative.

### ❌ AI marketing filler words
Banned phrases: "Elevate", "Seamless", "Unleash", "Next-Gen", "Revolutionize", "Game-changer", "Delve", "Tapestry", "In the world of...", "Empower your team", "Unlock the power of".
**Fix:** Use the actual product's verb. "Move money." "Ship code faster." "Plan your week."

### ❌ Hero subtext that explains the headline
**Why it's slop:** "Move money. (Subtext: We help you move money internationally with low fees and great rates.)" Redundant.
**Fix:** Subtext adds NEW info — quantification, audience, distinction. "Move money. (Subtext: 0.5% fee, 60+ currencies, settled in 24h.)"

### ❌ Feature card titles like "Powerful Features", "Built for Speed", "Designed for You"
**Why it's slop:** Empty marketing words.
**Fix:** Concrete promises. "Live exchange rates", "Scheduled transfers", "Bank-level security" — or specific to the product.

### ❌ Pricing tiers named "Basic / Pro / Enterprise"
**Why it's slop:** Default. Lazy.
**Fix:** Name tiers based on the product or audience. "Solo / Team / Studio" for design tools. "Starter / Growth / Scale" for SaaS.

### ❌ Generic placeholder names ("John Doe", "Sarah Chan", "Jack Su")
**Why it's slop:** Reads as a Lorem-Ipsum dump. Instantly screams template.
**Fix:** Use creative, realistic, diverse names. "Maya Okafor", "Ezra Singh", "Lucia Marchetti", "Tomas Brandt".

### ❌ Generic avatars (SVG-egg, Lucide user icon, gradient initials)
**Why it's slop:** "JD" in a colored circle is the laziest possible avatar.
**Fix:** Use believable photo placeholders via `https://picsum.photos/seed/{unique-id}/100/100` or styled SVG portraits. NEVER initials.

### ❌ Fake suspiciously-round numbers (99.99%, 50%, 1234567)
**Why it's slop:** Round numbers = invented. Real data has texture.
**Fix:** Use organic data: `47.2%`, `+1 (312) 847-1928`, `$3,481`, `1,247 active users`.

### ❌ Startup slop names ("Acme", "Nexus", "SmartFlow", "Flowbit", "NovaCore")
**Why it's slop:** Pattern-matched template fillers.
**Fix:** Invent contextual brand names that sound real. Two-syllable favored. Avoid `-ly`, `-fy`, `-hub` suffixes.

### ❌ Unsplash placeholder URLs
**Why it's slop:** Often broken (slug changes, rate limits, 404s in a week).
**Fix:** Use `https://picsum.photos/seed/{unique-string}/{width}/{height}` (deterministic per-seed, reliable).

---

## DECORATION ANTI-PATTERNS

### ❌ Plain glassmorphism (`backdrop-filter: blur()` semi-transparent panels)
**Why it's slop:** Peak 2021 AI aesthetic. Reads as "trying too hard" without refinement.
**Fix:** If you need glass, use **Liquid Glass** = backdrop-blur + 1px inner border + inner shadow. See `tokens.md` Liquid Glass spec. Use ONLY for sticky nav and floating overlays — never for cards/sections.

### ❌ Random `<div>` blobs in pastel gradients as background "decoration"
**Why it's slop:** The "Apple keynote rip-off" gradient blob. Used by every fintech bootstrap site.
**Fix:** Use bundled WebP backgrounds in `assets/backgrounds/` (see `recipes/backgrounds-catalog.md`). Or one single contained accent — like a small gradient under a product mockup, not floating in negative space.

### ❌ Custom cursor (giant circle that scales on hover)
**Why it's slop:** Awwwards-2020 trend that aged poorly. Hurts accessibility.
**Fix:** Default cursor. If you must, do a subtle 4px dot follower with `mix-blend-mode: difference`.

### ❌ Page-load entrance with EVERY element fading in
**Why it's slop:** "I learned Framer Motion yesterday." Fatiguing.
**Fix:** Stagger only the hero (3-5 elements: pill, headline, subtext, CTA, mockup). Below the fold, use scroll-triggered subtle reveals — and sparingly.

---

## RED FLAGS — STOP IF YOU CATCH YOURSELF

```
"Let me just add a quick gradient..."           → STOP. No new gradients.
"I'll center this for balance..."               → STOP. Vary alignment.
"Loader2 is fine for now..."                    → STOP. Skeleton instead.
"This looks empty, let me add..."               → STOP. Empty is the design.
"text-3xl seems readable..."                    → STOP. Bigger.
"I'll just write a hero from scratch..."        → STOP. Open hero recipe.
"hover:scale-110 will feel snappy..."           → STOP. Spring + 1.02.
"The user said make it pop, so neon..."         → STOP. Pop = restraint + one accent.
"Three columns of features should work..."      → STOP. Bento or split.
"h-screen for the hero..."                      → STOP. min-h-[100dvh].
"Just a small emoji in the heading..."          → STOP. No emojis ever.
"useState for the parallax..."                  → STOP. useMotionValue.
"John Doe is fine for the testimonial..."       → STOP. Real names.
```

**All of these mean: re-read the rule, open the recipe, follow the discipline.**

---

## THE TEST

After building, ask: "If I showed this side-by-side with an Awwwards-tier site, would the difference be obvious?"

If yes → restart with the recipes.
If no → you've shipped premium.
