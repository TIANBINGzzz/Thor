# recipes/dashboard-shell.md — Premium Dashboard Shell

**Page header + sidebar + content area for admin/SaaS dashboards.** Adapted from awsmd-dashboard, kvnkld empty state, jeet-agent, shahidux.

## When to use

- Internal/admin dashboard
- User says: dashboard, admin panel, control panel, analytics
- B2B SaaS that needs a "logged-in app" feeling

## Structure

- Left sidebar (~240px) with logo + nav + workspace switcher
- Top page header: breadcrumb / title-subtitle (left) + search / filter / sort / primary CTA (right)
- Content area: cards, tables, charts
- One accent color throughout (semantic colors red/green/yellow OK for status)

## Code

```tsx
import { motion } from "framer-motion";
import { Search, Plus, Filter, ArrowUpDown, Bell } from "lucide-react";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--bg)] flex">
      <Sidebar />
      <main className="flex-1 flex flex-col">
        <PageHeader />
        <div className="flex-1 p-8">{children}</div>
      </main>
    </div>
  );
}

function Sidebar() {
  return (
    <aside className="w-60 shrink-0 border-r border-black/8 bg-[var(--bg-elevated)] flex flex-col">
      {/* Workspace switcher */}
      <div className="p-4 border-b border-black/8">
        <button className="w-full flex items-center gap-2.5 rounded-lg p-2 hover:bg-neutral-100">
          <div className="size-7 rounded-md bg-[var(--accent)] grid place-items-center text-[var(--accent-fg)] font-bold text-sm">A</div>
          <div className="text-left">
            <div className="text-sm font-semibold">Acme Inc.</div>
            <div className="text-[11px] text-[var(--text-muted)]">Pro plan</div>
          </div>
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-0.5">
        <NavItem icon="📊" label="Overview" active />
        <NavItem icon="📦" label="Projects" />
        <NavItem icon="👥" label="Team" />
        <NavItem icon="⚙️" label="Settings" />
      </nav>
    </aside>
  );
}

function NavItem({ icon, label, active = false }: { icon: string; label: string; active?: boolean }) {
  return (
    <a
      href="#"
      className={`relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
        active ? "bg-[var(--text)] text-[var(--bg)]" : "text-[var(--text)] hover:bg-neutral-100"
      }`}
    >
      <span>{icon}</span>
      {label}
      {active && (
        <motion.span
          layoutId="sidebar-active-pill"
          className="absolute inset-0 -z-10 rounded-lg bg-[var(--text)]"
        />
      )}
    </a>
  );
}

function PageHeader() {
  return (
    <header className="px-8 py-5 border-b border-black/8 flex items-center justify-between gap-4">
      {/* LEFT: title + subtitle */}
      <div>
        <h1 className="text-xl font-bold tracking-tight">Overview</h1>
        <p className="text-sm text-[var(--text-muted)]">Last 30 days</p>
      </div>

      {/* RIGHT: actions */}
      <div className="flex items-center gap-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-[var(--text-muted)]" />
          <input
            type="text"
            placeholder="Search..."
            className="rounded-full border border-black/10 bg-white pl-8 pr-3 py-2 text-sm w-56 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30"
          />
        </div>
        <button className="grid place-items-center size-9 rounded-full border border-black/10 bg-white">
          <Filter className="size-4" />
        </button>
        <button className="grid place-items-center size-9 rounded-full border border-black/10 bg-white">
          <ArrowUpDown className="size-4" />
        </button>
        <button className="grid place-items-center size-9 rounded-full border border-black/10 bg-white">
          <Bell className="size-4" />
        </button>
        <a className="inline-flex items-center gap-1.5 rounded-full bg-[var(--text)] px-4 py-2 text-sm font-medium text-[var(--bg)] hover:bg-[var(--text)]/90">
          <Plus className="size-4" />
          New project
        </a>
      </div>
    </header>
  );
}
```

## Content area patterns

