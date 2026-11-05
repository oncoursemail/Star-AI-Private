# STAR: a measurable private VTuber rehearsal, gaming intelligence and faster real-time cognition

**Research / implementation: November 4, 2026.** Scope: one new offline read-only operational CLI plus tests. It builds on existing OBS artifact decoding and recorded-audio/rendered-mouth alignment analyzers. This does not demonstrate a complete real game, humanlike livestream, faster neural inference, or increased model intelligence.

## Why this iteration is different

Star already had extensive planning/control-plane code for OBS, avatar, game telemetry, learning, model routing and speculative commentary. A practical integration gap remained: the OBS monitor could report that private recording was progressing and the audio/avatar analyzer could measure selected output, but there was no single operator-facing command that joins the decoded OBS artifact and optional rendered voice/mouth evidence.

This PR adds **star/stream_private_rehearsal_audit_cli.py** with one bounded report across both existing measurement stages. It does not increase OBS, game, microphone, chat, or streaming permissions.

Run after an independently started, nonbroadcast OBS recording has **fully stopped**, with the video inside an owner-approved local directory:

~~~powershell
python -m star.stream_private_rehearsal_audit_cli --recording "C:\StarRehearsal\test.mkv" --allowed-root "C:\StarRehearsal" --owner-approved --recording-stopped --broadcast-inactive
~~~

For optional **rendered mouth vs isolated spoken audio** measurement, supply calibrated mouth-closed and mouth-open stills from the same avatar inside the same approved directory, an owner-chosen mouth ROI, and host declarations that the track contains only Star speech and the capture is actual output rather than generated/intended audio:

~~~powershell
python -m star.stream_private_rehearsal_audit_cli --recording "C:\StarRehearsal\test.mkv" --allowed-root "C:\StarRehearsal" --owner-approved --recording-stopped --broadcast-inactive --audio-track 1 --closed-still "C:\StarRehearsal\closed.png" --open-still "C:\StarRehearsal\open.png" --mouth-roi 120 180 96 64 --isolated-star-audio --actual-output
~~~

The ROI numbers are **illustrative**. The track number is a zero-based selected audio stream in the container and may not match the OBS UI track number.

**Evidence boundary:** CLI flags are operator declarations, not trusted attestations. The module cannot independently verify that the media came from OBS, who spoke, that a game was played, that actions were authorized, or that a broadcast was off at all earlier times. False flags could mislead; an independently controlled host is needed for stronger provenance. Reports always mark humanlike behavior, game success, voice identity, and broadcast authorization as **not verified**.

The new CLI emits aggregate JSON, not filenames, speech, pixels, viewer IDs or transcripts. Admission requires an approved absolute root and bounded paths inside it; symlinks, traversal and altered media are rejected. Both existing analyzers use bounded FFmpeg/FFprobe subprocesses with no shell. A failure returns a sanitized deferred verdict and exit code 2. This command never starts/stops OBS, captures media, invokes a model, broadcasts, or controls games.

## Research and engineering findings

### 1. Verify end-to-end output before swapping voice models

A genuine 30–120 second private recorded session is the smallest falsifiable next milestone. Evaluate the *same physical output*: actual gameplay visible; isolated Star-only voice present; mouth movements aligned to output; comments tied to authentic game events; acceptable presented frames; no broadcast. The CLI automates decodability and optional waveform/mouth alignment, **not** semantic event identity.

Microsoft Research's Proact-VL (accepted at ICML 2026) focuses on **when to speak, what to say and how much** during live gaming. Compare silence versus commentary using a fixed real-game trace. Track false callouts/minute, relevance, unanswered questions, interruption mistakes, first-audible-sample latency and owner-rated naturalness. Speaking more often is not proof of better conversation.

Kyutai's Pocket TTS offers 18.2M-, 6.9M- and 1.9M-parameter CPU variants (October 2026). Published performance is **not** Star's latency. Try the smallest voice that achieves acceptable clarity while gaming; measure PCM time-to-first-chunk, CPU use, pronunciation, coherence and expression. CPU can be superior when the GPU is already constrained by game rendering.

### 2. Separate fast speech from slow game strategy

TalkAct (2026) demonstrates a fast conversational lane and a slower computer-use agent joined by a bounded action/state digest. Its reported ~0.6 s versus ~8.6 s median conversational latency belongs to its **controlled synthetic benchmark**, not Star or gaming. The transferable principle is to avoid blocking real-time social turns behind a slow multistep planner.

For Star, the fast short-answer lane should receive scene-specific, source-tagged digests from the slow planner: current goal, progress, verified result, uncertainty, and expiry. It must not invent task completion from a stale digest. Expired/superseded commentary is discarded before speech. Reuse the existing stream_brain_governor, stream_parallel_commentary_prefetch, stream_preemptive_host, stream_focus_inbox, stream_context_host, stream_stage and stream_host_live_output_gate modules before creating more scaffolding.

