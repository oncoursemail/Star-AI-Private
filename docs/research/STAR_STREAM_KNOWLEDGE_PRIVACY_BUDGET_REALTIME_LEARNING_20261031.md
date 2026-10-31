# STAR AI — Stream knowledge confidentiality, retrieval quality, and real-time intelligence

Date: 2026-10-31. Scope: deterministic, offline Python change and verified engineering research on the draft PR #845 branch. No game input, audio capture, new model, OBS output, or deployment.

## Directly inspected code and identified reliability gaps

Star already has project-scoped `KnowledgeStore`, reviewed-only retrieval, and owner-selected public note IDs in `public_knowledge_packet`. A streaming model receives these notes at USER priority, not as system commands. In addition to source content, each note has an internal revision field. Prior behavior put the first 48 characters of that revision directly into the broadcastable language-model context. Revisions were *not* separately approved for public disclosure and may contain private branch names, ticket references or opaque tokens. This violates the existing code's policy of hashing source labels before exposure.

The packet builder also allocated an *estimated* 230-character reserve for framing, stopped entirely after encountering one oversized ranked note, and therefore could fail to return a later, shorter, explicitly approved fact. Increasing the model size would not fix either bug.

### Change implemented here

- Omit the unreviewed-for-broadcast `revision` metadata entirely. The owner-approved factual text, bounded note ID, kind, age and a 16-character SHA-256 source label remain. A source digest is **not** proof that a source is reliable.
- Measure the length of the **complete serialized packet** including instructions and end delimiter before accepting a candidate. Reject only that oversized candidate and keep scanning ranked approved notes, up to the configured limit.
- Preserve explicit per-call public note approval, project scope, reviewed-only retrieval, age limits, 1,400-character maximum, and no network access. No change to general-model weights.
- New offline regression cases use a synthetic secret-like revision and a long unicode fact (which expands under JSON encoding) followed by a smaller approved fact. These test confidentiality and continued retrieval, not model intelligence.

## Research-to-architecture recommendations

### 1. Make Star better at answering, not merely faster at talking

Keep separate indexes for (a) verified durable knowledge, (b) rapidly aging current facts, (c) unverified hypotheses, (d) host-approved stream facts, (e) signed gameplay outcomes, and (f) fictional Star persona lore. A retrieved passage is evidence, not permission to run a tool. Answer with source and applicable date, or abstain when verification is missing. Include false-answer rate and correction latency in the scorecard, not just answer quantity.

Use an offline task bank across unfamiliar science, coding, mathematics, game mechanics, design, UI, history, audio, and visual reasoning. Hold out prompts and source documents from the retrieval development set. Report accuracy, groundedness, calibration, abstention, source aging, p50/p95 latency, RAM/VRAM and token usage together. Treat model self-grades only as proposals; independent executable tests and human comparison are the acceptance gates.

### 2. Gaming intelligence needs two distinct speeds

Pan et al., *The World Won't Wait* (published 2026-10-14), evaluate real-clock game environments and show an offline teacher improving the smaller live student's instructions on their tasks: https://arxiv.org/abs/2610.20665 . This is **not** evidence that Star's gameplay has improved. Reuse Star's existing real-time action gate/freshness measurements and signed learning bank. The live student acts from a fresh scene and bounded known move list, while the teacher studies verified failures off-stream. No expensive teacher inference in the frame-sensitive action loop. A proposed skill update is promoted only after preregistered unseen real-clock trials show gains without newly failed objectives, per-map regression or p95 action-delay regression.

### 3. Roblox game creation must have executable acceptance

Roblox added StudioTestService and StudioDeviceSimulatorService and supports scripted client/server tests, including up to eight clients: https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854 and https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers . A premium-quality STAR build should verify Luau execution, UI clipping across device profiles, physics/prop anchoring, texture seams, lighting and animation, and independently observed multiplayer functionality. Require screenshots and geometry/visual comparisons alongside tests. Do not confuse successful code generation with a playable, polished result.

### 4. Natural VTuber behavior comes from coherence across subsystems

For Star's OLED-black-and-gold original persona, build a local, consented rehearsal that observes real game state, chooses when to **stay silent**, uses episode memories only if host verified and broadcast-approved, emits short grounded reactions, then aligns PCM playback with expressive gaze, blinks, eyes, twin-tail secondary physics and appropriate body motion. Do not overreact to a suspected victory or fabricate an off-camera life.

A realistic streaming gate should measure interruption-to-actual-speaker-silence, frame time, game objective success, speech naturalness from blinded listeners, words actually audible in OBS loopback, lip-sync alignment, duplicate utterances and lost/queued audio. OBS's official documentation calls for authenticated websocket access: https://obsproject.com/kb/remote-control-guide . Use localhost and an authorized host adapter; never expose live stream controls directly to untrusted chat or model-generated text.

### 5. Speed is a multi-objective constraint

Star's gaming GPU has only 8 GB VRAM in the planned configuration. Benchmark a warm small live model, conditional stronger reasoning off-stream, stable-prefix caching *only after isolation tests*, quantization choices, CPU/VPU placement, frame-diff perception, bounded TTS chunks and streamed outputs. Optimize for p95 time-to-useful-action and p99 game frame time with low audio drop rate, **not** idle tokens/sec alone. Do not rewrite Python orchestration in Rust until a profiler shows a measured hotspot. When justified, port the narrow capture/copy/codec hot path and require equivalent output tests and rollback support.

Use Star Core Forge as the local gatekeeper for strategy/code experiments: source snapshots, deterministic tasks, paired seeds, holdout evaluation, performance constraints and rollback. GitHub remains a review/export surface, not a prerequisite for autonomous local improvement.

## Acceptance status

This revision changes the **accuracy of public-knowledge packet selection** and **reduces accidental exposure of revision metadata**. It does not increase the underlying language model's intelligence, prove any real-world speedup, deploy a voice, or connect an active game or OBS host. The new tests are offline and CI must be checked on the resulting commit. The repository currently reports public visibility despite its `Private` name; never commit credentials, recordings, or private stories.
