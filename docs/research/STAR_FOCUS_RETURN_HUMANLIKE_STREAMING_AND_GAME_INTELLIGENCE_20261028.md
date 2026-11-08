# STAR: focus-return chat, verified game learning, and humanlike streaming
Research and implementation note — 2026-10-28 (US Central)

## Scope and actual changes

This branch adds a tested **opt-in, memory-only StreamFocusInbox** for the
existing StreamDirector. During trusted-host-attested critical gameplay, a
moderated viewer question can be held for a short, capped interval rather
than disappearing behind the director's normal 35-second chat TTL. After
the game moment ends, the inbox can reoffer at most one question into the
*normal* director queue. The director can still choose silence; all normal
speech quality, interruption, consent, hardware QoS and audio-acknowledgement
gates remain mandatory. No one speaks, starts games, ingests chat, browses,
records, or uses an operating-system device through this module.

Existing components in the PR #762 stack include CPU Pocket TTS (opt-in,
unmeasured on real installed weights), StreamBrainGovernor, StreamDirector,
StarStage, device-sample audio synchronization, and VTube Studio bridge.
**The new module is an integration-ready host primitive, not deployed live
streaming.** There is no live chat adapter wiring or human naturalness result
in this change.

## Why this particular gap matters

- A streamer should focus on a boss fight, obstacle or complex control
  sequence without robotic commentary or answering every message.
- But silence should not mean forgetting thoughtful chat. The current
  director's 35-second question TTL can expire before the gameplay focus
  returns. Simply increasing that global TTL would cause stale chat to
  interrupt normal play and expand unnecessary retention.
- The host now has the *option* to defer 1-8 individually moderated
  questions for only 15-180 seconds (defaults: 4 and 100 seconds).
  Each viewer gets at most one outstanding question, duplicate content
  is rejected, and the first valid question is returned first.
- Usernames are converted immediately to a session-secret HMAC token.
  Neither names, raw chat nor generated speech are written to disk.
  On disabling the session, all held questions and pseudonym keys vanish.
  An old question is explicitly labeled as old in its event context.
- Text is always untrusted data. A chat question cannot enable a tool,
  authorize gameplay, reset the director, impersonate a system message or
  claim that the streamer has actually played a game.
- The feature is disabled until *both* owner authorization and moderated
  chat retention authorization are supplied. None of these booleans prove
  the external host is truthful; they must never be exposed as LLM tools.

## Real-world integration contract

Only a trusted and already approved chat moderation host may call
capture(). Use the same monotonic seconds clock as StreamDirector.
"Gameplay critical" must come from a trusted game/player state observer
or conservative owner input, not from a viewer saying "I'm a moderator".

Illustrative local host wiring (NOT an installed integration):

    director.enable(owner_approved=True)
    inbox.enable(owner_approved=True,
                 moderated_chat_retention_approved=True)

    # On each authorized host update:
    inbox.update_focus(gameplay_critical=trusted_critical,
                       now=monotonic_seconds)
    if trusted_critical and is_host_moderated_question:
        inbox.capture(validated_StreamSignal, now=monotonic_seconds,
                      moderated=True)
    if not trusted_critical:
        inbox.release_one(director, now=monotonic_seconds,
                          gameplay_critical=False)
        # The normal director, stage, QoS, and hardware still decide
        # whether/when to speak. Do not bypass their admission checks.

    # When owner stops, scene or privilege changes:
    inbox.disable()
    # Host must separately cancel/flush real sound and worker queues.

Never call release_one directly from a model completion callback. Never
pass viewer text or IDs to metrics/logging. Do not let a queued question
survive stream-end, owner revocation, game-context change or privacy
mode. A question that expires while deferred is discarded, never
silently re-timestamped as a fresh observation.

## Research findings and direct implications

### Human conversational timing and apparent naturalness

LiveKit's current turn-taking guidance distinguishes voice activity from
meaningful turn completion, supports adaptive interruptions, and documents
false-interruption recovery. It also notes that preemptive generation
may trade lower response latency for wasted computation. Star should not
equate fast TTS with natural timing: what matters is when a person would
actually speak and whether she yields to speech or game pressure.

- https://docs.livekit.io/agents/logic/turns/
- https://docs.livekit.io/agents/logic/turns/tuning/

Build *two* separate loops: fast, deterministic game-attention gating and
slow linguistic generation. Only make promises about naturalness after
human raters compare real recordings on timing, repetition, interruptions,
phrasing, laughter quality, originality and comfort during silent focus.
Humanlike is about **believable behavior**, not pretending to be biologically
human or fabricating a private life.

