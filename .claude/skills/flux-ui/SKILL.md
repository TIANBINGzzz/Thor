---
name: flux-ui
description: Design, redesign, or implement product interfaces using the Flux UI design language: dark-first minimal technology aesthetics, precise typography and spacing, restrained depth, one accent color, dense but calm information hierarchy, and purposeful high-quality motion. Use for dashboards, SaaS apps, AI tools, developer tools, data products, landing pages, component libraries, design-system work, or requests for a clean futuristic/technical UI.
---

# Flux UI

Build interfaces that feel precise, calm, technical, and alive.

Flux UI is not cyberpunk. It avoids visual noise, decorative neon, excessive glassmorphism, random gradients, and motion without purpose.

## Core rules

1. Use a dark-first neutral foundation with one primary accent.
2. Create hierarchy with spacing, typography, borders, surface elevation, and motion before adding decoration.
3. Keep geometry precise: consistent grid, radii, icon sizes, and alignment.
4. Use sans-serif typography for interface text and mono typography selectively for data, status, identifiers, shortcuts, versions, and measurements.
5. Motion should explain state, continuity, hierarchy, or causality.
6. Prefer subtle local effects over large global effects.
7. Preserve accessibility: visible focus states, sufficient contrast, keyboard behavior, and reduced-motion support.
8. Reuse existing project primitives before introducing new abstractions or dependencies.
9. Do not redesign unrelated areas unless the task requires it.
10. Do not add placeholder copy, demo panels, explanatory banners, or decorative controls that the product does not need.

## Workflow

When asked to create or modify UI:

1. Inspect the existing stack, layout conventions, component primitives, design tokens, icon library, and animation library.
2. Preserve the project's framework and architecture unless the user asks for a migration.
3. Identify the primary user task and the dominant information hierarchy.
4. Read the relevant Flux references below before implementing.
5. Establish or map design tokens before styling many components.
6. Build from primitives to composed patterns; avoid one-off values.
7. Add motion after layout and states are correct.
8. Implement responsive, hover, focus-visible, active, disabled, loading, empty, and error states where relevant.
9. Respect `prefers-reduced-motion`.
10. Review the result against the anti-patterns before finishing.

## Design priority

When tradeoffs arise, prioritize in this order:

1. Usability and information clarity
2. Consistency with the existing product
3. Flux UI visual language
4. Motion quality
5. Decorative novelty

## Signature language

Use these motifs selectively, not everywhere:

- **Tracking Glow**: a faint pointer-following radial highlight on high-value interactive surfaces.
- **Data Scan**: a thin scan/reveal treatment for technical loading or data arrival.
- **Spatial Spring**: shared-position motion for active tabs, selections, segmented controls, and navigation indicators.

A page normally needs zero to two signature motifs. Three is reserved for highly expressive surfaces such as a product landing hero.

## Required references

- Read [references/design-tokens.md](references/design-tokens.md) when choosing color, spacing, radius, type, border, shadow, or layout values.
- Read [references/motion.md](references/motion.md) for transitions, springs, reveals, hover behavior, and reduced motion.
- Read [references/components.md](references/components.md) when creating or restyling reusable UI components.
- Read [references/patterns.md](references/patterns.md) for page-level composition.
- Read [references/implementation.md](references/implementation.md) before adding dependencies or changing an existing frontend architecture.
- Read [references/anti-patterns.md](references/anti-patterns.md) before final visual polish.

## Optional starter tokens

For a new web project without an established token system, adapt [templates/flux-tokens.css](templates/flux-tokens.css).

Do not blindly overwrite an existing design system. Map existing semantic tokens to Flux principles first.
