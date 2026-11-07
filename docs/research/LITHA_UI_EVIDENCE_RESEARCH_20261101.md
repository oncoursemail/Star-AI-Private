# Evidence, accessibility and motion research for Litha

Retrieved 2026-11-01 UTC. Primary sources only. This research did not install any external tool, execute external skill instructions, or run a browser/Roblox engine. Repository observations refer to the local Litha baseline inspected during this task. Recommendations are engineering judgments, not measured improvements to Litha's design quality.

## Research conclusion

The implementation in [the main report](LITHA_UI_RESEARCH_20261101.md) extends Litha's existing `starry_eye_quality.audit`. The research below explains that choice. It already validates bounded screenshot files, declared geometry, contrast, hit targets, captured-frame changes, completed event traces and performance budgets. It explicitly distinguishes these from trusted execution receipts and artist approval. The useful gap is coverage: every supplied check can pass even if mobile, loading/error/empty, keyboard, or reduced-motion states were never supplied. A bounded optional UI contract can require particular captures and report missing evidence separately from failing evidence.

The best sequence is: articulate intended hierarchy and interaction -> build native components -> render representative states -> inspect measured layout/semantics -> review images for visual intent -> repair specific failures. A collection of attractive screenshots is not a complete interaction specification.

## Evidence boundaries

| Evidence | Useful conclusion | Unsupported conclusion |
|---|---|---|
| Authored design tokens and declared element rectangles | Internal consistency and intended geometry | Browser/engine actually rendered these values |
| Decodable screenshot at expected dimensions, bound to a source hash | A specific image was supplied for this source revision | Which runtime, state, accessibility preferences or interactions produced it unless separately recorded |
| Live DOM/engine measurements with capture context | Observed bounds, resolved properties, text clipping in one state | Every other viewport/state passes |
| Playwright/axe and interaction traces | Specific automated assertions passed in the tested context | Complete WCAG conformance, delightful aesthetics or inclusive usability |
| Screenshot baseline comparison | Rendering did or did not change from a chosen baseline | Baseline is good; animation feels good; focus is correct |
| Human visual and keyboard review | Contextual hierarchy, coherence, usability and intended composition | Universal preference or proof about unseen states |

Store the evidence kind, source revision, viewport coordinate space, dimensions, UI state, theme, input mode, locale/text-size and motion preference. Missing items should be `insufficient_evidence`, not a numerical quality bonus. Supplied scenario labels remain declarations unless a trusted collector binds them to execution.

## High-value additions beyond the linked list

