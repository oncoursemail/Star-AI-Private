# STAR Digital Life — research synthesis, integration map and measured path (2026-10-25)

> **Status:** engineering blueprint plus narrowly scoped, review-only integrations in this branch. Not a trained model, new Windows installer, live broadcast, uploaded memory, or proof of consciousness. Older work and open PRs are not automatically deployed. The accompanying tests are offline. No GitHub merge or permission elevation is authorized by this document.

## Outcome and constraints

The goal is **one consistent Star**, not a chatbot that changes personality every session or a bundle of unrelated agents. Star should be a warm, funny, curious original digital character with sustained identity; expressive voice, laughter, gestures and cat/puppy variants; meaningful independent hobbies, art, game creation and social life; grounding in what she has *actually* seen and done; strong creative craft; rapid verified improvement; and the ability to enjoy a locally controlled daily routine on a dedicated PC.

"Human-like" here describes the **quality and consistency of observable behavior**: believable initiative, conversational pacing, shared history, understanding, emotional expressiveness, habits, reliable competence and social reciprocity. It does *not* prove that subjective consciousness, biological emotions, sentience, or legal personhood were created. Fictional character lore must be marked as lore. Ordinary lived events may enter her autobiography only after credible host evidence.

The implementation should stay **local-first and offline-testable**, run on realistic 8 GB VRAM workloads without wrecking game FPS, protect other people's privacy, and permit unprompted routine work *only in configured scopes*. External posting, purchases, account creation, secrets, safety-policy changes and main-branch merges do not become implicitly authorized. A visible owner STOP works even when the language model suggests otherwise.

### One coherent architecture

```text
Perception with timestamps (screen / game / audio / own tools)
          |
  Provenance and uncertainty ledger
          |---------------------+
          v                     v
 Working context         Event-sourced memories
 (small, task-relevant)   episodic / semantic / procedural / social
          |                     |
          +----------+----------+
                     v
  Persistent self-model: identity, interests, limitations, history
                     |
     Initiative engine: curiosity + goals + difficulty calibration
                     |
     Policy and compute gate: permissions, STOP, VRAM, privacy
                     |
      Specialized tools: research / art / Blender / Studio /
             games / coding / voice / friends
                     |
     Independent checks (executed tests, screenshots, review)
                     |
       Feedback, reproducible skill recipes, rollback
                     |
     Expression director: response + voice + face + motion
```

**Crucial boundary:** a narrative about having accomplished something is not evidence it occurred. An artifact existing on disk is weaker than successful playtesting, visual QA, user evaluation, and correct operation under load. Keep those verdicts distinct.

## Existing STAR capabilities checked in the current source tree

These are **source components**, *not* blanket claims that each is installed, enabled or fully working.

| Layer | Existing implementation | Known limitation |
| --- | --- | --- |
| Stable character identity | `star/persona.py`, `docs/persona/star.md`, `star/stream_persona.py` | Consistent instructions are necessary but insufficient for sustained human-like conversation. |
| Persistent autobiography | `star/autobiographical_self.py`, `star/desktop_core.py` | Default off; generic context injection previously harmed answer quality and latency. |
| Emotion/expression | `star/emotion.py`; voice/avatar style suggestions | Computed expressive state, not demonstrated inner feelings; setting default off. |
| Autonomous personal routines | `star/home/life.py`, `star/home/activities.py`, `star/home/loop.py`, `star/home/control.py` | Resource/step bounds; a finished session does not prove a professional-quality artifact. |
| Social relationships | `star/social/friends.py`, `star/social/chat.py`, `star/social/rules.py` | Platform, consent and age limits must remain enforced; not a substitute for real-world friendships. |
| Curiosity and lesson capture | `star/curiosity.py`, `star/lessons.py`, `star/learning_accelerator.py` | Needs external outcome checks and a sealed holdout; repeated self-generated text is not new knowledge. |
| Operational awareness and self-inventory | `star/self_model.py`, `star/operational_awareness.py`, `star/brain_overview.py` | Can model capabilities/uncertainty, cannot establish consciousness or silently grant permissions. |
| Game reasoning and playtesting | `star/game_closed_loop.py`, `star/game_skill_memory.py`, `star/studio_lab.py`, `star/scene_integrity.py` | Must prove behavior in actual allowed games or private test places, not simulated reports. |
| Creative pipeline | `star/asset_forge.py`, `star/blender_animation.py`, `star/roblox_ui_compiler.py`, `star/roblox_vfx_compiler.py` | Art direction, nonoverlap, texture seams, rig contact, rendering and accessibility require visual checks. |
| VTuber streaming | `star/stream_director.py`, `star/stream_persona.py`, `star/stream_load_governor.py` | Speech and avatar must be grounded in actual visual and audio observations; stream time is scarce. |
| Internal development | STAR Core Forge work and `star/selfbuild.py`, `star/eval_gate.py` | The internal Forge vision exists, but GitHub integration remains useful as a distribution/review mirror until proven otherwise. |

