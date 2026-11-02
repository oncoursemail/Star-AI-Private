# Star AI — Fresh voice interruptions, real turn-taking benchmarks, realtime game intelligence and VTuber infrastructure
Date: November 2, 2026. Branch: feat/star-fresh-bargein-20261102. Parent: draft PR #896.

## What was actually built

This change includes two implemented, offline-tested pieces:

1. In optional verified-quiet mode, a 200ms-old authenticated-owner VAD
   callback no longer interrupts speech solely because a collection of old
   voice frames says an utterance had previously lasted 120ms.
   Both quiet-floor clearance and owner/guest speech decisions must use
   the most recent 75ms of trusted host time. The old opt-out behavior remains.
   A 120ms freshly observed owner utterance can still interrupt immediately.
2. New deterministic, offline benchmark
   "star/stream_endpointing_eval.py" evaluates two voice end-of-turn policies
   on independently reviewed, matched, pre-registered pause cases. It reports
   mid-turn false cutoffs, missed genuine turn ends, endpointing latency p95,
   and regressions in individual paired cases. Eligibility is only for a
   **manual, nonbroadcast rehearsal**.

Both are infrastructure: neither reads a microphone, streams, controls a
game, runs a speech model, or proves any capability has improved in live play.

## Reproduced failure and fix

Existing verified-quiet mode had a stricter 75ms recency test for deciding
that silence was clear to SPEAK. But its earlier 120ms owner-barge-in branch
executed before that test, and inherited a permissive 250ms frame freshness
window from the legacy mode.

Reproduction using four owner frames at t=100/130/160/190ms:
- At host t=190ms it requested a valid owner interruption.
- At host t=390ms — 200ms after the last audio sample — it **still**
  requested a hardware-interrupting owner yield, even with strict mode on.
- An actual StreamInterruptionHost synthetic audio epoch could be interrupted
  by a batch of callbacks arriving 200ms after capture.

Correction: require VAD frame age <=75ms in verified-quiet mode **before**
checking the owner or guest branch. When delayed, return a noninterrupting
hold with reason "voice_frame_not_recent". Keep the previous "quiet_frame_not_recent"
reason for quiet samples and do not affect hosts that opt out.

Threat model: this is a latency and freshness defense, not an identity
authentication mechanism. The host MUST independently authenticate owner voice
provenance, physically stop/flush audible PCM for a valid interruption,
and recheck stage and animation epochs. An incorrect host clock or fabricated
host attestation remains out of scope.

## Important NEW research finding: smaller turn detector can be less natural

LiveKit's publicly reproducible eot-bench scores end-of-turn policies by
**false interruption rate and response delay together**. The published English
comparison shows, at the same 600ms decision budget:

| Model | False-cutoff rate at 600ms | Mean endpoint delay at 5% false-cutoff budget |
| --- | ---: | ---: |
| LiveKit Turn Detector v1 | 4.5% | 543ms |
| LiveKit Turn Detector v1-mini | 12.1% | 1070ms |
| VAD baseline | 21.7% | 1600ms |

