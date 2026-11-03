# STAR: session-wide gameplay memory identity, faster gaming AI, natural VTuber behavior
**Date:** 2026-11-03
**Scope:** Offline, owner-approved STAR AI development; not an actual livestream or autonomous Windows game-control demo.

## 1. Verified problem: expired/evicted game moments could become "new" victories
The separate `StreamEpisodeJournal` stores short structured, host-attested game facts for grounded conversation.
Its prior duplicate fence was rebuilt from the currently retained deque. When a moment expired or fell out
of the FIFO, an old `(game_scope, moment_id)` could be submitted again with a **new** timestamp and a
different `kind` such as `win`. The code accepted the replay, which could produce false "Earlier Star
won a round" context for a later viewer question. This gap remained even after the signed
`StreamEpisode` and `VerifiedGameReactionHost` duplicate/event-order fixes.

Two deterministic tests were run against the unmodified implementation and **both failed**: replay
after FIFO eviction and replay after age expiry. This is provenance correctness, not a claim that the
underlying game-state observer is authentic. `host_observed=True` alone is an API attestation.

### Changes
- Introduce a **session-lifetime, game-scoped seen-ID fence**, not rebuilt when recent cards expire.
- Reject ID reuse even if the replay changes outcome, timestamp or stage.
- Preserve legitimate identical moment IDs used by different independently scoped games.
- Bound the fence to **4,096 unique accepted IDs** per owner-approved session. Saturation fails closed;
  `identity_capacity_rejected` exposes an anonymous count without retaining raw transcripts/players.
- Reset the fence only when an authorized episode is actually disabled/re-enabled.
- Do not spend replay budget on untrusted or stale observations.
- Add tests for eviction replay, expired replay, capacity saturation, fresh-session reset and isolation.

Tradeoff: a session producing >4,096 unique host moments will stop admitting new journal records until
an explicit owner-approved restart. This avoids silently forgetting receipt identities in a long stream.
The producer should sample *meaningful* milestones rather than every game frame or input. Do not
silently expand the identity budget on an 8 GB gaming box without RSS measurements. Future production
design could use a durable rotating ledger with sequence windows and explicit source-epoch fencing.

## 2. Architecture: intelligence = grounded outcomes, not faster fabricated text
A practical pipeline for a capable AI gaming VTuber:

`Capture / game-state bridge -> evidence provenance -> low-latency action agent -> guarded input -> game-side outcome -> memory / training -> speech director -> verified playback / avatar`

**Fast lane (online play):** fixed input/output schema, cropped event-driven perception, state and
input deadlines, short action horizon, a small GPU-resident model or deterministic fallback. In-game
deadlines matter more than raw tokens/sec. Use the existing OBS guard and independent key-release
watchdog. Silence and no-op are legitimate outputs when evidence is missing.

**Slow lane (learning between attempts):** inspect failed clips and input receipts, propose alternatives,
run independently seeded practice challenges, compare to a frozen control, then promote only gains on
holdout levels. Maintain `game/version/objective` scopes and an immutable experiment ledger. Do not
teach from duplicate captures, or use validation outcomes as narrated experience.

**Creator lane (game building):** Roblox Studio observe-before-edit, generate best-of-N diffs, run Luau
analysis and Studio tests, test physics, multiplayer, UI legibility and a complete playable round.
Separate model-generated code from **executed** evidence.

**Knowledge lane:** local-first indexed manuals, author/publish/version metadata, provenance and source
revocation; retrieve relevant facts rather than dumping a giant fixed prompt. Write learned claims back
only after explicit tool/test verification, not on a model's confidence alone.

## 3. Faster inference without making streams worse
The STAR host should compare A/B candidates with the **same prompt, model revision, quantization,
context length, audio workload and game scene**. At minimum report:
- p50/p95 decision-to-action latency, action-deadline miss rate and actual game objectives completed.
- p50/p95 time to first token, prompt ingestion and decode tok/s, CPU/RAM/VRAM peaks.
- p95 game frame time, OBS render/encode/network drops and speech first-audible latency.
- Ratio of verifiably correct decisions and outcomes, on independent game seeds.

Experiments to isolate (not yet enabled or measured):
1. KV/prefix caching and cache-stable system/tool instructions; test whether cache hits improve real
   completion latency and whether changing a project invalidates the cache.
