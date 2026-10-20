# Windows artifact cleanup: verified execution checkpoint

Updated 2026-10-19 UTC. Owner-directed maintenance. This record distinguishes completed artifact deletion, proposed workflow changes, and the account storage meter.

## Current verified outcome

The signed-in browser cleanup removed **73 artifacts / 28,032,268,321 bytes (28.032 GB decimal)** across **29 completed old Windows PR runs**. Together with the earlier independently audited maintenance pass, confirmed removal is **125 distinct artifacts / 59,043,372,476 bytes (59.043 GB decimal)**.

A fresh run-specific API audit completed at **2026-10-19 04:26:47 UTC**. All 73 deleted IDs were absent; every one of the 29 affected runs contained exactly its single GUI preview. These **29 preserved previews total 2,159,357 bytes**. All 73 API reads in the final audit succeeded: the other 44 runs still contained the 128 selected remaining artifacts with matching IDs, names and sizes, alongside their preserved GUI previews. This verifies the selected runs, not the complete repository inventory.

The [machine-readable receipt](WINDOWS_ARTIFACT_CLEANUP_RECEIPT_20261019.json) preserves the original first-batch evidence, exact additional IDs and bytes, fresh API results, the remaining selection and the approval failure. The cumulative browser receipt did not synchronize into the local workspace; its additional records were reconstructed from exact observed candidate metadata and root-confirmed UI execution. Missing execution timestamps remain null. API verification timestamps are actual read times, not invented deletion times.

## First cleanup batch: historical detail

After the owner completed GitHub sign-in, **38 obsolete Windows artifacts were deleted through GitHub's supported artifact UI, totaling 14,771,686,659 bytes (14.772 GB decimal)**. Each click targeted a previously inspected exact artifact ID and name from a completed old Windows PR run. The original triggering PR shown by GitHub was checked closed, alongside the current open-PR branches and SHAs. Every deletion produced GitHub's success message and the exact artifact link disappeared.

A separate API check afterward read all 13 affected run-artifact lists successfully. Each run retained exactly its small GUI preview: **13 previews / 967,975 bytes**. Workflow runs, logs, source, branches, public releases, models and personal files were not deleted. The [machine-readable receipt](WINDOWS_ARTIFACT_CLEANUP_RECEIPT_20261019.json) records exact IDs and bytes and includes the API verification.

| Run | Original closed PR | Deleted artifacts | Deleted bytes |
|---|---|---:|---:|
| [38181409430](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38181409430) | #102 | 3 | 1,174,994,726 |
| [38181839579](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38181839579) | #115 | 3 | 1,175,040,807 |
| [38182052924](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38182052924) | #116 | 3 | 1,175,088,719 |
| [38182726203](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38182726203) | #117 | 3 | 1,175,105,965 |
| [38184385063](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38184385063) | #123 | 2 | 587,513,548 |
| [38184396540](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38184396540) | #124 | 3 | 1,175,030,022 |
| [38185113666](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38185113666) | #125 | 3 | 1,174,990,722 |
| [38185184749](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38185184749) | #127 | 3 | 1,175,002,904 |
| [38185213935](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38185213935) | #129 | 3 | 1,175,038,788 |
| [38185255806](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38185255806) | #128 | 3 | 1,175,139,372 |
| [38185288525](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38185288525) | #134 | 3 | 1,174,978,573 |
| [38185299529](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38185299529) | #131 | 3 | 1,175,052,176 |
| [38191325764](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38191325764) | #151 | 3 | 1,258,710,337 |
| **Total** | **13 runs** | **38** | **14,771,686,659** |

The original proposal contained 39 artifacts / 15,359,199,891 bytes. Combined preview 11719198406 (587,513,232 bytes) had already been removed by the separate earlier maintenance cleanup. It is excluded from this session's deletion total. The original candidate manifest is obsolete and is not distributed as an apply plan.

Three original-trigger PR numbers were corrected using the live run UI plus full PR API reads: run38182052924 is PR116, run38185184749 is PR127, and run38185299529 is PR131. A commit can appear in a different merged PR; that alone does not establish the original run's PR identity.

## Additional completed cleanup

The next **16 runs** contributed **35 additional deleted artifacts / 13,260,581,662 bytes**. This includes portable artifact11683055887, whose root-confirmed UI deletion preceded the expanded review refresh. The final deletion was artifact11694187690 from run38117374499, confirmed by the UI at **2026-10-19T04:03:20.485Z**.

