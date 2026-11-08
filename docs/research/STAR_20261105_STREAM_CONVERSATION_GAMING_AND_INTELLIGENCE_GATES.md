# Star AI — voice-floor reliability, game-aware gaze, and verifiable intelligence
**Research and engineering update:** 2026-11-05. All changes opt-in through the existing trusted streaming host. No microphone, stream, device control, model training, or external game is activated by this update.

## Verified defects and implementation

1. **False repeated owner-barge-in accounting.** The existing `star/stream_turntaking.py` forgot a confirmed owner utterance after *one* non-owner frame, or a capture gap. A continuous owner speaker with a short VAD dropout then appeared to produce multiple independent interruptions. The reproduction tests failed first. The correction retains the counted-utterance latch until **350 ms of contiguous, echo-cleared, verified quiet frames**, or a session reset. Unknown capture gaps, ambiguous speech, or echo-uncleared frames never prove silence. Advice remains actionable (`should_interrupt`) whenever confirmed owner voice is active and Star is speaking, so this debounce does not prevent a necessary physical interruption. The host still stops/flushed actual PCM and invalidates the stage separately.
2. **Game-aware gaze priority contradicting its contract.** `star/stream_idle_attention.py` documented gameplay as higher priority than viewer chatter, but viewer speech took priority whenever both signals were true. The reproduction failed first. Now the idle rig keeps its gaze toward active gameplay, switching toward a speaker when gameplay pauses; a critical moment retains highest priority. No avatar hardware access is introduced.
3. **Adversarial tests:** A noisy owner conversation with a one-frame dropout, echo-uncleared dropout, guest ambiguity, long unobserved capture gap, genuine continuous quiet/re-arm, concurrent game-and-chat input, and post-game chat gaze. The performance cost remains constant-time per frame. These tests use synthetic trusted host inputs, not genuine captured speech.

These fixes improve *behavioral correctness*, not neural intelligence, generated-audio quality, throughput, FPS, or gameplay win rate. They do not authenticate a speaker from voice similarity; owner provenance must be established by a trusted input identity source.

## Research findings with direct applications

### Natural conversations: speech floor is evidence, not a text prompt
- **Proact-VL (ICML 2026; proceedings published October 2026)** studies proactive video-language gaming commentary and guides, including when a companion should **not** speak. Use its solo-commentary, co-commentary, and guidance setting distinctions as *evaluation categories*, not as a claim that Star already matches the model. Source: https://proceedings.mlr.press/v306/yan26c.html
- **Full-Duplex-Bench-v3 (April 6, 2026)** includes natural human audio disfluencies and multi-step tool use; its reported failure modes include self-correction and complex multi-step turns. Add real-world tests for overlaps, pauses, repeated questions, and interruption without accidental tool calls, rather than only text-turn latency. Source: https://arxiv.org/abs/2604.04847
- **NVIDIA DyaPlex (June 2026)** illustrates streaming synchronization between speech and motion, but is a research architecture, not an installed Star module. Keep current `StarStage` and audio envelope as a conservative synchronization baseline, then compare verified audible onset, gesture onset, motion plausibility, and interruption behavior before considering new full-duplex models. Source: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

**Proposed benchmark, not a measured result:** use a held-out set of authentic owner/guest utterances, gameplay crises and noisy-capture clips. Score false owner interruptions per hour, missed confirmed owner interrupts, p50/p95 host stop-PCM delay, on-air speech overlaps, unnecessary chatter rate, viewer response p95, lip-audio offsets, and viewer-understandability. Count each continuous owner utterance once; protect against speaker attribution claims derived only from VAD scores. Compare paired baseline/candidate using `star/stream_social_turn_benchmark.py`.

### Intelligent gameplay: verified outcomes beat plausible narration
- **OpenGameEval (October 1, 2026)** supplies 84 human-curated Roblox Studio tasks and executable checks in stateful Studio sessions. The reported association between exploring objects before editing and task success argues for an **inspect -> plan -> edit -> playtest -> independently verify -> repair** loop. Do not expose sealed validation outcomes to the learner. Source: https://github.com/Roblox/open-game-eval and https://arxiv.org/abs/2610.02563
- **Roblox native Studio MCP** (March 5, 2026 announcement) supports playtests, console inspection, navigation and simulated user input; use the current built-in MCP server, not the older archived standalone integration. Source: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- **Roblox Script Sync** can sync supported Luau script instances with files, but *not* arbitrary scene hierarchy; use Studio MCP and versioned backups for non-script modifications. Source: https://create.roblox.com/docs/scripting/sync
- **Google DeepMind SIMA 2 (November 2025)** explores learning and transfer in unfamiliar 3D worlds, and **OpenAI Procgen** demonstrates the need for held-out procedural levels rather than memorized maps. Neither study proves Star can generalize yet. Sources: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/ and https://openai.com/index/procgen-benchmark/