2. Short fast-path reasoning and a teacher model only for offline study; no unbounded context in the
   realtime action loop.
3. Speculative decoding using a compatible draft and target. Measure acceptance rate and actual
   end-to-end speed; it may lose on small models and 8 GB VRAM.
4. Small batching and resource admission. Total throughput is not the same as single-turn latency;
   reserve GPU memory/frame time for Roblox, OBS and the avatar.
5. CPU voice as an **A/B** option, not a blanket winner; benchmark intelligibility, natural turn timing,
   first-audible p95 and game FPS against GPU voice.
6. Cancellation-aware speech and animation: utterances stale after scene handoff, revoked consent,
   audience interruption, or playback epoch change must not be published as new memories.

## 4. Natural AI VTuber behavior that is truthful
- **Interesting silence:** use scene relevance, viewer speech and game danger to choose when *not* to
  talk. Do not force constant commentary or exaggerated scripted laughter.
- **Turn-taking:** adaptive interruptions, endpointing and recovery from false interruptions;
  measure not only speed but false barge-ins and speaker overlap.
- **Expressive delivery:** pitch/prosody/emotion appropriate to **observed** game events, phoneme or
  audio-envelope-driven mouth cues and small gaze/blink/body movements. Avoid invented achievement
  stories or unsupported claims about chat participants' emotions.
- **Long-lived identity:** retain Star's chosen lore and style as character configuration. Maintain
  separate verified session episodes and historical summaries with provenance, consent and retention
  controls; an appealing character need not claim to be biological or conscious.
- **Social skills:** consent-respecting chat moderation, remembering opted-in preferences, fair viewer
  turn handling, and explicit disclosure that the VTuber is AI.
- **Original companions:** Astro and Amber may interact through shared turn schedules and game context,
  but generated banter must never imply actual gameplay observations not recorded by the host.

## 5. Recommended acceptance milestones (in order)
1. Merge/review the existing draft PR chain in order. Don't mistake draft branches for shipped behavior.
2. Nonbroadcast Windows rehearsal on an authorized test game: OBS read-only monitor, guarded key
   actuation + independent watchdog, game-side receipt, spoken audio, playback-verified avatar.
3. StreamEpisodeJournal event-source authentication and **monotonic game-event sequence/epoch**; an
   event ID alone does not prove uniqueness or time order if the trusted producer lies/restarts.
4. Benchmark at least 30 paired sessions across game seeds, including 8 GB GPU stream contention.
   Publish median, tail latency, complete outcomes, OBS loss and failures before changing defaults.
5. Only after nonbroadcast A/B succeeds, separately authorize live broadcast and chat integration.

## Sources checked (2026-11-03)
- Microsoft Research, *Proact-VL: A Proactive VideoLLM for Real-Time AI Companions*, ICML 2026
  (May 2026): https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
  Explores efficient realtime perception and deciding when/what to say in games.
- LiveKit documentation, *Turns overview* and *Turn-taking tuning* (accessed Nov 3, 2026):
  https://docs.livekit.io/agents/logic/turns/
  https://docs.livekit.io/agents/logic/turns/tuning/
  Describes semantic/VAD turn detection, adaptive interruptions, false-interruption recovery and
  tradeoffs of preemptive generation.
- Roblox, *OpenGameEval* (October 2026 research; repository):
  https://github.com/Roblox/open-game-eval
  Separates observation from editing and evaluates real Studio edit/play behavior.
- *From Code to Playable Systems: CEGame-Bench for Long-Horizon Game Creation Agents*,
  Oct 19, 2026: https://arxiv.org/abs/2610.26098
  Highlights that build/integration success is not equivalent to finishing a playable game.
- llama.cpp official speculative decoding demonstration (accessed Nov 3, 2026):
  https://github.com/ggml-org/llama.cpp/blob/master/examples/speculative-simple/README.md
  Actual gains must be benchmarked rather than extrapolated from examples.

**Not demonstrated by this patch:** faster model inference, improved game scores, verified real
keyboard injection/release, humanlike speech quality or a running livestream. It only corrects
an independently reproduced game-memory replay flaw and adds acceptance-grade research.