### Empty state (the kvnkld pattern)

```tsx
// Don't show a blank screen. Show ghost cards behind the CTA.
<div className="relative grid place-items-center min-h-[60vh]">
  <div className="absolute inset-0 grid grid-cols-2 md:grid-cols-3 gap-4 opacity-30 pointer-events-none">
    {[...Array(6)].map((_, i) => (
      <div key={i} className="aspect-video rounded-xl bg-neutral-100 border border-black/8" />
    ))}
  </div>
  <div className="relative text-center max-w-sm">
    <h3 className="text-2xl font-bold">No projects yet</h3>
    <p className="mt-2 text-sm text-[var(--text-muted)]">Create your first project to get started.</p>
    <a className="mt-6 inline-flex rounded-full bg-[var(--text)] px-5 py-2.5 text-sm font-medium text-[var(--bg)]">
      Create project
    </a>
  </div>
</div>
```

### KPI strip

```tsx
<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
  {[
    { label: "Revenue", value: "$24,381", delta: "+12.4%", deltaColor: "emerald" },
    { label: "Users", value: "12,492", delta: "+3.1%", deltaColor: "emerald" },
    { label: "Conversion", value: "3.2%", delta: "-0.4%", deltaColor: "neutral" },
    { label: "Churn", value: "1.8%", delta: "-0.2%", deltaColor: "emerald" },
  ].map((k) => (
    <div key={k.label} className="rounded-2xl border border-black/8 bg-white p-5">
      <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider">{k.label}</div>
      <div className="mt-2 text-3xl font-bold tabular-nums tracking-tight">{k.value}</div>
      <div className={`mt-1 text-xs font-medium text-${k.deltaColor}-600`}>{k.delta} from last month</div>
    </div>
  ))}
</div>
```

## Comparison Line Chart

The signature dashboard chart for time-series with year-over-year or period-over-period context. **No legend** — the tooltip carries the labels. Past series is dotted, never dashed (dashes look like errors). Single hue; the difference is line style + tooltip pill style.

