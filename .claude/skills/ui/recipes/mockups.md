# recipes/mockups.md — Device Frames + Mockup Primitives

**This recipe replaces the #1 worst AI default: fake dashboards built with divs and gradients.** When a hero needs a product mockup, you have FOUR valid options, **in priority order**:

1. **🥇 Bundled real-device PNG** — drop in a photoreal mockup from `assets/mockups/`. **DEFAULT CHOICE — see `recipes/device-mockups-catalog.md`.** 17 photoreal mockups bundled (iPhone 16 Pro, MacBook Pro/Air, iPad Air, Apple Watch, iMac, Pixel 9, Dell XPS) — all CC0 licensed, transparent WebP, ~14KB each.
2. **Real screenshot** of the actual product (`<img src="/dashboard.png" />`). Always best when the user provides one.
3. **Device frame + minimal real content** — wrap a small UI snippet in an SVG frame from this recipe. Use when you need **theme-aware (light/dark) chrome** that real PNGs can't provide.
4. **Decorative abstract** — only if the product is conceptual (no UI yet). Use one of the SVG primitives below, never freeform divs.

**BANNED:** Inventing a fake dashboard inline with `<div>`s + gradients + fake charts + fake stat cards labeled "Sales / Revenue / Activity". This is the laziest, most AI-tell pattern in the playbook. Both the bundled PNGs (option 1) and SVG frames (option 3) are the guardrail.

> **Default decision flow:**
> - Phone mockup needed? → `assets/mockups/iphone-16-pro-black.webp`
> - Laptop mockup needed? → `assets/mockups/macbook-pro-14.webp`
> - Tablet? → `assets/mockups/ipad-air-13-landscape-space-gray.webp`
> - Desktop? → `assets/mockups/imac-24-silver.webp`
> - Watch? → `assets/mockups/apple-watch-44mm.webp`
>
> See `recipes/device-mockups-catalog.md` for the full catalog with screen-area coordinates for placing screenshot content INSIDE each device.

---

## When to use which

| Situation | Use |
|---|---|
| You have a real product screenshot | Plain `<img>` (no frame, unless you want browser chrome) |
| Real screenshot, want browser chrome around it | `<BrowserFrame><img/></BrowserFrame>` |
| No screenshot yet, but the product IS a web app | `<BrowserFrame>` + 2-3 primitives inside |
| No screenshot, product IS a mobile app | `<iPhoneFrame>` + ONE primitive inside (ChatThread, KPIStrip, etc.) |
| No screenshot, product IS a desktop app or dev tool | `<MacBookFrame>` + composition |
| Product is wearable / health | `<AppleWatchFrame>` + KPIStrip |
| Generic "creative tool / design app" | `<TabletFrame>` |
| Conceptual product, no UI to show | `<CardFrame>` with a single primitive, OR no mockup at all (use a hero photo from `assets/backgrounds/`) |

If you can't pick — pick `BrowserFrame`. It's the safest default for SaaS.

---

## Device frames

All frames accept `children` and render the frame chrome around them. They are **static** — no motion, no client component required. They use shadow tokens from `tokens.md`.

### BrowserFrame

A clean Chrome/Safari window. Traffic-light dots top-left, URL pill in the middle, optional toolbar icons right. Inner area inherits a soft inset.

```tsx
type BrowserFrameProps = {
  url?: string;
  theme?: "light" | "dark";
  className?: string;
  children: React.ReactNode;
};

export function BrowserFrame({
  url = "app.linear.app/inbox",
  theme = "light",
  className = "",
  children,
}: BrowserFrameProps) {
  const isDark = theme === "dark";
  return (
    <div
      className={`relative overflow-hidden rounded-[14px] border ${
        isDark ? "border-white/10 bg-[#0e1014]" : "border-black/8 bg-white"
      } ${className}`}
      style={{ boxShadow: "0 40px 80px -20px rgb(0 0 0 / 0.18)" }}
    >
      {/* Title bar */}
      <div
        className={`flex items-center gap-3 px-4 h-10 border-b ${
          isDark ? "border-white/8 bg-[#16191f]" : "border-black/6 bg-[#f6f6f5]"
        }`}
      >
        {/* Traffic lights */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="size-3 rounded-full bg-[#ff5f57]" />
          <span className="size-3 rounded-full bg-[#febc2e]" />
          <span className="size-3 rounded-full bg-[#28c840]" />
        </div>

        {/* URL pill */}
        <div
          className={`flex-1 flex items-center justify-center gap-2 mx-8 h-6 px-3 rounded-md text-[11px] ${
            isDark
              ? "bg-[#0a0c10] text-white/55 border border-white/8"
              : "bg-white text-neutral-500 border border-black/6"
          }`}
          style={{ fontFamily: "'Geist Mono', ui-monospace, monospace" }}
        >
          <svg viewBox="0 0 16 16" className="size-3 opacity-70" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="6" width="10" height="7" rx="1.5" />
            <path d="M5.5 6V4.5a2.5 2.5 0 0 1 5 0V6" />
          </svg>
          {url}
        </div>

        {/* Spacer to balance traffic lights */}
        <div className="w-[54px] shrink-0" />
      </div>

      {/* Content area */}
      <div className={isDark ? "bg-[#0e1014]" : "bg-white"}>{children}</div>
    </div>
  );
}
```

**Variants:**
- `theme="dark"` — for dark dashboards (Linear, Raycast, Vercel)
- `url=""` — passes empty, URL pill renders blank (use when content is the focus)
- Wrap in `<div className="rounded-[14px]" style={{ boxShadow: "0 0 80px -20px var(--accent)" }}>` for the color-matched glow under-mockup look from `hero-saas.md`

### MacBookFrame

Modern MacBook silhouette. Screen + bezel + slim notch + tapered base. Renders only the lid+screen by default; pass `withBase` for the full laptop. Children fill the screen area.

