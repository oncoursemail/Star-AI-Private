# Metallic layer: what makes the owner's forge better than GitHub for STAR and the Metallic projects

2026-10-20, Claude (board #191). Core: Forgejo on brain 1 (git, pull requests, Forgejo Actions; board #189, another
agent). This layer sits on top of it and also runs on any plain clone. First slice built in `metallic/` (CLI `metallic`,
dashboard v1); numbers below marked RAN were measured on this PC on 2026-10-20, the rest is design.

## Why: the problems this team actually hit

| Problem (measured, with source) | Cost |
|---|---|
| PRs green alone, red together: round 6 step 4, #208's test vs #219's paired gate, star/next red after a back-to-back merge; fix PR #229 (docs/agents/integrator.md) | a red staging branch, an extra fix PR, a re-run of the whole round |
| Gates landing mid-round: pyright baseline gate (#328) merged 10:54Z on 2026-10-14, every open PR's earlier CI run had not run it; later ruff findings after merges (integrator round 7 fixes "lazy httpx vs pyright", "3 ruff findings") | PRs "green" on a gate that no longer matched the target; integrator fix commits |
| Full suite is slow: 9,901 passed / 315 skipped in 475 s serial on this PC (RAN, pytest 9.1.1); 400+ test files | every integration step waited ~8 min per combined run |
| GitHub Actions stopped: no job starts on Star-AI-Private since 2026-10-20 09:58Z (billing), artifact storage full (5,221 artifacts) | no CI at all; all verification by hand, locally |
| Shared mutable state between agents: `git stash` is per clone, three agents popped each other's work (2026-10-13/14) | lost work, reverse patches |
| Whitespace/conflict-marker slips: #497 left a blank line at EOF, fixed afterwards in 78bc1ebd; staged conflict markers once | follow-up commits |
| Slop in answers and code: 6 % of 416 stored eval answers are slop, invented Roblox members in 4 passed answers (docs/agents/anti-slop-20261020.md) | wrong code passes lenient gates |
| 46 open PRs from two assistants, many off-scope | the integrator is the bottleneck |

## Top features (ranked by expected gain for this team)

| # | Feature | Fixes | Expected gain | Slice status |
|---|---|---|---|---|
| 1 | Merge queue on the COMBINED tree | green alone / red together; gates landing mid-round | no red staging branch from a merge; one full run per green batch instead of one per PR | built (local queue), tested |
| 2 | Content-addressed result cache | re-running identical work | unchanged re-run 185 s -> 12.5 s, 100 % hits (RAN) | built |
| 3 | Distributed, niced sharding | 475 s serial suite | 4 local workers: 475 s -> 185 s (RAN); target < 60 s with brain 2 + PC + idle brain 1 | local parallel built; remote designed |
| 4 | Test-impact ordering and selection | slow first signal | first test result 9-14 s, nearest tests done 19-38 s, selected tests 121-130 s vs 475 s (RAN, 3 real merges) | built (static graph); runtime map designed |
| 5 | Built-in Metallic checks | secrets, private names, protected closure, slop, Luau API, eval gate, diff-check | each catches a class seen here; diff-check alone would have stopped b4d318ca | built (AI review: client built, live run not done) |
| 6 | One dashboard for all projects | five repos, three machines, no overview | data age, queue, checks, runners, releases on one page at 1440 and 390 px | v1 built from CLI JSON |
| 7 | Local-first speed targets | waiting on remote CI | first verdict < 2 s, first test < 15 s, nearest tests < 60 s | measured below |

## (a) Merge queue that tests the combined state

How it works (`metallic queue`, metallic/metallic/queue.py):
1. One queue lock per clone (the `star integrator` rule in code): a second run is refused (`QueueBusy`, exit 3).
2. A scratch worktree inside the clone's git dir (`.git/metallic/scratch-<pid>`): the user's worktrees, index and
   stash are never touched (the stash collisions cannot happen here).
3. Optimistic batch: merge every queued branch in order and run the full checks once on the combined tree. Green: all
   land together. Red or a conflict: fall back to one by one.
4. One by one: branch k is merged onto the last GREEN state (not onto the target alone), checks run on that combined
   tree, and it is kept only if green. A conflict or a red check drops it with the reason; the queue moves on.
5. The checks use the combined tree's own `metallic.toml`. A gate added by branch 1 (ruff, pyright, a new test
   command) is enforced on branch 2 in the same run: the "gate landed mid-round" failure cannot pass.
