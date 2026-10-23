# star-finetune-20261018 (claude): more verified data, apprentice v2, embedding A/B prep

Board item #175. Branch `star/star-finetune-20261018` (worktree `worktrees/star-finetune`, from origin/star/next
798d88e7). Local data (not in git): `work/ft18/` (copies of the night-school data), `work/apprentice/` (pilot + v2).

## 1. Data: verified worked examples (measured 2026-10-18 07:40Z)
Sources: server 1 `data/examples.jsonl` (324 rows), server 2 (49), PC GPU turbo `%LOCALAPPDATA%\STAR-night-turbo\ns\data`
(216 rows on 77 tasks). One example per task after dedupe (count script `work/ft18/count.py`):
- **426 unique verified tasks** (s1 only 300, PC only 77, s2 only 25, s1+s2 24); 572 distinct (task, answer) pairs.
  8 of them are PRIVATE paintball/river tasks (local training only, never in a public file).
- Families: ledger (generated) 196, roblox-* 41, luau 21, economy 18, obby 15, npc/ui/remotes/world/combat/datastores
  13 each, rounds 9, river 8 (private), security 8, others < 7.
- Pool 671 tasks, 245 never solved (practice-tasks-round-lifecycle 0/12, security 4/20, beginner 11/30, debugging 15/37).
- New unique verified tasks per day (all workers): 10-15 45, 10-16 166 (PC turbo's first night), 10-17 56, 10-18
  (to 07:40Z) 16. Baseline ~**56-89/day**.
- Night conductor night of 10-17 (before this change): 5 cycles, created 85, accepted 29 (34 %), cap 40 not reached.
  Rejects: mostly "reference fails its own task" (the model's reference misses its own patterns) and format.
- Bottlenecks seen: (a) one example per pool task, so growth = new tasks + solving the 245 hard ones; (b) server-1
  night school waits "brain busy" since 05:15Z (other clients on the brain + another agent's quiet lock).

## Deployed (server 1, container starai)
- 07:46Z `app/server/night_school/nightschool/conductor.py` (this branch): each cycle also asks for **variants of 4
  recently solved tasks** (2 calls; non-ledger tasks preferred, river/paintball skipped) and gives a reference that
  fails its own checks **one repair call** (at most 4 a cycle; the repaired reference must pass every validator
  again). Calls per cycle 6 -> 8 (+ repairs), accepted per cycle 12 -> 16. Report shows accepted by source and repairs.
- `env`: `STAR_NS_CONDUCTOR_MAX_NEW=80` (was default 40). Timer runs read env + code fresh each start (no restart
  needed); the night-school loop (after-batch hook) still runs the old code until restarted under the quiet lock.
- Undo: `cd /opt/star/learning && cp env.bak-20261018 env && cp app/server/night_school/nightschool/conductor.py.bak-20261018 app/server/night_school/nightschool/conductor.py`
  (then restart star-night-school if it was restarted with the new code).
- Also fixed: `run_cycle` used the wall clock for the first failure cut-off instead of `now` (the existing cycle test
  failed from 2026-10-18 on).
- 08:58Z server 1 also got `config.py` (new STAR_NS_CONDUCTOR_TAG setting; backup config.py.bak-20261018).
- **PC GPU turbo now runs the conductor too** (08:57Z): `worktrees/ns-pc` checked out (detached) at this branch's head.
  Its star-fast has one slot; with STAR_NS_SLOT=0 the model server is night school's own, so the conductor may use
  slot 0 there. Its tasks go to `ns/pool/conductor-pc-<night>.json` and are copied into server 1's pool (tmp + mv) before
  each pool sync and at each merge, so every worker gets them. First PC cycle 09:18-09:24Z: created 27, accepted 2
  (both from failure clusters), repairs 0 of 4; star-fast writes regexes its own reference misses (main reject reason).
  Undo PC: `git -C worktrees/ns-pc checkout --detach 798d88e7`, `turbo.cmd off`, kill the two pythonw turbo.py processes,
  `turbo.cmd on`, start the supervisor again (see below). Remove `/opt/star/learning/pool/conductor-pc-*.json` on
  server 1 if those tasks are unwanted.
- Turbo restart quirk: a supervisor started by the scheduled task at 08:53Z logged "server_ssh NOT set; pool missing"
  (same as 2026-10-16 00:57) and did nothing; started from Git Bash instead it reads config.json fine:
  `cd /c/Windows/System32 && ("<pr39 venv>/Scripts/pythonw.exe" "<ns-pc>/server/night_school/pc/turbo.py" --home "%LOCALAPPDATA%\STAR-night-turbo" run &)`.

## 2. Apprentice v2: NOT trained tonight (guard)
- Dataset `work/apprentice/data-v2` (build_dataset.py over s1+s2+PC examples, pool of server 1): rows 589, dup task
  163, dup answer 8, measuring slice excluded 89 -> **train 304 / val 25** (pilot 154 / 10); 165 hand-written-family,
  134 ledger, 5 private river rows (local only). Measuring slice now 128 tasks; the pilot's 117 are all inside it
  and none is in training (checked), so v2 is scored on the same 117 as the pilot base/apprentice answers.
- Venv `tools-portable/train-venv` was broken (its base Python lived in the deleted voice-lab folder): pyvenv.cfg now
  points to the Codex runtime Python 3.12.14 (backup pyvenv.cfg.bak-20261018); torch 2.11+cu128 CUDA OK.
- HF weights re-downloaded (rev cdbee75f, 7.6 GB in work/apprentice/hf). `run_arm.sh` fixed: it killed EVERY
  llama-server.exe (incl. the GPU turbo's); now only its own (backup run_arm.sh.bak-20261018).
- GPU guard: RobloxStudioBeta (a place edit, open since 05:13Z) is open on this PC -> training waits.

## 3. Embedding fine-tune: already live since 2026-10-14
The guarded server A/B in gpu-training-pilot.md was done on 2026-10-14 (msg 2026-10-14 09:20Z, night-school-restart.md):
star-knowledge and star-knowledge-refresh run with STAR_EMBED_MODEL=star-embed-ft1 (systemd drop-ins embed-ft1.conf),
router alias star-embed-ft1 loaded. Checked 07:55Z: all 18,208 chunks have ft1 vectors (0 missing); the old star-embed
vectors miss 342 chunks added since (a rollback would leave those 342 without vectors until `starkb embed` runs).
Nightly refresh eval30 vector r@5 30/30. Nothing to do; rollback stays `deploy_embed_ft.sh rollback`.

## Status log
- 07:37Z start; data copied read-only; HF weights of Qwen3-4B-Instruct-2507 re-downloading (pilot deleted them).
- 07:46Z conductor deployed (file + env only; loop not restarted: quiet lock held by claude-model-scout18).
- 08:13Z msg #427 (Studio open on the PC blocks training; quiet lock of model-scout18 paused night school 05:15-08:33Z).
- 08:34Z star-night-school restarted under my quiet lock (< 1 min): loop now runs the new conductor, env cap 80.
- 10:05Z PC conductor 2nd cycle: created 27, accepted 7. Night total on the PC: **9 accepted in 2 cycles** (cluster 3,
  ideas 4, variants 2), repairs **0 of 8** (the repair round has not helped yet with star-fast). Server 1 conductor:
  no cycle since 04:47Z ("brain was not quiet": another client generates on star-fast slot 0 most of the time).
- Apprentice v2 pipeline ready: `bash work/apprentice/v2_pipeline.sh` (guards: no RobloxStudio, >= 8 GB free RAM
  after the turbo is off, >= 15 GB on C:; turbo off during train+answers, on again after; 1 epoch by default,
  EPOCHS=2 for two; then scores base, pilot and v2 answers in one server-1 run and writes score/v2-compare.txt).
  `work/apprentice/split_compare.py` reproduces the pilot: 43 vs 35 of 117 (20 wins/12 losses, two-sided p=0.215;
  ledger 26 vs 14, p=0.017; hand-written 17 vs 21, p=0.34).
- 10:27Z `turbo.cmd merge` copied the PC tasks: server 1 pool 671 -> **680 tasks, 0 dropped** (validate-pool).
- 10:30Z recount: **429 unique verified tasks** (07:40Z: 426). +3 in ~3 h, all from the PC turbo; server 1 and 2 made
  none (server 1 waited for a quiet brain all night: another client on star-fast slot 0, quiet locks of model-scout18).
  The PC also re-answers its validation slice (250 rows on 80 tasks), which adds rows but not new tasks.
- 10:41Z STOP. RobloxStudioBeta (pid 25896, ~0.3 core busy) stayed open the whole
  session, so by the owner's guard apprentice v2 was never trained. Pipeline is ready (above).

## Next (for whoever resumes)
1. When Studio is closed: `bash work/apprentice/v2_pipeline.sh` (~35 min train, ~15 min answers, ~10 min scoring),
   then put score/v2-compare.txt numbers here (v2 vs base and vs pilot e1, ledger vs hand-written split).
2. Morning: read `%LOCALAPPDATA%\STAR-night-turbo
s\conductoreport-20261017.md` and server 1
   `/opt/star/learning/conductor/report-20261017.md`; measure new verified tasks/day over the next 2 nights vs the
   56-89/day baseline. If the repair round stays at 0 repaired, drop it (set MAX_REPAIRS_PER_CYCLE = 0).
3. Data quality: practice-tasks-round-lifecycle-v1 is 0/12 solved, security 4/20; check their regexes (failures
   cluster on require patterns such as highest_score, store_connection) - fixing broken checks unlocks examples.
4. Server 1 night school needs brain time: it got none 05:15-10:40Z. A planned quiet window (or star-deep with a
   second slot) would let the conductor and practice run there.