```tsx
type MacBookFrameProps = {
  withBase?: boolean;
  className?: string;
  children: React.ReactNode;
};

export function MacBookFrame({
  withBase = true,
  className = "",
  children,
}: MacBookFrameProps) {
  return (
    <div className={`relative w-full ${className}`}>
      {/* Lid (bezel) */}
      <div
        className="relative rounded-[18px] bg-[#1d1f24] p-[10px]"
        style={{
          boxShadow:
            "0 1px 0 rgba(255,255,255,0.05) inset, 0 40px 80px -20px rgb(0 0 0 / 0.25)",
        }}
      >
        {/* Notch */}
        <div className="absolute top-[10px] left-1/2 -translate-x-1/2 h-[14px] w-[110px] rounded-b-[8px] bg-[#0a0b0e] z-10" />
        {/* Screen */}
        <div
          className="relative overflow-hidden rounded-[10px] bg-white"
          style={{ aspectRatio: "16 / 10" }}
        >
          {children}
        </div>
      </div>

      {withBase && (
        <>
          {/* Hinge gap shadow */}
          <div className="h-[6px] bg-gradient-to-b from-[#1a1c20] to-[#0a0b0e] mx-[2%] rounded-b-[2px]" />
          {/* Base */}
          <div
            className="relative h-[14px] mx-[-2%] rounded-b-[16px] bg-gradient-to-b from-[#cfd2d6] via-[#a8acb1] to-[#7c8086]"
            style={{ boxShadow: "0 30px 40px -20px rgb(0 0 0 / 0.4)" }}
          >
            {/* Notch indent (trackpad slot) */}
            <div className="absolute top-0 left-1/2 -translate-x-1/2 h-[4px] w-[110px] rounded-b-[6px] bg-[#0a0b0e]/50" />
          </div>
        </>
      )}
    </div>
  );
}
```

**Proportions:** screen aspect is 16:10 (real MacBook ratio). Bezel is 10px thick — modern Apple uses thin bezels, not the chunky 90s look.

### iPhoneFrame

Modern iPhone (15 Pro era). Dynamic Island, side button, volume rockers. 19.5:9 screen ratio. Status bar with real-looking time/signal/battery.

```tsx
type IPhoneFrameProps = {
  time?: string;
  className?: string;
  children: React.ReactNode;
};

export function IPhoneFrame({
  time = "9:41",
  className = "",
  children,
}: IPhoneFrameProps) {
  return (
    <div
      className={`relative mx-auto rounded-[44px] bg-[#1a1c20] p-[10px] ${className}`}
      style={{
        width: 320,
        boxShadow:
          "0 1px 0 rgba(255,255,255,0.06) inset, 0 40px 80px -20px rgb(0 0 0 / 0.28)",
      }}
    >
      {/* Side buttons */}
      <span className="absolute -left-[2px] top-[110px] h-[28px] w-[3px] rounded-l-sm bg-[#16181c]" />
      <span className="absolute -left-[2px] top-[160px] h-[52px] w-[3px] rounded-l-sm bg-[#16181c]" />
      <span className="absolute -left-[2px] top-[230px] h-[52px] w-[3px] rounded-l-sm bg-[#16181c]" />
      <span className="absolute -right-[2px] top-[170px] h-[80px] w-[3px] rounded-r-sm bg-[#16181c]" />

      {/* Screen */}
      <div
        className="relative overflow-hidden rounded-[36px] bg-white"
        style={{ aspectRatio: "9 / 19.5" }}
      >
        {/* Dynamic Island */}
        <div className="absolute top-[10px] left-1/2 -translate-x-1/2 z-20 h-[28px] w-[110px] rounded-full bg-black" />

        {/* Status bar */}
        <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-7 pt-[14px] pb-1 text-[13px] font-semibold text-black">
          <span style={{ fontFamily: "'Geist', system-ui, sans-serif" }}>
            {time}
          </span>
          <div className="flex items-center gap-1.5">
            {/* Signal */}
            <svg viewBox="0 0 18 12" className="h-[10px]" fill="currentColor">
              <rect x="0" y="8" width="3" height="4" rx="0.5" />
              <rect x="5" y="5" width="3" height="7" rx="0.5" />
              <rect x="10" y="2" width="3" height="10" rx="0.5" />
              <rect x="15" y="0" width="3" height="12" rx="0.5" opacity="0.35" />
            </svg>
            {/* Wifi */}
            <svg viewBox="0 0 16 12" className="h-[10px]" fill="currentColor">
              <path d="M8 11.5a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z" />
              <path d="M3.6 6.4a6.2 6.2 0 0 1 8.8 0l-1.2 1.2a4.5 4.5 0 0 0-6.4 0L3.6 6.4Z" />
              <path d="M0.8 3.6a10.2 10.2 0 0 1 14.4 0l-1.2 1.2a8.5 8.5 0 0 0-12 0L0.8 3.6Z" />
            </svg>
            {/* Battery */}
            <div className="relative flex items-center">
              <div className="h-[11px] w-[22px] rounded-[3px] border border-black/55 p-[1.5px]">
                <div className="h-full w-[78%] rounded-[1.5px] bg-black" />
              </div>
              <div className="h-[5px] w-[1.5px] rounded-r-sm bg-black/55 ml-[1px]" />
            </div>
          </div>
        </div>

        {/* App content */}
        <div className="absolute inset-0 pt-[44px] pb-[18px]">{children}</div>

        {/* Home indicator */}
        <div className="absolute bottom-[6px] left-1/2 -translate-x-1/2 h-[5px] w-[120px] rounded-full bg-black/85" />
      </div>
    </div>
  );
}
```

### AppleWatchFrame

Series 10 / Ultra silhouette. Rounded rectangle case, digital crown + side button, single screen area.

```tsx
type AppleWatchFrameProps = {
  className?: string;
  children: React.ReactNode;
};

