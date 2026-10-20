# STAR SkillForge: Safe Agent Skills Import and Priority Roadmap

**Date:** 2026-10-20  
**Scope:** private `star/next` development feature; not in the public installer.  
**Implementation:** `star/skill_import.py`, `scripts/skill_review.py`, and `tests/test_skill_import.py`.

## Decision

Add a **reviewed skill ingestion layer**, not indiscriminate automatic imports. STAR already has a read-only `SkillLibrary` (`star_skill_list` / `star_skill_load`), bounded Roblox/game skill packs, keyword selection and optional embedding routing. Their real-world effects must be measured before enabling more automatic loading.

Agent Skills are portable `SKILL.md` directories with optional `references/`, `assets/` and `scripts/` (https://agentskills.io/specification). The external prompt or metadata, including `allowed-tools`, **does not authorize** commands, MCP actions, network access, user data reads or publishing.

## Implemented now

1. Import preview parses an exact, local skill folder; validates its Agent Skills name, description and body; verifies declared license compatibility; rejects executable/binary/unexpected files and symlinks.
2. Requires a reviewer-supplied HTTPS repository URL, full Git commit SHA and an explicitly reviewed permissive license. Supported initial license IDs: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, CC0-1.0. Missing/restricted licenses do not automatically qualify.
3. Copies only UTF-8 `SKILL.md`, license notices, and text `references/` or `assets/`. Limits: at most 48 files, 64 KB per file, 512 KB total; no `scripts/`.
4. Owner approval is required for import; writes a deterministic SHA-256 manifest into `<home>/skills/<name>/.star-source.json` and refuses overwrites.
5. Imported skills cannot shadow STAR's bundled skills by name. Existing `SkillLibrary` sees the installed reference material when skills are explicitly enabled. The importer **does not execute** any of its scripts or auto-add the skill to every turn.
6. `verify` detects changes against the local snapshot. It does **not** verify origin authenticity, signatures, or tampering with the manifest itself.

The URL/commit record is **provenance metadata supplied by the reviewer**, not proof of an independently verified upstream commit. Do not label imported skills “trusted” solely from their digest.

## Owner CLI (source checkout, not packaged UI)

Start with a skill directory already downloaded *and reviewed* through your normal process. Inspect its upstream license; never run an upstream install script merely to read its documentation. Substitute real values for the illustrative ones here:

```bash
python -m scripts.skill_review preview \
  --source /reviewed/skills/code-review \
  --source-url https://github.com/example/skill-library \
  --commit aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --license MIT

python -m scripts.skill_review import \
  --source /reviewed/skills/code-review \
  --source-url https://github.com/example/skill-library \
  --commit aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --license MIT \
  --home /path/to/STAR-user-data \
  --approve

python -m scripts.skill_review verify \
  --home /path/to/STAR-user-data --name code-review
```

The `example` URL and commit above are placeholders, not verified sources. Existing personal skills are **never replaced** automatically; compare and review updates separately.

## High-impact external sources to evaluate

| Collection | Relevant specialization | Next evaluation |
| --- | --- | --- |
| [Agent Skills standard](https://agentskills.io/specification) | Portable progressive-disclosure format | Spec parity and strict import fixtures |
| [AionUI](https://github.com/iOfficeAI/AionUi) | Built-in, custom, extension skills; per-chat selection | UI ideas; do not copy restricted assets |
| [Anthropic Skills](https://github.com/anthropics/skills) | Reusable task workflows | Per-skill license check: some files are source-available, not open-source |
| [OpenAI Plugins](https://github.com/openai/plugins) | Agent tool/skill packaging | Per-plugin license and capability audit |
| [Superpowers](https://github.com/obra/superpowers) | Planning, debugging, TDD and verified completion | Benchmark on actual STAR repo bugs |
| [GameDev Agent Skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills) | Roblox, Unity, Unreal, Godot, Blender, audio and VFX | Real engine/build/playtest acceptance |
| [Vercel Agent Skills](https://github.com/vercel-labs/agent-skills) | React UX and performance | Browser, accessibility and screenshot tests |
| [Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills) | Reproducible scientific workflows | Numerically verified research tasks |

These are **candidates**. None are automatically downloaded, imported, endorsed as safe, or proven to boost STAR by this PR.

## Why skills alone do not make STAR smarter

A large library can cost context and route incorrectly. For user-visible quality improvement, compare identical work with (A) no skill, (B) one selected skill, and (C) a competing skill, using independent evaluators and sealed holdouts. Track task success, visual/game quality, latency, resource cost and failure rate. The private v1.0 README reports 9/24 blind Roblox tasks, so quality gains must be verified rather than promised.

## Highest-value follow-on gates

**P0: make existing creation loops work better**
- Roblox: Studio play-mode tests, full Luau/API checks, animation/VFX visual capture, frame-time regressions and real-world use of OpenGameEval-style evaluations.
- Web design: actual rendered screenshots at multiple sizes, style-reference comparison, accessibility, clicks, animation and overlap detection.
- Debugging: reproduce → isolate cause → small fix → tests → runtime proof; no unverified “done” messages.

**P1: multimedia and Discord**
- Video: timestamped frames + aligned transcription + non-speech events + speaker turns; attach an evidence timestamp for every claim.
- Music: instrument/time/tempo analysis, stems and editable MIDI when tools allow; do not imply perfect source separation.
- Voice: verify existing microphone/call/barge-in pipeline on actual PC audio devices before adding more personality presets.
- Discord: verify Components V2 layouts and real native voice message behavior. Full-duplex voice reception is separately gated by Discord voice protocol compatibility and explicit consent.

**P2: quality and speed**
- Build the owner-visible Skills UI: preview source/license, show active skills per chat, compare outcomes and roll back.
- Add independent upstream commit/signature checks and reviewed update diffs.
- Add semantic routing only after measured gains; keep short fast-path turns free of unnecessary skill text.
- Introduce resource-aware GPU scheduling for 8 GB local generation, heavy media jobs and CPU servers.

## Acceptance and release policy

- Execute the new importer regression tests plus adjacent skill routing and skill pack suites.
- Run an explicit malicious/oversized/symlink/no-approval fixture; preserve existing skill content after failed imports.
- Keep this branch as a reviewable PR against private `star/next`. It must not auto-merge or deploy to a public release.
- Do not claim production compatibility from unit tests alone. Require a tested Windows acceptance path and private integration review before release.
