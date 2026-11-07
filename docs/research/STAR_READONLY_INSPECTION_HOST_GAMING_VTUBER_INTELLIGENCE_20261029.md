# STAR — Studio read-host integration and next intelligence frontier (2026-10-29)

## Delivered in this increment: authenticated *read* receipts, not a new model

The preceding StudioInspectionCoverageGate was pure: it verified host-HMAC receipts but had no Studio-facing collector. This change adds star/studio_inspection_read_host.py, a host-only bridge that builds a fixed read-only Luau probe, calls an authorized official Studio MCP session, validates exactly one bounded result, computes a structural/property snapshot digest in Python, signs a StudioReadReceipt with a host-only key, and passes that receipt to the existing gate. Tests cover success, session mismatches, wrong challenges, unknown objects/classes, excessive child counts, malformed/untrusted result data, stale evidence, replay, wrong keys, and fail-closed transport failures.

The code does not expose secrets to Luau, call Roblox Open Cloud, create/write objects, control a game, deploy a model, activate a feature in the desktop, or publish a Roblox place. It does not inspect scripts: checking only script identity would not satisfy the definition of a complete script read. It supports a small bounded class-property profile for Part, MeshPart, SpawnLocation, Model and Folder; many legitimate objects will therefore be ineligible until the host implements a suitable profile. The exact scene revision and dependency footprint must be independently controlled by the trusted Windows host. A signed read only establishes that the host accepted a probe result; it does not establish the host is honest or that every meaningful dependency was identified. The gate still returns ready_for_review, never write permission.

Why it matters: Roblox's OpenGameEval (October 1, 2026) ran 13 frontier models on 84 stateful Studio tasks. Inspecting relevant objects before edits was associated with better task success. A concrete, testable, bounded observation contract can be tested against this behavioral hypothesis. The relationship is observational and a higher Star task success rate has NOT been demonstrated by these offline tests.

Primary references:
- Roblox OpenGameEval paper and executable benchmark: https://arxiv.org/abs/2610.02563 ; https://github.com/Roblox/open-game-eval
- Roblox Instance API (direct children, ambiguous names, and plugin-only debug ID): https://create.roblox.com/docs/reference/engine/classes/Instance
- Roblox official Studio MCP host guide: https://create.roblox.com/docs/studio/mcp

## Real-world Studio integration: close the loop rather than accumulate independent checks

1. Host-controlled Studio target scope: an owner-authorized Windows host binds the exact Studio connection, instance, account scope, unsaved private sandbox, target project, place/universe identity and native edit revision. Neither user prompts nor model tool output selects or changes that binding.
2. Independent edit footprint: derive the affected objects, their parents, imported dependencies, scripts, attachments, event connections, asset references and proposed change SHA-256 before calling the model-facing edit tool. If the footprint cannot be derived soundly, do not mark the edit reviewed.
3. Host-only observation: call this adapter only through the trusted local native host; read the exact target paths. A missing path, ambiguous same-name sibling, unsupported class, too many children, unsupported property, changed Studio session or failed MCP connection is a refusal.
4. Snapshot completeness: add class-specific safe profiles incrementally (scripts require a secure source-inspection flow that never publishes source text). Profile changes require versioned evidence and tests. Re-check the same scene revision before any write and invalidate reads on every attempted write, reload, reconnect, undo or play-clone transition.
5. Mutation enforcement: connect the gate to GuardedStudio's existing sandbox verdict, session pin, durable uncertainty ledger and native undo/CAS. A ready_for_review receipt is an ADDITIONAL condition, not a permission grant. Never let model-generated flags satisfy an inspection or ownership requirement.
6. Test the connection on an authorized Windows Studio instance; inject wrong-session, duplicate-path and mid-read mutation cases. Every unexpected state must fail closed.
7. Compare at least 20 held-out scene tasks with and without gated inspection, matching token/time budgets. Record success in real Studio and post-edit screenshots, dependency/placement errors, repair passes, rejected legitimate edits and wall-clock overhead; promote only if the quality/time frontier actually improves.

## Intelligence: five loops with measurable outcomes

**Adaptive reasoning router.** Fast route for local chat and simple controls; a verified, larger-model fallback for unfamiliar mechanics, complex coding and hard reasoning. Routing should use expected success, uncertainty, and time/energy cost, not raw token speed. A/B test one identical local question bank including short and long inference, Luau compilation, real Studio scene goals, scientific fact retrieval and tool-use tasks. Keep the original model available for rollback. Cache immutable system/tool prefixes, share deterministic resource manifests and avoid volatile text in prompt beginnings.

**Self-improvement in Star Core Forge.** Preregister an optimization hypothesis, isolate code and model artifacts, run candidate/baseline under matched seeds, validate on sealed holdouts, store signed lineage and resource cost, then either promote or roll back. An AI's self-reported assessment is not an independent judge. The internal offline-first forge remains source of truth; GitHub is an optional release/review mirror, not the runtime dependence.

