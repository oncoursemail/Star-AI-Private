# STAR Intelligence — Evaluation Cohort Integrity, Fast Game Agents, and Natural VTuber Roadmap
**Research + implementation note — 2026-11-05**
**Scope:** Host-owned evaluation advisory and measurable next experiments; no model deployment, remote game input, social interaction, public broadcasting, permission change, or training run.

## 1. A verified failure mode: reusing one suite is not reusing one measured experiment

The existing quality-gated route selector requires a pre-registered suite SHA-256, model-runtime profiles, fresh aggregate metrics, and matched per-case correctness. This is important, but the same suite can be run repeatedly. An aggregate measurement from experiment B and an ordered binary-case receipt from experiment A can have the same 30/30 or 29/30 count. A suite digest alone cannot establish that the two documents reflect the **same execution cohort**.

**Implemented in this change:** Optional `eval_cohort_sha256` fields on each aggregate and the paired receipt. Advising a nonbaseline route now fails closed unless all three share a non-null lowercase 64-character digest. Previously created evidence without this value still permits an independently qualified baseline, but cannot justify a faster model. All other model, task, workload, freshness, correctness, critical-task and QoS conditions remain required. This adds data association, not cryptographic proof.

**Trust boundary:** Generate one unique cohort identity **before** running the baseline/candidate experiment, on the trusted offline evaluator host. The 256-bit digest should bind an unpredictable per-execution nonce to immutable evaluator version, exact preregistered task suite, task order, rubric, target workload and hardware/driver profile. Store only the digest in the advisory summaries and ordered verdict receipt. Never derive it solely from the suite digest, current minute, or model response. No AI/chat text should be allowed to mint trusted receipts. Ensure summaries are produced from the same collected run and independently scored raw artifacts, not recomputed from model statements. A host claim is not a signature; follow up with a signed evaluator manifest and authenticated artifact hashes.

**Backward compatibility:** The field is optional for constructors and existing baseline-only workflows. *Promotion* to a different model is deliberately stricter and therefore existing external evaluators must update before they receive fast-route advice. Nothing selects, downloads, launches or swaps a worker on its own.

## 2. Evidence from primary external research

