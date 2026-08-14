# visual-thinking.md — How to think before you build

**Read this between Step 1 (IDENTIFY) and Step 2 (READ recipes).** Before writing a single `<div>`, you MUST silently answer the five phases of questions below. Skipping this step produces "good attempt" output. Answering these produces output that competes with Awwwards-tier sites.

The owner's tested feedback: every output that lacked these answers shipped with floating decorations on top of headlines, light sources from three directions at once, missing depth layers, and no "expensive moment". Forcing the answer cycle is the difference.

---

## THE FIVE-PHASE QUESTION GATE

Answer every question silently in your `<thinking>` block before writing JSX. If you cannot answer one, the composition is not yet designed — STOP and decide.

### Phase 1 — Composition

1. Scan pattern — F (text-heavy), Z (sparse marketing), center-out (product/portfolio), or layered-Z (long-scroll narrative)?
2. 3-step eye flow path — name the primary focal, the secondary anchor, the tertiary CTA. Trace it with a finger; if you can't, the layout is flat.
3. What is anchoring the BOTTOM of the composition — footer band, horizon line, heavy element, baseline strip? (Without bottom weight, every comp floats and feels unfinished.)
4. Which quadrant carries the negative-space weight — top-left, top-right, bottom-left, bottom-right? Negative space only counts when it's *claimed*, not residual.
5. The asymmetric-tension pair — what's the heavy side, and what's the small high-chroma accent balancing it on the other side?
6. Are focal points on third-lines or golden-ratio (62/38) intersections, or am I defaulting to dead-center?
7. Is there a diagonal connecting at least two focal points? Pure horizontal/vertical = static.

### Phase 2 — Light

