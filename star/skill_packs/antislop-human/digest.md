# Anti-slop accessibility (anti-slop-human v3.2.21, MIT)
- Contrast (WCAG): body text at least 4.5:1, large text (18 px and up, or 14 px bold) at least 3:1, UI borders and icons at least 3:1. Compute the ratio from the real colours, never judge by eye. Check text over gradients and images at the worst spot, and in every theme you ship.
- Keyboard: every control reachable with Tab in a logical order, operable with Enter or Space, Escape closes overlays; use real buttons and links, not clickable divs.
- Focus: a visible focus ring on every interactive element, never removed without a replacement.
- States: hover, focus, active, disabled, loading, error, empty and success all exist and are distinguishable without colour alone; errors say what to do.
- Zoom and mobile use: layout survives 200% zoom and text-size changes; do not block pinch zoom; respect prefers-reduced-motion; give images useful alt text.
