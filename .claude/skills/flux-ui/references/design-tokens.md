# Flux UI — Design Tokens

Use semantic tokens. Avoid scattering raw values through components.

## Color system

Flux is dark-first. The default neutral palette is slightly cool but should still read as near-neutral.

### Core surfaces

| Token | Default | Use |
|---|---|---|
| `canvas` | `#08090A` | App/page background |
| `surface-1` | `#0D0F11` | Primary panels |
| `surface-2` | `#131519` | Raised/interacting panels |
| `surface-3` | `#191C21` | Strong hover/selected surfaces |
| `surface-inverse` | `#F5F7FA` | Rare inverted element |

### Text

| Token | Default |
|---|---|
| `text-primary` | `rgba(255,255,255,.92)` |
| `text-secondary` | `rgba(255,255,255,.62)` |
| `text-tertiary` | `rgba(255,255,255,.40)` |
| `text-disabled` | `rgba(255,255,255,.24)` |

### Borders

| Token | Default |
|---|---|
| `border-subtle` | `rgba(255,255,255,.06)` |
| `border-default` | `rgba(255,255,255,.09)` |
| `border-strong` | `rgba(255,255,255,.14)` |
| `border-focus` | accent at ~70% opacity |

### Accent

Use one product accent across a view.

Default:
- `accent`: `#5B8CFF`
- `accent-hover`: `#74A0FF`
- `accent-soft`: `rgba(91,140,255,.12)`
- `accent-border`: `rgba(91,140,255,.32)`

An existing brand color should replace the default accent. Do not introduce a second decorative accent without a semantic reason.

### Semantic colors

Success, warning, danger, and info are functional colors, not decorative accents. Keep them localized to status communication.

Do not tint large background regions red/green/yellow unless the state is critical.

## Typography

Preferred UI stacks:
- Sans: `Geist`, `Inter`, system sans fallback
- Mono: `Geist Mono`, `SFMono-Regular`, `ui-monospace`

Use mono selectively for:
- IDs
- timestamps
- key commands
- versions
- measurements
- latency
- code-like values
- compact status labels

Do not set entire paragraphs or navigation in mono.

### Type scale

Prefer a compact product scale:

| Role | Size | Line height | Weight |
|---|---:|---:|---:|
| Display | 48–64 | 1.00–1.05 | 500–600 |
| H1 | 32–40 | 1.10 | 550–650 |
| H2 | 24–28 | 1.15 | 550–650 |
| H3 | 18–20 | 1.25 | 550–650 |
| Body | 14–16 | 1.45–1.60 | 400–450 |
| UI | 13–14 | 1.30–1.45 | 450–550 |
| Caption | 11–12 | 1.35–1.50 | 450–550 |
| Mono data | 11–14 | 1.30–1.45 | 450–550 |

Prefer sentence case. Avoid excessive uppercase. Uppercase is acceptable for very small technical labels with increased tracking.

## Spacing

Use a 4px base.

Preferred steps:
`4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96`

Common product defaults:
- icon/text gap: 6–8
- inline control gap: 8
- compact group gap: 12
- component internal padding: 12–16
- card padding: 16–24
- section gap: 32–48
- page horizontal padding: 20–32 desktop, 16–20 mobile

Avoid arbitrary spacing such as 13px, 17px, 29px unless matching an existing system.

## Radius

Flux uses restrained rounding.

Preferred:
- `4px`: tiny controls, code chips
- `6px`: compact controls
- `8px`: buttons, inputs
- `10px`: popovers, compact cards
- `12px`: standard cards/dialog sections
- `16px`: large feature surfaces
- pill: only tags, segmented elements, status chips, or truly capsule-shaped controls

Avoid 20–32px radii on every panel.

## Borders and depth

Default depth comes from:
1. background contrast
2. 1px border
3. local highlight
4. restrained shadow

Recommended panel edge:
`1px solid rgba(255,255,255,.08)`

Optional top-edge highlight:
`inset 0 1px 0 rgba(255,255,255,.03)`

Avoid thick outlines and large diffuse glow around normal cards.

## Shadows

Dark UI shadows should be subtle and structural.

Examples:
- floating menu: `0 12px 40px rgba(0,0,0,.35)`
- modal: `0 24px 80px rgba(0,0,0,.50)`
- small raised control: `0 4px 16px rgba(0,0,0,.22)`

Do not make glow the default shadow.

## Layout

Use a strong grid:
- marketing: 12 columns
- product workspace: shell + content grid
- content max width: typically 1120–1280px
- text-heavy reading width: 640–760px

Align headings, cards, chart axes, tables, and metadata to shared vertical lines.

Prefer asymmetric composition only when it improves hierarchy.

## Iconography

- Use one icon family per product.
- Standard icon size: 16px.
- Dense UI: 14px.
- Emphasis: 18–20px.
- Stroke weight should remain visually consistent.
- Do not mix emoji with product icons unless the product explicitly uses emoji as content.

## Data visualization

Favor:
- neutral grid/axes
- one accent series for focus
- muted secondary series
- thin strokes
- direct labels where practical
- subtle hover crosshair/tooltips

Do not make every data series neon.
