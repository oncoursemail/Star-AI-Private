# Private Development → Public Releases: STAR AI Migration

**Checked:** 2026-10-18. **Development repository:** `oncoursemail/Star-AI-Private` (private). **Distribution:** `oncoursemail/Star-AI` (public). **Current state:** historic `v1.0.0` builds exist under private Releases; the new public repository initially has no release files.

## Intended boundary

- Private: source, tests, agent branches, proposed improvements, CI builds, owner-approved learning configurations, internal technical research. Keep *personal* chats, model weights, logs with user data and credentials in secure local/owner storage **outside Git**.
- Public: landing page, public support materials, release notes, Windows Setup, portable ZIP, and SHA256SUMS. It should never receive source code, GitHub Actions preview archives, tokens, personal data, or unapproved builds.
- Existing installed STAR versions already read `https://api.github.com/repos/oncoursemail/Star-AI/releases/latest` through `star/version.py` and `star/updates.py`. Keep that public slug unchanged. The new public repository must eventually host a **newer** stable version for them to receive an update.

## What this migration PR changes

1. Converts the private Windows workflow's `publish-release` into a **manual** `workflow_dispatch`-only publication job.
2. Requires matching private `main` tip and successful Windows packaging/tests; preserves artifact hashes from the independent Windows build and requires them to match the files being released.
3. Publishes to `oncoursemail/Star-AI`, never to private Releases, using a short-lived GitHub App token restricted to exactly `Star-AI` and `Contents: write`. No GitHub PAT, repository source checkout in public, or cross-repository git push is required.
4. Uses public `main` as the release tag target (a private commit cannot be a tag target in an unrelated public repo). Records the private SHA **as release text only** for traceability.
5. Refuses release if the tag already exists in either private published Releases or public tags/releases; no overwrite or retag.
6. Stops the private React site workflow from deploying GitHub Pages; its frontend assets remain private Actions preview artifacts.
7. Updates the private working agreement, README and regression tests. The public repo gets an independently maintained, source-free static download page which checks real public release metadata.

### Create the dedicated publishing GitHub App (owner setup)

GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**. Pick a descriptive name such as "STAR Public Release Publisher". Use a homepage URL under the official public `Star-AI` repository; webhooks may be disabled because this app only creates short-lived release tokens. Set **Repository permissions → Contents: Read and write** and grant no account, organization, issues or other repository permissions. Create a private key. In **Install App**, select **only the public `Star-AI` repository** (do *not* install it on `Star-AI-Private`).

In the **private** `Star-AI-Private` repository, configure:
- **Settings → Secrets and variables → Actions → Variables:** `STAR_PUBLIC_RELEASE_APP_CLIENT_ID` = the GitHub App **Client ID** shown on its configuration page.
- **Settings → Secrets and variables → Actions → Secrets:** `STAR_PUBLIC_RELEASE_APP_PRIVATE_KEY` = the whole PEM private key for that GitHub App. Do **not** paste it in issues, chat, the public repo, a commit, or logs.
- Optionally, set repository variable `STAR_PRIVATE_ATTESTATIONS_ENABLED=true` only if the GitHub plan supports private artifact attestations. **GitHub limits private-repository attestations to Enterprise Cloud.** With this unset, the workflow requires the same successful CI jobs and SHA-256 checks but correctly reports that private attestations and code signing are not provided.

Configure private `Settings → Environments → star-public-release`. Where plan features allow, add required reviewers and restrict to main. If required reviewers are unavailable, the publishing job still requires an explicit owner-triggered workflow run on main and normal branch protection; do not assume GitHub enforces an unavailable reviewer control.

Do not switch the GitHub Actions `GITHUB_TOKEN` to broad write; private source verification uses read scope. The app token is minted **only after** tests and hash/source checks, and is automatically revoked at job end. The publisher GitHub App's private key can be rotated or revoked independently.

### Prepare a NEW release version

Historic `v1.0.0` from the private repository is NOT automatically transferable to the new public releases channel and must not be reissued with different binaries. When the migration PR is merged and the release is independently reviewed, choose a new patch version (for example `v1.0.1` if unused). Update all synchronized version entries:

- `star/version.py` (canonical `__version__`)
- `pyproject.toml` and `frontend/package.json` (the version synchronization test checks these)
- `installer/STAR.iss` fallback `StarVersion` and `site/version.json`
- Stable release notes and any visible current-version text.

Run local/sandboxed checks: `python -m compileall -q star main.py star_desktop.py`, `python -m pytest -q`, `npm run typecheck --prefix frontend`, `npm test --prefix frontend`, `npm run build --prefix frontend`. Native Windows smoke, real app-update preservation, malware/signing review, anti-virus false positives, UI polish and actual network downloads remain required. Passing synthetic/offline tests is not native installation proof.

### Run the release workflow

After review and merger to **private main**, go to **Actions → STAR Desktop — Build, Test & Release → Run workflow** on `main`. The manual run builds and tests the Windows packages, optionally attests them, validates exact installer ZIP + SHA-256 against Windows-generated manifest, and attempts to publish to `oncoursemail/Star-AI`. Until the App is configured, the publication job **fails closed** with a clear missing-config error; it never substitutes an unrelated token or uploads source.

Expected new public GitHub Release assets:
- `STAR-Setup-vX.Y.Z.exe`
- `STAR-Genesis-Windows-x64.zip`
- `SHA256SUMS.txt`

The private repo's `gh release create` no longer runs against itself. Public release version tags point at **public main**, not private source SHA.

### Owner verification BEFORE claiming public availability

1. Confirm `https://github.com/oncoursemail/Star-AI/releases/latest` works without authentication or private source access.
2. From an **anonymous** browser, download Setup, ZIP and SHA256SUMS; calculate SHA-256 locally and match both names/hashes.
3. Inspect the public GitHub Release API and confirm correct digest metadata for the exact Setup and portable assets and that no secrets or code bundles were attached.
4. On a real Windows 11 machine, back up `%APPDATA%\STAR`, then test existing installer → update → preserved chats/models/settings → new version and rollback/recovery scenarios.
5. Confirm no private Actions previews, agent outputs, training data, source files or personal files are publicly accessible.
6. Configure the separate **public** repository Settings → Pages → Deploy from a branch → `main` / root, then test `https://oncoursemail.github.io/Star-AI/`. The site's download buttons remain inactive until a valid public release is visible.
7. Disable any *old* GitHub Pages settings on the now-private source repository, if previously configured. Changing code does not necessarily unpublish a prior Pages deployment.
8. Only then announce the new public release channel.

### Failure and rollback

- No App credentials / no public release: the private code stays private and the public landing page honestly shows "No public installer available". Previously installed STAR checks the same public slug but finds no update.
- Build/test/hash/attestation failure: publication is blocked; do not flip skipped tests into successful statuses.
- Existing public tag: abort; deliberately bump version after review.
- Bad public binary: stop advertising/installing it, investigate and issue a new properly tested version; **do not silently replace the same tag**.
- Reverting this migration: revert the private PR after audit; never point the updater to private Releases or expose private source as a workaround.

### Security and product caveats

SHA-256 checksums and GitHub's release API are useful authenticity *signals* only when the download URL and metadata channel are trusted; they are not the equivalent of publisher code signing. GitHub private-repo attestations are optional and plan-dependent. Protect the GitHub App key, enforce branch protection and independent tests, and prefer actual Windows Authenticode signing for production installers when a publisher certificate is available.

This migration does **not** itself publish an executable, configure account secrets/environments, sign binaries, merge a PR, train a model, or test a real Windows update. Those require separate owner or authorized deployment actions.