1. ONE light source — where? Default top-left at ~45° elevation (sun-over-shoulder convention). Commit to one and never mix.
2. Do all shadows fall in the same direction? (Inconsistent light direction is the #1 reason AI UI looks fake.)
3. Are shadow COLORS tinted toward the bg hue or toward warm/cool of the scene — never pure `rgba(0,0,0,...)` black?
4. Stacked shadow layers — tight contact (`0 1px 2px`) AND ambient (`0 20-40px wide-spread`)? Single-layer shadows look CGI-fake.
5. Which ONE element catches an edge highlight (1px inner-top at white/8%)?
6. Light temperature — warm sunlight (yellow-tinted highlight), cool studio (neutral white), overcast (no highlight), neon (saturated highlight)?
7. Hard or soft shadows? Hard = small/close light (editorial poster). Soft = large/distant light (premium product).

### Phase 3 — Depth

1. Foreground / midground / background — name each layer explicitly before placing elements.
2. Each layer differentiated by ≥2 cues (blur, scale, shadow stack, opacity, chroma desaturation, lightness shift)?
3. Atmospheric perspective — distant elements lose chroma, shift toward background lightness, lower contrast?
4. Overlap on the focal point — something foreground covers a corner of midground by 8-16px? (Strongest depth cue available.)
5. Lighting consistency — all layers lit by the same source, shadows agreeing in direction?
6. Does the depth hierarchy match the importance hierarchy? (Most important = most foreground.)

### Phase 4 — Materiality

1. Name the material per surface — paper, glass, brushed metal, polished metal, cloth, plastic, ceramic, vellum, cardstock, chrome.
2. Where does the brand sit on the matte ↔ satin ↔ gloss ↔ chrome spectrum? Commit to a position.
3. Is there ONE tactile detail that earns the material claim — paper grain, glass refraction edge, brushed metal anisotropy, leather stitching, ceramic micro-cracking?
4. Are surface materials consistent within a single element? (Don't mix glass and matte plastic on one card.)
5. Does each material have the correct shadow softness, highlight sharpness, and chroma to read as that material?

### Phase 5 — Polish

1. What's the ONE "expensive moment" — the single detail that telegraphs custom-build vs template? (See list below.)
2. Is everything OPTICALLY aligned, not mathematically? (Icons need 1-2px fudge to visually center; triangles need ~10% horizontal offset; capital letters sit differently than lowercase.)
3. GREYSCALE TEST: convert to greyscale mentally. Does the focal still dominate via VALUE alone? If color is the only thing carrying hierarchy, the design is fragile.
4. MOBILE-CROP TEST: cropped to 375px wide, does focal robustness survive? Or does it become bland?
5. Have I removed every element I could not justify in one sentence?
6. Are the type tracking, line-height, and optical sizing intentional at every scale — or am I shipping defaults?

---

## THE BANNED-DEFAULT BLACKLIST (from GStack)

If the output contains any of these, it is slop. Hard fail — do not ship.

1. **Purple/violet/indigo gradient backgrounds** — the AI-defaults-here color.
2. **Blue→purple color schemes** — the cookie-cutter hackathon palette.
3. **3-column feature grid with icon-in-circle + bold title + 2-line desc** — the cardinal sin. The single most-recognized AI tell.
4. **Emoji used as design elements** — slop. Emojis are content, never decoration.
5. **Cookie-cutter section rhythm** — hero → 3-features → testimonials → pricing → CTA. The literal Vercel Geist template.
6. **Default font stacks (Inter regular, Roboto, Arial, system) without intent** — using a font because it's free, not because it serves the work.
7. **Decorative blobs / SVG dividers as filler** — used to hide that there's no content.
8. **Glassmorphism + neon glow + blurred orbs combo** — peak 2021 AI aesthetic.
9. **Monospace everything** — the hackathon look. Mono is for code/data/labels, not body.
10. **Generic SaaS card grid as first impression** — three identical rounded-2xl shadcn cards on a white bg.
11. **Beautiful imagery with weak brand presence** — the photo overpowers the brand and the page becomes a stock-photo gallery.

---

## THINKING TEMPLATE

Before code, output a SILENT design plan in your scratchpad / `<thinking>` block, NOT visible to the user, covering:

```
Page type: ___
Vibe (from Step 1.5 ROLL THE DICE): ___
Composition: scan pattern ___, 3-step eye path ___ → ___ → ___, anchor at bottom ___, asymmetric tension ___, negative space in ___ quadrant
Light: source from ___ at ___° elevation, temperature ___, edge highlight on ___
Depth: foreground = ___, midground = ___, background = ___ (each differentiated by ___)
Materiality: surfaces = ___ material, brand sits at ___ on matte↔chrome spectrum, tactile detail = ___
Expensive moment: ___
Greyscale dominance: focal element survives = YES/NO
Mobile robustness: focal at 375px = YES/NO
Banned-defaults check: clean YES/NO
```

If any answer is "I don't know" — STOP and decide. Don't ship without the answer.

---

## THE TWO-PART SHADOW LAW

Every elevated card needs a stacked shadow. NEVER a single soft drop.

```css
/* Two-part shadow — tight contact + ambient halo */
box-shadow:
  0 1px 2px 0 rgb(0 0 0 / 0.06),       /* contact: anchors element to surface */
  0 20px 40px -12px rgb(0 0 0 / 0.10); /* ambient: ground shadow with directional offset */
```

Contact shadow proves the element is sitting on something. Ambient shadow proves it has volume. Without both, it's a flat rectangle floating in space.

**Dark mode**: tint shadows toward the background hue, never pure black. A pure-black shadow on a dark navy bg lands flat and reads CGI-fake.

```css
/* Dark mode — shadow tinted toward bg hue */
box-shadow:
  0 1px 2px 0 oklch(0.06 0.02 250 / 0.5),
  0 20px 40px -12px oklch(0.06 0.02 250 / 0.4);
```

---

## THE KEY-LIGHT INSET HIGHLIGHT

The single most-cited "premium" trick for raised surfaces. A 1px inset-top highlight at white/8% — invisible individually, transformative cumulatively.

```css
box-shadow:
  inset 0 1px 0 rgb(255 255 255 / 0.08),  /* key light catching top edge */
  0 1px 2px 0 rgb(0 0 0 / 0.06),
  0 20px 40px -12px rgb(0 0 0 / 0.10);
```

Used by Linear, Vercel, Resend on every dark card. The "MacOS Big Sur key light." Always paired with a top-left light source so the highlight reads as a real caught edge.

---

## ATMOSPHERIC GRAIN OVERLAY

SVG turbulence grain at 4-8% opacity, fixed and pointer-events-none, with `mix-blend-mode: overlay` — site-wide subtle texture. The single biggest "expensive" tell.

```css
.grain-overlay::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 100;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' /></filter><rect width='100%25' height='100%25' filter='url(%23n)' opacity='0.06'/></svg>");
  mix-blend-mode: overlay;
}
```

Apply once on `<body>` or root layout. Test at 4%, 6%, 8% — pick the lowest opacity where the grain just barely registers.

---

## ATMOSPHERIC VIGNETTE + WARM-COOL SPLIT

### Vignette

Subtle radial darkening at corners — focuses the eye, mimics camera lens fall-off.

```css
.bg-vignette {
  background-image: radial-gradient(ellipse at center, transparent 40%, rgb(0 0 0 / 0.4) 100%);
}
```

Layered ABOVE hero content with `pointer-events: none`. Use sparingly — heroes only, never on body sections.

### Warm-cool split

Cross-page subliminal depth — hero background goes from cool bottom-left to warm top-right (or vice versa). Reads as physical 3D space without anyone naming why.

```css
.bg-split-gradient {
  background-image: linear-gradient(
    to top right,
    oklch(0.16 0.02 250) 0%,    /* cool side */
    oklch(0.18 0.02 30) 100%    /* warm side */
  );
}
```

Premium fintech, EV brands, dark luxury all use this. Subtle is the point — if anyone notices it directly, it's too strong.

---

## THE EXPENSIVE MOMENT — what counts

Every premium build has ONE detail that telegraphs "custom-built" vs "template". You commit to one per build. Without this, the page reads like a competent shadcn assembly.

Counts as an expensive moment:

- A single rendered 3D object floating in the hero
- An animated SVG that draws on scroll
- A custom font character (drop cap, swash letterform, ligature)
- Real live data in the hero (counter pulling from edge function)
- A subtle cursor-tracked mesh gradient
- A single perfect photograph with halftone treatment
- A cinemagraph (one element subtly looping inside an otherwise still composition)
- A custom pointer follower
- A scroll-driven shape morph
- A key-art illustration that contains the brand mark cleverly hidden
- A background that responds to time of day
- An audio cue on a key interaction
- A sticky-scroll narrative section
- A perfectly composed full-bleed quote
- A repeating ASCII signature in the footer

If you can't name yours from this list (or invent an equivalent) — STOP. The page is not yet premium.

---

## OPTICAL ALIGNMENT NOTES

The eye lies. Math doesn't match perception. Trust the eye, not the box.

- Icons inside circles need a 1-2px nudge to look centered
- Triangles need ~10% horizontal offset (visual mass not at geometric center)
- Quote marks should hang outside the text column (`margin-left: -0.5em`)
- Headlines with descenders (g, p, y, j) need extra bottom padding to look balanced
- Numbers right-align tabular; words left-align
- Border-radius — outer container radius minus inner padding equals inner element radius (concentric)
- Round shapes need to extend ~2-4% past square baselines to look optically aligned
- Capital letters sit differently than lowercase; mixed-case buttons need slight bottom padding bump

---

## SQUINT TEST + GREYSCALE TEST + MOBILE-CROP TEST

Three pre-flight tests every build runs in Step 4 (also encoded in `review.md` checks 18-20):

**Squint test** — apply 5-10px blur mentally (or via DevTools `filter: blur(8px)`). Does the focal element still dominate? If everything is mush, hierarchy fails. Re-check Rule 2 (typography is the design) and Phase 1 above.

**Greyscale test** — mentally desaturate the page. Does visual hierarchy survive on VALUE contrast alone? Premium designs work in greyscale. If color is the only thing carrying hierarchy, the design is fragile. Add value contrast: darker bg behind important sections, lighter cards on darker bg, etc.

**Mobile-crop test** — crop the layout to 375px wide. Does focal robustness survive? The primary focal must still hit. If the design becomes bland at mobile width, the focal moment was relying on viewport scale — fix that before shipping.

---

## CROSS-REFERENCES

- See `tokens.md` § ATMOSPHERE & SURFACE DETAIL for the SHADOW STACKS, KEY-LIGHT INSET, GRAIN OVERLAY, VIGNETTE tokens
- See `anti-slop.md` § THE GSTACK BANNED-DEFAULT BLACKLIST (mirrored from above)
- See `recipes/animations.md` for spring/motion presets
- See `review.md` § STEP B checks 18-20 for the three pre-flight tests (squint / greyscale / mobile-crop) and the expensive-moment naming requirement
- See `SKILL.md` § Step 1.6 — DESIGN PLAN PREAMBLE for where this file fits in the procedure
