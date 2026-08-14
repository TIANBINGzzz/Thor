# review.md — Pre-Ship Checklist

**Run this in Step 4 of the procedure. Every item must pass before SHIP.**

If Playwright is available (`mcp__playwright__browser_*` tools), use them. Otherwise, manually verify by reading the code.

---

## STEP A — Take a screenshot

```
1. Start the dev server (if not already running)
2. Navigate the browser to localhost:{port}
3. Take a full-page screenshot (fullPage: true)
4. Read the screenshot
```

If you cannot reach the running site, **state this explicitly** in the final message: "I could not verify visually — code-only review."

---

## STEP B — The 20 checks

Verify one, mark, then next. **Mobile-test:** use Playwright `browser_resize` at 375px — confirm asymmetric layouts collapse to single-column.

### ✅ 1. Hero copy ≤ 8 words
Count words in `<h1>`. See `SKILL.md` Rule 1.

### ✅ 2. Hero has dual CTA pattern
Filled pill + outlined/text pill, side-by-side. Not solo, not three.

### ✅ 3. Background is NOT pure white or pure black
Body bg must be off-white (`oklch(98% ...)`) or near-black (`oklch(12% ...)`). See `tokens.md` § COLOR PALETTES.

### ✅ 4. Hero uses ONE italic-serif accent word
H1 = bold sans + ONE italic-serif word. See `SKILL.md` Rule 2.

### ✅ 5. Only ONE accent color is used
Scan rendered page. Neutral text + neutral bg + ONE accent. See `SKILL.md` Rule 1.

### ✅ 6. NO empty / sparse sections
Every section has meaningful content density. If hollow, delete it. See `anti-slop.md` § LAYOUT.

### ✅ 7. NO `<Loader2 />` or generic spinner
Verify: `grep -r "Loader2" src/` returns zero. See `anti-slop.md` § COMPONENT.

### ✅ 8. NO purple-to-blue gradient
Verify: `grep -r "from-purple.*to-blue\|from-blue.*to-purple" src/` returns zero.

### ✅ 9. NO "MOST POPULAR" pricing banner
Verify: `grep -r "MOST POPULAR\|POPULAR" src/` returns zero. See `anti-slop.md` § COMPONENT.

### ✅ 10. Section padding ≥ `py-24`
Inspect each `<section>`. `py-32`–`py-40` is the premium target. See `tokens.md` § SPACING.

### ✅ 11. NO elements overflow containers
Use Playwright `browser_resize` at 375 / 768 / 1280. No horizontal scroll, no bleeding content.

### ✅ 12. Motion uses springs, not cubic-bezier
Verify: `grep -r "cubic-bezier\|transition: all" src/` — primary motion must be Framer Motion `layout` + spring. See `tokens.md` § MOTION PRESETS.

### ✅ 13. NO `h-screen` — see `anti-slop.md` § MOBILE
Verify: `grep -r "h-screen" src/` returns zero.

### ✅ 14. NO emojis in product UI — see `anti-slop.md` § TYPOGRAPHY
Scan rendered page for any emoji in headings, buttons, labels, alt text.

### ✅ 15. CONTENT passes "Jane Doe" check — see `anti-slop.md` § CONTENT
Verify: no `John Doe`/`Sarah Chan`, no `Acme`/`Nexus`, no filler verbs (`Elevate`/`Unleash`/`Empower`), no `99.99%`/`50%` round-fakes, no `unsplash.com` URLs.

### ✅ 16. Animation uses transform + opacity only — see `anti-slop.md` § MOBILE

### ✅ 17. NO floating decoration overlaps text/numbers/CTAs (SAFE-ZONE rule)
Every `position: absolute` or `position: fixed` decorative element (sticker, note card, badge, accent shape) must NOT intersect any `<h1>`, `<h2>`, big-number stat, or CTA button bounding box. See `anti-slop.md` § COMPONENT for the full SAFE-ZONE rule.

