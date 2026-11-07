# STAR: OBS output/host mode reconciliation and real-time intelligence gate

Research and implementation note — October 31, 2026. This changes **advice only** in an opt-in offline-tested coordinator; it does not open OBS, control a game, execute jobs, install a model, or broadcast.

## Verified issue and implementation

The existing streaming bridge independently required OBS GetStreamStatus outputActive=True before admitting live work. However, a contradictory trusted host snapshot with telemetry.live=False could still enter the **offline** path while the separately attested OBS output was active or reconnecting. That could advise costly training/render/research at precisely the wrong time. A malformed trusted GetStreamStatus response that was not a mapping also raised before invalidating its prior healthy admission.

The fix introduces an output-busy latch: outputActive **or** outputReconnecting means *possibly streaming*, independently of host telemetry.live. A reconnect or invalid trusted status cannot clear that latch; only an ordered host-verified GetStreamStatus with both flags strictly False can clear it. Contradictory offline samples now fail closed, and malformed trusted status packets invalidate previous advice. Existing real-time speech/gameplay priority advice remains unchanged; no new permissions or job execution are granted. Synthetic tests cover mismatch, reconnect, malformed shapes and flags, stopped-stream recovery, and unverified spoofing.

Official OBS WebSocket v5 protocol documents GetStreamStatus.outputActive and outputReconnecting, distinct from GetStats frame counters: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

## Next implementation gates (not shipped by this commit)

1. **Authenticated Windows integration**: one local, version-pinned OBS WebSocket v5 collector with source/session binding; record one monotonic host timestamp per measurement and explicitly reset after OBS restart or output switch. Reconcile stream-state reports from OBS and local GPU/voice monitoring. Do not treat OBS preview rendering or disconnected OBS as a healthy broadcast.
2. **Admission enforcement**: local Windows task runner must check advice before launching noncritical work, re-check while it runs, cooperate with immediate suspension, and retain an independent owner emergency stop. The bridge must never be construed as an execution grant. Preserve game/OBS/voice threads under contention. Report VRAM, game p95 frame time, OBS render/output-frame skip delta, speech playback queue, and action age.
3. **Two-timescale gaming**: fast policy handles time-critical actions; teacher explores mistakes offline in owner-authorized local game labs. Admit changes only with paired unseen-map outcome improvements, no material per-map latency regressions, and reproducible snapshots. The October 14 RealtimeBench paper evaluates 180 tasks in environments that keep running while models think; external benchmark gains are *not* STAR benchmarks: https://arxiv.org/abs/2610.20665
4. **Independent latency-aware benchmark**: Stanford's October 22 Realtime-Bench compares wall, paused, and token clocks, exposing reasoning-vs-action latency tradeoffs. STAR should report all three clocks on private fixtures, action TTL expiration, objective/gameplay win rate, and independent evaluator acceptance: https://digitaleconomy.stanford.edu/publication/realtime-bench-can-frontier-models-solve-real-time-interactive-problems/
5. **VTuber naturalness without false human claims**: keep an expressive stable AI persona with brief gameplay-grounded recollections, speech/animation alignment, context-sensitive silence during combat, interruptions and warm responses. Compare voice candidates using first-audio latency, intelligibility, listener preference, voice consistency, and CPU load; **do not** infer human feeling or consciousness. LiveKit v1-mini runs a local CPU speech-turn detector; benchmark against existing endpointing and preserve opt-in microphone controls: https://docs.livekit.io/agents/logic/turns/turn-detector/ . Kyutai Pocket TTS v4.0.1 (October 21, 2026) offers small English models to test for CPU streaming: https://github.com/kyutai-labs/pocket-tts/releases
6. **General intelligence and game creation**: evidence-tagged notes (verified/reference/hypothesis/persona lore), retrieval with source and expiry, active practice on unknown tasks, multi-agent generate/verify, and local Forge rollback. Build -> inspect scene graph -> run Luau/style/API checks -> visual/physics checks -> scripted StudioTestService with client/server and dynamic joins -> repair -> independent play. Roblox documents up to eight simulated Studio clients: https://create.roblox.com/docs/studio/testing-modes

## Measurable owner-PC acceptance

- During a verified OBS live session, a contradictory host live=False sample must never advise training, research, or rendering. Valid stopped-output attestation plus a fresh offline snapshot restores eligibility.
- Missing, invalid, replayed, reconnecting, or stale OBS stream status must not imply idle resources. Speech/gameplay prioritization remains advice only; critical host permissions do not change.
- A 30-minute private dry run should capture synchronized p50/p95 action-age, LLM time-to-first-token, TTS first-audio delay, OBS render/output skip, GPU VRAM headroom, game frame time, interruption latency, and grounding errors (without retaining chat identities or frames by default).
- Performance claims require a paired baseline on STAR's real CPU/GPU and held-out games. No inference-speed, win-rate, voice-quality, or humanlikeness improvement is claimed from this coordinator fix alone.

## Safety and scope

Opt-in feature off unless authorized; never infer permission to play an external multiplayer game, broadcast, spend money, or modify autonomous policies from good health metrics. Public repositories must not contain OBS keys, recordings, biometric voice data, private source examples, or user identifiers. GitHub is an optional export; STAR Core Forge retains local snapshots, rollback and test evidence.
