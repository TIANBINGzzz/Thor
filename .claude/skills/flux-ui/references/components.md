# Flux UI — Component Language

Components should feel precise, low-noise, and state-rich.

## Buttons

Primary:
- accent fill
- high-contrast label
- 8px radius
- compact height, typically 32–40px
- minimal shadow
- fast hover/press response

Secondary:
- neutral surface
- subtle border
- no accent unless active

Ghost:
- transparent until hover
- use for toolbars and low-priority actions

Rules:
- one clear primary action per local region
- avoid gradient-filled buttons by default
- do not animate button labels unless communicating a state transition
- loading state should preserve button width where possible

## Inputs

- 8px radius
- neutral surface
- subtle border
- focus state uses accent border/ring without large glow
- labels are visible; placeholders do not replace labels when context is ambiguous
- errors use localized semantic styling

Search/command inputs may use mono hints for keyboard shortcuts.

## Cards

Default card:
- `surface-1`
- 1px subtle border
- 10–12px radius
- 16–24px padding

Cards should exist because they group related information, not merely to put a rectangle around everything.

Interactive cards may add:
- stronger border on hover
- tiny elevation
- Tracking Glow for important surfaces

Avoid nested card-on-card-on-card layouts.

## Tabs

Preferred:
- compact text
- strong active contrast
- Spatial Spring indicator/background
- inactive states remain readable
- keyboard navigation preserved

Do not animate each label independently when one shared indicator can communicate selection.

## Segmented controls

Use for 2–5 mutually exclusive modes.

- neutral track
- selected element has a shared moving surface
- minimal border
- no oversized pill unless dimensions naturally create one

## Badges and status

Badges communicate compact metadata.

Use mono when displaying:
- version
- build
- environment
- latency
- ID

Status color should be semantic and localized. Do not use an accent badge merely for decoration.

## Tables

Flux tables are dense but calm.

- 36–44px row height for product UI
- muted dividers
- numeric columns aligned consistently
- mono for technical identifiers or measurements
- row hover is subtle
- sticky headers only when useful
- selected state uses soft accent, not bright fill

Actions appear on hover only when discoverability remains adequate.

## Command palette

A signature Flux pattern.

Structure:
- search field
- grouped results
- keyboard shortcut hints
- selected row with Spatial Spring or stable selection surface
- secondary metadata muted
- fast open/close

The palette should feel like a tool, not a modal form.

## Dialogs

- clear title and short supporting text
- restrained radius, typically 12–16px
- strong backdrop separation without excessive blur
- enter slightly slower than exit
- focus trap and Escape behavior
- destructive actions clearly distinguished

Avoid huge center modals for small choices; use popovers or sheets when appropriate.

## Popovers and menus

- 8–12px radius
- dense spacing
- subtle border
- strong shadow only because they float above content
- 160–220ms entrance
- keyboard states required

## Tooltips

- concise
- near-instant
- visually quiet
- do not put essential multi-step instructions in tooltips

## Toasts

Use for transient confirmation or recoverable status.

- compact
- no oversized iconography
- action only when useful
- avoid stacking many persistent toasts

## Skeletons

Skeleton geometry should match final content.

Optional Data Scan may pass through the skeleton or local loading region.

Avoid pulsing the entire screen.

## Metrics / stat blocks

Preferred structure:
- small muted label
- prominent value
- compact delta/trend
- optional sparkline
- mono value when it strengthens technical character

Do not make every metric a separate oversized card if they belong to one scorecard.

## Charts

- thin axes/grid
- one focus series
- restrained supporting series
- tooltips aligned to data
- smooth but quick hover transitions
- animation should not delay reading values

## Navigation

Side navigation:
- compact
- strong selected state
- muted inactive items
- mono may be used for tiny section labels, not all navigation

Top navigation:
- low visual weight
- allow product content to dominate

## Empty states

Keep them useful:
- explain what is empty
- provide one meaningful next action
- illustration is optional and should remain technical/minimal

Do not fill empty states with generic marketing copy.

## AI / generated-content surfaces

Communicate system state clearly:
- queued
- thinking/processing
- streaming
- complete
- error

Use motion to show progress, not to imply certainty.

Generated content should remain readable while streaming. Avoid flashy token-by-token effects.
