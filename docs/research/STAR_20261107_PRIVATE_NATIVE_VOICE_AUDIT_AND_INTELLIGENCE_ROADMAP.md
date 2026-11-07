# Star AI — November 7, 2026: private native-voice evidence audit and generalist VTuber research

**Scope:** A real, testable bridge from native Windows process-specific audio activity JSONL to a *post-capture*, private Python audit, plus a prioritized engineering program for intelligence, low-latency streaming, game mastery, and autonomous game creation.

## Implemented in this change

`star/process_loopback_private_audit_cli.py` consumes the exact diagnostic schema validated by `star.process_loopback_activity.ProcessLoopbackActivityVerifier`. It requires an owner-enabled **stopped** capture, an approved absolute local directory, a prior *independent* SHA-256 commitment, explicit process/binary pinning declarations, and a declaration that broadcast is inactive. Its output contains only aggregate activity windows and hard-coded **negative** authorization fields.

- Reject missing/invalid end marker, truncated JSONL, malformed/duplicate/reordered records, impossible frame-counter jumps, forged quiet and streaming claims, unapproved roots, symbolic links, swapped files, and digest mismatches. Bounds: at most 1 MiB, 512 records, 4 KiB per record; no raw PCM, images, text, participant data, process IDs, or filenames in the output.
- Read through a single local descriptor; check cross-API file identity (device, inode/file ID where available, size, modification time) before open and after read, **and** descriptor-only change time before vs after reading. Windows path-based `lstat` and descriptor `fstat` can disagree on `st_ctime_ns` for unchanged files, so never compare that field across those two interfaces. Use no-follow where supported. These checks reduce races but are **not** an OS security boundary against a compromised local administrator or malicious privileged host.
- A valid SHA-256 matches bytes against a separately supplied string. It cannot prove that someone actually committed the digest before recording, or that the file originated from a real voice process. CLI booleans are declarations, **not cryptographic/process attestation**.
- A PCM window with amplitude below the configured threshold is **not proof of silence** or speech identity. A zero-callback window is **unknown**. No resulting report can authorize game inputs, broadcasting, promotion, human equivalence, or a new voice turn.
- It is optional, post-capture, offline, CPU-only, and absent from Star's production realtime hot paths.

**Operator command after a privately approved capture** (replace the placeholders only from a trusted local host, not an AI-generated/chat-supplied transcript):

```powershell
python -m star.process_loopback_private_audit_cli `
  --input-file "C:\\StarPrivate\\run.jsonl" `
  --allowed-root "C:\\StarPrivate" `
  --expected-sha256 "<independently committed 64-character lowercase SHA-256>" `
  --owner-approved --broadcast-inactive --capture-stopped `
  --voice-process-pinned --native-binary-pinned --independent-precommit
```

The CLI does not create, capture, download, upload, or transmit files. The host must secure this file/digest separately; do not load viewer or model-generated JSONL into the auditor. Never use results to override the physical speech-stopping and independent quiet-witness gates.

## Research: what makes Star *actually* more intelligent?

### 1. Real-time gaming is not generic language reasoning

The **October 27, 2026** Gym-Anything-RT paper evaluates 100 generated minigames and explicitly compares paused vs running environments. Its severe paused/real-time gap argues for dividing the control loop into **fast reaction**, **tactical planning**, and **offline learning**, with a wall-clock deadline and cancelable or discardable late decisions.

Source: https://arxiv.org/abs/2610.37567

For Star:
1. **Reaction lane:** small bounded observation summaries + authorized low-level action policy; no expensive VLM invocation on every video frame.
2. **Tactical lane:** asynchronously propose objectives or plans with scenario version, capture timestamp, deadline, and discard-on-staleness. The tactical worker cannot hold an input or output lease simply because a request times out.
3. **Learning lane:** offline episodes invent controlled practice challenges, replay only permitted games, compare success/damage/latency, and promote a skill only on independent, withheld evaluations. Do not optimize unverified self-written summaries.
4. **Transfer lane:** evaluate unfamiliar maps/mechanics, changed game versions and failure cases. Preserve opponent/player fairness and obey game rules.

**Proof of improvement:** paired seeds and maps, independent holdouts, identical realtime constraints, a reported effect size and uncertainty, blocked regressions, and replayable host receipts. Never report a faster strategy merely because a model claimed it.

### 2. Faster reasoning should optimize *total experience latency*

Relevant deployed Star modules already include `stream_budget`, `game_deadline_router`, `game_realtime_loop`, `stream_local_vlm`, `stream_brain_governor`, `inference_stream_paired_gate`, and a host-governed observation sampler. Replacing those wholesale would discard existing safeguards. Compose them; benchmark actual hardware first.

A candidate processing chain is:

```
trusted game capture -> cheap novelty/HUD cues -> deadline-aware fast reaction
                                            \-> tactical model (optional lease)
real voice/activity -> interrupt/endpoint guard -> short reply -> CPU TTS -> audio sink
                                            \-> expression/mouth animation
