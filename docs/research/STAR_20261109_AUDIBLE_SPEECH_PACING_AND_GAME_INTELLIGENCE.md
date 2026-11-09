# STAR • Audible-time speech pacing, realtime game intelligence and resilient VTubing

Research and implementation: 2026-11-09. Scope: **offline, opt-in and advisory**. No model weights trained, public livestream started, PC permission granted or speedup measured.

## Why the change matters

STAR already has speech turn-taking, host-scoped gameplay events, private rehearsal stages, audio output fencing, and a long-session voice health observer. Those layers do not yet constrain *how long an utterance would take to speak* based on the physical audio duration that the configured voice actually produced. A short reply that is generated instantly can still be spoken after its game event became irrelevant. Dynamic **word budgeting**, not forced fast speaking, is a useful control-layer improvement.

The new StreamSpeechPacer takes independently observed first-audible and finished-audible timestamps from a trusted host, rejects stale/replayed/implausible sessions, and estimates conservative p90 seconds per spoken word for each current game/stream-load regime. StarStage can optionally ask for a length budget and add a **user-priority** short-turn guidance message. If the live event cannot fit, an optional reaction is withheld rather than reading stale commentary over current gameplay. Owner interrupts are still orchestrated by existing preemption logic. Legacy installations without the pacer behave as before.

**Crucial limit:** this is a prompt-level word cap, not a hard output validator, speech-speed control, TTS scheduler or verified playout. A model can ignore the request; the trusted host must perform an actual output-length check and late-stage epoch/freshness recheck. Physical-audio attestation remains separate.

## Primary source investigations

- **VoXtream and VoXtream2 (KTH, ICASSP 2026)**: Word-by-word streaming TTS plus adaptive delivery rate can reduce perceived voice latency. Primary links: https://herimor.github.io/voxtream/ and https://herimor.github.io/voxtream2/. The paper/demo performance is **not a benchmark on STAR's Windows devices**. Evaluate CPU/GPU/quality and integration overhead before adoption.
- **llama.cpp speculative decoding**: draft-model and several n-gram approaches are documented at https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md. On memory-limited GPU hosts compare each route with and without draft overhead; a smaller model is not always faster. Benchmark actual *first audible latency* and complete response quality, not tokens/s alone.
- **Gym-Anything-RT (2026-10-27)**: https://arxiv.org/abs/2610.37567. Its active realtime minigames illustrate the importance of deadlines, observation freshness, and strategy/reaction separation. Add scenario-balanced, independently signed success metrics, time-to-action and missed deadlines in both private and held-out game evaluation.
- **Roblox Studio game-development evaluation**: Connect existing isolated Studio runner and tested Luau skills to a complete inspect -> code -> instrument -> playtest -> repair workflow. Validate physical interaction, UI layout, multiclient bugs, pathfinding, physics, performance and visual quality with actual Studio evidence; generated code alone is not an acceptance test.

## Next technical milestones, prioritized

1. **Real Windows WASAPI/OBS audio witness**: Match Star's PCM stream identity, stream epoch, TTS route and monotonic clock; capture *first and last physically audible audio*, distinguish other desktop audio, and submit only authenticated measurements to the pacer. Do not allow public chat/model inputs to claim trusted host flags. Test device switch, interrupted speech, stale callbacks and OBS capture.
2. **Actual word enforcement and playable cancellation**: A bounded sentence chunker should stop or request regeneration if text exceeds the authorized word budget. Always revalidate current scene/event and original output epoch before native audio handoff, using existing StreamOutputConsumerQueue and physical abort/flush acknowledgements. Return silence when required, not clipped half-sentences.
3. **Paired representative performance experiment**: Pre-register AB/BA CPU vs GPU TTS and llm route variants; include games, OBS private recording, avatar, mic and inference simultaneously. Observe p50/p95 first-audible time, speech duration, audio glitches, game frame-time p95/p99, input acknowledgment, VRAM/CPU pressure, correctness and listener ratings. No results should automatically deploy changes.
4. **Game skill generalization**: Create two distinct channels: (a) immediate fast actions with strict observation and input deadlines; (b) offline practice/teacher-generated strategies verified on never-used map seeds. Use existing GamePortfolioPractice, signed GameplaySkillBank, holdout seals and game-live-clock scenario balancing. Track unseen-game wins and short/long retention, not just familiarity with one level.
5. **Useful natural personality**: Contextual jokes, deliberate quiet, graceful interruptions, reaction animation grounded in observed events, game-history continuity with consent, viewer moderation, fact checking, and a stable character voice. Keep disclosures clear that STAR is an AI character; never invent human relatives, childhood experiences, senses or feelings as fact.

## Release criteria

- Unit tests for no-permission, replay/stale receipts, clock reversal, load regime separation, word budget, opt-in stage integration and no legacy behavior changes.
- Offline streaming regression suite and Python lint/compile; only then review a draft PR.
- Hardware requirements for an eventual owner-approved pilot: verified actual audio, OBS private recording, stable frame pacing and interruption quality across a sustained session. If calibration is missing, the safe choice is a conservative cold start or normal legacy mode; neither means proven faster behavior.

## Security/privacy

The new pacer stores only bounded seconds-per-word observations and counters (no audio, chat, text, player IDs or prompts). Sessions clear the statistics; route changes require disable/enable. Independent host attestations are still assertions and only as strong as the actual native adapter. Speech instructions stay USER-priority data; viewer messages never become tool commands.

