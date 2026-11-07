# Own-PC autonomy hardening, 2026-10-26

This change prepares a more reviewable first session on the dedicated PC. No target-PC deployment, real account sign-in, contact, message, voice-device capture, game session, public stream or payment was performed. The sealed brain evaluation was not restarted or changed by this work. Emotion and inner-recall defaults remain unchanged.

## Changes

- Home now schedules voice, call, camera and registered game cleanup independently. A blocked cleanup cannot hold all other resources hostage. Duplicate in-flight cleanup is suppressed; failed callbacks remain available for retry. New work stays blocked through pending or failed cleanup after STOP, including an early owner resume.
- Late synthesized speech is discarded after cancellation or call handoff. Call cleanup is identity-aware, so an old call cannot clear its replacement. Preview prevents native game factories, Home voice and camera startup while preserving planning.
- Requested and resumed activities respect GPU eligibility without losing deferred work. Invalid outcome dictionaries become failures rather than verified success. Game sessions close on STOP, completion and exceptions; ordinary attention pauses preserve a continuation and use a fresh session on resume.
- Social lookup no longer invents reciprocity. Private inbound observations record it explicitly. Handle ownership, non-recycled IDs and serialized SQLite operations prevent local identity corruption; forgetting remains effective. New fact/moment writes skip recognizable credentials and payment details. This is incomplete sensitive-data detection, not a universal guarantee.
- The owner has a preview-first social/game configuration command. Minecraft has a separate device-code connection check, bound to an enabled, named saved profile on an explicitly allowed server. Login codes stay in an explicit owner console callback; results omit them. Normal game startup reuses its protected local cache path.
- STAR-LIVE-TEST.md provides the supervised device, input, voice, game and STOP sequence. Packaging includes the owner setup modules and review notes.

## Validation and review

The existing combined selection passed **198 tests**: Home wiring, Home runtime, social games, VTuber camera and voice call. After independent review found a blocked capture closer could delay call cancellation, cleanup was reordered to flush the pinned speaker and stop its session before capture closers. The relevant existing Home/voice/natural-voice selection then passed **83 tests** on the final source. The new standalone verifiers passed **116 cases**: 31 recovery, 26 voice lifecycle, 19 social lifecycle, 25 Minecraft setup and 15 root integration. They use synthetic state and injected transports/devices; see each linked review note for the retained cases and limits:

- [Recovery and game cleanup](codex-autonomy-recovery-20261026.md)
- [Voice lifecycle](codex-home-voice-lifecycle-20261026.md)
- [Social lifecycle and primary platform research](codex-social-lifecycle-20261026.md)
- [Minecraft owner sign-in check](codex-minecraft-setup-20261026.md)

The root integration verifier additionally covers preview/configuration preservation, bounded profiles, lookup and forget behavior, independent cleanup, retry/error paths, early resume and stale unregister handling. An independent agent reproduced the blocked-closer issue, rechecked the fix and passed the scoped final source review. Existing tests, evaluation fixtures and grading baselines were not edited. Ruff, compilation and whitespace checks apply to the changed source and new verifier scripts. Package-free Pyright 1.1.414 reports 571 errors versus the previous 577, with no increased per-file/per-rule error counts. Full-repository static typing remains unclean.

## Remaining live evidence and capability gaps

Native STOP latency, device capture, audio routing, Microsoft account authorization, process exit, actual game progress, delivery and sustained GPU load need the target PC. A returned transport close method is not independent process-exit evidence. Blocking native calls do not gain hard preemption from this Python cleanup design.

Current social adapters do not prove immutable platform identity or send/confirm friend requests. The proactive contact planner has no delivery loop. Discord user automation and Roblox restrictions are documented with primary references in the social review; no GUI-policy exception is claimed. Twitch public speech remains unwired. The new cat/puppy artwork remains flat concept art awaiting production layers and rigging. This build does not establish consciousness, human feelings, general computer competence or unrestricted independence.