These are dataset-specific benchmark results, not Star measurements, and the
live CPU overhead must also be considered. They invalidate the blanket
assumption that "v1-mini" is always the best choice because it is smaller.
Test v1 versus mini versus Star's deterministic voice gate under a fixed
false-cutoff limit. Source: [LiveKit official eot-bench](https://github.com/livekit/eot-bench)
and [published English result table](https://github.com/livekit/eot-bench/blob/main/output/livekit__eot-bench-data__validation__min_silence_100ms/en/comparison/report.md).

New local evaluator deliberately separates mid-turn hesitation from real
speaker completion and rejects gaming-voice models that gain "speed" by
interrupting people or never yielding a true reply. Its guardrails include:
- At least 20 independent matched mid-turn and 20 final-turn cases.
- False cutoffs at most 5% AND no newly introduced false cutoff in a paired case.
- No missed true ends; final-turn p95 <=900ms and <=baseline p95+100ms.
- No individual true-turn latency regression >250ms.
- Different pause types, missing A/B review and fabricated out-of-window
  timestamps invalidate comparison; there is no broadcast permission.

A controlled field benchmark should later add 100-300 realistic audio turns
across gaming, Discord, distracted conversation, natural hesitation,
overlapping voices, silence and playback echo. Do not tune on the hidden
evaluation set. Never upload real viewer speech without consent.

## October 2026 voice technology: what to test, not blindly install

Kyutai Pocket TTS v4.0.0 released October 20, 2026 with 18.2M, 6.9M and
experimental 1.9M English models, each also offering a reward-tuned variant.
Release v4.0.1 on October 21 corrected pronunciation problems in sub-20M
models. These small CPU models may let Star speak without sacrificing her
8GB graphics card's rendering headroom, but quality is not guaranteed:
the smallest checkpoint may sound less expressive, especially on names,
emotion, laughter, long sentences and conversational transitions.

Proposed side-by-side qualification:
- Host-measured time to first *audible* PCM, sustained real-time factor,
  CPU p95/p99 and memory, alongside simultaneous game FPS and GPU free VRAM.
- Human-blind rating of Star's character consistency, pronunciation,
  breathing/pauses, expressive variety and emotional congruence.
- PCM gap measurements, clip restarts, cancellations and owner barge-in
  physical stop latency. Voice cloning needs permission from the voice owner.
- Prefer caching the reference voice encoding, with revocable local storage.

Primary release notes: [Kyutai Pocket TTS releases](https://github.com/kyutai-labs/pocket-tts/releases)
and [Kyutai official TTS overview](https://kyutai.org/tts/).
No model installation, audio recording or voice training occurred this run.

## Real-time intelligence for games: two clocks, not one huge brain

RealtimeBench, published October 14, 2026, presents 180 time-continuous game
tasks across six game types. It reports a slower teacher studying errors
between attempts and a fast student acting during real gameplay. Its paper
reports a particular student score improving from 13.51 to 24.19 on a 0-100
progress scale over two learning rounds. This is NOT Star's measured score.
Source: [RealtimeBench paper](https://arxiv.org/abs/2610.20665).

For Star, the proposed architecture is:

- **Fast actor (on the active gameplay clock):** scene identity, trusted game
  observation, quick policy, action whitelist, focus check, monotonic deadline,
  safe key-up, refusal when frame is stale. No live calls to a giant teacher.
- **Tactical guide (spare cycles only):** choose the next objective, annotate
  hazards, update the current finite-state goal and retrieve brief tested
  strategies. Should never monopolize game rendering or microphone handling.
- **Offline teacher (between games, not broadcasting):** review failed runs,
  propose tactics, create novel practice levels, compare with unchanged
  baseline and evaluate on unseen maps/versions. Pass only verified lessons.
- **Memory consolidation:** versioned game + objective + situation +
  provenance; short tactical notes for the fast actor, longer validated
  knowledge separately. No private player IDs, fabricated achievements,
  mixed-game memories or failed conjectures as facts.
- **General knowledge:** source-grounded retrieval with freshness/permission
  filters first; label uncertainty; periodically audit factual precision
  across science, media, language, culture, tech and game rules. Large
  context is not itself reliable reasoning.

Crucial anti-cheating requirement: a teacher must never see the holdout seeds,
validation receipts or secret independent scoring key. Demonstrate
paired progress gains, no game regressions, success on unfamiliar levels and
stable frame times **before** claiming genuine game mastery.

## Inference speed: what is promising on 8GB, what needs measurement

Official llama.cpp docs describe speculative decoding with small draft models
and EAGLE-3 adapters, alongside ngram-cache/ngram-map options. Such
optimization is workload- and hardware-sensitive: a second draft model can
consume the GPU memory that OBS and the game need.
Source: [llama.cpp speculative decoding documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).

Recommended A/B matrix, with **identical prompts and independent outcome
evaluation**, on both idle Windows and simultaneous game/VTuber workloads:
- Small reactive model, no speculation, fixed context and cache warm/cold.
- Ngram speculative decoding without another loaded model.
- Draft-model speculation where RAM/VRAM fits; compare accepted draft tokens,
  effective generated tokens per second and p95 wall-clock latency.
- CPU-only speech versus GPU speech; CPU vs GPU fast actor; offloading
  a teacher to a second PC when available.
- Bounded short-term context with verified knowledge retrieval versus
  indiscriminately expanding the KV cache.
- Capture CPU package usage, RAM, GPU VRAM, OBS render/output loss, game
  frametime p95/p99, TTFT, time to first audible sound, answer quality and
  scene-action deadline misses. Reject any speed tweak that makes the whole
  experience worse.

November 2 **read-only Windows Main snapshot**, not a performance claim:
RTX 3060 Ti 8192MiB, 7535MiB used, 490MiB free, 18% instantaneous GPU load;
Ryzen 5 5500; 31.9GB RAM; llama-server observed, but no obs64 or VTubeStudio
process found. This PC is not currently ready to add a full GPU-consuming
game+OBS+avatar stack without reclaiming headroom or shifting workloads.
Do not restart the inference service or delete models as a shortcut.

A technically correct, 1000-token-per-second answer that arrives after the
game frame deadline is not helpful. Track **end-to-end useful outcome per
second** and absolute p95 response delay, not just peak generation speed.

## Robust game creation: observe before editing, test after building

Roblox's OpenGameEval paper (October 2026) reports 84 curated core tasks,
13 frontier models and 16 attempts per task. It measures exploration and
success inside actual stateful Roblox Studio sessions. Across fixed task/model
comparisons, inspecting every relevant object before an edit was associated
with 13.4 percentage points higher success on scene-only tasks and 9.8 points
on script-only tasks than inspecting none. These are reported observational
benchmarks, NOT Star measurements.
Sources: [OpenGameEval paper](https://arxiv.org/abs/2610.02563),
[open benchmark repo](https://github.com/Roblox/open-game-eval).

Applied workflow for Star's Roblox game creator:
1. Collect a structured scene inventory, relevant scripts, connections,
   remote events, constraints, dependencies and screenshot reference.
2. Decompose goals into geometry, behavior, animation, VFX, audio, UI,
   accessibility and networking; use appropriate tools for each discipline.
3. Generate several candidate changes in isolated, restorable sandboxes,
   with scene-diff provenance and no cross-candidate asset contamination.
4. Run Luau analysis, formatting, unit tests, geometry/collision checks,
   renderer-frame screenshot inspections and multiplayer simulated playtests.
5. Prefer the passing candidate with independently checked visuals and
   gameplay, not the candidate with the longest chain of thought.
6. On failures, inspect traces, produce minimal repairs, and retest the
   exact defect plus held-out scenarios. Store validated patterns for recall.

Roblox reports Studio's built-in MCP server and playtest automation since
March/April 2026. StudioTestService can launch simulated client sessions and
test join/leave events, not merely syntax.
Sources: [Roblox April 15 announcement](https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic),
[StudioTestService docs](https://create.roblox.com/docs/reference/engine/classes/StudioTestService).
A live Windows Studio session was NOT exercised in this update.

## More believable Star VTuber: executable behavior, not fictional claims

Star's identity, ongoing interests and relationships are product/persona
features. Believability requires consistent, grounded behavior rather than
asserting she is literally a human with real lived experiences.

Build an event-sourced expressive director mapping: (a) game event
verified from current scene, (b) emotion and arousal appropriate to event,
(c) voice prosody and speech content, (d) mouth from actually played PCM
samples, (e) gaze tied to current verified attention, (f) body/hair reactions,
(g) quiet listening and turn transitions. Keep synchronized monotonically
with epoch invalidation on game switches and physical audio-stop acknowledgments.
Never animate based on PCM merely queued but not heard.

VTube Studio's plugin API supports custom model parameters through trusted
plugins; these should not be exposed to raw viewer chat or arbitrary model
tool calls. Reference: [VTube Studio plugin overview](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins).
For Star+Astro+Amber, distinct scene identity, separate audio channels, and
consensual co-character behavior should prevent voices/poses being swapped.

A rigorous nonbroadcast Windows rehearsal should score: real-time FPS,
CPU/GPU headroom, OBS lost render/output frames, actual mouth-to-audio sync,
talk-over false cutoffs, human-rated voice naturalness, grounded reaction
accuracy, scene-transition mistakes, interruptions and long-session recovery.

## Practical priority order and proof of success

P0: Connect real trusted capture timestamps, voice-frame delivery time,
    actual PCM playback stop acknowledgement and avatar epoch reset on Windows
    in a nonbroadcast rehearsal. Test injected 75/76/200ms VAD delivery delays
    at the host boundary. Do not enable public streaming yet.
P1: Run independently reviewed matched endpointing experiments, including
    LiveKit v1, v1-mini and the local gate, under a declared false-cutoff
    budget. Compare actual total audio latency and CPU usage.
P1: Recover VRAM headroom or split game/inference jobs across PCs; collect
    a 30-minute sustained stream-ready resource window with no uncontrolled
    restarts, freezes, clip underruns or stale speech.
P2: Add real-game replay traces and teacher/student study loops; hold out maps,
    apply practice budgets and require signed independent paired evaluations.
P2: Put OpenGameEval + Studio's playtest loop into a repeatable Windows
    test lane; distinguish script success, scene success and visual quality.
P3: Improve general knowledge through curated source-backed retrieval and
    difficult cross-domain evaluations; promote only measured gains.

**Pass criteria** are independently witnessed end-to-end, not just
passing Python tests: stale VAD must never interrupt, fresh owner input must
still work; voice false cutoffs <= preregistered budget, p95 response must
not regress; uninterrupted game/UI/avatar/audio for a full nonbroadcast
session; actual gameplay achievements on unseen tasks; reliable rollback.

## Reproduce locally and limitations

- Run new tests using Python 3.11+ with pytest:
  python -m pytest -q tests/test_stream_fresh_barge_in.py tests/test_stream_endpointing_eval.py tests/test_stream_verified_quiet_floor.py
- Run Ruff and Python compilation for modified modules; also stream suite.
- No audio, OBS, network, gameplay, microphone, camera or model was operated
  during these offline code tests.
- Synthetic unit-test eligibility must NEVER be called a real streaming,
  intelligence, gaming or naturalness improvement without field evidence.
