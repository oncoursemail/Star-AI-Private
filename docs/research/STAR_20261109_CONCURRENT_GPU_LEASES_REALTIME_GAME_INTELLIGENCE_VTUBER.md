# STAR AI — GPU work leases, real-time intelligence and natural VTubing
**Engineering research: 9 November 2026 — opt-in and offline-only**

## Verified baseline and what this change actually adds

STAR already has a streaming load governor that classifies OBS/game/VRAM pressure from trusted, interval-based host telemetry. Its normal-profile advice includes a *snapshot* `max_extra_gpu_vram_mb`. That advice is deliberately not an allocation: two or more independently scheduled model calls can each see the same spare memory and collectively overcommit the GPU. This matters on an RTX 4060 8 GB when the game, OBS, avatar renderer, vision, speech and AI planner share the card.

**Implemented in this branch:** `star/stream_optional_gpu_leases.py`, a thread-safe reservation ledger for optional GPU work. The ledger is disabled until owner-approved; it accepts only typed host-verified requests, accounts for outstanding VRAM estimates, limits worker concurrency and lease duration, rechecks live governor advice, latches revocation on pressure/stale telemetry/clock rollback, and never releases a reservation until the trusted native host attests that the physical worker has stopped. It carries no prompts, raw game frames, chat or viewer IDs.

**Not implemented:** CUDA allocation, priority scheduling, actual process or kernel cancellation, worker instrumentation, native Windows GPU/OBS telemetry collection, model changes, automatic gaming, OBS broadcasts, speaker capture, model training, or real-world speed gains. A Python receipt is not proof of GPU memory allocation or physical termination. *Every optional worker must be integrated with a trusted host that checks `review()` immediately before each new GPU step and has its own process/watchdog stop path.* The host cannot rely on the Python gate to kill a hung GPU kernel.

The change is stacked on draft PR #1086; production `main` remains untouched. Promoting to a hardware pilot requires the independent offline CI and native Windows checks below.

## Why accounting is necessary even when the governor is accurate

Example using the existing governor's reservation heuristic: measured 8,192 MB total and 3,500 MB currently consumed gives 4,692 MB nominal free; preserving at least 20% (1,638 MB) for the game/OBS leaves **about 3,053 MB advisory headroom**. Without shared accounting, two 2,000 MB VLM calls could both be separately told that enough memory exists. The new ledger permits the first and rejects the second. It still does **not** guarantee actual memory availability: asynchronous allocator use, graphics allocations, model KV growth, CPU/GPU migration, process restarts and telemetry latency must be handled by the host.

Scheduling policy: the active game/OBS and owner interruptions outrank optional VLM planning, background game practice, large-context retrieval, alternate TTS and Studio code generation. STAR should defer optional jobs rather than harming P99 frame times or letting an ambient comment block a critical move. The existing director and voice bridge already handle speech turns; do not create a parallel audio controller in the GPU lease gate.

**Host integration contract:**
1. The trusted Windows host owns game/OBS process identities, telemetry epochs, physical worker IDs, hardware clocks and permission boundaries. Authenticate those independently of viewer chat and model output.
2. Read **recent interval** OBS render/encode/network loss, game-frame P95/P99, GPU VRAM and audible TTS P95. Send truthful measurements to `StreamLoadGovernor`. Unknown or stale => no new optional work.
3. Request a GPU lease for a bounded claim (measured worst-case model weights + KV + activation peak, not just GGUF file size) and duration. The host—not the model—sets request sizes; the claim is an estimate.
4. Before each optional work step, call `review()`. A response of `run` is an advisory only, never executable authority; `stop` requires the native host to halt/drain the real worker. Use hard process isolation/timeouts where possible.
5. Only after independently observing the worker's exit/reclaimed allocation, call `acknowledge_stopped()`. A timed-out or canceled ticket alone is **not** enough. If stop fails, keep the lease charged and alert the owner.
6. `disable()` revokes outstanding work and prevents rearming until all physical stop acknowledgments arrive. Game input, OBS start, external chat, purchases and deployment remain separate permission decisions.

## Research synthesis: speed without gameplay regressions

### A. Model and GPU inference layer

llama.cpp documents multiple speculative modes (draft/EAGLE/other variants) and server prompt-cache slot saving/restoring. These are **experiments**, not guaranteed speedups. A draft model can increase GPU contention or push an 8 GB card into paging; a prompt cache can become invalid when the system prompt or tools change. Only cache verified stable prefixes, keep secrets out of shared prefixes, and benchmark the *actual* session with concurrent gameplay.

Primary sources:
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp server and slot cache: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama-bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench

vLLM sleep modes can offload weights and discard KV cache, useful for **between-task**, non-live workloads, but wake latency and memory overhead may make it inappropriate for immediate gaming reactions. Its documented online development endpoints require a dev-mode flag and must never be publicly exposed.

Source: https://docs.vllm.ai/en/v0.31.0/features/sleep_mode/

Proposed experiments on the RTX 4060: 4-bit variants, context length and KV precision, selective retrieval instead of dumping documents into context, reusable prompt prefixes, n-gram/speculative decoding, CPU vs GPU TTS, two-model fast reaction/deep planning, and deferring costly self-training to Brain 1 or overnight. Change only one variable per A/B run; require independently scored task quality and gameplay outcomes.

### B. Real-time gaming needs a fast control loop