export function AppleWatchFrame({
  className = "",
  children,
}: AppleWatchFrameProps) {
  return (
    <div className={`relative mx-auto ${className}`} style={{ width: 200 }}>
      {/* Top strap stub */}
      <div className="mx-auto h-[40px] w-[120px] rounded-t-[20px] bg-gradient-to-b from-[#3a3d44] to-[#1d1f24]" />

      {/* Case */}
      <div
        className="relative rounded-[44px] bg-[#1a1c20] p-[8px]"
        style={{
          boxShadow:
            "0 1px 0 rgba(255,255,255,0.07) inset, 0 30px 60px -15px rgb(0 0 0 / 0.35)",
        }}
      >
        {/* Digital crown */}
        <span className="absolute -right-[4px] top-[40px] h-[22px] w-[6px] rounded-r-md bg-[#2a2c32]" />
        {/* Side button */}
        <span className="absolute -right-[3px] top-[85px] h-[34px] w-[4px] rounded-r-sm bg-[#2a2c32]" />

        {/* Screen */}
        <div
          className="relative overflow-hidden rounded-[36px] bg-black text-white"
          style={{ aspectRatio: "41 / 50" }}
        >
          {children}
        </div>
      </div>

      {/* Bottom strap stub */}
      <div className="mx-auto h-[40px] w-[120px] rounded-b-[20px] bg-gradient-to-t from-[#3a3d44] to-[#1d1f24]" />
    </div>
  );
}
```

### TabletFrame

iPad-style. Slim uniform bezel, no notch, no home button. 4:3 aspect.

```tsx
type TabletFrameProps = {
  orientation?: "portrait" | "landscape";
  className?: string;
  children: React.ReactNode;
};

export function TabletFrame({
  orientation = "landscape",
  className = "",
  children,
}: TabletFrameProps) {
  const aspect = orientation === "landscape" ? "4 / 3" : "3 / 4";
  return (
    <div
      className={`relative rounded-[26px] bg-[#1a1c20] p-[12px] ${className}`}
      style={{
        boxShadow:
          "0 1px 0 rgba(255,255,255,0.06) inset, 0 40px 70px -20px rgb(0 0 0 / 0.25)",
      }}
    >
      {/* Front camera */}
      <span
        className={`absolute ${
          orientation === "landscape"
            ? "top-1/2 -translate-y-1/2 left-[20px]"
            : "left-1/2 -translate-x-1/2 top-[20px]"
        } size-[5px] rounded-full bg-[#0a0b0e] z-10`}
      />
      <div
        className="relative overflow-hidden rounded-[16px] bg-white"
        style={{ aspectRatio: aspect }}
      >
        {children}
      </div>
    </div>
  );
}
```

### CardFrame

The catch-all. A clean rounded card that works as a "generic UI shot" when you don't want to commit to a device. Use sparingly — devices are stronger.

```tsx
type CardFrameProps = {
  theme?: "light" | "dark";
  className?: string;
  children: React.ReactNode;
};

export function CardFrame({
  theme = "light",
  className = "",
  children,
}: CardFrameProps) {
  const isDark = theme === "dark";
  return (
    <div
      className={`relative overflow-hidden rounded-2xl border ${
        isDark
          ? "border-white/10 bg-[#0e1014]"
          : "border-black/8 bg-white"
      } ${className}`}
      style={{ boxShadow: "0 24px 48px -12px rgb(0 0 0 / 0.12)" }}
    >
      {children}
    </div>
  );
}
```

---

## Content primitives (compose inside frames)

When you can't use a real screenshot, use these clean primitives. They don't fake an entire app — they show ONE clear thing. **Max 3 primitives per frame.** More than that and you've reverted to "fake dashboard" territory.

All primitives use real-looking data. None invent brand names. Numeric data uses `font-variant-numeric: tabular-nums` and Geist Mono.

### LineChart

SVG line chart with one or two series, smooth path, real labels (months / weekdays), one accent dot at the latest point.

```tsx
type LineChartProps = {
  data: { label: string; a: number; b?: number }[];
  className?: string;
};

export function LineChart({ data, className = "" }: LineChartProps) {
  const W = 560;
  const H = 200;
  const PAD_X = 32;
  const PAD_Y = 24;
  const max = Math.max(...data.flatMap((d) => [d.a, d.b ?? 0]));
  const min = Math.min(...data.flatMap((d) => [d.a, d.b ?? Infinity]));
  const range = max - min || 1;

  const x = (i: number) =>
    PAD_X + (i * (W - PAD_X * 2)) / (data.length - 1);
  const y = (v: number) =>
    PAD_Y + (1 - (v - min) / range) * (H - PAD_Y * 2);

  const path = (key: "a" | "b") => {
    const pts = data
      .map((d, i) => (d[key] != null ? [x(i), y(d[key]!)] : null))
      .filter(Boolean) as [number, number][];
    if (!pts.length) return "";
    return pts.reduce(
      (acc, [px, py], i) =>
        i === 0
          ? `M ${px} ${py}`
          : `${acc} L ${px} ${py}`,
      ""
    );
  };

  const last = data[data.length - 1];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={`w-full h-auto ${className}`}
      style={{ fontFamily: "'Geist Mono', ui-monospace, monospace" }}
    >
      {/* Y gridlines */}
      {[0.25, 0.5, 0.75].map((t) => (
        <line
          key={t}
          x1={PAD_X}
          x2={W - PAD_X}
          y1={PAD_Y + t * (H - PAD_Y * 2)}
          y2={PAD_Y + t * (H - PAD_Y * 2)}
          stroke="currentColor"
          strokeOpacity="0.07"
        />
      ))}

      {/* Series B (muted) */}
      {data.some((d) => d.b != null) && (
        <path
          d={path("b")}
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.25"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}

      {/* Series A (accent) */}
      <path
        d={path("a")}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Last-point dot */}
      <circle
        cx={x(data.length - 1)}
        cy={y(last.a)}
        r="4"
        fill="var(--accent)"
      />
      <circle
        cx={x(data.length - 1)}
        cy={y(last.a)}
        r="9"
        fill="var(--accent)"
        fillOpacity="0.18"
      />

      {/* X labels */}
      {data.map((d, i) => (
        <text
          key={d.label}
          x={x(i)}
          y={H - 4}
          textAnchor="middle"
          fontSize="9"
          fill="currentColor"
          fillOpacity="0.45"
        >
          {d.label}
        </text>
      ))}
    </svg>
  );
}

