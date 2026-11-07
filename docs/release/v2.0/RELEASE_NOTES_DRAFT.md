# STAR Intelligence v2.0.0: release notes (DRAFT, not a release)

Draft written 2026-10-20 from what is merged into `star/next` (`798d88e7`) since v1.0.0. "Merged" means the pull
request passed CI and is in the branch. "Ran on real hardware" is written only where a notes file records the run; if a
feature is not in that list, assume nobody has used it outside the test suite. The measured-results and
not-tested sections are filled in by the checklist ([CHECKLIST.md](CHECKLIST.md), sections 3 and 5) before release.

## Before you upgrade

- Back up `%APPDATA%\STAR` first. Setup keeps it, and v1.0.0 kept it on the one PC where that was tested.
- All-users installs ask for administrator approval on every upgrade; Setup now keeps the scope you installed with
  (#458) and keeps the old copy working if an upgrade is refused or fails (#457, #217).
- The installer is not code-signed. Compare the file with `SHA256SUMS.txt`.

## What is new since v1.0.0 (merged into `star/next`)

STAR learns on its own, more honestly (server side; the app imports only reviewed candidates)
- Night school writes its own practice tasks at night from its failures and notes, free local models only, with a
  cap and a validator (#476). Ran on real hardware: live on brain 1 since 2026-10-17 (first cycle: 18 written,
  8 accepted), plus variants of solved tasks and one repair round (#478 is still a draft).
- Playtest learning: STAR builds small games, a robot playtests them in a real Studio, STAR fixes, re-playtests (#436,
  #438, #449). Ran on real hardware: Studio on the PC and on brain 1's Studio runner.
- Studio Lab v2/v3: parallel Studios, measured jump limits, UI fix loop, 43 specs, nightly timer (#268, #277, #292).
- Verified conductor duel (#473, opt-in): two writers, STAR's own checkers pick the winner, hash-only learning event.
- Instant memory with measured pre-solving (#435), GPU night turbo on the PC when idle (#434, #442), apprentice model
  pilot measured but not switched on (#437), RAMForge NUMA placement on brain 1 (+6.6 % generation, #386).
- Open Roblox benchmark: 20 Luau tasks checked in a real Studio playtest (#448).

Agents (all opt-in, nothing runs unless you turn it on)
- Agent fleet (#474): resource-sized worker slots, one git worktree per task, the fleet runs the tests itself, a
  passing task is only a proposal; never merges. ACP hand-off pilot (#475): STAR hands one turn to a local agent over
  the Agent Client Protocol, rejects its permission requests unless the host approves. Both tested with simulated
  agents only; no real OpenCode/Codex/Claude CLI run is recorded.
- Resource planner: live admission across brain 1, brain 2 and the PC (#266). Best-of-N for code (#270).
- Multi-model research and an offline cascade router (#374). Use my GPU: STAR's code model on the PC's NVIDIA card
  per request (#426).

Roblox and code quality
- Run and repair Luau before answering (#181), Luau retry ladder (#379), Roblox API checker for wrong
  event/property/method names (#443), deprecated-API/pcall/InvokeClient/leak rules (#330), module require graph
  preflight (#293), bundled Roblox API dataset for Studio 0.742 (#331), luau-analyze knows Roblox data types (#371).
- Sixteen more opt-in skill packs (combat, pathfinding, physics, tags, input, audio, specs, purchases, teleport, Open
  Cloud, cutscenes/FaceControls, VFX Studio, field lessons from the Paintball port, other engines) (#329, #351, #327,
  #284, #348). Routing by embedding similarity is a draft (#394).
- Motion Forge: Blender R15 draft animation and R6 preflight (#297, #369). STAR sees Blender on brain 2 (#289).

Issue fixes from the v2.0 milestone
- #118 two clients on one model slot: a pinned request no longer corrupts another client's answer (#450; live on
  brain 1). #120 and #121 installer behaviour (#457, #458, #217).
- #290 Brain 2 Studio/Blender evidence and task-specific Discord DMs, opt-in (#460): offline tests only; no native
  Studio/Blender run, no real DM delivery recorded.

Chat, app and performance
- Settings with seven sections, search and an unsaved-changes bar (#342); honest UI states (#340); worst-case data
  and narrow widths (#337); accessibility: axe-core tests, skip link, one h1, WCAG AA colour pairs (#352, #301, #303).
- Start thinking while you type (prompt-cache prefill, off by default) (#441); chat switch 75 ms -> 4 ms offline
  (#375); streaming re-parses only the live tail (#377); desktop start-up imports deferred (#339, #383); SQLite open
  6.8x faster (#341); Luau lint 2-5x faster (#322).
- Voice: Star mum persona, read-aloud, push-to-talk calls (#294); plain-language voice setup errors (#367).
- Discord: images (/draw), phone photos, server mode on brain 2, Studio Lab screenshots and visual corrections
  (#387, #391, #392, #287, #281, #283).
- Web: STAR Evidence Broker, reversible web context reduction (#401).

Research and documents (no runtime change): accelerator roadmap (#278), Knowledge Fabric (#306), STAR 2.0 agent
universe and conductor research (#413, #421, #425), Creator Intelligence (#271), Business OS and commerce research
(#404, #412, #416, #423), REA (#439), Codespaces acceleration (#496 on `main`).

## Off by default (you turn these on)

Every agent feature (fleet, ACP, duel, best-of-N, cascade router, GPU use), every new skill pack, Luau run-and-repair
and the retry ladder, instant memory, prefill, Discord features, Blender/Motion Forge, evidence broker. Night school,
the conductor and the GPU turbo run on the servers/PC under the owner's timers, not inside the app.

## Measured results

To be filled from the checklist's evaluation gate (section 5): golden v2 (34), creation (23), blind holdout (24),
paired against v1.0.0, with model, server, commit and date. No number is claimed until those runs exist.

## Not tested on real hardware or against real services

To be filled from the Windows acceptance (#444). Known today: no real OpenCode/Codex/Claude CLI run through the fleet
or ACP adapter; no native Studio/Blender -> Discord delivery for #290; apprentice model not trained; speculative
decoding measured on brain 1 but not switched on; the free API control center and diagnostic compaction (#407, #411)
are libraries with tests and no app wiring; STAR Clips (#431) has only draft PRs; the in-app updater cannot see a
v2.0 release until the public release channel is set up (checklist section 0).
