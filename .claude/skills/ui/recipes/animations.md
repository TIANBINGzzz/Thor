# recipes/animations.md — Animations Library

**Curated CSS animations from owner. Style: transitions.dev — clean, reduced-motion-aware, custom cubic-bezier eases.**

Use these instead of inventing your own. Drop the CSS into your project's global stylesheet (or scoped via CSS modules), then add the class names to elements as documented.

**All animations:**
- Use custom cubic-bezier easings (premium feel, not stock `ease-in-out`)
- Respect `prefers-reduced-motion: reduce`
- GPU-friendly (transform / opacity / filter only — never width/height/top/left)
- Have CSS custom property hooks so you can adjust duration / distance / direction without rewriting

---

## 1. Card resize

**When to use:** Any element whose `width` or `height` changes (open/close states, grow/shrink, expand panels). Direct CSS sizing transitions — sister to Framer Motion's `layout` prop for non-React contexts.

```css
:root {
  --resize-dur: 300ms;
  --resize-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-resize {
  transition:
    width  var(--resize-dur) var(--resize-ease),
    height var(--resize-dur) var(--resize-ease);
  will-change: width, height;
}

@media (prefers-reduced-motion: reduce) {
  .t-resize { transition: none !important; }
}
```

```html
<div class="t-resize">…</div>
<!-- Toggle a state class like .is-small to change width/height — transition fires automatically -->
```

> **Note:** This is one of the few cases where animating `width`/`height` is OK because it's a deliberate, contained transition (not part of an entrance/scroll animation). For continuous animations, still use `transform: scale()`.

---

## 2. Number pop-in (with stagger + blur)

**When to use:** Stat counters, balance reveals, hero number entrance, KPI strip animations. Each digit pops in independently with a slight stagger.

```css
:root {
  --digit-dur: 500ms;
  --digit-distance: 8px;
  --digit-stagger: 70ms;
  --digit-blur: 2px;
  --digit-ease: cubic-bezier(0.34, 1.45, 0.64, 1);  /* spring-like overshoot */
  --digit-dir-x: 0;
  --digit-dir-y: 1;  /* enter from below */
}

@keyframes t-digit-pop-in {
  0%   {
    transform: translate(
      calc(var(--digit-distance) * var(--digit-dir-x)),
      calc(var(--digit-distance) * var(--digit-dir-y))
    );
    opacity: 0;
    filter: blur(var(--digit-blur));
  }
  100% { transform: translate(0, 0); opacity: 1; filter: blur(0); }
}

.t-digit-group {
  display: inline-flex;
  align-items: baseline;
}
.t-digit {
  display: inline-block;
  will-change: transform, opacity, filter;
}
.t-digit-group.is-animating .t-digit {
  animation: t-digit-pop-in var(--digit-dur) var(--digit-ease) both;
}
.t-digit-group.is-animating .t-digit[data-stagger="1"] {
  animation-delay: var(--digit-stagger);
}
.t-digit-group.is-animating .t-digit[data-stagger="2"] {
  animation-delay: calc(var(--digit-stagger) * 2);
}

@media (prefers-reduced-motion: reduce) {
  .t-digit-group .t-digit { animation: none !important; }
}
```

```html
<span class="t-digit-group is-animating">
  <span class="t-digit">1</span>
  <span class="t-digit">2</span>
  <span class="t-digit" data-stagger="1">.</span>
  <span class="t-digit" data-stagger="2">3</span>
</span>
```

**To replay:**
1. Remove `.is-animating`
2. Re-render digits (or swap text)
3. Force a reflow (e.g., `void el.offsetWidth`)
4. Re-add `.is-animating`

**Direction control:**
- `--digit-dir-y: 1` enters from below (default)
- `--digit-dir-y: -1` enters from above
- `--digit-dir-x: 1` enters from right
- `--digit-dir-x: -1` enters from left

---

## 3. Notification badge (slide-in + pop)

**When to use:** Bell-icon notification dot, cart-count badge, status indicator that appears/disappears as state changes. Badge slides into anchor position then pops the dot — trigger element stays put.

```css
:root {
  --badge-slide-dur: 260ms;
  --badge-pop-dur: 500ms;
  --badge-pop-close-dur: 180ms;
  --badge-fade-dur: 400ms;
  --badge-fade-close-dur: 180ms;
  --badge-blur: 2px;
  --badge-offset-x: -8.2px;
  --badge-offset-y: 12.4px;
  --badge-slide-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --badge-pop-ease: cubic-bezier(0.34, 1.36, 0.64, 1);
  --badge-close-ease: cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes t-badge-slide-in {
  from { transform: translate(var(--badge-offset-x), var(--badge-offset-y)); }
  to   { transform: translate(0, 0); }
}

.t-badge {
  position: absolute;
  top: -6px;
  right: -8px;
  pointer-events: none;
  will-change: transform;
}
.t-badge[data-open="true"] {
  animation: t-badge-slide-in var(--badge-slide-dur) var(--badge-slide-ease);
}

.t-badge-dot {
  display: block;
  transform-origin: center;
  transform: scale(1);
  opacity: 1;
  filter: blur(0);
  transition:
    transform var(--badge-pop-dur)  var(--badge-pop-ease),
    opacity   var(--badge-fade-dur) var(--badge-pop-ease),
    filter    var(--badge-pop-dur)  var(--badge-pop-ease);
  will-change: transform, opacity, filter;
}
.t-badge[data-open="false"] .t-badge-dot {
  transform: scale(0);
  opacity: 0;
  filter: blur(var(--badge-blur));
  transition:
    transform var(--badge-pop-close-dur)  var(--badge-close-ease),
    opacity   var(--badge-fade-close-dur) var(--badge-close-ease),
    filter    var(--badge-pop-close-dur)  var(--badge-close-ease);
}

@media (prefers-reduced-motion: reduce) {
  .t-badge, .t-badge-dot { animation: none !important; transition: none !important; }
}
```

```html
<button class="your-trigger" style="position: relative">
  <BellIcon />
  <span class="t-badge" data-open="false">
    <span class="t-badge-dot">1</span>
  </span>
</button>
<!-- Toggle data-open="true" / "false" via state -->
```

---

## 4. Text states swap (JS-driven)

**When to use:** Button label changes during async action (Sign up → Sending… → Sent ✓), status text rotation, dynamic headline changes. Old text exits up + blurs, new text enters from below.

```css
:root {
  --text-swap-dur: 200ms;
  --text-swap-translate-y: 8px;
  --text-swap-blur: 2px;
  --text-swap-ease: ease-out;
}

.t-text-swap {
  display: inline-block;
  transform: translateY(0);
  filter: blur(0);
  opacity: 1;
  transition:
    transform var(--text-swap-dur) var(--text-swap-ease),
    filter    var(--text-swap-dur) var(--text-swap-ease),
    opacity   var(--text-swap-dur) var(--text-swap-ease);
  will-change: transform, filter, opacity;
}
.t-text-swap.is-exit {
  transform: translateY(calc(var(--text-swap-translate-y) * -1));
  filter: blur(var(--text-swap-blur));
  opacity: 0;
}
.t-text-swap.is-enter-start {
  transform: translateY(var(--text-swap-translate-y));
  filter: blur(var(--text-swap-blur));
  opacity: 0;
  transition: none;
}

@media (prefers-reduced-motion: reduce) {
  .t-text-swap { transition: none !important; }
}
```

**JS sequence (3 phases):**
```js
async function swapText(el, newText) {
  // 1. Exit old
  el.classList.add('is-exit');
  await new Promise(r => setTimeout(r, 200)); // --text-swap-dur

  // 2. Swap text + jump to enter-start position
  el.textContent = newText;
  el.classList.remove('is-exit');
  el.classList.add('is-enter-start');

  // 3. Force reflow, then animate to rest
  void el.offsetWidth;
  el.classList.remove('is-enter-start');
}
```

---

## 5. Menu dropdown (scale + fade with origin presets)

