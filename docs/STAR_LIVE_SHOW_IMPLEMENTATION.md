# STAR Live Show: implementation and verification

**19 October 2026 UTC. Status: offline source foundation, ready for engineering review.**

The research blueprint defines a much larger animated production system. This change supplies a small, inspectable planning module that can support later work. It does not install a new STAR capability, train a model, create animation, connect a channel, or demonstrate television-quality entertainment.

## Files and entry point

| File | Purpose |
|---|---|
| `star/live_show.py` | Standard-library episode validation, supplied-review checks, question selection, throughput and cost calculations, and an offline CLI |
| `tests/test_live_show.py` | Focused regression tests for the new module |
| `examples/live_show/pilot.json` | A 20-second timing sketch of the opening dialogue from Night Window's proposed Weather Report cold open |
| `docs/STAR_LIVE_SHOW_RESEARCH_20261019.md` | Production architecture, current technical research, economics, rollout and primary sources |
| `docs/STAR_LIVE_SHOW_CREATIVE_BIBLE.md` | Original cast, performance language, episode premises, full cold-open draft and companion website specification |
| `docs/STAR_LIVE_SHOW_YOUTUBE.md` | Broadcast, chat, highlights, quotas, recovery and future live acceptance specification |
| `docs/STAR_LIVE_SHOW_IMPLEMENTATION.md` | This scope and verification record |

Run from the repository root using Python 3.11 or newer:

```bash
python -m star.live_show examples/live_show/pilot.json
```

The supplied sample returns `simulation: true`, `broadcasting: false`, `generated_media: false`, readiness `HOLD`, and playout recommendation `INTERMISSION`. Cost and throughput are `null` until the caller supplies inputs. No audience data or production measurements are invented.

The sample's cast, set, rig and voice IDs are proposed references. No corresponding assets are supplied. The 20-second JSON is a partial dialogue/timing example, not the complete 60-90-second cold open, a storyboard, or rendered media. Its timing is illustrative and must be replaced by measurements from actual recorded performances.

## Episode contract and review semantics

The version-one manifest contains show, episode and canon IDs, a title, cast references, and ordered shots. Each shot names a set, start, duration, present characters, and dialogue lines with offsets and durations. The parser rejects unknown fields, duplicate JSON keys and identifiers, unknown speakers, non-finite or invalid numeric inputs, invalid UTF-8, timeline gaps, overlapping shots and out-of-shot dialogue.

Inputs are bounded to 512 KiB, 16 cast members, 120 shots, 500 total dialogue lines, and 30 minutes. Shots may contain overlapping dialogue for intentional interruptions; the parser cannot decide whether the performance is intelligible. Structurally permitted zero-duration material cannot make an entire zero-duration episode ready.

Reviews cover `canon`, `visual_identity`, `voice_identity`, `timing` and `editorial`. Each supplied record has exactly these fields:

```json
{
  "check": "editorial",
  "manifest_sha256": "<SHA-256 of the exact manifest bytes>",
  "result": "PASS"
}
```

All five distinct checks must match the exact manifest bytes for a `READY` result. Missing, duplicate, rejected, unknown or stale evidence produces `HOLD`. Editing whitespace also changes the digest; persist the reviewed bytes rather than reconstructing JSON later.

These are caller-supplied records. `READY` means their fields are consistent; it does not authenticate a reviewer, confer permission, inspect an asset, or establish subjective quality. A production integration still needs independently controlled review provenance and final-media/asset-content hashes. Changing the contents behind an unchanged asset ID is not detectable by this module.

## Audience questions and completed episodes

Question records contain `question_id`, `show_id`, `episode_id`, `manifest_sha256`, `text`, `approved_text_sha256`, `moderation_status`, `approved_at` and `expires_at`. The last two fields use Unix seconds. A supplied approval must match the exact text, current episode bytes and scope; it must be active at selection time and expire within one hour of approval.

