# recipes/backgrounds-catalog.md — 26 Bundled WebP Backgrounds

Stored at `assets/backgrounds/AI_Bg_*.webp`. Each is 1920px wide, optimized to ~50-150KB.

**Use these instead of CSS gradients.** They look hand-designed because they were AI-curated from a premium pack. Adding a real image background to a hero section instantly removes the "generic AI" feeling.

---

## Quick Pick by Mood

### Want premium / cinematic / luxury?
→ `AI_Bg_031.webp` (red-orange sunset between monoliths) — for Electric.-style EV / dark luxury
→ `AI_Bg_037.webp` (Earth from orbit, blue + amber lights) — for AI / global SaaS / aerospace
→ `AI_Bg_041.webp` (red-orange light leak on black) — for premium dark mode / film tech

### Want abstract / soft / approachable?
→ `AI_Bg_044.webp` (smooth orange→navy→pink gradient) — for SaaS / product / startup
→ `AI_Bg_038.webp` (cyan/coral lenticular gradient) — for creative / Gen-Z / music
→ `AI_Bg_017.webp` (sage green organic wave) — for wellness / sustainability / green tech

### Want dreamy / pastel / wellness?
→ `AI_Bg_05.webp` (baby blue + lavender + pink clouds) — for wellness / baby / beauty
→ `AI_Bg_011.webp` (purple→blue→pink soft radial) — for SaaS friendly tone

### Want bold + corporate / trustworthy?
→ `AI_Bg_015.webp` (royal blue with light rays) — for cybersecurity / enterprise / cloud
→ `AI_Bg_06.webp` (wind turbine in blue sky) — for cleantech / ESG / sustainability

### Want fantasy / magical / NFT-adjacent?
→ `AI_Bg_019.webp` (anime waterfall) — for gaming / VTuber / fantasy
→ `AI_Bg_048.webp` (rainbow + redwoods + nebula) — for whimsical / children's / AI art
→ `AI_Bg_049.webp` (rainbow meadow) — for hopeful / wellness / lifestyle
→ `AI_Bg_043.webp` (golden mountain peaks with sparkles) — for fintech "wealth" / aspiration

### Want pastoral / golden hour / human?
→ `AI_Bg_050.webp` (stone arch at sunset) — for travel / wedding / lifestyle
→ `AI_Bg_054.webp` (alpine valley with cottage) — for travel / luxury / retreat

### Want bright daytime / cheerful?
→ `AI_Bg_051.webp` / `AI_Bg_053.webp` (cumulus over green hills) — for organic / outdoor / kids

### Want story-driven / human / cinematic?
→ `AI_Bg_028.webp` (warm amber portrait on subway) — for fashion / culture / urban (subject-heavy, requires overlay)
→ `AI_Bg_029.webp` (astronaut + eclipse) — for sci-fi / aerospace / VR (story-driven)

### Want minimal almost-blank?
→ `AI_Bg_08.webp` (ice blue + soft pink wash) — when the UI is the hero, bg should disappear
→ `AI_Bg_010.webp` (mint + cyan + lilac iridescent) — for Web3 / fintech / creative tools
→ `AI_Bg_01.webp` (topographic blue island) — for data / mapping / scientific
→ `AI_Bg_09.webp` (silk ribbon flow) — for premium SaaS / AI / corporate

---

## Usage in JSX

### Simple: full-bleed background

```tsx
<section className="relative min-h-[90vh] overflow-hidden">
  <img
    src="/backgrounds/AI_Bg_044.webp"
    alt=""
    aria-hidden
    className="absolute inset-0 w-full h-full object-cover -z-10"
  />
  {/* hero content goes here */}
</section>
```

### With overlay scrim for text readability

For backgrounds with detail (anything photo-realistic, fantasy, or cinematic), add a scrim:

```tsx
<section className="relative min-h-[90vh] overflow-hidden">
  <img src="/backgrounds/AI_Bg_048.webp" alt="" aria-hidden className="absolute inset-0 w-full h-full object-cover -z-10" />

  {/* Scrim — darker at top where text sits, fades to transparent */}
  <div
    className="absolute inset-0 -z-10"
    style={{
      background: "linear-gradient(to bottom, rgb(0 0 0 / 0.45) 0%, rgb(0 0 0 / 0.15) 40%, transparent 70%)",
    }}
    aria-hidden
  />

  {/* Hero content with white text */}
</section>
```

### Frosted glass card on top of bright background

For bright daylight backgrounds (051, 053) or anything where text won't have contrast:

```tsx
<div className="rounded-2xl bg-white/70 backdrop-blur-xl border border-white/40 p-8">
  <h1>Headline that needs contrast</h1>
</div>
```

---

## Text overlay rules per category

| Background type | Text color | Treatment |
|---|---|---|
| Light gradient (08, 011, 017) | Dark (`var(--text)`) | None needed |
| Medium gradient (05, 010, 044) | Dark preferred | Optional `text-shadow: 0 1px 2px rgb(0 0 0 / 0.05)` |
| Bold blue (015) | White only | `text-shadow: 0 2px 8px rgb(0 0 0 / 0.3)` |
| Cloudscape (014, 05, 06) | White top OR frosted card | Frosted card if hero needs density |
| Photographic (028, 029, 048, 049) | White only | Gradient scrim mandatory |
| Dark cinematic (031, 037, 041) | White / off-white | NO scrim — image is dark enough |
| Pastoral daytime (051, 052, 053) | Dark | Frosted card recommended |

