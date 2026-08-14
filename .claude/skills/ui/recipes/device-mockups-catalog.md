# recipes/device-mockups-catalog.md — 17 Bundled Device Mockup PNGs

**Real photoreal device mockups bundled in `assets/mockups/`.** Use these for product mockups in heroes — they look way better than the SVG/CSS device frames in `recipes/mockups.md`.

**License:** All mockups are CC0 (public domain). Sourced from PommePlate (github.com/ephread/PommePlate) and James Jingyi's mockup-device-frames (github.com/jamesjingyi/mockup-device-frames).

---

## When to use real mockups vs CSS frames

| Use real PNG mockup | Use SVG/CSS frame from `mockups.md` |
|---|---|
| You want the absolute highest visual quality | You need a custom screen-size proportion |
| Hero is the primary moment of the page | The frame needs to be theme-aware (light/dark) |
| You don't need the device chrome to be theme-aware | You need to swap content frequently / programmatically |

**Default: use the real PNG.** Falls back to `mockups.md` SVG frames only if you specifically need theme adaptation.

---

## The catalog (17 mockups, 1600px max, transparent WebP)

### iPhone (modern with Dynamic Island)

- `iphone-16-pro-black.webp` — iPhone 16 Pro, Black Titanium
- `iphone-16-pro-white.webp` — iPhone 16 Pro, White Titanium
- `iphone-16-pro-natural.webp` — iPhone 16 Pro, Natural Titanium
- `iphone-16-black.webp` — iPhone 16 (standard), Black
- `iphone-16-white.webp` — iPhone 16 (standard), White
- `iphone-15-pro-max-black.webp` — iPhone 15 Pro Max, Black Titanium

**Default pick:** `iphone-16-pro-black.webp` for premium tech / fintech / dev tools. `iphone-16-white.webp` for warm/editorial brands.

### MacBook (open laptop, perspective)

- `macbook-pro-16.webp` — MacBook Pro 16-inch (most premium)
- `macbook-pro-14.webp` — MacBook Pro 14-inch (best for SaaS hero)
- `macbook-air-15.webp` — MacBook Air 15-inch (lifestyle / consumer)
- `macbook-air-13.webp` — MacBook Air 13-inch (compact)

**Default pick:** `macbook-pro-14.webp` for SaaS dashboards. `macbook-pro-16.webp` for cinematic / agency.

### iPad

- `ipad-air-13-landscape-space-gray.webp` — iPad Air 13" landscape (best for hero showing a wide app)
- `ipad-air-11-portrait-space-gray.webp` — iPad Air 11" portrait

### Mac Desktop / Imac

- `imac-24-silver.webp` — iMac M3 24"

### Apple Watch

- `apple-watch-44mm.webp` — Apple Watch Series 4+ (44mm)

### Android (alt to iPhone)

- `pixel-9-pro-obsidian.webp` — Google Pixel 9 Pro
- `pixel-9-pro-xl-obsidian.webp` — Google Pixel 9 Pro XL

### Windows Laptop

- `dell-xps-14-graphite.webp` — Dell XPS 14 (2024)

---

## How to use

The mockup is a transparent PNG with the device chrome rendered. Your job is to position your screenshot/content INSIDE the screen area.

### Approach 1 — Layered absolute positioning (most flexible)

```tsx
<div className="relative inline-block">
  {/* Device chrome (transparent except the device) */}
  <img
    src="/mockups/macbook-pro-14.webp"
    alt=""
    aria-hidden
    className="block w-full h-auto select-none pointer-events-none"
  />
  {/* Screen content positioned over the screen area */}
  <div
    className="absolute"
    style={{
      // These percentages are eyeballed for MacBook Pro 14 — measure if precise placement matters
      top: "5.5%",
      left: "12%",
      width: "76%",
      height: "82%",
    }}
  >
    <img src="/dashboard-screenshot.png" alt="Dashboard" className="w-full h-full object-cover rounded-md" />
  </div>
</div>
```

### Approach 2 — CSS mask (composes content INTO the screen rectangle)

For iPhone where the screen has rounded corners that match the chrome's rounded corners, use a mask:

