# STAR performance and embodied-streaming R&D — 2026-10-25

Status: engineering research + a **disabled-by-default experimental llama.cpp startup option**.
This is not evidence of faster inference, higher base-model intelligence, improved Roblox game
quality, live gameplay or a working public VTuber stream.

## Why this change, rather than another isolated simulation?

STAR already has request-prefix stability, a model server, the offline first-token benchmark
(`scripts/measure_first_token.py`), Studio MCP access behind owner permissions, and several
unmerged proposals for real-time event triage, game outcomes and stream memories. The missing
piece for inference experimentation was a **bounded, real server invocation option** that can
be switched on in a controlled test and switched back off without model changes.

This PR extends `Runtime.arguments`, `Runtime.router_arguments`, `Runtime.start`, and
`Runtime.start_router` with `speculative="ngram-simple"` and `max_draft_tokens=16`.
All existing callers remain unchanged. The default is **off**. This mode uses previously
generated n-grams to suggest next-token sequences that llama.cpp verifies. It does not
load a second model, does not use a hosted service, and cannot grant game/OBS privileges.

This is a Python **caller-level opt-in** for controlled experiments, not a settings/UI toggle.
A maintainer must deliberately pass it to the runtime and use a llama.cpp build exposing
these arguments. An older server can fail at startup rather than silently falling back.

## 1. Grounded inference-performance plan

### Decoding versus prompt processing

- **Prompt-prefill caching:** repeated system prompts and history prefixes can skip work
  when the slot/cache recognizes them. This already has supporting code in
  `star/context_layout.py` and `star.providers`; do not shuffle their stable prefixes.
  vLLM's automatic prefix caching documentation explicitly says it accelerates prefill,
  not output-token decoding. STAR's own engine is llama.cpp, so do **not** copy a vLLM
  configuration flag into a llama-server command.
- **Speculative decoding:** ngram-simple retrieves already-observed token patterns and
  proposes a batch, which the target model can verify. Text/code with repetition may
  benefit; short answers, dissimilar prompts or VRAM/CPU contention can be slower.
  The controlled experiment should start with 16 draft tokens, then compare 8/32.
  This does not make model weights more intelligent.
- **Additional draft models / EAGLE-3 / DFlash:** possible future tests only after
  checkpoint-license, tokenizer/model compatibility, RAM/VRAM and official engine-version
  verification. An arbitrary small GGUF is not automatically a compatible drafter.
- **Inference layout:** preserve one warm active model before attempting concurrent
  models on an 8 GB card. Keep GPU/encoder/OBS headroom before using GPU acceleration
  or running video-generation workloads simultaneously.

### Required acceptance experiment

Use the existing `scripts/measure_first_token.py` against **the same pinned llama.cpp
build and model**, first baseline, then experimental mode, with all other settings fixed.
Run both orders (A→B and B→A), at least five independent repetitions each, for chat
and code/Roblox tasks. Use `--phases chat,resume`, a fixed prompt set and equal token
budgets. Do not run concurrent server workloads while benchmarking; record CPU/GPU
utilization, model residency and free VRAM with a trusted host tool. Do not record any
private gameplay frame or user's audio.

Report **median and tail (p95) time-to-first-visible-token, generated tokens/sec,
end-to-end latency, error rate and peak VRAM**. Repeated prompt-cache hits must
be separated from cold-cache starts. Small samples make p95 noisy, so prefer
at least 20 trials per condition for tail latency, then repeat on both computers.

Quality gate: assess blinded, independently scored Luau/regression prompts and
the untouched blind holdout from the existing evaluation process. Do not edit the
holdout fixtures. Accept only when both speed and task quality are no worse within
predeclared tolerances. Choose a named hardware/model combination, never assert a
universal speedup. Roll back by omitting `speculative` or setting it to `off`.

**Critical guardrail:** the server's synthetic-acceptance flags benchmark an artificial
verification path and can generate invalid outputs. They must NOT be used for real
quality or accuracy measurements.

## 2. An architecture that can actually play and learn games

1. **Instrumented, consented game adapter.** Receive versioned frames, a game/session
   ID, monotonic timestamps, observable scene entities and a finite action inventory.
   Keep actuation behind an out-of-model host permission. Initially use one owner-owned,
   unpublished Roblox Studio test place and the built-in Studio MCP tools.
2. **State estimation with uncertainty.** Maintain what is *seen* separately from
   what is *assumed*. Reject stale frames and coordinate transforms, missing walls,
   severe occlusion, mismatched scene scales, and unexplained collision states.
   Perception confidence is not a substitute for collision/geometry verification.
3. **Short-horizon world model.** Predict the next state, use conservative planning
   under uncertainty, take one bounded action, and compare the observed outcome.
   If an expected door/ladder/wall is absent, stop or re-localize. Never repeatedly
   run a long unverified macro on a live account.
4. **Reusable skills.** Store a skill's game version, entry conditions, steps,
   success predicate, failure conditions and evidence. Prefer retrieval of a verified
   skill to repeatedly re-prompting the language model. Voyager's open-ended skill
   library and iterative feedback are useful precedents, not directly pluggable
   into Roblox.
5. **Independent game tests.** Compare new and baseline policies on unseen seeds,
   with complete episodes and held-out metrics. Practice tasks are not holdout tasks.
   Record wins, objective completion, deaths, collision errors, latency, intervention
   counts and confidence intervals; use owner review to adopt changes.
6. **Safe interaction envelope.** Disable live matchmaking, publishing,
   unrestricted scripts and keyboard/mouse control unless the owner has configured
   and approved the exact capability. Use stop switches, per-session action limits,
   and full reversibility for Studio edits.

This is how to turn the prior navigation/closed-loop/skill-promotion PRs into a single
evaluated system. Their "trusted_host" method booleans are **not authentication**;
the actual tool bridge must independently authenticate the source and enforce scope.

