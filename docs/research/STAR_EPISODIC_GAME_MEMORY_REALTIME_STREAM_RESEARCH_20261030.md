# STAR: grounded gameplay memories, fast live attention, and continuous game learning

Engineering research and implementation record — October 30, 2026. Owner-controlled, local-first. This memo documents new code published on draft PR #845, the relevant external findings and an experimental roadmap. No broadcast or model-weight change was executed.

## A. Implemented now: genuine stream-session moment recall

The new `star/stream_episode_journal.py` is an offline-only, consent-gated bounded memory component. It improves an important precondition for a compelling VTuber: recollections must refer to *actual observed experiences*, not model-invented character biography, unrelated chat or generic streamer scripts.

Public API: `GameMoment`, `StreamEpisodeJournal`, `EpisodeRecall`. A trusted host extracts a structured game-state event (a checkpoint, round win/loss, close call, puzzle solved, discovered mechanic, or verified practice improvement). It supplies canonical game/stage IDs, timestamp and a unique moment ID to `record(..., host_observed=True)`. The journal refuses events while disabled, rejects duplicates, future timestamps and overly delayed observations, and offers simple deterministic recap suggestions through `recall(...)`.

**Scope:** The host is responsible for authenticating its game-state observation. The boolean is *not* a cryptographic signature or a defense against a compromised host. The journal stores nothing on disk, performs no audio/input/network activity, never reads chat or transcripts, and cannot authorize speech. It retains at most 48 observations by default (configurable 1–128), expires them after one hour by default, and clears everything on disable. Identifiers are bounded ASCII tokens; arbitrary prose is disallowed to prevent accidental passage of viewer chat and prompt-injection text through this channel. Event timestamps, not arrival order, determine the recency of a recollection; delayed observations expire independently. No raw player identity, account ID, personal anecdotes or invented emotional states are retained.

Example use for a permitted owner-run game test:

```python
from star.stream_episode_journal import GameMoment, StreamEpisodeJournal

journal = StreamEpisodeJournal()
journal.enable(owner_approved=True)
# ONLY the trusted game host should submit a true observed event:
journal.record(
    GameMoment("event_42", "obby_v1", "checkpoint", 101.0, "bridge_3"),
    now_s=101.0, host_observed=True,
)
cards = journal.recall(now_s=105.0, game_scope="obby_v1")
# cards[0].context: "Earlier in obby_v1, Star reached a checkpoint on stage bridge_3."
# Authorized speech is still False. Host must separately decide whether to speak.
journal.disable()
```

This builds an honest, explainable source for eventual stream recaps. **It is not connected to OBS, StarStage speech prompts, gameplay capture or any game controller in this patch.** Integration must use a real game-state witness and opt-in host; do not fabricate signed evidence or feed chat-provided game stories as trusted observations.

`tests/test_stream_episode_journal.py` covers opt-in, no unauthorized writes, timestamp validation, clock reversal, replay, moment diversity, cross-game isolation, capacity/expiration, out-of-order evidence, thread safety, immutable result objects, and no raw private text in public metrics. These are synthetic offline tests, not an actual game-play proficiency result.

## B. New research findings with immediate architectural implications

### 1. Real-time gaming: inference is part of the environment

GameWorld covers 34 games and 170 verifiable tasks using a serialized game-state outcome judge rather than impressionistic LLM scoring. Its real-time variant (`GameWorld-RT`) does **not pause the game while the agent thinks**; this exposes response latency in moving environments. The August 2026 Fine-Control Protocol uses higher-frequency actions and up to 400 steps per episode. STAR should evaluate both paused and real-time tracks and report them separately; a strong paused-game score can conceal poor reaction time or controller integration.

**STAR experiment:** Prepare a legal, owner-approved local game roster: a predictable platformer, dynamic avoidance game, puzzle, and multiplayer Roblox test place. Hold game version, seeds, actions, FPS and difficulty constant; compare a fast model alone vs a fast action policy with a slower planning model. Measure objective success, normalized progress, actions per success, invalid actions, median/p95 action delay, replay reproducibility, failures after visual occlusion, and held-out-map transfer. Precommit cases outside Star's learning memory. Game-state telemetry or Studio assertions, not Star's narrated confidence, must be the ground truth.

Source: GameWorld official implementation https://github.com/gameworld-project/GameWorld and project https://gameworld-project.github.io/

### 2. Honest stream memory must distinguish four kinds of evidence

Do not mix:
1. *Game-state fact* (trusted host confirms a checkpoint, health change or victory).
2. *Prediction* (the model thinks a jump should work; record before action).
3. *Speech receipt* (host confirms an audible utterance completed).
4. *Broadcast receipt* (OBS recording independently contains synchronized audio and video).

A game event may be true without Star having talked about it. Speech may have completed without the broadcast capturing it. The new journal records only category 1, and only as host-attested structured data; it must never be used as proof of 3 or 4. The existing StreamStage and gaming evidence bank already maintain important boundaries for the other categories. Store any signed training outcomes apart from viewer-facing recollections so fake stories cannot contaminate learned success rates.

### 3. Natural conversational turn-taking depends on interruptions, not more words

LiveKit's documentation distinguishes real barge-in attempts from short backchannels such as "uh-huh." Its current adaptive interruption feature is not an unqualified drop-in local solution: outside supported cloud configurations, the documented model uses LiveKit credentials and development allowances; VAD-only handling is the fallback. Its local `v1-mini` audio turn detector is a separate possibility to benchmark. Do not claim that an unconnected self-hosted STAR instance is already running LiveKit's adaptive backchannel model.

