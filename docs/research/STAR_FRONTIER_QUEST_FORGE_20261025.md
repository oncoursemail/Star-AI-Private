# STAR Frontier Quest Forge — verified self-assigned challenges

**Status:** Offline implementation proposed for review, **not a deployed autonomy loop or proven
intelligence gain**. This proposal is deliberately separate from the protected benchmark harness,
Night School lesson promoter, production runtime, GitHub permissions, and model weights.

## Why add this to STAR?

STAR already has three different mechanisms:

- **Night School:** a conductor writes short Luau exercises from development failures and solved
  examples; an independent validation slice decides whether candidate text lessons help.
  See `server/night_school/nightschool/{conductor,engine,pool}.py`.
- **Studio self-play:** `star/selfplay_curriculum.py` creates disposable, constrained Roblox obbies,
  requires a host-authorized Studio campaign, and checks real Studio Lab evidence before claiming
  any run succeeded.
- **Self-builder and skill evolution:** `star/selfbuild.py` may propose only
  `star/skills/*.py` or `docs/skills/*.md` in an isolated worktree; `star/skill_evolution_lab.py`
  evaluates candidate improvements against development tasks and independent holdouts before
  suggesting review. Neither is a free pass to modify policy, tests, auth, or deployment.

The missing feedback loop was *persistent, programmatically graded challenge progression*:
give STAR a harder, unseen instance after demonstrated mastery; preserve its training history;
identify repeated weaknesses; and submit reviewable skill proposals without allowing the
student to rewrite its own exam.

## What the new code does

`star/frontier_quests.py` is pure Python plus a private SQLite training ledger. A trusted
host can pass a local model's response back for exact grading. The module does not start
a model server, run arbitrary submitted code, edit GitHub, or open Roblox Studio by itself.

| Family | Level progression | Host-owned correctness oracle |
| --- | --- | --- |
| **Route** | Larger weighted obstacle grids; ordered mandatory waypoints; count equally optimal routes | Dynamic programming over valid right/down transitions |
| **Scheduler** | More render/game tasks; growing dependency count; exact earliest starts | Topological critical-path calculation |
| **Game state** | Longer action logs, shields, inventory buying, potion cooldowns | Deterministic state-machine interpreter |
| **Fusion** | Route-derived modifier to an independent rendering graph | Both original oracles composed by the host |

Families start at level 1; three consecutive correct **new** tasks move that family up one level,
and three consecutive failures move it down one level. Levels are capped at 12 pending review
of new difficulty families and compute budgets. Fusion becomes eligible after route and
scheduler both reach level 3. Every seed and task specification is committed to a digest
and stored with the original prompt. A pending question is reused rather than overwritten.
Answers are graded once. Incorrect JSON, extra keys, and booleans in place of integers fail.

The host reports a deterministic **training** result, never a sealed holdout result. A generated
question can be predicted by anyone who sees its generation source; therefore high scores do
*not* establish general intelligence, novel reasoning, visual perception, creativity, game
mastery, or human-level performance.

## How to run an offline preview

From a checkout containing this module:

```bash
python -m star.frontier_quests preview --family route --level 5 --seed 42
python -m star.frontier_quests preview --family fusion --level 8 --seed 43
```

These commands do not create a database, invoke a model, or run a test environment.

Choose an existing local private STAR home **outside Git** before using the database:

```bash
python -m star.frontier_quests next --home /path/to/private-star-data --project STAR
python -m star.frontier_quests status --home /path/to/private-star-data --project STAR
python -m star.frontier_quests propose --home /path/to/private-star-data --project STAR
```

The `next` command returns a challenge ID, family, level, and prompt *without an answer*.
After independently running the question through the local model, submit JSON to standard
input to the `grade` command using the returned ID:

```bash
printf '%s' '{"makespan":12}' |
  python -m star.frontier_quests grade --home /path/to/private-star-data --project STAR --id FULL_CHALLENGE_ID
```

The example answer is **not** guaranteed correct; the actual response must match the
specific question. Do not use `next` or `grade` CLI commands on protected evaluation
questions. Never put the private home folder under a Git checkout.

A host-integrated campaign calls `practice_campaign(store, project, solve, host_approved=True,
count=3)`; `solve(challenge)` is an async callback from a **host-controlled local model**.
The host supplies the model, allocates compute, decides when STAR is idle, and enforces
its authenticated approval and resource lease. Each campaign is capped at six questions;
each model response is awaited for no more than 120 seconds. Default approval is **off**.
Cancellation or solver errors leave the pending question for investigation.

## How her improvements reach a GitHub review

```text
Host-issued challenge -> Local model attempt -> Code-owned oracle
                                 |
                      Per-project SQLite evidence
                                 |
                3+ failures in last <=8 attempts,
                   with more failures than passes
                                 |
                   Candidate skill improvement
                                 |
                      Host approves self-build
                                 |
               STAR's existing restricted builder
                                 |
              Isolated skill/docs branch (syntax checked)
                                 |
                 Optional configured GitHub App
                 -> draft PR against work branch
                                 |
              CI, external eval, owner review, merge
```

