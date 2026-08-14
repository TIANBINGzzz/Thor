# Flux UI — Anti-patterns

The following weaken the Flux identity.

## Visual

Avoid:
- blue + purple + cyan + pink gradients used together without meaning
- gradient text on routine headings
- neon glow around every surface
- thick luminous borders
- heavy glassmorphism across the whole page
- excessive backdrop blur
- giant rounded rectangles everywhere
- every section placed in a card
- repeated decorative grid backgrounds
- random noise textures
- fake terminal styling for ordinary product UI
- decorative 3D objects unrelated to product behavior
- inconsistent icon families
- excessive pills
- too many badge colors

## Motion

Avoid:
- every element animating on mount
- long stagger cascades
- bounce on routine controls
- scale-up hover on every card
- continuous shimmer after loading has completed
- parallax on reading-heavy sections
- scroll hijacking
- motion that delays interaction
- looping effects that compete with live data
- letter-by-letter animation for normal UI copy

## Typography

Avoid:
- mono font for all text
- uppercase navigation everywhere
- extremely low contrast body text
- huge marketing headings inside product workspaces
- many unrelated font sizes

## Layout

Avoid:
- excessive empty space that reduces product utility
- arbitrary offsets used only to look experimental
- misaligned card edges and chart baselines
- deeply nested panels
- floating controls without clear anchoring
- desktop layouts merely scaled down for mobile

## AI-generated UI clichés

Actively remove:
- generic glowing orb
- purple gradient mesh behind every hero
- four identical feature cards with icon circles
- empty metrics added only to fill space
- fake customer logos
- fake activity feeds
- placeholder charts presented as product data
- unnecessary "AI-powered" badges
- decorative command palettes that do not function

## Rule of restraint

When two visual effects compete, keep the one that carries more information.

When an effect is memorable but the interface becomes less legible, remove the effect.

Flux should feel advanced because of precision and behavior, not because it contains more effects.
