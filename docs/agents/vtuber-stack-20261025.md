# VTuber stack #619 + #621 + #622 (Claude, 2026-10-25)

Branch `star/vtuber-stack-20261025` = origin/star/next 53ef0485 + merge of #619 (e27c987c), #621 (0d0e1287),
#622 (3d2799f4) in that order. All three merges were clean (no conflicts). ChatGPT is out of credits, so Claude
reviewed and landed the stack as one PR into star/next.

## Verdicts (quality and safety review only)
- #619 verified active game practice + stream pressure pacing: LAND, no change. `ActivePracticePlanner` is disabled
  until `enable(owner_approved=True)`, never plays or authorizes anything, reads only signed PRACTICE aggregates
  (`practice_evidence` skips validation/holdout rows but checks every row's receipt, a corrupt row fails closed);
  finish() needs both a fresh trial count and `signed_practice_run` for the reserved run id. `StarStage.prepare(telemetry=)`
  turns measured pressure (game fps < 50, voice backlog > 250 ms, live and VRAM < 1536 MiB) into `gameplay_critical`,
  so only `owner_interrupt` and `game_danger` stay eligible (tested). Default `telemetry=None` = old behaviour.
- #621 grounded signed stream episode: LAND, no change. `StreamEpisode` is off until `start(owner_approved=True)`,
  accepts only a trial that equals the stored signed PRACTICE row (`verify_practice_trial`), replay-safe `_seen` set,
  session-scoped, `public_packet` needs `broadcast_approved` plus a curated action allowlist, packet is aggregate symbolic
  IDs only (no run ids, receipts, timestamps), capped at 1350 chars, only attached to game_observation / game_success /
  viewer_question prompts, never to danger warnings or idle banter.
- #622 host-VAD turn-taking gate: LAND, no change. Barge-in logic checked by reading and by the 10 tests: a request to
  interrupt (`should_interrupt`) needs an echo-cleared frame, owner probability >= .75 with guest < .75, sustained >= 120 ms
  of contiguous frames (gap > 150 ms resets), a fresh frame (<= 250 ms) and `star_speaking`; one spike, uncleared echo,
  mixed owner+guest labels and stale VAD never interrupt (they hold); `TurnAdvice` refuses should_interrupt on any other
  action. Guest voice only holds. The host still has to call `StarStage.interrupt()` (the test does).

## Safety / default checks
- Everything new is disabled by default and adds no model call, no latency and no thread: pure host-fed libraries.
  Nothing in the app imports them yet (only tests and `examples/stream_stage_rehearsal.py` use StarStage), so there is no
  on-by-default path to measure. Wiring them into a live stream runtime is future work, not done here.
- `git diff origin/star/next` scan for private IPs, host or user names, keys, tokens: none (only the word "token" in
  research prose and a fixture string "not-a-real-secret").
- No vacuous tests found (0 `assertTrue(True)`, no skips); tests assert behaviour such as danger preserved under pressure
  and the owner barge-in cases above.

## Noted, not changed (smallest-change rule)
- `TurnTakingGate.metrics()["owner_yields"]` is incremented on every `advise()` call that returns a yield while Star is
  speaking, so it over-counts if the host polls per frame. Metric only, not a safety issue.
- Any `TurnAdvice.hold` (including `vad_missing_or_stale`) is mapped to `viewer_speaking`, which also mutes `game_danger`
  and `owner_interrupt` replies. That is the pre-existing meaning of `viewer_speaking` and is fail-closed; the host decides
  whether to pass `turn` at all.
- Pressure thresholds in `StarStage.prepare` (fps 50, backlog 250) differ from `stream_budget.advise_workload` (45 / 350).
  Different purposes; both are heuristics, none measured on a real stream.
- The three research docs under docs/research/ say explicitly that nothing was measured; no performance claim to remove.

## Commands run (worktree `worktrees/vtuber-stack`)
- `git merge origin/feat/...` x3 in order: clean.
- pytest (venv `worktrees/pr39/.venv-audit`, temp APPDATA), 12 files: test_active_practice, test_gameplay_skill_bank,
  test_learning_accelerator, test_stream_budget, test_stream_director, test_stream_episode, test_stream_knowledge,
  test_stream_observe, test_stream_persona, test_stream_stage, test_stream_stage_pressure, test_stream_turntaking:
  175 passed, 113 subtests passed (5.9 s). Full suite not run (lead runs it in the merge queue).
- `ruff check` on the 5 touched source files and 4 new test files: all checks passed.
- `git diff origin/star/next --check`: no problems.
- pyright not installed in that venv: not run.
