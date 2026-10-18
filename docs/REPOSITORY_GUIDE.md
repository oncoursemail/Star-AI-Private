# STAR Intelligence — repository map and safe cleanup

**Canonical development home:** [oncoursemail/Star-AI-Private](https://github.com/oncoursemail/Star-AI-Private) (**private**), with STAR's source, the Windows builder and internal tests. The separate [oncoursemail/Star-AI](https://github.com/oncoursemail/Star-AI) (**public**) is the canonical installer/download, auto-update, static landing page and support channel. The desktop checks the public Releases API without credentials. See [migration instructions](PRIVATE_PUBLIC_RELEASE_MIGRATION.md).

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

## Private build to public Releases flow

1. Developers create isolated branches in the **private source repo** and open review PRs. No auto-merging or private-code replication to public.
2. A successful private Windows CI build, tests and checksums are required. A new **manual** workflow_dispatch run on private `main` can publish after independent owner approval. Existing tags cannot be reused with different binaries.
3. A public-only GitHub App installation token, created only in the publishing job, writes `STAR-Setup-vX.Y.Z.exe`, `STAR-Genesis-Windows-x64.zip` and `SHA256SUMS.txt` to **public** Star-AI Releases.
4. The updater checks public `Star-AI` unauthenticated Releases, validates exact HTTPS asset URL, size and SHA-256, and prompts to install. Chats, models and lessons under `%APPDATA%\\STAR` remain local and are not GitHub release assets.
5. The now-private repository's React Pages workflow builds preview artifacts **without deploying a website**. Public `Star-AI` has a separate static landing page served using GitHub Pages from `main` root after owner enables it.
6. Private-repository artifact attestations are optional on supported GitHub plans. A checksum is not binary code signing. Verify public downloads anonymously and perform a real Windows update before announcing availability.

Read [PRIVATE_PUBLIC_RELEASE_MIGRATION.md](PRIVATE_PUBLIC_RELEASE_MIGRATION.md) for exact permissions, first-release steps and blocked conditions.

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

The GitHub Windows job must additionally pass packaged `STAR.exe --doctor` and `--ui-doctor`. The final Windows installation/restart, anonymous public download, local GPU response and Roblox Studio workflow require **human-observed native testing**. Do not claim them verified from Linux/Python-only checks.