// Example data:
// [
//   { label: "Mon", a: 4280, b: 3940 },
//   { label: "Tue", a: 5120, b: 4310 },
//   { label: "Wed", a: 4870, b: 4602 },
//   { label: "Thu", a: 6240, b: 5180 },
//   { label: "Fri", a: 7180, b: 5740 },
//   { label: "Sat", a: 6925, b: 5610 },
//   { label: "Sun", a: 7842, b: 6204 },
// ]
```

### BarChart

Vertical bars, one accent column highlighted (latest / current period).

```tsx
type BarChartProps = {
  data: { label: string; value: number }[];
  highlightLast?: boolean;
  className?: string;
};

export function BarChart({
  data,
  highlightLast = true,
  className = "",
}: BarChartProps) {
  const W = 480;
  const H = 200;
  const PAD_X = 24;
  const PAD_Y = 24;
  const BAR_W = (W - PAD_X * 2) / data.length - 8;
  const max = Math.max(...data.map((d) => d.value));

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={`w-full h-auto ${className}`}
      style={{ fontFamily: "'Geist Mono', ui-monospace, monospace" }}
    >
      {data.map((d, i) => {
        const h = ((H - PAD_Y * 2) * d.value) / max;
        const x = PAD_X + i * ((W - PAD_X * 2) / data.length) + 4;
        const y = H - PAD_Y - h;
        const isLast = i === data.length - 1;
        return (
          <g key={d.label}>
            <rect
              x={x}
              y={y}
              width={BAR_W}
              height={h}
              rx="3"
              fill={highlightLast && isLast ? "var(--accent)" : "currentColor"}
              fillOpacity={highlightLast && isLast ? 1 : 0.15}
            />
            <text
              x={x + BAR_W / 2}
              y={H - 6}
              textAnchor="middle"
              fontSize="9"
              fill="currentColor"
              fillOpacity="0.45"
            >
              {d.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// Example data:
// [
//   { label: "W21", value: 4280 },
//   { label: "W22", value: 5120 },
//   { label: "W23", value: 4870 },
//   { label: "W24", value: 6240 },
//   { label: "W25", value: 7180 },
//   { label: "W26", value: 7842 },
// ]
```

### KPIStrip

Three or four stat cards. Label / value / delta. Tabular numerals via Geist Mono. Real-looking organic numbers (no `99.99%`).

```tsx
type KPI = {
  label: string;
  value: string;
  delta?: { dir: "up" | "down"; value: string };
};

export function KPIStrip({ items }: { items: KPI[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-black/6">
      {items.map((it) => (
        <div key={it.label} className="bg-white p-4">
          <div className="text-[10px] uppercase tracking-[0.14em] text-neutral-500 font-medium">
            {it.label}
          </div>
          <div
            className="mt-1.5 text-2xl font-semibold text-neutral-900"
            style={{
              fontFamily: "'Geist Mono', ui-monospace, monospace",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {it.value}
          </div>
          {it.delta && (
            <div
              className={`mt-1 inline-flex items-center gap-1 text-[11px] font-medium ${
                it.delta.dir === "up" ? "text-emerald-600" : "text-rose-600"
              }`}
              style={{
                fontFamily: "'Geist Mono', ui-monospace, monospace",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              <span>{it.delta.dir === "up" ? "▲" : "▼"}</span>
              {it.delta.value}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// Example items:
// [
//   { label: "MRR",          value: "$48,217", delta: { dir: "up",   value: "12.4%" } },
//   { label: "Active seats", value: "1,247",   delta: { dir: "up",   value: "3.1%"  } },
//   { label: "Trial → paid", value: "31.8%",   delta: { dir: "down", value: "1.2%"  } },
//   { label: "NPS",          value: "62",      delta: { dir: "up",   value: "4 pts" } },
// ]
```

### Sidebar

Generic app sidebar. Logo at top, 4–5 nav items with line icons, an active state, a footer slot. Width 240px (collapses to 56px via `compact` if needed).

```tsx
type NavItem = { label: string; icon: React.ReactNode; active?: boolean; count?: number };

export function Sidebar({
  brand = "Outlier",
  items,
  workspace = "Maya Okafor",
}: {
  brand?: string;
  items: NavItem[];
  workspace?: string;
}) {
  return (
    <nav className="w-[240px] shrink-0 border-r border-black/6 bg-[#fafaf9] flex flex-col h-full">
      {/* Brand */}
      <div className="px-4 h-12 flex items-center gap-2 border-b border-black/6">
        <span className="size-5 rounded-md bg-neutral-900" />
        <span className="text-sm font-semibold text-neutral-900">{brand}</span>
      </div>

      {/* Items */}
      <ul className="p-2 space-y-0.5 flex-1">
        {items.map((it) => (
          <li key={it.label}>
            <a
              href="#"
              className={`flex items-center gap-2.5 h-8 px-2.5 rounded-md text-[13px] ${
                it.active
                  ? "bg-white text-neutral-900 shadow-[0_1px_2px_rgba(0,0,0,0.04)] border border-black/6"
                  : "text-neutral-600 hover:bg-black/4"
              }`}
            >
              <span className="size-4 shrink-0 text-current opacity-70">
                {it.icon}
              </span>
              <span className="flex-1 truncate">{it.label}</span>
              {it.count != null && (
                <span
                  className="text-[10px] text-neutral-500"
                  style={{
                    fontFamily: "'Geist Mono', ui-monospace, monospace",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {it.count}
                </span>
              )}
            </a>
          </li>
        ))}
      </ul>

      {/* Workspace footer */}
      <div className="px-3 h-12 border-t border-black/6 flex items-center gap-2">
        <span className="size-6 rounded-full bg-gradient-to-br from-amber-300 to-rose-400" />
        <span className="text-[12px] text-neutral-700 truncate">{workspace}</span>
      </div>
    </nav>
  );
}
```

### TableRows

Clean data table. 4 columns, 5 rows. Real-looking entries (people, statuses, organic dates/amounts). Alternating zebra is optional — usually cleaner without.

```tsx
type Row = { id: string; name: string; status: "Paid" | "Pending" | "Refunded"; amount: string; date: string };

export function TableRows({ rows }: { rows: Row[] }) {
  return (
    <div className="text-[13px]">
      <div className="grid grid-cols-[1fr_110px_120px_110px] gap-4 px-5 h-9 items-center text-[10px] uppercase tracking-[0.14em] text-neutral-500 font-medium border-b border-black/6">
        <span>Customer</span>
        <span>Status</span>
        <span className="text-right">Amount</span>
        <span className="text-right">Date</span>
      </div>
      {rows.map((r) => (
        <div
          key={r.id}
          className="grid grid-cols-[1fr_110px_120px_110px] gap-4 px-5 h-12 items-center border-b border-black/4 last:border-0"
        >
          <div className="flex items-center gap-3 min-w-0">
            <img
              src={`https://picsum.photos/seed/${r.id}/40/40`}
              alt=""
              className="size-7 rounded-full object-cover shrink-0"
            />
            <span className="truncate text-neutral-900">{r.name}</span>
          </div>
          <span>
            <span
              className={`inline-flex items-center gap-1.5 h-6 px-2 rounded-full text-[11px] font-medium ${
                r.status === "Paid"
                  ? "bg-emerald-50 text-emerald-700"
                  : r.status === "Pending"
                  ? "bg-amber-50 text-amber-700"
                  : "bg-neutral-100 text-neutral-600"
              }`}
            >
              <span
                className={`size-1.5 rounded-full ${
                  r.status === "Paid"
                    ? "bg-emerald-500"
                    : r.status === "Pending"
                    ? "bg-amber-500"
                    : "bg-neutral-400"
                }`}
              />
              {r.status}
            </span>
          </span>
          <span
            className="text-right text-neutral-900"
            style={{
              fontFamily: "'Geist Mono', ui-monospace, monospace",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {r.amount}
          </span>
          <span
            className="text-right text-neutral-500"
            style={{
              fontFamily: "'Geist Mono', ui-monospace, monospace",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {r.date}
          </span>
        </div>
      ))}
    </div>
  );
}

// Example rows:
// [
//   { id: "ezra",  name: "Ezra Singh",        status: "Paid",     amount: "$2,481.00", date: "Apr 24" },
//   { id: "lucia", name: "Lucia Marchetti",   status: "Pending",  amount: "$640.50",   date: "Apr 24" },
//   { id: "tomas", name: "Tomas Brandt",      status: "Paid",     amount: "$1,217.00", date: "Apr 23" },
//   { id: "maya",  name: "Maya Okafor",       status: "Refunded", amount: "$ 89.00",   date: "Apr 23" },
//   { id: "kira",  name: "Kira Adeyemi",      status: "Paid",     amount: "$3,902.40", date: "Apr 22" },
// ]
```

### ChatThread

Three-message message thread. Alternating sides. Real conversation, plausible domain (support, design feedback, dev review). Time stamps in muted Geist Mono.

```tsx
type Message = { from: "them" | "me"; name?: string; text: string; time: string };

export function ChatThread({ messages }: { messages: Message[] }) {
  return (
    <div className="flex flex-col gap-3 p-5 text-[13px]">
      {messages.map((m, i) => (
        <div
          key={i}
          className={`flex gap-2 ${m.from === "me" ? "justify-end" : "justify-start"}`}
        >
          {m.from === "them" && (
            <img
              src={`https://picsum.photos/seed/${m.name}/40/40`}
              alt=""
              className="size-7 rounded-full object-cover self-end"
            />
          )}
          <div
            className={`max-w-[75%] rounded-2xl px-3.5 py-2 ${
              m.from === "me"
                ? "bg-[var(--accent)] text-[var(--accent-fg)] rounded-br-md"
                : "bg-neutral-100 text-neutral-900 rounded-bl-md"
            }`}
          >
            <p className="leading-snug">{m.text}</p>
            <div
              className={`mt-1 text-[10px] ${
                m.from === "me" ? "text-white/70" : "text-neutral-500"
              }`}
              style={{
                fontFamily: "'Geist Mono', ui-monospace, monospace",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {m.time}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// Example messages:
// [
//   { from: "them", name: "lucia", text: "Pushed the new export flow — can you take a pass before standup?", time: "9:14" },
//   { from: "me",                  text: "On it. Did the CSV header order get fixed?",                       time: "9:16" },
//   { from: "them", name: "lucia", text: "Yes — matches the spec now. Test file is in /fixtures/q2.",        time: "9:17" },
// ]
```

### CalendarGrid

7-column month grid, 5 visible rows. Today highlighted with accent ring. 1–2 events as colored dots beneath the date number.

```tsx
type Event = { day: number; color?: string };

export function CalendarGrid({
  monthLabel = "April 2026",
  today = 24,
  startWeekday = 2, // Apr 1, 2026 = Wednesday
  daysInMonth = 30,
  events = [
    { day: 9, color: "var(--accent)" },
    { day: 18 },
    { day: 24, color: "var(--accent)" },
    { day: 24 },
  ],
}: {
  monthLabel?: string;
  today?: number;
  startWeekday?: number;
  daysInMonth?: number;
  events?: Event[];
}) {
  const cells: ({ day: number } | null)[] = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: d });
  while (cells.length % 7) cells.push(null);

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-semibold text-neutral-900">{monthLabel}</h3>
        <div className="flex gap-1">
          <button className="size-7 rounded-md hover:bg-black/5 text-neutral-500">‹</button>
          <button className="size-7 rounded-md hover:bg-black/5 text-neutral-500">›</button>
        </div>
      </div>
      <div className="grid grid-cols-7 gap-1 text-[10px] uppercase tracking-[0.14em] text-neutral-500 font-medium mb-2">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
          <div key={d} className="text-center">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((c, i) => (
          <div
            key={i}
            className={`aspect-square rounded-md flex flex-col items-center justify-center text-[12px] ${
              c?.day === today
                ? "bg-[var(--accent)] text-[var(--accent-fg)] font-semibold"
                : c
                ? "text-neutral-700 hover:bg-black/4"
                : ""
            }`}
            style={{
              fontFamily: "'Geist Mono', ui-monospace, monospace",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {c && <span>{c.day}</span>}
            {c && (
              <div className="flex gap-0.5 mt-0.5 h-1">
                {events
                  .filter((e) => e.day === c.day)
                  .slice(0, 3)
                  .map((e, k) => (
                    <span
                      key={k}
                      className="size-1 rounded-full"
                      style={{
                        background:
                          c.day === today ? "currentColor" : e.color || "#d4d4d4",
                      }}
                    />
                  ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

### CodeEditor

Code window with line numbers and minimal hand-rolled syntax highlighting. Real-looking JSX/TS, never Lorem.

```tsx
type Token = { t: string; c?: "kw" | "str" | "fn" | "cm" | "tag" | "attr" | "punct" };
type Line = Token[];

export function CodeEditor({
  filename = "components/Hero.tsx",
  lines,
  theme = "light",
}: {
  filename?: string;
  lines: Line[];
  theme?: "light" | "dark";
}) {
  const isDark = theme === "dark";
  const colors = isDark
    ? { kw: "#c792ea", str: "#c3e88d", fn: "#82aaff", cm: "#5c6370", tag: "#f07178", attr: "#ffcb6b", punct: "#abb2bf", base: "#e6e6e6" }
    : { kw: "#a626a4", str: "#50a14f", fn: "#4078f2", cm: "#a0a1a7", tag: "#e45649", attr: "#986801", punct: "#383a42", base: "#383a42" };

  return (
    <div
      className={isDark ? "bg-[#0e1014] text-neutral-200" : "bg-[#fafafa] text-neutral-800"}
      style={{ fontFamily: "'Geist Mono', ui-monospace, monospace" }}
    >
      <div
        className={`flex items-center gap-2 h-9 px-4 text-[11px] border-b ${
          isDark ? "border-white/8 text-white/60" : "border-black/6 text-neutral-500"
        }`}
      >
        <span className="size-3 rounded-sm bg-blue-500/30" />
        {filename}
      </div>
      <div className="text-[12px] leading-[1.7] py-3">
        {lines.map((line, i) => (
          <div key={i} className="grid grid-cols-[40px_1fr] gap-3 px-3">
            <span
              className={isDark ? "text-white/25 text-right" : "text-neutral-400 text-right"}
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {i + 1}
            </span>
            <code style={{ color: colors.base }}>
              {line.map((tok, k) => (
                <span
                  key={k}
                  style={{ color: tok.c ? colors[tok.c] : colors.base }}
                >
                  {tok.t}
                </span>
              ))}
            </code>
          </div>
        ))}
      </div>
    </div>
  );
}

// Example lines:
// [
//   [{ t: "import", c: "kw" }, { t: " { motion } " }, { t: "from", c: "kw" }, { t: " " }, { t: "\"framer-motion\"", c: "str" }],
//   [],
//   [{ t: "export", c: "kw" }, { t: " " }, { t: "function", c: "kw" }, { t: " " }, { t: "Hero", c: "fn" }, { t: "() {" }],
//   [{ t: "  " }, { t: "return", c: "kw" }, { t: " (" }],
//   [{ t: "    <" }, { t: "section", c: "tag" }, { t: " " }, { t: "className", c: "attr" }, { t: "=" }, { t: "\"px-6 py-24\"", c: "str" }, { t: ">" }],
//   [{ t: "      <" }, { t: "h1", c: "tag" }, { t: ">Build something real</" }, { t: "h1", c: "tag" }, { t: ">" }],
//   [{ t: "    </" }, { t: "section", c: "tag" }, { t: ">" }],
//   [{ t: "  )" }],
//   [{ t: "}" }],
// ]
```

### TerminalWindow

Terminal with prompt cursor, 4–5 lines of plausible output. No fake `Loading...` spinner — just real text from `pnpm`, `git`, `vercel`, etc.

```tsx
type TermLine =
  | { kind: "prompt"; cmd: string }
  | { kind: "out"; text: string; tone?: "ok" | "warn" | "muted" };

export function TerminalWindow({
  cwd = "outlier-app",
  lines,
}: {
  cwd?: string;
  lines: TermLine[];
}) {
  const tone = (t?: string) =>
    t === "ok"
      ? "text-emerald-400"
      : t === "warn"
      ? "text-amber-400"
      : t === "muted"
      ? "text-white/45"
      : "text-white/85";

  return (
    <div
      className="bg-[#0e1014] text-[12px] leading-[1.7] p-4"
      style={{ fontFamily: "'Geist Mono', ui-monospace, monospace" }}
    >
      {lines.map((l, i) =>
        l.kind === "prompt" ? (
          <div key={i} className="flex gap-2">
            <span className="text-emerald-400">{cwd}</span>
            <span className="text-white/40">›</span>
            <span className="text-white">{l.cmd}</span>
          </div>
        ) : (
          <div key={i} className={tone(l.tone)}>
            {l.text}
          </div>
        )
      )}
      <div className="flex gap-2 mt-1">
        <span className="text-emerald-400">{cwd}</span>
        <span className="text-white/40">›</span>
        <span className="inline-block w-[7px] h-[14px] bg-white/85 animate-pulse" />
      </div>
    </div>
  );
}

// Example lines:
// [
//   { kind: "prompt", cmd: "pnpm build" },
//   { kind: "out", text: "  ▲ Next.js 15.0.3", tone: "muted" },
//   { kind: "out", text: "  ✓ Compiled successfully in 8.2s", tone: "ok" },
//   { kind: "out", text: "  ✓ Generated 47 static pages",     tone: "ok" },
//   { kind: "out", text: "  Route                       Size", tone: "muted" },
//   { kind: "out", text: "  ┌ ○ /                       2.1 kB" },
//   { kind: "out", text: "  ├ ○ /pricing                3.4 kB" },
//   { kind: "out", text: "  └ ƒ /api/checkout           0.3 kB" },
// ]
```

---

## Composition examples

Real, complete examples. Each shows how to compose ONE frame + 1–3 primitives. Copy the pattern; don't pile more in.

### 1. SaaS dashboard hero (BrowserFrame > Sidebar + KPIStrip + LineChart)

```tsx
<div className="relative max-w-5xl mx-auto">
  <div
    className="absolute inset-x-12 -bottom-4 h-32 blur-3xl opacity-40"
    style={{ background: "var(--accent)" }}
    aria-hidden
  />
  <BrowserFrame url="app.outlier.dev/overview" theme="light">
    <div className="flex h-[460px]">
      <Sidebar
        brand="Outlier"
        workspace="Maya Okafor"
        items={[
          { label: "Overview", icon: <DotIcon />, active: true },
          { label: "Customers", icon: <DotIcon />, count: 1247 },
          { label: "Invoices",  icon: <DotIcon />, count: 38 },
          { label: "Reports",   icon: <DotIcon /> },
          { label: "Settings",  icon: <DotIcon /> },
        ]}
      />
      <div className="flex-1 flex flex-col">
        <KPIStrip
          items={[
            { label: "MRR",          value: "$48,217", delta: { dir: "up",   value: "12.4%" } },
            { label: "Active seats", value: "1,247",   delta: { dir: "up",   value: "3.1%"  } },
            { label: "Trial → paid", value: "31.8%",   delta: { dir: "down", value: "1.2%"  } },
            { label: "NPS",          value: "62",      delta: { dir: "up",   value: "4 pts" } },
          ]}
        />
        <div className="p-5 flex-1">
          <LineChart
            data={[
              { label: "Mon", a: 4280, b: 3940 },
              { label: "Tue", a: 5120, b: 4310 },
              { label: "Wed", a: 4870, b: 4602 },
              { label: "Thu", a: 6240, b: 5180 },
              { label: "Fri", a: 7180, b: 5740 },
              { label: "Sat", a: 6925, b: 5610 },
              { label: "Sun", a: 7842, b: 6204 },
            ]}
          />
        </div>
      </div>
    </div>
  </BrowserFrame>
</div>
```

### 2. Mobile app hero (iPhoneFrame > ChatThread)

```tsx
<IPhoneFrame time="9:41">
  <div className="h-full flex flex-col">
    <header className="px-5 py-3 border-b border-black/5">
      <h2 className="text-[15px] font-semibold">Lucia Marchetti</h2>
      <p className="text-[11px] text-neutral-500">Active now</p>
    </header>
    <div className="flex-1 overflow-hidden">
      <ChatThread
        messages={[
          { from: "them", name: "lucia", text: "Pushed the new export flow — can you take a pass before standup?", time: "9:14" },
          { from: "me",                  text: "On it. Did the CSV header order get fixed?",                       time: "9:16" },
          { from: "them", name: "lucia", text: "Yes — matches the spec now. Test file is in /fixtures/q2.",        time: "9:17" },
        ]}
      />
    </div>
  </div>
</IPhoneFrame>
```

### 3. Developer tool hero (BrowserFrame > CodeEditor + TerminalWindow)

```tsx
<BrowserFrame url="ide.outlier.dev/repo/web" theme="dark">
  <div className="grid grid-rows-[1fr_180px] h-[480px]">
    <CodeEditor
      filename="app/(marketing)/Hero.tsx"
      theme="dark"
      lines={[
        [{ t: "import", c: "kw" }, { t: " { motion } " }, { t: "from", c: "kw" }, { t: " " }, { t: "\"framer-motion\"", c: "str" }],
        [],
        [{ t: "export", c: "kw" }, { t: " " }, { t: "function", c: "kw" }, { t: " " }, { t: "Hero", c: "fn" }, { t: "() {" }],
        [{ t: "  " }, { t: "return", c: "kw" }, { t: " (" }],
        [{ t: "    <" }, { t: "section", c: "tag" }, { t: " " }, { t: "className", c: "attr" }, { t: "=" }, { t: "\"px-6 py-24\"", c: "str" }, { t: ">" }],
        [{ t: "      <" }, { t: "h1", c: "tag" }, { t: ">Build something real</" }, { t: "h1", c: "tag" }, { t: ">" }],
        [{ t: "    </" }, { t: "section", c: "tag" }, { t: ">" }],
        [{ t: "  )" }],
        [{ t: "}" }],
      ]}
    />
    <TerminalWindow
      cwd="outlier-web"
      lines={[
        { kind: "prompt", cmd: "pnpm build" },
        { kind: "out", text: "  ▲ Next.js 15.0.3", tone: "muted" },
        { kind: "out", text: "  ✓ Compiled successfully in 8.2s", tone: "ok" },
        { kind: "out", text: "  ✓ Generated 47 static pages",     tone: "ok" },
      ]}
    />
  </div>
</BrowserFrame>
```

### 4. Analytics product hero (MacBookFrame > Sidebar + KPIStrip + TableRows)

```tsx
<MacBookFrame>
  <div className="flex h-full">
    <Sidebar
      brand="Outlier"
      items={[
        { label: "Overview",   icon: <DotIcon /> },
        { label: "Payments",   icon: <DotIcon />, active: true },
        { label: "Customers",  icon: <DotIcon />, count: 1247 },
        { label: "Reports",    icon: <DotIcon /> },
        { label: "Settings",   icon: <DotIcon /> },
      ]}
    />
    <div className="flex-1 flex flex-col">
      <KPIStrip
        items={[
          { label: "Volume (24h)", value: "$128,402", delta: { dir: "up", value: "8.7%" } },
          { label: "Successful",   value: "98.4%",    delta: { dir: "up", value: "0.3%" } },
          { label: "Disputed",     value: "0.21%",    delta: { dir: "down", value: "0.04%" } },
          { label: "Refunded",     value: "$890",     delta: { dir: "down", value: "12%" } },
        ]}
      />
      <TableRows
        rows={[
          { id: "ezra",  name: "Ezra Singh",      status: "Paid",     amount: "$2,481.00", date: "Apr 24" },
          { id: "lucia", name: "Lucia Marchetti", status: "Pending",  amount: "$640.50",   date: "Apr 24" },
          { id: "tomas", name: "Tomas Brandt",    status: "Paid",     amount: "$1,217.00", date: "Apr 23" },
          { id: "maya",  name: "Maya Okafor",     status: "Refunded", amount: "$ 89.00",   date: "Apr 23" },
          { id: "kira",  name: "Kira Adeyemi",    status: "Paid",     amount: "$3,902.40", date: "Apr 22" },
        ]}
      />
    </div>
  </div>
</MacBookFrame>
```

### 5. Wearable product hero (AppleWatchFrame > simple stat display)

```tsx
<AppleWatchFrame>
  <div className="h-full flex flex-col items-center justify-center px-3 text-center">
    <div className="text-[10px] uppercase tracking-[0.14em] text-white/55 mb-1">
      Move
    </div>
    <div
      className="text-[42px] leading-none font-semibold text-[#fb6a4a]"
      style={{
        fontFamily: "'Geist Mono', ui-monospace, monospace",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      482
    </div>
    <div className="text-[10px] text-white/55 mt-0.5">/ 600 cal</div>
    <div className="mt-3 h-1 w-24 rounded-full bg-white/10 overflow-hidden">
      <div className="h-full w-[80%] bg-[#fb6a4a]" />
    </div>
  </div>
</AppleWatchFrame>
```

### 6. Calendar app hero (BrowserFrame > Sidebar + CalendarGrid)

```tsx
<BrowserFrame url="cal.outlier.dev/april" theme="light">
  <div className="flex h-[460px]">
    <Sidebar
      brand="Cadence"
      items={[
        { label: "Day",      icon: <DotIcon /> },
        { label: "Week",     icon: <DotIcon /> },
        { label: "Month",    icon: <DotIcon />, active: true },
        { label: "Bookings", icon: <DotIcon />, count: 12 },
        { label: "Settings", icon: <DotIcon /> },
      ]}
    />
    <div className="flex-1">
      <CalendarGrid
        monthLabel="April 2026"
        today={24}
        startWeekday={2}
        daysInMonth={30}
      />
    </div>
  </div>
</BrowserFrame>
```

---

## What NOT to do

- ❌ Don't invent custom UI inside a frame — use the primitives above. The frame is the premium signal; the content should be clean and minimal.
- ❌ Don't stack 5+ primitives in one frame (cluttered = AI tell). **Max 3 primitives per frame.**
- ❌ Don't put fake testimonials/avatars in frames — use real photos via `picsum.photos/seed/{id}/{w}/{h}`.
- ❌ Don't use fake brand names like "Acme Inc" inside frames. Pick a believable two-syllable name (Outlier, Cadence, Filo) — see `anti-slop.md` § CONTENT.
- ❌ Don't scale frames below their natural minimum. `BrowserFrame` < 600px wide looks silly. `iPhoneFrame` < 240px wide loses the chrome detail.
- ❌ Don't add fake decorative gradients inside frames. The frame chrome IS the premium signal — don't compete with it.
- ❌ Don't skip the under-mockup glow when placing a frame in a hero. See `hero-saas.md` for the pattern.
- ❌ Don't render a frame on mobile at full size. Wrap in `<div className="scale-[0.7] origin-top md:scale-100">` or similar.

---

## When you don't have a screenshot AND don't want a frame

Use a single hero photo from `assets/backgrounds/` for context, OR `picsum.photos/seed/{slug}/{w}/{h}` for placeholder. **Do not invent UI.** A single beautiful photo > a fake dashboard.

---

## Future: real image generation

For sites with budget for AI image gen (Replicate, fal.ai, OpenAI gpt-image-1) to produce real product mockups instead of frames + primitives, see `image-generation.md`. That's a power-user upgrade — for most builds, this recipe is enough.

---

## Cross-references

- See `recipes/hero-saas.md` for the bleeding-mockup hero composition (drop a `BrowserFrame` where the `<img>` is)
- See `recipes/hero-fintech.md` — fintech is the EXCEPTION: a real interactive widget is allowed (and preferred) over a frame
- See `tokens.md` for the `--shadow-xl` and `--shadow-glow` tokens used in frame shadows
- See `anti-slop.md` § COMPONENT for the "fake dashboard" anti-pattern this recipe replaces
- See `image-generation.md` for the optional real-image-gen integration