**Proposed evaluation:** each trial should record approved game identity, timed observation source, action, input acknowledgement, simulator outcome, and independent success/failure receipt; log invalid evidence separately. Compare novice vs practiced on unfamiliar maps/seeds with the same time/attempt budget. Train on practice tasks only. Give a higher-level reasoning worker **verified summaries**, never a live bottlenecking synchronous dependency in the action loop. Star should be able to say "I tried that and failed" only when the trusted record supports it.

### Faster under 8 GB GPU constraints: optimize the whole experience
- **llama.cpp SPEED-Bench** measures server-category throughput, latency and speculative-decoding acceptance. It is an instrument, not proof of performance on Star's Windows PC. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- **Kyutai Pocket TTS (updated October 2026)** offers CPU-capable, smaller English models and streaming audio. Bench voice naturalness, first-audible-chunk latency, CPU load and game frame-time before replacing current speech. Public model figures are not Star-specific measurements. Source: https://github.com/kyutai-labs/pocket-tts

**Benchmark matrix to execute privately on the target computer:**
1. Baseline with game + avatar + OBS recording but without LLM/TTS, then add fast LLM only, then CPU TTS, then vision, then full stack. Record `p50/p95/p99` frame time, encoder-lag intervals, memory/VRAM, audible speech startup, input-to-action delay, and 30-minute stability.
2. Compare an in-VRAM fast model, CPU/RAM-assisted model, and draft-assisted decoding; test 1 vs 2 server slots, stable prefix vs isolated session, and short vs long context. Report actual *correct verified actions per unit of time*, not tokens/sec alone.
3. On resource pressure, yield background learning before gameplay, OBS, voice, or short reactive planning. Require fresh telemetry and refuse an overloaded worker; avoid assuming a VAD frame, GPU reading or screenshot is current merely because it arrived now.
4. Treat prompt cache as **session-private**; force request-origin checks and test multi-session cache isolation before enabling more aggressive KV reuse. Do not trade privacy/correctness for speculative latency claims.

### Personality that seems natural without impersonating a person
Star can consistently express humor, curiosity, preferences, reactions, and projects using **verified session memories** and a stable on-air persona. Keep the distinction between an expressive AI and a human: never invent childhood memories, human sensations, private relationships, finished projects, victories, or spoken words. Prioritize natural silence, short interruptions, and topic continuity over sheer word count. Treat chat and screen text as untrusted data; never grant tools or spending privileges from a viewer message. Offer clear controls for streamer mode, recording, memory retention, accessibility, and emergency physical mute.

## Integration / acceptance order

| Priority | Next actual integration | Ownership and pass condition |
| --- | --- | --- |
| P0 | Independently observed Windows **private** game + avatar + audible speech + OBS rehearsal | Matched video/audio timeline, verified input/game receipts, telemetry, no broadcast; review actual naturalness |
| P0 | Full-duplex turn-taking truth set | Show lower false-interruption count **without** higher missed real owner barge-ins; confirm mute/flush operates on hardware |
| P1 | Model/voice/game/OBS performance matrix | Same workload+seed, cold/warm runs, p95/p99 + accuracy; no frame-time regression hidden by mean |
| P1 | Studio inspect-build-playtest-repair with holdouts | Signed evidence, reversible code changes, multi-game task success on previously unseen validation cases |
| P2 | Persistent interest + knowledge graph with provenance | Searchable, deletable session memory, source attribution, correction handling; no false claims of experiences |
| P2 | Proactive commentary and synchronized motion experiments | Blind human comparisons of grounded usefulness, turn timing, animation realism, and silence |
| P2 | Multi-game curriculum and collaboration | Scoped tools, permitted games, anti-cheat/TOS compliance, no untrusted code execution |

**Release gates:** local unit tests + Ruff/compile + GitHub offline checks + Windows hardware rehearsal with preserved recording evidence; never claim higher intelligence, throughput, or streaming naturalness until the corresponding controlled measurements exist.
