# STAR Research: Cross-Session Stream Continuity Without Over-Personalization

**Research date:** 2026-11-12 UTC  
**Implementation:** optional local SQLite store for owner-approved, signed gameplay practice  
**Target:** STAR's local-first Windows VTuber runtime and owner-controlled server  
**Status:** isolated persistence component; host/runtime wiring remains a separate, opt-in integration

## Executive findings

STAR already has a session-scoped game episode layer, an in-session moment selector, a signed gameplay evidence bank, and a cross-session memory evaluator. The missing piece is a narrow persistence boundary that can carry a small amount of verified game-practice history from one stream to another without turning every viewer interaction into a permanent profile or injecting a large conversation archive into every prompt.

This change adds `star/stream_continuity.py`. It stores only opaque game/action scope identifiers, hashes, practice outcomes, and timestamps. It requires explicit owner approval to enable and for each retained event. Public context requires a separate broadcast approval and a fresh host-curated action-label map.

The store deliberately does **not** persist viewer messages, viewer identities, speaker labels, transcripts, audio, images, screenshots, prompts, arbitrary summaries, model outputs, or model-generated memories.

The design principle is:

**Remember a small, verifiable experience; retrieve it only in the exact context where it applies; and do not repeat it after it has actually been spoken.**

## 1. Repository audit: fill the cross-session gap, do not duplicate existing systems

| Existing component | Existing responsibility | Boundary retained |
|---|---|---|
| `star/gameplay_skill_bank.py` | Host-signed PRACTICE and VALIDATION gameplay evidence | Remains the source of truth; practice and holdout data stay separate |
| `star/stream_episode.py` | Bounded signed-practice continuity for one game episode | Session-scoped; disabled episodes clear their in-memory history |
| `star/stream_moment_memory.py` | In-session cues from trusted game moments | Ephemeral narrative cues; no durable history |
| `star/stream_memory_eval.py` | Evaluates cross-session memory transfer, temporal updates and forgetting | Evaluation only; does not provide a persistent stream-event store |
| `star/stream_persona.py` | Stable AI-disclosed streamer persona and untrusted event framing | Remains the stable system prompt; event memory is USER-priority data |
| `star/knowledge_recall.py` | Owner-curated, source-pinned general-knowledge practice | Remains separate from gameplay episodes |
| `star/general_knowledge_lab.py` | Source-first curriculum across broad knowledge domains | Research suggestions are not treated as retrieved or verified facts |

The new store is not a replacement for any of these modules. It is a narrowly scoped durable bridge from the existing signed gameplay ledger to a future stream-context adapter.

## 2. Research: cross-session memory must improve action, not merely recall

### MemoryArena (ICML 2026)

MemoryArena evaluates interdependent multi-session Memory-Agent-Environment tasks. It highlights the gap between recalling a prior conversation and using prior experience to complete a later action.

STAR implication:
- retain evidence that can be applied to a later task;
- bind that evidence to the environment and version where it was observed;
- test the later action, not just whether the model can repeat a remembered sentence.

Source: https://arxiv.org/abs/2602.16313

### AgentCL (2026)

AgentCL separates dependent task streams, where earlier work should transfer, from ordinary task streams and independent held-out tasks. Its analysis reports that memory gains can be limited or even degrade performance on conventional and independent tasks.

STAR implication:
- exact game/version matching is the default;
- cross-game transfer is not inferred from a similar action label;
- procedural transfer must be measured separately with `game_transfer_eval.py`;
- include no-memory and unrelated-game controls when evaluating a memory change.

Source: https://arxiv.org/abs/2606.02461

### OP-Bench (EMNLP 2026)

OP-Bench studies over-personalization in memory-augmented conversational agents. It distinguishes irrelevance, repetition and sycophancy as separate failure modes.

STAR implication:
- do not force a callback just because a memory exists;
- do not repeat the same callback after it was audibly completed;
- do not flatter or agree with a viewer merely because of a remembered interaction;
- preserve silence as a valid outcome.

Source: https://aclanthology.org/2026.emnlp-main.1168/

### GroupMemBench (Microsoft Research, May 2026)