6. `--apply` fast-forwards the target only if it has not moved since the run started (compare-and-swap on the ref,
   `git update-ref ref new old`). Nothing is pushed; on Forgejo the queue service pushes with its own token.
7. Tests in the queue are the full suite. Their cache entries are scoped to the exact tree, never to inferred
   dependencies; selection only orders them, and the first failure stops new batches (fail fast).

Tests that pin this (metallic/tests/test_metallic_queue.py, all fail when the feature is removed, checked by mutation):
two branches each green alone (a rename and a new caller of the old name) -> second rejected, target fast-forwarded to
the first only; a gate added by one branch rejects the next branch; conflicts drop a branch and the queue continues;
the lock refuses a second integrator; a target that moved during the run is not overwritten.

On Forgejo (next slice): Forgejo has "merge when checks succeed" but, as far as I know, no merge queue that tests the
combined state (check on the installed version). The queue runs as a small service in the brain 2 ci-runner container:
a PR gets the label `queue` (or a `/queue` comment) -> webhook -> `metallic queue run` -> commit status
(`POST /api/v1/repos/{owner}/{repo}/statuses/{sha}`) and a PR comment with the combined-tree result -> on green it
pushes the fast-forward to the target branch with a bot token that only it holds. Merging by hand stays possible for
the owner; agents only enqueue.

