# Codex PR and integration audit, 2026-10-26

This is an integration status record, not a claim of a deployed or measured improvement.
After the current handoff was read, all further integration targets `star/next`; `main`
and releases remain owner-controlled. No further remote merges are part of this change.

## Completed and blocked work

- Before receiving the handoff clarification, the two non-draft PRs with passing
  checks, #558 (Night School evidence summaries) and #559 (optional Mobbin/OMP
  preparation), were normally merged to `main` with exact-head checks. No protection
  bypass, auto-merge, force-push or branch deletion was used. Both were already in
  `star/next`. This did not publish a release.
- The latest Linux checks are queued because their self-hosted Linux runner is
  offline. The laptop Windows runner is online; the two other Windows runners are
  offline. These are observations at audit time, not a continuing monitor.
- #608 has three regression failures involving the new `UNDERPOWERED` verdict
  versus existing `INCONCLUSIVE` expectations. #625 inherits those and has a
  background-stream pause failure. Evaluator, grader and regression changes require
  their independent review; no expectations or baselines were relaxed here.
- #626's type failure is in `stream_episode.py`: dictionary values typed as
  `object` were used to construct `EpisodePacket.action_ids`. The focused fix keeps
  a separate `list[str]` populated from the already typed action-group key. Packet
  contents, order, permission checks and evaluation rules are unchanged.
- #549 has a failed type check; #489 conflicts and includes release/authentication
  changes. #514 remains a draft integration PR, awaiting checks and independent
  review. Several older main-target PR branches are already ancestors of `star/next`.
- The streaming stack #626, #630, #634, #642, #652 and #655 requires dependency-order
  review and passing checks. Pending checks are not passing checks.

## Digital-life continuity, #644

The branch conflicts with the newer Home attention/interruption and inner-life
wiring in `activities.py`, `brain.py` and `loop.py`. Its bounded, relevant verified
autobiographical recall is still useful: the current opt-in desktop path supplies
generic self-description each turn. Its separate Home metadata recall remains off
until measured. A reconciliation patch was prepared outside the checkout and
validated against `star/next` using a separate temporary Git index.

The proposed integration keeps the new recall module and desktop/Home recall hooks,
preserves the session stop callback, and leaves current `loop.py` intact. The old
emotion-loop fix is superseded. Original exact-emotion-callback assertions are stale
against the newer strength/detail API; new retrieval/privacy/stop-coexistence checks
are needed instead of rewriting existing tests to disguise failures. No part of
#644 is claimed merged by this note.

## Voice-natural work and measurements

The local `star/voice-natural-20261026` branch at `4526cec5` has not been pushed and
has no matching remote PR at audit time. It adds opt-in opener variation and
reasoning-leak guards, including changes to `voice/persona.py` and `voice/call.py`.
It predates emotion wiring and must be reconciled deliberately. It does not provide
the adult social-persona selection requested in the handoff.

The sealed brain-1 evaluation was still running at the last read-only progress
check: 240 of 399 tasks, 11.41 hours elapsed. No task contents were read. No brain
workloads, deployment or restart were started. Emotion, recall and other candidate
defaults must remain unchanged until their documented measured decision rules pass.

## Validation

- `python -m pytest -q -p no:cacheprovider tests/test_stream_episode.py`: 9 passed.
- Pyright 1.1.414 on `star/stream_episode.py`: zero errors and warnings.

Native Discord, voice latency, avatar camera and the RTX 4060 computer were not
exercised by this audit.

## Adult peer voice gap

The adult social path now chooses a short peer persona only when the trusted
host's `emotion_partner_adult` is exactly `True`. Other calls retain their existing
persona. New age uncertainty, minor signals, explicit romantic refusals or a failed
trusted age recheck revoke that state for the rest of the call. An age claim inside
an unknown call cannot enable it. The Home callback applies existing social age
observation to committed transcripts and rechecks the remembered person.

For these peer calls, model reply speculation waits for a committed transcript so
discarded ASR cannot change friend memory. Speculative speech recognition remains
available. This is an unmeasured latency tradeoff, not an instant-voice claim.
Once revoked, romantic model sentences are replaced before TTS, streamed captions
and final history. Other safeguards and emotion defaults remain unchanged.

- Existing voice/Home/social regression selection: 194 passed in 79.77 seconds.
- Standalone adversarial checks with fake engines and temporary friend memory: 59
  passed, including strict truth values, age digits/words, refusals, callback
  failures, speculative/final observation, persistence, spoken output and history.
- The reproducible verifier is `python scripts/verify_adult_voice.py`: 10 checks
  passed on Python 3.12. Its inert engines are defined in the script; it does not
  import regression fixtures. It also checks a live host decision changing from
  allowed to disallowed between turns and proves a speculative age transcript
  leaves stored age unchanged until the final turn.
- Python compilation and whitespace checks passed. Targeted type analysis still
  reports existing Home locator and voice protocol findings; these were not
  suppressed or added to the baseline.

No real friend was contacted, no live credential was accessed and no model or
device was loaded by those checks. Refusal revocation is call-local; this change
does not introduce a new permanent relationship-preference setting.

## Independent integration fixes

- Home's microphone status check called `VirtualMicRoute.ready` as a function,
  although it is a boolean property. It now reads the property. Checks with the
  real route class and fake enumeration cover both present and missing routes.
  Existing senses/acceptance regression selection: 109 passed in 28.06 seconds.
- Wallet CLI inspection previously ran writable database initialization. Its new
  read-only connection uses SQLite `mode=ro`, requires an existing file, skips
  schema/default-row/permission changes and uses a read-only snapshot transaction.
  Temporary-database checks verified unchanged bytes and modification time,
  rejected writes, no missing-file creation and no initialization of an empty
  database. The simulation still passed; wallet Pyright reported zero errors or
  warnings. No actual funding or payment was attempted.

The final review covered the integrated Home/voice/watch changes and both detached
wallet/credential APIs. It found no further blocking issue in those APIs after the
read-only inspection fix. The hearing setup now catches reporting-callback errors
so they cannot skip owned capture cleanup. The model, devices, live account flows
and production provider connections still require separate acceptance checks.
