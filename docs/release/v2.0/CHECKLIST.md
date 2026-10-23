# STAR v2.0 release checklist

Written 2026-10-20 against `star/next` at `798d88e7` (4 commits ahead of `main` `80bf8540`). Nothing below is ticked:
every box is a check somebody still has to run, with the evidence to attach next to it. The release is blocked until
every box in sections 1-6 is ticked with evidence, exactly as the standing rules say (never merge to `main` or publish
without the owner's OK and the release checks; honest notes; no force-push).

Previous release: v1.0.0 (2026-10-14, `main`). v1.1 is skipped; its fixes are in v2.0. The milestone issues are
#444 #424 #406 #407 #411 #290 #431 #414 #445 (status in [STATUS.md](STATUS.md)).

## 0. Decide the release channel first (new since v1.0.0)

The source moved to the private repository `oncoursemail/Star-AI-Private`; the public `oncoursemail/Star-AI` is now the
website and downloads repository. The app still checks `oncoursemail/Star-AI` releases for updates
(`star/version.py` `REPO`, `star/updates.py`), which is right for users, but:

- [ ] The owner decides how a v2.0 Setup/ZIP gets from the private CI to the public Releases page. Draft PR #489
      proposes a private-main publisher with a public GitHub App; it is unmerged and needs the owner to install the
      apps and set two Actions variables/secrets. Until this is decided there is no path from a green private build to a
      public download, and the in-app updater can never see v2.0.
- [ ] `.github/workflows/windows-desktop.yml` (`attest-release`, `publish-release`) is run once end to end on a
      throwaway tag to prove the chosen channel, before the real tag.

## 1. Green head (ledger check 1)

On the exact commit that will be tagged (after the version bump, section 4):

- [ ] Full Python suite on this PC, one suite at a time, fresh profile:
      `APPDATA=<temp> worktrees/pr39/.venv-audit/Scripts/python.exe -m pytest -q -p no:cacheprovider` -> 0 failed.
      On `798d88e7` `tests/test_night_conductor.py::test_cycle_accepts_valid_tasks_dedups_and_writes_report` failed
      (`created 0 == 4`) on an untouched checkout; PR #501 (merged 2026-10-20) fixes it: confirm with a full run on
      the head that gets tagged.
- [ ] `frontend/`: `tsc`, `vitest`, `vite build` (Node at
      `~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe`) -> all green.
- [ ] GitHub CI green on the PR head: `tests.yml`, `windows-desktop.yml` (`frontend`, `windows-tests`,
      `windows-build`), `luau-specs.yml`, `protected-closure.yml`, `dependency-audit.yml`.
      BLOCKED 2026-10-20 since 09:58Z: every Actions job on the private repository fails at start with "recent account
      payments have failed or your spending limit needs to be increased" (private repositories use paid Actions
      minutes). Owner: GitHub Billing & plans. No PR can show green CI until then.
