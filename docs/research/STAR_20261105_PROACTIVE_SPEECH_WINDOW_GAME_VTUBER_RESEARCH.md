# STAR — proactive speech pacing, measured game intelligence and VTuber rehearsal
**Research and engineering note — 2026-11-05**

## Scope and what changed in this branch

This branch adds an **optional rolling audible-reaction budget** to `StreamDirector`,
with offline tests and `StarStage` integration coverage. It is **disabled by
default** (`proactive_limit_per_minute=0`), and the host still needs to opt into
the director/stage. For a private operator-controlled evaluation, instantiate
`StreamDirector(proactive_limit_per_minute=5)` and inject it into `StarStage`.
There is no live audio generation, stream control, model training or real game
input in this change. The limit is a proposed experiment, not a measured
optimal number.

Count only *audibly acknowledged* game observations, game successes, optional
viewer acknowledgements, and ambient remarks. Do **not** charge repeated
`propose()` calls, failed or abandoned utterances, or queued text. The rolling
window is 60 seconds, bounded in memory and thread-safe. A scene change does
not refresh the quota, avoiding chatter at each new level. Owner interruptions,
verified game-danger callouts and real viewer questions remain eligible; ordinary
voice overlap/game-critical/OBS pressure checks are still enforced upstream.
When quota is exhausted, the director returns silence on those optional
events and allows expired queues to disappear by their existing TTL.

**Why this matters:** repeated commentary every ~2 seconds can be distracting
and steal compute from gameplay and streaming. A short *measured* rate limit
is an experimentally controllable path to natural timing. This does **not**
assert that a quota by itself makes Star humanlike: muted or irrelevant speech
is also a failure. The existing social-turn benchmark explicitly detects
dropped expected commentary, missed questions, false interruptions and late
speech, so compare this opt-in policy to the default before adopting it.

## Research findings and practical integration