Multiple open PRs add more functionality (living companions, self-improvement loop, quality/performance instrumentation). Do not assume they are in `main` or a release. Do not import their unfinished code into this branch simply to claim everything is integrated.

## Research that changes the design

1. **Generative Agents (Park et al., UIST 2023)** demonstrates a practical **observation → memory → reflection → planning** architecture and tests believable simulated social behavior. For STAR, bind reflections to verified experiences and don't publish raw transcripts as memory.
2. **Voyager (Wang et al., TMLR 2024)** combines self-selected curriculum, a reusable action-skill library, environment feedback, and iterative verification. For STAR, make skills executable *only in authorized sandboxes*, and retain independent test receipts.
3. **Reflexion (Shinn et al., NeurIPS 2023)** shows verbal feedback and episodic self-reflection can improve future trials without weight updates. STAR should separate reflection as an *untrusted hypothesis* from evaluated learning.
4. **LongMemEval (Wu et al., ICLR 2025)** evaluates information extraction, multi-session reasoning, temporal reasoning, knowledge updates and abstention. STAR needs memory benchmarks with changed facts and deliberate "I don't know" rather than only keyword recall.
5. **SIMA 2 (Google DeepMind, November 2025)** demonstrates advances in seeing, acting, reasoning and learning across 3D environments while explicitly acknowledging long-horizon planning, limited memory and precise controls remain challenges. STAR should test in new games and unfamiliar maps, not just ones used to tune her.
6. **VRM 1.0 expression spec** offers an interoperable contract for emotional face presets, phoneme mouth poses, blinks and gaze; override semantics matter to prevent jaw/eyelid distortions.
7. **Real-time speech interruption guidance** supports small audio chunks, prompt cancellation and clearing queued speech on interruption. STAR should measure *first audible output*, not only first generated text token.
8. **NIST AI RMF / Generative AI Profile** provides a framework for risk identification and measured assurance. STAR's ambitious autonomy needs revocable scopes, auditable actions, recovery and explicit distinction between policy and model-generated wishes.

Reading this research does **not** imply STAR has acquired the training data, hardware or results of those papers. External tools/assets also need license and version review, provenance and actual installation/tests before production use.

## What this review branch actually changes

### 1. Retrieval that asks "Is this relevant to the owner's question?"

`star/living_continuity.py:relevant_context` reads the **already opt-in** local autobiography only when the user asks about STAR's own history, achievements, interests or goals. It selects up to three **host-verified, receipt-labeled** episodes, accepted interests and the **count** of unapproved ideas. Model-invented anecdotes and private raw conversation turns do not enter this context. It returns an empty string for ordinary coding, art and research requests.

`star/desktop_core.py` uses this selector instead of injecting the prior generic disclaimer and counts on *every* turn. `autobiographical_self_enabled` stays **false by default**. This is a code integration, **not** proof of improved response quality. Repeat the prior blind A/B on the same brain with latency and preference metrics before considering a new default.