**When to use:** Menus, popovers, dropdown-menus, command palettes. Origin-aware so it scales OUT FROM the trigger, not from center.

```css
:root {
  --dropdown-open-dur: 250ms;
  --dropdown-close-dur: 150ms;
  --dropdown-pre-scale: 0.97;
  --dropdown-closing-scale: 0.99;
  --dropdown-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-dropdown {
  transform-origin: top left;
  transform: scale(var(--dropdown-pre-scale));
  opacity: 0;
  pointer-events: none;
  transition:
    transform var(--dropdown-open-dur) var(--dropdown-ease),
    opacity   var(--dropdown-open-dur) var(--dropdown-ease);
  will-change: transform, opacity;
}
.t-dropdown[data-origin="top-right"]     { transform-origin: top right; }
.t-dropdown[data-origin="top-center"]    { transform-origin: top center; }
.t-dropdown[data-origin="bottom-left"]   { transform-origin: bottom left; }
.t-dropdown[data-origin="bottom-center"] { transform-origin: bottom center; }
.t-dropdown[data-origin="bottom-right"]  { transform-origin: bottom right; }

.t-dropdown.is-open {
  transform: scale(1);
  opacity: 1;
  pointer-events: auto;
}
.t-dropdown.is-closing {
  transform: scale(var(--dropdown-closing-scale));
  opacity: 0;
  pointer-events: none;
  transition:
    transform var(--dropdown-close-dur) var(--dropdown-ease),
    opacity   var(--dropdown-close-dur) var(--dropdown-ease);
}

@media (prefers-reduced-motion: reduce) {
  .t-dropdown { transition: none !important; }
}
```

```html
<div class="t-dropdown" data-origin="top-center">
  <!-- menu items -->
</div>
<!-- Toggle .is-open. On close: swap .is-open → .is-closing, then remove after 150ms. -->
```

---

## 6. Modal open / close (scale up from 0.96)

**When to use:** Standard modals, dialogs, sheets. Subtle scale-up on entrance, not the cheap "pop big".

```css
:root {
  --modal-open-dur: 250ms;
  --modal-close-dur: 150ms;
  --modal-scale: 0.96;
  --modal-scale-close: 0.96;
  --modal-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-modal {
  transform-origin: center;
  transform: scale(var(--modal-scale));
  opacity: 0;
  pointer-events: none;
  transition:
    transform var(--modal-open-dur) var(--modal-ease),
    opacity   var(--modal-open-dur) var(--modal-ease);
  will-change: transform, opacity;
}
.t-modal.is-open {
  transform: scale(1);
  opacity: 1;
  pointer-events: auto;
}
.t-modal.is-closing {
  transform: scale(var(--modal-scale-close));
  opacity: 0;
  pointer-events: none;
  transition:
    transform var(--modal-close-dur) var(--modal-ease),
    opacity   var(--modal-close-dur) var(--modal-ease);
}

@media (prefers-reduced-motion: reduce) {
  .t-modal { transition: none !important; }
}
```

```html
<div class="t-modal" role="dialog">…</div>
<!-- Toggle .is-open. On close: .is-open → .is-closing → remove after 150ms. -->
```

---

## 7. Panel reveal (Y-translate + fade + blur)

**When to use:** Sliding side panels, sheet drawers, accordion content reveals, sticky-bar slide-down. Combo of translate + fade + cross-blur reads as one continuous "physical reveal".

```css
:root {
  --panel-open-dur: 400ms;
  --panel-close-dur: 350ms;
  --panel-translate-y: calc(187px * 0.5);  /* set to ~50% of panel's own height */
  --panel-blur: 2px;
  --panel-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-panel-slide {
  transform: translateY(var(--panel-translate-y));
  opacity: 0;
  filter: blur(var(--panel-blur));
  pointer-events: none;
  transition:
    transform var(--panel-close-dur) var(--panel-ease),
    opacity   var(--panel-close-dur) var(--panel-ease),
    filter    var(--panel-close-dur) var(--panel-ease);
  will-change: transform, opacity, filter;
}
.t-panel-slide[data-open="true"] {
  transform: translateY(0);
  opacity: 1;
  filter: blur(0);
  pointer-events: auto;
  transition:
    transform var(--panel-open-dur) var(--panel-ease),
    opacity   var(--panel-open-dur) var(--panel-ease),
    filter    var(--panel-open-dur) var(--panel-ease);
}

@media (prefers-reduced-motion: reduce) {
  .t-panel-slide { transition: none !important; }
}
```

```html
<div class="t-panel-slide" data-open="false">
  <!-- panel contents -->
</div>
<!-- Wrap in overflow:hidden if you want closed state fully clipped -->
```

---

## 8. Page side-by-side (left/right page transition)

**When to use:** Multi-step wizards, paginated content, tab content swaps. Page 1 exits left, page 2 exits right — directional storytelling.

```css
:root {
  --page-slide-dur: 200ms;
  --page-fade-dur: 200ms;
  --page-slide-distance: 8px;
  --page-blur: 3px;
  --page-stagger: 0ms;
  --page-exit-enabled: 1;
  --page-slide-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --page-fade-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-page-slide {
  position: relative;
}
.t-page-slide .t-page[data-page-id="1"] {
  --t-page-from-x: calc(var(--page-slide-distance) * -1);
}
.t-page-slide .t-page[data-page-id="2"] {
  --t-page-from-x: var(--page-slide-distance);
}
.t-page-slide .t-page {
  position: absolute;
  inset: 0;
  opacity: 0;
  pointer-events: none;
  transform: translateX(calc(var(--t-page-from-x, 0px) * var(--page-exit-enabled)));
  filter: blur(calc(var(--page-blur) * var(--page-exit-enabled)));
  transition:
    opacity   var(--page-fade-dur)  var(--page-fade-ease),
    transform var(--page-slide-dur) var(--page-slide-ease),
    filter    var(--page-slide-dur) var(--page-slide-ease);
  will-change: opacity, transform, filter;
}
.t-page-slide[data-page="1"] .t-page[data-page-id="1"],
.t-page-slide[data-page="2"] .t-page[data-page-id="2"] {
  opacity: 1;
  pointer-events: auto;
  transform: translateX(0);
  filter: blur(0);
  transition-delay: var(--page-stagger);
}

@media (prefers-reduced-motion: reduce) {
  .t-page-slide .t-page { transition: none !important; }
}
```

```html
<div class="t-page-slide" data-page="1">
  <section class="t-page" data-page-id="1">…</section>
  <section class="t-page" data-page-id="2">…</section>
</div>
<!-- Toggle data-page="1" / "2" -->
```

---

## 9. Icon swap (cross-fade + blur + scale)

**When to use:** Hamburger ↔ X, play ↔ pause, sun ↔ moon (theme toggle), expand ↔ collapse, copy ↔ check (after copy), heart-outline ↔ heart-filled. The two icons share the same grid cell and crossfade.

```css
:root {
  --icon-swap-dur: 200ms;
  --icon-swap-blur: 2px;
  --icon-swap-start-scale: 0.25;
  --icon-swap-ease: ease-in-out;
}

.t-icon-swap {
  position: relative;
  display: inline-grid;
}
.t-icon-swap .t-icon {
  grid-area: 1 / 1;
  transition:
    opacity   var(--icon-swap-dur) var(--icon-swap-ease),
    filter    var(--icon-swap-dur) var(--icon-swap-ease),
    transform var(--icon-swap-dur) var(--icon-swap-ease);
  will-change: opacity, filter, transform;
}
.t-icon-swap[data-state="a"] .t-icon[data-icon="a"],
.t-icon-swap[data-state="b"] .t-icon[data-icon="b"] {
  opacity: 1;
  filter: blur(0);
  transform: scale(1);
}
.t-icon-swap[data-state="a"] .t-icon[data-icon="b"],
.t-icon-swap[data-state="b"] .t-icon[data-icon="a"] {
  opacity: 0;
  filter: blur(var(--icon-swap-blur));
  transform: scale(var(--icon-swap-start-scale));
}

@media (prefers-reduced-motion: reduce) {
  .t-icon-swap .t-icon { transition: none !important; }
}
```