**STAR experiment:** 60 preregistered speech clips: interruption while explaining a move, quiet acknowledgment, correction at speech onset, viewer joins mid-sentence, noisy combat, laughter after a win, and silence while concentrating. Label independently whether Star should stop, continue, or briefly acknowledge. Compare false interruption rate, true interruption recall, first-audible latency, total speech interruption-to-physical-silence, background narration density, naturalness ratings and GPU/CPU cost. Video/OBS review should include mouth/gaze synchronization and gentle hair physics. Require consent before voice cloning and preserve AI disclosure.

Sources: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/ and https://docs.livekit.io/agents/logic/turns/turn-detector/

### 4. New lightweight CPU voice candidates and an October 21 patch

Kyutai Pocket TTS version 4.0.0 was published October 20, 2026, with 18M/7M and experimental 2M English variants. Version **4.0.1**, published **October 21**, fixed an issue affecting sub-20M models and changed the default English model. For comparisons, pin the exact model and **release version**, rather than comparing Star's old voice against an unspecified `latest` binary. CPU speech might preserve 8 GB gaming VRAM; its naturalness and measured audio startup on Star's hardware are unknown. Evaluate listening quality across normal/cat/puppy modes without losing Star's identity or treating size as a quality ranking.

Official releases: https://github.com/kyutai-labs/pocket-tts/releases

### 5. Fast reasoning requires workload-matched benchmarks

The current llama.cpp server supports cache reuse, continuous batching, multiple slots, quantized models and speculative decoding. Its SPEED-Bench reports per-category latency, throughput and draft acceptance. Prompt cache reuse can alter numerical outputs across batch shapes, so correctness must accompany timing. On a gaming PC with an RTX 4060 8 GB card, simultaneous game graphics + avatar + OBS load can dominate an isolated tokens/sec win.

Test at least three separate configurations, with fixed model weights/prompts, repeated warmups and a holdout set: baseline single-model generation, prompt cache, and speculative decode (only if a draft fits measured headroom). Report first *audible* token / complete speech p50/p95, gameplay 1%-low FPS, memory/VRAM headroom, dropped frames, correctness across general knowledge, Roblox code/build tasks, game-event grounding and response cost. Reject an optimization if one task category develops previously correct-to-incorrect paired failures. CPU voice or CPU research offload needs its own A/B experiment.

Sources: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md and https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

### 6. Make Roblox creation a repeatable learned skill

OpenGameEval's executable scene and play-session checks cover 84 curated Roblox Studio tasks; merely generating syntactically valid Luau is not enough. A safe Star evaluation farm should test an entire sample game: inspect objects before editing, use Luau analysis, run server/client playtests, check attachments and collision integrity, launch multiplayer tests, and visually inspect gameplay for broken props and animations. `StudioTestService` supports scripted multi-client scenarios, including join/leave. Capture *what failed*, the fix, and whether a fresh held-out task succeeded without looking up the answers. Keep game/test rights and creator platform rules intact.

Sources: https://github.com/Roblox/open-game-eval and https://create.roblox.com/docs/reference/engine/classes/StudioTestService

## C. Integrated learning loop STAR should work toward

**Fast perception/action (tens of milliseconds):** bounded game-state or screenshot sampling; local deterministic controller for safe, permitted test sessions; stale frame and action rejection. Do not route frame-critical movement through a long language-model completion.

**Interactive planning (hundreds of milliseconds):** select a short tactical goal, identify unfamiliar mechanics, choose an owner-curated safe experiment, and submit a prospective prediction. A trusted host independently tests the outcome. Reserve game GPU and audio capacity before any vision model starts.

**Deliberate background learning (seconds/minutes):** read accessible docs and licensed examples, synthesize candidate improvements, test them through Star Core Forge with automatic rollback, and promote only after offline regression + held-out game/build/general-knowledge evaluations. Preserve a retrieval cache of source-backed facts with timestamps and contradiction checks, not an unverified "I know everything" store.

**On-stream personality and continuity:** pause naturally when concentration matters, react to actually witnessed events, recall *recorded* experiences rather than fictitious personal history, allow interruptions and silence, and coordinate eye, head, hand, mouth and hair motion to real audio timing. Viewers should be told STAR is an AI entertainer.

## D. Acceptance and blockers

**Implemented and locally checked:** 16 offline synthetic tests for the new session journal passed with Python 3 test runtime in isolation. The GitHub full repository CI must still pass at the newest commit, including React, Ruff/Pyright and complete Python tests; do not infer full CI from local module tests.

**Not yet implemented:** wiring the journal to an authenticated local game-state host; UI for owner opt-in; voice turn detector; genuine replay/history retrieval across sessions; GPU model benchmark; OBS independent audio witness; automated Roblox studio action loop; general-knowledge retriever retraining; actual streaming or game-play mastery.

**Proposed gates before deployment:** no unsafe/unsigned game observation, no viewer text in experience cache, no replay after disable, no false victory narration, no new failures on matched general-knowledge/Roblox/streaming holdouts, neutral or improved gameplay frame-times and p95 first-audible latency, and independently reviewed OBS audio/animation. Keep public GitHub free of real tokens, unredacted viewer information, raw media and private evaluation cases.

**Critical visibility note:** `oncoursemail/Star-AI-Private` reports GitHub visibility **public**, regardless of its name. Star Core Forge remains the owner's local-first authoritative environment; GitHub is a reviewed publishing mirror, not a required autonomous-learning backend.
