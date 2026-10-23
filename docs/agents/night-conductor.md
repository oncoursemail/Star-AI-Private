# night-conductor-20261017 (claude): STAR writes its own practice tasks at night

Branch `star/night-conductor-20261017` -> `star/next`. Code: `server/night_school/nightschool/conductor.py`
(+ `RealModel.complete` in real.py, `conduct` command in `__main__.py`, settings in config.py), units
`server/night_school/star-night-conductor.{service,timer}`, tests `tests/test_night_conductor.py` (23).

## What a cycle does (free local models only; nothing leaves the server)
1. Reads `data/failures.jsonl` (bounded tail, rows newer than the last cycle, validation-slice failures left out so the
   gate stays a fair test), groups them by category + first failed check, takes the 4 biggest groups.
2. Per group: one model call -> `DIAGNOSIS:` line + 1-3 NEW, smaller practice tasks. Plus 2 "ideas" calls (4 tasks each)
   from `docs-recent/*.md` (notes changed in the last 2 days, copied by deploy.sh; paintball/pb- notes skipped) and the
   benchmark categories. Plain-text format with `:::` separators and a fenced reference solution (not JSON: local models
   break on escaped code).
3. Validators (all must pass, else a counted reason in the report): format/length/blocked words (paintball, rec room,
   golden, holdout, key/token words, private addresses) -> regexes compile and are not nested-quantifier -> loader
   (`star.evals.load_catalog`, `validate_tasks`) and the evaluation-copy guard (`forbidden-prompts.json`) via
   `load_pool` -> static Luau check of the reference (knowledge service) and the task's own `score_answer` on it ->
   negative control (`print('hello')` must FAIL the task) -> Roblox API checker (`check_luau_api`, bundled dump) ->
   duplicate: same id/prompt hash or word-set overlap >= 0.72 with any pool task or earlier accepted task.
4. Accepted tasks go to `pool/conductor-YYYYMMDD.json` (night of the local date the night began), at most 40 a night
   (STAR_NS_CONDUCTOR_MAX_NEW), 12 a cycle. Night school reloads the pool between batches. Reference solutions are kept in
   `conductor/references-YYYYMMDD.jsonl` (not in the pool).
5. Report: `conductor/report-YYYYMMDD.md`, `report/conductor-latest.md`, one line `conductor/summary.txt`. There is no
   board on the server, so the one-liner is posted to the board from the PC by hand/`star msg`.

## When it runs
- In the night-school loop after every batch (`conductor.after_batch`; never raises), and from the timer
  `star-night-conductor.timer` (`*:10,40`, oneshot `python -m nightschool conduct`, Nice 19, idle I/O, CPUWeight 5).
  Both ask `due()`: inside the window (18:00-09:00 owner-local = UTC-5 by default, STAR_NS_CONDUCTOR_TZ_HOURS), not
  within 30 min of the last cycle, not switched off. An flock keeps two from running together. When the loop is working
  the timer run finds the brain busy (waits up to 25 min, then does nothing) - the loop's own hook then runs it.
- Politeness is night school's own: idle gate / HOLD file / quiet lock, `id_slot` pinned (never slot 0), request
  cancelled the moment another client appears (owner chat always wins).
- Models: `STAR_NS_CONDUCTOR_MODELS` = `star-deep,star-fast`, tried in order, but a model is used only if it is LOADED and
  has a slot other than 0. **star-deep runs `--parallel 1` (only slot 0 = owner chat), so today every call goes to
  star-fast slot 1.** Giving star-deep a second slot (parallel 2) would make the conductor use it automatically.

## Switch off / pause
- `touch /opt/star/learning/data/CONDUCTOR_OFF` (no restart; delete to resume), or `STAR_NS_CONDUCTOR=off` in
  `/opt/star/learning/env` + restart star-night-school, or `systemctl disable --now star-night-conductor.timer`.
  HOLD file pauses everything. Rollback of the deploy: `app.bak-20261017-pre-conductor` (copy back, restart) and
  `data/state.json.bak-20261017-pre-conductor`.

## Not done / limits
- Per-worker solved/failed in the report is this server only (attempts.jsonl has no worker field); the PC turbo and
  server 2 keep their own reports. Server 2 and the PC do not run a conductor; the PC receives the new pool file
  with its session-start copy of server 1's pool.
- Generated tasks have pattern + Luau-check scoring only (no unit tests); they are as strong as their regexes plus a
  reference that must pass and a trivial answer that must fail.
- `docs-recent` is a snapshot made at deploy time; after 2 days without a redeploy the ideas calls use categories only.

## Real run (server 1, 2026-10-17, window forced open with STAR_NS_CONDUCTOR_WINDOW=00:00-23:59; real time was 10:30 local)
- Run 1: created 19, accepted 0 (parser too strict: backticks around ids/regex, `forbid: none`). Run 2: created 19,
  accepted 0 (a prose `forbid:` line made the whole block "bad"). Both found by `conductor/rejected-YYYYMMDD.jsonl`
  and the raw reply; fixed in the parser (commits 355fa7fd, 277c2192).
- Run 3 (final code, 17 min, 6 model calls on star-fast slot 1): **created 18, accepted 8, rejected 10** (all 10: the
  model's own reference failed its own require patterns). Pool 642 -> 650 tasks, 0 dropped, loaded by `validate-pool`.
  Report: `/opt/star/learning/conductor/report-20261017.md` (copies of runs 1-2: run1-report.md, run2-report.md).
- Deployed: app backup `app.bak-20261017-pre-conductor`; units in /etc/systemd/system; timer enabled, `*:10,40`.
  The cycle takes about 17 minutes of star-fast; accept rate is limited by the model, not the validators.

## Ideas not done
- One repair round: feed a failed reference check back to the model once (probably doubles the accept rate).
- Send the unaccepted-but-diagnosed clusters to the PC conductor / Codex for stronger tasks.

## Status log
- 2026-10-17 15:50Z PR #476, deployed, first real cycle done.