| Evidence (accessed 2026-11-05) | Finding | Next STAR experiment |
| --- | --- | --- |
| Microsoft/Zhejiang et al. **Proact-VL**, ICML 2026 (code released March 16; accepted May 1, 2026). [Project](https://proact-vl.github.io/) and [Microsoft](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) | Timing and *whether* a response is necessary are central live gaming companion problems; demos distinguish solo, co-commentary and guidance. | Evaluate independent speech timing, grounding and quantity on matched gaming situations, not just texts-per-minute. Keep strict source provenance. |
| [Full-Duplex-Bench v3](https://github.com/DanielLin94144/Full-Duplex-Bench), released May 20, 2026 | Turn-taking, backchannels and overlapping speaker interruptions must be scored directly. | Run owner barge-in, incidental noise, simultaneous viewer/chat/game and interrupted TTS playback tests with captured audio. |
| [DeepMind SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/), November 13, 2025 | Game agents can combine interactive perception, reasoning and repeated trial feedback; reported results are DeepMind's, not STAR's. | Separate fast action from offline teacher; add unfamiliar levels and independent outcome metrics before claiming skill transfer. |
| [Roblox OpenGameEval](https://github.com/Roblox/open-game-eval), October 2026 paper | 84 human-curated core tasks with stateful Studio plus executable edit-time/play-time checks; observation before edit is correlated with higher performance. | Evaluate `inspect -> plan -> edit -> simulation -> repair` on fresh game tasks; compare pass@1, stable repeat success and cost, not screenshot aesthetics. Do not inspect leaked holdouts during training. |
| [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md), documentation accessed Nov 5 | Controlled baseline and speculative configurations measure prompt/decode throughput, end-to-end latency and draft acceptance; acceptance varies with workload. | Bench identical coding + gaming-QA prompt mixes at equal slots/context, report p50/p95 first usable speech and GPU/OBS/game FPS under load; reject a faster-but-wrong setup. |
| [Kyutai Pocket TTS v4.0.0](https://github.com/kyutai-labs/pocket-tts/releases), released October 20, 2026 | CPU-usable English checkpoints at 18.2M/6.9M/1.9M parameters; 2M variants explicitly experimental. | Offline blind A/B of 100M vs 18M REFL vs 7M (and optional 2M) for first audible PCM, emotion/prosody, consonant clarity, and game FPS. Avoid assuming parameter count predicts quality. |

## Operating architecture: speed and correctness together

1. **Fast path (game focus):** a 10–30 Hz host capture loop should perform
   cheap hazard/focus observation where feasible; short trusted leases bound
   context and clock freshness. This is a design target, not the current
   verified throughput. Never send an old game's keypress after focus or OBS
   state changes. Route expensive VLM use at a lower cadence under pressure.
2. **Conversation path (speech):** source-classified, moderated viewer questions
   and grounded events go through the director. Optional proactive cadence
   handles only nonurgent commentary; turn-taking and interruption policy
   independently handle real people talking. Speech must not starve gameplay.
3. **Slow path (study):** a separate teacher solves navigation failures, game
   mechanics, coding, art, general questions, and retrospective plans **after**
   practice. Require independently verified signed outcomes, chronological
   precommit and clean held-out challenge split. Never call internal reflection
   verified gameplay success or updated model weights.
4. **Resource control:** schedule RAM- or CPU-bound work only with verified
   headroom. On the inspected Windows RTX 3060 Ti, one read-only snapshot
   reported 8,192 MiB total VRAM, 7,506 MiB free, and 30% GPU utilization.
   This is a momentary observation (2026-11-05), not a sustained capacity
   guarantee. OBS and VTube Studio were not running in that snapshot. Do not
   conclude STAR is ready to stream from this data.

## Concrete acceptance protocol

**A. Offline director and voice.** Compare default/no budget vs budget=5
using the same scripted, independently reviewed 20+ matched situations covering
viewer questions, gameplay comments, owner barge-ins, incidental noise and
critical gameplay. Score per-case first audible PCM, interruption stop, overlap,
grounding, dropped useful commentary, and false alarms. Pass only if human
reviewers find the paced behavior no less useful and measured critical/owner
handling stays intact; candidate must not win merely by being silent.

**B. Real nonbroadcast Windows rehearsal.** Verify OBS, avatar runtime, voice
device and a legally permitted game are genuinely available, pin process identity,
record game/voice/avatar in a private OBS file, hash the selected recording and
independently review audio, frame timing, avatar sync and gameplay outcomes.
Do not use a launched application, process existence, or a preflight report
as proof of successful speech or gameplay. Never publish without separate
broadcast permission. A missing game/avatar runtime is a blocker for an honest
end-to-end demonstration, not a reason to fabricate results.

**C. Performance trials.** Compare baseline model and CPU TTS against proposed
settings with fixed prompt hashes, seeds if supported, identical simultaneous
OBS/game load, repeated samples and p95 latency/FPS; compare response
correctness, holdout gameplay success and audio quality. Reject any optimization
that drops real game FPS below an agreed floor, produces hallucinated game
events, worsens barge-in handling, or leaks chat context between inference
slots. Do not deploy cache reuse across users without isolation testing.

**D. General capabilities.** Expand public, attributable knowledge retrieval
with review, facts with dated provenance, cross-project skill libraries for
Roblox/Blender/Rust/game mechanics, and owner-selected hobbies/art/game projects.
Keep a persistent functional self-model and consistent fictional persona;
never imply biological awareness, human biography, or real experiences STAR
did not actually have. Track completed real tasks, not fictional achievements.

## Non-goals, limitations, and rollout

No external chat action, game control, streamer broadcast or model migration is
added here. The rolling quota is opt-in and static, not a learned proactivity
policy. A future host may A/B-test budgets (e.g. 3, 5, 8 per minute) on reviewed
events; only independently measured quality and sustained hardware stability
justify changing the default. The code and synthetic tests do not prove a
speedup, human realism, game skill or speech quality.
