# STAR AI: evidence-guided game skill and truthful VTuber continuity

**Research and offline implementation — October 25, 2026.** This is an engineering proposal plus two tested *pure-Python advisors*. It is **not** an autonomous game player, a new foundation model, a consciousness claim, a voice synthesizer, an OBS connection, or a demonstrated model-speedup. No device input or broadcast occurs.

## Goal and evidence gap

STAR already has `star/playtest_learning.py`, `star/selfplay_curriculum.py`, `star/player_twins`, the model routing/evaluation code, and multiple unmerged streamer drafts (#579, #580, #581, #585, #586, #593). The missing seam is a cheap, bounded intermediate memory connecting *scored game experiences* to *conservative next-action advice* and *truthful stream callbacks*. It must not mistake an LLM's description of gameplay for an independent result. Such a seam can be prototyped without creating another input adapter or competing with pending stream directors.

Two opt-in building blocks were added:

1. `star/game_skill_memory.py`: independent-session action evidence per **game + state + action**, a one-sided conservative Wilson lower bound, a strict veto for any observed unsafe attempt, least-tried experiments in an **explicitly approved sandbox**, no advice when the lower bound has insufficient support, and a small fixed-capacity ledger. Its only output is an advisory action ID. It never executes game inputs. Multiple episodes in one session **do not multiply the number of independent trials**; if any attempt failed, that session is scored failed. This conservative rule limits high-confidence illusions due to retry loops, but is not a guarantee of independence across matches, players or seeds.
2. `star/stream_moment_memory.py`: bounded, sequential, checksummed references to host-observed discoveries, losses, recoveries and surprises. It can produce a comeback cue linking a real setback and recovery **only when the topic/session match**, under a speaking cooldown. It produces an instruction for the separate speech planner to consider; it never plays a sound. The first-person persona may have **fictional in-world lore, clearly distinguished from actual lived experience**. Do not invent real-life childhoods, relationships or human experiences.

A SHA-256 digest identifies evidence bytes but is **not authentication**: any caller can fabricate a digest. The host application's privileged adapter and game-specific independent evaluator must establish provenance. In particular, `trusted_host=True` / `trusted_game_adapter=True` are **in-process developer APIs, not authorization or security boundaries**. Do not expose them as AI-callable tools. Put a real trust boundary outside the model and chat layers and persist actual evidence separately if needed.

## Research-backed architecture

### A. Game intelligence that can actually improve with experience

- **Observe:** a consented, permitted game telemetry adapter turns on-screen/engine events into normalized state tags. Screenshots alone are ambiguous; Roblox Studio's built-in MCP and StudioTestService plus VirtualInput allow structured, bounded tests in an owner's unpublished place. Keep action legality/game ToS constraints in the adapter, not in the language model.
- **Understand:** separate what was *seen*, *inferred*, and *experimentally verified*. Record an observation only after the host's win-condition evaluator has returned an outcome. Failed pathfinding, missing UI buttons, death loops and jump timings can each become evidence for that exact task state.
- **Plan:** let a reasoner propose possible behaviors; the cheap evidence layer accepts only a host-allowlisted set of actions. In a test sandbox it can ask to try an under-explored option; during an actual live performance it abstains unless enough independent safe episodes exist. A high-level goal must not map directly to arbitrary OS keyboard/mouse actions.
- **Act:** a separately permissioned controller, not the memory code, performs short bounded action batches; monitor frame input freshness and always provide operator stop. Prefer private game servers and owner-owned test places. Do not bypass game anti-cheat or competitive fairness mechanisms.
- **Score:** record successes, failures, side effects, clearances and real latency by session. Evaluate new behavior on sealed independent games/levels/seeds before calling it a gain. Report uncertainty and failure cases, not just a cherry-picked successful demo.
- **Consolidate:** store *verified reusable skills* in a local library; if fine-tuning is ever considered, use a licensed dataset and an independent holdout. Never claim a change to model weights when only the surrounding policy changes.

SIMA 2 (Google DeepMind, Nov 13, 2025) is evidence that embodied generalists can combine vision, reasoning and transferable actions across games; it is a research preview rather than a deployable STAR component. Voyager (Wang et al., 2023) demonstrates curricula, composable skills and environment-based correction. DreamerV3 (Hafner et al., Nature 2025) provides evidence for learned world models and experience-based simulated rollouts. These are **distinct methods**; this PR implements none of their architectures, only a small measurable component they motivate.

### B. Humanlike streaming is a realtime systems problem

A compelling virtual character must be a coherent **AI character**: context-aware, playful, quick to recover, capable of quiet concentration, expressive and able to remember actual earlier events. It should not claim to be biologically human, conscious, or to have a real unobserved biography. High-value capabilities:

- *Turn-taking:* speech activity detection + barge-in + interruption-safe cancellation. Integrate with the pending `PlaybackGate` work in draft #593 and/or LiveKit event handling only after a contract review; cancel old lipsync/captions too.
- *Emotion and animation:* synchronize speech prosody, mouth shapes, gaze shifts, brows, ears/tail and hair secondary motion with the **same** generation/turn ID; use a reduced-motion option and avoid constant fidget loops. The pending #581 avatar motion planner is another isolated part of that work.
- *Situated callbacks:* cite two observed events for a comeback, use conversational variation and pauses, avoid narrating every game tick, allow owner interruption. The current module delivers bounded cue metadata only; actual script generation and TTS need separate controls.
- *Live chat:* a moderated retrieval stage chooses recent messages, guards against chat-based instruction hijacking and hides identifying viewer data from lasting memories. This PR stores **no chat content** and grants no broadcast rights.
- *Gameplay quality:* avoid asking a huge reasoning model at every frame. Event gates and cached short skill choices handle routine frames. The larger model receives compact summaries on decision points or novel states. Route expensive research and training off the streaming/gaming device.

NVIDIA PersonaPlex (Jan 15, 2026) supports full-duplex speech/role conditioning, and NVIDIA DyaPlex (June 2026) studies synchronized streaming speech and body motion. Both require significant integration/review; neither is silently installed. LiveKit Agents documents turn detection, interruption handling and separate speech/audio processing; the hosted product and free software should be distinguished in budgets.

### C. STAR speed and infrastructure — experiments to prioritize

1. **Quantify first:** frame time p50/p95/1% lows, event-observation age, time to first audible response, p95 speech tail, GPU/CPU/RAM/VRAM residency, first-token delay, prompt tokens/sec and decode tokens/sec. Record warm/cold separately.
2. **Split Brain 1 and Brain 2 explicitly:** Brain 2 protects active game/Roblox Studio, OBS, avatar and latency-sensitive audio. Brain 1 handles text reasoning, offline evaluation, knowledge indexing and overnight skill rehearsal when connected. Respect actual network latency, security and peak RAM; do not claim free GPU memory.
3. **Enable measured prefix reuse where the serving runtime really supports it.** The prefill-only benefit documented by vLLM matters on repeated stable prompts, but does not speed decoder token generation and gives little value for low-prefix-sharing requests. STAR already has `star/context_layout.py` and `star/cache_banks.py`; benchmark those before another cache layer.
4. **Small fast policy between frames, powerful model between milestones:** lightweight deterministic state-action lookup can run in microseconds locally when the state is known. It does *not* improve the base model's IQ or invent new skills. New states or tricky decisions still need the base model or a verified skill search.
5. **Latency-aware and interruption-aware services:** bounded event queues with deadlines, isolate expensive work from input/voice threads, explicit cancellation tokens, stale-frame replacement; integrate with #593 after review rather than start another competing runtime service.
6. **Quality gates:** offline unit and schema checks first; then real Windows + Linux packaging tests, Studio test harness against unpublished games, cross-PC LAN inference benchmarks, owner-reviewed streams and protected holdout game levels. A synthetic unit-test pass must never be reported as live-game proficiency.

### D. General knowledge beyond games

For non-game questions, use source-labeled retrieval with source dates and rights, attribution, conflict handling, abstention on insufficient evidence, independent answer verification and a per-domain evaluation suite. Autonomy should be measured as repeatable success under limited human interventions, not a claim to consciousness or unlimited general intelligence. Avoid training on copyrighted videos, fan art or game captures without permission. Let STAR research and form hypotheses, but require a separate verification process before accepting them as durable knowledge. Existing `star/knowledge_checks.py`, `star/general_knowledge_benchmark.py`, `star/eval_stats.py` and `star/learning.py` provide places to integrate rather than fork.

## Operational integration contract

The trusted host (not a model instruction) creates `Episode(game,session,seq,state,action,success,unsafe,elapsed_ms,evidence_sha256)` from its own scored playtests, then calls `record(..., trusted_host=True)`. `advise(game,state,tuple_of_whitelisted_action_ids,mode="play")` returns `action=None` on weak evidence. Sandbox experiment proposals require both `mode="practice"` and `sandbox_approved=True`. Host-approved controls still need their *own* per-game authorization; these flags are not permissions.

For streaming, the host creates `GameMoment(session,event_id,seq,kind,topic,occurred_ms,evidence_sha256)`, calls `observe(..., trusted_game_adapter=True)`, then may request `next_cue(..., audience_can_hear=True)` when the host has decided speech is possible. `VoiceCue` is a short prompt brief plus evidence IDs; the broadcaster must separately check the active session, moderation, copyright, output generation ID and user stop before each chunk. The cue does **not** indicate a real voice or game observation was made by this implementation.

Memory is **in-process only** and intentionally bounded (default 256 game sessions/4096 episodes; 16 stream sessions/256 moments). The host must rotate the ledger rather than silently drop replay protection, with an explicit lifecycle policy. No data persists to disk, no network requests or game inputs are made by these modules. The checksum and trusted flags are caller declarations and not cryptographic provenance. Do not serialize PII in the IDs.

## Verification completed for these additions

- Local isolated Python `unittest` suites for bad input, gating, independent-session counting, unsafe veto, replay/out-of-order, strict game scope, speech cooldown, truthful comeback callbacks, time expiry, capacity and non-execution.
- `python3 -m unittest discover -s tests -p 'test_*memory.py' -v`: **46 tests passed** on an isolated Linux Python environment (not whole-repo CI or native Windows testing).
- No speedup percentage, base model improvement, model training, game capture or live streaming is claimed. Actual performance and gameplay competence are unmeasured until adapter integration.

## Primary sources (consulted October 25, 2026)

- Google DeepMind, SIMA 2 (Nov 2025): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Wang et al., Voyager, arXiv 2305.16291 (2023): https://arxiv.org/abs/2305.16291
- Hafner et al., DreamerV3, *Nature* (Apr 2025): https://www.nature.com/articles/s41586-025-08744-2
- Roblox, Studio built-in MCP / playtest automation (Mar 2026): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox, studio testing modes (including StudioTestService / VirtualInput): https://create.roblox.com/docs/studio/testing-modes
- NVIDIA, PersonaPlex (Jan 2026): https://research.nvidia.com/labs/adlr/personaplex/
- NVIDIA, DyaPlex (June 2026): https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- LiveKit, agent speech and interruptions: https://docs.livekit.io/agents/multimodality/audio/
- vLLM, automatic prefix caching limitations: https://docs.vllm.ai/en/v0.13.0/features/automatic_prefix_caching/

## Follow-up acceptance experiments

- In a private Roblox Studio test place, run a locked battery of >= 30 seeded layouts against the current robot and the evidence-guided advisor, each seed counterbalanced across arms. Compare independent **win rate, deaths, collisions, avg/p95 time-to-goal, and action reversals** with a preregistered scoring procedure.
- In an owner-approved offline stream rehearsal, replay 30 minutes of rights-cleared game events and compare **truthful callbacks, repeated lines, owner interruption age, time-to-audio, dead-air, and hallucinated off-game biography**. Never live-broadcast automatically.
- Benchmark the advisor on the actual target PCs with P50/P95 overhead and unchanged game-frame rate under sustained voice + game rendering. These proposals are not completed benchmarks.
- Combine this work with pending #580/#581/#593 after contract and privacy review; require full CI, green status, a human-approved merge, and a canary rollout. No automatic merge or publish.