The selector inspects the complete bounded batch of at most 100 records before applying its one-to-five-question limit. Identical valid duplicates collapse. Conflicting or invalid versions exclude that question ID regardless of ordering, including a later rejection. Repeated text is deduplicated after case and whitespace normalization. Viewer text remains text and is never executed.

This is selection from external moderation records, not a moderation classifier, authenticated approval service, YouTube listener, response generator, or guarantee that an answer is suitable. The future controller must supply trusted records, episode-boundary state and a clock, then apply an independent gate to the resulting spoken answer.

Before an episode, supplied ready evidence can produce the offline `EPISODE` recommendation. After a completed episode, eligible questions produce `Q_AND_A`; otherwise the result is `INTERMISSION`. Completed-episode mode does not recommend the same episode again. A future queue owner must explicitly choose the next episode and track actual playback completion.

## Capacity and cost calculations

Accepted throughput is usable media seconds divided by elapsed wall seconds. The target is the new-content duty cycle multiplied by one plus the requested headroom. The default 25% reserve matches the blueprint's initial planning target; it is configurable and has not been established as sufficient for this production.

When the accepted rate falls below consumption, the reserve estimate is buffer seconds divided by the difference. This assumes constant rates. A healthy average does not prove tolerance of stalls or long-tail render latency. The generation-only cost function multiplies provider price, new duration and paid-take multiplier, including successfully generated takes rejected by editorial review. It omits other costs described in the research report.

Optional CLI inputs include paired `--accepted-seconds` and `--wall-seconds`, `--buffer-seconds`, `--duty-cycle`, `--headroom`, `--price-per-second`, and `--paid-take-multiplier`. Values supplied by the caller remain estimates or observations from that caller; the CLI does not run a benchmark or obtain a bill.

## Verification actually performed

The final focused check on 19 October 2026 used:

```bash
python3 -m unittest discover -s tests -p test_live_show.py -v
python3 -m compileall -q star/live_show.py tests/test_live_show.py
python3 -m star.live_show examples/live_show/pilot.json
```

All 12 test methods passed. Compilation passed. The CLI returned the honest offline state described above. Coverage includes changed content invalidating review, malformed input, bounded numeric calculations, approval scope/expiry/text binding, conflicting question versions, completed-episode behavior, and the empty default state.

An independent review identified and corrected two defects before the final run: completed episodes could be recommended again, and an early question-selection limit could miss a later rejection. Focused regressions preserve both fixes. The reviewer's additional mutation probe found no unexpected exceptions in 756 manifest mutations; this is supplementary evidence, not exhaustive fuzzing or production certification.

Local validation used an isolated partial snapshot of current repository files. Full application startup, Windows checks, model calls, media rendering, subjective audience tests, OBS interaction, and YouTube end-to-end rehearsal were not run locally. Existing authentication, policy, release workflows, other feature branches and evaluation harness files are outside this change.

### Subsequent repository CI

GitHub CI checked code commit `879ba66d9bca2a947fd3200bb4517ad573fec0bb` in [draft PR #492](https://github.com/oncoursemail/Star-AI-Private/pull/492). The [offline Python job](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39198072292/job/117885127876) passed: 9,635 tests passed, 90 were skipped, and 38 subtests passed. Compilation, correctness linting, the type baseline gate, protected-file checks, and Luau checks also passed. A constructor typing diagnostic found in the first CI run was corrected without changing the schema or runtime behavior.

The [React desktop-assets job](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39198072288/job/117885121851) passed its build and verification step, including 562 frontend tests across 63 files. The separate [React UI job](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39198072292/job/117885127603) also passed its typecheck/build and screenshot-capture steps. Both jobs then failed to upload artifacts because GitHub reported that artifact storage quota had been reached. Overall CI is therefore not fully green; subsequent Windows/release jobs were skipped. These logs establish successful checks of source behavior, while the artifact-upload blockage remains outside this feature's code changes. No unrelated artifacts were deleted or billing limits changed.

The next implementation milestone is a real timed animatic using approved original visual and voice assets. After that, connect a persistent renderer and measured media inventory before enabling a live performer or channel controller.
