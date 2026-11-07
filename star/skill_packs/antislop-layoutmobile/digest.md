# Anti-slop mobile layout (anti-slop-layoutmobile v3.2.21, MIT)
- Design mobile first and check about 360, 768 and 1280 px widths; use content-driven breakpoints and fluid sizing (clamp, rem, min/max), not fixed pixel widths.
- No horizontal page overflow: images and tables get max-width and overflow rules, long words and URLs wrap, grids use auto-fit/minmax or stack to one column on phones.
- Text never escapes its container; cards never collide or clip; spacing stays consistent across breakpoints.
- Tap targets at least 44 px with room between them; hover-only interactions need a touch and keyboard path.
- Mobile navigation: a menu that opens and closes, does not cover content, and keeps the primary action reachable. Use dvh and safe-area insets rather than 100vh on full-screen layouts.
