---
name: design-anti-ai-look
description: Make a UI, web page, Roblox screen, UI motion or game effect look intentional and human-made: the tells of generic AI design, the rules that replace them, and reference layouts (references/layouts.md).
---
# design-anti-ai-look
## When to use
Any request to design, style, lay out or polish a web page, app screen, Roblox HUD/menu/shop/inventory, UI animation or game VFX. Design the thing the request is about, with its real content; never a template with blanks.

## Do first (two passes)
1. Plan, in four lines, before any code: subject and audience; palette of 3-5 named colours with roles (ground, ink, one accent, one tone step); one or two typefaces with a size scale; the layout idea (what sits where, left-aligned by default). If the plan is what you would write for any brief, change it.
2. Build to the plan, then remove one ornament before answering.

## Never (these mark a design as generated)
- Violet/indigo/pink gradients, gradient text, glowing or gradient buttons; cream background with a terracotta accent; near-black with one neon accent and glows.
- Glassmorphism (backdrop blur, translucent panels), floating pill navigation.
- Emoji as icons or bullets. Three identical icon-topped feature cards. Rows of identical cards with the same shadow.
- Tiny tracked uppercase labels, eyebrows, pill badges above headings; 01/02/03 index markers; monospace labels; meta joined with middle dots; an arrow glued to button text; one styled accent word in the headline.
- Everything centred; a headline that runs three or four lines; lorem ipsum, "Feature 1", "Your company", "Click here".
- Grey text under 4.5:1 contrast; text under 12 px (Roblox TextSize under 12); more than two typefaces; one weight for every size; four or more accent hues; spacing values off the 4 px grid; four or more corner radii.

## Always
- Type: one or two typefaces, named on purpose; 3-6 sizes on a ratio (for example 16, 20, 28, 40, 64); at least two weights; body line-height 1.4-1.6; measure under 75 characters.
- Spacing: multiples of 4 (8/16/24/32/48/64); one spacing rhythm per screen; align text blocks to one left edge.
- Colour: ground, ink, one accent, one tone step for surfaces; structure comes from space and tone steps, not lines, shadows or boxes. Shadows only on things that truly float (menu, dialog).
- Content: real words about the subject (names, numbers, times, prices); a button says what happens ("Reserve a loaf"); errors say what went wrong and what to do.
- Responsive: web pages with a viewport meta tag, @media or clamp(), no fixed widths over 390 px; Roblox with Scale sizes plus Offset padding, UIListLayout/UIGridLayout for repeats, UIAspectRatioConstraint or UISizeConstraint on panels, TextScaled only with UITextSizeConstraint, buttons at least 44 px tall.
- Web output: one complete HTML document with inline CSS in a ```html block; a :focus-visible style; prefers-reduced-motion when anything moves.
- Roblox output: a LocalScript in a ```luau block building the tree with Instance.new, properties set per object, a Theme table for colours, fonts and spacing.

## Motion (UI animation)
- Animate only to show what changed or to answer an action. No fade-up on every section, no hover lift on every card, nothing infinite that is not a loading or marquee state.
- Enter/exit: ease-out (CSS cubic-bezier(0.22, 1, 0.36, 1); Roblox Enum.EasingStyle.Quad/Quint with EasingDirection.Out). Never ease-in on UI; no Bounce/Elastic/Back except a deliberate playful moment.
- Durations: press 100-160 ms, hover 150-200 ms, menus 150-250 ms, dialogs 250-400 ms; UI under 300 ms wherever possible, under 500 ms always. Leaving is quicker than arriving.
- Animate transform and opacity only (web); specify properties, never transition: all. Prefer transitions (interruptible) to keyframes for state changes. Press feedback: scale 0.96-0.98. Never enter from scale(0).
- Roblox: TweenService:Create with TweenInfo (not TweenPosition/TweenSize); AutoButtonColor = false when you animate the colour yourself.

## Game VFX
- One readable silhouette per effect; at most three hue families (one hot accent, one body colour, one dark debris/smoke tone). Not everything additive: LightEmission 1 for the flash and sparks, 0 for debris and smoke.
- Time it in phases: anticipation (a small flash or inward pull, 0.05-0.1 s), impact (one burst, Emit(n)), aftermath (debris with gravity, smoke that grows and fades for 1-2 s). Size and Transparency change over life (NumberSequence with keypoints), never constant.
- Budget: Rate at most 100/s per emitter for mobile (engine limit 400), bursts under 200 particles, Lifetime under 6 s, at most 6 emitters per effect, large particles (over 15 studs) mostly transparent; remove or disable what you create (Debris:AddItem). BloomEffect Intensity at most 1, Threshold at least 0.8.

## Checklist
Palette 3-5 colours with roles; 1-2 typefaces, 3-6 sizes, 2+ weights; spacing on 4 px; left edge aligned; real copy; contrast 4.5:1; no gradients/glass/emoji/eyebrows/index numbers; phone width works; motion ease-out under 300 ms with reduced-motion; VFX three hues, phased, inside budget. Reference layouts: references/layouts.md (web landing, dashboard, form; Roblox shop, HUD, menu, inventory; VFX impact).

## Sources
Anthropic frontend-design skill (AI-look traits list, type and copy rules); Awwwards/One Page Love study in the tasteskill house rules (gradients 22% of top sites vs 52% of weak, shadows 24% vs 48%, tracked caps 16% vs 57%); Emil Kowalski design engineering notes (easing, durations, interruptibility); Apple WWDC "Designing Fluid Interfaces"; WCAG 2.2 contrast (1.4.3); Apple HIG 44 pt targets; Roblox Creator Docs UI, ParticleEmitter (400/s, 20 s), BloomEffect, TweenService; Vercel web interface guidelines.