RAN on STAR (throwaway local target `metallic/demo-target` = origin/star/next 78bc1ebd; branches: this branch, #517
anti-slop, #515 release-v2-checklist; nothing pushed): first run 698 s: the batch was red on a false positive (the
anti-slop rule matched fixtures inside string literals in #517's own tests), so all three were tested one by one
(~165-177 s each), #517 rejected. After the fix (matches inside string literals are ignored), the second run took
186 s: batch green, all three fast-forwarded in one full run. Serial pytest one PR at a time would be 3 x 475 s.

Expected gain: the round 6 class of failure (and #229-style fix PRs) goes to zero; one full run per green batch
instead of one per PR (round 8b merged 16 PRs after one simulated combined merge: the queue makes that the default).

## (b) Test-impact selection

How it works (metallic/metallic/impact.py): a static dependency graph of the tree: Python imports anywhere in a file
(lazy imports inside functions included), the parent packages an import executes, string constants that name a module
(`python -m star.slop`, `import_module`) or a non-Python file or folder, and conftest.py files. A test file is affected
when a changed file is in its dependency closure; the import distance orders the run (changed tests, then direct
importers, then the rest), fastest files first within a distance (durations recorded per clone). A changed file that
no test names (and is not in `no_tests`) or a `full_on` file (pyproject, requirements, metallic.toml) selects the full
suite. Parse results are cached by blob hash: graph build 0.4-0.5 s warm, 6-9 s cold on STAR (RAN).

Measured on STAR (RAN):
- Last 40 first-parent merges into star/next: 9 needed the full suite (dependabot requirements bumps, correctly),
  1 needed nothing (a docs-only commit), the other 29 selected a median 64 % of test files (min 0, max 266 of ~390).
- Why only 64 %: `star/desktop_core.py` imports most of `star/` (many lazily) and ~250 test files import it, so by
  static imports a change to almost any module reaches them. Ordering still gives an early signal: on three real merges
  (534768da 3 files, b4d318ca 4 files, 98164f90 3 files) the first test result came at 9.3-9.6 s, all tests at
  distance <= 1 (7-30 files) were done at 19-38 s, all selected tests at 121-130 s, against 475 s serial.
- Caught at merge time, in history: 534768da's selection includes the `tests/test_server_provider.py` failure that
  the next commit (33dad8ad) fixed; b4d318ca's diff-check flags the blank line at EOF fixed later in 78bc1ebd.

Next (phase 2, expected 64 % -> well under 30 % of files for a typical change): a runtime dependency map recorded during
full runs with `sys.monitoring` (Python 3.12, PEP 669: one PY_START event per code object, then disabled, so near-zero
overhead), giving per test file the repo files whose code actually ran, unioned with the static direct imports of the
test and of each executed file (covers module-level constants). Lazy imports that never run stop counting. The queue
keeps running the full suite, so a gap in the map can only delay a red signal, never land a red tree. For the other
projects: Go `go list -deps -test ./...`, Luau `require()` graph, TypeScript `vitest related`.

## (c) Content-addressed result cache

Key = SHA-256 of (task kind, command, toolchain fingerprint, sorted (path, blob hash) of every input). For a test file
the inputs are its dependency closure plus `full_on` files; for a gate, the files matching its `inputs` globs; the
toolchain fingerprint is the interpreter's version, platform and path. Records are JSON files under
`~/.metallic/cache/<2 hex>/<key>.json`, written by temp file + rename. Only passes are stored: failures always re-run
(flakes), and a file that failed in a batch but passed alone is flagged order-dependent and not cached.

RAN on STAR: full run cold 185.4 s (406 misses) -> identical re-run 12.5 s with 406/406 hits; after a one-line change to
one module, only the files whose closure contains it re-run (pinned by a test on the demo repo).

Shared cache across runners (design): brain 2 serves the same layout over HTTP (GET/PUT by key). Only the queue
service writes the shared cache (a developer machine reads it and keeps its own local cache), so a dirty laptop cannot
poison results. Keys already include the toolchain, so Windows and Linux results never mix.

## (d) Distributed sharding

Today (built): N local workers pull test files from one queue (durations-weighted batches, first batch one file per
worker), each a separate pytest process with its own temp APPDATA. STAR's suite ran clean in parallel: 10,223 test
cases, 0 failures, 185 s with 4 workers vs 475 s serial (RAN).

Design for the fleet (existing pieces: `tests/sharding.py` LPT split, brain 2 ci-runner container from board #188):
- brain 2 (i7, 8 cores, container limited to 6 CPUs, load 11.3 at probe time): primary runner, 6 workers; runs the queue.
- PC (12 threads, RTX 3060 Ti): a runner agent that takes shards only while the owner's PC is idle (same idle rule as
  the GPU night turbo) and never while Studio runs; GPU jobs (Studio, vision) only here.
- brain 1 (EPYC 48 threads, load 12 at probe time): idle-only and niced: `nice -n 19`, `ionice -c3`, cgroup
  `cpu.weight=1`, at most 8 workers, and it pauses while the server quiet lock `/opt/star/lock` exists or a chat slot is
  busy, so STAR's chat stays fast.
- Scheduler: the queue service splits by recorded duration (longest first, per file) across the runners that answered
  a heartbeat in the last 30 s; a shard that does not report in 2x its estimate is re-queued elsewhere; results come
  back as per-file JSON keyed like the cache.
- Expected: 434.5 s of test work (sum of per-file times, RAN) over 6 + 8 workers plus start-up: about 40-60 s for the
  full suite; with the cache and selection most queue runs touch far less.

## (e) Built-in Metallic checks

All in metallic/metallic/checks.py, run on the change from the base tree to the tree under test, findings with file,
line and rule; `metallic:allow` on a line skips it (for fixtures).

| Check | What | Status |
|---|---|---|
| diff-check | `git diff --check base tree`: whitespace errors, blank line at EOF, conflict markers | built; found 2 real issues on Metallic-RC's latest merge (#69) today |
| secrets | same patterns as `star commit` (private key blocks, GitHub/AWS/Slack/HF/Google/sk- tokens, JWTs, secret-looking assignments), private network addresses, server user names from `~/.metallic/private_names.txt`; prints the category, never the text | built |
| files | model/audio/credential files, `pnpm-lock.yaml` etc. from metallic.toml, files over 5 MB | built |
| protected-paths | generator branches (`star/chatgpt-*` ...) may not touch the evaluation closure; lists equal to star/protected_paths.py | built |
| anti-slop (code diffs) | focused tests (`it.only`), vacuous asserts, debugger left in, TODO without an issue, placeholder text, swallowed exceptions, 3+ lines of commented-out code | built (STAR's answer-level star/slop.py, PR #517, is separate) |
| luau-api | `GetService` of a non-service, `Instance.new` of an unknown or non-creatable class (Roblox API dump), deprecated `wait/spawn/delay` | built |
| eval-gate | a change to eval-sensitive paths (skill packs, routers) needs a paired-session verdict from `python -m star.evals gate --paired-session --json` that allows it | built (report-only for STAR until the owner makes it blocking) |
| gates | any command in metallic.toml with input globs and a cache (STAR: ruff; frontend tsc/vitest when node_modules exists) | built |
| ai-review | STAR's brain reads the diff and returns at most 5 concrete comments as JSON; never blocking; a slow or absent brain is a skip | client built and unit-tested; no live call made in this slice (keeps chat slots free) |

On Forgejo the AI review runs only in the queue service, one request at a time, only for non-draft PRs, with the
background-request convention from the speed notes (never in the chat slot).

## (f) One dashboard

Screenshots (real data from this PC, 2026-10-20): `metallic-layer-20261020/dashboard-1440.png` and `dashboard-390.png`.

v1 (metallic/dashboard, React 19 + Vite, no other runtime dependency): reads `metallic status` JSON (projects from
`~/.metallic/projects.toml`, their latest check and queue reports, latest tag, runners probed now); `metallic serve`
serves it on 127.0.0.1 with live data. Look: the owner's Metallic-MC control dashboard (graphite, hairlines, three-bar
mark, one restrained accent), and its design rules: data age shown, health as shape + word, no invented numbers, no
fake trends, a phone layout that opens on what is red. Next: Forgejo API (open PRs, Actions runs, queue positions),
release notes per tag, Metallic-PX progress feed.

## (g) Local-first speed targets

| Signal | Target | Measured (RAN, STAR, this PC, 4 workers) |
|---|---|---|
| First verdict (built-in checks) | < 2 s | 0.6-1.2 s |
| First test result | < 15 s | 3.3 s with recorded durations; 9.3-9.6 s on real merges (13.9 s cold, before the key fix) |
| Nearest tests (changed tests + direct importers) done | < 60 s | 19-38 s |
| Selected tests done | < 3 min | 121-130 s |
| Unchanged re-run | < 15 s | 12.5 s (100 % cache hits) |
| Full suite, local | < 3.5 min | 185 s (serial pytest: 475 s) |
| Full suite, fleet | < 60 s | not built yet (estimate 40-60 s) |
| Queue, green batch of N PRs | one full run | 3 PRs in 186 s (one full run on the combined tree) |

## Architecture

```
 PC / any clone                     brain 1 (Forgejo, container)         brain 2 (ci-runner container)
 metallic check  --push------------> git + PRs + Actions --webhook-----> metallic queue service
   local cache                         commit status <---- status ------   |-- shards -> brain 2 workers
   dashboard <---- metallic status     PR comments  <---- review ------    |-- shards -> PC agent (idle only)
                                                                           |-- shards -> brain 1 agent (idle, nice 19)
                                                                           \-- shared cache (HTTP, queue writes only)
```

## Why a CLI in the STAR repo first

`metallic/` imports nothing from `star/` and uses only the standard library (Python 3.11+), so it runs on any clone,
on brain 2 and inside Forgejo Actions without installing anything; it lifts out with `git subtree split -P metallic`
into its own repo once Forgejo hosts it. It lives in STAR for now because STAR is the first and biggest user and the
team's checks (protected closure, eval gate, `star commit` patterns) are defined here.

## Limits (said once)

Static selection cannot see paths built at run time or folders found by globbing; unknown non-Python changes select the
full suite and the queue always runs the full suite. Order-dependent tests exist in STAR's history (test_first_token at
98164f90 and b4d318ca failed in a batch and passed alone): the runner now re-runs a failing file alone and reports it
instead of calling the branch red. The fleet scheduler, shared cache, Forgejo service and runtime dependency map are
designs, not code.