| Source | Mechanism worth adopting | Limit / decision for Litha |
|---|---|---|
| [Playwright accessibility testing](https://playwright.dev/docs/accessibility-testing) | Navigate to the state first, then run `@axe-core/playwright` on the rendered DOM; scan dialogs/menus after opening them | Automated tests cover only some accessibility problems; add keyboard and human checks. Adopt as an optional web verification adapter, not a mandatory runtime dependency. |
| [Playwright screenshot comparison](https://playwright.dev/docs/test-snapshots) | Stable screenshots and approved reference images per environment | Rendering varies with OS, browser, fonts and hardware. Baseline similarity measures regression, not design merit. |
| [Playwright screenshot assertions](https://playwright.dev/docs/api/class-pageassertions) | Explicit animation policy and visual diffs | Screenshot assertions disable animations by default, fast-forward finite animations and cancel infinite ones. This cannot establish that reduced-motion behavior works. Test motion separately. |
| [React Aria quality](https://react-aria.adobe.com/quality) | Reuse keyboard/focus/press semantics and state attributes, with unstyled composition | It does not supply the final art direction. Labels, contrast, hit areas, focus styles, RTL layout and motion policies still belong to the product. Prefer the project's existing primitives before adding another component stack. |
| [Storybook interaction tests](https://storybook.js.org/docs/writing-tests/interaction-testing) | Represent initial component states as stories, then exercise user actions in `play` functions | Adopt the explicit state-fixture idea immediately; add the dependency only if the React project needs it. A render-only story does not test interaction. |
| [Motion accessibility](https://motion.dev/docs/react-accessibility) and [MotionConfig](https://motion.dev/docs/react-motion-config) | `reducedMotion="user"`; custom `useReducedMotion` branches | Current default is `never`. The user policy suppresses transform/layout animation while allowing opacity/color changes. Match the installed package version before generating imports. |
| [Roblox accessibility](https://create.roblox.com/docs/production/publishing/accessibility) | Native user preferences, adaptive text, transparent-background handling and alternative cues | Use real editable GUI instances and native properties. Web CSS-pixel thresholds do not automatically become Roblox conformance rules. |
| [W3C modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/) | Focus enters the dialog, stays in its tab sequence, Escape closes it, focus generally returns to the invoker | Merely adding `role="dialog"` and `aria-modal` is not the interaction. Test the keyboard path and underlying inert state. |

## Standards precision and a concrete bug

[WCAG 2.2 contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) uses 4.5:1 for normal text and 3:1 for qualifying large text, with stated exceptions including inactive controls. The computed value must not be rounded before deciding whether it reaches the threshold. Font size and weight determine large-text eligibility; a caller's `large_text` flag is only a declaration. Opaque authored color pairs can be checked statically, but translucent backgrounds, imagery, gradients and overlays need resolved context. Anti-aliased glyph-edge sampling is not the normative color calculation.

Found `starry_eye_quality._contrast` rounding to three decimals before comparison. Concrete counterexamples, independently computed with the WCAG luminance formula:

| Foreground / background | True ratio | Existing rounded value | Correct outcome |
|---|---:|---:|---|
| `#00827F` / `#000000` | 4.499513915165525 | 4.5 | Below normal-text AA threshold |
| `#004FCD` / `#000000` | 2.9999484857479417 | 3.0 | Below large-text AA threshold |

Return full precision; round only for display. Root is implementing this regression fix.

[WCAG 2.5.8 target size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum) is AA and specifies 24 by 24 CSS pixels or one of five exceptions: spacing, equivalent control, inline, user-agent control, essential presentation. Do not claim that every target under 44 pixels fails AA. A product may deliberately use 44+ as its own touch design target.

[Reflow 1.4.10](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) is AA: vertically scrolling content should work at a width equivalent to 320 CSS pixels, with exceptions for content requiring two-dimensional layout. A 320 CSS-pixel viewport is equivalent to a 1280-pixel viewport at 400% zoom for this purpose; a generic overflow detector still needs intentional 2D exceptions.

[Focus Not Obscured 2.4.11](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html) is AA and requires that the focused component not be entirely hidden by author-created content. Fully unobscured is a stronger AAA outcome. This is distinct from a visible focus indicator.

[Animation from Interactions 2.3.3](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html) is AAA. Nonessential interaction-triggered motion can be disabled. Honoring user reduced-motion preferences is a sensible Litha product policy; do not mislabel this particular criterion AA. Automatically started animation has additional considerations under Pause/Stop/Hide.

## Native Roblox: current facts and version drift

Pinned documentation repository: `Roblox/creator-docs@c8f5276703948ef4868c9b9fd44fae619dbe2f11`, committed 2026-10-29T00:17:33Z. Repository metadata identifies CC-BY-4.0 documentation licensing. This is documentation evidence, not a claim that this environment ran a particular Studio build.

- [Accessibility source](https://github.com/Roblox/creator-docs/blob/c8f5276703948ef4868c9b9fd44fae619dbe2f11/content/en-us/production/publishing/accessibility.md), blob `6a34ac3943c78f9a6e2a8d8addc134926fc5d0f4`.
- [GuiService source](https://github.com/Roblox/creator-docs/blob/c8f5276703948ef4868c9b9fd44fae619dbe2f11/content/en-us/reference/engine/classes/GuiService.yaml), blob `11e1cbab74476fe97f951213af1c4f0a0935c76e`.
- [StyleQuery source](https://github.com/Roblox/creator-docs/blob/c8f5276703948ef4868c9b9fd44fae619dbe2f11/content/en-us/reference/engine/classes/StyleQuery.yaml), blob `873d4484dc5a31640bdcd33e1c5f379ae0560009`.

### Motion and transparency

`GuiService.ReducedMotionEnabled` is read-only and not replicated; current YAML permits script reads. Query it when constructing a transition and subscribe through `GetPropertyChangedSignal` when running continuous effects. The official guide proposes either snapping to the final state or replacing positional movement with a fade. An implementation should preserve the semantic end state, cancel/replace any already running animation consistently, and release event connections when its component is destroyed. Those lifecycle points are engineering recommendations rather than claims that the guide supplies a complete component implementation.

`PreferredTransparency` ranges from 0 to 1. One means the authored transparency; zero means opaque. Save each authored baseline and use `baseline * preference`, as the official sample does. Repeatedly multiplying an already adjusted value produces drift. Include instances added after initialization and remove destroyed/tag-removed objects from tracking. Increasing opacity does not automatically fix contrast if the authored background itself is poor.

### Text size

`PreferredTextSize` provides Medium (default), Large, Larger and Largest. `TextScaled=true` prevents that preference from resizing the text. `UITextSizeConstraint` still limits minimum/maximum size. Automatic sizing and wrapping can accommodate larger rendered text, while the two TextService measurement methods described by the docs honor the preference. Test actual clipped bounds after changing preference and with long/localized strings; do not assume property presence alone proves accessibility.

The [official text-scaling announcement](https://devforum.roblox.com/t/introducing-text-scaling-setting-studio-beta/3136967) was originally a Studio beta in August 2024 and was updated to general availability on August 25, 2025 ([release update](https://devforum.roblox.com/t/introducing-text-scaling-setting-studio-beta/3136967/78)). A stale design skill can therefore wrongly describe this setting as beta or absent.

### Native styles and queries

[UI styling](https://create.roblox.com/docs/ui/styling) supports StyleSheet rules, attributes as tokens, related themes with matching token sets, StyleLink propagation and query selectors. This can preserve editable native structure while making layout and accessibility changes consistent.

The [official full-release announcement](https://devforum.roblox.com/t/full-release-stylequery-more-styling-features/4566519?page=3) records May 11, 2026 release and additional PreferredTextSize queries. The pinned YAML is the stronger present API reference: StyleQuery conditions include `AspectRatioRange`, `MinSize`, `MaxSize`, `PreferredInput`, `PreferredTextSize`, `ReducedMotionEnabled` and `ViewportDisplaySize`. It documents inclusive minimum and exclusive maximum comparisons. Invalid condition names and type mismatches can silently fail. Future compiler support should validate condition names and native value types before emission, then verify effective runtime state. Do not copy the older beta-only limitation from the original announcement body.

This is a roadmap item rather than a justified large compiler rewrite in the present patch. The existing generated UI should first gain accurate diagnostics and explicit coverage. Also, official CSS comparison examples are conceptual analogies, not a promise that every CSS input/media condition maps exactly onto Roblox behavior.

## Research benchmarks: useful evaluation methods, not imported leaderboard claims

[Design2Code, NAACL 2025](https://aclanthology.org/2025.naacl-long.199/) evaluates screenshot-to-code on 484 real pages and combines automatic metrics with human evaluation. Its [project](https://salt-nlp.github.io/Design2Code/) separates visual similarity, block match, text, position and color. The useful lesson for Litha is to track distinct failure dimensions; one attractive-looking or high-similarity image can hide missing content. Do not reuse old model rankings as current recommendations, or claim its benchmark measures Litha.

[DesignBench](https://arxiv.org/abs/2506.06251) and its [repository](https://github.com/WebPAI/DesignBench) expand evaluation across generation, editing and repair, and across vanilla HTML, React, Vue and Angular. The source annotation guide distinguishes compile, layout, position, color, text, size and missing-element failures. This supports evaluating Litha on edit preservation and repair in addition to creation. GitHub metadata does not identify a repository license, so treat it as a research reference and review dataset/code terms separately before copying or training.

## Suggested bounded verification matrix

Use a small risk-based set of scenarios instead of multiplying every axis into thousands of captures. For example: desktop default; phone portrait default; phone landscape; keyboard menu/dialog; empty; loading; validation/network error; long text; large text; reduced motion. Add theme or locale variants only when relevant. The contract must distinguish rendering at an exact viewport from merely naming a device. Specify CSS pixels for web and native viewport pixels for Roblox, and record DPR if images are involved.

Each required scenario should reference actual existing source-bound captures. A screenshot with missing geometry/semantics is weaker than a measured live inspection and must stay labeled accordingly. Dimensions, duplicate identifiers, unbounded collections, unknown keys, mismatched states and missing captures need negative tests. Existing contracts should keep their prior behavior when the new optional feature is absent.

For a later browser collector: wait for the intended state and font loading, capture screenshots with deterministic viewport/DPR/browser context, inspect visible text/targets, run axe in the same state, and exercise keyboard focus. Do not suppress screenshot changes through broad masks or arbitrarily generous pixel tolerances. Keep human visual review separate, especially for hierarchy, rhythm, originality and whether the interface serves the user's task.

## Repository snapshot and reuse metadata

These are snapshot identities and GitHub-reported license identifiers, not an assertion that all files, fonts, datasets, premium products or hosted services share the repository license. No external code was copied in this research.

| Repository | Pinned revision | Metadata license |
|---|---|---|
| microsoft/playwright | `deb7e86201e26cb4a8e25191fce5ef2f7a28aa87` | Apache-2.0 |
| dequelabs/axe-core | `6b52b841461bd23345970b91ec75fdaff6bad31a` | MPL-2.0 |
| adobe/react-spectrum | `a562b335e645c172ec5a940b3e47ccdadbeeaa15` | Apache-2.0 |
| motiondivision/motion | `7415b6cd14dfdb35d91dfc5b9758994444cc228b` | MIT |
| storybookjs/storybook | `43a13889a499ee209a52dc5f874c0ad84b3eeec3` | MIT |
| NoviScl/Design2Code | `7a575e4c33f417c4be5c64072b8f5798de0d0f99` | MIT |
| WebPAI/DesignBench | `a1e58d66ecbf1f77848bc5529ee7bbbe33bc25ba` | Not identified |
| Roblox/creator-docs | `c8f5276703948ef4868c9b9fd44fae619dbe2f11` | CC-BY-4.0 |