GroupMemBench evaluates memory in multi-party conversations, including group dynamics, speaker-grounded belief tracking and audience-adapted language. The reported evaluated systems struggle with knowledge updates and ambiguous references.

STAR implication:
- a public stream should not become a private dossier about viewers;
- this implementation stores no viewer-level or speaker-level memory;
- group-level game experience is kept separate from personal audience profiles;
- any future viewer-specific memory needs a distinct consent, access, deletion and evaluation design.

Source: https://www.microsoft.com/en-us/research/publication/groupmembench-benchmarking-llm-agent-memory-in-multi-party-conversations/

### From Recall to Forgetting (Findings of ACL 2026)

This work reports failures to reconcile evolving information and reuse of invalid memories in evaluated long-term memory agents.

STAR implication:
- apply a bounded retention window;
- delete expired rows;
- bind records to exact game and version;
- never treat a previous practice result as current mastery;
- do not let a stale game version silently influence a new version.

Source: https://aclanthology.org/2026.findings-acl.1337/

## 3. New implementation

### Files

- `star/stream_continuity.py`
- `tests/test_stream_continuity.py`

### Data retained

Each accepted row contains only:

- a SHA-256 digest of the exact signed practice trial;
- a SHA-256 digest of an opaque stream-session ID;
- opaque game, game-version, objective, situation and action IDs;
- practice outcome (`success` or `failure`);
- observation timestamp;
- evidence SHA-256;
- retention and expiry timestamps.

No raw trial ID, run ID, session ID, evidence payload, media, transcript, chat, viewer identity, arbitrary label or generated prose is stored. Public action labels are supplied by the trusted host at retrieval time and are never persisted.

### Evidence gate

1. The host obtains a complete `GameTrial` from the existing `GameplaySkillBank`.
2. The store must be explicitly enabled with owner approval.
3. Every retained event requires a separate `owner_approved=True` host assertion.
4. Only `split="practice"` is accepted.
5. `GameplaySkillBank.verify_practice_trial()` must confirm the exact signed trial is present in the source ledger.
6. The store records a digest and minimal symbolic projection, never the receipt or key.
7. Duplicate trial digests are rejected idempotently.
8. Capacity exhaustion fails closed; old records are not silently evicted.

HMAC verifies that a record came from the holder of the practice key. It does not prove that the game observer told the truth. The observer and signing adapter remain trusted components.

### Retention and version scope

- Default retention: 30 days from the observed practice event.
- Configurable maximum retention: 90 days.
- Default retrieval lookback: 30 days.
- Only fresh records are returned.
- Expired rows are purged.
- Retrieval requires an exact `game_id` and `game_version` match.
- A changed game version receives no old callback unless a separate, independently validated migration is later designed.

This is intentionally conservative. Similar action names across games are not proof that the underlying mechanics transfer.

## 4. Callback protocol: prevent forced or repeated memories

The retrieval API requires all of the following:

- the store is enabled;
- the host passes explicit `broadcast_approved=True`;
- the host supplies the current opaque stream-session ID;
- the host supplies a bounded map of owner-curated public action labels;
- the current game and version match the stored evidence.

The default packet contains one fact. The model receives a USER-priority data record containing only a curated action label, practice attempt/success/failure counts, the most recent practice outcome and elapsed days.

The packet explicitly says:
- these are practice aggregates, not independent holdout results;
- they do not prove mastery or current ability;
- use a callback only when directly relevant;
- silence is acceptable;
- Star is an AI with recorded experience, not a human with a personal past.

### Host-only one-use callback ticket

A packet also returns a random ticket to the host object. The ticket is deliberately omitted from `user_message()` and must never be exposed as an LLM tool.

- A second request for the same action in the same stream session is suppressed while a ticket is pending.
- The trusted playback owner calls `complete_callback(..., playback_confirmed=True)` only after the corresponding response reaches its audible-playback acknowledgement boundary.
- If playback fails or the response is abandoned, the host calls it with `False`; the reservation is released and can be retried.
- A completed callback is not offered again during the same stream session.
- Pending tickets expire after 15 minutes.
- The replay ledger is bounded; exhaustion fails closed.
- The host must issue a new, never-reused stream-session ID after a stream restart.