## 3. A believable, lively VTuber without fabricated human memories

The humanlike effect comes from **timing, continuity and embodied feedback**, not from
telling viewers STAR is a biological person.

**Realtime direction:** lightweight VAD/listening, incremental speech recognition,
intent selection, a speech generator with interleaved playback, a separate low-rate
game-event stream, and an avatar-animation scheduler. Make "react to damage /
celebrate win / thank a viewer / ignore low-value spam / be quiet during a boss"
different behavior policies, each interruptible. Do not make every event produce speech.

**Speaking:** aim for first audible acknowledgement while longer answers continue;
measure end-to-end mic-to-speaker and interruption-to-stop, not merely model TTFT.
Natural hesitations and laughter can add expressiveness but should be contextual, not
randomly inserted every sentence. Correct pronunciation and consistently placed
pauses matter more than artificial filler.

**Avatar:** align phonemes/visemes with **audio playback**, not request generation;
generate gaze, blinks, breath, body settle, head turns, hair secondary dynamics and
ear/tail physics with an accessibility motion-reduction option. Animation instructions
must be cancelled when playback is cancelled. The owner-approved Star chibi identity
should remain consistent across normal, cat and puppy modes.

**Stream continuity:** preserve verified in-session events, goals, running jokes,
and a compact approved personality profile. NEVER pretend to have real childhood
memories, physical experiences, private friendships or events that were not observed.
She can tell fictional character lore if it is presented as fiction and can disclose
that she is an AI when relevant. Provenance, privacy, viewer consent and deletion
controls matter more than storing full raw chats.

**Integration and QA:** controlled OBS/VTube Studio adapters should expose only
approved scenes/triggers and never embed auth tokens in Git. A rehearsal with dummy
events, synthetic chat and pre-rendered audio is required before live streaming.
Test subtitles, audio sync, dropped frames, interruption cancelation, repetitive
speech, inappropriate praise after failed attempts, and overuse of sound effects.
NVIDIA's DyaPlex illustrates joint full-duplex speech/motion research; it is not
included, licensed or integrated by this PR.

## 4. General knowledge, judgment and game creation

STAR can increase **task capability** without retraining model weights:

- Build a local knowledge index of allowed sources with URL/author/revision,
  retrieval timestamp, licensing status and per-fact confidence. Verify facts
  against source text rather than accumulating unsupported "lessons".
- Use a request-level tool/model router: fast local model for simple chat, precise
  context retrieval for niche facts, slower verified code/build mode for geometry,
  Luau, game economy, VFX or animation. Compare costs/quality rather than
  simply routing every request to the biggest model.
- For game construction, generate a semantic scene manifest (room, floor, walls,
  openings, attachments, prop sockets, collision/visibility constraints).
  Check missing walls, wrong pivots, z-fighting, floating objects, overlapping
  props, min passage clearance, texture scale, lighting and viewport quality.
  Evaluate against real Studio captures and measured playtests, not only prose.
- Model quality improvement requires actual held-out wins. Expose failures and
  regressions; keep self-generated data separate from ground truth. Train only
  with appropriate license, consent, compute budget, human review and explicit
  owner permission. Code/reflection-based learning does not imply consciousness.

## 5. Two-machine production readiness and deployment gates

- **Interactive computer:** reserve GPU/encoder capacity for the game, avatar,
  renderer, capture, TTS/ASR and one local fast model if feasible. When OBS
  drops frames, voice underruns increase or the game FPS falls below an owner's
  calibrated floor, pause optional background work and lower observation rate.
- **STAR Server:** searchable knowledge, offline Luau/unit tests, long research,
  queued game-skill experiments and slow model tasks. Do not put latency-critical
  reflexes behind an unreliable network hop.
- **Brain 2 / authorized Studio:** owner-controlled game workspace, verified
  movement, geometry acceptance, screenshot reviews and rollback. No accidental
  live-game or public publishing permissions.
- **Operations:** isolated process trees, bounded queues with stale-work dropping,
  idempotent retry rules, health checks, local-only secrets, and explicit disable
  defaults. A GPU OOM or model reload must not crash the game or leave stale
  input pressed.
- **Release gate:** pin model/build hashes, run full Python and React CI, run 2026
  Studio native smoke tests and visual review, confirm safety/privacy approval,
  and collect real FPS, VRAM, TTFT, speech latency and episode-success evidence.

## Implementation inventory in this PR

- `star/local_runtime.py`: strictly validated optional n-gram inference flags for
  single-model and model-router processes (no shell, remains bound to loopback).
- `tests/test_speculative_runtime.py`: offline checks for default-off behavior,
  allowlisting, integer bounds, command construction and subprocess propagation.
- This research/acceptance document. **No hardware benchmark results** are claimed.

## Primary references (checked 2026-10-25)

1. llama.cpp, *Speculative Decoding* (examples, n-gram mode, flags, and SPEED-Bench):
   https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
2. vLLM, *Automatic Prefix Caching* (cache mechanism and prefill-only limits):
   https://docs.vllm.ai/en/latest/design/prefix_caching/
3. NVIDIA Research, *DyaPlex: Full-Duplex Speech-Motion Model for Dyadic Interaction*
   (June 2026): https://research.nvidia.com/labs/amri/projects/DyaPlex/
4. Voyager research, *An Open-Ended Embodied Agent with Large Language Models*:
   https://arxiv.org/abs/2305.16291
5. Roblox, *Studio built-in MCP server and playtest automation* (March 5, 2026):
   https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
6. Roblox official plugin, supported native Studio MCP commands:
   https://github.com/Roblox/roblox-studio-agent-plugin

No component above was downloaded, trained, broadcast or deployed as a result of
writing this document.
