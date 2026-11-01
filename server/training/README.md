# STAR training-data generator (server side)

Generates verified Roblox/Luau training examples from the owner's own open-weight models, for the one-week
training pilot (`docs/research/training-plan.md`, sections 3 and 6). **It does not train anything.** It runs
inside the STAR container on the server, one request at a time, at the lowest priority.

An example is: a task statement, a solution, and an executable Luau test file. It is kept only if it passes
every gate below; every kept row carries the evidence of each gate and a hash of the gate log.

## What is used, and what is not

| Used | Not used |
|---|---|
| `star-fast` (Qwen3.6-35B-A3B, Apache-2.0) writes the task, the tests and the solution | hosted-model outputs (Anthropic, Google, Groq, OpenAI, OpenRouter) |
| `star-quick` (Mellum2.1, Apache-2.0) drafts task ideas | scraped text, DevForum, other people's games, community datasets |
| `star-embed` embeds task texts for the similarity gates | any evaluation task, reference answer or test (they are only compared against) |
| The official Luau tools (`luau-compile`, `luau-analyze`, `luau`; MIT) | the engine API reference as training text (oracle only; licence unconfirmed) |

The teachers never see text from the evaluation suites. The topics (`startrain/topics.py`) are written at
category level and weighted by where the day-1 baseline failed; closeness to a specific evaluation task is removed
afterwards by gate G8.

## Gates (cheapest first; the first failing gate is the recorded reason)

| Gate | Check |
|---|---|
| T / S | the task writer's and the solver's replies can be parsed and were not cut off |
| G0 | length bounds; credential pattern; no `require` / `loadstring`; pure tasks start with `--!strict` and have no `:: any`; Roblox-flavoured tasks must not claim `--!strict` (it cannot be verified here); at least 5 `check()` calls, none constant or comparing a value with itself; no debug `print` |
| G6 | deprecated APIs: `wait`, `spawn`, `delay`, `tick`, `:connect`, `game.Workspace`, `Instance.new(class, parent)`, `Body*` movers ... (list in `gates.py`) |
| G8 | decontamination, text: exact hash and fuzzy match (token 5-gram Jaccard and containment, shared 8-grams) of the task, the solution and the tests against every item of the evaluation suites |
| G7 | near-duplicates, text: exact hash and 5-gram Jaccard at 0.70 against everything kept so far |
| G1 | `luau-compile` accepts the code |
| G2 | pure tasks: `luau-analyze` in strict mode, zero errors. Roblox-flavoured tasks: non-strict, zero errors, engine type names accepted (Roblox classes are typed `any` on the server, so API names and argument types are **not** verified) |
| G3 | all tests pass in the standalone Luau VM (address space 256 MB, CPU 6 s, wall 8 s, file size and open-file limits, empty environment, own session), at least 5 assertions ran, and a second run gives the same results |
| G4 | test sanity: the tests must fail on an empty stub, and must fail on at least 70 percent of at least 3 mechanical mutants of the solution (flip a comparison, off-by-one, and/or swap, drop a statement ...) |
| G7e / G8e | near-duplicate (cosine 0.92) and decontamination (cosine 0.88) by embedding of the task text |

Roblox-flavoured examples run against deterministic stand-ins (`startrain/prelude.luau`: Instance tree with
signals, Players, RunService, CollectionService, TweenService, Vector3, UDim2, ...). They are labelled
`mock-verified`, never "run in Roblox". `python -m startrain selftest` runs 42 checks of the stand-ins.

## Optional verifier-feedback repair loop

The generator can optionally give a failed **solution** one or more chances to re-solve after an independent gate
rejects it. This is disabled by default:

```bash
STAR_TRAIN_SOLVER_REPAIR_ROUNDS=0   # default
```

For a reviewed pilot, set it to `1` in the server training environment and compare keep rate, token cost and
held-out quality before considering a larger value. The setting is clamped to 0–3.

The solver receives only the authoritative task plus compact structured failure information
(`gate`, `code`, and a short detail). It does **not** receive the hidden test source, decontamination index,
evaluation suites or gate implementation. Each replacement is parsed as a complete new solution and must pass the
same gates from the start.

Only failures controlled by the solution are eligible for repair: selected G0 code-shape failures, deprecated APIs
(G6), compile/type failures (G1/G2) and executable-test failures (G3). The loop never asks the solver to repair its
way around decontamination/duplicate gates or weak-test sanity (G4).

