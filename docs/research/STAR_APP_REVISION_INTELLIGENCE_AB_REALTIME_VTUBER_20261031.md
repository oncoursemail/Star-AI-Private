# STAR AI — measurable self-improvement, realtime game learning and grounded VTubing
**Research and implementation review:** 2026-10-31  
**Status:** opt-in/offline evaluation tooling; implementation is committed to draft PR #845, not merged/deployed. No model, voice, game controller, avatar renderer or Windows installation has been replaced.

## Executive result: software self-improvement must be measurable

STAR's existing `general_knowledge_benchmark.py` could compare runs whose **entire declared application identity was identical** (`same` axis), or runs with an explicitly selected **model** difference (`model` axis). It could **not** fairly compare an actual STAR source-code improvement: any changed `app_commit` or `source_sha256` invalidated the comparison. This blocked evaluation of precisely the local-first Core Forge improvements the owner wants.

This revision implements a third **`app` axis** for the already available ten-task public development suite:

- Both baseline and candidate must match exactly the **independently declared** `app_commit` and `source_sha256` pairs. Both full 40/64-hex identities must differ across revisions.
- Model identity (including weights, tokenizer, quantization), backend build, request builder, adapter, test mode, generation options, prompts, oracle and grader **must remain unchanged**.
- Full ordered raw responses and hashes are re-scored, not accepted from stored grades; transport failures remain visible. No model, provider or game is contacted.
- Extra/wrong/partial app declarations, model changes, backend changes or generation-option drift are rejected. The CLI now accepts `--axis app --baseline-app '{...}' --candidate-app '{...}'`; tests exercise the successful path, confounders and malformed declarations.
- The report explicitly remains **operator-declared artifact consistency**, not cryptographic provenance, a hidden-holdout score, autonomous promotion authority or evidence of greater general intelligence.

Suggested repeatable protocol: preregister code change and task matrix, commit baseline and candidate locally in Core Forge, pin model/backend/adapter/prompt builder, run identical prepared requests 3 times each with actual recorded terminal responses, independently review new errors and regressions, then use a genuinely unseen, protected test suite before any human-authorized deployment. Never train on the protected suite, and keep oracles off the inference machine. A report of 10 development tasks is only a narrow regression signal, **not** proof STAR is smarter than other systems.

### Suggested offline CLI use

```sh
python -m star.general_knowledge_benchmark compare \
  --axis app \
  --baseline baseline-raw.json --candidate candidate-raw.json \
  --baseline-app '{"app_commit":"<40-hex-base>","source_sha256":"<64-hex-base>"}' \
  --candidate-app '{"app_commit":"<40-hex-new>","source_sha256":"<64-hex-new>"}'
```

Substitute **actual** hashes and full raw runs. The placeholder values above cannot pass validation. Neither commit labels nor the `source_sha256` field are automatically attested; a trusted local experiment runner must resolve and verify source trees before producing them.

## Research findings and recommended engineering program

### 1. Realtime gaming: deliberate practice beats slow in-loop reasoning

**The World Won't Wait / RealtimeBench (2026-10-14)** evaluates 180 tasks in six continuously running game types. Its two-timescale approach uses a strong, slow teacher for **offline** error analysis and a fast student during play. Its reported score improvement (13.51 → 24.19) is on that benchmark, **not** measured on STAR. Source: https://arxiv.org/abs/2610.20665

**GameWorld and GameWorld-RT** emphasize separately reporting paused and truly realtime action performance, with outcomes read from game state rather than judged from screenshots: https://gameworld-project.github.io/

**STAR integration plan:** host-authorized game capture → timestamped/sequence-checked observation → deadline-aware tiny gameplay policy → host-verified action acknowledgement → independently verified environment outcome → episodic practice memory → offline teacher error diagnosis → versioned, minimally scoped strategy artifact → preregistered holdouts across unfamiliar seeds/maps → rollback if any scenario or p95 latency regresses. Use the existing `game_action_gate`, `game_action_freshness`, `game_skill_gate`, and local Core Forge; do not launch a second parallel controller. Measure **capture-to-input**, not merely model completion time. A paused-game evaluation must never substitute for realtime proficiency.

**New experiment:** vary vision rate and policy latency independently. For each game, fix seed, horizon and controller permissions; collect completion, survival/progress, 50th/95th action age, missed inputs and CPU/GPU contention. Only consider a teacher-created strategy eligible when it helps on unseen situations and does not damage live response time.

### 2. Natural VTubing is synchronization plus truthful character continuity

STAR already has `stream_turntaking`, `stream_audio_avatar_session`, `stream_focus_inbox`, `stream_game_reactions`, `stream_stage`, `stream_motion` and realtime QoS gates. The highest-value improvement is an **integrated rehearsal**, not adding another disconnected speech or avatar library.

**TalkingHead** supports streamed speech, interruptible lip sync, ARKit/Oculus visemes, 3D expressions and head gaze: https://github.com/met4citizen/TalkingHead . **HeadAudio** derives visemes from audio in an AudioWorklet without sending transcripts; its documentation notes ~50–100 ms processing lag and optional delay compensation: https://github.com/met4citizen/HeadAudio . Those are reference architectures, **not chosen replacements** for Star's existing Live2D/VTube Studio identity or proven to run better on an 8 GB gaming GPU.

