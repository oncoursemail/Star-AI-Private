# STAR — pre-edit inspection coverage, game intelligence and VTuber research (2026-10-29)

## Delivered in this increment

`star/studio_inspection_coverage.py` adds a **pure, opt-in, host-attested pre-edit inspection review** for Roblox Studio. An owner-authorized host registers the exact proposed edit digest, bounded target objects, and read-dependencies, then supplies HMAC-signed observations for **every** path from one session and scene revision. Stale, missing, ambiguous, partial, forged, duplicate and wrong-revision reads cannot qualify. New edit plans, Studio mutations, reconnects and clock resets invalidate previous reads. This library returns **ready_for_review**, never write authorization.

This matters because Roblox's October 1, 2026 OpenGameEval benchmark found that scene/script exploration correlates with successful edits, including a +13.4 percentage-point association for comprehensive object inspection on scene-only tasks. Association is **not** proof of causation. The implementation moves from a vague "look first" suggestion to a testable coverage contract.

**Primary source:** https://arxiv.org/abs/2610.02563 ; executable benchmark: https://github.com/Roblox/open-game-eval

### Required Windows host integration (not implemented here)

1. An owner-approved private Studio test starts with a stable, host-owned scene revision.
2. The host obtains the proposed edit footprint independently of model claims, including relevant scripts, parents, references and dependencies. If the footprint is unknowable/incomplete, return ineligible.
3. A trusted Studio plugin enumerates each path by *direct children*, rejects ambiguous same-name siblings, records class/properties/script hash, marks reads complete only after checking every selected property, and returns read results. Do **not** expose private script source to the model as telemetry.
4. A distinct local host validates the Studio session/revision, computes a canonical SHA-256 observation digest, and HMAC-signs the receipt using a host-only key. The game and model never receive the HMAC key.
5. The host evaluates all receipt coverage immediately before an edit and **separately** enforces the existing mutation ledger, user-scoped Studio authorization, native undo recording and post-edit playtesting. Any revision change must call `invalidate_revision`.
6. Measure improvement against a holdout task set: edit success at fixed cost, missing dependencies, latency overhead and inspection false positives. Compare with an otherwise identical no-gate baseline; no quality gain has yet been measured.

**Limits:** Host signatures identify the signer, not truth; a bad or compromised host can attest incorrect completeness. The library cannot discover unlisted dependencies, detect plugin errors, resolve same-name siblings, or protect writes unless the mutating host wires it in. No Roblox Studio was opened and no game modified.

## Larger intelligence roadmap — prioritize demonstrated gains, not AI claims

**1. Game creation.** Use OpenGameEval's reproducible stateful tasks for discovery, edit, and verification. After inspection, require geometry/material/attachment checks, independent rendered screenshots, genuine input, win condition, rejoin and save recovery. CEGame-Bench (October 19, 2026) found game endings occurred in 16% of evaluated agent runs despite high integration scores, underlining the importance of complete-game tests. Source: https://arxiv.org/abs/2610.26098

**2. Learn games through experience.** In private permitted test worlds, observe UI/state, hypothesize rules, plan input, act, compare actual state with prediction, store a signed outcome, and practice harder unseen scenarios. Build on PairedMechanicLab's fixed-pair experiments and GameTransferAuditor's sealed holdouts. Keep game/level versions separate; never train on hidden evaluations or claim mastery from synthetic tests. GameWorld reports 34 games and 170 state-verifiable tasks, highlighting long-horizon/memory and latency limitations. Source: https://arxiv.org/abs/2604.07429

**3. Faster useful intelligence.** Make a per-task Pareto frontier (wall-clock first audible syllable, complete result latency, real Studio task success, energy, Roblox p95 frame time, OBS skipped frames). Compare a cheap model first vs a verified larger-model fallback; tune prompt caching, context-length budgeting, speculative decoding, VLM region-of-interest sampling and CPU threads with matched workloads. llama.cpp's SPEED-Bench supports speculative decoding/acceptance testing, but only end-to-end task-and-OBS measurements justify promotion. Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

**4. Natural gaming VTuber.** A single event timeline should coordinate attention, authenticated owner interruption, appropriately moderated chat, speech generation, actual audible PCM progress, Live2D pose, eye gaze and quiet focus. Use verified in-game reactions; deliberate silence is useful during difficult gameplay. VTube Studio supports model custom parameters and LiveKit has a local CPU `v1-mini` audio turn detector. Preserve Star's distinctive voice and animations after listening tests rather than adopting a smaller TTS purely for token speed. Source: https://github.com/DenchiSoft/VTubeStudio ; https://docs.livekit.io/agents/logic/turns/turn-detector/

**5. Humanlike continuity without fabrication.** Maintain an explicit persona/character sheet, actual event-backed episodic memory, interest/hobby projects, uncertainty, conversational repair, natural laughter and choices. Stories about her actual game sessions are better than counterfeit human childhood memories. Stream-chat is untrusted, private viewer identifiers should not enter durable knowledge, and external actions need the existing owner-defined boundaries.

**6. Self-improvement in Star Core Forge.** Use preregistered hypotheses, immutable experiment receipts, reproducible isolated tests, ablations, holdout evaluation, resource budgets, human-readable diff/rollback. Github is an optional publication target; the internal forge owns the history and deployment gate.

## Acceptance criterion

One authorized Windows Studio session must demonstrate that a correctly inspected edit receives *ready_for_review*; deliberately uninspected/wrong-scene/ambiguous target cannot, and a post-mutation edit invalidates old evidence. Repeat with comparable tasks to quantify whether this gate increases actual completed, visually acceptable games. No verified real-world performance or streaming improvement is asserted by this increment.
