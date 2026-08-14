# Flux UI — Implementation Guidance

## Preserve the stack

Before editing:
- inspect package files
- identify framework
- identify styling system
- identify component library
- identify icon library
- identify animation library
- identify existing tokens/theme

Prefer adapting what exists.

Do not migrate styling frameworks or component libraries merely to achieve Flux styling.

## Dependency policy

Do not add a package for an effect that can be implemented cleanly with existing tools or small CSS.

If a motion library already exists, use it consistently.

For React projects:
- existing Motion/Framer Motion: use it for shared layout, orchestration, and springs
- CSS transitions: use for simple hover/focus/color changes
- Web Animations API: acceptable for focused cases

Do not add multiple animation libraries.

## Token strategy

If the project has semantic tokens:
- map Flux concepts onto them
- preserve token names where practical

If the project has only raw values:
- introduce a minimal semantic layer needed for the task
- avoid a massive design-system migration unless requested

If starting new:
- use the provided token template as a base
- adapt accent to the brand/product context

## Component strategy

Prefer:
1. existing project component
2. small variant of an existing primitive
3. new reusable component when repeated or conceptually meaningful
4. one-off markup for truly one-off composition

Do not create abstractions only to make the folder tree look like a design system.

## Animation implementation

Separate:
- state logic
- layout
- animation

Animation must not be required for the state to be understandable.

Avoid expensive continuous effects:
- large blurred layers moving every frame
- huge canvases for trivial decoration
- many independent pointer listeners
- layout-thrashing animations

Prefer transform and opacity for motion.

For pointer-tracking effects:
- scope event handling to the local interactive region
- use CSS variables where practical
- disable or simplify on coarse pointers
- keep repaint area small

## Accessibility

Maintain:
- semantic HTML
- labels
- focus-visible states
- keyboard interaction
- escape behavior for dismissible overlays
- reduced motion
- sensible contrast
- usable touch targets

Never remove focus outlines without providing a replacement.

## Performance

For animated lists:
- avoid animating large numbers of rows simultaneously
- cap stagger
- virtualize large datasets when the project already supports it

For scroll effects:
- avoid synchronous heavy work on scroll
- prefer platform/browser primitives and the existing animation library

For decorative loops:
- pause offscreen when practical
- avoid on battery-sensitive/mobile contexts when value is low

## Responsive implementation

Do not solve responsiveness with arbitrary shrinking.

Instead:
- reduce columns
- collapse side content
- reorder by task priority
- switch dense controls to appropriate mobile patterns
- remove pointer-only effects

## Completion standard

Before finishing UI work:
- inspect responsive states
- verify hover/focus/active/disabled
- verify loading/empty/error when relevant
- verify reduced motion
- check for raw one-off values that should use tokens
- remove unused experiments
- keep code concise and consistent with the repository