---

## Performance

All backgrounds are WebP, optimized to under 200KB each. Use `loading="eager"` and `fetchpriority="high"` for hero images:

```tsx
<img
  src="/backgrounds/AI_Bg_044.webp"
  loading="eager"
  fetchPriority="high"
  alt=""
/>
```

For mobile, consider a 50% quality lower-resolution variant if you have many backgrounds.

---

## What NOT to do

- Don't use these as decorative elements scattered behind cards (they're full-bleed backgrounds for hero sections only)
- Don't apply CSS filters (`filter: hue-rotate(...)`) to recolor them — pick the right one
- Don't stretch them with `object-position` to "fill" — they're designed for normal `object-cover`
- Don't combine multiple backgrounds in one section
- Don't use them in dashboards or mobile screens (overkill — keep those clean)

---

## CSS-only background recipes (when WebP overkill)

Sometimes you don't need a 120kb photographic background — you need a clean, hand-feeling texture. Two CSS-only patterns that read as "designed-without-AI."

### Stone Dotted Grid

Warm-stone background with a tiny dotted overlay. Pairs with editorial / studio / "calm premium" briefs (Rivo / Kora aesthetic).

```tsx
<section
  className="relative min-h-[90dvh]"
  style={{
    backgroundColor: "oklch(94% 0.005 70)",
    backgroundImage:
      "radial-gradient(circle, oklch(70% 0.005 70) 1px, transparent 1px)",
    backgroundSize: "24px 24px",
  }}
>
  {/* hero content */}
</section>
```

Rules:
- Dot opacity stays under 0.10 — any higher and it screams "graph paper"
- Dot size 1px, grid spacing 24px — never larger
- Never combine with another bg image
- The dotted grid is ALL OVER the page (footer included), not just the hero

### Pastel Gradient Stripes

Alternating solid-pastel + gradient-pastel horizontal bands in a single hue family. Premium consumer / soft tech.

```tsx
<section
  className="relative min-h-[90dvh]"
  style={{
    backgroundImage: `
      linear-gradient(180deg,
        oklch(92% 0.04 290) 0%,
        oklch(92% 0.04 290) 14%,
        oklch(98% 0.01 290) 14%,
        oklch(92% 0.04 290) 28%,
        oklch(92% 0.04 290) 42%,
        oklch(98% 0.01 290) 42%,
        oklch(92% 0.04 290) 56%,
        oklch(92% 0.04 290) 70%,
        oklch(98% 0.01 290) 70%,
        oklch(92% 0.04 290) 84%,
        oklch(92% 0.04 290) 100%
      )
    `,
  }}
>
  {/* hero content */}
</section>
```

Hue swap (replace the two `290` values):
- Lavender: `290`
- Sage: `150`
- Peach: `40`
- Sky: `230`
- Butter: `90`

Rules:
- ONE hue family per page. Never mix hues across stripes (rainbow stripes = template energy).
- Stripe heights are NOT equal — vary 14% / 14% / 14% (solid) and 14% / 14% (gradient) for visual rhythm. Equal stripes look like a barcode.
- Lightness gap stays small (`92%` vs `98%`). Larger gap reads as "loading skeleton."
- Headlines need `text-shadow: 0 1px 2px rgb(255 255 255 / 0.4)` if they cross a stripe boundary
- Never combine with a photo, dotted-grid, or another bg image
- Marketing/hero only — never dashboards or mobile screens

---

## File listing

```
AI_Bg_01.webp   topographic blue island       (data viz)
AI_Bg_05.webp   pastel sky / clouds           (wellness)
AI_Bg_06.webp   wind turbine + sky            (cleantech)
AI_Bg_08.webp   ultra-minimal ice blue        (UI hero, bg disappears)
AI_Bg_09.webp   silk ribbon flow              (premium SaaS)
AI_Bg_010.webp  holographic iridescent        (Web3 / Gen-Z)
AI_Bg_011.webp  purple-blue-pink soft radial  (friendly SaaS)
AI_Bg_014.webp  illustrated cloudscape         (creative agency)
AI_Bg_015.webp  bold blue + light rays        (corporate)
AI_Bg_017.webp  sage green wave               (wellness)
AI_Bg_019.webp  anime waterfall               (gaming/fantasy)
AI_Bg_028.webp  warm amber portrait subway    (urban/fashion)
AI_Bg_029.webp  astronaut + eclipse           (sci-fi)
AI_Bg_031.webp  red sunset between monoliths  (cinematic dark)
AI_Bg_037.webp  Earth from orbit              (global SaaS / aerospace)
AI_Bg_038.webp  cyan/coral lenticular         (creative / Gen-Z)
AI_Bg_041.webp  red light leak on black       (premium dark)
AI_Bg_043.webp  golden mountain sparkles      (fintech / aspiration)
AI_Bg_044.webp  smooth orange-navy-pink       (modern SaaS — DEFAULT PICK)
AI_Bg_048.webp  rainbow redwoods + nebula     (fantasy whimsy)
AI_Bg_049.webp  rainbow meadow                (lifestyle)
AI_Bg_050.webp  stone arch at sunset          (travel / wedding)
AI_Bg_051.webp  cumulus + hilltop             (organic / kids)
AI_Bg_052.webp  arch in daylight              (travel / heritage)
AI_Bg_053.webp  bright meadow + flowers       (outdoor / cheerful)
AI_Bg_054.webp  alpine cottage golden hour    (luxury travel / retreat)
```
