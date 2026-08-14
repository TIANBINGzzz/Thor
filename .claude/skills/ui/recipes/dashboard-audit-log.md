# recipes/dashboard-audit-log.md — Audit Log with Diff Rows

**Adapted from mxkaske / OpenStatus.** A table of events where each row expands inline to reveal a git-style diff (red strikethrough OLD / green plus NEW) plus structured ENTRY metadata. Filter chips above. Used for compliance, agent activity, "track every action" surfaces.

## When to use

- Audit log / activity log / event history
- Agent action log ("the AI did X")
- Compliance / SOC 2 / GDPR-required change tracking
- Webhook / integration delivery log
- Any "what changed and who did it" surface where users will want detail

**Don't use** for: notification feeds (use a list, not a table), comments (use a thread).

## Structure

- **Filter row** — pill-shaped chips for actor / action / resource / time-range
- **Table head** — Timestamp / Actor / Action / Resource / Status (right-aligned)
- **Table body** — clickable rows; clicked row expands a panel with ENTRY metadata + CHANGES diff
- **Action chips** color-coded by verb family: `delete` → rose, `create` → emerald, `update` → indigo, `read` → neutral
- **Diff lines** — `-` red strikethrough for OLD, `+` green for NEW, monospace, line-numbered

## Code

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import { ChevronRight, Filter, X } from "lucide-react";

const SPRING = { type: "spring" as const, stiffness: 320, damping: 30 };

const ACTION_COLORS: Record<string, string> = {
  create: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  update: "bg-indigo-50  text-indigo-700  ring-indigo-600/20",
  delete: "bg-rose-50    text-rose-700    ring-rose-600/20",
  read:   "bg-neutral-100 text-neutral-700 ring-neutral-600/20",
};

function actionFamily(action: string) {
  if (action.endsWith(".create")) return "create";
  if (action.endsWith(".update")) return "update";
  if (action.endsWith(".delete")) return "delete";
  return "read";
}

export type AuditEvent = {
  id: string;
  timestamp: string;
  actor: { name: string; type: "human" | "agent" };
  action: string;          // e.g. "page.delete", "monitor.update"
  resource: string;        // e.g. "Status Page · Marketing"
  status: "ok" | "fail";
  changes?: { field: string; old: string; new: string }[];
  entry?: Record<string, string>;
};

