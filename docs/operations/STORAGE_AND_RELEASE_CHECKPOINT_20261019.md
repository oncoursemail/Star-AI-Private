# Storage and release continuation checkpoint

Observed 2026-10-19 UTC. Actor: owner-directed ChatGPT through the authorized GitHub and remote connections. These changes are not an autonomous Star AI contribution or a measured increase in model intelligence.

## Repository and deployment state

Private source: `oncoursemail/Star-AI-Private` (GitHub ID 1412474221). Public distribution: `oncoursemail/Star-AI` (ID 1424898960). No private source, build artifacts, user data or credentials were copied into the public repository during this continuation.

Authentication bootstrap PR #490 was merged previously. Migration PR #489 remains a draft pending the complete release gates. Changes below were prepared together on `fix/continuation-storage-readiness-20261019`, based on #489 revision `249b20340ad1d482978deedf639c0e8d3c30d348`, to avoid triggering the full pipeline after each individual edit. This checkpoint is not evidence of a main-branch merge or a published release.

## Complete read-only artifact inventory

Workflow: [STAR read-only artifact inventory, run 39187242144](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39187242144). Job 117852138317 completed successfully. Observation time: `2026-10-19T01:52:05.802000+00:00`.

| Observation | Result |
| --- | ---: |
| Listed / reported artifacts | 5,373 / 5,373 |
| Inventory complete | true |
| Unexpired artifacts in this listing | 5,373 |
| Sum of reported artifact sizes | 744,948,406,129 bytes (693.79 GiB) |
| Possible duplicate preview groups | 603 |
| Combined-archive sizes in those candidate groups | 360,983,399,054 bytes (336.19 GiB) |
| Artifacts deleted by this continuation | 0 |

This is a repository artifact-size inventory, **not the account's billed storage, remaining quota, charges, or a guaranteed recoverable-space estimate**. GitHub billing may include storage from elsewhere and time-based accounting.

The largest categories were 608 combined `STAR-Fast-Brain-Preview` archives (363,863,815,293 bytes), 603 `STAR-Ultimate-Windows-Portable` archives (216,167,097,908 bytes), and 604 `STAR-Ultimate-Windows-Setup` archives (145,050,899,004 bytes).

A candidate group requires one combined archive plus one installer archive and one portable archive from the same run, source SHA and non-main branch, all unexpired. Contents and ongoing review needs have **not** been verified for these 603 groups. The inventory does not authorize deletion. Before cleanup, compare contents/checksums, preserve required copies and release/recovery/active-review evidence, and obtain the owner's authorization. No existing release, tag, artifact or workflow run was removed.

The inventory workflow uses only Actions read and Contents read. It has no checkout, artifact upload, deletion or billing operation. It reports in logs and the job summary, so it does not depend on the artifact-storage service accepting a new upload. Pagination is bounded at 10,000 records and marks truncated or changing listings incomplete rather than pretending to have a full snapshot.

## Source changes prepared

### Stop duplicating future PR binaries

The Windows workflow now uploads the complete `STAR-Windows-vNext` package only for non-PR builds. Pull requests retain one separate installer archive and one separate portable archive, each with the existing checksum file; they no longer also upload a combined copy.

Future PR binary retention is three days rather than thirty. The non-PR build-to-release handoff artifact is retained for one day; GUI preview images are retained seven days. Existing files and their retention settings are unchanged. A delayed release approval may require a fresh build after the one-day handoff artifact expires; expiration must never be treated as a passing release check.

All React tests, Windows regression shards, packaging, executable diagnostics, source attribution, checksum verification and publication gates remain. The quota-blocked cross-job artifact handoff has **not** been skipped or replaced with public storage. Reducing future retention does not immediately clear existing storage or erase charges already accrued.

### Bind automatic handoffs to the tested revision

An automatic handoff previously checked `main` and then dispatched a workflow against the moving branch name. A commit arriving between those events could change the revision selected by the receiving workflow.

The handoff now sends `inputs.expected_source_sha`. Both the receiving frontend build and publication job require that supplied SHA to match the actual workflow `github.sha`. The publisher still rechecks the current main tip and the original Windows artifact hashes. A different revision cannot silently inherit the old patch-release eligibility decision. Owner-initiated manual releases retain the empty-input path and all their existing gates.

Automatic handoff remains opt-in and limited to the next patch after a real stable public baseline. This work does not enable it, automatically merge agent proposals, create release credentials, or bootstrap the first public release.

## Executed validation

[STAR storage and release contracts, run 39187284242](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39187284242) succeeded on source SHA `d59cf50230005e6bc835e9f892d8b81e2f5ced21`. Job 117852261619 reported **33 passed, 17 subtests passed in 0.36 seconds**.

This targeted suite covers inventory pagination and error handling, conservative duplicate classification, credential/endpoint boundaries, mutually exclusive artifact uploads, retention and preserved release checks, synthetic dispatch behavior, Codespaces permissions and the exact-SHA receiving contract. It exercises the real workflow code against mocked GitHub responses. It requires no artifact upload.

This is an additional operations check, not a replacement for the normal suite. The earlier migration SHA `249b20340ad1d482978deedf639c0e8d3c30d348` passed full offline Python checks and all 562 frontend tests, but artifact uploads failed with GitHub's storage-quota error. Windows jobs for that run were skipped, not passed. The final migration revision still needs complete application CI and Windows validation.

## Remote verification and remaining owner setup

The `starai` remote doctor at `2026-10-19T01:37:27.464622+00:00` confirmed the public repository is anonymously readable, but the server has no configured GitHub CLI authentication and no verified private source access. No stable public release metadata was present. The Windows `Main` device remained offline. Existing production services and models were not restarted or changed.

The read-only doctor and separate public checkout remain under `/home/star/star-github-workspaces`. The public checkout cannot push private source. ChatGPT's connected GitHub authorization is not a reusable credential for the Star AI runtime.

Before end-to-end operation:

1. Resolve the artifact quota with owner-approved, verified cleanup or an explicitly authorized capped allowance. Do not assume a new paid plan or buy additional usage automatically.
2. Authorize a dedicated developer GitHub App on the private repository, with its key outside the checkout; configure the worker and authenticate private reads.
3. Authorize the separate public-only publishing App through private Actions variable `STAR_PUBLIC_RELEASE_APP_CLIENT_ID` and secret `STAR_PUBLIC_RELEASE_APP_PRIVATE_KEY`. Configure the developer Bot/App IDs for truthful `actor:star-ai` attribution. Do not paste private keys into chat.
4. Complete review and all Windows gates, merge through normal controls, publish the first approved version, and test anonymous downloads and a real data-preserving Windows upgrade.

Codespaces is prepared as an optional private development environment, not a solution to the Actions artifact quota, native Windows validation, or an always-on GPU service. No Codespace, paid prebuild or new production worker was created.

See [GitHub operations and Codespaces](../GITHUB_OPERATIONS_AND_CODESPACES.md) and [private/public migration](../PRIVATE_PUBLIC_RELEASE_MIGRATION.md).

Primary platform references: [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [removing workflow artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts), [Codespaces billing](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces).
