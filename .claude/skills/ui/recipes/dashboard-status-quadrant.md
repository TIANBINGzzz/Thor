# recipes/dashboard-status-quadrant.md — Status Quadrant Card

**Adapted from heyrico.** A 2×2 grid of mini-cards inside a parent card, each mini-card tinted to its status color. For "summary by status" surfaces — bug states, ticket priorities, deal stages, order fulfillment status. Different from the KPI strip in `dashboard-shell.md`: KPI is for metrics with deltas, this is for ENUM counts.

## When to use

- Bug tracker / issue tracker summary
- Support ticket "by priority" or "by status" overview
- Deal pipeline summary (lead / qualified / won / lost)
- Order status (pending / shipped / delivered / returned)
- Anything where you have 4 mutually-exclusive states and want a glanceable count

**Don't use** for: continuous metrics (use KPI strip), more than 4 categories (use a list), single highlight (use a stat card).

## Structure

- Parent card: `rounded-2xl border bg-elevated p-5` with title + period selector at top
- 2×2 grid of mini-cards inside, `gap-3`
- Each mini-card: tinted bg + matching ring + status dot + ALL-CAPS label + bold count
- Hover: subtle `y: -1` lift (no scale)

## Locked tint taxonomy

| Status | bg | ring | dot | text |
|---|---|---|---|---|
| NEW | `bg-blue-50` | `ring-blue-200/60` | `bg-blue-500` | `text-blue-900` |
| IN PROGRESS | `bg-amber-50` | `ring-amber-200/60` | `bg-amber-500` | `text-amber-900` |
| RESOLVED | `bg-emerald-50` | `ring-emerald-200/60` | `bg-emerald-500` | `text-emerald-900` |
| DEEP FIX | `bg-rose-50` | `ring-rose-200/60` | `bg-rose-500` | `text-rose-900` |

## Code

```tsx
import { motion } from "framer-motion";
import { Bug, Loader2, CheckCircle2, AlertOctagon } from "lucide-react";
import type { LucideIcon } from "lucide-react";

type Status = "new" | "in_progress" | "resolved" | "deep_fix";

const STATUS_THEME: Record<
  Status,
  { label: string; bg: string; ring: string; text: string; dot: string; icon: LucideIcon }
> = {
  new:         { label: "New",         bg: "bg-blue-50",    ring: "ring-blue-200/60",    text: "text-blue-900",    dot: "bg-blue-500",    icon: Bug },
  in_progress: { label: "In Progress", bg: "bg-amber-50",   ring: "ring-amber-200/60",   text: "text-amber-900",   dot: "bg-amber-500",   icon: Loader2 },
  resolved:    { label: "Resolved",    bg: "bg-emerald-50", ring: "ring-emerald-200/60", text: "text-emerald-900", dot: "bg-emerald-500", icon: CheckCircle2 },
  deep_fix:    { label: "Deep Fix",    bg: "bg-rose-50",    ring: "ring-rose-200/60",    text: "text-rose-900",    dot: "bg-rose-500",    icon: AlertOctagon },
};

export function StatusQuadrant({
  title = "Bug tracking summary",
  period = "Last 30 days",
  counts,
}: {
  title?: string;
  period?: string;
  counts: Record<Status, number>;
}) {
  const order: Status[] = ["new", "in_progress", "resolved", "deep_fix"];

  return (
    <div className="rounded-2xl border border-black/8 bg-[var(--bg-elevated)] p-5">
      {/* header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          <p className="text-xs text-[var(--text-muted)]">{period}</p>
        </div>
        <button className="text-[11px] font-medium text-[var(--text-muted)] hover:text-[var(--text)] underline-offset-4 hover:underline">
          View all
        </button>
      </div>

      {/* 2x2 grid */}
      <div className="grid grid-cols-2 gap-3">
        {order.map((s) => {
          const t = STATUS_THEME[s];
          const Icon = t.icon;
          return (
            <motion.button
              key={s}
              whileHover={{ y: -1 }}
              transition={{ type: "spring", stiffness: 380, damping: 28 }}
              className={`text-left rounded-xl p-4 ring-1 ring-inset ${t.bg} ${t.ring} hover:shadow-sm`}
            >
              {/* top row: icon chip + dot */}
              <div className="flex items-center justify-between">
                <div className={`grid place-items-center size-8 rounded-lg bg-white/80 ${t.text}`}>
                  <Icon className="size-4" />
                </div>
                <span className={`size-1.5 rounded-full ${t.dot}`} aria-hidden />
              </div>

              {/* label + count */}
              <div className={`mt-3 text-[10px] font-semibold uppercase tracking-[0.14em] ${t.text} opacity-70`}>
                {t.label}
              </div>
              <div className={`mt-0.5 text-2xl font-bold tabular-nums tracking-tight ${t.text}`}>
                {counts[s]}
              </div>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
```

### Usage

```tsx
<StatusQuadrant
  counts={{ new: 12, in_progress: 8, resolved: 47, deep_fix: 2 }}
/>
```

## What makes it premium

1. **Pastel tints, not saturated fills** — `bg-blue-50` not `bg-blue-500`. The dot carries the saturation.
2. **Ring-inset, not border** — `ring-1 ring-inset ring-blue-200/60` blends with the tint
3. **Icon on a white-translucent square inside the tint** — gives the icon depth without breaking the color story
4. **Status dot top-right** — confirms color encoding for users who can't perceive the bg tint
5. **ALL-CAPS label with `tracking-[0.14em]`** — matches the meta-label typography from `tokens.md`
6. **Hover = `y: -1` lift, not scale** — premium tells: shadow + 1px rise, never `scale(1.05)`
7. **Count uses `tabular-nums`** — when counts change live, digits don't reflow

## Customization rules

- **Exactly 4 categories.** This is a 2×2 quadrant. 3 = use a row, 5+ = use a list with bars.
- **Color taxonomy is fixed** — see the locked table above. Re-map by semantic role, not by aesthetic preference:
  - blue = new / pending / queued
  - amber = in progress / processing
  - emerald = resolved / success / done
  - rose = error / blocked / needs-attention
- **Tint is `*-50`, ring is `*-200/60`, dot is `*-500`, text is `*-900`** — keep the pattern even when swapping colors
- **Status label is ALWAYS UPPERCASE with letter-spacing 0.14em**
- **Don't add a delta / sparkline inside.** That's the KPI strip's job.

## What NOT to change

- Don't make it 3 columns (loses the quadrant gestalt)
- Don't replace pastel tints with white cards + colored borders (defeats the at-a-glance scan)
- Don't use saturated fills (`bg-blue-500`) — screams "alert", not "summary"
- Don't put count in the same color as the label — count must be `*-900` so eyes land on it first
- Don't use scale-hover. `y: -1` only.
- Don't drop the status dot "because the bg color already shows status" — accessibility/colorblind users need both encodings

## Cross-references

- See `tokens.md` "META LABELS" for the ALL-CAPS letter-spacing pattern
- See `recipes/dashboard-shell.md` "KPI strip" for the metric-with-delta sibling
- See `recipes/dashboard-audit-log.md` — pairs well: StatusQuadrant on top, AuditLog beneath
- See `anti-slop.md` "Saturated status fills" anti-pattern
