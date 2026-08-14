# Flux UI — Page Patterns

## Product dashboard

Composition:
- compact app shell
- strong page title / context row
- primary scorecard or work area
- supporting panels on a consistent grid
- dense tables/charts below

Use visual hierarchy rather than many card colors.

Motion:
- micro interactions throughout
- Spatial Spring in navigation/tabs
- Data Scan only during data refresh
- Tracking Glow rarely, usually on one interactive feature area

## AI / developer tool

Composition:
- command/search entry is prominent
- workspace is dense but legible
- status/latency/version metadata uses mono
- keyboard shortcuts are visible where helpful
- output and controls are clearly separated

Motion:
- fast response
- streaming state
- shared selection movement
- subtle focus changes

Avoid turning the interface into a sci-fi terminal parody.

## Analytics / data workspace

Composition:
- filters close to the data they affect
- consistent date/range controls
- aligned metric baselines
- charts share visual grammar
- tables support detailed inspection

Motion:
- animate state transitions and hover focus
- avoid dramatic chart intro animations on every filter change

## Settings

Composition:
- narrow readable content column
- sections separated by spacing/dividers more often than nested cards
- labels and descriptions align consistently
- destructive zone separated visually

Motion:
- minimal
- toggles and local feedback only

## Landing page

Flux marketing pages may be more expressive than the product UI.

Suggested rhythm:
1. restrained navigation
2. high-contrast hero
3. one technical visual/interactive centerpiece
4. evidence / product proof
5. feature sections
6. workflow or system explanation
7. final CTA

Use a maximum of a few major visual effects across the whole page.

Hero options:
- technical grid
- data plane
- beam/connection diagram
- interactive product fragment
- subtle particles
- typographic reveal

Do not combine all of them.

## Technical feature section

Prefer:
- one concise claim
- one product/diagram surface
- small supporting details
- visible system metadata

Make the product behavior itself the visual.

## Research / scientific workspace

Composition:
- document/data content dominates
- metadata and provenance remain accessible
- tables/figures use restrained surfaces
- identifiers, sample IDs, units, and timestamps may use mono
- tool controls remain compact

Motion:
- use Data Scan for analysis/result arrival
- preserve static readability for figures and scientific data

## Responsive behavior

Desktop:
- maximize useful density
- avoid oversized empty margins in product UIs

Tablet:
- collapse secondary rails
- keep core task visible
- simplify multi-column scorecards

Mobile:
- prioritize task sequence
- replace hover-only affordances
- avoid motion requiring pointer tracking
- keep controls at accessible touch size
- preserve information hierarchy rather than shrinking desktop layout

## Hierarchy test

At a glance, a user should be able to answer:
1. Where am I?
2. What is the primary task?
3. What changed?
4. What can I act on?
5. What is secondary?

If the answer depends on decorative color, the hierarchy is too weak.
