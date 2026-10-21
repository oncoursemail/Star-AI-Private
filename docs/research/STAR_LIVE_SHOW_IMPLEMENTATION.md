# STAR Live Show: implementation and verification

**Status: offline planner, opt-in. Updated 21 October 2026 UTC.**

The research blueprint defines a much larger animated production system. The code here is a small planning module with two entry points (below). It does not render, train a model, create animation, connect a channel, post anywhere or touch the network, and it does not demonstrate television-quality entertainment.

## Files and entry points

| File | Purpose |
|---|---|
| `star/live_show.py` | Standard-library episode validation, supplied-review checks, question selection, throughput and cost calculations, the agent tool gateway and a module CLI |
| `tests/test_live_show.py` | Module regression tests, plus the CLI subcommand, agent tool and Settings gate |
| `examples/live_show/pilot.json` | A 20-second timing sketch of the opening dialogue from Night Window's proposed Weather Report cold open |
| `docs/research/STAR_LIVE_SHOW_*.md` | Research blueprint, creative bible, YouTube appendix and this record |

Entry points:

- `star live-show <manifest.json> [--reviews F] [--questions F] [--post-episode]` (`star/cli.py`): an explicit request; reads only the named files and prints the report.
- Agent tool `star_live_show_plan` (`manifest`, optional `reviews`, both workspace-relative `.json` files). OFF by default: it is offered only when Settings > Workspace > "Plan live-show episodes" (`live_show_enabled`) is on, a workspace is selected and the prompt mentions a live show, episode manifest or playout plan.
- `python -m star.live_show <manifest>` adds the throughput and cost flags listed below.

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

## Not covered

Full application startup, model calls, media rendering, subjective audience tests, OBS interaction and a YouTube end-to-end rehearsal have not been run. The next implementation milestone is a real timed animatic using approved original visual and voice assets; after that, a persistent renderer and measured media inventory, before any live performer or channel controller.
