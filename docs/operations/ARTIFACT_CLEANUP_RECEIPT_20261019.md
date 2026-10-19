# Owner-authorized verified artifact cleanup receipt

Date: 2026-10-19 UTC. Repository: `oncoursemail/Star-AI-Private`, ID 1412474221. Actor: owner-directed ChatGPT, not an autonomous Star AI contribution. The owner explicitly authorized removal of unnecessary material after being told that releases, recovery files and active-review evidence would be preserved.

## Confirmed result

**52 redundant combined build archives were deleted. Their 104 separate installer/portable archives were verified and preserved. The reported size removed is 31,011,104,155 bytes: 28.88 GiB, approximately 31.01 decimal GB.**

| Measurement | Before | After |
| --- | ---: | ---: |
| Artifacts in complete repository listing | 5,373 | 5,321 |
| Sum of reported unexpired artifact sizes | 744,948,406,129 bytes | 713,937,301,974 bytes |
| Reported size, GiB | 693.79 | 664.91 |

The difference in both counts and bytes exactly equals the confirmed deletion receipts. These are artifact metadata measurements, not the account's remaining quota, invoice, accrued usage or a refund calculation.

Final read-only reconciliation: [run 39191998958](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39191998958), job 117866639894. It succeeded and reported the final inventory at `2026-10-19T02:53:13Z`. Its workflow had only Actions read, Contents read and Pull requests read permissions.

## What was removed and what was kept

Only redundant `STAR-Fast-Brain-Preview` combined archives were removed. Each contained the same installer, portable ZIP and checksum manifest retained in that run's separate `STAR-Ultimate-Windows-Setup` and `STAR-Ultimate-Windows-Portable` archives.

Every deletion required full download and SHA-256 verification of all three archives, exact installer and portable member-byte hashes, matching original Windows checksums, matching manifest bytes, the same source/run identity, and surviving artifacts that expire no earlier than the original. ZIP files with unexpected unique content, ambiguous paths, unsafe entries or corruption were refused. No downloaded executable was run.

Immediately before deletion, the tool rechecked the private repository identity, original run status, active-review branches and all artifact metadata. It required a successful completed private pull-request build. After deleting only the authorized combined artifact ID, it confirmed GitHub returned 404 for that ID and both surviving artifacts were still present with unchanged metadata.

Protected material included all open-PR branches, main/master/star-next builds, the two newest recovery runs per branch, recent builds, releases, release tags, source code, user data, test reports, screenshots and incomplete or ambiguous archive groups. The final read-only report counted 547 groups excluded for active-review or latest-recovery protection. None of those exclusions was waived to free additional space.

Of the 55 conservatively selected candidates, 52 passed all checks and were removed. Three combined artifact IDs remain because their original-run validation failed: `11851813558`, `12023415238`, `12027353341`. They were not proved unnecessary and were not deleted. No selected candidate remains unexamined.

## Execution evidence

| Phase | Workflow run | Job | Confirmed removals | Reported bytes removed |
| --- | --- | --- | ---: | ---: |
| Canary | 39189319517 | 117858406213 | 2 | 1,149,899,638 |
| Bounded batch, attempt 1 | 39189516219 | 117859010428 | 25 | 14,791,985,405 |
| Bounded batch, attempt 2 | 39189516219 | 117864399156 | 22 | 13,254,504,055 |
| Last three explicitly selected candidates | 39191907529 | 117866361245 | 3 | 1,814,715,057 |
| **Total** | | | **52** | **31,011,104,155** |

All 15 cleanup safety tests passed before each execution and in the final read-only reconciliation. The two broad batch jobs reported failure because the tool retained candidates that failed its original-run requirement; valid removals within those jobs have explicit before/after receipts. No failed validation was treated as permission to delete. The last three-candidate run succeeded without refusals. An earlier attempt of that explicit step stopped at a Python import error before any API request or deletion; it was corrected without changing the verification rules.

Receipts in the job logs include the deleted ID, original workflow run, source SHA, surviving IDs, archive digests and verified binary digests. Separate connector reads also checked original run artifact lists for selected removals, confirming that their installer/portable files, test reports and GUI previews remained.

## The upload quota block remains

After reconciliation, a single tiny non-sensitive upload probe was run: [run 39192375324](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39192375324), job 117867770759. At `2026-10-19T02:57:30Z`, GitHub still rejected creation with: `Artifact storage quota has been hit. Unable to upload any new artifacts.` No probe artifact was created. Its deletion step therefore did not run.

**The cleanup is verified, but artifact-upload recovery is not.** No expensive full Windows rebuild was repeatedly retried after this failed probe, and no required artifact handoff was bypassed. Remaining stored artifacts may still exceed the account allowance; account billing and quota settings were not available to this maintenance process. Reporting lag must not be assumed to be the only cause.

GitHub's published billing documentation says artifact storage usage updates within 6–12 hours. Deletion lowers current storage and future accrual for removed files; it does not erase already accrued charges. No paid plan, spending cap or billing setting was changed. Source: https://docs.github.com/en/billing/concepts/product-billing/github-actions

## Temporary cleanup authority has been removed from current workflow definitions

The maintenance branch's cleanup workflow was restored to read-only permissions with no apply flag or approval value in commit `d9a60b4af2408209391fe70e0ae04270e60de995`. The one-time probe was retired in commit `803e3707967b660d05a8aed2d6d7e1887fa977eb`: no automatic trigger, no Actions write permission, and an always-skipped job. No recurring cleanup was scheduled. Historical job definitions remain in Git history for audit, so this statement does not claim that history was erased.

## Star AI release status is separate

Migration PR #489 is still draft and unmerged at source revision `2a60c62e9fbfa39194adde83cd449403f4c5c40e`. The public `oncoursemail/Star-AI` releases API returned an empty list after the cleanup. No installer was published, no main branch was changed, and no private source was copied to public storage.

The future duplicate-upload/shorter-retention fix remains in PR #489, not deployed to main. The private developer runtime and separate public-only publishing App still need their owner-configured authentication, followed by complete final Windows checks and public-download/upgrade verification. ChatGPT's connected repository access is not a server credential.

The remote read-only doctor during this cleanup confirmed public reads but no configured private GitHub authentication. Production services, models, game servers, personal files and other agents' worktrees were not modified. This operation reduces redundant storage; it is not a claim of improved model intelligence or a working public update release.
