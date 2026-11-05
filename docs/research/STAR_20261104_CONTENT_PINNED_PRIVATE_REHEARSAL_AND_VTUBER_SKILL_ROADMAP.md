# STAR AI — content-pinned private VTuber rehearsal and intelligence/game research
Research date: November 4, 2026. Status: reviewed concept + implementation proposal; no broadcast or deployment.

## Verified infrastructure gap and implementation

The prior private rehearsal CLI could check recorded video/audio decodability and optionally
check mouth-to-audio synchronization. Its inode/size/time fingerprint checks could not
show that a selected recording matched a content fingerprint retained by a separately
trusted host. The OBS recording duration and byte counters also cannot identify the
finished media file actually inspected.

This patch adds an OPTIONAL SHA-256 commitment to the stopped private recording:
- Obtain the finished clip's SHA-256 from an independent trusted host/operator AFTER
  OBS stops and BEFORE selecting/evaluating it; retain the commitment outside the
  evaluator's authority. A caller calculating the hash after evaluation provides no
  independent provenance evidence.
- The CLI accepts 64 hexadecimal digits (uppercase/lowercase). It checks SHA-256 with
  bounded 1-MiB reads before and after the decoder/mouth-synchronization stages and
  rejects mismatches, invalid syntax and post-selection byte modification.
- SHA verification is skipped when no commitment is provided to avoid extra I/O.
  Reports contain only media_sha256_precommit_matched: true/false; no digest, path,
  personal speech, frames or transcript are persisted.
- This verifies byte equality to a prior known value, NOT true OBS provenance,
  actual gameplay, Star speech identity, an authorized broadcast, or human-likeness.
  Those are separately attested by independent host/owner evidence.

A separate prerequisite fix was committed directly to the preceding PR #979:
the Twitch EventSub ingress test incorrectly forbade the literal digits 789
inside a random SHA-256 pseudonym. Any random digest can contain those digits.
The corrected test validates the twv_ plus 32-lowercase-hex representation and
that the complete pseudonym differs from the raw user ID. CI must rerun.

## Exact private Windows acceptance plan (not performed by this patch)

1. Obtain owner authorization for a SHORT LOCAL RECORDING. Disable broadcasts.
2. Have actual game + authorized input, a real Star inference worker, synthesized
   isolated Star voice, live avatar and OBS running. Capture at least one authentic
   gameplay action and a matching spoken reaction with synchronized mouth animation.
3. Observe sustained GPU VRAM headroom, p50/p95 game frame time, first model token,
   actual first audible phoneme, OBS render/encode drops, recording bytes and duration.
4. Stop OBS recording; independently record the selected file's SHA-256 before running
   the evaluation. On Windows, Get-FileHash -Algorithm SHA256 is a suitable local
   tool. Retain this value in an operator-controlled record, outside the model.
5. Run python -m star.stream_private_rehearsal_audit_cli with --recording,
   --allowed-root, --owner-approved, --recording-stopped, --broadcast-inactive,
   --expected-media-sha256 and, when independently verified, the optional
   closed/open calibration stills, isolated audio declarations and mouth ROI.
6. Inspect the actual decoded result: confirm Star really played, her voice is
   audible and hers, avatar mouth matches audible speech, the event/commentary
   pair is valid, gameplay remains smooth and no private player data leaked.
7. Keep private/review-only. Public broadcast and game publishing require
   independent authorization gates.

Acceptance metrics: zero false success on wrong hash, altered bytes or missing
consent; no output leak; audible voice lag and mouth sync; p95 game frame times;
captured voice/visual identity; reproducible held-out game success, failures and
interventions. Do NOT label FFmpeg decode or hash success as live streaming success.

## Higher intelligence, faster actual decisions

Split a latency-critical game loop, a fast conversational voice loop, and a slower
tool-reasoning, memory-retrieval and software-building loop. Give the speech model
a trusted action/state digest from the slower agent, not an unverified narrative.
TalkAct investigates this fast/slow separation, but its reported latency gains are
not STAR measurements. Source: https://github.com/19PINE-AI/TalkAct

For local 8-GB GPUs compare matched correctness sets with different quantization,
context lengths, prompt caching, GPU offload, batch size and speculative decoding.
Bench during gaming/OBS load rather than at an idle desktop. The official llama.cpp
SPEED-Bench describes category latency, throughput and draft acceptance for
speculative modes. Slower draft configurations can lose performance; no general
speed or intelligence claims are made without on-device A/B evidence.
Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

## Stronger game playing and autonomous Roblox creation

Use a progress curriculum across movement, platforming, navigation, combat
timing, object interactions, trading/inventory, puzzles, team communication
and recovery from errors. Capture verified state/action/outcome observations;
test on random unseen levels and different game mechanics to avoid overfitting.
Score unseen completion rate, time, interventions, deaths, input/controller
failures and skill transfer separately. OpenAI's Procgen demonstrates that
trained-game competence may not generalize without diverse environments.
Source: https://openai.com/index/procgen-benchmark/

For game development, inspect DataModel and code BEFORE editing, then write Luau,
lint, playtest in a private authorized Studio sandbox, examine visual output,
and verify resulting scene and game interactions. The native Roblox Studio MCP
server supports playtesting; April 2026 Playtest Agent beta adds scenarios.
OpenGameEval benchmarks stateful Roblox edit and playtest success with executable
checks. None of this proves STAR already plays or builds games autonomously.
Sources:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- https://arxiv.org/abs/2610.02563

## An entertaining, natural, honest AI VTuber

The research-backed direction is learning WHEN to speak, not just WHAT to say.
Proact-VL studies low-latency video understanding, proactive commentary and
appropriate silence in solo commentary, co-commentary and guidance.
Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

Recommended integrations, all pending actual playback and review:
- State-aware attention: short game-grounded reactions, quiet focus during combat,
  and meaningful responses to viewer questions rather than constant narration.
- Conversational repair: natural interruption and resumption, appropriate humor,
  admitted uncertainty, contextually responsive laughter and fewer repeated lines.
- Visible presence: eye gaze/blinks and idle motion coupled to actual speech and
  verified game events. Audible PCM playback, not speculative TTS scheduling,
  drives mouth animation. Evaluate delays in the real OBS recording.
- Character consistency: Star can express interests, lore and friendly chemistry
  with Astro and Amber; memories must originate from approved interactions,
  not invented history or private viewer profiling.
- Viewer trust: always disclose that Star is AI; do not claim to be a human,
  sentient person or actual friend with fabricated feelings; gate all external
  network, third-party, moderation and purchasing actions appropriately.

## Status and next decision

Shipped into this unmerged draft: optional content pin. The test reliability
repair was published separately to parent PR #979. Not established: verified OBS-to-file provenance, a genuine Windows game
session, a live synthesized voice, avatar lip sync, higher model intelligence, or
faster game/voice inference. The next meaningful milestone is PRIVATE Windows
end-to-end rehearsal with captured independent evidence, not another unmeasured
claim of increased intelligence.
