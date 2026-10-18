# Anti-"AI look" rubric for STAR's designs

What makes a UI, web page, Roblox screen, UI animation or game effect read as generic machine output, and the rules
that replace each tell. Every rule is checkable: the id is the finding id of `star/design_check.py` (static, from the
code) or `star/design_render.py` (measured in a headless browser, suffix `_measured`), and `star-fast` judges the
rendered screenshot against the same list (`design_render.judge`). Score: 100, minus 15 per fail and 5 per warn;
a design passes at 70 or more with no fail (a task may ask for more: `auto.design.min_score`).

Sources (short names used below):
- [FD] Anthropic `frontend-design` skill: the five clusters of generated design, typography and copy rules.
- [TS] tasteskill v2 house rules + `references/tells.md`, from a panel study of 247 One Page Love / Awwwards
  sites: among sites scored 7.5+ versus under 6.5, icon feature cards 1% vs 28%, pill badges 14% vs 34%,
  gradients 22% vs 52%, shadows 24% vs 48%, tiny tracked caps 16% vs 57%.
- [EK] Emil Kowalski design-engineering notes (`emil-design-eng`, `review-animations/STANDARDS.md`): easing,
  durations, interruptibility, physicality.
- [AP] Apple, *Designing Fluid Interfaces* (WWDC 2018) via the `apple-design` skill; Apple HIG 44 pt targets.
- [W3] WCAG 2.2 success criterion 1.4.3 (4.5:1 body text, 3:1 large text).
- [RB] Roblox Creator Docs: UI (position and size, styling, list/grid layouts), ParticleEmitter limits (400
  particles/s per emitter, 100 on mobile guidance, Lifetime 20 s cap), BloomEffect, TweenService; the shipped
  `roblox-ui-styles` and `roblox-vfx` packs.
- [MN] `minimalist-skill` / `soft-skill` (taste-skill marketplace): spacing, radius and shadow discipline.
- [VG] Vercel Web Interface Guidelines (`web-interface-guidelines` skill): focus, targets, reduced motion.

## A. Visual tells and the rule that replaces each

| Id | Tell (fail / warn) | Rule | Source |
| --- | --- | --- | --- |
| A1.violet_gradient / A1.violet_accent | Violet or indigo accent, worse with a gradient; cream ground with terracotta accent (A1.cream_terracotta) | Palette derived from the subject: ground, ink, one accent, one tone step | FD, TS |
| A2.gradients / A2.gradient_text | Gradient backgrounds, buttons or text (3+ gradients fail, 1-2 warn) | Flat colour or a real picture; a neutral scrim under text on a photo is the one exception | TS, FD |
| A3.glass | Backdrop-blur translucent panels (2+ fail) | Opaque surfaces one tone step from the ground | TS, MN |
| A4.shadows / A4.glow | Box shadows on things at rest (4+ fail), coloured glows | Shadows only on what floats (menu, dialog); a tone step separates surfaces | TS, MN |
| A5.emoji | Emoji as icons or bullets | Words, or a drawn/real icon set with one stroke width | TS, FD |
| A6.font_families | More than two typefaces | One or two, clearly distinct, chosen for the brief | FD, TS |
| A6.default_font | Default sans (Inter/Roboto/Arial/Poppins...) at one weight | Named typeface(s), at least two weights | FD |
| A6.type_scale / A6.flat_hierarchy / A6.one_weight | 9+ sizes (no scale), or largest text under 1.8x body, or one weight for every size | 3-6 sizes on a ratio (16/20/28/40/64), weight carries hierarchy too | FD, TS |
| A6.tracked_caps | Tiny tracked-uppercase labels (3+ fail) | Sentence case at a readable size | TS, FD |
| A6.tiny_text | Text under 12 px (Roblox TextSize under 12) | 14-16 px body on web, 14+ on Roblox phones | W3, RB |
| A6.textscaled_unbounded | Roblox TextScaled without UITextSizeConstraint | Bound scaled text (min/max) | RB |
| A7.spacing_grid | Spacing values off the 4 px grid (more than a quarter fail) | 4/8/16/24/32/48/64 only; one rhythm per screen | MN, TS |
| A7.radii | Four or more corner radii | One radius per hierarchy level, at most three | FD (SaaS-card kit), MN |
| A8.contrast (static same-rule pairs) / A8.contrast_measured | Text under 4.5:1 (3:1 at 24 px+) | WCAG AA everywhere, including secondary text | W3 |
| A9.palette | Five or more chromatic hue families (four warn) | Three hue families at most, with roles | TS, FD |
| A10.centered | text-align:center in four or more rules | Left-aligned blocks on one edge; centre only a single short element | FD, TS |
| A10.icon_cards / A10.card_rows | Three identical icon-topped feature cards; six or more identical cards | Composed sections that differ; cards only when content is truly a list of equals | TS, FD |
| A10.hairlines | 1 px hairline borders (6+ fail) outside tables and forms | Space, tone steps, filled shapes | TS |
| A10.hand_positioned (Roblox) | Repeated elements positioned by hand | UIListLayout / UIGridLayout own the repeats | RB |
| A11.placeholder_copy | Lorem ipsum, "Feature 1", "Your company", "Click here" | Real words about the subject: names, numbers, times, prices | FD |
| A11.long_headline | h1 over 12 words (wraps to 3-4 lines) | A title of about five words; the rest below | TS |
| A11.index_numbering / A11.middle_dots / A11.arrow_labels / A11.accent_word / A11.eyebrow | 01/02/03 markers; "A · B · C"; "Get started →"; one styled word in the headline; eyebrow/badge above headings | Order by position or words; plain labels; a button says what happens; one face, one colour | FD, TS |
| A12.phone_overflow (measured) | Horizontal overflow at 390 px | Fluid layout: @media or clamp(), no fixed widths over 390 px (A12.fixed_width), viewport meta (A12.no_viewport_meta) | VG, FD |
| A12.offset_only / A12.no_constraints (Roblox) | Offset-only sizes; no aspect or size constraint on panels | Scale sizes with Offset padding; UIAspectRatioConstraint or UISizeConstraint | RB |
| A12.touch_target / A12.tap_targets | Buttons under 44 px (Roblox) or under 32 px rendered | 44 pt minimum targets | AP, VG |
| P1.focus_visible (info, positive) | | A visible :focus-visible style | VG |