export function AuditLog({ events }: { events: AuditEvent[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const [filters, setFilters] = useState<string[]>(["page.*", "last 7d"]);

  return (
    <div className="rounded-2xl border border-black/8 bg-[var(--bg-elevated)] overflow-hidden">
      {/* FILTER ROW */}
      <div className="flex items-center gap-2 px-5 py-3 border-b border-black/8">
        <Filter className="size-4 text-[var(--text-muted)]" />
        {filters.map((f) => (
          <button
            key={f}
            onClick={() => setFilters((cur) => cur.filter((x) => x !== f))}
            className="inline-flex items-center gap-1.5 rounded-full bg-neutral-100 px-2.5 py-1 text-xs font-medium hover:bg-neutral-200"
          >
            {f}
            <X className="size-3 opacity-60" />
          </button>
        ))}
        <button className="ml-auto text-xs font-medium text-[var(--text-muted)] hover:text-[var(--text)]">
          Add filter
        </button>
      </div>

      {/* TABLE */}
      <div className="divide-y divide-black/8">
        {/* head */}
        <div className="grid grid-cols-[160px_minmax(120px,1fr)_140px_minmax(160px,1.5fr)_80px_24px] items-center gap-4 px-5 py-2.5 text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
          <div>Timestamp</div>
          <div>Actor</div>
          <div>Action</div>
          <div>Resource</div>
          <div className="text-right">Status</div>
          <div />
        </div>

        {/* rows */}
        {events.map((e) => {
          const isOpen = open === e.id;
          const family = actionFamily(e.action);
          return (
            <div key={e.id}>
              <button
                onClick={() => setOpen(isOpen ? null : e.id)}
                className={`w-full grid grid-cols-[160px_minmax(120px,1fr)_140px_minmax(160px,1.5fr)_80px_24px] items-center gap-4 px-5 py-3 text-sm text-left hover:bg-neutral-50/60 ${
                  isOpen ? "bg-neutral-50/60" : ""
                }`}
              >
                <div className="font-mono text-xs tabular-nums text-[var(--text-muted)]">
                  {e.timestamp}
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`size-1.5 rounded-full ${
                      e.actor.type === "agent" ? "bg-indigo-500" : "bg-emerald-500"
                    }`}
                    aria-hidden
                  />
                  <span className="truncate">{e.actor.name}</span>
                </div>
                <div>
                  <span
                    className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${ACTION_COLORS[family]}`}
                  >
                    {e.action}
                  </span>
                </div>
                <div className="truncate text-[var(--text)]">{e.resource}</div>
                <div className="text-right">
                  <span
                    className={`inline-flex size-1.5 rounded-full ${
                      e.status === "ok" ? "bg-emerald-500" : "bg-rose-500"
                    }`}
                    aria-hidden
                  />
                </div>
                <motion.div animate={{ rotate: isOpen ? 90 : 0 }} transition={SPRING}>
                  <ChevronRight className="size-4 text-[var(--text-muted)]" />
                </motion.div>
              </button>

              {/* EXPANDED PANEL */}
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    key="panel"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={SPRING}
                    className="overflow-hidden bg-neutral-50/40"
                  >
                    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6 px-5 py-5 border-t border-black/8">
                      {/* CHANGES (left, larger) */}
                      <div>
                        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-muted)] mb-2">
                          Changes
                        </div>
                        {e.changes && e.changes.length > 0 ? (
                          <div className="rounded-lg border border-black/8 bg-white overflow-hidden font-mono text-xs">
                            {e.changes.map((c, i) => (
                              <div key={i} className="border-b border-black/5 last:border-b-0">
                                <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)] bg-neutral-50">
                                  {c.field}
                                </div>
                                <div className="px-3 py-1 bg-rose-50/70 text-rose-700">
                                  <span className="select-none opacity-60">- </span>
                                  <span className="line-through decoration-rose-400/60">
                                    {c.old}
                                  </span>
                                </div>
                                <div className="px-3 py-1 bg-emerald-50/70 text-emerald-700">
                                  <span className="select-none opacity-60">+ </span>
                                  <span>{c.new}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-xs text-[var(--text-muted)] italic">
                            No field changes — action did not mutate data.
                          </div>
                        )}
                      </div>

                      {/* ENTRY METADATA (right, narrower) */}
                      <div>
                        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-muted)] mb-2">
                          Entry
                        </div>
                        <dl className="rounded-lg border border-black/8 bg-white divide-y divide-black/5 text-xs">
                          {Object.entries(e.entry ?? {}).map(([k, v]) => (
                            <div
                              key={k}
                              className="grid grid-cols-[88px_1fr] gap-3 px-3 py-1.5"
                            >
                              <dt className="text-[var(--text-muted)] truncate">{k}</dt>
                              <dd className="font-mono tabular-nums truncate">{v}</dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

## What makes it premium

1. **Action chips color-coded by verb family** (not random) — users learn "rose = destructive" once
2. **Single-row expand** — only one row open at a time keeps the page readable
3. **Diff is real diff syntax** — `-` and `+` prefixes, monospace, line-numbered field labels
4. **ENTRY column is metadata, not duplicated** — request-id, IP, user-agent, never the diff data
5. **Status dot, not "Success" / "Failed" badge** — quieter at scale
6. **Filter chips with X dismiss** — the chip IS the dismiss button

## Customization rules

- **Color families are fixed:** create=emerald, update=indigo, delete=rose, read=neutral. Don't reassign.
- **Action format is `resource.verb`** (period-separated, lowercase) — `page.delete`, `monitor.update`. Never SHOUT-CASE.
- **Timestamps are mono + tabular-nums** — they must align vertically
- **Actor dot color**: indigo for agent, emerald for human
- **Empty changes block** says "No field changes" — don't hide the section

## What NOT to change

- Don't use a `<Sheet>` or modal for the expansion — must be inline expand-row
- Don't replace strikethrough with a side-by-side two-column diff (loses the git-feel)
- Don't put both diff and metadata in one column — they're parallel concerns
- Don't add a "Re-run" or "Revert" button in the row — this is read-only history
- Don't use cubic-bezier on the chevron rotate — must be spring

## Cross-references

- See `tokens.md` semantic colors (emerald/rose/indigo) for action chip ring colors
- See `recipes/dashboard-shell.md` — this recipe lives INSIDE the dashboard shell content area
- See `recipes/dashboard-status-quadrant.md` — pairs well as a top status overview above the log
- See `anti-slop.md` "Status as text-badge instead of dot" anti-pattern
