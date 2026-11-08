# STAR — Preplay speech safety, gaming intelligence, speed and VTuber research
**2026-11-08 | Experimental draft | No live audio, game control or streaming was initiated.**

## Actual code delivered in this iteration

`star/stream_preplay_gate.py` composes three already-existing but independently
operated systems: `StreamDirector` (evidence-grounded, pace-limited candidate
speech), `TurnTakingGate` (owner/guest/echo VAD advice), and
`StreamLoadGovernor` (trusted GPU/OBS/game/TTS interval measurements).

A **two-phase preplay review** allows candidate speech only when the VAD says
speak, the host is not already speaking, gameplay is not critical (except
qualified danger cues), and the game/stream load is healthy. Revalidation
checks those conditions again with a 250 ms default plan lifetime before
any separately authorized playout. Changes to VAD or OBS pressure while
speech is being synthesized now block the candidate. An authenticated
owner's sustained interruption produces a *physical-stop request* for
the existing authorized audio host; the gate does not stop hardware.

The final host receipt is single-use; claimed audible delivery before
revalidation cannot mark the director cue spoken. A boolean audio receipt
is only as trustworthy as the independent real PCM observer producing
it. **This is not integrated into the production output host** and does not
activate voice, OBS, gaming, microphone or a public broadcast. Review
`tests/test_stream_preplay_gate.py` for offline adversarial checks.

## Why this work matters

Fast first-token timings alone do not make natural conversations.
The expensive failure is generating an answer to a stale video/chat moment,
continuing to speak while the owner interrupts, or consuming GPU capacity
while rendering a game. A response gate must synchronize *three different
lifetimes*: conversational turn, recently observed game state, and fresh
physical-output resources. If any becomes stale, silence is the safe default.

Proact-VL (March 3, 2026) specifically studies whether a live gaming
companion should speak, not merely what it should say. STAR should measure
appropriately withheld commentary and user interruption quality as explicit
success criteria, rather than maximizing words per minute.

Source: https://arxiv.org/abs/2603.03447

## Game learning — move beyond benchmark descriptions

Gym-Anything-RT (submitted October 27, 2026) evaluates 100 realtime
minigames as well as slowed/paused variants. The central lesson is to
separate **reactive** control (bounded perception-to-action latency)
from **tactical** planning and **offline** rehearsal. STAR already
possesses deadline routing, a skill bank, independent holdout reservations,
and a scenario failure atlas; the next step is to connect them to
verified noncompetitive practice games and report completed, independently
measured trials rather than adding only more evaluators.

Proposed reproducible protocol:
1. Record authorized non-public game captures, host monotonic action
   deadlines, engine acknowledgement, process load and actual outcome.
2. Reserve hidden held-out cases **before** running any trials, keeping
   holdout identities inaccessible to the practice policy.
3. Train/practice with a small reactive policy while the deep teacher
   plans only between attempts or on a spare device.
4. Compare baseline and candidate on the same preregistered task
   distribution; use unseen seeds/games for final independent assessment.
5. Publish wins, failures, missed deadlines, and resource consumption
   together. Never label an offline unit-test improvement as game mastery.

Source: https://arxiv.org/abs/2610.37567

## Roblox creation — inspect, build, playtest, repair, retest

Roblox OpenGameEval (October 1, 2026) studies reproducible Studio
sessions with executable edit- and play-mode checks. Inspection of
relevant objects before changes correlates with better task success.
STAR should enforce a structured sequence: inventory current hierarchy,
derive acceptance tests, edit via official Studio MCP, run multiple-client
playtest checks, review Luau and performance diagnostics, and only preserve
verified results. Use isolated test places, not live player projects.

Sources:
- https://github.com/Roblox/open-game-eval
- https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md

## Faster intelligence within 8 GB VRAM

The connected development setup has previously reported 8 GB GPUs.
Treat *free VRAM while OBS, the avatar and game are active* as a
hard measured constraint, not a generic model-size claim. Evaluate:
- Small reactive models with strict scene deadlines; no slow teacher in
  the active frame loop.
- Model-loading costs, context/KV-cache memory, prompt caching and
  time-to-first-audible PCM, not only decode tokens/s.
- Low-cost CPU speech when independently shown to preserve the game
  frame deadline without unacceptable speech lag.
- Speculative decoding *only if* an identical-task A/B test beats the
  baseline under the actual 8 GB GPU + OBS workload. Some model/draft
  pairs and content types regress.
- Three-slot workload priority: game/render > owner speech/physical
  interruption > optional commentary/background study.
- When disk, VRAM or OBS telemetry is missing, reject optional work;
  never assume spare capacity from a stale sample.

Use llama.cpp SPEED-Bench to compare same-model, same-quantization
throughput and token acceptance, then verify performance with a timed
real game + OBS rehearsal. Do not infer any speed improvement from
this Python-only review code.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/issues/23052

## Human-like without deceptive human identity

A natural VTuber needs listening, pauses, context-appropriate jokes,
expressive but restrained animation, consistent character memory,
emotionally legible *expression*, and authentic accounts of what happened
in games. No claim of actual subjective feelings or human identity is
necessary. STAR should clearly remain an AI persona.

Proposed independent rehearsal scorecard:
- Owner interruption -> **actual output PCM stop** p95, measured in
  milliseconds with separate physical evidence.
- Mean and p95 event -> first audible response; unexpected silent
  pauses during speech; false interruptions on noise or echo.
- Percentage of critical-gameplay windows with **no** unnecessary
  speech; gameplay success rate on fresh tasks; speech groundedness
  judged against video/audio evidence.
- Game p95 frame time, OBS render/encoder/network loss, actual VRAM
  allocation and local speech/inference latency.
- Public safety: moderation, opt-in social interaction, emergency
  shutdown, independent capture/broadcast permission. No key exposure.

## Operational observation

The Linux `starai` machine reported roughly **14 GB free and 94% disk
usage** during this run. This is an instantaneous filesystem observation,
not a trend. Avoid speculative bulk model downloads or duplicate clone
trees there until safe capacity is verified. No cleanup was performed.

## Implementation boundaries and next verification

This change does **not** improve base-model weights, enable live
streaming, or certify human-level gameplay. It supplies a testable
composition point for *fresh voice + current game + OBS pressure*.
The next high-value Windows milestone is a **private, nonbroadcast,
explicitly authorized** rehearsal linking the final preplay check to
real PCM playout and real game/OBS telemetry, followed by blind outcome
review. Unverified integrations must remain off by default.
