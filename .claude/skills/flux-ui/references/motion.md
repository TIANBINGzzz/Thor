# Flux UI — Motion Language

Motion is a functional layer, not decoration.

Every animation should communicate at least one of:
- state change
- spatial continuity
- hierarchy
- causality
- progress
- response to user input

If it communicates none of these, remove it.

## Duration tokens

| Token | Duration | Typical use |
|---|---:|---|
| `instant` | 100ms | hover color, tiny feedback |
| `fast` | 160ms | buttons, icons, toggles |
| `normal` | 220ms | tabs, popovers, local panels |
| `slow` | 360ms | dialogs, larger reveals |
| `scene` | 520ms | page/hero composition |

Avoid >900ms UI transitions except deliberate storytelling.

## Easing

Recommended CSS easings:

- Standard: `cubic-bezier(.2,.8,.2,1)`
- Enter: `cubic-bezier(.16,1,.3,1)`
- Exit: `cubic-bezier(.4,0,1,1)`

Use springs for spatial continuity, not for every opacity fade.

Suggested spring starting point for small shared-layout movement:
- stiffness: 380
- damping: 32
- mass: 0.8

For larger panels:
- stiffness: 280
- damping: 30
- mass: 1

Avoid exaggerated bounce.

## Motion hierarchy

### Tier 1 — micro feedback
Use frequently:
- button press
- icon rotation
- toggle
- hover border
- tooltip
- focus state

Amplitude should be tiny:
- scale: usually 0.98–1.01
- translation: usually 1–4px

### Tier 2 — component transitions
Use selectively:
- tabs
- accordion
- popover
- command palette
- dialog
- toast
- expandable card

Typical movement:
- 4–12px
- opacity + transform
- shared position where possible

### Tier 3 — scene motion
Use sparingly:
- page entry
- hero choreography
- feature storytelling
- scroll-driven technical diagrams

A product workspace should usually have less Tier 3 motion than a marketing page.

## Signature motion 1: Tracking Glow

Use on:
- high-value cards
- interactive feature tiles
- technical hero surfaces

Behavior:
1. pointer position controls a radial gradient
2. highlight follows locally
3. edge may brighten near cursor
4. opacity remains low

Constraints:
- glow radius: roughly 180–320px
- accent opacity: generally under 14%
- no persistent bright halo
- disable on touch-only devices if it adds no value

Do not apply Tracking Glow to every card in a dense dashboard.

## Signature motion 2: Data Scan

Use for:
- technical loading
- data refresh
- generated results
- system initialization
- image/data reveal

Behavior:
1. content skeleton or masked surface is visible
2. a thin line/gradient traverses the local region
3. real content resolves progressively
4. animation stops when loading ends

Constraints:
- line should be thin and low-contrast
- no endless scan when data is already loaded
- avoid fake progress claims

## Signature motion 3: Spatial Spring

Use for:
- active nav indicator
- tab underline/background
- selected command row
- segmented control
- filter chip selection

Behavior:
- the indicator moves from the old state to the new state as one continuous object

Prefer shared-layout animation instead of fading one indicator out and another in.

## Hover language

Default card hover:
- border slightly stronger
- surface rises one small visual step
- optional translateY of -1px or -2px
- optional local tracking glow

Default button hover:
- color/surface change
- no dramatic scale-up

Default icon button:
- surface appears or strengthens
- icon may shift/rotate only if the action semantics support it

## Reveal language

For grouped content:
- stagger only when it improves scan order
- typical stagger: 30–60ms
- cap long cascades; do not make users wait for item 20

For text:
- prefer line/block reveal over letter-by-letter animation for product UI
- letter animation is reserved for hero moments

## Scroll motion

Use scroll animation to reinforce:
- progression
- relationship between sections
- technical process
- before/after comparison

Avoid:
- hijacked scrolling
- excessive parallax
- essential content hidden behind long scroll choreography
- motion that interferes with reading

## Loading states

Preferred order:
1. immediate local optimistic state when safe
2. skeleton or reserved layout
3. subtle Data Scan if appropriate
4. progress indication for genuinely long operations

Avoid a generic spinner as the only feedback for complex processes when meaningful progress/status can be shown.

## Reduced motion

Always support `prefers-reduced-motion: reduce`.

Under reduced motion:
- remove nonessential transforms and parallax
- remove continuous decorative loops
- replace shared spring travel with short fades or instant state changes
- preserve state clarity

Never make content inaccessible when motion is disabled.

## Motion quality checklist

Before finishing:
- Does each motion have a reason?
- Is anything moving farther than necessary?
- Do related elements share timing?
- Are exit animations faster than entrances?
- Is interaction responsive under rapid repeated input?
- Does layout remain stable?
- Does reduced motion work?
- Are continuous animations paused when offscreen where practical?