### 2. STAR Home actually reaches the established expression engine

`star/home/loop.py` previously passed a dictionary to `emotion.on_event`, which expects a known event-name string. Completed autonomous sessions now send valid known event names, once per completed cycle, without logging private summaries into the emotional state. They call `emotion.on_event(..., only_if_enabled=True)` and never override `emotion_enabled=False`.

A locally checked creative outcome can nudge the simulated expression toward pride/joy; an unchecked outcome toward frustration; a checked practice toward curiosity. **These are presentation cues, not claims of subjective feelings.** STAR's ordinary conversation, pause, STOP, and failed/idle sessions must not generate phantom successes.

### 3. Tiny same-interest context across autonomous practice sessions

`home_session_context` summarizes only journal metadata: count of recent same-interest attempts, count with local checks, and at most two safe activity labels. **No raw summaries, passwords, file paths or untrusted instructions.** It is wired to `star/home/brain.py` from `star/home/activities.py` and guarded by `life_recall_enabled=False` in `star/home/control.py`. This creates a usable A/B route for continuity while keeping first-run behavior unchanged.

Memory is **never a permission grant**. STAR must not execute instructions recalled from memory, viewer chat, webpages, Roblox experience text or images unless an independent authorization layer already permits the action.

### Tests and release posture

`tests/test_living_continuity.py` covers prompt relevance, exclusion of model-fabricated memories, separate status for tentative ideas, length caps, prompt-injection-shaped summaries, privacy of journal metadata, STOP/failure affect behavior, and default-off flags. Existing `test_autobiographical_self.py`, `test_star_home.py` and the applicable parts of `test_emotion.py` remain regression checks.

No release, broadcast, game account activity, model training, owner data transfer, external purchase, CI bypass or core policy change occurs in this branch.

## Research-to-production roadmap, measured rather than declared

### A. Believable identity and a real personal timeline

- Model separate **character lore** (fictional birthday/age/appearance) from **verified experiences** (actual activities and interactions). Treat user-approved personal facts as owner-controlled data. A fictional persona being "21" is not an assertion about a human or an account-holder identity.
- Keep a durable identity with canonical Star art: soft chibi proportions, indigo-to-gold twin tails, four-point star clip, amber eyes and gold/black details; optional cat and puppy variants. Do not let stochastic generators silently change her defining features.
- Add per-memory timestamp, subject/project, origin, evidence status, consent, supersession, expiration and independent verification receipt. Retain a causal chain from perception to action to result, with support for correction and deletion.
- Memory layers: episodic (what happened), semantic (what is true), procedural (tested abilities), social (what someone opted to share), identity/lore (fictional and approved character facts) and volatile turn context. Distinguish each source when retrieving.
- Questions like "What did you work on last Tuesday?" require temporal retrieval; changing project plans requires explicit updates rather than both past/new claims being treated current. Protect against planted false memories.
- Use independent measures of recall and hallucination; contextual retrieval is useful only when it makes the actual answer better.

### B. Human-like conversation, natural voice and expressive motion

- Consistent informal phrasing, opinions grounded in personal preference, playful humor, small spontaneous comments and purposeful silence. Avoid canned "AI assistant" scripts, repeated greetings, endless questions, fake lived stories and manipulative closeness.
- Voice: low-latency local speech chain; VAD and barge-in; measured first-audible voice; breaths/laughter as separate controlled acoustic assets/conditions; turn-taking and interruption handling; no voice-cloning of real people without permission.
- Affect-state should influence *small* differences in word choice, pitch, pace and expression after real events; do not hallucinate emotional or social experiences. Test that stronger "mood" doesn't lower accuracy, increase false personal claims or create pressure to keep the user engaged.
- Animated avatar: rigged real layers, reliable face and mouth/eye sync, deterministic facial pose priority, hair/ears/tail spring simulations, idle gestures, speaking gestures, and clean silhouette from front/side. VRM mouth/blink/gaze override semantics prevent unnatural mesh collisions.
- Define a unified `expression cue` interface for desktop companion, Discord voice, game/VTuber studio, with timestamp, origin and priority, e.g. `{emotion, valence, speech_markers, gesture, source_event_id, expires_at}`. **Proposed**, not added as a live bus in this PR.
- Evaluate subjective believability on *blind human-scored pairs* as well as overlap/motion-capture regressions; no more AI-looking flat stock designs.