## M. Motion (UI animation)

| Id | Tell | Rule | Source |
| --- | --- | --- | --- |
| M1.transition_all | `transition: all` | Name the properties; animate transform and opacity | EK |
| M2.ease_in | ease-in (CSS) or EasingDirection.In (Roblox) on UI | Enter/exit ease-out; move ease-in-out; hover `ease`; constant travel linear | EK, TS |
| M3.duration | UI transitions over 500 ms (warn), over 1200 ms or tweens over 1 s (fail) | Press 100-160, hover 150-200, menus 150-250, dialogs 250-400 ms; UI under 300 ms wherever possible | EK |
| M4.bounce | Overshooting cubic-bezier, Bounce/Elastic/Back easing | Bounce only for a deliberate playful or drag-release moment, 0.1-0.3 | EK, AP |
| M5.infinite | Infinite animations without a loading or marquee purpose | Nothing loops that means nothing | TS |
| M6.layout_props | Animating width/height/top/left/margin | transform and opacity only (composite-only) | EK |
| M7.scale_zero | Entering from scale(0) | Start at 0.9-0.97 with opacity 0 | EK |
| M8.fade_up_everywhere | Four or more fade/rise entrance animations | One orchestrated moment per page at most | FD, TS |
| M9.reduced_motion | Motion with no prefers-reduced-motion rule | Respect reduced motion | VG, AP |
| M10.no_feedback (Roblox) | Buttons with no hover or press feedback | 0.1-0.15 s Quad Out colour tween; press scale 0.96 | RB, EK |
| M11.deprecated_tween | GuiObject:TweenPosition / TweenSize | TweenService:Create | RB |
| (judge) | Transitions that cannot be interrupted | Transitions over keyframes for state changes; springs for gestures, started from the current value | EK, AP |

## V. Game VFX (Roblox)

| Id | Tell | Rule | Source |
| --- | --- | --- | --- |
| V1.emitter_count | More than 6 emitters in one effect (12+ fail) | Three layers do the job: flash, debris, smoke | RB |
| V2.rate / V2.burst | Rate over 100/s per emitter (400 fail); bursts over 200 | Mobile budget first; one burst via Emit(n) | RB |
| V3.lifetime | Lifetime over 6 s (20 s fail) | Flash 0.1 s, debris under 1 s, smoke 1-2 s | RB |
| V4.overdraw | Particles over 15 studs mostly opaque | Big particles mostly transparent; avoid stacked translucent layers | RB |
| V5.colour_restraint | Four or more hue families | One hot accent, one body colour, one dark debris tone: a readable silhouette | TS (colour roles), roblox-vfx pack |
| V6.bloom / V6.bloom_threshold / V6.all_additive | Bloom Intensity over 1 (2 fail), Threshold under 0.8, every emitter additive | Bloom at most 1, threshold 0.8+; LightEmission 1 only for the flash and sparks | RB |
| V7.no_layering | One burst, no phases | Anticipation (0.05-0.1 s), impact, aftermath; Size and Transparency change over life (V9.flat_size info) | roblox-animation-craft pack (anticipation, follow-through) |
| V8.no_cleanup | Continuous emitters never disabled or destroyed | Debris:AddItem or Enabled = false | RB |
| (judge) | Noisy over-bloom, unreadable silhouette on the rendered frame | Vision pass on a frame against this table | |

## How the checker and judge divide the work
- Static (`star/design_check.py`): every id above except the measured ones; works on the fenced blocks of an answer
  (```html / ```css, ```luau Instance.new trees, or a JSON layout tree), so night school can grade an answer with no
  browser (`auto.design` in a task).
- Measured (`star/design_render.py`, Node + Chromium): overflow at 390 px, computed contrast of real text runs,
  fonts actually rendered, text under 12 px, tap targets; screenshots at 1280 and 390 px.
- Judge (`design_render.judge`, star-fast vision): a 0-10 "AI look" grade with the tells it saw; calibrated on good
  and bad pages (`python -m star.design_render --calibrate <dir>`), numbers in docs/agents/design-school-20261018.md.
