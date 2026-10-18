# Changelog

All notable changes to STAR are recorded here, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.

This section covers everything merged into `star/next` after the `v0.9.0` tag, up to the v1.0.0 release PR (#254).
Entries are taken from pull request titles and merge messages, one line per pull request. "Opt-in" and "default off"
are used only where the pull request title says so. A merged pull request is not proof that a feature ran on the
owner's PC; check the pull request for what was tested.

## [1.0.1] - release candidate (not yet public)

### Changed
- Separate **private** STAR source development (`oncoursemail/Star-AI-Private`) from the new **public** `oncoursemail/Star-AI` distribution repository.
- Private Windows CI builds and checks source/hash provenance; the public publisher requires a **manual** main-branch workflow run and a GitHub App installation token restricted to the public downloads repository.
- Removed private GitHub Pages deployment; the new public repository hosts an independent, source-free downloads portal.
- Improved migration documentation, explicit no-release states and tests for private-to-public release boundaries.
- Optional private artifact attestations on eligible plans; SHA-256 package integrity checks remain mandatory. No claim of code signing.

### Release status
- This version is **not released**. The public repository initially contains no installer. A future release requires independent CI and real Windows QA, GitHub App credentials, owner approval and anonymous download verification. The historic v1.0.0 release is accessible only in the now-private source repository.

## [1.0.0] - published 2026-10-14 (legacy repository now private)

The release PR (#254) bumps the version, adds release notes and updates the website. Check the GitHub Releases page for
whether the v1.0.0 artifacts have actually been published.

### Added

- Discord: owner-only bot with DM chat and `/ask`, `/image`, `/screen`, `/status`, `/digest`, local token file (#226, earlier #102); time on every message and cited live web results (#267).
- STAR knows the time and can use the internet without paid keys: clock line, `star_clock`, SearXNG, web fetch (#265).
- Chat: rename and delete with Undo, Look at my screen, animated Star, quieter site (#228); animated Star mascot with reduced-motion safety (#172); mascot in the app with one copy of the art (#156); read-only Brain overview with six data groups (#135); streaming answers keep running across navigation (#115).
- Self-learning: per-cause practice tasks with runnable checks, 300 tasks (#255); "What STAR learned this week" with a 14-day trial, undo and keep, and owner corrections as regression-test candidates (#256); night school, where STAR practises Roblox tasks while the brain is idle (#153); failure ledger that attributes stored evaluation failures and generates targeted practice (#177); import of server-learned lessons as opt-in local candidates (#176); proposal-only lesson hygiene report (#137).
- Lesson candidates: invented Roblox API names (#251), logic and missing features (#247), strict Luau types (#246), character lifecycle (#261), self-check truncation scanner (advisory) (#250).
- Practice tasks: 20 Roblox server-security tasks (#197), 25 beginner find-and-fix debugging exercises (#198), 12 round-lifecycle scoring contracts (#209).
- Evaluation: paired statistical gate and protected-closure guard (#219); guard for reviewed Roblox train/eval splits (#231).
- Opt-in features (each described as opt-in or default off in its pull request): Godot 4 skill packs and GDScript static evals (#237); six game-design skill packs (#138); DataStore, remotes and TweenService packs (#201); game math pack (#166); worked examples (#230, #262, #263); bounded research and coding specialists (#196); Asset Forge and Poly Haven metadata (#192); Luau checks for server/client trust (#221) and for busy loops, touch rewards and connection lifetime (#220); official Luau analyzer second opinion (#193); StyLua formatting (#188); Roblox Full API dump name checker (#200); bounded continuation of cut-off code answers (#182); instant answers on this PC, default off (#243); design database, DESIGN.md lint, map plan dry runs and live Roblox docs tools (#216); shared brain store, protocol and guarded runtime tools (#239); local Blender tools behind two switches, both off (#112); Brain 2 MCP smoke probe and registry search (#107); research watch of five documentation pages, automatic check off (#113).
- Roblox tooling (standalone or source checkout only): JSON-to-Luau UI compiler (#232), VFX compiler (#149), remote compiler (#124), player-data schema compiler (#174), environment craft toolkit (#110), template build planner (#129), incremental Rojo project builder (#123), read-only Roblox project source preflight (#258), Roblox XML model/place reader (#141), deterministic Studio error explanations (#140), read-only multi-Studio discovery tests (#170), pinned Luau CLI runner for template specs (#165), fail-closed Luau spec results (#257).
- Agent: safe numerical calculator tool (#131); data profiles and read-only Obsidian links (#157); Brain 2 practice runner, command line only (#160); STAR Workbench connector (#154); conversation turn filtering (#150).
- Pictures can be requested from the ordinary chat (#128).
- Performance and training: Discord chat speed with quick-model fast path, streaming and cache-stable history (#264); brain config and benchmark scripts with 2026-10-13 results (#225); GPU training pilot with EmbeddingGemma retrieval fine-tune and QLoRA feasibility notes (#248).
- Planning and research documents: multi-Studio playtest plan (#207), unified research resource planner (#206), Tool Intelligence Scout (#212), Roblox-free Luau test runner design (#202), 2026 tooling scout (#186), architecture triage (#191), independent native waveform evidence foundation (#178).

### Changed

- Setup explains the all-users upgrade administrator prompt before it starts (#218, #175).
- Windows release provenance: main-only artifact attestations and verification (#114).
- Offline updater harness and safe shutdown before Setup (#164).
- Tailscale/CGNAT opt-in is passed to every server check (#168).
- Roblox craft audits and prompt gating repaired on the integration base (#169).
- Website and README repaired for v0.9.0 (#171); release claims audited and unsupported wording qualified (#190, #205).
- Offline Luau stand-in applies inherited `IsA` correctly (#222).
- Test coverage added for five Python modules (#199) and five frontend modules (#195).

### Fixed

- A chat turn can move off a slot another STAR client is using (#215; slot collision repair #125).
- Retries no longer leak across chats after navigation (#183).
- Close-request cleanup hardened; interrupted turns are preserved (#126).
- Data compiler keywords and a hermetic Discord doctor test (#253).
- Flaky tests: quiet-lock corpus planning made deterministic (#214); night-school test adapted to the paired gate (#229, #208); Windows workflow tests skipped when PowerShell 7 is missing (#180); frontend test timeout raised to 20 seconds (#156).

### Security

- Security review 2: legacy archive extraction hardened, residual risks documented (#134).
- Opt-in Luau trust and lifetime checks with metamorphic regression tests (#221, #260).

[1.0.0]: https://github.com/oncoursemail/Star-AI/compare/v0.9.0...star/next
