# STAR Creator Studio — integration map and source of truth

**Updated 2026-10-24.** This is a GitHub project handoff, NOT a claim that STAR can currently stream, learn arbitrary games, mimic human biology or publish to a platform. All existing owner-approved STAR appearance and safety requirements remain unchanged.

## Where the complete work lives

| Owner goal | Repository artifact | Honest status |
| --- | --- | --- |
| Original premium Star 2D/3D VTuber design, flowing twin tails, eyes/face/cloth/ears/tail physics | docs/STAR_ULTIMATE_VTUBER_PRODUCTION_RESEARCH_20261024.md | Research/production specification |
| Consistent cute Star personality, anime-like original fictional history, real verified episodes, cat/puppy modes, emotes and streaming brand | docs/STAR_CHARACTER_AND_CHANNEL_BIBLE_PROPOSAL_20261024.md | **Fiction is a proposal**, not approved existing history |
| Long-form research: conversational humanlike performance, games, memory, streaming, creator software | docs/research/STAR_STREAMER_HUMANLIKE_FULL_RESEARCH_20261024.md | Research archive |
| Long-form autonomous game-playing agent and architecture | docs/research/STAR_AUTONOMOUS_GAME_STREAMER_FULL_RESEARCH_20261024.md | Research archive |
| Discoverable STAR read-only VTuber planning skill | star/skill_packs/vtuber-creator-studio/SKILL.md | Bundled skill reference; not a tool, not enabled automatically by skill-pack trigger routing |
| Premium rig voice/eye/cloth/twin-tail signal prototype | frontend/src/vtuber/performanceMotion.ts, performanceMotion.test.ts | Numeric simulation only; not drawn, played or wired |
| Moderated chat, game-focus speech scheduling, Twitch overlay restrictions, fictional/real provenance, owner go-live plan | star/streamer_creator.py, tests/test_streamer_creator.py | Offline pure-Python contract, no platform login |
| Real PCM waveform envelope, externally tagged laughs/purrs/meows/woofs | star/streamer_media.py, tests/test_streamer_media.py | Offline PCM analysis, not voice synthesis or audio capture |
| Source-backed long/short highlight rough-cut planner | star/streamer_media.py | Non-destructive **edit decision list**, no video rendered/uploaded |
| Event-backed stage intention, cancellation and learning holdout checks | [draft PR #580](https://github.com/oncoursemail/Star-AI-Private/pull/580) | Separate draft; NOT merged into this branch |
| Existing WebGL skeleton, animator, spring hair/ears/tail | [PR #549](https://github.com/oncoursemail/Star-AI-Private/pull/549) and [issue #551](https://github.com/oncoursemail/Star-AI-Private/issues/551) | Existing feature work, owner visual acceptance outstanding |
| This Creator Studio branch | [draft PR #582](https://github.com/oncoursemail/Star-AI-Private/pull/582) | Awaiting human review, not production installed |

**No migrations or imports from unfinished branches are assumed.** Avoid adding implicit dependencies on #580 or #549 until both are independently reviewed and conflict-resolved. No auto-merge or public release.

## A complete, functional end-state

1. The trusted human owner configures permitted game windows, privacy boundaries, avatar/voice settings, private test streams, platform OAuth and moderation. Chat/game/model text cannot grant those capabilities.
2. The capture/control game engine observes the permitted game; keeps motor control on separate low-latency process; records input/game results as independently verified events.
3. The strategic layer selects tactics and verified tasks, while the learning system records real attempts and promotes only reviewed measurable improvements; tests include untouched seeds.
4. The attention scheduler selects a fresh, moderated viewer question only when gameplay is safe; the stage-intent director decides whether to react with short speech, laugh, silence, gaze or body movement.
5. The speech runtime produces actual original-voice PCM, verified laughter or purr/woof audio. Audio playout timestamps drive lip/jaw amplitude, cheeks, eyes, head, shoulders and spring hair across every animation frame.
6. The production model uses original editable art and actual bones/meshes, compliant licensing, collisions, physics and native GPU quality tests. Studio companion rig and broadcast VTuber rig may be different sizes but preserve Star's silhouette.
7. The recording service verifies completed real video files. Source-backed timestamps create a first-pass edit timeline; an editor renders 16:9 and 9:16 drafts, generates captions and original thumbnails, and presents non-destructive owner review.
8. Each stream platform has its own legally supported API/scopes and output scene. A human confirms first broadcasts, uploads and eventual permitted scheduling. Recovery after a power loss defaults to **OFFLINE**, never auto-goes-live.

## Exact future connectors and work items

| Connector | How it must be introduced | Current gate |
| --- | --- | --- |
| Twitch EventSub | Owner OAuth, subscription, chat moderation and platform-only on-screen chat scene | No tokens, no account link |
| YouTube liveChatMessages.streamList | Owner OAuth, moderated message intake, resume tokens and per-output chat | No tokens, no live chat |
| TikTok LIVE | Owner eligibility and approved documented LIVE integration; avoid account-cookie scrapers | API/access not verified |
| OBS WebSocket v5 | Authenticated localhost, verified scene/capture/recording state, explicit start/stop | Existing manual clip pilot elsewhere, not new auto-broadcast |
| Qwen3-TTS or Chatterbox Turbo | Original synthetic voice audition, legal/licensing review, GPU tests; preserve Kokoro fallback | Not installed as streamer voice |
| Live2D/Inochi2D | Legal SDK and original layered art proof, owner animation review, Windows/OBS performance | Art and high-res rig not ready |
| PySceneDetect/WhisperX/FFmpeg/OpenTimelineIO | Sandboxed local video/editor pipeline and real playable input files | Research; new EDL only |
| Game controller | Permission-scoped original offline game, no multiplayer exploits | Not connected |

## Explicit safety promises

- **No unreviewed auto-go-live, API tokens, account creations, live platform writes or stream/public uploads.**
- **No secrets, stream keys, private user details, pretrained weights or private copyrighted third-party art in Git.**
- **No unsupported inference that PCM magnitude is laughter, or that generated story lore actually happened.**
- **No automatic acceptance of AI self-evaluation, or invented game clips/results.**
- **No claiming a source-only program is a working VTuber model or reliable editor.**
- **No unauthorized voice imitation or copied character assets.**
- **No merge to main until normal green full-repository CI, owner art/voice review and real Windows acceptance.**

## Local isolated checks

Run at repository root:

~~~sh
python -m pytest -q tests/test_streamer_creator.py tests/test_streamer_media.py
python -m compileall -q star/streamer_creator.py star/streamer_media.py
cd frontend
npm ci
npm test -- src/vtuber/performanceMotion.test.ts
npm run build
~~~

A scripted unit test is not evidence of an actual running game, a live mic/laugh, 60 FPS graphics, a recorded MP4, a successful platform broadcast or an audience. Run dedicated native demos for those gates.

## Owner acceptance milestones

- **M1:** Original editable layered Star turnaround art, color accuracy, black-gold flowing twin tails, genuinely attached accessories, animal mode art, high-resolution face/eyes.
- **M2:** Rig 60 FPS live in an actual capture of game + OBS with coherent laughing shoulder/hair/eye/mouth and audio, quality graded by the owner.
- **M3:** Real PCM voice/laugh audition with measured p95 responsiveness and natural human-listener feedback; no copied real-person voice.
- **M4:** Read-only, moderated single-platform chat rehearsal; later safe game-focus interruption, custom original channel emotes and branding.
- **M5:** Original offline game played using screen/controller, holdout success measured, lessons stored and reviewed.
- **M6:** Actual source-backed horizontal and vertical edited videos with coherent narrative, captions, music rights and preview sign-off.
- **M7:** Owner-approved private stream and then single-platform public launch; only afterward review eligible cross-platform simulcast and optional recurring scheduler.

This document is the coordination entrypoint for the **proposed Star Creator Studio**. It does not change STAR's tool allowlists, provider routing, published installer, or owner-approved existing character design.
