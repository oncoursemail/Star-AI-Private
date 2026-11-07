# STAR — Paired local inference evidence, real-time gaming and natural VTuber roadmap
**Research and engineering update: 2026-11-07 (America/Chicago)**

## What actually shipped in this draft

Added `star/inference_stream_paired_gate.py`, an **offline** gate for sanitized
`star/inference_stream_benchmark.py` reports, and regression tests. Unlike
another speculative "faster model" recommendation, this answers the critical
question **whether a change starts *speakable* replies faster without
dropping turns or hiding slow complete responses**.

The input contains no model responses, chats, images, microphones, accounts
or PIDs. Each preselected baseline/candidate pair must have identical
synthetic input hash, request count, parallelism and workload mode, with an
operator-supplied identical target-model digest and machine-profile digest.
No workload may be pooled across different hardware or models. All observed
requests must complete with speakable text, without canary mismatches;
incomplete attempts stay in the denominator. Candidate dropped turns or
pronounced pairwise regressions fail even when successful replies look fast.
The default lower bound on bootstrap-mean speakable p95 improvement is **40
ms**, with six complete pairs required; the response-completion p95 cannot
regress by more than 100 ms. A repeated identical prompt is a cache diagnostic
and cannot promote an experiment. Thresholds are **engineering heuristics**,
not claims about statistical power or human perception.

CLI from a source checkout (offline, no API calls):
```bash
python -m star.inference_stream_paired_gate private-paired-evidence.json
```
JSON shape (use actual output from `benchmark_stream_startup`, not made-up
performance numbers):
```json
{
  "pairs": [
    {
      "pair_id": "opaque-01",
      "target_model_sha256": "<64 lowercase hex of locally verified SAME target model>",
      "host_profile_sha256": "<64 lowercase hex of host-controlled hardware/settings profile>",
      "baseline": {"...": "actual benchmark_stream_startup summary"},
      "candidate": {"...": "actual benchmark_stream_startup summary"}
    }
  ]
}
```
Build at least six pre-registered pairs; the ellipses above describe schema
rather than a runnable JSON example. To avoid reporting biased speedups, the
operator must randomize or alternate AB/BA measurement order, preserve
clock/temperature/concurrency/context settings and **not select the six best
runs**. The digest fields are metadata, not cryptographic host attestation;
independent signed receipt and GPU/OBS evidence are separate requirements.
The output is only `eligible_for_private_pilot`, `regressed`, or
`inconclusive`; it never changes the active model. Failure to parse or
validate evidence produces `invalid_evidence` and a nonzero exit code.
Do not mistake first-speakable model text for actual first audible PCM.

## Research findings with measurable engineering implications

### 1. A clever model that responds too late cannot play a live game

Aggarwal and Welleck, *Gym-Anything-RT* (2026-10-27), describe 100 real-time
minigames and large discrepancies between environments advancing during
inference and environments paused for the same agent.
Source: https://arxiv.org/abs/2610.37567

Tang et al., *Realtime-Bench* (2026-10-15), similarly distinguish wall,
paused and token-clock settings and show that decision quality and
latency-aware action timing must be evaluated jointly.
Source: https://arxiv.org/abs/2610.22155

**STAR experiment:** for each independently reset seed, record the
authoritative game-world clock at observation, inference finish and OS
acknowledgment (not just desktop wall time), action deadline, selected
action, and objectively scored result. Compare a fast reactive action lane
to a deeper reasoner **on the same held-out levels**. Reward *verified
progress before the deadline*, not length of reasoning or action count.
Existing modules `game_live_clock_benchmark.py`,
`game_deadline_router.py`, `game_realtime_loop.py` and signed game-state
witnesses provide much of this foundation. The next challenge is
instrumenting a genuine supported Windows game, not another synthetic pass.

### 2. Faster token generation is not faster conversation

llama.cpp's SPEED-Bench measures prompt/decode throughput, end-to-end
latency, and speculative draft acceptance and compares matched baseline
and speculative runs.
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**STAR experiment:** first compare local mixed synthetic input and canary
sequences on a *single owner-approved idle model server*. Measure
first-visible token, first SentenceChunker speakable phrase, complete
response, per-run failure rates, VRAM and GPU sampling. Compare variants
of prompt caching, n-gram speculation, draft-model speculation and
context limits only when they fit the **actual concurrent GPU headroom**.
A second, separate gate measures first **audible** sound, avatar pose
alignment and game frame p99 while OBS records locally. Faster decoder TPS
does not compensate for new FPS hitches, a false game claim or 1.5-second
synthesis startup.

### 3. Humanlike streaming means conversational timing and grounded personality

*Proact-VL*, ICML 2026, studies proactive gaming companions and precisely
**when** to comment; the source evaluation includes commentary, co-commentary
and user guidance:
https://proceedings.mlr.press/v306/yan26c.html