### 3. Game-playing ability must learn from authenticated attempts

Roblox's built-in Studio MCP (March 5, 2026) supports playtests and simulated input. Its April 9 Playtest Agent beta can tackle bounded tasks like picking up items or entering a vehicle. These are powerful QA tools in owner-authorized private games, not evidence of a trained general-purpose online player.

A genuine learning loop: observe a trusted game state/screenshot; establish one actionable goal; choose a permitted action; independently witness the outcome; classify the failure (perception/timing/world model/UI/planning); retry on a different seed; score on previously unseen levels. Start with navigation and simple inventory interaction before combat. Respect individual games' rules and do not bypass anti-cheat. Pause compute-intensive training while live.

Continue the independently sealed/counterbalanced holdout work from PRs #977–#978. Authentic process identity, actually witnessed runs and trusted game state remain prerequisite evidence. **Signed JSON alone is not game success.**

### 4. Make game creation executable, reversible and visually verified

Roblox's April 15, 2026 Studio roadmap emphasizes plan–build–test loops. Retrieve targeted official documentation; inspect the actual DataModel; perform reversible Luau/assets/UI edits only on one approved private experience; execute Luau tooling and multiplayer playtests; inspect runtime logs, gameplay objectives and rendered screenshots; roll back measurable regressions. Use performance, mechanics, timing, animation clarity, visual usability, and playability, not verbose code or self-rated style, as success metrics.

### 5. Raise verified intelligence-per-second, not just tokens-per-second

For 8 GiB RTX 3060 Ti / 4060-class machines, context KV cache, game textures, OBS composition and avatar animation compete for VRAM. No universal fixed model speed, size, or context capacity is justified without concurrent hardware measurement.

Run paired measurements under the **same real game+OBS workload**, controlling prompts, game scene, starting memory, model revision and capture configuration: fast model versus deep model, prompt cache off/on, speculative decoding off/on, CPU vs GPU TTS, context length, and background learner off/on. Report p50/p95 first-audible latency, successful game actions/sec, unseen-game success, inference TTFT/tokens/sec, frame-time p1, OBS missed frames, memory margin and faults.

llama.cpp SPEED-Bench supports per-category throughput, latency and speculative draft acceptance comparisons. Different speculative methods can regress on higher-entropy prompts, so select by measured workload. Keep expensive research/training behind a bounded low-priority queue; caching and fact verification beat spawning more unmonitored agent processes.

### 6. Humanlike presentation without deceptive identity

Build a consistent **AI character**: stable expressive voice, recurring preferences and interests, playful but nonrepetitive humor, relevant silence, natural interruptions, believable reactions and **memories of actual experiences only**. Victory/loss/surprise cues should be grounded in observed game events, not fabricated human emotions. Avoid reading secrets or abusive chat aloud and identify Star as an AI VTuber. This is functional behavioral design, not a claim of human consciousness.

## Acceptance targets and what is actually proven

| Goal | Independent evidence needed | This iteration |
| --- | --- | --- |
| Valid local private OBS artifact | Stable stopped nonbroadcast media, decoder verifies video and audio | New CLI checks a selected local file; no actual Star recording provided |
| Voice visibly syncs with Star avatar | Isolated actual-output Star track, calibration stills, audio/mouth frame alignment | New CLI combines existing analyzers; no actual Star voice/rig capture |
| Commentary matches gameplay | Spoken output time aligned with a separately authenticated game event | Not verified |
| Autonomous gameplay learns | Real attempted actions and hidden-seed holdout improvement | Not verified |
| Faster intelligence | Matched A/B performance and quality across game, OBS and TTS | Not verified |
| Humanlike private stream | Independent viewer review, timing and naturalness plus disclosure | Not verified |

Tests include mocked integration, adversarial admission/media-mutation/consent cases and an optional synthetic FFmpeg integration when that decoder is installed. Synthetic clip success is **not** evidence of a live Star game or speech.

## Sources researched

- Roblox, built-in Studio MCP and automated playtesting, March 5 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox, Playtest Agent Beta, April 9 2026: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- Roblox, Studio is Going Agentic, April 15 2026: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- Microsoft Research, Proact-VL, ICML 2026: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- Kyutai, Pocket TTS small English CPU models (October 2026): https://github.com/kyutai-labs/pocket-tts
- TalkAct, Talking While Acting (2026): https://github.com/19PINE-AI/TalkAct
- ggml-org/llama.cpp, SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- OBS Project, obs-websocket and authenticated local OBS interface: https://github.com/obsproject/obs-websocket