| Run | Original closed PR | Deleted artifacts | Deleted bytes |
|---|---|---:|---:|
| [38020494643](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38020494643) | #31 | 1 | 573,102,523 |
| [38021047030](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38021047030) | #34 | 1 | 573,091,694 |
| [38021929127](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38021929127) | #35 | 1 | 573,250,368 |
| [38022981459](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38022981459) | #39 | 1 | 573,443,210 |
| [38025009718](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38025009718) | #39 | 3 | 1,146,815,779 |
| [38055625474](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38055625474) | #39 | 3 | 1,146,876,704 |
| [38087299235](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38087299235) | #40 | 2 | 574,810,576 |
| [38099231076](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38099231076) | #40 | 2 | 575,089,694 |
| [38100581901](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38100581901) | #40 | 2 | 575,147,127 |
| [38102137801](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38102137801) | #40 | 2 | 575,169,557 |
| [38114432255](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38114432255) | #40 | 2 | 575,268,492 |
| [38115411675](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38115411675) | #41 | 3 | 1,150,547,604 |
| [38116229001](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38116229001) | #43 | 3 | 1,150,658,964 |
| [38116289378](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38116289378) | #42 | 3 | 1,173,191,010 |
| [38116642950](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38116642950) | #44 | 3 | 1,150,861,372 |
| [38117374499](https://github.com/oncoursemail/Star-AI-Private/actions/runs/38117374499) | #45 | 3 | 1,173,256,988 |
| **Additional total** | **16 runs** | **35** | **13,260,581,662** |

## Remaining selected cleanup and approval block

The refreshed artifact-list audit confirms **128 selected artifacts / 49,131,258,338 bytes** still present across **44 runs**. These are expanded review groups17-60. Their exact IDs and original protection evidence are included in the receipt. The broader review was bounded; this is not every potentially obsolete artifact in the repository. Before resuming, refresh run and artifact identity, PR state, current open-PR protections and explicit recovery exceptions.

Two attempts to execute the next deletion batch failed before execution during **automatic approval review**. The service returned **“Selected model is at capacity. Please try a different model.”** It explicitly stated that the action was **not executed** and that this was **not a determination that the action was unsafe**. A following read-only browser documentation request also failed at the same review boundary. GitHub sign-in had succeeded; this is an approval-service capacity blocker. No alternative deletion mechanism was used to bypass it, and no blocked attempt is counted as deleted.

## Earlier independently audited cleanup

The earlier maintenance runs contain 52 distinct deleted-and-survivors-confirmed receipts totaling **31,011,104,155 bytes**. They confirmed 104 separate installer/portable survivors at that time. Subsequent owner-authorized removal of obsolete complete build sets may remove some of those formerly preserved copies; their earlier survival is a historical statement.

The [read-only reconciliation at 02:53:13Z](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39191998958/job/117866639894) measured a decrease from 5,373 artifacts / 744,948,406,129 bytes to 5,321 artifacts / 713,937,301,974 bytes. Receipt bytes exactly matched that delta. That inventory predates this browser cleanup.

Across the earlier maintenance and both browser batches, **125 distinct artifacts / 59,043,372,476 bytes** have verified removal evidence. Subtracting the browser cleanup from the last complete inventory gives **685,905,033,653 bytes**, but that subtraction is an arithmetic estimate, not a fresh complete inventory, and does not account for concurrent changes. The remaining selected 49,131,258,338 bytes are only part of that estimated total; protected and unreviewed artifacts must not be treated as automatically deletable.

## Account and quota status

The signed-in [Billing Overview](https://github.com/settings/billing), inspected during this session, confirms **GitHub Free** and displays **0.5 GB used / 0.5 GB included** for Actions storage. It displays **$0 current billable Actions usage** after included-usage discounts. Gross usage is not an amount owed. No plan, payment, spending limit or paid storage setting was changed.

The [storage probe at 02:57:30Z](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39192375324/job/117867770759) was rejected with the artifact-storage quota error; its artifact list was empty. That probe predates both browser cleanup batches. A successful upload has not yet been established after this cleanup. The remaining inventory is substantial; reporting delay alone is not sufficient evidence that the problem will disappear.

GitHub documents a 6–12 hour storage-reporting refresh and that deleting artifacts does not erase earlier storage accrual. The repository inventory and the account's billing meter measure different things. Verify a real accepted upload and the relevant Windows checks before declaring recovery. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## Conservative manual cleanup helper

[Helper](../../scripts/prune_old_windows_artifacts.py) and [targeted tests](../../tests/test_prune_old_windows_artifacts.py) accompany this receipt. The helper uses the authenticated GitHub CLI with an argument list, shell disabled, and an explicit github.com hostname. It does not extract credentials, change authentication or schedule deletion.

Planning is read-only. Selection is limited to the three exact obsolete Windows package names: STAR-Fast-Brain-Preview, STAR-Ultimate-Windows-Setup and STAR-Ultimate-Windows-Portable. Eligible runs must belong to private repository1412474221 and the verified Windows workflow380060164 at .github/workflows/windows-desktop.yml, and have completed at least three days ago. Artifact/run repository identity, source branch, SHA and timestamps must match. The helper requires real matching PR-branch evidence and verifies all associated PRs are closed; unresolved associations are preserved. All currently open PR branches and SHAs, main/non-PR runs, other artifact families and explicit keep-runs are preserved.

Generate a new plan for every operation; the historical receipt is intentionally not an apply manifest:

```bash
python scripts/prune_old_windows_artifacts.py --plan cleanup.json
python scripts/prune_old_windows_artifacts.py --only-run RUN_ID --plan selected-cleanup.json
python scripts/prune_old_windows_artifacts.py --apply cleanup.json
```

A plan binds exact IDs and metadata, is limited to 24 hours, and cannot widen selection during apply. Its digest detects edits; it is not an approval signature. Full preflight precedes any deletion, followed by fresh checks before every exact-ID DELETE. A deletion acknowledgment is recorded before absence verification. Verified removal requires an artifact404 plus an accessible full run listing excluding that ID. Processing stops at the first error; generate a new plan after partial completion. GitHub has no atomic conditional artifact deletion, so a small race remains between the final read and DELETE. Preserve any exceptional review or recovery run explicitly.

**61 targeted helper tests passed locally.** Tests use mocked API state to exercise wrong repository/workflow/PR identity, matching-branch fallback, open or reopened PRs, incomplete pagination, stale/tampered manifests, exact scope, failures and partial-deletion receipts. Test success does not establish a live CLI apply, Windows installation or a release. The deletions recorded above were executed through the UI, not by running this helper against GitHub.

## Prevention and release boundaries

[Draft PR489](https://github.com/oncoursemail/Star-AI-Private/pull/489), head2a60c62e9fbfa39194adde83cd449403f4c5c40e, remains unmerged at the inspected checkpoint. Its storage changes remove the combined PR upload and propose three-day binary previews, one-day main release handoffs and seven-day GUI previews. They are not deployed to main.

Retention alone cannot fit a roughly 600 MB Windows pair into this account's 500 MB allowance. The [combined prevention change](WINDOWS_STORAGE_PREVENTION_20261019.md) is prepared with this cleanup record on branch `fix/windows-artifact-cleanup-20261019`, based on verified main `0d7bfdb838435221ab60ecd83687e896d34b568e`. It runs normal PR validation without artifact uploads, builds required frontend outputs on each Windows runner, adds an actual installer smoke check and makes non-main downloadable previews explicitly requested. Mandatory release checks and tested-output provenance remain intact. The existing approximately 600 MB main handoff still needs sufficient storage or a separately reviewed transfer design. The 400 MB optional-preview policy is a best-effort repository budget, not an account-wide hard cap. **20 prevention tests and 3 unmodified release-provenance baseline checks passed locally; native Windows execution is still required.**

Repository AGENTS.md requires an independently controlled review gate for workflow changes. Code preparation and a draft PR do not mean those changes are merged or operating on main. Actual Windows CI and installer execution must be reported from real runner results, not inferred from static workflow tests.

## Extra-storage research

See [FREE_STORAGE_OPTIONS_20261019.md](FREE_STORAGE_OPTIONS_20261019.md) for official-source research on GitHub Releases, R2, Backblaze B2, Hugging Face and other free tiers. No provider signup, payment method, public exposure or off-site upload was performed. Existing-server free disk capacity remains unverified because the remote capacity command returned no usable result.