```html
<div class="t-icon-swap" data-state="a">
  <span class="t-icon" data-icon="a"><MenuIcon /></span>
  <span class="t-icon" data-icon="b"><XIcon /></span>
</div>
<!-- Toggle data-state between "a" and "b" -->
```

---

# Hover & interaction

## 10. Magnetic button (cursor-pull)

**When to use:** Hero CTA buttons, primary action buttons in marketing pages, anywhere you want a tactile "the button is pulling toward my cursor" feel. Aceternity / Awwwards staple.

```css
:root {
  --magnetic-dur: 400ms;
  --magnetic-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --magnetic-strength: 0.35;  /* 0..1, fraction of cursor distance to follow */
}

.t-magnetic {
  display: inline-block;
  transform: translate3d(var(--mx, 0px), var(--my, 0px), 0);
  transition: transform var(--magnetic-dur) var(--magnetic-ease);
  will-change: transform;
}

@media (prefers-reduced-motion: reduce) {
  .t-magnetic { transform: none !important; transition: none !important; }
}
```

```jsx
// Vanilla JS — no Framer Motion required
function attachMagnetic(el, strength = 0.35) {
  const onMove = (e) => {
    const r = el.getBoundingClientRect();
    const x = (e.clientX - (r.left + r.width  / 2)) * strength;
    const y = (e.clientY - (r.top  + r.height / 2)) * strength;
    el.style.setProperty('--mx', `${x}px`);
    el.style.setProperty('--my', `${y}px`);
  };
  const onLeave = () => {
    el.style.setProperty('--mx', '0px');
    el.style.setProperty('--my', '0px');
  };
  el.addEventListener('mousemove', onMove);
  el.addEventListener('mouseleave', onLeave);
}
```

```html
<button class="t-magnetic">Get started</button>
```

**Notes:** Listen on the button itself (small radius) for a tight pull, or on a parent zone for a wider field of attraction. Strength 0.2–0.4 feels best.

---

## 11. Spotlight border (cursor-tracked glow)

**When to use:** Pricing cards, feature cards, dashboard tiles. Border lights up where the cursor hovers — Aceternity / Linear / Vercel marketing-card pattern.

```css
:root {
  --spotlight-size: 260px;
  --spotlight-color: rgba(255, 255, 255, 0.18);
  --spotlight-border-color: rgba(255, 255, 255, 0.08);
  --spotlight-radius: 16px;
}

.t-spotlight {
  position: relative;
  border-radius: var(--spotlight-radius);
  background: rgba(255, 255, 255, 0.02);
  isolation: isolate;
}
.t-spotlight::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background:
    radial-gradient(
      var(--spotlight-size) circle at var(--mx, 50%) var(--my, 50%),
      var(--spotlight-color),
      transparent 60%
    ),
    linear-gradient(var(--spotlight-border-color), var(--spotlight-border-color));
  -webkit-mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
          mask-composite: exclude;
  pointer-events: none;
  transition: opacity 200ms ease;
}

@media (prefers-reduced-motion: reduce) {
  .t-spotlight::before { background: linear-gradient(var(--spotlight-border-color), var(--spotlight-border-color)); }
}
```

```jsx
function attachSpotlight(el) {
  el.addEventListener('mousemove', (e) => {
    const r = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - r.left}px`);
    el.style.setProperty('--my', `${e.clientY - r.top}px`);
  });
}
```

```html
<div class="t-spotlight">…card content…</div>
```

**Notes:** For a group of cards, attach the listener to the parent grid and update each card's `--mx/--my` from one shared event for buttery performance.

---

## 12. Shine sweep (light passes across button)

**When to use:** Premium CTA buttons, badges ("Pro", "New"), promo banners. Diagonal light streak slides across on hover.

```css
:root {
  --shine-dur: 700ms;
  --shine-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --shine-color: rgba(255, 255, 255, 0.35);
  --shine-width: 40%;
}

.t-shine {
  position: relative;
  overflow: hidden;
  isolation: isolate;
}
.t-shine::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    115deg,
    transparent 30%,
    var(--shine-color) 50%,
    transparent calc(50% + var(--shine-width))
  );
  transform: translateX(-120%);
  transition: transform var(--shine-dur) var(--shine-ease);
  pointer-events: none;
}
.t-shine:hover::after,
.t-shine:focus-visible::after {
  transform: translateX(120%);
}

@media (prefers-reduced-motion: reduce) {
  .t-shine::after { transition: none !important; transform: translateX(-120%) !important; }
}
```

```html
<button class="t-shine">Upgrade to Pro</button>
```

---

## 13. Tilt-on-hover card (3D perspective)

**When to use:** Product cards, pricing tiers, photo galleries — adds depth without being gimmicky. Best at small max angles (6–10deg).

```css
:root {
  --tilt-max: 8deg;
  --tilt-perspective: 800px;
  --tilt-dur: 400ms;
  --tilt-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --tilt-lift: 6px;
}

.t-tilt {
  transform-style: preserve-3d;
  perspective: var(--tilt-perspective);
  transition: transform var(--tilt-dur) var(--tilt-ease);
  will-change: transform;
  transform:
    rotateX(calc(var(--ty, 0) * var(--tilt-max) * -1))
    rotateY(calc(var(--tx, 0) * var(--tilt-max)))
    translateZ(0);
}
.t-tilt:hover { transform:
  rotateX(calc(var(--ty, 0) * var(--tilt-max) * -1))
  rotateY(calc(var(--tx, 0) * var(--tilt-max)))
  translateZ(var(--tilt-lift));
}

@media (prefers-reduced-motion: reduce) {
  .t-tilt { transform: none !important; transition: none !important; }
}
```

```jsx
function attachTilt(el) {
  el.addEventListener('mousemove', (e) => {
    const r = el.getBoundingClientRect();
    const tx = ((e.clientX - r.left) / r.width  - 0.5) * 2;  // -1..1
    const ty = ((e.clientY - r.top)  / r.height - 0.5) * 2;
    el.style.setProperty('--tx', tx);
    el.style.setProperty('--ty', ty);
  });
  el.addEventListener('mouseleave', () => {
    el.style.setProperty('--tx', 0);
    el.style.setProperty('--ty', 0);
  });
}
```

```html
<article class="t-tilt">…</article>
```

---

## 14. Underline grow (left-to-right wipe)

**When to use:** Inline text links in body copy, nav items, footer links. Reads like a fountain-pen underscore drawing in.

```css
:root {
  --underline-dur: 350ms;
  --underline-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --underline-thickness: 1.5px;
  --underline-color: currentColor;
  --underline-offset: 2px;
}

.t-underline {
  position: relative;
  display: inline-block;
  text-decoration: none;
}
.t-underline::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(var(--underline-offset) * -1);
  height: var(--underline-thickness);
  background: var(--underline-color);
  transform: scaleX(0);
  transform-origin: left center;
  transition: transform var(--underline-dur) var(--underline-ease);
}
.t-underline:hover::after,
.t-underline:focus-visible::after {
  transform: scaleX(1);
}

@media (prefers-reduced-motion: reduce) {
  .t-underline::after { transition: none !important; transform: scaleX(1) !important; }
}
```

```html
<a href="/" class="t-underline">Read the docs</a>
```

---

## 15. Ripple click (concentric pulse from cursor)

**When to use:** Material-style buttons, toggle pills, anywhere a tap should leave visible feedback. Origin tracks the click point.

```css
:root {
  --ripple-dur: 600ms;
  --ripple-ease: cubic-bezier(0.4, 0, 0.2, 1);
  --ripple-color: rgba(255, 255, 255, 0.5);
}

