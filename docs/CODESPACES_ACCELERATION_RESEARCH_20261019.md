# Star AI: Codespaces acceleration and free-tier engineering plan

Research date: 2026-10-19 UTC (2026-10-18 evening in America/Chicago).
Status: **proposed engineering plan; no Codespace launched, budget changed, or runtime acceleration measured by this work.**
Authoring actor: owner-directed ChatGPT, not autonomous Star AI.

## Decision

Use GitHub Codespaces as a bounded Linux development worker behind Star's existing resource planner. Keep persistent coordination and model inference on the owned fleet; keep native Windows acceptance in the Windows environment. Optimize time to a verified change and successful work per core-hour. A cloud machine is useful only when it improves that outcome or frees local capacity needed for interactive AI or games.

This extends the existing configuration in [migration PR #489](https://github.com/oncoursemail/Star-AI-Private/pull/489), without editing that concurrent branch or changing its release/authentication design.

## 1. Observed project state

The connected repository inventory confirms private source at `oncoursemail/Star-AI-Private` and public distribution at `oncoursemail/Star-AI`. The public repository is not another source workspace.

At inspection, PR #489 was open and draft; its head was `2a60c62e9fbfa39194adde83cd449403f4c5c40e`. Its [devcontainer configuration](https://github.com/oncoursemail/Star-AI-Private/blob/2a60c62e9fbfa39194adde83cd449403f4c5c40e/.devcontainer/devcontainer.json) uses a custom Python 3.11 image, Node 22 and GitHub CLI, minimum 2 CPUs/8 GB, a private UI preview, and virtual-environment creation. Dependencies and a live worker lifecycle are not installed by that configuration.

The inspected main commit was `0d7bfdb838435221ab60ecd83687e896d34b568e`. [orchestration.py](https://github.com/oncoursemail/Star-AI-Private/blob/0d7bfdb838435221ab60ecd83687e896d34b568e/star/orchestration.py) validates dependencies and conflicting read/write ownership; it does not spawn workers. [resource_planner_service.py](https://github.com/oncoursemail/Star-AI-Private/blob/0d7bfdb838435221ab60ecd83687e896d34b568e/star/resource_planner_service.py) has an admission/lease service; the code explicitly says it does not start or stop jobs. A Codespaces backend therefore needs an execution adapter and lifecycle reconciliation, not another unrelated planning framework.

Repository state is not proof of what is deployed on a remote host. Account plan, remaining allowance, billing controls, authentication scopes, eligible machines and cloud performance were not inspected.

## 2. Verified GitHub allowance

| Personal plan | Monthly compute | Monthly storage |
| --- | ---: | ---: |
| GitHub Free | 120 core-hours | 15 GB-month |
| GitHub Pro | 180 core-hours | 20 GB-month |

| Cores | Running hours from the full Free compute allowance | Overage compute price per hour |
| ---: | ---: | ---: |
| 2 | 60 | USD 0.18 |
| 4 | 30 | USD 0.36 |
| 8 | 15 | USD 0.72 |
| 16 | 7.5 | USD 1.44 |
| 32 | 3.75 | USD 2.88 |

Storage overage is USD 0.07/GB-month. Allowances are shared by the billed account across Codespaces, not multiplied by repository count. Organizations/enterprises have no included Codespaces quota of their own. Exhausting included use blocks further use without a valid payment method; with payment enabled, applicable budgets matter. [Official billing](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces).

The runtime calculation is `core_hours = sum(cpus * running_hours)`. Two 4-core workers, if permitted by the account, use 8 core-hours each elapsed hour. Fifteen hours together exhaust 120. GitHub's [included-usage guide](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-included-usage) explains the multiplier.

These figures assume untouched compute allowance and enough remaining storage. They are not a statement that this account currently has 120 core-hours available.

### Proposed conservative monthly allocation

| Task allocation | Planned running time | Core-hours |
| --- | ---: | ---: |
| Routine 2-core development/checks | 36 hours | 72 |
| Measured 4-core build bursts | 4 hours | 16 |
| Optional 8-core experiment, if justified and available | 1 hour | 8 |
| Reserve for urgent fixes, accounting uncertainty and other use | — | 24 |
| Total | — | 120 |

The planned work consumes 96 core-hours. All billable setup and idle time must fit those rows. The reserve is a design policy, not extra GitHub credit. Deduct this account-level reserve once; do not silently subtract another 20% reserve from the same allowance. If there is other usage, reduce allocations before admitting jobs.

Configure an applicable product budget with **Stop usage when budget limit is reached**, if spending controls are being set. An alert-only budget does not block charges. Do not change billing automatically. [Budget controls](https://docs.github.com/en/billing/how-tos/set-up-budgets).

## 3. Storage, lifecycle and machine constraints

A GB-month measures storage over time. For a simplified 30-day example, 20 GB retained for 15 days consumes 10 GB-month; 30 GB for 15 days consumes 15 GB-month. Use the actual billing-cycle duration and GitHub's measurements for accounting.

GitHub excludes its default base container image from Codespaces storage volume, including configurations that add features to that default image. A custom base image counts. Repository content, dependencies, caches, extensions and generated data still use space. The small-looking Python image in PR #489 should therefore be compared with the default image plus required features. Image download size and billable storage are different measurements. [Included-usage/storage guide](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-included-usage).

Current lifecycle rules:

- Continuous running has a 12-hour maximum, including active sessions; saved data remains after the automatic stop.
- Total and concurrently running Codespaces limits vary by account and circumstances.
- Closing a browser tab leaves the Codespace running until stopped or timed out.
- Stop ends compute use while storage continues; deletion ends future storage accumulation.
- Deletion does not reverse already accrued usage and can destroy unexported work.
- Default inactive retention is 30 days.
- Rebuilds preserve project data under `/workspaces`; changes elsewhere can be removed.

Source: [Codespaces lifecycle](https://docs.github.com/en/codespaces/about-codespaces/understanding-the-codespace-lifecycle).

Idle timeout defaults to 30 minutes, configurable between 5 and 240. Terminal output can reset the timer. Proposed worker policy: 10-minute idle timeout plus a separately enforced 30–45-minute task deadline, with explicit stop at completion. [Timeout documentation](https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces).

Published machine range is 2 cores/8 GB RAM/32 GB storage through 32 cores/128 GB RAM/128 GB storage; the remote container runs Linux. Read the eligible machine catalog for the actual repository instead of assuming every size is available. [Environment](https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces); [machine discovery](https://docs.github.com/en/rest/codespaces/machines).

GitHub's GPU Codespaces offering was retired by August 29, 2025. This plan does not depend on cloud GPUs. [Retirement announcement](https://github.blog/changelog/2025-08-01-upcoming-deprecation-of-gpu-machine-type-in-codespaces/).

## 4. Work placement

| Work | Initial execution location | Why |
| --- | --- | --- |
| Star planning, queues, model inference and durable run history | Existing owned Star service | Preserves continuity when cloud workers stop |
| Focused Python/TypeScript checks, frontend builds and reproducible Linux debugging | One Codespace when admitted | Frees owned-machine resources and provides a repeatable environment |
| Repeatable merge verification and Windows packaging | Existing GitHub Actions workflows | Preserves independent verification and native OS coverage |
| Metallic Go checks and small Java plugin development | Codespace when economical | Useful CPU development work |
| Metallic player-capacity and tail-latency measurements | Controlled staging on intended hardware | Cloud development VMs cannot establish production capacity |
| Live Minecraft, persistent worlds, continuous learning, large model storage | Owned infrastructure or explicitly provisioned services | Requires durability and appropriate networking |

Codespaces TCP forwarding can support private previews and local CLI tunnels. A browser preview URL is not a normal public Minecraft TCP listener, and the documented mechanism does not establish Bedrock UDP support. [Forwarding documentation](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace); [CLI forwarding](https://cli.github.com/manual/gh_codespace_ports_forward).

GitHub Free separately includes 2,000 Actions minutes, 500 MB shared artifact/Packages storage, and 10 GB Actions cache per repository. Standard public-repository runner use is free; larger runners are billed. Codespaces storage does not repair Actions artifact overages. Keep each storage class and runtime budget separate in Star's dashboard. [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## 5. Real acceleration mechanisms

### A. Reduce repeated environment work

Use lockfile/toolchain keyed caches for Python and npm dependencies. Benchmark uv as an optional installer/cache implementation against the existing dependency graph; do not switch package semantics blindly. Split focused development dependencies from full desktop/ML installations where tests genuinely allow it. Preserve full acceptance coverage elsewhere. [uv caching](https://docs.astral.sh/uv/concepts/cache/).

For Metallic Java projects, use the repository's compatible Gradle wrapper, incremental builds, build cache and configuration cache where supported; bound worker counts to measured CPU/RAM. Avoid routine clean builds when incremental verification is sufficient. Changes to build caching need a clean baseline to detect undeclared inputs. [Gradle performance](https://docs.gradle.org/current/userguide/performance.html).

### B. Schedule the critical path

Estimate per-task runtime, memory, dependencies and touched paths. Run independent tasks concurrently only when their work and resources are independent. Several processes inside one 2-core Codespace still share those two cores. An extra Codespace creates more capacity but consumes more allowance.

The existing TaskPlan conflict logic is a useful starting point. Add actual execution records rather than interpreting a planned task as running. Superseded work can be canceled after keeping useful failure evidence; required verification for the final commit remains mandatory.

### C. Use larger machines only after measuring

If a job takes 10 minutes at 2 cores, it consumes 0.333 core-hours. At 4 cores it must finish in 5 minutes to match that compute use; 6 minutes consumes 0.4 core-hours. Larger machines can still be worthwhile to reduce waiting or avoid memory failures. Optimize a declared objective rather than calling every reduction in elapsed time a cost reduction.

Benchmark setup + queue + execution + verification, with both cold and warm caches. A local 24-core server may win a build outright while the Codespace still improves overall service quality by leaving inference resources free.

### D. Prebuild only when reuse justifies it

Prebuilds prepare setup in advance, using Actions minutes and retained Codespaces storage. They execute `onCreateCommand`/`updateContentCommand`, not `postCreateCommand`. Merely moving a slow install into postCreate will not make prebuild snapshots contain it. [Prebuild behavior](https://docs.github.com/en/codespaces/prebuilding-your-codespaces/about-github-codespaces-prebuilds).

Start without prebuilds. If repeated cold starts dominate, test one region and one retained version with a controlled refresh policy. Account for snapshot multiplication and dependency invalidation; frequent agent pushes should not continually rebuild every configuration. [Configuration options](https://docs.github.com/en/codespaces/prebuilding-your-codespaces/configuring-prebuilds).

## 6. Codespaces backend contract

This is an implementation specification, not an installed service.

The trusted coordinator should hold the queue and a durable record for each job:

| Field | Meaning |
| --- | --- |
| job_id, attempt_id | Stable logical work plus unique attempt |
| repository_id, repository_name, source_sha | Exact authorized private source |
| task_kind, read_paths, write_paths | Allowed workload and ownership |
| trusted_runner_revision | Independently controlled task launcher |
| machine_name, cpus, memory_limit | Actual selected resources |
| budget_reservation, deadline, lease_expiry | Bounded compute admission |
| input_hashes, cache_key | Repeatability and cache invalidation |
| result_status, exit_code, evidence_refs | Observed result, including failure |
| output_commit_sha, content_hashes | Exact reviewed output |
| stop_requested_at, stopped_observed_at | Stop request versus confirmed lifecycle state |

Do not put credentials or private service addresses into this record's GitHub-visible representation.

### Admission and execution sequence

1. Validate repository identity, task scope, trusted setup and permitted credential context.
2. Reconcile the account's current Codespaces and budget snapshot with a conservative local ledger. Deduplicate usage already reflected by GitHub against overlapping reservations so the same consumed interval is not charged twice in admission calculations.
3. Reserve estimated billable setup/runtime before starting. Subtract outstanding concurrent reservations and the reserve buffer. Treat stale or unavailable billing data as a reason to queue or use already authorized local capacity.
4. Reuse a compatible stopped worker or create one for the pinned source, subject to account limits. Reconcile uncertain create responses before retrying; otherwise a network timeout could create duplicate workspaces.
5. Verify the observed repository, source SHA, toolchain and machine after connection. A `hostRequirements` minimum is not a verified runtime size.
6. Start one bounded job with an external watchdog and heartbeat. Workers may write only their assigned paths and must not alter grading or authorization rules.
7. Store output and evidence, including unsuccessful runs. Confirm the actual remote branch/commit and artifact persistence before treating the result as durable.
8. Request stop on success, failure, cancellation or deadline. Confirm the observed stopped state; an API request receipt alone is insufficient.
9. Retain recovery data if output export fails. Deletion requires a verified durable copy and resolved uncommitted, unpushed, untracked and valuable ignored files, including work outside Git. A clean git status is insufficient. Classify disposable caches separately, and keep secrets out of source/artifact exports. Default to stop while preserving the workspace.
10. Reconcile costs and release the reservation only after accounting for observed runtime. If the coordinator restarts, reconstruct outstanding work from durable state rather than forgetting it.

A process inside the same container is not sufficient as the only watchdog. The coordinator must recover from container failure or lost connectivity.

### Authentication boundary

The repository machine-discovery endpoint accepts an App installation token with Codespaces metadata read access. User-owned create/start/stop operations require a supported user-context token: an App user token or fine-grained PAT with the endpoint's permissions. Classic PAT/OAuth uses the `codespace` scope. Creating requires Codespaces write; start/stop requires Codespaces lifecycle admin write. [Machine API](https://docs.github.com/en/rest/codespaces/machines); [lifecycle API](https://docs.github.com/en/rest/codespaces/codespaces).

Star's existing source-proposal App installation token must not be assumed to manage a user's Codespaces. Keep lifecycle authorization in a separately reviewed adapter and out of model-visible code. Repository write authority, cloud lifecycle authority, independent grading, and public publishing remain separate responsibilities.

For SSH execution, ensure the image actually contains a running SSH server; GitHub documents an sshd feature for custom containers. The existing PR #489 configuration does not prove that requirement has been met. [CLI SSH](https://cli.github.com/manual/gh_codespace_ssh).

## 7. Verification and rollout

| Stage | Concrete deliverable | Exit criterion |
| --- | --- | --- |
| C0: inventory | Read-only account/repository capability and budget report | Unknowns explicit; no lifecycle writes |
| C1: footprint experiment | Default image vs existing Python image, focused dependencies | Actual setup time, billable footprint and successful checks recorded |
| C2: pure admission policy | Core-hour/storage reservation calculations and bounded state model | Boundary, duplicate-request, stale-data and quota tests |
| C3: one worker pilot | Reviewed lifecycle adapter with stop reconciliation | End-to-end job, forced disconnect, export failure and stop failure tested |
| C4: acceleration experiment | Local vs 2-core vs justified 4-core comparisons | Lower verified-change turnaround or demonstrated relief of local contention |
| C5: limited parallelism | Independent-job execution using the existing task planner | Conflict, retry, resource and budget correctness preserved |
| C6: optional prebuilds | Measured reuse policy | End-to-end benefit exceeds added storage/Actions consumption |

Record median/P95 time to a passing candidate, core-hours per accepted change, cold/warm setup, peak memory, cache hit rate, retries and failure rate. For shared local hardware also record interactive model latency and game tick tails, not just cloud build speed.

A passing synthetic scheduler test is not a live Codespaces test, native Windows validation, a released Star update, or a model-intelligence improvement. Future runtime changes follow the repository's independent review gates. This document does not grant additional permissions.
