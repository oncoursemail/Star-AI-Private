# Litha: UI research, concrete fixes and evidence coverage

Research and implementation date: **2026-11-01 UTC**.
Repository baseline: `oncoursemail/Star-AI-Project`, `star/next` at
`a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f`.
Task branch: `feat/litha-ui-evidence-20261101`.

## Outcome

The useful improvement is to connect deliberate design decisions to explicit,
inspectable evidence. Litha already has a design database, structured design
notes, native Roblox UI generation, a Studio device lab and visual auditing.
This change extends those capabilities with a bounded UI coverage contract and
fixes two demonstrated contrast defects. It adds no model, hosted service,
package dependency or imported third-party skill.

The research covers every entry in the linked
[Awesome AI Tools for UI snapshot](https://github.com/maxbogo/awesome-ai-tools-for-ui/tree/680b351764199b9b6b4352d3ea5af0bce927b6ed),
then follows stronger primary sources for accessibility, component behavior,
motion, evidence collection and native Roblox APIs. Coverage depth is recorded
per entry. A public page review is not a runtime audit or a measured endorsement.

Read the companion material according to the question:

- [Complete source review and 64-entry decision matrix](LITHA_UI_SOURCE_REVIEW_20261101.md).
- [Machine-readable source catalog](litha-ui-source-catalog-20261101.json).
- [Pinned repository revisions and license observations](litha-ui-source-pins-20261101.json).
- [Evidence, accessibility, motion and Roblox research](LITHA_UI_EVIDENCE_RESEARCH_20261101.md).
- [Contract format, activation and examples](../guide/ui-evidence-contract.md).
- [Recorded local validation](litha-ui-validation-20261101.json).

## What was actually added

### Required UI cases in the existing audit tool

`workspace_starry_eye_audit` accepts an optional `ui_contract_path` when
`STAR_UI_EVIDENCE=on`. The new `star/ui_evidence.py` inspector checks one to twelve
explicit cases. Each identifies a screen, state, viewport, input method, motion
condition, required layout elements and optionally an ordered event sequence.
The feature is off by default. An explicitly requested contract while disabled
returns an error instead of silently producing an ordinary audit result.

An inventory example might require a desktop default screen, a phone screen,
an empty inventory, a loading state, an error with retry, a keyboard-operated
details dialog and a reduced-motion case. The contract makes those expectations
concrete. If only the desktop case exists, the result is insufficient evidence.
The model cannot satisfy the other cases by omitting them from its observations.

Each observation binds to the current declared source set, exact PNG bytes and,
when used, exact trace bytes. Labels must match the required conditions. Web
viewport dimensions use CSS pixels with an explicit PNG-to-viewport scale;
Roblox uses rendered pixels at scale one. Required event sequences are bound to
their case and capture, so one global event sequence cannot cover every device
and input mode. Contracts, cases, observations and viewport objects reject
unknown fields and malformed values; existing manifest and trace metadata can
still contain additional fields.

The top-level audit distinguishes failed checks from missing evidence. The
nested successful coverage status deliberately says `declared_coverage_complete`.
Matching a label such as `keyboard` does not prove keyboard operation. Hashes
detect changed bytes; they cannot prove how the image was produced. Required
element IDs refer to supplied layout records, not visual recognition. The report
explicitly keeps runtime execution, capture authenticity, accessibility
conformance, honored motion preference and owner approval unproven.

The existing evidence identity still covers source and image bytes. A separate
`ui_audit_key` also fingerprints the contract, manifest and trace, so changing
requirements or labels changes the audit identity. Counts remain accurate even
when the existing 100-finding display cap omits records. No approval or execution
permission is created by these hashes or results.

Implementation: [inspector](../../star/ui_evidence.py),
[existing audit integration](../../star/starry_eye_quality.py),
[workspace dispatch](../../star/workspace.py). Tests exercise the actual agent
loop through a scripted offline model as well as the pure inspector.

### Contrast thresholds now use the actual value

The previous visual auditor rounded contrast to three decimals before comparing
it with the threshold. That accepted colors just below the requirement.

| Foreground on black | Actual contrast | Previous compared value | Correct result |
| --- | ---: | ---: | --- |
| `#00827F` | 4.499513915165525 | 4.5 | Below the normal-text 4.5 threshold |
| `#004FCD` | 2.9999484857479417 | 3.0 | Below the qualifying-large-text 3.0 threshold |

The calculation now keeps full precision for the decision and formats only the
displayed number. This follows the explicit threshold instruction in
[W3C's contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
Regression cases run through the complete audit, not just a helper formula.

### Roblox contrast diagnostics include interaction states

The native compiler previously checked only the base declared color pair. A
black button with white text and a hover state changing its background to white
produced no warning. The validator now checks the base and each declared hover,
pressed, selected or disabled state, using the same base-reset semantics as the generated code.
Pressed styling does not inherit an unrelated hover override.

It also distinguishes known opaque backgrounds from unresolved backgrounds.
Fully transparent elements can use a known ancestor backdrop. Fractional
transparency, missing native color declarations and unresolved ancestors remain
indeterminate. An explicitly opaque child can establish its own known backdrop.
The compiler no longer implies that an unspecified native control color simply
inherits a parent color.

These are authoring diagnostics, not a WCAG certification. The conservative
4.5:1 target is identified as such, including the inactive-control exemption in
disabled-state messages. Actual rendering, text metrics, overlapping content
and translucent compositions still need runtime inspection. The emitted Luau
was unchanged for the 23 representative specifications compared with baseline.
Implementation: [compiler](../../star/roblox_ui_compiler.py);
[state-contrast regressions](../../tests/test_roblox_ui_contrast.py).

## What Litha already had, and why that changes the adoption decision

The local baseline was inspected before selecting the patch. Counting features
already present as new research gains would be misleading.

| Capability at the inspected baseline | Evidence in Litha | Consequence |
| --- | --- | --- |
| Offline style and palette retrieval | `star/design_db.py`; 88 styles, 192 palettes, 74 font pairings, 119 UX rules | Keep the existing bounded search rather than importing another complete catalog. |
| Data provenance | `star/data/design/ui-ux-pro-max/PROVENANCE.json`; upstream `7246805992a42b7bba37d4cac83b01416f0c6c44` | Existing four-table MIT subset has hashes and attribution; any update should retain this discipline. |
| Structured design notes | `star/design_md.py` and `star_design_md` | Extend actual project design memory; do not create a parallel incompatible format casually. |
| Editable native Roblox UI | `roblox_ui_designer.py`, `roblox_ui_compiler.py` | Share design intent with web work, then generate real engine instances and native interactions. |
| Live Studio device checks | `roblox_ui_check.py` | Use actual engine bounds, text fitting and screenshots when a Studio run is available. |
| Cross-engine visual checks | `starry_eye_quality.py`, `creative_review.py` | Add required coverage to the existing path. |
| Frontend motion policy | `frontend/src/MotionPolicy.tsx`, `motion.ts` | OS and saved reduced-motion preferences are already combined; preserve this policy. |
| Frontend accessibility tests | `frontend/src/a11y-axe.test.tsx` | The actual shell is tested in jsdom, but rendered color contrast is explicitly disabled there. |

A concrete retrieval probe exposed a later improvement opportunity:
`design_db.recommend("Roblox inventory native editable phone accessible minimal")`
returned an “AI-Native UI” style and a web “ARIA Labels” rule. Lexical retrieval
can surface useful vocabulary while missing platform intent. This patch does
not claim to have fixed retrieval. The next retrieval change should filter by
target and evidence type before ranking, then label a fallback honestly.

## Findings from the linked catalog

The pinned catalog has **64 entries**: 25 skills, 13 apps, six MCP/plugin entries,
12 design tools and eight resources. Some refer to the same ecosystem twice.
Its complete four-entry tree has no license file, and GitHub detects no license.
The catalog is a discovery index, not a package whose contents can all be
installed or redistributed under one permission.

The source review pinned 40 relevant repositories. Eight additional snapshots
cover the broader evidence and native-platform research: 48 repository snapshots
in total. Snapshot identities
make the findings reproducible; they do not imply every repository received the
same depth of code review. The machine-readable catalog records that depth.

| Source | Mechanism worth learning from | Decision for Litha |
| --- | --- | --- |
| [Impeccable](https://github.com/pbakaus/impeccable/tree/4f956490f0056ae1ff5ea80372cf56e83c001d3c) | Durable product/design context, focused commands, separate source and rendered checks | Adopt the separation of evidence and taste; evaluate its engine/hooks independently. |
| [UserInterface.wiki](https://github.com/raphaelsalaja/userinterface-wiki/tree/256a954080c8bcf1b1ceb1e2a4079d1f24cf593a) | Small stable rule IDs and individual reference files | Retrieve a relevant subset; keep narrow style recipes advisory. |
| [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/bf41cbc3ce63e30c922e58ef48741ba6133f9aa9) | Local BM25, calibrated retrieval, persisted master and page decisions | Retain the existing subset; evaluate target-aware retrieval before a corpus refresh. |
| [Anthropic frontend-design](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design/SKILL.md) | Ground direction in subject and content; plan, build, inspect | Strong fit for authored UI; guidance alone is not verification. |
| [Taste Skill](https://github.com/Leonxlnx/taste-skill/tree/12af471f627f866411b4bd785b19646d3672784c) | Before/after review at multiple viewports; separate app-screen path | Use the review concept; reject marketing quotas for the working interface. |
| [shadcn skills](https://ui.shadcn.com/docs/skills) | Inspect real configuration and installed primitives before composing | Apply the project-awareness idea; add no second component system by default. |
| [Interface Design](https://github.com/Dammyjay93/interface-design/tree/2f9be3206855bcb2d1d0af262c8bae25cba6658d) | Preserve durable decisions and product-interface consistency | Useful model for future design memory. |
| [Design and Refine](https://github.com/0xdesign/design-plugin/tree/913a7ab2ac7e0f48eab77c93f2f5376150864b02) | Compare alternatives against the same brief, then synthesize feedback | Workflow reference; no license file found at the inspected snapshot. |
| [Google DESIGN.md](https://github.com/google-labs-code/design.md/tree/6e5da5382f41edbba9d73b2c62f33f32e9971f15) | Structured tokens plus rationale, validation and exports | Keep current support; use an explicit adapter for later alpha-format changes. |

### Several sources conflict, so copying them together would be incoherent

The catalog describes Impeccable as 20 commands; its inspected current source
documents 24 and 62 deterministic detector rules. Its source and browser scans
observe different things. A source-pattern check cannot determine rendered
contrast or whether a control works. Those boundaries informed the new contract.

Taste's inspected marketing workflow requires at least four pictures and eight
animated elements. Its application-screen workflow is separate. Other reviewed
skills favor one restrained, meaningful motion event. Neither a motion quota
nor a universal ban can substitute for the task. Litha's operational UI should
show state changes clearly and stay calm during repeated work.

UserInterface.wiki's useful micro-rules sit beside narrow recipes such as exactly
three SVG lines, a 32-pixel hit target and universal sub-300ms timing. These can
be house preferences, not general standards. Vercel's reviewed guidance also
contains a conflict: its README offers a zoom-limiting fallback while the review
command flags that same restriction. Preserve zoom and evaluate the actual
criterion rather than importing every sentence as an instruction.

The catalog's [OpenAI frontend article](https://developers.openai.com/blog/designing-delightful-frontends-with-gpt-5-4)
supports explicit constraints, real content, visual references and rendered
inspection. Its example prompt also contains promotional-page assumptions about
heroes, imagery and motion. Those assumptions should stay scoped to that kind
of work. The article explicitly preserves an existing design system; it is not
evidence that Litha's operational shell should become a promotional page, or
that a different local model will reproduce the illustrated results.

## A design process appropriate for Litha

The following is an engineering recommendation drawn from the review. The
current patch implements evidence coverage and diagnostics; it does not install
this entire generation workflow or retrain a model.

**Start with the task and existing system.** Identify the user, the action that
must succeed, actual content, supported devices, accessibility preferences and
the component library already in the project. Preserve deliberate product
choices. Litha's own black-and-gold identity belongs to its shell; a user's
cartoon game, education app or editorial site needs its own suitable direction.

**Make a compact design brief.** Record type roles, semantic colors, spacing,
density, navigation structure, component states and the intended role of motion.
Give each prominent element a purpose. A tool that suggests a font pair has not
decided how a five-digit inventory count, long label or error message will fit.
Use realistic content early so layout choices are tested against the real task.

**Compose installed primitives.** Existing buttons, fields, dialogs and menus
carry behavior that a hand-built imitation can accidentally discard. On web,
reuse correct semantics and focus management. In Roblox, preserve editable
ScreenGui/Frame/TextButton and layout/constraint objects. A screenshot of a
beautiful menu is a reference, not the delivered native hierarchy.

**Choose representative cases before implementation is declared complete.**
Default, empty, loading, error, disabled, focused and success are common state
categories, but the product decides which apply. Include long content, relevant
input modes and motion preference. The new contract makes a bounded subset
explicit. It is intentionally not an automatic claim of exhaustive coverage.

**Inspect and repair concrete defects.** Combine real measurements with visual
review. Fix clipped labels, overlapping actions, lost focus, unreadable states
and confusing recovery before adding decorative polish. A screenshot comparison
can identify change; it cannot decide whether the initial design was good.

**Retain the decision and evidence.** Record which project values were preserved,
what changed and what was actually exercised. A future local rule index should
separate functional defects, accessibility criteria, framework constraints,
owner requirements and overridable taste suggestions. A style exception should
be narrow and explained, not a global switch that disables the quality checks.

## Beyond the list: stronger validation sources

### Web behavior, semantics and screenshots

[Playwright's accessibility guide](https://playwright.dev/docs/accessibility-testing)
scans the page in its current state; opening a menu or dialog before scanning is
therefore essential. It also states that automated accessibility tests find only
some issues. Keyboard checks and human assessment remain necessary.
[React Aria](https://react-aria.adobe.com/quality) is useful as a reference for
semantics, focus, input handling and internationalization, while visual labels,
contrast and layout still belong to the product.

[Playwright visual comparisons](https://playwright.dev/docs/test-snapshots)
depend on environment: browser, OS, fonts and other rendering conditions can
change a screenshot. Its
[screenshot assertions](https://playwright.dev/docs/api/class-pageassertions)
disable animations by default. Thus a clean screenshot diff does not establish
reduced-motion behavior or transition quality. Record the capture conditions
and test motion separately.

[WAI's modal pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
provides concrete keyboard expectations: focus enters the dialog, its tab
sequence is contained, Escape closes it and focus generally returns to the
invoker. Merely adding a role or a recorded event with that name is insufficient.
An eventual live collector should assert these states and preserve the results.

### Standards must be named accurately

WCAG 2.2 [target-size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
uses 24×24 CSS pixels or a qualifying exception at AA. The enhanced criterion
uses 44×44 with its own exceptions. Litha may choose a larger product target,
but should not label a blanket 44-pixel rule as the exact AA requirement.

[Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) addresses
320 CSS-pixel-wide vertical content with relevant two-dimensional-layout
exceptions. [Focus Not Obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html)
at AA requires that a focused component not be entirely hidden by author-created
content; full visibility is a stronger condition. The specific
[Animation from Interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html)
criterion is AAA. Respecting reduced motion is still an appropriate product
requirement. These distinctions prevent a convenient checklist from making
inaccurate conformance claims.

### Motion and native Roblox preferences

Current [MotionConfig documentation](https://motion.dev/docs/react-motion-config)
defaults reduced motion to `never`. Its `user` policy suppresses transforms and
layout movement while retaining some other animation. Litha's frontend already
combines OS and application settings and explicitly settles variants; importing
a separate default policy could weaken that existing behavior.

[Roblox's accessibility documentation](https://create.roblox.com/docs/production/publishing/accessibility)
describes native `ReducedMotionEnabled`, `PreferredTransparency` and
`PreferredTextSize`. Save authored transparency before multiplying it by the
preference; repeatedly multiplying an adjusted value causes drift. `TextScaled`
bypasses preferred text-size scaling, while wrapping and automatic sizing can
help layouts accommodate it. The native designer should eventually react to
preference changes and clean up listeners along with its existing animation
lifecycle. That runtime change requires real Studio testing and is not claimed
as part of the present diagnostics patch.

The pinned [StyleQuery API source](https://github.com/Roblox/creator-docs/blob/c8f5276703948ef4868c9b9fd44fae619dbe2f11/content/en-us/reference/engine/classes/StyleQuery.yaml)
provides a later native styling route for viewport, input and preference
conditions. It warns that invalid condition names or value types can silently
fail. Any compiler adapter should validate the schema and inspect the effective
runtime style, not merely emit plausible property names.

### Portable design tokens and evaluation methods

The [Design Tokens Community Group 2025.10 format](https://www.designtokens.org/tr/2025.10/format/)
offers typed interchange and references. It is a Community Group specification,
not a W3C Standard. A future adapter could map shared semantic tokens into web
and Roblox-specific values without pretending the rendering systems are equal.
The current patch adds no such exporter.

[Design2Code](https://aclanthology.org/2025.naacl-long.199/) combines automatic and
human evaluation over 484 real webpages. The useful lesson is to separate
element recall, layout, text and visual similarity rather than collapse them
into one flattering score. [DesignBench](https://arxiv.org/abs/2506.06251) adds
generation, editing and repair across frontend frameworks. These inform a later
evaluation design; their model rankings are not current Litha measurements, and
their datasets were not copied or used for training here.

## Hosted services, licenses and local operation

The implemented inspector is deterministic local Python and uses the existing
image verifier. It makes no model call or network request. This fits the local
hardware constraint without claiming a measured whole-agent speed gain.

The reviewed [Magic MCP migration](https://github.com/21st-dev/magic-mcp/blob/6b5299e8a83ceffa73d4fc4e148905bb3eeeeb55/README.md)
now describes a compatibility proxy forwarding messages to hosted 21st MCP.
Its local stdio process is not local inference. The reviewed
[OpenDesign README](https://github.com/nexu-io/open-design/blob/12d970eacc8971150e3c76470d2a9afe16dc2ed1/README.md)
supports local compatible endpoints but also describes always-on reliability
and safety telemetry. Both are architecture references, not dependencies added
to this patch.

License scope also differs by path and resource. Anthropic's frontend-design
directory and Cursor's pstack directory have their own license files; no root
license should be generalized across either monorepo. TypeUI's
[current EULA](https://www.typeui.sh/license) distinguishes permitted end products
from prohibited standalone resource redistribution. AI Canvas's
[FAQ](https://aicanvas.me/faq) separates free MIT components from Premium content.
Tool licensing does not establish rights to every fetched image, font or brand
example. The appendix records the inspected files and uncertainty rather than
relabeling all listed resources as freely redistributable.

The extended review also changes specific adoption choices. [Superdesign's
current product guidance](https://superdesign.dev/blog/ai-ui-generator-exports-code)
distinguishes its current product from its older open-source extension.
[Variant's public terms](https://variant.com/terms-and-privacy) restrict service
integration and AI-system improvement from outputs, so automatic integration
needs an appropriate permission basis. [SVG Backgrounds](https://www.svgbackgrounds.com/license/)
restricts automated end-user creation systems. [Craftwork](https://craftwork.design/license)
separates unlicensed inspiration references from individually licensed components
and commercial resources. These are material distinctions for a tool that
creates other interfaces. The full catalog records each decision and six
limited access paths, with the primary material that remained readable.

## Next implementation priorities

| Priority | Work | Acceptance evidence |
| --- | --- | --- |
| Delivered | UI case coverage, contrast precision and interaction-state diagnostics | Offline adversarial tests, actual agent dispatch and unchanged compiler output checks. |
| Next | Platform-aware retrieval over existing design data and authored rules | Native Roblox queries do not receive web-only rules as implementation advice; weak matches are labeled; relevant context stays bounded. |
| Next | Optional live browser/Studio evidence collectors | Actual source/capture context, DOM or engine measurements, interaction assertions, failure-to-run distinct from passed. |
| Next | Native Roblox preference lifecycle | Real changes to reduced motion, text size and transparency preserve functionality, cancel ongoing effects and clean up listeners. |
| Later | Persistent component-level design decisions and scoped variants | Refinement preserves existing semantics and owner choices; side-by-side comparison uses one consistent brief. |
| Later | Versioned token adapters and selected registry resources | Explicit compatibility tests, provenance, previewed changes and no unsolicited dependency replacement. |

For generation quality, compare the same brief, content, model and inference
settings before and after a change. Evaluate task completion, missing states,
layout defects, accessibility findings, correction effort and human preference
separately. Measure wall time and tool calls alongside those outcomes. Keep
reference artifacts stable and do not update expected screenshots simply to
hide a regression. These are proposed evaluation gates, not results obtained
by the present offline validation.

## Validation, activation and practical limits

The focused validation includes pure contract checks, real-file hash changes,
strict parsing, workspace protections, read-only dispatch through the actual
agent loop, existing design and compiler tests, packaging resource checks and
documentation links. **386 focused tests passed, with zero failures, errors or
skips.** Source compilation and Ruff passed; pinned Pyright reported zero errors
and warnings in the four changed runtime modules. Independent review found two malformed-number/type paths
before the new validator and prompted bounded validation fixes. The machine
record gives the exact command, environment, results and source fingerprints.
The [compiler parity verifier](../../benchmarks/ui_compiler_parity.py) reproduces
the [23-case byte comparison](litha-ui-compiler-parity-20261101.json) against the
explicit baseline commit. It compares generated source without executing Luau.

No real browser, Studio instance, Windows executable or live model was run for
this change. No aesthetic improvement percentage, accessibility certification,
GPU gain, model training or whole-suite success is claimed. Supplied source
lists can omit relevant files, and self-reported capture labels remain
self-reported. Those limits are visible in the output and guide.

Activate the new coverage behavior with `STAR_UI_EVIDENCE=on` and an explicit
contract path. Unset the flag to disable it; omitting the optional path retains
the prior audit behavior. The contrast and bounded-validation corrections are
ordinary fixes in the draft. They do not change generated Luau or silently
enable the coverage feature. This branch is separate from the earlier Freebuff
and Rust draft changes; it is prepared for review, not merged or deployed.