```tsx
import { motion } from "framer-motion";
import { useMemo, useState } from "react";

type Point = { label: string; current: number; past: number };

export function ComparisonChart({ data, height = 240 }: { data: Point[]; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const [showPast, setShowPast] = useState(true);

  const { currentPath, pastPath, points } = useMemo(() => {
    const max = Math.max(...data.flatMap((d) => [d.current, d.past])) * 1.1;
    const w = 100, h = 100;
    const step = w / (data.length - 1);
    const points = data.map((d, i) => ({
      x: i * step,
      yCurr: h - (d.current / max) * h,
      yPast: h - (d.past    / max) * h,
    }));
    const currentPath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.yCurr}`).join(" ");
    const pastPath    = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.yPast}`).join(" ");
    return { currentPath, pastPath, points };
  }, [data]);

  const active = hover !== null ? data[hover] : null;
  const activePoint = hover !== null ? points[hover] : null;

  return (
    <div className="rounded-2xl border border-black/8 bg-[var(--bg-elevated)] p-5">
      {/* Header w/ Curr/Past toggle */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-sm font-semibold">Daily active users</div>
          <div className="text-xs text-[var(--text-muted)]">vs previous 30 days</div>
        </div>
        <div className="inline-flex rounded-full border border-black/10 p-0.5 text-[11px] font-medium">
          <button
            onClick={() => setShowPast(false)}
            className={`px-2.5 py-1 rounded-full transition-colors ${!showPast ? "bg-[var(--text)] text-[var(--bg)]" : "text-[var(--text-muted)]"}`}
          >
            Curr
          </button>
          <button
            onClick={() => setShowPast(true)}
            className={`px-2.5 py-1 rounded-full transition-colors ${showPast ? "bg-[var(--text)] text-[var(--bg)]" : "text-[var(--text-muted)]"}`}
          >
            Curr / Past
          </button>
        </div>
      </div>

      {/* SVG chart */}
      <div
        className="relative"
        style={{ height }}
        onMouseLeave={() => setHover(null)}
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full overflow-visible">
          {showPast && (
            <path
              d={pastPath}
              fill="none"
              stroke="var(--accent)"
              strokeOpacity="0.55"
              strokeLinecap="round"
              strokeDasharray="0.6 1.4"
              vectorEffect="non-scaling-stroke"
              style={{ strokeWidth: 1.5 }}
            />
          )}
          <path
            d={currentPath}
            fill="none"
            stroke="var(--accent)"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            style={{ strokeWidth: 2 }}
          />
          {points.map((p, i) => (
            <rect
              key={i}
              x={p.x - (100 / data.length) / 2}
              y={0}
              width={100 / data.length}
              height={100}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              style={{ cursor: "crosshair" }}
            />
          ))}
          {activePoint && (
            <>
              <line
                x1={activePoint.x} x2={activePoint.x}
                y1={0} y2={100}
                stroke="var(--text)" strokeOpacity="0.08"
                vectorEffect="non-scaling-stroke" style={{ strokeWidth: 1 }}
              />
              <circle cx={activePoint.x} cy={activePoint.yCurr} r="0.6" fill="var(--accent)" />
            </>
          )}
        </svg>

        {/* Stacked-pill tooltip — the legend lives at the active point */}
        {active && activePoint && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            className="absolute -translate-x-1/2 -translate-y-full -mt-2 flex flex-col items-stretch gap-1 pointer-events-none"
            style={{ left: `${activePoint.x}%`, top: `${activePoint.yCurr}%` }}
          >
            <div className="rounded-full bg-[var(--accent)] text-[var(--accent-fg)] px-2.5 py-0.5 text-[11px] font-semibold tabular-nums shadow-sm">
              Current {active.current}
            </div>
            {showPast && (
              <div className="rounded-full bg-[var(--bg-elevated)] border border-[var(--accent)]/40 text-[var(--accent)] px-2.5 py-0.5 text-[11px] font-semibold tabular-nums">
                Past {active.past}
              </div>
            )}
          </motion.div>
        )}
      </div>

      <div className="mt-2 flex justify-between text-[10px] text-[var(--text-muted)] font-mono">
        <span>{data[0]?.label}</span>
        <span>{data[Math.floor(data.length / 2)]?.label}</span>
        <span>{data[data.length - 1]?.label}</span>
      </div>
    </div>
  );
}
```

**The tooltip IS the legend.** No separate legend block — the two stacked pills at the active point label both series in context.

**Rules for this micro-pattern:**

- **Past series uses the SAME hue as current** — never a different color. Difference is line style (dotted) + opacity (55%) + tooltip pill style (outlined vs filled).
- **Dotted, not dashed.** `strokeDasharray="0.6 1.4"` — close-spaced dots. Dashes read as "broken / loading."
- **Tooltip pills stack vertically**, current on top, past below. Never side-by-side.
- **No data-point dots on the line** by default — only one dot at the active x.
- **Crosshair cursor** signals interactivity; the dotted vertical guide line confirms.

## Customization rules

- **Sidebar uses one accent color** — active state is dark on cream, hover is just neutral-100
- **Page header is split L/R** — never stack title and actions
- **Search is required** — always pill-shaped with icon left, focus ring uses `--accent`
- **Empty states show ghost cards behind CTA** — never a blank screen
- **Use semantic colors for status** — emerald for success, amber for warning, rose for error. NOT the brand accent.

## What NOT to change

- Don't use `<Sheet>` or shadcn defaults
- Don't make the sidebar wider than 280px
- Don't use checkmark icons in tables (use status pills)
- Don't use the AI-default "MOST" / "POPULAR" tags

## Cross-references

- See `tokens.md` for accent + semantic colors
- See `anti-slop.md` for default-component anti-patterns
- See `recipes/morphing-button.md` for the new-project CTA expansion pattern