- [ ] Dependabot PRs #461-#472 against `star/next` (frontend majors: TypeScript 7, Vite 8, Vitest 5, motion 14,
      lucide 1.x; pip minimums; actions) are either merged green or explicitly deferred to v2.1 in the notes. Vite 8 +
      Vitest 5 (#507) and Lucide 1.x + pip minimums (#506) were merged on 2026-10-20; TypeScript 7 + motion 14 (#509)
      is still a draft. Do not take a major bump into the release commit without the frontend checks above.

## 2. Real-window acceptance on the head (ledger check 2)

- [ ] `scripts/shell_acceptance.py` passes on a packaged build of the head (CDP, disposable profile), as in v1.0.0
      (`docs/agents/release-v1.0.md` in the workspace: 18/18 checks, "Look at my screen" -> Cancel, key never shown).
- [ ] `STAR.exe --doctor`, `--ui-doctor`, `--build-doctor` on the packaged exe print the exact build commit.

## 3. Windows 11 acceptance (#444, ledger check 3)

Run by the owner on the physical PC (`needs-owner`). Procedure: `docs/STAR_WINDOWS_ACCEPTANCE.md` W01-W13 with
`scripts/windows_acceptance.cmd`; report per item: pass/fail, version, GPU, DPI. Evidence folder
`%USERPROFILE%\STAR-acceptance`, screenshots into `docs/release/v2.0/` (no private addresses in them).

Install and upgrade
- [ ] W01 backup of `%APPDATA%\STAR` (`robocopy ... Failed : 0`) BEFORE anything else. This install is the one
      sanctioned exception to "never touch `%APPDATA%\STAR`", and only through Setup and the app.
- [ ] Upgrade from the installed v1.0.0 with the v2.0 Setup; W02/W07/W08: chats, settings, models preserved.
- [ ] Per-user and all-users upgrade: note whether the administrator prompt appears (#121, fixed in #458; the
      installed copy on the test PC is all-users, so the owner must approve UAC).
- [ ] Upgrade while STAR is running (W04b) and a refused/failed upgrade leaves the old STAR working (W04c; #120,
      #457).
- [ ] Portable ZIP starts; W06 doctors pass.
- [ ] In-app checksum-verified update and restart; a failed update shows an actionable error (needs section 0).

App and AI
- [ ] W09/W10 React UI (not legacy Qt), conversations persist, prompt stored once.
- [ ] W11/W12 STAR Brain install, "Test actual AI response", model checksum, corrupt/missing file errors, offline.
- [ ] Long context, vision references, audio transcription, attachments, with no hosted API key.
- [ ] Two clients using tools at once do not stall each other (#118: fix in #450, live on server 1 since 10-16).

Voice
- [ ] Speaker output heard through real speakers; microphone input and wake phrase.

UI
- [ ] 1050x680 and 1440x900 at 100/125/150 % DPI; keyboard focus, Ctrl+K, Esc, Enter vs Shift+Enter, code copy,
      send/retry, reduced motion.

Roblox
- [ ] Disposable unpublished Studio place only: MCP discovery read-only first, then scoped writes, undo, screenshots.

## 4. Version bump and notes (ledger check 5)

- [ ] Version `2.0.0` in `star/version.py`, `pyproject.toml`, `installer/STAR.iss`, `frontend/package.json`,
      `frontend/src/constants.ts`, `frontend/src/Desktop.tsx`, `frontend/src/fake-desktop.ts`, `frontend/src/siteContent.ts`, `frontend/src/SiteDownload.tsx`, `site/version.json`;
      `tests/test_version_sync.py` and `tests/test_releases_and_site.py` pass.
- [ ] `CHANGELOG.md` gets a `[2.0.0]` section (one line per merged PR, "opt-in" only where the PR says so).
- [ ] `docs/release/v2.0/RELEASE_NOTES.md` finished from [RELEASE_NOTES_DRAFT.md](RELEASE_NOTES_DRAFT.md): only
      merged and verified features; the "Measured results" and "Not tested" sections filled from sections 5 and 3.

## 5. Evaluation gate on the release head

Same setup as v1.0.0 so the numbers compare: STAR Server (brain 1) model `star-fast`, mode auto, skill packs off,
knowledge on, temperature 0, quiet server (night school `HOLD` file present, no other eval, no `/opt/star/lock`
quiet lock because the runner cancels under it), two runs per task for the paired gate.

- [ ] `python -m star.evals run --suite evals/roblox/golden-tasks-v2.json --out evals/results/v200-v2-{1,2}.json`
- [ ] `python -m star.evals run --suite evals/roblox/golden-tasks-creation-v1.json --out evals/results/v200-creation-{1,2}.json`
- [ ] `python -m star.evals run --suite evals/roblox/holdout-v1.json --out evals/results/v200-holdout-{1,2}.json`
- [ ] `python -m star.evals gate --paired-session --baseline <v1.0.0 files> --candidate <v2.0 files>` per suite.
      PROMOTE or INCONCLUSIVE ("about the same") may ship; a REGRESS blocks. v1.0.0 reference: v2 16/34,
      creation 10/23, holdout 9/24 (all inconclusive vs v0.9.0). The v1.0.0 result files are on the PC under
      `work/eval-runs/v100-*.json`, not in the repository.
- [ ] Timeouts get ONE re-run each with `--retry-errors` on a quiet server; `--tasks` rewrites the result file, so
      copy it first (runner bug noted in `docs/agents/release-v1.0.md`).
- [ ] Record model/server/commit/date next to every number in the notes.

## 6. Security and honesty (ledger check 4 and 5)

- [ ] Security review of `star/next` vs `main` by one assistant, the other reads it: no open finding on merged code
      (new tool switches off by default; a grep of the diff for the private subnet prefix and the server login names, as listed in the workspace ledger, is empty).
- [ ] The notes say plainly what was and was not verified (the draft keeps the two lists apart).
- [ ] Owner's explicit OK in chat for the `star/next -> main` PR and for publishing (the one in the ledger covers
      v1.0; v2.0 needs its own).

## 7. After the tag

- [ ] Verify the published Setup, ZIP and `SHA256SUMS.txt` (W03 with `--tag v2.0.0`), the attestation, and that the
      installed v1.0.0 sees the update ("Installed v1.0.0, latest v2.0.0").
- [ ] Close #444 with the per-item report; close the milestone only when every issue is closed or moved.