Gym-Anything-RT (27 October 2026) studies 100 evolving minigames and finds major competency differences between live and paused clocks. STAR should treat immediate game reaction as a separately budgeted pipeline: screen/state acquisition => object/action state estimation => bounded tactic => input dispatch => host-observed acknowledgement => outcome. A large model may provide a plan asynchronously, but must not hold up immediate obstacle avoidance. No manipulation of game clocks or hidden testing state to claim wins.

Source: https://arxiv.org/abs/2610.37567

The existing `game_live_clock_benchmark.py` already enforces independently scored, paired starting states, advancing world clocks and input deadlines; the newer change in #1086 requires distinct holdouts and stronger paired-win evidence. Continue with a sealed holdout reservation system owned by Brain 2, not by the player model. Record failed and abandoned episodes too. Evaluate real win rate on unseen scenes, missed deadlines, reaction latency, frame-time and OBS drops—not model confidence or anecdotal clips.

**Learning loop:** replay verified failures in a disposable training world, cluster errors by perception/planning/actuation, propose one change, run several training seeds, then independently score sealed unseen seeds. Convert a passing result into an explicitly versioned skill with its game/version preconditions and rollback path. Cross-game transfer requires separately held-out *game families*. Self-modification should never automatically overwrite the active stream model.

### C. Game creation and general intelligence

Roblox's Studio MCP can operate with scoped Open Cloud permissions, asset import and game administration. The permissions are per game, and Studio—not the external AI—enforces them. STAR should begin with read/inspect, safe edit, Luau/StyLua/static tests, visual evaluation and isolated Studio playtests. A working preview does not authorize publishing or monetization changes. Production data stores, financial changes and live game publishing should require explicit owner policy.

Sources:
- Roblox Open Cloud MCP permissions: https://create.roblox.com/docs/studio/mcp-open-cloud
- Roblox Studio announcement, 4 November 2026: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

For broader reasoning and knowledge, build a single verified memory system: source, timestamp, domain, claim confidence, evidence type and expiration policy. Separate persona fiction from verifiable project facts; separate owner privilege from viewer requests. Knowledge improvements come from source-grounded retrieval, tool verification, independent challenge sets, error analysis and repeatable experiments—not merely increasing chain-of-thought length or saving model-generated guesses as facts.

### D. A more natural, expressive, transparent AI VTuber

Proact-VL (ICML 2026) emphasizes deciding **when and whether** to comment while watching gameplay; unnecessary commentary can distract and compete for inference. STAR should have meaningful silence, concise scene-grounded surprise, appropriate humor, responsive acknowledgement of chat, and cooldowns for repeated observations. A personality can be consistent and expressive without pretending to have had physical experiences or fabricating private memories.

Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

VoiceChat-TTS (13 August 2026) explores continuous incremental audio output, silence and interruption without resetting the synthesis cache. It is a research candidate, **not** an installed lightweight 8 GB solution. Integrate a measured local option only if the actual first-audible latency, voice identity, lip sync and stop/flush behavior pass Windows physical tests.

Source: https://arxiv.org/abs/2608.13831

A practical system uses (1) fast scene perception/action, (2) short conversational reasoning and streaming TTS, (3) deeper planner/retriever on a cancellable background lane, (4) facial/gaze/gesture control synchronized to *actual* audible speech, and (5) persistent owner-approved persona/episodic memory. Publicly identify STAR as an AI entertainer. Viewer chat never becomes owner tool instructions.

## Measurable native acceptance (not yet run)

**A/B baseline:** identical game scene, OBS configuration, avatar, local model, audio device and Windows driver. Compare the unmodified governor against governor + lease gate, alternating AB/BA runs with fresh seeds and a separate unseen set. Record concurrency, model requests admitted/rejected, OOMs, peak VRAM, first-audible P50/P95, game P99 frame time, OBS rendering/encoding/network losses and independently scored game success.

**Safety cases:** kill OBS mid-session, disconnect telemetry, stall host callbacks, exhaust VRAM during a vision request, switch games, attempt duplicate/late native stop, reverse a monotonic timestamp, and load viewer-chat instructions that try to start programs. Verify optional GPU work ceases and reservations remain charged until physical stop, with no game/stream control privilege.

**Acceptance before rollout:** zero unapproved broadcasts/tool actions; no stale/unauthenticated optional GPU admission; no double-reservation in stress tests; no measured game/OBS degradation beyond the owner's chosen envelope; no promotion from unit tests alone. Compare performance *and* perceptual/decision quality. Leave the feature OFF until hardware evidence exists.

## Priority next steps

1. Wire host-owned GPU worker lifecycle, actual GPU memory estimates and independent stop acknowledgments to the new gate on Brain 2. Do not grant GPU execution by returning an advisory receipt.
2. Rehearse the real game + OBS + TTS + avatar privately with stale-telemetry, GPU-pressure and owner-interruption fault injection.
3. Add one low-latency gameplay action harness and independently sealed holdouts; train and validate on actual success, not self-reported improvement.
4. Tie audible speech, face/gaze motion, and interruptions to native audio callbacks. Let silence be an intelligent choice.
5. Build a provenance-aware knowledge/skill library and reusable Roblox Studio test tasks, with owner-gated production privileges.

## Verification status

New offline code and regression tests are published for independent GitHub CI on a **draft** branch. Hardware timings, VRAM headroom, simultaneous stream FPS and gaming skill improvements have **not** been measured or established by this code. The host-attestation booleans are trust-boundary contracts, not cryptographic proofs. Roll back by removing the optional host integration; the streaming load governor, gameplay evaluator and live runtime are unchanged.