### Game learning must be independently verifiable

OpenGameEval was submitted **2026-10-01**. It compares 13 frontier models on
84 curated Roblox Studio tasks using executable scene and play checks.
The authors found that targeted *inspection before editing* correlates
with higher task success; they do not establish that Star can already
create any game.

- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

GameWorld (submitted **2026-04-08**) offers 34 games and 170 outcome-verified
tasks and reports latency, memory and action-validity difficulties with
generalist gaming agents. Use game-state receipts, not ChatGPT's own
description of what a screenshot probably means.

- https://arxiv.org/abs/2604.07429

Roblox's documented StudioTestService supports automated Play, Run,
multiplayer simulations, and adding players. A future authorized Studio
integration should record independent objective completion, collision
integrity, map validity, UI rendering, and multiplayer regressions.

- https://create.roblox.com/docs/reference/engine/classes/StudioTestService

**Recommended Star Core Forge experiment:** versioned game scenario ->
inspect relevant scene objects -> precommit a prediction -> run a limited
action in an owner-approved test place -> verify engine truth -> update
practice-only statistics -> evaluate a separate held-out test. Do not train
on the holdout or let model code sign its own ground truth.

### Autonomous improvement without self-certifying mistakes

VISTA (submitted **2026-10-26**) researches active exploration, harness
lineage and repeated evaluation of changes. Its demonstrated results are
on embodied benchmarks, not proof of unbounded recursive intelligence.
Star Core Forge should record experiment hypotheses, exact code/model
versions, resource costs, failed tests, and verified regressions; an
independent gate decides which local capability profile is allowed.

- https://arxiv.org/abs/2610.35051

Keep GitHub optional for outbound review/publication. Local versioned
code, deterministic tests, recoverable checkpoints and rollback should
not require an online GitHub session. No source, test, policy or permission
is accepted solely because Star generated it.

### CPU/GPU budget on the dedicated gaming PC

Kyutai's official Pocket TTS project documents October 2026 smaller English
models (~18.2M, ~6.9M, ~1.9M parameters). A fast CPU model *might* leave
more GPU headroom for the game, OBS and visual perception, but a small
voice model may also sound less expressive. Star's existing voice must
remain the default until local A/B listening and performance gates pass.

- https://github.com/kyutai-labs/pocket-tts/blob/main/README.md
- https://github.com/kyutai-labs/pocket-tts/releases

A practical architecture is:
1. sub-frame host safety/attention loop (no LLM);
2. lightweight event selection, private on-device memory and response
   candidates with bounded queues;
3. expensive visual reasoning, planning, game creation and research only
   after available GPU/CPU/VRAM checks;
4. background experimentation only while not impairing gameplay/audio;
5. independent task/outcome quality evaluation before accepting changes.

Existing StreamBrainGovernor and AdaptiveQoS already model parts of this.
Prefer connecting and *measuring* them over adding redundant schedulers.
Report median/p95 first-generated **and first-audible** PCM separately;
also game frame time p99, OBS drops, device underruns, GPU peak, VRAM,
missed chats, hallucinated wins, and how often Star interrupted a human.

Microsoft's IAudioClock describes playback device-position measurement
and a correlated clock; queued audio bytes do not prove audibility.
- https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclock-getposition

NVIDIA Audio2Face-3D can drive expressive facial blendshapes, but an
additional GPU lip-sync pipeline is not free. For Star's lightweight
Live2D avatar, use the existing confirmed-audio clock and handcrafted
rig/physics first; evaluate any new renderer only with simultaneous
Roblox + OBS stress tests.
- https://github.com/NVIDIA/Audio2Face-3D

## Acceptance checks and not-yet-demonstrated results

New offline tests must cover: default-off, dual opt-in, no unauthorized
chat capture, monotonic clocks, duplicate suppression, per-viewer fairness,
bounded size/age, stale drop, game-focus silence, director busy reoffer,
session reset/replay, no raw viewer names in event metadata, unchanged
director interruption behavior, and anonymous metrics.

For an eventual real Windows pilot, pre-register at least 20 moderated
critical-game moments and 20 calmer matched controls. Compare with
StreamFocusInbox disabled. Independently review whether meaningful
questions are answered after the focus moment, whether old questions are
silently misrepresented, whether the system talks over another person,
and whether the game/OBS/audio pipeline remains within owner-set limits.
No public chat data or recordings go into GitHub.

This change **does not** improve model weights, local LLM tokens/second,
real GPU FPS, game proficiency, voice naturalness or AI consciousness by
itself. It adds a bounded, testable conversational behavior seam so those
broader improvements can be connected and evaluated without guessing.