NVIDIA's *DyaPlex*, June 2026, investigates streaming full-duplex speech
and synchronized motion, rather than waiting for a rigid reply cycle:
https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

Kyutai's Pocket TTS offers an on-CPU candidate to test when GPU memory is
contended, but needs real **first audible** and quality experiments rather
than an assumption of lower latency:
https://kyutai.org/tts/

**STAR implementation sequence:**

1. Build a host-observed audio/visual turn-taking state machine:
   `listening -> thinking -> speaking -> yielding`, with optional brief
   acknowledgment, overlapping audio playback prevention, and immediate
   owner mute. Speech may be interrupted without dropping verified game
   state or causing a stuck avatar gesture.
2. Use source-verified game milestones and moderated viewer questions,
   with a silence budget during critical gameplay. Announce **what the
   host observed**, not invented victories, emotions, viewers or personal
   experiences. State openly that Star is an AI VTuber.
3. Maintain a durable, consent-aware personal-memory index with timestamp,
   source and confidence for prior collaboration. Keep fictional persona
   preferences separate from verified memories; expire uncertain facts and
   make deletion possible. Never store private chat by default.
4. Give the avatar short anticipatory blinks, gaze changes, idle breathing
   and bounded reactions tied to output timestamps. Report misalignment
   and stop expressive output on stream stop, rather than fabricating a
   prerecorded human performance.
5. Independently score interrupt-to-silence delay, onset latency, overlap
   rate, OBS dropped frames, grounded event coverage and erroneous claims
   using private recordings, owner review and volunteer feedback. Set
   thresholds from owner acceptance tests, not invented "human" labels.

A natural persona is possible without suggesting that STAR is actually a
human, possesses human consciousness, or shares human relationships.

### 4. General intelligence must be evaluated, not self-declared

Build a **held-out cross-domain curriculum**: novel mechanic discovery,
route planning, tool use, Roblox Luau, Rust debugging, 3D/Blender,
documentation retrieval, grounded summarization, PC maintenance and
creative design. Require unit/game tests plus visual human review for
high-stakes creative outputs. Check **transfer to new environments**, not
merely reruns of practiced levels. Keep training and validation isolated;
never feed withheld answers back into `gameplay_skill_bank`. Avoid
external actions and spending without appropriate owner authority.

For Roblox specifically, Roblox's *OpenGameEval* uses executable scene and
simulated play checks, emphasizing inspection before modification:
https://github.com/Roblox/open-game-eval

Roblox's **2026-11-04 Studio MCP update** expanded permission-controlled
Open Cloud access for asset importing and game management:
https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
https://create.roblox.com/docs/studio/mcp-open-cloud

**STAR experiment:** clone a disposable unpublished/test game into a
separate approved testing environment; inspect objects, propose a patch,
run Luau lint/analyzer, verify geometry + playtest goals, and retain only
independently passing repairs. Read-only MCP first. Asset uploads, game
publication, player impacts and monetary API calls still require their
proper owner permissions and explicit approval. Never test datastore
writes against production player data.

## Prioritized engineering plan

| Priority | Integration | Evidence before enabling |
|---|---|---|
| P0 | Real Windows host: connect existing GPU telemetry/optional worker control to a **disposable**, owner-configured model worker | Live bounded GPU sample, Job Object process-tree exit, no orphan lease, safe stop under pressure |
| P0 | Private, **non-broadcast** OBS + game + speech + avatar rehearsal | Real game-world progress, input acknowledgment, first audible PCM, rig/OBS sync, frame p99, memory and abort test |
| P1 | Use this new paired inference gate on baseline vs candidate llama.cpp engine flags | >=6 AB/BA matched pairs, clean completion/speakable coverage, no tail regressions; manual acceptance only |
| P1 | Challenge-based game learning on unseen seeds | Held-out score, deadline misses, actions per success, paired CI and failure analysis |
| P1 | Natural streamer turn-taking with viewer-question focus and safe barge-in | Owner-reviewed latency, grounded statements and conversation flow; no fabricated achievements |
| P2 | Game creator loop (Roblox, then Blender/Rust and other engines) | Executable tests + scene checks + measured improvement on unfamiliar tasks |
| P2 | Retrieval and tool-use generalist with provenance, calibration and user-reviewable memory | Factuality/skill tests, documented uncertainties and safe rollback |

**Hard boundaries:** No public stream was started. No game win-rate,
language-model quality or neural speed increase is claimed by this PR.
The new component evaluates externally collected synthetic measurements;
it has not deployed a model or connected production Windows services.
All features default to opt-in or manual review. The main branch and
installed Windows release do not acquire this draft automatically.
