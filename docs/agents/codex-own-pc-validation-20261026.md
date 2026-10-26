# Own-PC preview validation, 2026-10-26

The local bundle is a source installation preview for the dedicated PC, not a public release or evidence of native acceptance. It is built from committed allowlisted source/assets; its manifest records the exact commit and every file hash. Models, native drivers, account sessions and user databases are not embedded.

## Verified locally

- The existing Home/installer/acceptance/wiring and VTuber selection passed **238 tests** on the combined source. The original larger run is recorded separately in `codex-handoff-validation-20261026.md`; it was not fully green and is not recast as such.
- Editable art passed **77 offline checks** covering real ORA layers, replay/composite equality, preserved inputs, STOP, bounded plans, no-op rejection and model-generation gates. Tiny synthetic rasters are fixtures, not artistic samples.
- OBS setup passed **14 fake-OBS tests**, including idempotence, selected virtual devices/game windows, output-idle checks, source isolation, partial cleanup failure and suppressed SDK password diagnostics. Starting/Gameplay/Ending overlays were rendered and visually inspected at 1920x1080. Standalone browser screenshots do not prove OBS custom-origin behavior or a live stream.
- PC audit/cleanup passed **57 checks** using mocked startup entries/probes and synthetic encrypted backups. No settings or apps on the development PC were changed.
- Avatar expressions passed **18 checks**, including the actual camera feed/tick path, stale cues, blinks/visemes, expiry, repeated-cue limits and stop. Mode checks exercise rooted settings, dog/puppy alias, live frame changes and honest missing-art reporting.
- Home chat passed **17 fake checks** for tool-free context, moderation, deletion/STOP/interruption/private-call races, cooldowns and failure handling. Another **8 playback-boundary tests**, with fourteen late-invalidation cases, reproduce ordinary voice playback's unsafe late-queue behavior and verify that this bridge refuses that path. The dedicated native public-audio implementation is still absent.
- Twitch EventSub passed **14 offline protocol cases** covering token identity/scope checks, queue lifetime/deletions, keepalive, abrupt reconnect, server migration, revocation, endpoint restrictions and dedupe overflow. Independent review reproduced and fixed a tombstone-eviction edge case; overload now clears pending chat and pauses admission until old notifications age out. No live account connection was made.
- Installer verification exercises its actual PowerShell functions and full preview with mutation commands blocked. Uninstall preview does not remove shortcuts. Failed hash verification makes one verified install attempt and stops. Independent review tested encoded elevation with quoted/hostile-looking paths and switch/array parameters, and found/fixed self-copy, exit-code and false running-status issues.
- Credential helper **73 checks**, allowance ledger **69 checks**, watch hearing **22 checks** and adult voice **10 tests** remain passing on fakes. No real vault entries, money, messages or app input were used.
- Whole-source Ruff, compilation and whitespace checks pass. A package-free Pyright comparison records **577 errors in both the previously reviewed source and this source, with no increased file/rule counts** at the checkpoint. The repository-wide type backlog is not green; new modules are checked without suppressions or baseline edits.

## Reviewed fixes

Independent agents reviewed installer safety, OBS protocol/privacy/failure paths, painting integration, facial event timing and the chat speech boundary. OBS browser sources now allow same-origin local art and explicitly enable custom 30 FPS. Cleanup attempts cannot skip microphone/camera deactivation after one stale scene-item error. The SDK's own connection logging is suppressed before it can print a password. The chat bridge requires a dedicated cancellable speech hook rather than using shared private-call audio.

The newer voice PR 664 remains unintegrated after independent synthetic reproductions found a partial reasoning-display leak and a suggested opener rejected by existing speech filters. Its conflicts and exact reviewed head are recorded in `codex-pr664-review-20261026.md`.

## Outstanding acceptance

No native RTX 4060, virtual microphone/camera, real Krita editing round trip, Comfy generation, authenticated Twitch/Discord session, live chat moderation, public speech playback or sustained OBS/game/speech benchmark ran here. The new cat and puppy illustrations are flat concept assets, not separated production model artwork or a Live2D rig. The approved mascot remains the runtime default.

No bank/card provider is connected; money execution remains absent. No new accounts or external friendships were created. Personality and emotion behavior do not establish human consciousness. Existing emotion/recall evaluation gates remain disabled until their own evidence passes. The active sealed evaluation/model server was not restarted or loaded with new work.

The last observed GitHub integration checks were queued on unavailable runners, with the protected-closure check passing. Local checks are not reported as GitHub CI results. PR 658 remains the reviewable integration target against `star/next`; no new merge to `main`, deployment or public release is claimed.