**Playwright verification:**
```js
const decorations = await page.$$('[data-decoration], section [class*="absolute"]');
const focal = await page.$$('h1, h2, button, [data-stat]');
for (const d of decorations) {
  const dBox = await d.boundingBox();
  if (!dBox) continue;
  for (const f of focal) {
    const fBox = await f.boundingBox();
    if (!fBox) continue;
    const overlap = !(dBox.x + dBox.width < fBox.x ||
                     fBox.x + fBox.width < dBox.x ||
                     dBox.y + dBox.height < fBox.y ||
                     fBox.y + fBox.height < dBox.y);
    if (overlap) flag(`Decoration overlaps focal element`);
  }
}
```
If any overlap is flagged → re-position the decoration into the section's margin safe zone (corners or edge-hugging mid-section), never inside the focal content rectangle.
Verify: `grep -rE "animate.*top|animate.*left|animate.*width|animate.*height" src/` returns zero.

### ✅ 18. SQUINT TEST passes
Apply 5-10px blur mentally (or via DevTools `filter: blur(8px)`). Does the focal element still dominate the composition? If everything is mush, hierarchy fails. Re-check Rule 2 (typography is the design) and `visual-thinking.md` Phase 1.

### ✅ 19. GREYSCALE TEST passes
Mentally desaturate the page. Does the visual hierarchy survive on VALUE contrast alone? If color is the only thing carrying hierarchy, the design is fragile. Premium designs work in greyscale. Add value contrast (darker bg behind important sections, lighter cards on darker bg, etc).

### ✅ 20. ONE expensive moment is named
The page has ONE detail that telegraphs "custom-built" vs "template". State which one in your final message. If you can't name one — re-read `visual-thinking.md` § THE EXPENSIVE MOMENT and add one before shipping.

---

## STEP C — Common failure modes & fixes

### Failure: "It looks fine to me"
You're missing it. Re-read `anti-slop.md` and look for the specific patterns.

### Failure: Sparse sections
Add real content (testimonials, FAQs, integrations) OR delete the section. Never ship a hollow section.

### Failure: Multiple accent colors
Pick ONE and remove others. Status colors (red/green/yellow) are semantic, not accents.

### Failure: Hero >8 words
Move detail to subtext.
Bad: `<h1>Move money internationally with low fees and great rates</h1>` (10 words)
Good: `<h1>Move money. <em>Anywhere.</em></h1>` (3 words)
Subtext: `0.5% fee. 60+ currencies. Settled in 24h.`

### Failure: Centered everything
After hero, ALTERNATE alignment. Centered only for deliberate special moments.

### Failure: Boxy accordion FAQ
Replace with `recipes/faq-pillrows.md`.

### Failure: Mobile broken at 375px
Asymmetric grids missing single-column reset. Add `grid-cols-1 md:grid-cols-2`. Verify with `browser_resize`.

### Failure: Janky scroll / mobile fps tanking
Either animating layout props (use `transform`), backdrop-blur on scroll content (move to sticky/fixed only — see `architecture.md` § Performance), or `useState` for continuous input (switch to `useMotionValue` — see `architecture.md`).

---

## STEP D — Final sign-off

In your final message, list the 20 checks and their status:

```
Review:
✅ Hero copy 5 words
✅ Dual CTA pattern (filled + outlined pill)
✅ Background: oklch(98% 0.005 90) (warm off-white)
✅ Headline: "Build something *beautiful*." (one italic word)
✅ Single accent (terracotta) on CTAs only
✅ All 5 sections have content density
✅ No <Loader2 /> usage
✅ No purple-to-blue gradients
✅ No "MOST POPULAR" banner
✅ Section padding py-32 throughout
✅ Verified at 375/768/1280 — no overflow
✅ All motion via Framer Motion spring presets
✅ min-h-[100dvh] used (no h-screen)
✅ No emojis in any rendered UI
✅ Content passes Jane Doe check
✅ All animations use transform + opacity
✅ No floating decoration overlaps focal content (SAFE-ZONE)
✅ Squint test passes — focal still dominates at 8px blur
✅ Greyscale test passes — hierarchy survives on value alone
✅ Expensive moment named: <state which one detail telegraphs custom-built>
```

If any check fails, **fix it before shipping**. Do not ship with a known violation.