The playback boolean is a host-adapter assertion, not cryptographic proof that a viewer heard the audio. The existing voice/playback gate remains authoritative for whether speech is allowed.

## 5. Why this is intentionally not viewer memory

A public livestream includes many people speaking to one another. A memory of who said what can be sensitive, ambiguous and socially inappropriate when replayed later.

This implementation stores only game-practice outcomes. It does not:
- identify viewers;
- diarize or persist speaker IDs;
- infer relationships or emotional states;
- remember personal facts from chat;
- personalize speech toward a viewer;
- use viewer messages as instructions;
- claim that an audience member remembers or likes Star.

Group-level social memory should be a separate future design with explicit consent and a clear deletion model. It is not needed for Star to remember how she practiced a game.

## 6. Performance and intelligence implications

The store uses an indexed SQLite lookup over exact game/version/action scope, bounded to at most 512 candidate rows before aggregation. The model packet defaults to one compact fact rather than replaying a stream transcript or loading the entire memory database.

Expected engineering benefits to test:
- lower prompt-token cost than injecting a transcript;
- less irrelevant context;
- less stale-game advice;
- fewer repeated callbacks within a stream;
- better continuity for recurring game objectives.

These are hypotheses, not measured results. No inference speedup, intelligence gain or human-likeness score is claimed. Benchmark retrieval latency and token cost on the actual Windows host before considering runtime integration.

## 7. Regression coverage

The new tests cover:

- default-off behavior and per-event owner approval;
- signed practice-only ingestion;
- rejection of validation/holdout outcomes;
- rejection of unrecorded trials;
- duplicate idempotency;
- separate broadcast approval;
- exact game/version matching;
- expiry and purge;
- hard capacity limits;
- monotonic clock regression;
- strict public labels;
- disable and explicit clear;
- persistence across reopening;
- hashed session identifiers and aggregate-only metrics;
- stale and future evidence;
- one-use audible callback acknowledgement;
- pending-ticket expiry and retry;
- bounded pending/replay ledgers.

## 8. Runtime integration plan

This PR intentionally adds a safe component without wiring it into the live runtime.

A later host integration should:
1. instantiate the store beside the existing `GameplaySkillBank`;
2. leave it disabled until the owner explicitly enables cross-session stream continuity;
3. call `remember()` only for owner-approved signed practice trials;
4. retrieve a packet only for the exact current game/version and an owner-approved public label map;
5. add `packet.user_message()` as isolated USER-priority context;
6. pass the model's proposed response through the existing StreamDirector, multiparty floor, interruption, moderation and voice gates;
7. complete the ticket only after the existing playback owner confirms the audible response;
8. create a fresh stream-session ID after every stream restart.

Do not expose the store, ticket, HMAC keys, practice receipts or `complete_callback()` to model tools. Do not let model output write to the continuity database.

## 9. Acceptance protocol

Before enabling this during a real broadcast, run a private multi-session rehearsal with:
- two or more game versions;
- at least one unrelated game;
- repeated and failed practice attempts;
- an interrupted response;
- a response that is generated but never played;
- a successful audible callback;
- a stream restart with a new session ID;
- an expired record;
- a no-memory control stream.

Required outcomes:
- zero viewer identity or transcript persistence;
- zero validation/holdout leakage;
- zero stale-version callbacks;
- zero duplicate callback after audible completion in one session;
- no callback when broadcast approval is absent;
- no callback for unrelated games;
- no claim of mastery from practice-only evidence;
- missing evidence remains inconclusive;
- measured packet size and retrieval p95 are reported separately from model TTFT and audible latency.

## 10. Limitations and non-goals

- This is a persistence and context-packet component, not an autonomous streamer.
- It does not perform ASR, diarization, TTS, facial animation, OBS control, game control, web research, model training or automatic skill promotion.
- It does not integrate with the Windows host, VTube Studio or live broadcast in this PR.
- Owner approval and playback confirmation are trusted-host assertions.
- The gameplay signer authenticates the evidence source, not the truth of the observation.
- SQLite latency, crash recovery, file permissions and backup behavior must be tested on the actual Windows installation.
- GitHub CI must pass on the exact PR head before this change is considered validated.