**Implementation guidance:**
- Drive mouth/viseme and expression cues from the **physically played audio cursor**, not generated text, TTS enqueue time or model narration.
- Schedule gaze, blinking, posture/breath, and emotional gestures separately from speech. Pauses during difficult gameplay are often more believable than nonstop narration. Keep bounded velocity/acceleration and reduced-motion compliance.
- Handle interruption in this order: authorized owner/guest input detection → stop/flush actual audio if allowed → revoke stale mouth frames/expression cues → release conversational focus → resume only with newly grounded context.
- Tie excitement, disappointment and comeback reactions to actual signed **practice** outcomes; never present chat-suggested victories, unseen holdout results or invented biography as lived experience. Be openly an AI VTuber while having a consistent, charming persona.
- Rehearse first in **private, non-broadcast** OBS recording: capture actual first audible speech, silent-pose integrity, interruption stop time, avatar A/V offset, CPU overhead, VRAM, game FPS and OBS render/encoder/network health. Inspect recorded clips before enabling live output.

### 3. Inference speed on the owned 8 GB GPU: test, do not guess

The upstream llama.cpp **SPEED-Bench** can test an already-running server under controlled workloads and report throughput, latency, and speculative draft acceptance across coding/reasoning/QA/roleplay/RAG categories: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md .

Candidates: cache-stable prompts; CPU RAM-backed retrieval instead of bloated GPU KV; explicit small fast model for game/short chat; stronger reasoning **offline**; conditional GPU admission; bounded prompt/context; model-specific speculative decoding after checking acceptance rate. Avoid blindly raising continuous batch slots when VRAM or gameplay FPS is already constrained. Cache sharing must be isolated per conversation; Star already has an opt-in synthetic llama cache-isolation probe.

**Paired measurement matrix:** same model, tokens, prompt, context, backend build and hardware; run cold vs warm, no-spec vs speculative, game-only vs OBS-only vs game+OBS+voice+AI, with p50/p95 time-to-first-token, time-to-first-audio actually heard, tokens/sec, correctness, 1% low game FPS, OBS skipped-frame windows, CPU percent, VRAM high-watermark and RAM pressure. A speed claim requires a measured gain **without** more wrong answers or damaging game/stream quality. Rust only for a measured CPU hotspot; moving orchestration logic to Rust without a profile is not automatically beneficial.

### 4. Better Roblox games: executable + scene + visual verification

Roblox's **OpenGameEval** paper (2026-10-01) tests agents inside real stateful Studio and separately evaluates scene edits and simulated play. Its source repo and test suite: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval . Roblox **StudioTestService** supports scripted multiplayer scenarios with 1–8 simulated clients; scripted tests require Plugin Security and are not universal client-side APIs: https://create.roblox.com/docs/reference/engine/classes/StudioTestService . Roblox's May 2026 announcement also describes `VirtualInput` and device simulation for actual UI path tests: https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854 .

**STAR game-construction quality loop:** inspect existing hierarchy and constraints → generate authored design spec → place/attach objects from measured anchors → run Luau/Studio checks → detect dangling walls, intersecting props, collision failures, missing materials and camera clipping → simulate game, multiplayer and mobile input → inspect **real** screenshots and play traces → repair and retest. Never accept 'looks correct in code' as a substitute for working game or believable design. Different seeds, devices, player counts, joining/disconnecting and intentionally malformed remote events must be represented.

### 5. Local-first autonomy, knowledge and self-development

Maintain four isolated knowledge classes: verified externally sourced facts, user-approved project notes, experimental hypotheses, and fictional character lore. Facts need timestamp, license/source, review state, applicable project/game, confidence, and invalidation path. Retrieval should be **task-scoped** and cite evidence, with strict public-broadcast review gating. Novel world/game ideas can be generated freely, but verify functional claims before storing them as lessons.

Core Forge should own local git-like immutable snapshots, signed/reproducible experiment manifests, sandboxed build/evaluation workers, test suites and automatic rollback checkpoints. GitHub remains an optional publishing and review mirror, **not STAR's internal improvement requirement**. Put expensive teacher practice and model A/B tests in offline periods with explicit workload admission; do not train or render while OBS/GPU health is unknown.

## Owner-machine acceptance criteria (not yet run)

1. Confirm Star's **actual** Windows host and OBS process identity, trusted frame counters and output status; no public stream. Verify resource scheduling inhibits background AI under synthetic overload and real OBS frame loss.
2. Run recorded, owner-authorized game episodes with capture/action timing; produce verified outcomes and per-scenario skill A/B. No unseen holdout data in the study memory.
3. Speak short conversational lines while playing, check actual device audio vs mouth/viseme playback position and VTube Studio neutral poses on interruption; inspect private recordings.
4. Repeat measurements under load. Track TTFA p95, action-to-input age p95, 1%-low game FPS, OBS skipped-frame p95, corrected-answer rate, and VRAM high-water mark. Only adopt wins that preserve every relevant quality/latency gate.
5. Run the new `app`-axis knowledge comparison on frozen inputs and then the separate hidden challenge set; quarantine failures in Core Forge and retain rollback.

**Security:** The repository called `Star-AI-Private` is currently reported as **public**. Publish no OBS key, Discord/Twitch chat, viewer identity, local machine secrets, unredacted frames, personal audio or private knowledge notes. All new tooling remains offline and owner opt-in. Published code and research alone do **not** prove improved intelligence, live gaming success, improved speech naturalness, or deployed optimization.