.t-ripple {
  position: relative;
  overflow: hidden;
  isolation: isolate;
}
.t-ripple .t-ripple-wave {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  background: var(--ripple-color);
  transform: translate(-50%, -50%) scale(0);
  opacity: 0.6;
  animation: t-ripple-grow var(--ripple-dur) var(--ripple-ease) forwards;
  will-change: transform, opacity;
}
@keyframes t-ripple-grow {
  to { transform: translate(-50%, -50%) scale(1); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .t-ripple .t-ripple-wave { animation: none !important; opacity: 0 !important; }
}
```

```js
function attachRipple(el) {
  el.addEventListener('pointerdown', (e) => {
    const r = el.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 2;
    const wave = document.createElement('span');
    wave.className = 't-ripple-wave';
    wave.style.left = `${e.clientX - r.left}px`;
    wave.style.top  = `${e.clientY - r.top}px`;
    wave.style.width = wave.style.height = `${size}px`;
    el.appendChild(wave);
    wave.addEventListener('animationend', () => wave.remove());
  });
}
```

```html
<button class="t-ripple">Click me</button>
```

---

## 16. Press-down (tactile :active scale)

**When to use:** All buttons, IconButtons, toggles. Tiny scale-down on press makes the button feel physical.

```css
:root {
  --press-scale: 0.97;
  --press-dur: 120ms;
  --press-ease: cubic-bezier(0.4, 0, 0.2, 1);
}

.t-press {
  transition: transform var(--press-dur) var(--press-ease);
  will-change: transform;
}
.t-press:active { transform: scale(var(--press-scale)); }

@media (prefers-reduced-motion: reduce) {
  .t-press { transition: none !important; }
  .t-press:active { transform: none !important; }
}
```

```html
<button class="t-press">Save</button>
```

---

## 17. Direction-aware hover fill

**When to use:** Nav links, grid cells, gallery tiles. The fill enters from the side the cursor came from — subtle but unforgettable.

```css
:root {
  --dir-fill-dur: 350ms;
  --dir-fill-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --dir-fill-color: currentColor;
}

.t-dir-fill {
  position: relative;
  overflow: hidden;
  isolation: isolate;
}
.t-dir-fill::before {
  content: "";
  position: absolute;
  inset: 0;
  background: var(--dir-fill-color);
  transform: translate(var(--dir-fx, -100%), var(--dir-fy, 0));
  transition: transform var(--dir-fill-dur) var(--dir-fill-ease);
  z-index: -1;
}
```

```js
function attachDirFill(el) {
  const compute = (e) => {
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top)  / r.height;
    // pick dominant axis
    const dx = Math.abs(x - 0.5), dy = Math.abs(y - 0.5);
    if (dx > dy) {
      el.style.setProperty('--dir-fx', x < 0.5 ? '-100%' : '100%');
      el.style.setProperty('--dir-fy', '0%');
    } else {
      el.style.setProperty('--dir-fx', '0%');
      el.style.setProperty('--dir-fy', y < 0.5 ? '-100%' : '100%');
    }
  };
  el.addEventListener('mouseenter', (e) => { compute(e); requestAnimationFrame(() => {
    el.style.setProperty('--dir-fx', '0%');
    el.style.setProperty('--dir-fy', '0%');
  }); });
  el.addEventListener('mouseleave', compute);
}
```

```html
<a class="t-dir-fill" href="#">Projects</a>
```

---

# Scroll-triggered entrance

## 18. Fade-up on enter viewport

**When to use:** Section headlines, body paragraphs, image blocks as user scrolls. The default scroll-reveal — never gets old.

```css
:root {
  --reveal-dur: 700ms;
  --reveal-distance: 24px;
  --reveal-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-reveal {
  opacity: 0;
  transform: translateY(var(--reveal-distance));
  transition:
    opacity   var(--reveal-dur) var(--reveal-ease),
    transform var(--reveal-dur) var(--reveal-ease);
  will-change: opacity, transform;
}
.t-reveal.is-in {
  opacity: 1;
  transform: translateY(0);
}

@media (prefers-reduced-motion: reduce) {
  .t-reveal { opacity: 1 !important; transform: none !important; transition: none !important; }
}
```

```js
const io = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) {
    e.target.classList.add('is-in');
    io.unobserve(e.target);
  }
}, { threshold: 0.15 });
document.querySelectorAll('.t-reveal').forEach(el => io.observe(el));
```

```html
<h2 class="t-reveal">Built for speed</h2>
```

---

## 19. Slide-in from side (alternating sections)

**When to use:** Long-form marketing pages where alternating sections slide in from left/right for narrative rhythm.

```css
:root {
  --slide-dur: 800ms;
  --slide-distance: 60px;
  --slide-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-slide-in {
  opacity: 0;
  transform: translateX(var(--slide-distance));
  transition:
    opacity   var(--slide-dur) var(--slide-ease),
    transform var(--slide-dur) var(--slide-ease);
  will-change: opacity, transform;
}
.t-slide-in[data-from="left"] { transform: translateX(calc(var(--slide-distance) * -1)); }
.t-slide-in.is-in { opacity: 1; transform: translateX(0); }

@media (prefers-reduced-motion: reduce) {
  .t-slide-in { opacity: 1 !important; transform: none !important; transition: none !important; }
}
```

```html
<section class="t-slide-in" data-from="left">…</section>
<section class="t-slide-in" data-from="right">…</section>
<!-- Use the same IntersectionObserver from #18 to add .is-in -->
```

---

## 20. Stagger children (cascade reveal)

**When to use:** Feature grids, card lists, nav items, anything where items should appear in sequence rather than all at once.

```css
:root {
  --stagger-dur: 500ms;
  --stagger-step: 70ms;
  --stagger-distance: 16px;
  --stagger-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-stagger > * {
  opacity: 0;
  transform: translateY(var(--stagger-distance));
  transition:
    opacity   var(--stagger-dur) var(--stagger-ease),
    transform var(--stagger-dur) var(--stagger-ease);
  will-change: opacity, transform;
}
.t-stagger.is-in > *  { opacity: 1; transform: translateY(0); }
.t-stagger.is-in > *:nth-child(1)  { transition-delay: calc(var(--stagger-step) * 0); }
.t-stagger.is-in > *:nth-child(2)  { transition-delay: calc(var(--stagger-step) * 1); }
.t-stagger.is-in > *:nth-child(3)  { transition-delay: calc(var(--stagger-step) * 2); }
.t-stagger.is-in > *:nth-child(4)  { transition-delay: calc(var(--stagger-step) * 3); }
.t-stagger.is-in > *:nth-child(5)  { transition-delay: calc(var(--stagger-step) * 4); }
.t-stagger.is-in > *:nth-child(6)  { transition-delay: calc(var(--stagger-step) * 5); }
.t-stagger.is-in > *:nth-child(7)  { transition-delay: calc(var(--stagger-step) * 6); }
.t-stagger.is-in > *:nth-child(8)  { transition-delay: calc(var(--stagger-step) * 7); }
.t-stagger.is-in > *:nth-child(n+9){ transition-delay: calc(var(--stagger-step) * 8); }

@media (prefers-reduced-motion: reduce) {
  .t-stagger > * { opacity: 1 !important; transform: none !important; transition: none !important; }
}
```

```html
<ul class="t-stagger">
  <li>Item 1</li><li>Item 2</li><li>Item 3</li>
</ul>
```

---

## 21. Blur-clear reveal

**When to use:** Hero text, headline statements, about-us paragraphs. Text begins blurred and sharpens — feels cinematic and editorial.

```css
:root {
  --blur-reveal-dur: 900ms;
  --blur-reveal-blur: 14px;
  --blur-reveal-distance: 12px;
  --blur-reveal-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-blur-reveal {
  opacity: 0;
  filter: blur(var(--blur-reveal-blur));
  transform: translateY(var(--blur-reveal-distance));
  transition:
    opacity   var(--blur-reveal-dur) var(--blur-reveal-ease),
    filter    var(--blur-reveal-dur) var(--blur-reveal-ease),
    transform var(--blur-reveal-dur) var(--blur-reveal-ease);
  will-change: opacity, filter, transform;
}
.t-blur-reveal.is-in {
  opacity: 1;
  filter: blur(0);
  transform: translateY(0);
}

@media (prefers-reduced-motion: reduce) {
  .t-blur-reveal { opacity: 1 !important; filter: none !important; transform: none !important; transition: none !important; }
}
```

```html
<h1 class="t-blur-reveal">A new way to ship.</h1>
```

---

## 22. Scale-up entrance (0.95 → 1)

**When to use:** Image cards, video thumbnails, feature illustrations. Subtle "settling into place" feel.

```css
:root {
  --scale-up-dur: 700ms;
  --scale-up-from: 0.95;
  --scale-up-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-scale-up {
  opacity: 0;
  transform: scale(var(--scale-up-from));
  transition:
    opacity   var(--scale-up-dur) var(--scale-up-ease),
    transform var(--scale-up-dur) var(--scale-up-ease);
  will-change: opacity, transform;
}
.t-scale-up.is-in { opacity: 1; transform: scale(1); }

@media (prefers-reduced-motion: reduce) {
  .t-scale-up { opacity: 1 !important; transform: none !important; transition: none !important; }
}
```

```html
<img class="t-scale-up" src="…" />
```

---

## 23. Word-by-word text reveal

**When to use:** Hero headlines, manifesto quotes, editorial headers. Each word fades + lifts in sequence. Magic UI / Aceternity signature.

```css
:root {
  --word-dur: 600ms;
  --word-step: 60ms;
  --word-distance: 14px;
  --word-blur: 6px;
  --word-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-words { display: inline; }
.t-words .t-word {
  display: inline-block;
  opacity: 0;
  transform: translateY(var(--word-distance));
  filter: blur(var(--word-blur));
  transition:
    opacity   var(--word-dur) var(--word-ease),
    transform var(--word-dur) var(--word-ease),
    filter    var(--word-dur) var(--word-ease);
  will-change: opacity, transform, filter;
}
.t-words.is-in .t-word { opacity: 1; transform: translateY(0); filter: blur(0); }

@media (prefers-reduced-motion: reduce) {
  .t-words .t-word { opacity: 1 !important; transform: none !important; filter: none !important; transition: none !important; }
}
```

```js
// Split a heading into <span class="t-word"> per word with stagger delays
function splitWords(el) {
  const words = el.textContent.trim().split(/\s+/);
  el.innerHTML = words.map((w, i) =>
    `<span class="t-word" style="transition-delay:${i * 60}ms">${w}</span>`
  ).join(' ');
}
```

```html
<h1 class="t-words">Design that moves you</h1>
```

---

## 24. SVG path-draw

**When to use:** Logo reveals, illustration outlines, signature flourishes, decorative dividers. Stroke draws itself in.

```css
:root {
  --draw-dur: 1600ms;
  --draw-ease: cubic-bezier(0.65, 0, 0.35, 1);
}

.t-draw path,
.t-draw polyline,
.t-draw line {
  stroke-dasharray: var(--len, 1000);
  stroke-dashoffset: var(--len, 1000);
  transition: stroke-dashoffset var(--draw-dur) var(--draw-ease);
  will-change: stroke-dashoffset;
}
.t-draw.is-in path,
.t-draw.is-in polyline,
.t-draw.is-in line {
  stroke-dashoffset: 0;
}

@media (prefers-reduced-motion: reduce) {
  .t-draw path, .t-draw polyline, .t-draw line { stroke-dashoffset: 0 !important; transition: none !important; }
}
```

```js
// Measure each path so the dash math is exact
document.querySelectorAll('.t-draw path').forEach(p => {
  const len = p.getTotalLength();
  p.style.setProperty('--len', len);
});
```

```html
<svg class="t-draw" viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="2">
  <path d="M10 50 Q 50 10, 90 50 T 170 50" />
</svg>
```

---

# Continuous / ambient

## 25. Marquee (infinite horizontal scroll)

**When to use:** Logo tickers, social proof bands, "trusted by" rows, scrolling testimonials.

### THE THREE MANDATORY RULES (skip any one and the loop visibly seams)

The owner has tested: AI gets this wrong constantly. The fix is non-negotiable:

1. **DUPLICATE THE CONTENT** inside the track. The animation translates `-50%`, NOT `-100%`. The track holds two identical sets of items back-to-back. As copy 1 scrolls off-screen left, copy 2 takes its place — invisible loop.
2. **EDGE MASK IN PIXELS, NOT PERCENT.** Use `linear-gradient(to right, transparent 0, #000 80px, #000 calc(100% - 80px), transparent 100%)`. A 10% mask is too narrow on wide viewports; a fixed 80px keeps the fade strong regardless of width.
3. **AT LEAST 8 ITEMS PER COPY.** If you have 5 logos, repeat them within ONE copy until you have 10, then duplicate the whole thing. Too few items per copy = the seam is unavoidable because the track isn't wide enough to hide it.

### Code (canonical seamless implementation)

```css
:root {
  --marquee-dur: 40s;     /* 30-60s range; <30s feels frantic, >60s feels dead */
  --marquee-gap: 48px;
}

.t-marquee {
  overflow: hidden;
  width: 100%;
  /* Pixel-based edge mask — strong fade no matter how wide */
  -webkit-mask-image: linear-gradient(to right, transparent 0, #000 80px, #000 calc(100% - 80px), transparent 100%);
          mask-image: linear-gradient(to right, transparent 0, #000 80px, #000 calc(100% - 80px), transparent 100%);
}
.t-marquee-track {
  display: flex;
  gap: var(--marquee-gap);
  width: max-content;            /* track is wider than container — required */
  animation: t-marquee-scroll var(--marquee-dur) linear infinite;
  will-change: transform;
}

@keyframes t-marquee-scroll {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }   /* -50% NOT -100% */
}

/* Pause on hover — only if items are clickable. Don't use for ambient logo walls. */
/* .t-marquee:hover .t-marquee-track { animation-play-state: paused; } */

@media (prefers-reduced-motion: reduce) {
  .t-marquee-track { animation: none !important; }
}
```

```jsx
const items = ["Outlier", "Cadence", "Filo", "Helio", "Quanta", "Rivet", "Northstar", "Brick & Bell"];

<div className="t-marquee">
  <div className="t-marquee-track">
    {/* Copy 1 */}
    {items.map((it) => <span key={`a-${it}`}>{it}</span>)}
    {/* Copy 2 — REQUIRED. Same content, in order. Hide from screen readers. */}
    <span aria-hidden="true" style={{ display: "contents" }}>
      {items.map((it) => <span key={`b-${it}`}>{it}</span>)}
    </span>
  </div>
</div>
```

### How to verify it's seamless

1. Open the page in browser, scrub time to ~5 seconds before a loop completes.
2. Watch the rightmost edge: items should slide IN from off-screen smoothly. If you see items APPEAR mid-band or fade-in inside the visible area → broken.
3. Scrub to mid-loop. The leftmost visible item should match the (N+1)-th item if everything's tiled correctly.
4. The mask gradient should fully fade items leaving the band — you should never see a half-cut item at the visible edge.

### Common failures that produce the "N-shape" (visible seam)

- ❌ Single copy of items in track + animating `-100%` → there's nothing on the right when items scroll off, leaving a gap
- ❌ Mask in `%` (e.g. `transparent 0%, #000 5%, ...`) → on wide viewports, 5% is too narrow to hide entry/exit
- ❌ Animating `left:` or `margin-left:` → triggers layout reflow per frame, AND the animation goes from 0 to large pixel value visibly resetting at end
- ❌ Track width set to a fixed value → if items don't fill it, the loop point is exposed
- ❌ Too few items per copy (3-4 items, container is wide) → the seam is wider than the items

If you see ANY of these in your code → fix before shipping.

---

## 26. Skeleton shimmer

**When to use:** Loading placeholders for cards, list items, avatars while data fetches. Premium alternative to a spinner.

```css
:root {
  --shimmer-dur: 1.6s;
  --shimmer-base: #1a1a1a;
  --shimmer-highlight: rgba(255, 255, 255, 0.06);
  --shimmer-radius: 8px;
}

.t-shimmer {
  position: relative;
  overflow: hidden;
  background: var(--shimmer-base);
  border-radius: var(--shimmer-radius);
  isolation: isolate;
}
.t-shimmer::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    100deg,
    transparent 30%,
    var(--shimmer-highlight) 50%,
    transparent 70%
  );
  transform: translateX(-100%);
  animation: t-shimmer-sweep var(--shimmer-dur) ease-in-out infinite;
  will-change: transform;
}
@keyframes t-shimmer-sweep {
  to { transform: translateX(100%); }
}

@media (prefers-reduced-motion: reduce) {
  .t-shimmer::after { animation: none !important; opacity: 0.4; transform: none !important; }
}
```

```html
<div class="t-shimmer" style="height: 16px; width: 240px;"></div>
```

---

## 27. Pulse / breathing dot

**When to use:** "Live" status indicators, recording dots, online presence, notification badges that need to breathe.

```css
:root {
  --pulse-dur: 1.8s;
  --pulse-color: rgb(34, 197, 94);
  --pulse-size: 8px;
}

.t-pulse {
  position: relative;
  display: inline-block;
  width: var(--pulse-size);
  height: var(--pulse-size);
  border-radius: 50%;
  background: var(--pulse-color);
}
.t-pulse::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--pulse-color);
  animation: t-pulse-ring var(--pulse-dur) cubic-bezier(0, 0, 0.2, 1) infinite;
  will-change: transform, opacity;
}
@keyframes t-pulse-ring {
  0%   { transform: scale(1);   opacity: 0.7; }
  100% { transform: scale(2.6); opacity: 0;   }
}

@media (prefers-reduced-motion: reduce) {
  .t-pulse::before { animation: none !important; opacity: 0; }
}
```

```html
<span class="t-pulse" aria-label="Live"></span>
```

---

## 28. Background gradient shift

**When to use:** Hero backgrounds, CTA buttons, decorative panels — slow color cycle adds life without distracting.

```css
:root {
  --grad-dur: 18s;
  --grad-1: #6366f1;
  --grad-2: #ec4899;
  --grad-3: #f59e0b;
}

.t-grad-shift {
  background: linear-gradient(120deg, var(--grad-1), var(--grad-2), var(--grad-3), var(--grad-1));
  background-size: 300% 300%;
  animation: t-grad-shift var(--grad-dur) ease-in-out infinite;
  will-change: background-position;
}
@keyframes t-grad-shift {
  0%   { background-position:   0% 50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position:   0% 50%; }
}

@media (prefers-reduced-motion: reduce) {
  .t-grad-shift { animation: none !important; }
}
```

```html
<section class="t-grad-shift">…</section>
```

---

## 29. Rotating loading orbit

**When to use:** Inline loaders, AI-thinking indicators, processing states. Two dots orbit a center — premium alternative to a generic spinner.

```css
:root {
  --orbit-dur: 1.4s;
  --orbit-size: 28px;
  --orbit-dot-size: 6px;
  --orbit-color: currentColor;
}

.t-orbit {
  position: relative;
  display: inline-block;
  width: var(--orbit-size);
  height: var(--orbit-size);
  animation: t-orbit-spin var(--orbit-dur) linear infinite;
  will-change: transform;
}
.t-orbit::before, .t-orbit::after {
  content: "";
  position: absolute;
  width: var(--orbit-dot-size);
  height: var(--orbit-dot-size);
  border-radius: 50%;
  background: var(--orbit-color);
  top: 50%;
  left: 50%;
  margin: calc(var(--orbit-dot-size) * -0.5) 0 0 calc(var(--orbit-dot-size) * -0.5);
}
.t-orbit::before { transform: translate(calc(var(--orbit-size) / 2 - var(--orbit-dot-size) / 2), 0); }
.t-orbit::after  { transform: translate(calc(var(--orbit-size) / -2 + var(--orbit-dot-size) / 2), 0); opacity: 0.4; }

@keyframes t-orbit-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .t-orbit { animation-duration: 0s; animation: none !important; }
}
```

```html
<span class="t-orbit" role="status" aria-label="Loading"></span>
```

---

# Loading / progress

## 30. Linear progress bar with shimmer

**When to use:** File uploads, form completion, multi-step indicators. Fill grows + shimmer pass conveys active progress.

```css
:root {
  --prog-dur: 400ms;
  --prog-ease: cubic-bezier(0.4, 0, 0.2, 1);
  --prog-track: rgba(255, 255, 255, 0.08);
  --prog-fill: #6366f1;
  --prog-radius: 999px;
  --prog-shimmer: 1.4s;
}

.t-prog {
  position: relative;
  overflow: hidden;
  height: 6px;
  border-radius: var(--prog-radius);
  background: var(--prog-track);
}
.t-prog-fill {
  height: 100%;
  width: var(--prog-value, 0%);
  background: var(--prog-fill);
  border-radius: inherit;
  transform-origin: left center;
  transition: width var(--prog-dur) var(--prog-ease);
  position: relative;
  overflow: hidden;
}
.t-prog-fill::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.35), transparent);
  transform: translateX(-100%);
  animation: t-prog-shimmer var(--prog-shimmer) linear infinite;
}
@keyframes t-prog-shimmer { to { transform: translateX(100%); } }

@media (prefers-reduced-motion: reduce) {
  .t-prog-fill, .t-prog-fill::after { transition: none !important; animation: none !important; }
}
```

```html
<div class="t-prog"><div class="t-prog-fill" style="--prog-value: 64%"></div></div>
```

---

## 31. Circular progress (conic-gradient)

**When to use:** Profile completion, daily goals, score gauges. Pure CSS — no SVG.

```css
:root {
  --ring-size: 64px;
  --ring-thick: 6px;
  --ring-track: rgba(255, 255, 255, 0.1);
  --ring-fill: #22c55e;
  --ring-dur: 600ms;
  --ring-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.t-ring {
  position: relative;
  width: var(--ring-size);
  height: var(--ring-size);
  border-radius: 50%;
  background:
    conic-gradient(var(--ring-fill) calc(var(--ring-value, 0) * 1%), var(--ring-track) 0);
  transition: background var(--ring-dur) var(--ring-ease);
}
.t-ring::before {
  content: "";
  position: absolute;
  inset: var(--ring-thick);
  border-radius: 50%;
  background: var(--ring-bg, #0a0a0a);
}
.t-ring-label {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-variant-numeric: tabular-nums;
}

@media (prefers-reduced-motion: reduce) {
  .t-ring { transition: none !important; }
}
```

```html
<div class="t-ring" style="--ring-value: 72">
  <span class="t-ring-label">72%</span>
</div>
```

---

## 32. Stepped progress dots

**When to use:** Multi-step forms, onboarding, checkout flows. Active dot is filled + slightly larger; completed dots filled.

```css
:root {
  --dots-dur: 250ms;
  --dots-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --dots-size: 8px;
  --dots-active-size: 22px;
  --dots-color: #6366f1;
  --dots-track: rgba(255, 255, 255, 0.18);
}

.t-dots { display: inline-flex; gap: 8px; align-items: center; }
.t-dots .t-dot {
  display: block;
  width: var(--dots-size);
  height: var(--dots-size);
  border-radius: 999px;
  background: var(--dots-track);
  transition:
    width      var(--dots-dur) var(--dots-ease),
    background var(--dots-dur) var(--dots-ease);
}
.t-dots .t-dot[data-state="done"]   { background: var(--dots-color); }
.t-dots .t-dot[data-state="active"] {
  background: var(--dots-color);
  width: var(--dots-active-size);
}

@media (prefers-reduced-motion: reduce) {
  .t-dots .t-dot { transition: none !important; }
}
```

```html
<div class="t-dots" role="progressbar" aria-valuenow="2" aria-valuemax="4">
  <span class="t-dot" data-state="done"></span>
  <span class="t-dot" data-state="active"></span>
  <span class="t-dot"></span>
  <span class="t-dot"></span>
</div>
```

---

## 33. Indeterminate loader (sliding bar)

**When to use:** Top-of-page route-change indicator, unknown-duration tasks. Bar slides across track endlessly.

```css
:root {
  --indet-dur: 1.4s;
  --indet-track: rgba(255, 255, 255, 0.08);
  --indet-fill: #6366f1;
  --indet-radius: 999px;
}

.t-indet {
  position: relative;
  overflow: hidden;
  height: 3px;
  border-radius: var(--indet-radius);
  background: var(--indet-track);
}
.t-indet::before {
  content: "";
  position: absolute;
  top: 0; bottom: 0;
  left: 0;
  width: 40%;
  background: var(--indet-fill);
  border-radius: inherit;
  animation: t-indet-slide var(--indet-dur) cubic-bezier(0.4, 0, 0.2, 1) infinite;
  will-change: transform;
}
@keyframes t-indet-slide {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(350%);  }
}

@media (prefers-reduced-motion: reduce) {
  .t-indet::before { animation: none !important; transform: translateX(0) !important; width: 100%; opacity: 0.5; }
}
```

```html
<div class="t-indet" role="progressbar" aria-label="Loading"></div>
```

---

# Text & data

## 34. Typewriter

**When to use:** Hero subheads, terminal-style intros, "I am a {role}" lead lines. Caret blinks; characters reveal one by one.

```css
:root {
  --type-dur: 2.4s;
  --type-steps: 28;       /* set to character count */
  --type-caret-color: currentColor;
}

.t-type {
  display: inline-block;
  overflow: hidden;
  white-space: nowrap;
  border-right: 2px solid var(--type-caret-color);
  width: 0;
  animation:
    t-type-in var(--type-dur) steps(var(--type-steps)) forwards,
    t-type-caret 0.8s step-end infinite;
}
@keyframes t-type-in   { to { width: 100%; } }
@keyframes t-type-caret { 50% { border-color: transparent; } }

@media (prefers-reduced-motion: reduce) {
  .t-type { width: 100% !important; animation: none !important; border-right: none; }
}
```

```html
<span class="t-type" style="--type-steps: 18">Build the future.</span>
```

**Notes:** Set `--type-steps` to the exact character count of the text for clean per-character progression. Wrap in a known-width container — the animation grows from 0 to 100% of intrinsic width.

---

## 35. Number counter (rolling odometer)

**When to use:** Stat sections ("10,000+ users"), score counters, financial totals. Each digit cylinder rolls into place.

```css
:root {
  --odom-dur: 1.4s;
  --odom-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --odom-digit-h: 1em;
}

.t-odom {
  display: inline-flex;
  align-items: baseline;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.t-odom .t-odom-digit {
  display: inline-block;
  height: var(--odom-digit-h);
  overflow: hidden;
  vertical-align: bottom;
}
.t-odom .t-odom-strip {
  display: flex;
  flex-direction: column;
  transform: translateY(0);
  transition: transform var(--odom-dur) var(--odom-ease);
  will-change: transform;
}
.t-odom .t-odom-strip > span {
  height: var(--odom-digit-h);
  line-height: var(--odom-digit-h);
}

@media (prefers-reduced-motion: reduce) {
  .t-odom .t-odom-strip { transition: none !important; }
}
```

```html
<span class="t-odom">
  <span class="t-odom-digit"><span class="t-odom-strip" style="transform: translateY(calc(-3 * 1em))">
    <span>0</span><span>1</span><span>2</span><span>3</span><span>4</span><span>5</span><span>6</span><span>7</span><span>8</span><span>9</span>
  </span></span>
  <!-- repeat per digit; set translateY to -targetDigit * 1em -->
</span>
```

**Notes:** For each digit, render 0..9 stacked vertically and translate the strip by `-target * 1em`. Replace strips when digit count changes.

---

## 36. Text scramble (matrix decode)

**When to use:** Hero word reveals, brand names, "decoding" intros. Characters cycle through random glyphs before settling. JS-required.

```css
:root {
  --scramble-color: currentColor;
}

.t-scramble {
  display: inline-block;
  font-variant-numeric: tabular-nums;
  color: var(--scramble-color);
}

@media (prefers-reduced-motion: reduce) {
  /* animation is JS-driven; respect reduced-motion in the JS below */
}
```

```js
const GLYPHS = '!<>-_\\/[]{}—=+*^?#abcdefghijklmnopqrstuvwxyz0123456789';
function scramble(el, target, { duration = 900 } = {}) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    el.textContent = target; return;
  }
  const start = performance.now();
  const from = el.textContent;
  const len = Math.max(from.length, target.length);
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    let out = '';
    for (let i = 0; i < len; i++) {
      const reveal = i / len < t;
      out += reveal ? (target[i] ?? '') : GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
    }
    el.textContent = out;
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
```

```html
<span class="t-scramble">Loading…</span>
<!-- scramble(el, "Welcome back") -->
```

---

## 37. Gradient text sweep

**When to use:** Hero headline accent words, brand wordmarks, callout phrases. Conic/linear gradient sweeps across text.

```css
:root {
  --gtext-dur: 4s;
  --gtext-1: #a78bfa;
  --gtext-2: #f472b6;
  --gtext-3: #facc15;
}

.t-gtext {
  background: linear-gradient(90deg, var(--gtext-1), var(--gtext-2), var(--gtext-3), var(--gtext-1));
  background-size: 300% 100%;
  -webkit-background-clip: text;
          background-clip: text;
  color: transparent;
  animation: t-gtext-sweep var(--gtext-dur) linear infinite;
  will-change: background-position;
}
@keyframes t-gtext-sweep {
  to { background-position: 300% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .t-gtext { animation: none !important; background-position: 0 0; }
}
```

```html
<h1>Build with <span class="t-gtext">imagination</span></h1>
```

---

## 38. Highlighter sweep

**When to use:** Marketing emphasis on key phrases, "this part matters" highlights, hover-on-keyword reveals. Yellow/accent bar grows in behind text.

```css
:root {
  --hl-dur: 600ms;
  --hl-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --hl-color: rgba(250, 204, 21, 0.45);
  --hl-thickness: 0.45em;
}

.t-highlight {
  background-image: linear-gradient(var(--hl-color), var(--hl-color));
  background-repeat: no-repeat;
  background-size: 0% var(--hl-thickness);
  background-position: 0 88%;
  transition: background-size var(--hl-dur) var(--hl-ease);
  padding: 0 0.05em;
}
.t-highlight.is-in,
.t-highlight:hover {
  background-size: 100% var(--hl-thickness);
}

@media (prefers-reduced-motion: reduce) {
  .t-highlight { transition: none !important; background-size: 100% var(--hl-thickness) !important; }
}
```

```html
<p>Designed for <span class="t-highlight is-in">people who care</span>.</p>
```

---

# Toggle / state

## 39. Sliding switch toggle (iOS-style)

**When to use:** Settings toggles, dark-mode switch, on/off booleans.

```css
:root {
  --switch-dur: 220ms;
  --switch-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --switch-w: 44px;
  --switch-h: 26px;
  --switch-pad: 3px;
  --switch-off: rgba(255, 255, 255, 0.18);
  --switch-on:  #22c55e;
  --switch-knob: #fff;
}

.t-switch {
  position: relative;
  display: inline-block;
  width: var(--switch-w);
  height: var(--switch-h);
  border-radius: 999px;
  background: var(--switch-off);
  transition: background var(--switch-dur) var(--switch-ease);
  cursor: pointer;
}
.t-switch::after {
  content: "";
  position: absolute;
  top: var(--switch-pad);
  left: var(--switch-pad);
  width: calc(var(--switch-h) - var(--switch-pad) * 2);
  height: calc(var(--switch-h) - var(--switch-pad) * 2);
  border-radius: 50%;
  background: var(--switch-knob);
  transform: translateX(0);
  transition: transform var(--switch-dur) var(--switch-ease);
  will-change: transform;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
}
.t-switch[data-on="true"] { background: var(--switch-on); }
.t-switch[data-on="true"]::after {
  transform: translateX(calc(var(--switch-w) - var(--switch-h)));
}

@media (prefers-reduced-motion: reduce) {
  .t-switch, .t-switch::after { transition: none !important; }
}
```

```html
<button class="t-switch" role="switch" aria-checked="false" data-on="false"></button>
```

---

## 40. Tab indicator slide (animated underline between tabs)

**When to use:** Tab bars, segmented controls, nav-pill switchers. Single underline element slides from old tab to new — Framer Motion `layoutId` look in pure CSS.

```css
:root {
  --tabs-dur: 280ms;
  --tabs-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --tabs-color: #fff;
  --tabs-thickness: 2px;
}

.t-tabs {
  position: relative;
  display: inline-flex;
  gap: 8px;
}
.t-tabs .t-tab {
  position: relative;
  padding: 8px 14px;
  background: none;
  border: 0;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: color var(--tabs-dur) var(--tabs-ease);
}
.t-tabs .t-tab[aria-selected="true"] { color: var(--tabs-color); }

.t-tabs .t-tab-indicator {
  position: absolute;
  bottom: 0;
  left: 0;
  height: var(--tabs-thickness);
  background: var(--tabs-color);
  border-radius: 999px;
  width: var(--ind-w, 0px);
  transform: translateX(var(--ind-x, 0px));
  transition:
    transform var(--tabs-dur) var(--tabs-ease),
    width     var(--tabs-dur) var(--tabs-ease);
  will-change: transform, width;
}

@media (prefers-reduced-motion: reduce) {
  .t-tabs .t-tab, .t-tabs .t-tab-indicator { transition: none !important; }
}
```

```js
function syncTabIndicator(container) {
  const active = container.querySelector('.t-tab[aria-selected="true"]');
  const ind    = container.querySelector('.t-tab-indicator');
  if (!active || !ind) return;
  const cRect = container.getBoundingClientRect();
  const aRect = active.getBoundingClientRect();
  ind.style.setProperty('--ind-x', `${aRect.left - cRect.left}px`);
  ind.style.setProperty('--ind-w', `${aRect.width}px`);
}
```

```html
<div class="t-tabs" role="tablist">
  <button class="t-tab" role="tab" aria-selected="true">Overview</button>
  <button class="t-tab" role="tab" aria-selected="false">Activity</button>
  <button class="t-tab" role="tab" aria-selected="false">Settings</button>
  <span class="t-tab-indicator" aria-hidden="true"></span>
</div>
```

---

## 41. Checkbox check-draw (SVG path animation)

**When to use:** Custom checkboxes, todo-item completion, terms-acceptance. Checkmark draws itself in.

```css
:root {
  --check-dur: 280ms;
  --check-ease: cubic-bezier(0.65, 0, 0.35, 1);
  --check-color: #22c55e;
  --check-bg: rgba(255, 255, 255, 0.04);
  --check-border: rgba(255, 255, 255, 0.25);
  --check-size: 20px;
}

.t-check {
  display: inline-grid;
  place-items: center;
  width: var(--check-size);
  height: var(--check-size);
  border-radius: 6px;
  background: var(--check-bg);
  border: 1.5px solid var(--check-border);
  transition: background var(--check-dur) var(--check-ease), border-color var(--check-dur) var(--check-ease);
  cursor: pointer;
}
.t-check svg { width: 70%; height: 70%; overflow: visible; }
.t-check svg path {
  fill: none;
  stroke: var(--check-color);
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 24;
  stroke-dashoffset: 24;
  transition: stroke-dashoffset var(--check-dur) var(--check-ease);
}
.t-check[data-on="true"] {
  background: rgba(34, 197, 94, 0.12);
  border-color: var(--check-color);
}
.t-check[data-on="true"] svg path {
  stroke-dashoffset: 0;
}

@media (prefers-reduced-motion: reduce) {
  .t-check, .t-check svg path { transition: none !important; }
}
```

```html
<button class="t-check" role="checkbox" aria-checked="false" data-on="false">
  <svg viewBox="0 0 16 16"><path d="M3 8.5 L7 12 L13 4" /></svg>
</button>
```

---

## Quick reference — when to reach for which

| Use case | Animation |
|---|---|
| Container width/height changes | **1. Card resize** |
| Numbers / counters / stats appearing | **2. Number pop-in** |
| Notification badges (bell, cart) | **3. Notification badge** |
| Button label changes during async | **4. Text states swap** |
| Menus, popovers, dropdowns | **5. Menu dropdown** |
| Modal / dialog open/close | **6. Modal** |
| Side panels / drawers / accordion content | **7. Panel reveal** |
| Multi-step flows / paginated content | **8. Page side-by-side** |
| Hamburger ↔ X, play ↔ pause, copy ↔ check | **9. Icon swap** |
| Premium CTA that "pulls" the cursor | **10. Magnetic button** |
| Card border lights up under cursor | **11. Spotlight border** |
| Light streak across button on hover | **12. Shine sweep** |
| 3D depth on cards under cursor | **13. Tilt-on-hover** |
| Inline link underline grows on hover | **14. Underline grow** |
| Tactile click feedback (Material) | **15. Ripple click** |
| Tactile press feel on any button | **16. Press-down** |
| Nav fill enters from cursor's side | **17. Direction-aware fill** |
| Default scroll-reveal for sections | **18. Fade-up on enter** |
| Alternating sides for long pages | **19. Slide-in from side** |
| Cascade reveal for lists / grids | **20. Stagger children** |
| Cinematic blurred-to-sharp text | **21. Blur-clear reveal** |
| Subtle scale-in for media blocks | **22. Scale-up entrance** |
| Per-word headline reveal | **23. Word-by-word** |
| Logo / illustration line draws in | **24. SVG path-draw** |
| Logo ticker / scrolling proof bar | **25. Marquee** |
| Loading placeholders | **26. Skeleton shimmer** |
| Live / online / recording dot | **27. Pulse / breathing** |
| Slow ambient color cycle | **28. Background gradient shift** |
| Inline thinking / processing loader | **29. Rotating orbit** |
| Determinate progress bar | **30. Linear progress** |
| Circular gauge / completion ring | **31. Circular progress** |
| Multi-step / wizard progress | **32. Stepped dots** |
| Unknown-duration top loader | **33. Indeterminate loader** |
| Terminal-style typing intro | **34. Typewriter** |
| Counting stat digits | **35. Number counter (odometer)** |
| Decoding / hacker glyph reveal | **36. Text scramble** |
| Animated gradient on hero text | **37. Gradient text sweep** |
| Marker bar under emphasized phrase | **38. Highlighter sweep** |
| iOS-style on/off switch | **39. Sliding switch** |
| Tab bar with sliding underline | **40. Tab indicator slide** |
| Custom checkbox with drawn check | **41. Checkbox check-draw** |

---

## When to use this library vs Framer Motion

| Use this CSS library when... | Use Framer Motion when... |
|---|---|
| Project doesn't use React (vanilla / Svelte / Vue) | React + Framer Motion already in deps |
| Simple entrance / hover / state-change | Layout morph (`layout`/`layoutId`) |
| Want zero JS for the animation | Cursor tracking / continuous input |
| Reduced-motion compliance is critical | Need spring physics |
| Server-rendered content with progressive enhancement | Interactive component morph |

Both can coexist in the same project — use this library for static pages and Framer Motion for app surfaces.

---

## Performance notes

All animations in this library:
- Animate `transform`, `opacity`, `filter` only (GPU-composited)
- Use `will-change` hints sparingly (on the elements actively animating, not parents)
- Are short enough to not cause user fatigue (<600ms typically; ambient loops can be longer)
- Have `prefers-reduced-motion` opt-out

Never adapt these animations to use `width`/`height`/`top`/`left` — that defeats the GPU acceleration and tanks mobile fps.
