# redesign.md — Upgrading an Existing UI

**Read this when the user has a UI they want fixed — not a UI they want built from scratch.** The standard `/ui` procedure assumes a greenfield build composed from recipes. Redesign is different: you start with code or a screenshot, audit it, and apply targeted fixes. Same rules, different entry point.

---

## Use this when

- User has existing UI and asks: "fix this", "audit this", "redesign", "make it look better", "this looks AI-generated"
- User links to a live URL or pastes a screenshot
- User points at a file or folder and says "the landing page" / "the dashboard"
- User says "I don't like how this looks" without specifying a recipe to apply

If the user wants a NEW page from nothing, use the standard `SKILL.md` procedure instead.

---

## The 5-step redesign procedure

This replaces Steps 1–5 of the standard build procedure. Rules from `SKILL.md`, `tokens.md`, and `anti-slop.md` still apply at every step.

### Step 1 — AUDIT

Inspect the current state.

- If a live URL is available and Playwright is installed: navigate, take a full-page screenshot, capture the DOM snapshot.
- If only code is provided: read the relevant component files end-to-end. Don't just skim — you need exact `file:line` references.
- If only a screenshot: rely on the visual; flag that you couldn't verify implementation details.

Then scan against the checklists:
- `anti-slop.md` — every banned pattern
- `review.md` — every checklist item
- `tokens.md` — typography size, font stack, color palette, motion preset compliance
- `SKILL.md` — Three Rules (restraint / typography / motion-via-shared-elements)

**Output a numbered list of specific issues** with `file:line` references where possible. Be concrete. "Spacing is off" is useless; "`Hero.tsx:42` uses `py-12` where `py-24` is the standard" is actionable.

### Step 2 — TRIAGE

Bucket every issue into one of three priorities:

- **SHOWSTOPPER** — Anti-slop violations, broken layouts on mobile, dead-space, AI-tells (`<Loader2 />`, "MOST POPULAR" banner, hero >8 words, pure `#fff` background, centered everything).
- **POLISH** — Spacing inconsistencies, weak alignment, headline a bit too small, body copy hierarchy, missing micro-interactions.
- **NICE-TO-HAVE** — Decorative additions, secondary motion, incremental refinements that don't move the needle.

Show the user the triaged list. Get explicit confirmation on priorities before touching code. Don't auto-fix everything — surprise refactors break working features.

### Step 3 — DIAGNOSE

For each SHOWSTOPPER, identify the recipe or rule that prescribes the fix. Be specific:

- "Hero is centered with 6-line copy → replace with `recipes/hero-saas.md` skeleton, cut copy to ≤8 words / ≤3 lines."
- "Features section is 3 equal cards → replace with `recipes/features-bento.md` mixed-size bento."
- "FAQ uses boxy `<Accordion>` → replace with `recipes/faq-pillrows.md` thin-pill rows."
- "Loading state uses `<Loader2 />` → replace with skeleton component matching the loaded layout."

The recipe is the floor — adapt copy, accent, and content, but keep the structure.

### Step 4 — APPLY

Apply fixes incrementally. One SHOWSTOPPER at a time, in priority order. After each fix:

- Show before/after — either as a diff snippet or, if Playwright is wired, a screenshot pair.
- Confirm no regressions in adjacent sections.
- Don't refactor working code "while you're in there". Scope creep is how redesigns get rejected.

If a fix requires installing a new dependency (e.g., Framer Motion isn't in the project), tell the user before installing.

### Step 5 — VERIFY

Run through `review.md` checklist end-to-end. Confirm:

- Every SHOWSTOPPER from Step 2 is resolved.
- No POLISH item silently regressed.
- The Three Rules from `SKILL.md` are now satisfied.

State which checklist items passed in your final message — same as Step 5 of the standard procedure.

---

## Common audit findings — the top 10

These are the issues you will find on >70% of audits. Scan for them first.

1. **`h-screen` on hero.** Mobile bug — iOS Safari URL bar pushes content offscreen. Replace with `min-h-[100dvh]` or remove entirely.
2. **Centered everything.** Every section uses `text-center` and `mx-auto`. Replace with the three forced alternatives: 50/50 split, left-text + right-asset, or asymmetric whitespace.
3. **3-equal-card features grid.** The single most common AI tell. Replace with bento, 2-column zig-zag, asymmetric split, or horizontal scroll gallery.
4. **Hero copy >8 words OR >3 lines.** Cut the headline. Move context to subtext. Widen the container or reduce font-size via `clamp()` if it still wraps.
5. **`<Loader2 />` spinner anywhere.** Replace with skeleton screens that mirror the loaded layout.
6. **Boxy `<Accordion>` FAQ.** Replace with `recipes/faq-pillrows.md` — thin pill rows, never card-bordered accordions.
7. **Pure `#ffffff` background.** Replace with `oklch(98% 0.005 90)` (warm) or `oklch(98% 0.002 250)` (cool) per `tokens.md`.
8. **Default "MOST POPULAR" pricing banner.** Replace with subtle "Currently Popular" pill + accent dot inside the card border.
9. **Missing dual-CTA pattern in hero.** Add the filled + outlined pill pair. Never one button alone, never two same-style buttons.
10. **Glassmorphism on cards.** Glass belongs on the nav bar (sticky, behind-blur). On cards it looks like 2021 Dribbble. Use solid `--bg-elevated` with subtle border instead.

---

## What to AVOID during redesign

- **Refactoring code that's working fine "while you're in there".** Scope discipline. If it isn't on the audit list, leave it.
- **Replacing component libraries** (shadcn → custom, MUI → Tailwind, etc.) unless the user explicitly asks. That's a migration, not a redesign.
- **Changing brand colors** without permission. Even if the existing accent is "AI purple", confirm before swapping.
- **Rewriting copy** beyond what the hero rule requires (≤8 words / ≤3 lines). Marketing copy is the user's domain — don't invent product positioning.
- **Adding new sections** the user didn't ask for. Empty space is the design.
- **Migrating to a different framework** (Vite → Next, Pages → App Router) — that's a separate conversation.

---

## Output format

1. **Audit list first** — numbered, with `file:line` refs and severity tags.
2. **Wait for user confirmation** on priorities before applying any change.
3. **Apply fixes in priority order**, one SHOWSTOPPER at a time, with before/after.
4. **Final review** with `review.md` checklist — list which items passed.

Never apply fixes silently. Never bundle multiple SHOWSTOPPERS into one diff without showing each one.

---

## Cross-references

- `SKILL.md` — the standard build procedure (use that for greenfield builds)
- `anti-slop.md` — the banned patterns the audit looks for
- `review.md` — the pre-ship checklist used in Step 5
- `tokens.md` — palettes, fonts, motion presets the redesign must conform to
- `architecture.md` — relevant if the project is Next.js App Router
