# STAR Intelligence — repository map and safe cleanup

**Source home:** [oncoursemail/Star-AI-Project](https://github.com/oncoursemail/Star-AI-Project) (renamed from Star-AI-Private on 2026-10-31): STAR's source, React website, Windows build workflow, work branches (`star/next`). **Downloads:** [oncoursemail/Star-AI](https://github.com/oncoursemail/Star-AI) holds only the public website and [official Releases](https://github.com/oncoursemail/Star-AI/releases/latest), the single download/update channel; never push source branches there. No separate `Star-Intelligence-Downloads` repository, mirror token, or duplicated publisher is required.

## Finding things quickly

| Directory | Purpose | Typical owner/review |
|---|---|---|
| `frontend/` | React/TypeScript website and desktop chat interface | UI changes, UX tests |
| `star/` | Python agent/model/controller, memory, policy, integrations, updater | Runtime and security review |
| `installer/` | Stable AppId and in-place Windows upgrade rules | Windows native acceptance |
| `scripts/` | Reproducible build, captures, diagnostics | Build and QA review |
| `.github/workflows/` | Test gates, Windows packages/public Releases, React Pages | Independent CI/release review |
| `tests/` and `evals/` | Regressions, fixtures and benchmarks (never fabricate pass results) | Test owner |
| `docs/` | Live guidance + historical research/design/release gates | Documentation review |
| `assets/` | Local app images/icons | Design review |
| `examples/` | Small source trees STAR builds and tests, such as the Roblox test place ([Roblox access](ROBLOX_ACCESS.md)) | Runtime review |
| `site/` | Historical standalone site used by compatibility fixtures | Keep until separately migrated |

Key starting points: [README](../README.md), [architecture](ARCHITECTURE.md), [release/update model](RELEASES_AND_MODELS.md), [GitHub App setup](GITHUB_APP_SETUP.md), [working agreement](../AGENTS.md).

## Canonical public release flow

1. Developers use task branches and open PRs. Do **not** merge untested agent-generated changes.
2. After merging to `main`, the Windows workflow builds/test-packs `STAR.exe` and its React assets. Only a successful `publish-release` job may publish a **new** version tag.
3. GitHub Releases on this repo holds `STAR-Setup-vX.Y.Z.exe`, `STAR-Genesis-Windows-x64.zip` and `SHA256SUMS.txt`. Actions *artifacts* are not Releases.
4. The updater reads this repo's unauthenticated Release API and checks the exact official HTTPS asset URL, length, and SHA-256 before staging a user-approved installer. User data remains under `%APPDATA%\\STAR` and is **never** cleaned as part of repository maintenance.
5. Pages builds the public React site from `frontend/`, **not** `site/` or a download mirror. Deployment still depends on the Pages configuration.

## Several agents working at once

- Before any edit, inspect the `main` SHA, open PRs and their changed files. Work only on **your own uniquely named branch** and make small, related commits.
- Unmerged branches/PRs may contain important work; do not delete, rename, reset, force-push, auto-merge, or overwrite them during housekeeping.
- Treat `star/policy.py`, `star/github_app.py`, `star/updates.py`, installer files and workflow permissions as **review-gated** paths. CI green is not equivalent to live Windows/Roblox verification.
- Avoid UI merges that revive multiple STAR desktop interfaces: image generation belongs inside the same chat, while old UI may remain temporarily for compatibility.
- Keep old research notes as historical evidence when they add context; update/remove only superseded *active* instructions or genuinely unused code paths. Use this guide as the current map rather than trusting older release documents.
- Preserve all user conversations, local projects, models, settings, reference media, secrets, and Git history. Never commit those to this public repository.

## Verification checklist

```powershell
python -m compileall -q star main.py star_desktop.py
python -m pytest -q
npm install --prefix frontend --no-audit --no-fund
npm run typecheck --prefix frontend
npm run test --prefix frontend
npm run build --prefix frontend
```

The GitHub Windows job must additionally pass packaged `STAR.exe --doctor` and `--ui-doctor`. The final Windows installation/restart, local GPU response and Roblox Studio workflow require **human-observed native testing**. Do not claim them verified from Linux/Python-only checks.