Kept rows record the repair round, failure trigger, before/after code hashes, a hash of the compact feedback, and
repair-token cost. This makes repaired examples auditable without copying evaluator internals into model-facing
training text.

## Behaviour on the shared server

* One request at a time; chat requests are streamed, so a running generation is dropped within about 3 seconds
  when somebody else starts using any loaded model (a second busy slot on the model we use, or a busy slot on
  another model), when `/opt/star/lock` appears (stale after 20 minutes, never removed here), when the PAUSE file
  appears, or when the job is stopped. After someone else's activity it waits 120 quiet seconds (a gap in a batch run is rarely longer).
* `STAR_TRAIN_WINDOW_UTC=04:00-10:00` (in `/opt/star/training/env`) confines it to a nightly window; by default
  it may run at any time because it yields as above.
* `Nice=19`, idle I/O class, `CPUWeight=5`, 2 GB memory cap, no network beyond the local brain.
* Checkpoint after every candidate (JSONL appended and fsynced, `state.json` replaced atomically; the files are
  authoritative if they disagree). SIGTERM stops cleanly; `Restart=on-failure` after 5 minutes.

## Safety of the code it runs

Everything a teacher writes is executed only inside the container, as the unprivileged user `star`, in the standalone
Luau VM (no `io`, no `os.execute`, no network library; the solution is loaded with `loadstring` into a whitelisted
environment), in a fresh private directory, with an empty environment, its own session (killed as a group on timeout),
address space 256 MB, CPU 6 s, wall 8 s, 1 MB files, 32 open files, and a 64 KB output cap. The unit adds `ProtectSystem=strict`,
`PrivateTmp`, `NoNewPrivileges`, a 2 GB memory cap and write access to `/opt/star/training` only. No network namespace is
available to user `star` here, but the VM has no way to open a socket.

## Files on the server (`/opt/star/training`)

| Path | What |
|---|---|
| `app/` | this folder |
| `data/kept.jsonl` | the dataset: prompt, response, code, tests, gate evidence, teacher names, hashes |
| `data/rejected.jsonl` | every rejected candidate with gate, reason and texts (also future preference data) |
| `data/vectors.jsonl`, `data/state.json` | embeddings of kept tasks; counters and cursors |
| `data/report.md`, `data/report.json` | the running report (kept / rejected per gate, kept per hour, nights to 800) |
| `decontam/index.json` | evaluation-suite index (hashes, shingles, embeddings); built from `suites/`; never committed |
| `PAUSE` | create to pause, delete to resume |
| `env` | optional environment for the unit (the window) |

## Commands

From the PC (Git Bash; the server address comes from `STAR_SERVER_SSH` and `STAR_LXC_CONTAINER`, never from the repo):

```bash
bash server/training/deploy.sh --install          # copy the code, install the unit (not started, not enabled)
bash server/training/deploy.sh --suites <evals/roblox folder with extra/ files>   # evaluation suites for G8
bash server/training/deploy.sh --exec build-decontam --suite-root /opt/star/training/suites --extra <files under suites/extra>
bash server/training/deploy.sh --exec selftest    # the Luau stand-ins
bash server/training/deploy.sh --live             # the gates against the real Luau tools
bash server/training/deploy.sh --ctl start|stop|restart|status|pause|resume|report|logs
bash server/training/deploy.sh --exec show -n 10 --tests       # read kept examples
bash server/training/deploy.sh --exec export --out /opt/star/training/export   # chat-format train/dev + manifest
```

Do not run `--exec run` in the foreground over SSH with a local `timeout`: killing the local client does not
stop the remote process. Use the unit, or `--exec run --max-hours 0.2`.

In the container: `systemctl start|stop star-training-gen`, `journalctl -u star-training-gen -f`,
`bash /opt/star/training/app/trainctl.sh status`. To start at boot: `systemctl enable star-training-gen`.

## Tests

```bash
python -m pytest -q server/training/tests          # 43 tests on the PC: parsing, mutants, similarity, decontamination,
                                                   # gates without tools, quiet rules, store, the loop with a scripted brain
bash server/training/deploy.sh --live              # on the server: real Luau tools, limits, wrong solutions rejected
```