```tsx
<div className="relative inline-block">
  <img src="/mockups/iphone-16-pro-black.webp" alt="" aria-hidden className="block w-auto h-[600px]" />
  <div
    className="absolute inset-0 m-auto"
    style={{
      top: "3%",
      left: "5%",
      width: "90%",
      height: "94%",
      borderRadius: "8%",
      overflow: "hidden",
    }}
  >
    {/* Your app screen content here */}
    <YourAppScreen />
  </div>
</div>
```

### Approach 3 — Pure showcase (no inner content)

Sometimes the device alone is the visual — paired with text on the other side of the hero. Just drop the mockup as a hero image:

```tsx
<img src="/mockups/macbook-pro-14.webp" alt="MacBook Pro" className="w-full max-w-2xl mx-auto" />
```

---

## Screen-area coordinates (approximate, for content placement)

Each device's screen sits at a different percentage offset within the bounding box. **For pixel-precise placement, measure with browser devtools** — these are starting estimates:

| Device | Top | Left | Width | Height | Notes |
|---|---|---|---|---|---|
| iPhone 16 Pro / 15 Pro Max | 3% | 5% | 90% | 94% | Rounded screen — use border-radius 8% |
| iPhone 16 (standard) | 3% | 5% | 90% | 94% | Rounded screen — use border-radius 8% |
| MacBook Pro 14 / 16 | 5.5% | 12% | 76% | 82% | Rectangular screen, slight rounding |
| MacBook Air 13 / 15 | 6% | 11.5% | 77% | 80% | Same as Pro |
| iPad Air landscape | 7% | 7% | 86% | 86% | Rounded corners ~3% |
| iPad Air portrait | 5% | 7% | 86% | 90% | |
| iMac 24 | 6% | 6% | 88% | 75% | Bottom is stand — content stops above |
| Apple Watch 44mm | 14% | 17% | 66% | 72% | Strong rounded corners ~25% |
| Pixel 9 Pro | 3% | 5% | 90% | 94% | |
| Dell XPS 14 | 6% | 12% | 76% | 80% | |

---

## Sizing rules (responsive)

These mockups are **decoration** — they should NEVER be larger than ~60% of the hero column on desktop, ~100% on mobile.

```tsx
{/* Hero with right-side product mockup */}
<div className="grid lg:grid-cols-2 gap-12 items-center">
  <div>{/* headline + CTAs */}</div>
  <div>
    <img
      src="/mockups/macbook-pro-14.webp"
      alt=""
      className="w-full max-w-xl mx-auto" // max ~576px
    />
  </div>
</div>
```

For phone mockups (taller aspect), don't let them dominate vertically:

```tsx
<img
  src="/mockups/iphone-16-pro-black.webp"
  alt=""
  className="h-[500px] md:h-[640px] w-auto mx-auto"
/>
```

---

## What NOT to do

- ❌ **Don't apply CSS filters** (hue-rotate, sepia) to recolor the device chrome — pick the right color variant from the catalog
- ❌ **Don't stretch the aspect ratio** — `object-cover` to a wrong AR will distort the device
- ❌ **Don't use multiple device mockups in the same hero** — pick ONE primary device. If you need multiple, use the combo shots from `mockups.md` device-stack patterns instead.
- ❌ **Don't put a mockup inside another mockup** — no MacBook with an iPhone screenshot inside, etc.
- ❌ **Don't add fake reflections, scratches, or "studio lighting"** to the chrome — the mockups are already cleanly rendered.
- ❌ **Don't put a screen-content image with hard rectangular corners over a device that has rounded screen corners** — apply `border-radius` to your content layer to match.

---

## Cross-references

- `recipes/mockups.md` — for SVG/CSS device frames as fallback (theme-aware, programmatic)
- `recipes/hero-saas.md` — hero composition (drop a mockup on the right)
- `recipes/hero-fintech.md` — uses the live converter widget instead of mockups
- `anti-slop.md` § COMPONENT — bans inline-fake-dashboards (use these instead)
- `tokens.md` § ATMOSPHERE & SURFACE DETAIL — pair mockup with color-matched glow underneath