`FrontierStore.propose_focus("STAR")` returns only a **candidate** path and general
objective. It does not turn a model assertion into trusted evidence, change memory or weights,
open a PR, or edit code. Its proposal text is derived from counted oracle-graded outcomes,
not arbitrary model-supplied instructions.

`draft_skill_upgrade(store, "STAR", client=local_client, model=selected_model,
repository=checkout_path, github=approved_writer_or_none, host_approved=True)` integrates
the proposed objective with **the existing** `star.selfbuild.develop`. The self-builder
still controls permitted paths and handles isolated source edits. Passing `github=None`
allows local-only proposal branches; a configured, reviewed GitHub App may create a
draft PR to the configured work branch. The upgrade function never merges, publishes,
restarts services, trains weights, or disables checks.

Each upgrade proposal has an idempotent job record in local SQLite. If a builder run throws
or returns an untrustworthy receipt, that job becomes **unknown** and cannot silently retry;
an owner must inspect the remote/local branch before pursuing further actions.

**GitHub migration checkpoint:** in the inspected `star/next` revision, the GitHub App
writer still restricts `REPO` to `oncoursemail/Star-AI`. The development source lives in
`oncoursemail/Star-AI-Private`; migration PR **#489** is the separately reviewed
owner of that transition. Do **not** bypass the repo restriction or push development
source into the public downloads repo to make this feature appear operational.
The repository named `Star-AI-Private` was reported **public** by GitHub at inspection
time; do not upload private notes, SQLite files, model outputs containing secrets,
credentials, API keys, or private media.

## Database and trust boundaries

Runtime data is `<STAR_PRIVATE_HOME>/frontier_quests/frontier.sqlite3`, one project
namespace per entry. The directory is created with owner-only permissions where
supported, the DB is owner-readable, and obvious symlink redirections are refused.
The schema preserves task provenance, hashes of submitted answers (not raw answers),
graded outcomes, current level, weak-skill candidates, and draft submission receipts.
Ordinary Git files contain **no runtime data**.

Independent code-owned graders are essential but are not a full security sandbox. The
configured solver callback must **only** receive `Challenge`, never a database handle,
oracle function, or direct permission to open its own challenge specification. Network,
GPU priority, GitHub identities, published game state, and other permissions stay in the
trusted host. The host must not count a toy/oracle-simulated callback as a real model
achievement. Model outputs and external documents remain untrusted data.

Questions with known answers are useful for practice, not for verifying transfer. Use
`star/eval_gate.py` and the sealed holdout under an independent owner-controlled runner
to establish whether any skill has improved on tasks that were not used for tuning;
report repeated baselines, regression rate, task pass rate, and compute/time cost.
Training completion **must not** change the suite, grader, or promotion threshold.

## Verification and operational boundaries

The new `tests/test_frontier_quests.py` checks reproducible oracles over all
four families, fixed expected route cases, advancement/backoff, prompt-only output,
cross-project segregation, database tamper detection, one-shot grading, answer
hashes, unapproved operation refusal, campaign and self-builder budgets, idempotent
upgrade jobs, refused GitHub-writer migration bypass, and failure preservation.

No real local model performance improvement, robotic game-playing, GPU utilization
improvement, live Studio result, actual autonomous scheduled session, or model-weight
update has been demonstrated by these tests. Scheduling a nightly run remains a
separate host integration; do not assume importing this module starts a daemon.

## Suggested next experiments (separate reviewable PRs)

1. **Constraint proposer:** a model suggests bounded new problem **parameters** or
   transformations; code-owned validators and oracles accept only solvable novel
   tasks. A model-generated solution must never become the authoritative answer.
2. **Multi-skill dependency DAG:** combine simulation, motion planning, visual layout,
   and animation timing with explicit interfaces and independently checked subgoals.
3. **Curriculum with a compute budget:** compare the adaptive ladder against fixed,
   random and failure-only curricula using matched compute, not raw task counts.
4. **Verified transfer:** evaluate on new unseen families, held-out seeds, realistic
   Roblox projects, and Studio screenshots assessed by independent visual reviewers.
5. **Night School and Star desktop integration:** attach host-authorized scheduling,
   resource leases, dashboard visibility, cancellation, and owner review actions.
   Keep the current Night School validation set and sealed holdouts isolated.

Relevant reading for techniques, not claimed STAR results: DeepMind **AlphaEvolve**
(model-driven algorithm proposals plus machine-checkable evaluation), recursive
self-play from **Dr. Zero**, and contemporary work on benchmark/reward hacking.
Reconcile licenses and operational risks before adopting third-party code.