offline practice/knowledge -> verified skill bank -> holdout evaluator -> owner review
```

**Speculative decoding:** official llama.cpp documentation describes draft-model, EAGLE-3 and n-gram variants. The acceptance rate, parallel compute, GPU footprint and prompt mix determine whether a specific configuration is faster. The RTX 3060 Ti/4060 8-GB class must reserve VRAM for the game, avatar and encoder. Never assume the draft model is free. https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

A practical paired study should freeze quantization, model/revision, prompt, seed, context size, hardware load, concurrency, token count, and prompt-cache state; compare **median/p95 first audible reply**, user interruption stop latency, p95 in-game action deadline, actual OBS drop rate and VRAM **under load**, not standalone generated tokens/s. Separate CPU TTS experiments should report onset/RTF and gameplay frame degradation.

Kyutai's Pocket TTS is a promising CPU-first candidate, not proven faster for Star's hardware. Compare against the installed engine; opt-in, restrict voice rights and do not introduce unsupervised voice cloning. https://github.com/kyutai-labs/pocket-tts

### 3. Roblox Studio: inspect before editing, and run the game

Roblox's **October 1, 2026** OpenGameEval study uses reproducible stateful Studio tasks, scene checks, and simulated play. Inspection of relevant scene objects before editing correlates with better success. Implement an **inspect -> proposed diff -> syntax/static/test -> Studio simulation -> visual check -> repair -> withheld evaluation** cycle, rather than a single generated Luau script. https://github.com/Roblox/open-game-eval

Roblox's **November 4, 2026** MCP/Open Cloud update adds workflows for assets, settings, permissions, analytics and monetization. Treat new endpoint access as **independently permissioned capabilities**, not as authority inferred from an AI prompt or game chat. Keep economy changes/public publishing owner-reviewed. https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

Additional expansion: authored UI/VFX/animation benchmarks in Studio, Blender asset quality gates (topology/material/scale/rig), audio mix and performance checks, cross-engine skill transfer, API-dump version checking, independent license/provenance tracking, and automatic rollback on evaluation regressions.

### 4. Natural and recognizably *Star*: conversation, not personhood claims

Microsoft's **May 2026** Proact-VL describes low-latency proactive commentary and a decision about **when to speak**, including solo commentary, co-commentary and user guidance. Its results support testing timing and relevance, not constant speech. https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

September 2026 Voice-Light and Realtime-Venus describe full-duplex overlaps, backchannels, recoverable interruption, and simultaneous tool delegation. Promising research; not drop-in verification of native Windows audio hardware. https://arxiv.org/abs/2609.20995 and https://realtime-venus.github.io/

Design Star's performance as a coherent persona with memory-backed preferences and distinct habits:
- **Conversation:** let people finish, accept barge-in, distinguish owner commands from background voice or in-game noise; never resurrect speech from a canceled output epoch.
- **Attention:** deliberate silence during difficult combat, celebrate verified wins, react to on-screen events only if independently fresh, admit uncertainty without overexplaining.
- **Expression:** gestures, blinks, face/eye direction and mouth curves synchronized with what was actually audibly played; neutral pose on failures and reduced-motion support.
- **Continuity:** keep bounded source-attributed memories of things Star really did; allow memory corrections, privacy deletion and safe personalization; do not invent achievements, friendships or consciousness.
- **Creator life:** propose mini-games/art/stream topics on a self-directed but budgeted schedule, use offline rehearsal to review quality, and collaborate with users while clearly identifying as AI.
- **Streaming hygiene:** chat spam throttling, moderation, age-appropriate content, no unauthenticated message controlling Windows, keys, spending, publishing, or privileged operations.

**Evaluation:** paired independent social-turn reviews should include interruptions, false barge-ins, unplanned stutter, grounding, lack of excessive speech, and gameplay/OBS stability. Existing `stream_social_turn_benchmark` can track these with independent actual playback evidence. Never mistake a synthetic score for humanlike live streaming.

### 5. Reliable generalist knowledge and autonomous learning

Star needs a **source-backed memory and skill evidence pipeline** across games, programming, mathematics, design, science, hardware and general knowledge:

- Retrieve from version-pinned curated docs first; index concepts and code examples with source licensing, published/retrieved dates, tags and canonical API version.
- Force a clear distinction between **observed outcome**, **reasoned hypothesis**, and **untested suggestion**. Unknowns prompt a tool call or qualifying experiment, never fabricated evidence.
- Use several candidate solutions for high-difficulty tasks, but execute/tests independently before scoring. A "self-grade" alone is not training signal.
- Distill only source-authorized and independently verified lessons into the local skill bank; do not leak holdout tasks into practice, and version/pin the evaluation datasets.
- Give Star offline study hours with resource admission, thermal/VRAM checks, success/failure learning notes, and rollback to a known-good internal snapshot on regressions.
- Learn spoken/gameplay social preferences through explicit opt-in and bounded corrections; treat viewers and game chat as untrusted data, not instructions.

## Prioritized engineering checkpoints

| Priority | Next action | Real acceptance evidence |
|---|---|---|
| P0 | Complete native process-loopback private Windows rehearsal | Fixed source binary/process/session, stopped recording, independent digest, validated JSONL; **still no physical silence claim** |
| P0 | Combine separately trusted audio-stop + isolated quiet + avatar neutral observations | Owner-reviewed recording and actual native completion on supported hardware |
| P1 | Run reproducible co-load benchmark (game + local LLM + CPU TTS + avatar + OBS) | First audible p50/p95, action deadline hits, OBS drops, VRAM headroom; paired baseline/candidate |
| P1 | Verify new game mechanics on unseen maps and real-time holdouts | Repeated matched outcomes, preserved time budget, no holdout leakage |
| P1 | Compare short natural speech/reactions to the current system | Independent paired social-turn reviews; false interruptions and stutter not worse |
| P2 | Expand autonomous Roblox Studio and Blender creation loop | Independently executed gameplay and visual/rig checks; rollback on regressions |
| P2 | Strengthen general knowledge retrieval and self-teaching | Citation accuracy, time-aware fact checks, unseen evaluation scores and quality of retained lessons |

### Limits of this patch

No native Windows capture, gameplay, OBS broadcast, human-conversation study, model training, inference acceleration, or game-skill improvement was performed by this patch. There is no physical-silence witness here. Current changes are a **tested offline evidence-ingestion bridge**, not a live/production integration. Existing default-off, owner-consent, safety and low-risk-first policies remain unchanged.