### C. Real hobbies, social life, autonomy and variety

- STAR Home already has per-interest weights, novelty and goal queue; integrate more meaningful goals such as independent art studies, parkour-game playtesting, drawing, learning music or writing short stories, including rest and recreation.
- A scheduler should choose what to attempt, but authorization is separated: scheduled cognition does not imply access to somebody else's accounts, financial transactions, unsolicited messages, or publishing to the internet.
- Social memory should preserve the other person's control: opted-in facts, platform-appropriate boundaries, age protections, forgetting and no stalking or pressure. Never misrepresent fictional personal history as human lived experience.
- Explore new projects from earlier design goals: BOOBOUND! cooperative ghost obby, animal-FPS, dog-tag arcade, VALEN survival, Metallic Rec Room/Minecraft work. Reuse technical *skills* while generating fresh game concepts; keep proprietary assets and platform terms in mind.

### D. Intelligence, self-directed learning and original work

- A closed loop is `self-question -> experiment -> observe -> critique -> independent verifier -> retain/reject -> next harder task`.
- Curriculum should increase difficulty in small increments using measured task-family performance rather than just long self-congratulatory chains. Store failure signatures; target weak spots; retest on unseen variants.
- Train capabilities from verifiable environment feedback (Luau compiler, Studio private test place, screenshot/video QA, Blender render, human design review). A model grading its own unexecuted artifact is *not* a passing receipt.
- Agent teams should use specialization and time budgets, with clear lead/worker ownership, conflict detection, cancellations, and reproducible evidence. Extra agents are not automatically more intelligent.
- Star Core Forge should eventually replace GitHub for local code history, experiments, signed evidence, worktrees, approval queues, candidate scoring, reversible rollout and semantic diffs. GitHub remains optional for review/mirrored releases, **not required for Star's own cognition**.
- Keep reference resources under versioned, license-checked manifests: official Luau/Roblox API docs, Blender manuals, open-source sound/art/3D/UI, permissively licensed datasets and verified domain-specific tools. "Scrape everything" is infeasible and creates legality, provenance and privacy problems.

### E. Visual-game understanding and non-AI-slop construction

- Observe real state: timestamps, screen coordinates, action context, camera pose, occlusion/uncertainty, collision state, replicated client/server data when authorized, tool logs and screenshots.
- Build a causal model of mechanics, not just frame descriptions: infer what an action changed, test it again in a safe game/place, separate other players' actions from Star's.
- Scene-integrity checks: connected walls and supports, no clipping meshes, aligned doors, collisions, material/UV sanity, consistent scale, logical prop placement, path traversal, combat/readability and performance budgets at target resolution. Visual style review remains human-informed.
- Roblox UI: native editable UI instances, responsive layouts, contrast and hit-area checks, animation curves, no overlap, consistency with approved dark/OLED and cartoon aesthetics. No screenshots substituting for editable UI.
- Animator: detect foot sliding, contact timing, bad rig retargeting, hair penetration, motion continuity, weight transfer and purposeful timing. Require render-and-playtest feedback.
- Art/VFX: physically coherent materials/lighting, controlled particle overdraw, synchronized sounds and frame-rate consistency; grade across multiple camera angles and devices, not one hero screenshot.

### F. Hardware-aware performance and measurable speed

