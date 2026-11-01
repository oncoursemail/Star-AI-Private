# Litha UI research: source review and adoption decisions

Research date: 2026-11-01 UTC. This appendix records upstream source research. See [the main report](LITHA_UI_RESEARCH_20261101.md) for the inspected Litha baseline, delivered code, validation and limits. Recommendations here are design-workflow ideas, not claims that every mechanism was implemented.

## Recommendation

Build a small Litha-owned design contract, load it only for a UI task, and validate the resulting interface through platform-appropriate evidence. Use this catalog as a discovery index. Do not install a bundle of overlapping skills or make remote component registries part of the default generation path.

The strongest reusable mechanisms are persistent design memory, task-specific retrieval, reuse of installed primitives, explicit state coverage, source-versus-rendered checks, and a bounded visual review loop. These mechanisms serve Litha's local-first goal and its owner's preference for an authored, restrained interface. A list of banned colors, fonts or layout shapes cannot establish design quality by itself.

The first implementation should be narrow: an opt-in, local UI brief/check path with separate web and Roblox targets, clear provenance, and no remote calls. Existing UI components and project identity should supply the values. Browser automation, large design corpora, cloud tools and third-party installation can be evaluated independently after that foundation works.

## Scope and evidence

The linked repository is pinned at [maxbogo/awesome-ai-tools-for-ui@680b351764199b9b6b4352d3ea5af0bce927b6ed](https://github.com/maxbogo/awesome-ai-tools-for-ui/tree/680b351764199b9b6b4352d3ea5af0bce927b6ed), committed 2026-09-25T18:28:07Z. Its README blob is `7360f3a04907ebd26b99644f33afe685286accca`. The complete recursive tree has four entries: README.md, .gitignore, assets and the banner image. It has no license file, and GitHub metadata reports no detected license.

The catalog has exactly **64 entries: 25 skills, 13 apps, 6 MCP/plugin entries, 12 design tools and 8 resources**. Entries are not independent technologies: UserInterface.wiki appears both as a skill and as a resource. Skill files, hosted services, component source, design examples and educational references have different reuse and trust boundaries.

This review extracted all 64 names and URLs and pinned 40 relevant GitHub repositories. All directly linked repository metadata/trees were inspected except one transient tree transport failure for OpenDesign; its README and license were successfully read at its pinned commit. The principal design skill/rule sources received deeper inspection, and every remaining metadata-only repository received a pinned README review. All 22 public-product/resource entries initially marked Catalog-only were extended to primary pages, docs or terms where readable. The official Delightful frontend article was also reviewed directly and is recorded below. The matrix distinguishes deep source, README, primary-page and terms review. No complete runtime security audit or measured Litha quality benchmark is claimed; no upstream installer, skill script, hook, browser extension, paid export or MCP server was executed.

## What changed since the catalog descriptions

1. **Impeccable is now more than 20 prompt commands.** Its pinned README documents 24 commands, 62 deterministic rules, a local engine, hooks, rendered-page scanning, design-context files and live source edits. The skill reports version 4.8.0. That creates useful evaluation opportunities and a much wider execution surface than copying a small Markdown file. Sources: [README](https://github.com/pbakaus/impeccable/blob/4f956490f0056ae1ff5ea80372cf56e83c001d3c/README.md); [skill](https://github.com/pbakaus/impeccable/blob/4f956490f0056ae1ff5ea80372cf56e83c001d3c/.agents/skills/impeccable/SKILL.md).

2. **Taste's website and repository no longer describe the same simple bundle.** The public website advertises 13 skills; the pinned repository contains a consolidated v2 skill with direction libraries, Node scripts and browser inspection. The marketing-page flow is distinct from the app-screen flow. Evaluate the exact commit and path, not a website install slogan. Sources: [website](https://www.tasteskill.dev/); [current skill](https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/skills/taste-skill/SKILL.md).

3. **Magic MCP has become a hosted-service proxy.** Its README says the old package was replaced by 21st MCP; v0.2.0+ forwards MCP messages to `https://21st.dev/api/mcp`. It requires an account API key, and hosted AI access is distinct from component access. A local stdio wrapper does not make processing local. Source: [migration README](https://github.com/21st-dev/magic-mcp/blob/6b5299e8a83ceffa73d4fc4e148905bb3eeeeb55/README.md).

4. **DESIGN.md has an actual evolving specification.** The catalog's brand examples are only one use. Google's official Apache-2.0 repository defines structured tokens and prose, plus validation, diffing and exports. Its spec is alpha. Source: [format specification](https://github.com/google-labs-code/design.md/blob/6e5da5382f41edbba9d73b2c62f33f32e9971f15/docs/spec.md); [Google announcement](https://blog.google/innovation-and-ai/models-and-research/google-labs/stitch-design-md/).

5. **OpenDesign is now a substantial workspace, not a small UI helper.** It documents native agent runtimes, BYOK endpoints including local model servers, portable design packages, desktop and cloud surfaces. Its README also says reliability/safety telemetry is always on, while product analytics and session replay are consent-gated. Local-first is not the same claim as fully offline. Source: [README](https://github.com/nexu-io/open-design/blob/12d970eacc8971150e3c76470d2a9afe16dc2ed1/README.md).

6. **Some downloadable design material is commercial.** TypeUI's current EULA grants use in end products while prohibiting standalone resource redistribution and competing design registries/datasets. AI Canvas differentiates MIT free components from proprietary Premium material. A public URL or downloadable skill is not a blanket redistribution license. Sources: [TypeUI EULA](https://www.typeui.sh/license); [AI Canvas FAQ](https://aicanvas.me/faq).

## Mechanisms worth carrying into Litha

### Impeccable: useful checks and durable context, selective adoption

The engine distinguishes source scanning from browser scanning. JSX/TSX can reveal patterns such as gradient text or suspicious source constructs, while rendered contrast and text size need a browser. It emits structured findings, source/element locations and different exit statuses for findings versus a scan failure. Narrow exceptions can allow one documented brand value without disabling a whole rule. Its context workflow loads PRODUCT.md, DESIGN.md and surface-specific briefs. The detector's current docs explicitly limit its automatic checks to web interfaces; native work uses a different review path. Sources: [implementation overview](https://github.com/pbakaus/impeccable/blob/4f956490f0056ae1ff5ea80372cf56e83c001d3c/README.md); [detector docs](https://impeccable.style/docs/detector/); [rule implementation](https://github.com/pbakaus/impeccable/blob/4f956490f0056ae1ff5ea80372cf56e83c001d3c/crates/core/src/checks/rules.rs).

For Litha, adopt the architecture of separate **observable defects**, **project-contract drift** and **taste suggestions**. A scan result should say which kind it is, how it was observed and what it cannot establish. A clean source scan must never claim visual or accessibility compliance. Allow a reasoned, narrow style exception. Do not automatically install the upstream binary, hooks or live overlay: these are separate product/runtime integrations.

Its current craft floor contains both useful standards-related checks and prescriptive house opinions, including an absolute ban on a label above a heading and fixed preferred radius/type values. Those are not general truths or Roblox requirements. Its animation advice even allows smooth blur, mask and shadow work, whereas other sources demand transform/opacity only. Keep performance evidence separate from aesthetic preference. Source: [craft floor](https://github.com/pbakaus/impeccable/blob/4f956490f0056ae1ff5ea80372cf56e83c001d3c/.agents/skills/impeccable/reference/craft-floor.md).

License: Apache-2.0, with a NOTICE file for derived native-platform references. Read those notices before copying substantial source or prose. Sources: [license](https://github.com/pbakaus/impeccable/blob/4f956490f0056ae1ff5ea80372cf56e83c001d3c/LICENSE); [notice](https://github.com/pbakaus/impeccable/blob/4f956490f0056ae1ff5ea80372cf56e83c001d3c/NOTICE.md).

### UserInterface.wiki: searchable micro-rules, not universal constraints

The pinned skill exposes 152 rules across 12 categories, each with a stable identifier and individual explanation/example files. It covers motion, exit lifecycle, pseudo-elements, audio, synthesis, icons, measured containers, UX concepts, prefetching, typography and visual surfaces. That organization is useful for retrieving only the rules relevant to a specific component. Source: [rule index](https://github.com/raphaelsalaja/userinterface-wiki/blob/256a954080c8bcf1b1ceb1e2a4079d1f24cf593a/skills/SKILL.md).

Select a compact set for Litha: disabled interactions during exit, visible equivalents for audio, reduced-motion handling, honest progress/recovery, stable numeric text, content-resilient sizing, and sufficient hit areas. Do not adopt its exact three-line SVG icon recipe, universal sub-300ms timing, typography stylistic-set assumptions or 32px target claim as platform policy. They depend on a particular implementation or style. Its own frontmatter says 11 categories while the body has 12, another reason to parse actual data rather than trust a count in a summary.

License: MIT at [license.md](https://github.com/raphaelsalaja/userinterface-wiki/blob/256a954080c8bcf1b1ceb1e2a4079d1f24cf593a/license.md). Any reuse still needs normal attribution/notice handling.

### UI UX Pro Max: local retrieval is the valuable engineering pattern

The actual mechanism is Python BM25 over local CSVs. The core normalizes synonyms, ranks documents, calibrates domains using relevance/coverage thresholds, and caches file snapshots and fitted indexes with signatures. The design generator joins product/style/color/landing/typography results, applies CSV reasoning profiles, resolves light/dark palettes and supports optional design dials. It is not itself a language model. Sources: [search core](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/bf41cbc3ce63e30c922e58ef48741ba6133f9aa9/.claude/skills/ui-ux-pro-max/scripts/core.py); [generator](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/bf41cbc3ce63e30c922e58ef48741ba6133f9aa9/.claude/skills/ui-ux-pro-max/scripts/design_system.py).

The skill requires a detected stack, one dominant query intent, a single narrower retry for a weak result, and explicit disclosure when falling back. Its persisted output uses a master document plus page overrides, with existing files preserved unless overwrite is explicitly selected. Those are good patterns for local-first Litha: bounded retrieval, provenance, non-destructive persistence and a clear distinction between retrieved evidence and fallback advice. Source: [workflow contract](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/bf41cbc3ce63e30c922e58ef48741ba6133f9aa9/.claude/skills/ui-ux-pro-max/SKILL.md).

Do not inject all 22 supported stacks or a full style catalog into every task. The current stack list has no Roblox target. Its CSS values, GSAP snippets and palette categorization are recommendations for supported surfaces, not Luau/native output. Start with Litha-authored, platform-tagged rules; evaluate external corpus quality on real tasks before importing it. License: [MIT](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/bf41cbc3ce63e30c922e58ef48741ba6133f9aa9/LICENSE).

### Anthropic frontend-design: intent, restraint and a two-pass process

The current skill asks for decisions grounded in the subject, audience and actual content. It recommends a compact token/layout plan, reviewing that plan against the brief, implementing it, and critiquing screenshots. It treats user-triggered motion as useful feedback and asks for restraint in autonomous decoration. It also distinguishes a deliberate use of a familiar style from an unexamined default. Source: [frontend-design](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design/SKILL.md).

This fits Litha's owner direction better than random theme assignment. Use the real task and existing identity as the source of visual choices. Do not transform an operational editor into an expressive marketing page because a skill contains a heroic design example. The skill does not provide automated accessibility verification, a component library or native Roblox APIs.

The repository has no detected root license, but the **specific frontend-design directory is Apache-2.0**. Do not label every skill in anthropics/skills with that one license. Source: [component license](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design/LICENSE.txt).

### Taste Skill: verification loop useful; marketing quotas conflict

The pinned v2 workflow deals candidate visual directions, chooses a direction based on the brief, supplies composition/type/palette libraries, runs a source linter, opens the finished page in a real browser and critiques screenshots at 1440, 768 and 390 widths. It requires Node 22+ and a local Chromium-family browser; its asset search script additionally uses network services. The app-screen path has distinct rules. Source: [v2 workflow](https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/skills/taste-skill/SKILL.md); [app-screen branch](https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/skills/taste-skill/references/app-screens.md).

Use its before/after evidence and bounded look/fix cycle as a process idea. Reject the marketing branch as Litha's default: it mandates at least four pictures and fails below eight moving elements. That directly conflicts with a quiet task interface and with Anthropic/Impeccable advice to choose one meaningful motion event. A threshold derived from gallery aesthetics is not a user outcome measure. Its screenshot/style gates also cannot prove task success.

The code has an MIT license, but its asset retrieval and source gallery references introduce additional per-image provenance. License for the tool is not a license for every image it can retrieve. Source: [license](https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/LICENSE).

### shadcn: project-aware composition, not a style generator

The skill obtains framework, aliases, base library, icon setup, installed components and resolved paths from project configuration. It teaches composition, semantic tokens and library-specific APIs, then retrieves relevant documentation before code. This avoids generating plausible but incompatible component calls. Source: [skill](https://github.com/shadcn-ui/ui/blob/c0d63c339d6cd2fc26135590a54cf1f362269451/skills/shadcn/SKILL.md); [official skills documentation](https://ui.shadcn.com/docs/skills).

Carry the idea into Litha: inspect the incumbent component system first. If Litha already has a Button, Dialog or field primitive, compose it and preserve its semantics. Do not introduce an additional component system merely to apply a polish rule.

The upstream skill uses executable context injection and broad `shadcn@latest` command permissions. Read that as implementation behavior to review, not authority to run it. Registry source can write files and introduce dependencies. An eventual integration should pin the CLI and each fetched source, preview changes, and retain per-item provenance. It is web/React context, not native Roblox generation. License: [MIT](https://github.com/shadcn-ui/ui/blob/c0d63c339d6cd2fc26135590a54cf1f362269451/LICENSE.md).

### Vercel Web Interface Guidelines: useful review seed with caveats

The small agent-skills wrapper fetches mutable `main/command.md` for each review and outputs terse file:line findings. The underlying guideline repository is MIT; the wrapper repository has no license file in the verified tree. Sources: [wrapper](https://github.com/vercel-labs/agent-skills/blob/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62/skills/web-design-guidelines/SKILL.md); [review rules](https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/command.md); [license](https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/LICENSE).

Useful checks include visible focus, semantic controls, accessible names, paste support, long-content behavior, interruptible reduced-motion alternatives, descriptive errors, stable media layout and correct native navigation semantics. Use a pinned, authored subset with target platform tags. Avoid importing Vercel-specific copy style as Litha identity.

The README includes a mobile-input fallback containing `maximum-scale=1`, while its command file flags that same zoom restriction as an anti-pattern. It also recommends APCA in its design section. Those conflicts make automatic wholesale incorporation inappropriate. Preserve zoom and use the actual WCAG success criteria for a conformance claim; APCA can be an additional perceptual design aid, not a substitution. Source: [README](https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/README.md).

### Interface Design and Design and Refine: memory and comparison, with boundaries

Interface Design focuses on product UIs. It reads a durable system document, reuses installed primitives, records concrete density/type/spacing decisions and checks for drift. This is an appropriate model for Litha's operational surfaces. Its source also embeds subjective rules and some imprecise standards shorthand; those should not become hard gates. Sources: [skill](https://github.com/Dammyjay93/interface-design/blob/2f9be3206855bcb2d1d0af262c8bae25cba6658d/.claude/skills/interface-design/SKILL.md); [MIT license](https://github.com/Dammyjay93/interface-design/blob/2f9be3206855bcb2d1d0af262c8bae25cba6658d/LICENSE).

Design and Refine constructs a temporary five-variant lab, collects feedback, synthesizes a choice and writes design memory/implementation planning artifacts. The useful idea is controlled comparison against one brief. Its multi-step interview and mandatory cleanup behavior should not be copied into Litha's normal editing flow. Deleting an entire lab directory may remove untracked user work if ownership is not explicit. This pinned repository contains **no license file**; use the workflow as a reference and author an independent implementation if needed. Source: [design lab](https://github.com/0xdesign/design-plugin/blob/913a7ab2ac7e0f48eab77c93f2f5376150864b02/design-and-refine/skills/design-lab/SKILL.md).

### DESIGN.md: capture actual Litha identity, with a typed bridge later

VoltAgent's repository contains brand-inspired design analyses. Its MIT license covers that repository's contributions; it does not demonstrate rights to every referenced company's marks, assets or typefaces. Use the documents to study organization and vocabulary. A Litha document should describe the real project's components, colors, spacing, motion, accessible states and native/web differences. Sources: [collection](https://github.com/VoltAgent/awesome-design-md/blob/fcc70284932276d085f01ef9f83edde90b1258cb/README.md); [license](https://github.com/VoltAgent/awesome-design-md/blob/fcc70284932276d085f01ef9f83edde90b1258cb/LICENSE).

Google's official alpha spec gives a more interoperable option: YAML token data plus rationale, reference resolution, duplicate-key rejection, component states as related entries and preservation of unknown sections. The CLI supports lint, token/prose diffing and Tailwind/DTCG exports. Export may succeed despite lint findings, so validation must be a separate gate. Sources: [spec](https://github.com/google-labs-code/design.md/blob/6e5da5382f41edbba9d73b2c62f33f32e9971f15/docs/spec.md); [official repository](https://github.com/google-labs-code/design.md).

The strongest near-term choice is an independently authored design brief with a small stable schema. If standard import/export becomes a requirement, add an explicit versioned adapter for the alpha format. Do not silently claim format compatibility just because a file is named DESIGN.md.

## Standards and platform corrections

A design preference, a platform behavior and an accessibility criterion need different treatment:

| Type | Litha treatment | Example |
|---|---|---|
| Observable functional failure | Block completion until fixed or accurately disclosed | Primary action does not work; focus is lost after dialog close |
| Accessibility requirement | Use the actual criterion and relevant platform test | Keyboard access, contrast, labels, reduced-motion alternative where applicable |
| Owner/project contract | Enforce with documented scope | No generic decorative gradients/shapes; preserve existing Litha identity |
| Framework constraint | Apply only to the detected stack/version | Correct shadcn base library and component APIs |
| Taste heuristic | Advisory, overridable with reason | Optical nudge, preferred density or heading line count |
| Upstream marketing claim | Do not score as established evidence | Tool claims a conversion or visual-quality improvement |

For web targets, WCAG 2.2 AA target-size minimum is **24×24 CSS pixels or a qualifying spacing/other exception**; the enhanced AAA target is **44×44**, again with exceptions. Choosing 44px as Litha's touch-friendly product default is reasonable, but it is not the exact wording of the AA minimum. Sources: [W3C SC 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum); [W3C SC 2.5.5](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced).

Do not make every interaction wait for animation. Repeated keyboard operations should feel immediate; an exit transition must not leave an invisible element accepting input. Motion should explain a state change, tolerate interruption and preserve functionality in reduced mode. Numerical durations are starting hypotheses to test, not universal laws.

Roblox is a distinct rendering and input platform. Share semantic intent and design tokens where useful, but resolve native layout, text sizing, input selection and safe-area behavior through a Roblox-specific profile. A browser screenshot or DOM accessibility scan cannot validate a native Roblox screen. No reviewed web skill establishes native Roblox support merely by mentioning mobile or native in its description.

## Later design-brief and retrieval proposal

This is a proposal beyond the delivered UI evidence contract; it is not a claim that generation or retrieval already uses these fields:

- A target field distinguishes web, Roblox and unspecified. Do not silently choose React when the request is native Roblox.
- An operation field distinguishes new design, refinement and review. Refinement preserves existing product identity and behavior.
- A bounded brief records audience/job, existing tokens/components, intentional style, density, real content/assets and hard owner constraints.
- A small local rule index carries stable IDs, target platforms, severity/type, explanation, source revision and the evidence required to establish a finding.
- A review result records source path or runtime element, condition observed, recommended fix and validation status. Separate not-run, failed-to-run and passed.
- Default behavior uses local authored data and the existing toolchain. Importing a skill, starting a browser, fetching a registry, installing a package or uploading project data is a separate operation.
- Native and web validation remain separate, while each checks meaningful states: loading, empty, error, disabled, focused, successful and content overflow.

Useful evaluation tasks are small and concrete: modify a settings form without losing keyboard behavior; generate an error/empty state from real project components; repair long-text overflow on small and large screens; improve purposeful motion while preserving reduced mode; produce native Roblox layout without introducing HTML/CSS artifacts. Compare user-task outcomes, defect counts, manual editing effort and latency. Do not equate a style linter's score with quality.

## Complete 64-entry triage

“Adopt pattern” means an independently authored Litha mechanism inspired by reviewed evidence, not installation or vendoring. Evidence labels describe the material actually read; primary product documentation establishes provider claims, not verified runtime behavior. The expanded inspection notes below record dates, concrete sources and access limits.

### Skills

| Entry | Surface | Decision for Litha | Reason / scope | Evidence depth |
|---|---|---|---|---|
| [Impeccable](https://impeccable.style/) | Rules + local CLI/hooks | Adopt pattern | Persistent product/design context; source and rendered checks. Defer engine, hooks and live editing integration. | Deep source |
| [UserInterface.wiki Skill](https://www.userinterface.wiki/skill) | Rule corpus | Adopt pattern | Select motion/state/typography guidance; exclude narrow recipes and unsupported universal thresholds. | Deep source |
| [UI UX Pro Max Skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | Local data + Python search | Adopt pattern | Bounded local retrieval and durable master/page overrides. Retain Litha's existing four-table subset; evaluate upstream corpus changes and generator dependency separately. | Deep source |
| [Anthropic Frontend Design Skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design) | Prompt guidance | Adopt pattern | Product-specific art direction, short plan, screenshot critique, purposeful motion. | Deep source |
| [Make Interfaces Feel Better](https://github.com/jakubkrehel/make-interfaces-feel-better) | Prompt + references | Adopt pattern | Keep the incumbent styling system; inspect intermediate motion and interaction states. | Source read |
| [shadcn/ui Skills](https://ui.shadcn.com/docs/skills) | Framework context + CLI | Adopt pattern | Detect real installed configuration and compose existing primitives; do not run latest installers automatically. | Deep source |
| [Web Design Guidelines Skill](https://github.com/vercel-labs/agent-skills/blob/main/skills/web-design-guidelines/SKILL.md) | Remote-rule review wrapper | Reference only | Use reviewed MIT underlying guidelines; wrapper has no license file and downloads mutable main each review. | Deep source |
| [Emil Kowalski Skills](https://github.com/emilkowalski/skills) | Motion diagnostics/rules | Adopt pattern | Separate movement design from performance diagnostics; audit frequent interactions for unnecessary animation. | Source read |
| [Unslop Skill](https://github.com/cursor/plugins/blob/main/pstack/skills/unslop/SKILL.md) | Writing rules | Reference only | Useful UI-copy cleanup; not a UI engine or graphics library. | Source read |
| [Refactoring UI Skill](https://github.com/s0xDk/refactoring-ui-skill) | Third-party design notes | Reference only | Read original MIT notes as ideas; book rights explicitly excluded. Do not market imported rules as the book. | License/source read |
| [Taste Skill](https://www.tasteskill.dev/) | Rules + Node/browser tools | Adopt pattern | Before/after viewport inspection; use app-specific reasoning. Reject mandatory marketing motion/photo quotas for Litha. | Deep source |
| [Designer Skills Collection](https://github.com/Owl-Listener/designer-skills) | Large multi-repository prompt marketplace | Defer | Select a specific unmet need; the marketplace aggregates other repositories, so its headline count does not describe one self-contained source tree. | Pinned README + metadata/tree |
| [TypeUI Design Skills](https://www.typeui.sh/design-skills) | Hosted/commercial design resources | Reference only | EULA restricts standalone redistribution and competing registries/datasets; do not ship downloaded skills in Litha. | Primary site/terms |
| [YC Web Design Strategy Skill](https://github.com/maxbogo/yc-web-design-strategy-skill) | Landing-page strategy guidance | Reference only | Use for startup positioning or a marketing page; stage-aware conversion heuristics should not become editor or Roblox UI rules. | Pinned README + metadata/tree |
| [Swiss Design System](https://swiss.ziki.boo/) | Fixed visual skill | Reference only | Useful grid/restraint specimen; IBM Plex/stone/red and large spacing are a style choice, not Litha defaults. | Source read |
| [Bencium Marketplace](https://github.com/bencium/bencium-marketplace) | Plugin marketplace with skills and hooks | Defer | Avoid the whole marketplace; its design styles, always-ask protocol, hooks and unrelated tools have different scopes. | Pinned README + metadata/tree |
| [Three.js Skills](https://github.com/CloudAI-X/threejs-skills) | Versioned browser 3D guidance | Defer | Only for an explicit web 3D requirement, with target-version checks; no native Roblox UI support is established. | Pinned README + metadata/tree |
| [Awesome DESIGN.md](https://github.com/VoltAgent/awesome-design-md/) | Example design documents | Reference only | Compare document structure; author Litha's identity from actual tokens rather than cloning another brand. | Deep source |
| [StyleSeed](https://github.com/bitjaru/styleseed) | Design-memory compiler and scored workflow | Evaluate pattern | Project-local decisions and rendered review are relevant; defer another executable rules engine and treat its benchmark as self-reported. | Pinned README + metadata/tree |
| [Claude Code Design Review Workflow](https://github.com/OneRedOak/claude-code-workflows/tree/main/design-review) | Review templates + browser workflow | Adopt pattern | Review changed routes with live interaction and screenshots; use Litha's own test harness and evidence schema. | Source read |
| [Huashu Design](https://github.com/alchaincyf/huashu-design) | Local prototype/media export suite with optional cloud | Defer | Useful later for prototypes/decks; broad render/export scripts and optional cloud features need a separate code review. | Pinned README + metadata/tree |
| [Nothing Design Skill](https://github.com/dominikmartn/nothing-design-skill) | Brand-inspired style and platform mappings | Reference only | Study coherent tokens and output mapping; do not automatically imitate another brand's type, dot motifs or progress treatment. | Pinned README + metadata/tree |
| [Hallmark](https://github.com/nutlope/hallmark) | Design rules + browser gates | Evaluate pattern | Useful separation of hard quality floor, overridable taste rules and polish. Theme roulette is not a default. | Source read |
| [Material Design 3 Skill](https://github.com/hamen/material-3-skill) | Third-party Material platform guidance | Reference only | Select only when Material is the product's chosen system; verify exact APIs in official platform documentation. | Pinned README + metadata/tree |
| [Scandinavian Design Skill](https://github.com/ericzakariasson/scandinavian-design) | Fixed style with screenshot tooling | Reference only | No license file found in the pinned tree; visual restraint is relevant but does not authorize vendoring or installing its scripts. | Pinned README + metadata/tree |

### Apps

| Entry | Surface | Decision for Litha | Reason / scope | Evidence depth |
|---|---|---|---|---|
| [21st.dev](https://21st.dev/home) | Hosted component marketplace | Defer | Component discovery candidate; review each resource license and dependencies, not the entire marketplace. | Catalog + 21st source |
| [AI Website Cloner](https://github.com/JCodesMore/ai-website-cloner-template) | Next.js recreation template and observation workflow | Reject default | Adopt matched-state observation only for authorized reference work; arbitrary website cloning is not Litha's design identity. | Pinned README + metadata/tree |
| [Superdesign](https://app.superdesign.dev/) | Hosted design canvas + coding-agent skill | Defer | Editable HTML and repo adaptation are useful; current product is proprietary and distinct from its unmaintained open-source IDE extension. | Primary product articles |
| [Variant](https://variant.com/) | Hosted variation service | Defer | Public terms restrict service use to personal noncommercial purposes, prohibit AI-system improvement from outputs, and require permission for interacting applications. | Primary terms; UI inaccessible |
| [Stitch by Google](https://stitch.withgoogle.com/) | Hosted design service | Defer service | Adopt portable design-document concept; hosted generation stays optional and separately authorized. | Official format source |
| [Open Design](https://github.com/nexu-io/open-design) | Desktop/local + cloud workspace | Reference only | Borrow portable design packages/preview architecture; current source has always-on reliability telemetry and much wider runtime scope. | Source/license read |
| [Khroma](https://www.khroma.co/) | Browser-local palette exploration | Reference only | Provider describes preference learning in the browser and CSS/color exports; useful palette aid, not a whole-interface accessibility result. | Primary feature page |
| [Noyzzi](https://noyzzi.com/) | Interactive design and prompt gallery | Reference only | Use public examples as references; inspected privacy policy does not supply a license to bundle prompts or visuals. | Primary gallery/privacy |
| [Design Resources for AI Agents](https://styles.refero.design/ai-agents/design-resources) | Hosted reference directory | Reference only | Use to find examples; does not establish a license for referenced sites or a machine-enforced standard. | Primary site |
| [prompt-kit](https://www.prompt-kit.com/) | React source components | Evaluate dependency | Inspect selected chat/tool/message primitives against existing frontend; no wholesale UI replacement. | Primary repo |
| [Brik](https://brik.space/) | Hosted parametric design tool builder | Defer | Reusable controllers are useful as an idea; paid standalone HTML and hosted iframe exports have different dependency and visibility boundaries. | Primary product/export/docs |
| [UIZZE](https://uizze.com) | Hosted references + paid MCP + free guidance | Adopt workflow; defer service | Adopt a two-screen consistency exercise and explicit design-file reads; defer authenticated remote reference retrieval. | Primary guide; paid path gated |
| [Curio](https://designbycurio.com/) | Commercial design-spec catalog + remote MCP | Reference only | Useful style-spec delivery format; commercial terms restrict catalog redistribution and competing datasets. Do not embed the catalog in Litha. | Primary docs/MCP/terms |

### MCP Servers & Plugins

| Entry | Surface | Decision for Litha | Reason / scope | Evidence depth |
|---|---|---|---|---|
| [Magic MCP](https://github.com/21st-dev/magic-mcp) | Hosted MCP + compatibility proxy | Defer | Renamed/replaced by 21st MCP; proxy forwards messages to hosted endpoint with API key and account access. | Source read |
| [UI Layouts MCP](https://www.ui-layouts.com/mcp) | Local stdio + remote registry | Evaluate later | Search/docs/metadata/TSX retrieval pipeline is useful; pin each fetched component and review its license/dependencies. | Primary docs/repo |
| [Lazyweb](https://www.lazyweb.com/) | Hosted research/growth service | Defer | Current site has expanded into growth automation; claims are vendor evidence, not proof of Litha gains. | Primary site |
| [Design and Refine](https://github.com/0xdesign/design-plugin) | Temporary multi-variant workflow | Reference only | Comparison lab and feedback loop useful; no license file found, cleanup workflow is not safe to import wholesale. | Deep source |
| [Interface Design](https://github.com/Dammyjay93/interface-design) | Product-UI skill + memory | Adopt pattern | Read durable system decisions and reuse primitives; author a Litha contract instead of importing rigid taste rules. | Deep source |
| [AI Canvas](https://aicanvas.me/mcp) | Open-core React registry/MCP | Evaluate selected free source | Free library MIT; Premium proprietary. Live registry is mutable and animated defaults need restraint. | Primary docs/repo |

### Design Tools

| Entry | Surface | Decision for Litha | Reason / scope | Evidence depth |
|---|---|---|---|---|
| [FontCrafter](https://arcade.pirillo.com/fontcrafter.html) | Browser-local font authoring tool | Defer | Useful only for a deliberate custom-font task; locally generated font output is distinct from a licensed copy of the tool itself. | Primary FAQ/technical page |
| [SVG Loaders](https://magecdn.com/tools/svg-loaders) | SVG asset index with upstream libraries | Evaluate selected asset | Two linked upstream libraries are pinned and MIT-licensed; preserve notices and test loading semantics, animation fallback and reduced motion. | Primary index + pinned licenses/README |
| [SVG Backgrounds](https://www.svgbackgrounds.com/set/free-svg-backgrounds-and-patterns/) | Customizable SVG assets under commercial terms | Reject default | Owner direction rejects decorative backgrounds; license also excludes automated end-user creation systems and generative-AI training. | Primary product/license |
| [Realtime Colors](https://www.realtimecolors.com/) | Browser palette/token preview | Reference only | Role-based preview and export can inform token choices; verify actual screen states and contrast independently. | Primary feature page |
| [Transitions.dev](https://transitions.dev/) | Motion snippets, skills and local/paid tools | Adopt pattern; defer integration | Named motion tokens and reduced-motion snippets are useful. Tooling is MIT; snippets/skills carry a distinct custom redistribution license. | Primary docs + pinned README/licenses |
| [Beautiful HTML Templates](https://github.com/zarazhangrui/beautiful-html-templates) | HTML slide template library | Defer | A later presentation/export resource, not a product UI foundation; external fonts and sibling assets still need per-template review. | Pinned README + metadata/tree |
| [daisyUI](https://daisyui.com/) | MIT Tailwind CSS library; separate paid MCP | Defer | Do not add a second component/theme system without an existing-library gap. Blueprint's paid workflow is separate from the MIT CSS source. | Primary docs + pinned README/license |
| [Paper Shaders](https://github.com/paper-design/shaders) | Canvas/React shader library | Reject default | Apache-2.0 source can be evaluated for explicit visualization needs; background shaders conflict with current restraint/performance goals. | Source read |
| [Pryzm](https://www.pryzm.design/) | Browser WebGL studio with hosted saves | Reference only | Optional authored asset creation, with account uploads on save and separate media/code export terms; no default background pipeline. | Primary FAQ/terms |
| [Logosystem](https://logosystem.co/) | Third-party logo inspiration gallery | Reference only | The site's FAQ expressly says displayed logos belong to their brands/designers and require original-source license checks. | Primary gallery/FAQ |
| [Ditther](https://www.ditther.com/) | Browser-local image/video editor with paid features | Defer | Niche asset treatment; local-processing claims and export tiers are documented, but output-license terms could not be fetched. | Primary FAQ; terms blocked |
| [Book of Shapes](https://bookofshapes.com/?tag=flow) | Generative SVG editor with output license | Reject default | Decorative shape defaults conflict with Litha's brief. Output rights exclude pattern-library redistribution and three study-only reconstructions. | Primary generator/license |

### Resources

| Entry | Surface | Decision for Litha | Reason / scope | Evidence depth |
|---|---|---|---|---|
| [Laws of UX](https://lawsofux.com/) | Conceptual design reference | Reference only | Useful for hypotheses about grouping, targets and feedback; the Miller page itself rejects using seven as an arbitrary UI limit. | Primary index + article |
| [UserInterface.wiki](https://www.userinterface.wiki/) | Educational site | Adopt selected reference | Same underlying ecosystem as the listed skill, not another independent tool or evidence source. | Primary site + source |
| [Craftwork](https://craftwork.design/curated/websites/) | Inspiration gallery + mixed-license assets/components | Reference only | Inspiration grants no reuse license. Selected code may be open source, but each item and AI-use restriction must be checked. | Primary gallery/license |
| [Zajno Motion](https://motion.zajno.com/) | Interactive motion education/reference | Reference only | Study feedback timing and attention, then implement and measure within Litha's own platform constraints. | Primary educational page |
| [The Shape of AI](https://www.shapeof.ai/) | AI interaction pattern reference | Adopt pattern | Use visibility of plans/sources, cancel/control, memory management, draft choices and recoverable actions. | Primary site |
| [aiux.courses](https://aiux.courses) | Curated course/source directory | Reference only | Useful navigation with dated editorial notes; follow each linked primary source before making technical or empirical claims. | Primary directory/about |
| [Delightful frontend](https://developers.openai.com/blog/designing-delightful-frontends-with-gpt-5-4) | Official design guidance article | Reference only | Use explicit constraints, real content, references and rendered verification; scope promotional hero/motion examples to that surface and preserve existing systems. | Primary official article |
| [Vibe Coding UI Specification](https://horizonx.so/resources/vibe-coding-ui-specification) | Vendor-neutral Markdown/YAML UI contract | Adopt pattern | Six explicit layers map well to Litha's local contract; the public page permits copying/adapting but the full download was not inspected. | Primary spec page; download unsupported |

## Additional primary-source inspection — 2026-11-01

These notes extend the initial triage. “Local” below reports the provider's documented processing model unless executable source was separately inspected; no network isolation audit, authenticated export test, purchase or installation was performed. No remote screenshots, catalog assets or prompt packs were imported.

### Designer Skills Collection

The README separates design-practice skills in this repository from four companion collections pulled through the marketplace. It provides task routing and workflow commands for research, state mapping, tokens and critique; these are guidance units, not independently validated product results.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/Owl-Listener/designer-skills/blob/9a6930cf84a822eb458624bd11c61aac5bbdf224/README.md).

### YC Web Design Strategy Skill

The README describes a framework distilled from YC design-review videos: product stage, a five-second comprehension filter, messaging, calls to action and QA. Its stated scope is websites and landing pages.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/maxbogo/yc-web-design-strategy-skill/blob/bf9e5ace80a958f25dbe60989762770bdcf3505f/README.md).

### Bencium Marketplace

The README lists restrained and experimental design options, a visual-only audit, typography guidance and broader architecture/marketing utilities. It also includes an emotional-status hook and an external build-loop repository, so installing all is broader than adopting UI guidance.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/bencium/bencium-marketplace/blob/5de46a39b4640fa419560cd0b67e4c4b50dac802/README.md).

### Three.js Skills

The README targets specific Three.js, React Three Fiber, drei and glTF-transform versions and separates fundamentals, rendering, WebGPU/TSL, performance and asset pipelines. Version-bounded API correction is useful, but the target remains browser rendering.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/CloudAI-X/threejs-skills/blob/0e181866f095b5f06d005133876e926515390d95/README.md).

### StyleSeed

The README describes STYLESEED.md decisions, source-hashed compiled rule bundles and a render-score-revise workflow. It explicitly says rules alone cannot block delivery and a score cannot replace human acceptance; its published benchmark is a claim of that project, not a Litha measurement.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/bitjaru/styleseed/blob/ce66f1dc1d14609ec43bc48eed1d97abb51489c8/README.md).

### Huashu Design

The English README describes local HTML, PDF/PPTX, image and video outputs, local design-history records and optional cloud scripts. It reports MIT relicensing but identifies demo stickers under PolyForm Shield; asset rights are therefore not uniform.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/alchaincyf/huashu-design/blob/9b01ee8751679724dd43d855a532944aaa2c2b59/README.en.md).

### Nothing Design Skill

The README maps one monochrome industrial design language to HTML/CSS, React/Tailwind and SwiftUI. Separate reference files cover tokens, components and platform mapping; Roblox is not listed.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/dominikmartn/nothing-design-skill/blob/74affbb786af098b18503467b205c10a7df30126/README.md).

### Material Design 3 Skill

The README prioritizes Jetpack Compose, gives Flutter a secondary role and marks its web path limited with no full Expressive parity. It calls itself a best-effort distillation that can drift and directs exact API checks to official documentation.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/hamen/material-3-skill/blob/14385f2bf3804d8779f8b4db2604211f1e70b4c1/README.md).

### Scandinavian Design Skill

The README describes a black/white visual style and ten demonstration sites evaluated through desktop/mobile captures and a CSS-override fallback. Its installation also includes npm script dependencies, so it is more than a static prompt.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/ericzakariasson/scandinavian-design/blob/295742307b97fa0fb848f9be2d6e229ca517c736/README.md).

### AI Website Cloner

The README describes route mapping, desktop/mobile and alternate-state inspection, editable components and matched-size comparison. It uses a Next.js/React/shadcn/Tailwind stack and distinguishes owned-site migration from impersonation or copying protected branding.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/JCodesMore/ai-website-cloner-template/blob/ee3f5a2f31fd549b9593fa4f7cf6d2955ee593bb/README.md).

### Superdesign

The current web workflow retains side-by-side design variants and exports editable HTML; its skill hands that output to a coding agent working in the target repository. The provider expressly distinguishes its current non-open-source product from the older unmaintained IDE extension.

**Limits:** Homepage yielded no readable content; primary product articles reviewed. No authenticated export, API contract, privacy audit or code quality test.

**Primary sources (accessed 2026-11-01):** [source 1](https://superdesign.dev/blog/ai-ui-generator-exports-code); [source 2](https://superdesign.dev/blog/how-to-build-ai-landing-page).

### Variant

The public terms grant the provider broad ongoing rights to use Materials and Output for operating and improving its offerings. They also bar unauthorized scraping/integrations and AI-system creation, training, testing or improvement from outputs. The service-access license is personal and noncommercial.

**Limits:** Homepage exposed no readable interface. Export formats and an approved integration API were not verified; commercial use would require resolving the public terms with the provider.

**Primary sources (accessed 2026-11-01):** [source 1](https://variant.com/); [source 2](https://variant.com/terms-and-privacy).

### Khroma

The site says its preference-learning color algorithm runs in the browser. It supports palette, type and gradient views, hue/value and color filters, saved combinations, CSS/RGB/hex output and WCAG ratings for color pairs.

**Limits:** Local-processing statement is vendor documentation, not a network audit. No supported automation API or underlying-code reuse license verified.

**Primary sources (accessed 2026-11-01):** [source 1](https://www.khroma.co/).

### Noyzzi

The gallery presents interactive designs alongside prompts. Its privacy policy describes an anonymous localStorage identifier for likes, server-side counts, Cloudflare hosting and Microsoft Clarity session analytics only after cookie consent.

**Limits:** No account or code was used. No reuse grant was found on the inspected gallery/privacy pages; that is not proof no other license exists.

**Primary sources (accessed 2026-11-01):** [source 1](https://noyzzi.com/); [source 2](https://noyzzi.com/privacy/).

### Brik

Prompts create reusable tools with controllers, presets and timelines. Documentation distinguishes image/GIF/video exports, paid self-contained HTML with baked-in controller values that runs without a Brik account, and paid iframe embeds of published tools. Drafts are private; publishing creates unlisted-link or gallery access.

**Limits:** Export and privacy behavior were not exercised. Standalone HTML support does not prove every exported dependency is offline-safe. Wix terms and gallery asset rights require separate project-specific review.

**Primary sources (accessed 2026-11-01):** [source 1](https://brik.space/docs/what-is-brik); [source 2](https://brik.space/docs/exporting); [source 3](https://brik.space/docs/publishing-visibility).

### UIZZE

The guide separates a free anti-generic-UI skill from a paid MCP reference service exposing find_ui_references and find_ui_materials. Its useful evaluation exercise compares settings and billing screens under shared rules, existing components, preserved behavior and matched viewports; fixtures are explicitly synthetic rather than benchmark evidence.

**Limits:** The connect flow reached sign-in/checkout and was not pursued. Paid content, output rights and runtime protocol behavior were not independently audited.

**Primary sources (accessed 2026-11-01):** [source 1](https://uizze.com/); [source 2](https://uizze.com/codex-ui-design); [source 3](https://uizze.com/web-ui-references).

### Curio

The remote MCP supports authenticated search_styles, get_style and get_style_spec. Share links can return Markdown design specs or JSON manifests. Current docs describe one-time style unlocks, while the May 2026 terms still discuss subscriptions and rolling credits; commercial end-product use is permitted subject to restrictions against redistribution, competing offerings and training replicas.

**Limits:** No paid style was unlocked or copied. Public billing descriptions conflict; YAML metadata plus prose is not proof of compatibility with Google's typed DESIGN.md alpha.

**Primary sources (accessed 2026-11-01):** [source 1](https://designbycurio.com/); [source 2](https://designbycurio.com/docs); [source 3](https://designbycurio.com/mcp); [source 4](https://designbycurio.com/terms).

### FontCrafter

The FAQ describes browser-only handwriting-to-font processing: thresholding, connected components, contour tracing, simplification, smoothing and Bezier fitting. It lists OTF, TTF, WOFF2 and Base64 exports with ligature/contextual features. Fonts made from one's own handwriting may be used commercially; other handwriting requires permission.

**Limits:** No input was uploaded or font generated. Local-processing claims were not network-tested; legibility, font shaping and target-platform loading require separate checks.

**Primary sources (accessed 2026-11-01):** [source 1](https://arcade.pirillo.com/fontcrafter.html).

### SVG Loaders

The index aggregates sources rather than granting one universal license. SamHerbert/SVG-Loaders and n3r4zzurr0/svg-spinners have MIT license files requiring retained notices; their READMEs distinguish animated SVG/SMIL or CSS and note embedding/browser caveats. A selected local SVG avoids requiring a CDN service.

**Limits:** No individual animation was run and not every indexed source was licensed or audited. The aggregator's shorthand that MIT has no attribution requirements must not replace the actual notice condition.

**Primary sources (accessed 2026-11-01):** [source 1](https://magecdn.com/tools/svg-loaders); [source 2](https://github.com/SamHerbert/SVG-Loaders/blob/561eacac2f46e2b02e48df547324dcea94a6a1c5/LICENSE.md); [source 3](https://github.com/SamHerbert/SVG-Loaders/blob/561eacac2f46e2b02e48df547324dcea94a6a1c5/README.md); [source 4](https://github.com/n3r4zzurr0/svg-spinners/blob/abfa05c49acf005b8b1e0ef8eb25a67a7057eb20/LICENSE); [source 5](https://github.com/n3r4zzurr0/svg-spinners/blob/abfa05c49acf005b8b1e0ef8eb25a67a7057eb20/README.md).

### SVG Backgrounds

The editor offers SVG/CSS copying and SVG/PNG exports. Its license allows incorporation into personal/commercial end products, requires attribution without an active subscription, and forbids standalone redistribution, competing products, automated systems/templates for end-user creation and generative-AI training. Premium graphics have active-subscription and existing-project limits.

**Limits:** No asset downloaded. Individual manual end-product rights do not authorize putting a reusable graphics corpus into Litha.

**Primary sources (accessed 2026-11-01):** [source 1](https://www.svgbackgrounds.com/set/free-svg-backgrounds-and-patterns/); [source 2](https://www.svgbackgrounds.com/license/).

### Realtime Colors

The preview maps text/background and primary, secondary and accent roles onto a sample page and offers export formats including CSS, SCSS, image/ZIP and QR. It links a Figma plugin; the displayed mock pricing section is part of the demonstration rather than proof of real service pricing.

**Limits:** No palette export or plugin was executed. Underlying-code license and supported automation API were not established; a sample page is not Litha accessibility evidence.

**Primary sources (accessed 2026-11-01):** [source 1](https://www.realtimecolors.com/).

### Transitions.dev

The README describes namespaced CSS snippets with semantic variables and reduced-motion guards, CLI/skill flows and a Refine path that can inject a panel and run a local relay. The license makes tooling MIT but applies custom terms to transitions/skills: end-product use allowed, competing collection redistribution forbidden, and template/theme distribution subject to plan and notice conditions.

**Limits:** No CLI, panel, relay or skill was installed. Free/paid counts differ across pages; no independent quality or runtime review of all transitions.

**Primary sources (accessed 2026-11-01):** [source 1](https://transitions.dev/); [source 2](https://transitions.dev/skill.html); [source 3](https://github.com/Jakubantalik/transitions.dev/blob/e3aefb554d8fd2cb3e91e773e82a0f2d5a4f82a0/README.md); [source 4](https://github.com/Jakubantalik/transitions.dev/blob/e3aefb554d8fd2cb3e91e773e82a0f2d5a4f82a0/LICENSE); [source 5](https://github.com/Jakubantalik/transitions.dev/blob/e3aefb554d8fd2cb3e91e773e82a0f2d5a4f82a0/skills/transitions-dev/LICENSE.txt).

### Beautiful HTML Templates

The README presents 34 HTML slide templates and directs agents through an index and operating instructions to match a brief and adapt content. It reports MIT licensing; this review did not inspect all template markup or embedded assets.

**Limits:** Pinned README and repository metadata/tree reviewed; not a complete skill, script, dependency or runtime audit.

**Primary sources (accessed 2026-11-01):** [source 1](https://github.com/zarazhangrui/beautiful-html-templates/blob/e5e204fb1f3b06290846e7dcd7aceddabeceec8c/README.md).

### daisyUI

The core library provides Tailwind-compatible CSS components and themes and has a pinned MIT license. Blueprint is a separate license-key product organized around setup, rules, creative direction, architecture, syntax and quality-agent roles; its commercial access is not covered merely by the core MIT license.

**Limits:** No package or MCP was installed. Marketing token/quality gains were not validated; the purchase page provided no additional readable license text.

**Primary sources (accessed 2026-11-01):** [source 1](https://daisyui.com/); [source 2](https://daisyui.com/blueprint/); [source 3](https://github.com/saadeghi/daisyui/blob/bf3bac3a397b543e55641ecb2d60a2ed961f09ec/README.md); [source 4](https://github.com/saadeghi/daisyui/blob/bf3bac3a397b543e55641ecb2d60a2ed961f09ec/LICENSE).

### Pryzm

The FAQ describes browser WebGL composition and local rendering during editing, but saving a look uploads its photo and preview to the account. Paid exports include live Framer/React/HTML components. Terms allow exported media/code in personal/client/commercial products but prohibit standalone stock/code resale and a competing background generator.

**Limits:** Browser-local rendering is not an offline guarantee. No export or upload was performed; native Roblox cannot consume browser WebGL components directly.

**Primary sources (accessed 2026-11-01):** [source 1](https://pryzm.design/); [source 2](https://pryzm.design/terms).

### Logosystem

The gallery provides filters, animated logos, app icons and a moodboard tool, with links to original designers. Its FAQ distinguishes free browsing from reuse rights: examples remain their respective owners' property.

**Limits:** No logos or moodboards were copied. No underlying asset license or API access was inferred from gallery availability.

**Primary sources (accessed 2026-11-01):** [source 1](https://logosystem.co/).

### Ditther

The site describes layered effects, image/video inputs, reusable looks and local browser media processing without server uploads. Core editing is free; video/4K, watermark removal and presets have paid boundaries.

**Limits:** The terms link failed with a redirect loop. Pricing statements were inconsistent across the page; no price recommendation, output-rights conclusion or runtime privacy test is made.

**Primary sources (accessed 2026-11-01):** [source 1](https://www.ditther.com/); [source 2](https://www.ditther.com/terms.html).

### Book of Shapes

The output license allows personal/commercial use and modification without attribution, but prohibits SVG/clip-art packs, template libraries and competing generators based on the patterns. Joy Division, Joy Division Mesh and Brockmann Beethoven Arcs are study-only exceptions. Underlying node graphs and site code are excluded.

**Limits:** No patterns were generated or downloaded. A permission to use a finished output is not permission to import the source library into Litha.

**Primary sources (accessed 2026-11-01):** [source 1](https://bookofshapes.com/?tag=flow); [source 2](https://bookofshapes.com/license).

### Laws of UX

The site organizes conceptual articles with examples and further reading. Its Miller article explicitly warns against imposing arbitrary limits from the familiar memory number, recommends meaningful chunking, and acknowledges individual/context variation.

**Limits:** The linked empirical papers were not independently reviewed here. Concept summaries are not numerical accessibility or usability acceptance tests, and poster availability is not a corpus redistribution grant.

**Primary sources (accessed 2026-11-01):** [source 1](https://lawsofux.com/); [source 2](https://lawsofux.com/millers-law/).

### Craftwork

The October 2026 license distinguishes third-party inspiration with no reuse license, commercial packs, individually open-source components and commercial components. It restricts redistribution, generators/registries/datasets and use of catalog assets/previews/prompts for AI training, fine-tuning or testing; hosted embeds and downloaded files also have different subscription effects.

**Limits:** No assets, prompts or code were downloaded. A site-level list of MIT/Apache/BSD/ISC examples does not make every component open source.

**Primary sources (accessed 2026-11-01):** [source 1](https://craftwork.design/inspiration/websites); [source 2](https://craftwork.design/license).

### Zajno Motion

The page teaches easing, delays, real-time versus after-action motion and attention through interactive examples. It is educational material rather than an installed UI runtime or a demonstrated performance/accessibility benchmark.

**Limits:** Demos were not run or copied. No general license for reproducing examples or assets was established.

**Primary sources (accessed 2026-11-01):** [source 1](https://motion.zajno.com/).

### aiux.courses

The directory labels recommendations with signal, verified date, intended audience, level and price band. Its About page states that rankings are not sold, there are currently no affiliate commissions, and an unnamed working designer curates the shelf.

**Limits:** Provider claims and course quality were not independently validated, and linked papers were not read merely by reviewing the directory.

**Primary sources (accessed 2026-11-01):** [source 1](https://aiux.courses/); [source 2](https://aiux.courses/about).

### Vibe Coding UI Specification

The v1.0 page organizes tokens, component states, responsive rules, accessibility, motion and quality gates into a Markdown/YAML contract. It requires real decisions for placeholders, an explicit agent-instruction link and acceptance checks, and says the resource is free to copy and adapt.

**Limits:** The Markdown download returned an unsupported-content error in the research reader. Only the public excerpt/page was inspected; no complete schema-validation or software license was inferred.

**Primary sources (accessed 2026-11-01):** [source 1](https://horizonx.so/resources/vibe-coding-ui-specification); [source 2](https://horizonx.so/resources/vibe-coding-ui-specification.md).

### Delightful frontend

The official article recommends explicit design constraints, realistic content, visual references and rendered verification with Playwright. Its example prompt contains promotional-page assumptions about large heroes, imagery and motion, while explicitly preserving an existing website or design system. Litha should carry over the constrained review process and choose surface-appropriate composition independently.

**Limits:** Official guidance and examples were reviewed; no demonstrated model result is treated as a measured result for Litha or its local models. The article does not establish a general reason to redesign an operational app as a promotional site.

**Primary source (accessed 2026-11-01):** [official article](https://developers.openai.com/blog/designing-delightful-frontends-with-gpt-5-4).

### Explicit access limits

There are **six limited public/paid paths**, not six unreviewed catalog entries: two unreadable homepages with readable primary alternatives (Superdesign and Variant), two unreadable specific documents (Ditther terms and the HorizonX Markdown download), and two gated or unreadable paid paths (UIZZE connect and daisyUI Blueprint checkout). Public product evidence was reviewed for all six. Separately, the earlier OpenDesign recursive-tree request failed while its pinned README/license succeeded. The Delightful frontend article was directly reviewed without an access limitation.

| Entry | Limited path | Remaining uncertainty |
|---|---|---|
| Superdesign | [observed URL](https://superdesign.dev/) | Homepage had no readable lines; two primary product articles supplied current product/export evidence. |
| Variant | [observed URL](https://variant.com/) | Homepage had no readable lines; primary public terms were readable. Export/API contract remains unverified. |
| Ditther | [observed URL](https://www.ditther.com/terms.html) | Redirect loop blocked terms; product FAQ was readable. Output license not established. |
| Vibe Coding UI Specification | [observed URL](https://horizonx.so/resources/vibe-coding-ui-specification.md) | Research reader did not support the Markdown download; explanatory page/excerpt and copy/adapt permission were readable. |
| UIZZE | [observed URL](https://uizze.com/) | Connect path reached sign-in/checkout; public guide and reference pages reviewed, no authenticated/paid content accessed. |
| daisyUI Blueprint | [observed URL](https://daisyui.com/blueprint/checkout/) | License/purchase link yielded an unreadable checkout page; public Blueprint page and core MIT license reviewed. |

## Licensing and source provenance

License metadata is useful for discovery, but path-level checks take precedence. Explicitly checked primary license files:

| Source | Verified license scope |
|---|---|
| awesome-ai-tools-for-ui | No license file in complete four-entry tree; no detected license |
| Impeccable | Apache-2.0; retain relevant NOTICE information |
| UserInterface.wiki | MIT |
| UI UX Pro Max | MIT |
| Anthropic frontend-design | Apache-2.0 at the skill directory; no blanket repo-level assertion |
| Taste Skill | MIT; image provenance is a separate question |
| shadcn/ui | MIT; registry resources/dependencies need their own review |
| Web Interface Guidelines | MIT; agent-skills wrapper has no license file in pinned tree |
| Interface Design | MIT |
| Design and Refine | No license file in pinned complete tree |
| Awesome DESIGN.md | MIT for the repository; external brand assets are separate |
| Google DESIGN.md | Apache-2.0; alpha specification |
| Cursor Unslop | MIT at pstack/LICENSE; not a claim about all cursor/plugins |
| Refactoring UI skill | MIT for original repository write-up/code/tokens; book rights expressly excluded |
| Scandinavian Design | No license file in pinned complete tree |
| OpenDesign | Apache-2.0; runtime/privacy and bundled external asset notices require separate review |
| TypeUI | Commercial EULA; standalone redistribution and competing resource datasets restricted |
| AI Canvas | Primary FAQ says free library MIT, Premium proprietary; per-resource check required |
| Superdesign | Current product article says the web product is not open source; old IDE extension is a separate unmaintained project |
| Variant | Public terms limit service access to personal noncommercial use and restrict integrations and AI-system improvement from outputs |
| Curio | Commercial end-product use subject to terms; catalog redistribution, competing offerings and training replicas restricted |
| SVG Loaders upstreams | SamHerbert/SVG-Loaders and n3r4zzurr0/svg-spinners MIT files verified; notices must be retained; other indexed sources are separate |
| SVG Backgrounds | End-product license with attribution/subscription limits; automated end-user generation systems and generative-AI training excluded |
| Transitions.dev | Tooling MIT; transitions and skills under custom end-product license with competing-library and template distribution limits |
| daisyUI | Core CSS MIT; Blueprint is a separate paid product and not implicitly covered by the core license |
| Pryzm | Exported media/code allowed in end products; standalone stock/code redistribution and competing generator restricted |
| Logosystem | FAQ expressly reserves displayed logos to their respective brands/designers; reference browsing grants no reuse license |
| Book of Shapes | Generated outputs permitted, pattern-library redistribution excluded; three named studies and underlying node graphs/code excluded |
| Craftwork | Inspiration has no reuse license; mixed per-item code/asset licenses and explicit catalog/AI-use restrictions |
| HorizonX UI specification | Public page expressly permits copying/adapting; full downloadable file and a formal software license were not inspected |

No license or lack of a detected root license should be inferred from a site's “open source” label alone. Conversely, a monorepo with no root license can contain a specifically licensed subdirectory, as the Anthropic and Cursor examples show. This research did not authorize or perform redistribution of third-party materials.

### Repository pin appendix

These are observed default-branch snapshots, not assertions that every repository was code-audited. “Metadata” is GitHub's detected license field; see the path-level table above for exceptions.

| Repository | Commit | Commit date (UTC) | License metadata |
|---|---|---|---|
| [maxbogo/awesome-ai-tools-for-ui](https://github.com/maxbogo/awesome-ai-tools-for-ui/tree/680b351764199b9b6b4352d3ea5af0bce927b6ed) | `680b351764199b9b6b4352d3ea5af0bce927b6ed` | 2026-09-25T18:28:07Z | none |
| [pbakaus/impeccable](https://github.com/pbakaus/impeccable/tree/4f956490f0056ae1ff5ea80372cf56e83c001d3c) | `4f956490f0056ae1ff5ea80372cf56e83c001d3c` | 2026-10-31T18:13:22Z | Apache-2.0 |
| [raphaelsalaja/userinterface-wiki](https://github.com/raphaelsalaja/userinterface-wiki/tree/256a954080c8bcf1b1ceb1e2a4079d1f24cf593a) | `256a954080c8bcf1b1ceb1e2a4079d1f24cf593a` | 2026-03-17T17:35:29Z | MIT |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/bf41cbc3ce63e30c922e58ef48741ba6133f9aa9) | `bf41cbc3ce63e30c922e58ef48741ba6133f9aa9` | 2026-10-31T16:07:44Z | MIT |
| [anthropics/skills](https://github.com/anthropics/skills/tree/ca45fc496a3436251f191354091d557da31c15b5) | `ca45fc496a3436251f191354091d557da31c15b5` | 2026-10-28T19:20:38Z | none |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill/tree/12af471f627f866411b4bd785b19646d3672784c) | `12af471f627f866411b4bd785b19646d3672784c` | 2026-10-24T23:42:19Z | MIT |
| [shadcn-ui/ui](https://github.com/shadcn-ui/ui/tree/c0d63c339d6cd2fc26135590a54cf1f362269451) | `c0d63c339d6cd2fc26135590a54cf1f362269451` | 2026-10-31T20:40:44Z | MIT |
| [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills/tree/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62) | `1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62` | 2026-10-27T21:40:02Z | none |
| [vercel-labs/web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines/tree/434b7f91364665f2f733b310ec54809bf8f37937) | `434b7f91364665f2f733b310ec54809bf8f37937` | 2026-10-05T20:49:16Z | MIT |
| [Dammyjay93/interface-design](https://github.com/Dammyjay93/interface-design/tree/2f9be3206855bcb2d1d0af262c8bae25cba6658d) | `2f9be3206855bcb2d1d0af262c8bae25cba6658d` | 2026-06-20T11:32:44Z | MIT |
| [0xdesign/design-plugin](https://github.com/0xdesign/design-plugin/tree/913a7ab2ac7e0f48eab77c93f2f5376150864b02) | `913a7ab2ac7e0f48eab77c93f2f5376150864b02` | 2026-09-17T16:07:52Z | none |
| [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md/tree/fcc70284932276d085f01ef9f83edde90b1258cb) | `fcc70284932276d085f01ef9f83edde90b1258cb` | 2026-10-28T15:45:37Z | MIT |
| [jakubkrehel/make-interfaces-feel-better](https://github.com/jakubkrehel/make-interfaces-feel-better/tree/35545ea1512ad59fa463e6b1f95ca9c052981fe6) | `35545ea1512ad59fa463e6b1f95ca9c052981fe6` | 2026-08-29T16:59:35Z | MIT |
| [emilkowalski/skills](https://github.com/emilkowalski/skills/tree/a81dbca07f2217b7103e510c0f13f8d5b017afc9) | `a81dbca07f2217b7103e510c0f13f8d5b017afc9` | 2026-10-28T18:25:28Z | MIT |
| [cursor/plugins](https://github.com/cursor/plugins/tree/ae5650febf4320793844c12c4adaa937f417f8da) | `ae5650febf4320793844c12c4adaa937f417f8da` | 2026-11-01T00:10:38Z | none |
| [s0xDk/refactoring-ui-skill](https://github.com/s0xDk/refactoring-ui-skill/tree/48872143abb0a8feb6d9bf58e222afbd800210b0) | `48872143abb0a8feb6d9bf58e222afbd800210b0` | 2026-08-26T22:47:16Z | NOASSERTION |
| [Owl-Listener/designer-skills](https://github.com/Owl-Listener/designer-skills/tree/9a6930cf84a822eb458624bd11c61aac5bbdf224) | `9a6930cf84a822eb458624bd11c61aac5bbdf224` | 2026-09-05T15:32:50Z | MIT |
| [maxbogo/yc-web-design-strategy-skill](https://github.com/maxbogo/yc-web-design-strategy-skill/tree/bf9e5ace80a958f25dbe60989762770bdcf3505f) | `bf9e5ace80a958f25dbe60989762770bdcf3505f` | 2026-03-23T19:00:45Z | MIT |
| [bencium/bencium-marketplace](https://github.com/bencium/bencium-marketplace/tree/5de46a39b4640fa419560cd0b67e4c4b50dac802) | `5de46a39b4640fa419560cd0b67e4c4b50dac802` | 2026-10-04T09:16:45Z | MIT |
| [CloudAI-X/threejs-skills](https://github.com/CloudAI-X/threejs-skills/tree/0e181866f095b5f06d005133876e926515390d95) | `0e181866f095b5f06d005133876e926515390d95` | 2026-10-19T05:17:17Z | MIT |
| [bitjaru/styleseed](https://github.com/bitjaru/styleseed/tree/ce66f1dc1d14609ec43bc48eed1d97abb51489c8) | `ce66f1dc1d14609ec43bc48eed1d97abb51489c8` | 2026-10-28T03:07:06Z | MIT |
| [OneRedOak/claude-code-workflows](https://github.com/OneRedOak/claude-code-workflows/tree/29a34c725313c7621f426f838ed31cf482473fb4) | `29a34c725313c7621f426f838ed31cf482473fb4` | 2026-10-09T05:59:19Z | MIT |
| [alchaincyf/huashu-design](https://github.com/alchaincyf/huashu-design/tree/9b01ee8751679724dd43d855a532944aaa2c2b59) | `9b01ee8751679724dd43d855a532944aaa2c2b59` | 2026-10-30T17:50:57Z | MIT |
| [dominikmartn/nothing-design-skill](https://github.com/dominikmartn/nothing-design-skill/tree/74affbb786af098b18503467b205c10a7df30126) | `74affbb786af098b18503467b205c10a7df30126` | 2026-04-01T05:40:01Z | MIT |
| [nutlope/hallmark](https://github.com/nutlope/hallmark/tree/4f6a46c6dc325d40ab268c93e25c7b96676ebccd) | `4f6a46c6dc325d40ab268c93e25c7b96676ebccd` | 2026-10-29T16:50:04Z | MIT |
| [hamen/material-3-skill](https://github.com/hamen/material-3-skill/tree/14385f2bf3804d8779f8b4db2604211f1e70b4c1) | `14385f2bf3804d8779f8b4db2604211f1e70b4c1` | 2026-07-15T22:10:48Z | MIT |
| [ericzakariasson/scandinavian-design](https://github.com/ericzakariasson/scandinavian-design/tree/295742307b97fa0fb848f9be2d6e229ca517c736) | `295742307b97fa0fb848f9be2d6e229ca517c736` | 2026-08-22T17:02:53Z | none |
| [JCodesMore/ai-website-cloner-template](https://github.com/JCodesMore/ai-website-cloner-template/tree/ee3f5a2f31fd549b9593fa4f7cf6d2955ee593bb) | `ee3f5a2f31fd549b9593fa4f7cf6d2955ee593bb` | 2026-10-05T08:06:55Z | MIT |
| [nexu-io/open-design](https://github.com/nexu-io/open-design/tree/12d970eacc8971150e3c76470d2a9afe16dc2ed1) | `12d970eacc8971150e3c76470d2a9afe16dc2ed1` | 2026-10-30T04:05:01Z | Apache-2.0 |
| [21st-dev/magic-mcp](https://github.com/21st-dev/magic-mcp/tree/6b5299e8a83ceffa73d4fc4e148905bb3eeeeb55) | `6b5299e8a83ceffa73d4fc4e148905bb3eeeeb55` | 2026-09-09T20:38:21Z | ISC |
| [zarazhangrui/beautiful-html-templates](https://github.com/zarazhangrui/beautiful-html-templates/tree/e5e204fb1f3b06290846e7dcd7aceddabeceec8c) | `e5e204fb1f3b06290846e7dcd7aceddabeceec8c` | 2026-06-09T23:59:36Z | MIT |
| [paper-design/shaders](https://github.com/paper-design/shaders/tree/1923e9f536ea079e2a95d23291cbfacfd69d37f6) | `1923e9f536ea079e2a95d23291cbfacfd69d37f6` | 2026-10-25T14:08:57Z | Apache-2.0 |
| [google-labs-code/design.md](https://github.com/google-labs-code/design.md/tree/6e5da5382f41edbba9d73b2c62f33f32e9971f15) | `6e5da5382f41edbba9d73b2c62f33f32e9971f15` | 2026-10-16T18:21:40Z | Apache-2.0 |
| [zeke/swiss-design-skill](https://github.com/zeke/swiss-design-skill/tree/285009f3dc4ba311f59bb757973274de2c9446c3) | `285009f3dc4ba311f59bb757973274de2c9446c3` | 2026-09-24T01:37:14Z | MIT |
| [ibelick/prompt-kit](https://github.com/ibelick/prompt-kit/tree/5a9496635cc0e1bf7679fe2a9e35d9b36b99c08a) | `5a9496635cc0e1bf7679fe2a9e35d9b36b99c08a` | 2026-09-28T13:33:24Z | MIT |
| [aicanvas-me/aicanvas](https://github.com/aicanvas-me/aicanvas/tree/8164f1e423e4e654dd0828a941ba5cdda69f08fe) | `8164f1e423e4e654dd0828a941ba5cdda69f08fe` | 2026-10-30T22:36:15Z | MIT |
| [Jakubantalik/transitions.dev](https://github.com/Jakubantalik/transitions.dev/tree/e3aefb554d8fd2cb3e91e773e82a0f2d5a4f82a0) | `e3aefb554d8fd2cb3e91e773e82a0f2d5a4f82a0` | 2026-10-29T10:48:25Z | NOASSERTION |
| [saadeghi/daisyui](https://github.com/saadeghi/daisyui/tree/bf3bac3a397b543e55641ecb2d60a2ed961f09ec) | `bf3bac3a397b543e55641ecb2d60a2ed961f09ec` | 2026-10-13T11:44:04Z | MIT |
| [SamHerbert/SVG-Loaders](https://github.com/SamHerbert/SVG-Loaders/tree/561eacac2f46e2b02e48df547324dcea94a6a1c5) | `561eacac2f46e2b02e48df547324dcea94a6a1c5` | 2025-01-02T15:41:35Z | MIT |
| [n3r4zzurr0/svg-spinners](https://github.com/n3r4zzurr0/svg-spinners/tree/abfa05c49acf005b8b1e0ef8eb25a67a7057eb20) | `abfa05c49acf005b8b1e0ef8eb25a67a7057eb20` | 2023-03-06T02:52:05Z | MIT |

Machine-readable companions: [source catalog](litha-ui-source-catalog-20261101.json) (all 64 entries with evidence depth) and [source pins](litha-ui-source-pins-20261101.json) (40 catalog-related repository snapshots plus eight broader evidence/platform snapshots, 48 in total). No upstream skill content or runnable package is bundled.