### Autonomous Roblox development
- [Roblox OpenGameEval (October 2026)](https://github.com/Roblox/open-game-eval) / [paper](https://arxiv.org/abs/2610.02563): revised dataset of 84 curated Studio tasks, 13 models and 16 attempts per task. OpenGameEval evaluates scene changes and **simulated gameplay** with executable checks, and distinguishes inspection from editing. The paper reports higher success associated with inspecting referenced objects first (13.4 percentage points on scene-only tasks; 9.8 on script-only tasks under their matching analysis). This is an association, not proof that inspection always causes success.
- [Roblox Studio's official MCP plugin](https://github.com/Roblox/roblox-studio-agent-plugin) exposes read-only tree/script inspection, Luau editing, screenshots, controlled playtests and console output, subject to project state and authorization. [Roblox April 2026 playtest-agent beta](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767) can simulate simple player interactions in Studio; availability varies with installed Studio features. A sandboxed build–inspect–test–repair loop is more defensible than treating generated Luau as a finished game.
- **Proposal:** Build a repeatable skill matrix for Star: UI interaction, pathfinding, checkpoints, inventory/shops, vehicle in/out, combat and co-op. Seed each task with hidden random variants and verifiable state assertions; track pass@1, pass@N, repair success, regressions, inspection coverage, wall-clock and compute cost. Separate held-out testing from training examples, and avoid running arbitrary untrusted Roblox code outside isolated Studio sessions.

### General game-playing intelligence
- [GameWorld and GameWorld-RT (2026)](https://gameworld-project.github.io/) evaluate outcomes using serialized state (score, health, checkpoints, etc.) rather than screenshots or an LLM judge. Importantly, GameWorld-RT does **not pause the game during agent inference**: gameplay policies must meet real action deadlines. Do not compare realtime and paused success rates as though they were identical benchmarks.
- **Proposal:** Split inference into a rapid perception/control policy (bounded action deadline), a tactical planner (seconds), and an offline learning/replay worker (minutes). Record action, state digest, event time, observation provenance and verified outcome; limit observations under GPU pressure and never accept screenshots alone as proof of objective completion. Evaluate held-out levels, unfamiliar hazards, recovery after wrong actions, and the percentage of required actions delivered before deadlines.

### Streaming and speech naturalness
- [Microsoft Proact-VL (ICML 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) separates *when to speak* from *what to say*, evaluating solo commentary, co-commentary and guidance. A good VTuber must be able to stay silent, not just produce more text.
- [NVIDIA PersonaPlex (January 15, 2026)](https://research.nvidia.com/labs/adlr/personaplex/) explores configurable full-duplex conversational speech, backchannels and interruptions. It is a comparatively large model and should **not** be assumed deployable alongside gaming on an 8-GB GPU.
- [NVIDIA DyaPlex](https://research.nvidia.com/labs/amri/projects/DyaPlex/) investigates causally coordinated streaming speech and motion; this is research inspiration, not a tested local deployment.
- [Kyutai Pocket TTS (January 13, 2026)](https://kyutai.org/blog/2026-01-13-pocket-tts/) describes a 100M-parameter CPU-capable text-to-speech option. Trial it against existing local TTS under simultaneous game/OBS load rather than assuming it is faster or more natural on Star's specific CPU.
- **Proposal:** Give Star a stable, explicitly AI identity/personality; memory sourced from *verified* game/chat experiences; appropriate laughter, timing, topic return and acknowledgement; calibrated uncertainty; limits on repetition; and expressive avatar/voice synchrony. Make viewers aware she is AI, and use minimum necessary chat retention with deletion controls. Genuine human consciousness or emotions are not technically established by these features.

### Throughput / resource scheduling
- Use pinned model/runtime/quantization/hardware profiles; compare *end-to-end* speech or game-action p50/p95/p99 and correctness at equal workloads, not tokens/sec in isolation.
- Measure first-audio latency, interruption cut-off, AV sync, speaker verification, dropped frames, gameplay 1% low FPS, GPU memory headroom, OBS render/encode lag, thermal throttling and inference queue wait.
- Test prompt caching, batching and speculative decoding one at a time. Draft models can consume valuable VRAM and lower overall stream FPS, even when token throughput rises.
- Escalate complex tasks to larger models with explicit budget gates; cache verified reusable skills/documents; use fast workers only when their paired sealed holdout cohort demonstrates no regressions on critical cases.
- Keep background self-play, drawing, retraining and repo analysis deferred while games or OBS recording are active. CPU vs GPU task placement must be selected by measurements, not fixed model-size heuristics.

## 3. Priority implementation sequence (not claimed complete)

1. **Evidence provenance:** Generate `eval_cohort_sha256` in the trusted evaluator, atomically persist associated input manifest and artifact hashes, and sign a compact receipt with an owner-controlled key. Enforce nonce uniqueness and stop reuse across model/suite/host revisions. Add negative tests for spliced, future-dated, duplicate and forged receipts.
2. **Private 30-minute Windows rehearsal:** Run a *local, non-broadcast* game + avatar + TTS + OBS recording with read-only measurement. Gate startup on user-approved game/app, owner authorization, host identity, active resource envelope and correct recording destination. Capture gameplay objective state, speech waveforms, avatar gestures and OBS progress at independently timestamped boundaries. If game frame rate, VRAM or OBS health goes critical, reduce AI work before any unsafe input is issued.
3. **Measured speech A/B:** Compare existing TTS against CPU Pocket TTS using the same permitted voice content. Require audible confirmation and avatar lip-sync, test interruptions and silence. Do not substitute subtitle text for sound.
4. **Game learning curriculum:** Use 20+ procedurally varied practice maps with independent state-based tests, train/practice on development seeds, evaluate on sealed unseen seeds. Report success, deadline misses, retries and resource cost; persist only independently verified lessons.
5. **Studio quality loop:** Apply OpenGameEval-style inspect-before-edit, script validation, saved-place snapshots, controlled playtest, state assertions and reversible repair. Run test tasks without publishing the game to the public platform.
6. **Longer-term grounded social personality:** Couple conversation state to witnessed events and consented viewer context. Use proactive speech budget, explicit privacy limits, topic memory, safe social rules, true interruption support and expressive motion. Measure interactions with human review, not a self-rated "humanness" score.

## 4. Acceptance criteria for claiming a real improvement

- **Intelligence:** statistically credible increase in unseen success rate / verified objective completion over the deployed baseline, no critical-case regressions, same evaluation cohort, same action deadlines.
- **Speed:** lower p95 action-to-effect or question-to-audible-word delay at equal quality, **without** worsening game 1%-low FPS, OBS health or GPU pressure.
- **Streaming:** at least 30 minutes recorded locally with usable audio, synchronized avatar, correct response to interruption and independent OBS/progress traces.
- **Knowledge:** grounded answers with cited retrieval or executed tests and reproducible corrections; report uncertainty rather than inventing confidence.
- **Governance:** private pilots are OFF by default; no silent model deployment, broadcasting, spending, public messages or irreversible project changes.

## 5. Measurement and limitations

The new cohort binding is covered by offline deterministic unit tests. It does not make evaluator assertions tamper-proof, install new models, improve neural weights, increase measured tokens/sec or establish game mastery. Host-signed manifests, a genuinely sealed independent benchmark and a real private multi-app rehearsal remain necessary before promotion.

**Research retrieval date:** November 5, 2026. Links represent papers, project docs and announcements available by this date; future API/model versions require re-verification.