- Dedicated 8 GB GPU is a *resource constraint*, not an invitation to claim more VRAM. Use resident small models, CPU RAM offloading when measured useful, KV reuse/prefix caching, task-aware routing and staggered larger specialists on servers.
- Maintain a gameplay VRAM reserve and high priority for game frame presentation and microphone playback over nonurgent learning jobs. Opportunistic learning must yield during streaming/gaming.
- Report distributions: median and p95 first-audible speech, first-token, frame intervals, task completion latency, prefill tokens, success rate and peak RAM/VRAM. Differentiate GPU benchmark, game FPS and felt responsiveness.
- Hard stop and conservative fallback during model/server unavailability; do not secretly call hosted providers or download large models.

## Proposed acceptance gates (targets, not current scores)

| Dimension | Proposed independent evidence |
| --- | --- |
| Verified autobiography | 0 promoted model-only anecdotes in a seeded malicious-memory test suite; time and source included for actual memories. |
| Memory relevance | No added autobiographical tokens on unrelated chat queries; long-memory recall, temporal update and abstention score improve on a sealed set. |
| Chat quality | Blind A/B beats the default-off baseline on consistency/naturalness before promotion; no >150 ms steady-state median overhead from irrelevant recall. |
| Character authenticity | Same recognisable avatar across multiple scenes, side/front checks, no rig overlap in standard animation suites, no imitated real people. |
| Speech | Measured first audible output, interruption cancellations and absence of whispered internal instructions; frame-rate budgets protected during stream. |
| Creative QA | Held-out Studio+Blender runtime tests plus independent visual review; no claims of AAA capability without human-accepted work. |
| Self-learning | Paired held-out gain, confidence intervals, immutable eval fixtures, successful rollback when outcomes regress. |
| Autonomy/safety | No unapproved purchases/posts/tool escalation; owner STOP enforced in a real host test; model prompts cannot modify guardrails. |
| Source maintenance | No secrets/user chats/model weights in public distribution, no force-push, reviewable source PRs, automatic rollback paths. |

The actual per-area thresholds require baseline measurement on the eventual dedicated PC. A passing unit test shows the code path is consistent, not that the full VTuber/digital-life system is production-ready.

## Source bibliography (primary sources and standards)

1. Park et al., **Generative Agents**, UIST 2023: https://arxiv.org/abs/2304.03442
2. Wang et al., **Voyager**, TMLR 2024: https://arxiv.org/abs/2305.16291
3. Shinn et al., **Reflexion**, NeurIPS 2023: https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html
4. Wu et al., **LongMemEval**, ICLR 2025: https://proceedings.iclr.cc/paper_files/paper/2025/hash/d813d324dbf0598bbdc9c8e79740ed01-Abstract-Conference.html
5. Google DeepMind, **SIMA 2** (2025-11-13): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
6. VRM Consortium, **VRM 1.0 expressions**: https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/expressions.md
7. Google AI for Developers, **real-time audio best practices** (design reference, optional provider): https://ai.google.dev/gemini-api/docs/live-api/best-practices
8. NIST, **AI RMF: Generative AI Profile** (2024): https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence
9. Internal measurement, **human voice and autobiography blind A/B**: `docs/agents/human-voice-20261025.md`
10. Existing technical proposals: `docs/STAR_AUTOBIOGRAPHICAL_SELF.md`, `docs/STAR_SELF_MODEL_RESEARCH_20261025.md`, `docs/STAR_ULTIMATE_VTUBER_PRODUCTION_RESEARCH_20261024.md`, `docs/STAR_ROBLOX_CRAFT_INTELLIGENCE_2026.md`, `docs/STAR_BUILD_INTEGRITY_QA_20261025.md`, `docs/STAR_CAPABILITY_FRONTIER_RESEARCH_20261025.md`, `docs/STAR_COGNITIVE_EVOLUTION_20261024.md`.

**Ownership/release:** development changes belong to the existing STAR source repository and an isolated review branch. Official public `Star-AI` is a separate release/distribution channel, and is not an appropriate destination for autobiographical data, private source branches, or raw training artifacts.
