# Windows and offline validation without recurring PR artifacts

Prepared 2026-10-19 UTC by owner-directed ChatGPT. This is an isolated, reviewable source change, not autonomous STAR work or a completed deployment.

## Source and scope

Both workflows, the root agreement, installer, and existing release-provenance checks were fetched at verified main commit [`0d7bfdb838435221ab60ecd83687e896d34b568e`](https://github.com/oncoursemail/Star-AI-Private/commit/0d7bfdb838435221ab60ecd83687e896d34b568e). The main branch was re-read when the offline workflow was added and still pointed to this commit. The recursive tree was complete and contained only the root `AGENTS.md`; there were no nested agreements for these files. The local directory is a selected-file review snapshot, not a complete application checkout or a copy of upstream Git history.

All 26 then-open PRs were inspected for changed-file overlap. Only [draft PR #489](https://github.com/oncoursemail/Star-AI-Private/pull/489), head `2a60c62e9fbfa39194adde83cd449403f4c5c40e`, overlaps the edited workflow. Its branch was not modified. Its PR base field pointed to an older commit; the source used here was rechecked against the actual main branch SHA above.

`AGENTS.md` requires an independent review gate for workflow changes. This patch must pass that review and real CI before merge. It changes no repository visibility, billing setting, provider, publishing credential, main protection, or release version. It deletes no existing artifacts or user data.

## Failure being fixed

The existing workflow uploaded a React bundle before either Windows job could begin. Once artifact storage was blocked, the upload failed and both real Windows jobs were skipped. A GUI screenshot upload also occurred before EXE packaging. PR builds then uploaded the same installer and ZIP both together and separately, retaining each for 30 days. [Inspected main workflow](https://github.com/oncoursemail/Star-AI-Private/blob/0d7bfdb838435221ab60ecd83687e896d34b568e/.github/workflows/windows-desktop.yml).

There was a second independent failure in `STAR offline checks`, whose actual run metadata identifies `.github/workflows/tests.yml` (workflow ID `380061661`). In [run 39187810130](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39187810130), both Python and pyright succeeded. Its [React job 117853842109](https://github.com/oncoursemail/Star-AI-Private/actions/runs/39187810130/job/117853842109) successfully completed typecheck/tests/build, entry-point validation, and browser screenshot capture, then failed at **Upload actual React browser renders**. The screenshot archive has no artifact-consuming job in that workflow. [Inspected offline workflow](https://github.com/oncoursemail/Star-AI-Private/blob/0d7bfdb838435221ab60ecd83687e896d34b568e/.github/workflows/tests.yml).

The parent session inspected the signed-in [GitHub billing overview](https://github.com/settings/billing) and confirmed GitHub Free, 0.5 GB used of 0.5 GB included Actions storage. The allowance is shared across the account. The observed approximately 600 MB installer/portable pair cannot fit that allowance by shortening its retention alone. This change does not claim the repository inventory equals metered billing, or that deleting artifacts immediately clears GitHub's storage block.

## Resulting behavior

| Run | React handoff | Actual Windows checks | Artifacts uploaded by this workflow |
|---|---|---|---|
| Ordinary pull request | No artifact handoff; build locally from checkout | Both offline shards, React checks, packaged EXE doctors, installer smoke | None |
| Manual dispatch on a non-main branch, default `none` | Same | Same | None |
| Manual non-main dispatch requesting `setup` or `portable` | Same | Same | Exactly one selected binary format, its checksum file, and GUI screenshots, only after the byte check approves |
| Main push or main dispatch | Same | Same, followed by original release gates | Required release handoff, GUI evidence, and per-shard XML evidence |

The Linux React check remains a prerequisite, with its existing typecheck, test, and build commands. Each Windows job now uses Node 22 to install dependencies, typecheck, test, and build its own React assets from the checked-out source. The resulting bundle is used on that same runner, including in the actual packaged EXE. There is no replacement download, upload, cache-based handoff, or ignored handoff error.

This deliberately trades additional React work for independent validation: there are four React builds per complete workflow, including Linux and the two Windows shards. Existing job time limits remain in place. It may consume more CI minutes than the previous single-bundle design; it does not start a paid runner or change the account's allowance. Caches already configured for package installation remain ordinary package caches, not trusted binary handoffs.

Pytest writes its real JUnit XML locally. Every shard records actual case/failure/skip counts in its job summary even on failure, or says that a report was not produced. Normal PRs do not attempt to upload that XML and therefore cannot turn a successful test execution into a quota-related upload failure. Main XML uploads remain required as before. No `continue-on-error` was added.

GUI rendering remains a required check and explicitly fails when capture fails or produces no PNGs. Its upload now occurs only after package validation, and only for main or an admitted manual preview. A passing rendering check does not constitute human visual acceptance.

### Independent offline workflow

The offline workflow's `STAR-v08-React-Visual-QA` screenshot upload is now restricted to main push runs and retained for seven days instead of thirty. Ordinary PRs and `star/**` branch pushes perform the existing offline checks without requesting artifact storage. Their React bundle remains local to the producing job, where the existing entry-point check and screenshot capture consume it; there is no necessary cross-job handoff to replace.

All Python compilation, ruff, research-catalog tests, complete offline regression tests, React installation/typecheck/tests/build, entry-point validation, and pyright baseline checks remain unchanged. The existing documentation-scope fallback and best-effort screenshot-capture behavior also remain unchanged. No new ignored failure is introduced. Main can still retain screenshot evidence after a failed check through its existing `always()` behavior; that does not make a failed validation job successful. No artifact download consumer was removed.

## Native installer smoke gate

The new `scripts/smoke_windows_installer.ps1` refuses to run outside a disposable GitHub-hosted Windows runner. It uses the one freshly built Setup, a unique directory under `RUNNER_TEMP`, finite native process timeouts, and the exact expected source SHA.

It performs a fresh silent install and a same-version reinstall, checks installed `STAR.exe` against the packaged EXE's SHA-256, runs the installed `--doctor`, `--ui-doctor`, and `--build-doctor`, verifies synthetic owner/profile markers survive, and checks that an injected obsolete runtime marker is removed on reinstall. It also confirms the tested Setup file itself was not changed. Because the unchanged installer launches STAR in silent mode, cleanup stops only the STAR process whose executable path is the unique CI installation. It does not delete profile or installation trees.

These are automated synthetic smoke checks. They do not replace human-observed installation/restart, a real existing-user upgrade, local GPU or Roblox acceptance, or rollback/power-loss testing. The script has not been executed against Windows in this local review environment. That native gate must really pass on CI before it can be reported as passed.

## Explicit downloads and budget

After the reviewed workflow is available, a maintainer can dispatch it on the same-repository PR head branch:

```bash
gh workflow run windows-desktop.yml --repo oncoursemail/Star-AI-Private --ref <pr-head-branch> -f preview_format=setup
```

Use `portable` to request the ZIP instead. The default is `none`; `both` is not an option. A main dispatch retains its existing release meaning and ignores preview selection. Non-main dispatches never enter main attestation or publication jobs. A preview is not a public release, and its presence does not replace checking the completed workflow's independent offline-test results.

The read-only admission script requires the exact private repository ID/name/visibility, a complete stable paginated inventory, one selected binary, the generated checksum file, and all screenshot sizes. It allows the upload only when:

`retained repository artifact bytes + new selected files + 10,000,000 reserve bytes <= 400,000,000 bytes`

The 10 MB reserve accounts conservatively for archive overhead. The 400 MB cap is a **best-effort repository policy, not an account-wide hard cap or a promise of available billed storage**. Other repositories, other workflows, reporting delays, and provider refusal can still block an upload. This workflow serializes its main/manual artifact-writing runs to avoid races between its own budget checks; other writers are outside that lock. No budget override, artifact deletion, paid-storage change, or token with write permissions is introduced. A refused request uploads nothing and reports failure truthfully; its package checks are not relabeled as failed tests or silently marked successful publication.

## Retention and PR #489 integration

This patch carries forward the relevant retention reductions already proposed in #489:

- Required `STAR-Windows-vNext` handoff: one day.
- Selected manual installer or portable preview: three days.
- GUI screenshots: seven days.
- Existing per-shard test results on main: seven days.

The duplicate combined PR preview is removed. Main's `STAR-Windows-vNext` still contains the actual tested installer, portable ZIP, and checksum; the attestation and publishing jobs are unchanged byte-for-byte from the inspected main workflow. Required publication checks still run against those exact uploaded bytes and the source SHA. If the handoff expires, rebuild and retest rather than substituting untested bytes.

The approximately 600 MB required main handoff can still exceed the confirmed 0.5 GB account allowance. This patch does not disable, ignore, or route around that required release handoff. Making that release transfer work within a smaller account limit requires a separately reviewed release-transfer design or verified sufficient storage. Ordinary PR validation no longer has that storage dependency.

#489 also changes private/public publisher authentication, optional private attestations, release dispatch, and version metadata. Do not replace its entire workflow with this file or overwrite this change with its older workflow. Deliberately combine the quota-independent producer changes with #489's reviewed publisher/attestation changes. Its existing `tests/test_storage_operations.py` predicates expect automatic PR uploads and must be updated to the new explicit-dispatch policy without relaxing release gates. Its role/provenance/release tests must remain effective. The full integrated result needs fresh independent review and Windows CI.

## Local validation and outstanding evidence

- 20 new hermetic tests passed using `python -m unittest discover -s tests -p test_windows_storage_prevention.py -v`, including independent offline-workflow event/scope predicates and unchanged required validation.
- All three unmodified baseline release-provenance test functions passed when invoked directly; pytest was unavailable in this selected-file environment.
- Both workflows parsed successfully as YAML, including the Desktop dispatch choices, its five jobs, and the offline workflow's three jobs.
- The complete attestation/publisher section matched the fetched main section byte-for-byte.

These checks establish source-level policy behavior, including zero ordinary-PR uploads and refusal of an oversized or unverified preview. They do not establish a live artifact upload, a native Windows installer result, the full application test suite, released binaries, or a cleared account storage block. PowerShell and actionlint are unavailable locally; GitHub's workflow validation and the actual Windows jobs remain required before merge.