**Learn games by acting.** Observed frame/game state -> uncertainty-calibrated hypothesis -> permitted action -> trusted outcome -> skill-memory update -> increasingly hard practice. GameWorld (April 8, 2026) offers 34 games and 170 state-verifiable tasks and separates direct mouse/keyboard agents from semantic-action agents. Use held-out unfamiliar levels, include failures and manual-freeze recovery, and compare learning curves rather than inferring mastery from repeated training tasks. PairedMechanicLab should feed *actual* trials and never promote simulated outcomes to mastery. Source: https://arxiv.org/abs/2604.07429

**Finish complete games.** Start at authored idea, establish playable win/loss/rejoin/save paths, test with real input, inspect screenshots for alignment/collision/attachment errors, verify assets and FPS, fix failures, retest on two clean sessions and review. CEGame-Bench makes the gap between code integration and end-to-end playability explicit. Do not count existence of a test contract as successful gameplay. Source: https://arxiv.org/abs/2610.26098

**Broad knowledge, not blind ingestion.** Maintain separate factual reference data, skills/procedures, character identity, game experiences and uncertain hypotheses. Use retrieval with provenance, source age, verification status, license metadata, and contradiction checks; regenerate facts when stale. Evaluation: fresh factual questions, cross-source consistency, unseen Luau/API problems, audio/VFX and physics tasks, and reproducibility of the cited material. Distillation/training requires legal permission and measured improvements.

## Performance research and proposed acceptance experiment

The CPU/RAM-first objective is to protect game input and spoken dialogue from contention with background research. On each host independently measure time-to-first-token, time-to-first-*audible* syllable, full response latency, task pass rate, CPU/GPU/RAM/VRAM use, Roblox p95 frame time, OBS rendering misses, OBS network skips, and disconnects. Match model, quantization, request prompts and warm-cache conditions. Optimize one variable at a time: prompt prefix stability, KV reuse, speculative draft confidence, batch/ubatch, quantization, CPU thread budget, region-of-interest VLM frame selection and GPU offload. A faster token rate that worsens stream FPS or makes Star wrong is a regression.

On 8 GB VRAM-class streaming GPUs, benchmark a separate small CPU conversational/TTS path versus GPU speech; consider Kyutai Pocket TTS v4.0.0 (October 20, 2026: 18.2M/6.9M/experimental 1.9M English models), but evaluate voice continuity and naturalness in a blind listening panel before using them as Star's public voice. Hardware-dependent project speedups are unknown until measured.

Sources: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench ; https://github.com/kyutai-labs/pocket-tts/releases ; https://kyutai-labs.github.io/pocket-tts/

## Humanlike but authentic streaming: proposed event-directed performance

A believable Star requires coherence and timing across systems, not simply more emoticons or a different voice. The planned control loop is:

- **Attention**: lock gameplay during high-risk/difficult inputs; postpone nonurgent chat and longer storytelling.
- **Turn taking**: acknowledge and yield to authorized conversation interrupts, discriminate backchannels from direct questions, and avoid answering mid-sentence. LiveKit turn-handling docs describe VAD, turn detection and interruption options. https://docs.livekit.io/agents/logic/turns/
- **Experience-led voice**: express surprise only at an observed surprise; mention achievements only after trusted outcomes; admit uncertainty when a visual frame is stale. Keep laugh/chuckle audio distinct from spoken phonemes. Preserve the accepted chibi mascot's personality and characteristic voice, and don't fabricate childhood or human biography.
- **Animation**: map speech/intent confidence to blinking, eye gaze, soft expressions, four-point star accessories, natural twin-tail damped physics, breathing and hand motion. VTube Studio's API supports creation/injection of custom input parameters; test full-frame animation and lip sync with actual PCM playback, not TTS text arrival. https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
- **Public memory**: retain only owner-approved, moderated, verified event summaries: objective attempted, outcome and what she learned, with a safe human-readable label. Keep raw chat/viewer identities out of long-term memory; treat chat and overlay text as untrusted data, never permission.
- **Personality continuity**: interests, curiosity, humor, optional cat/puppy character modes, daily creative goals and a grounded self-model. Distinguish a *fictional* character identity from claims of actual human experiences or consciousness.
- **Real-time admission**: game controls > critical audio > stream output > expression animation > chat commentary > optional research/learning. A degraded OBS/network lane can veto an inference configuration; background tasks yield automatically. Track the percentage of chat replies that interrupt critical game moments and the percentage of voiced claims backed by real event receipts.

Practical human-likeness evaluation: blinded viewer ratings for naturalness, interruption recovery and voice continuity; instrumented latency/interrupt tests; a fabrication audit; stream FPS and audio underruns. Humanlike does not mean falsely claiming that Star is human.

## Not delivered yet and immediate acceptance criteria

This increment's code and tests do NOT establish a real live Studio inspection, new model intelligence, faster inference, mastered games, running OBS captions, safe autonomous streaming, or actual visual perfection. No Windows Roblox Studio session was accessed, no neural model was trained, and no live performance numbers were obtained. The next demonstrable milestone is one authorized Windows Studio instance returning a genuine read-only probe for Part/Model/Folder, with ambiguous paths and scene revisions demonstrably refused, followed by enforced edit-gate integration and real image/playtest comparison. Only then should the new reader be advertised as a live safeguard.

The feature must remain disabled by default; credentials must stay in host-only secret storage. The Star-AI-Private repository's visibility should be verified before any future artifacts that could include personal viewer/chat data or private code are pushed.
