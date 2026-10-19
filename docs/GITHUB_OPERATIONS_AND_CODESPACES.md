# STAR GitHub operations, activity evidence and Codespaces

Owner-directed implementation, researched 2026-10-18. This is configuration and engineering work, not a measured improvement to model intelligence or a declaration that a public installer has shipped.

## Repository roles are different authorities

| Role | Repository | Stable GitHub ID | Access |
| --- | --- | --- | --- |
| Development source | oncoursemail/Star-AI-Private | 1412474221 | Owner and explicitly installed developer App only |
| Public distribution | oncoursemail/Star-AI | 1424898960 | Anonymous reads; separate CI publishing App for release writes |

`star/version.py:REPO` intentionally remains the PUBLIC updater location. The old developer client mistakenly imported that value to authorize source writes. `star/repository_roles.py` now holds explicit identities, and `star/github_app.py` uses the PRIVATE source role. Before proposals, it checks GitHub's actual full name, stable ID and private visibility. Renames, replacements or an unexpectedly public source repository stop the operation.

`GitHubApp.repository_status()` checks safe metadata from both repositories, using source authentication only for private metadata and an independent anonymous client for public metadata. Failure is reported as unavailable, never replaced by public source or concealed behind fabricated success. The developer App still cannot edit tests, policy, workflows or arbitrary source paths; it proposes skill modules and their documentation on a non-default work branch. It cannot merge itself or obtain release credentials.

## Three separate responsibilities

**Developer:** existing STAR GitHub App, installed only on `Star-AI-Private`, Contents Read/Write and Pull requests Read/Write. It reads approved private project material and creates bounded proposal branches/draft PRs.

**Evaluator / maintainer:** independent tests and reviews decide whether the proposal belongs on `star/next`, and whether a reviewed integration belongs on `main`. A model cannot change its own grading rules or turn a failure into approval. Use ordinary SHA-guarded GitHub merges; never force-push or replace required checks. Batch independent file edits into one coherent commit to avoid restarting expensive CI for every file.

**Publisher:** separate GitHub App installed only on PUBLIC `Star-AI`, Contents Read/Write. Its private key exists only in the private release workflow's secret store, not in STAR's runtime, a Codespace, a PR, a model context or a user download. It uploads exact tested Setup/ZIP/checksums, not the source checkout. See `PRIVATE_PUBLIC_RELEASE_MIGRATION.md` for setup.

A private repository is not a guarantee that distributed software is impossible to inspect. Packaged Python/JavaScript and prompts on a user's machine may be examined. Logic or training data that must remain server-only must not be bundled into the desktop app. User chats, credentials, private customer files and model weights belong outside Git history.

## Activity must be attributable, not inferred from marketing

The runtime generates a random run ID. Its commits carry `AI-Actor`, `AI-Run-ID`, `AI-Stage: proposed` and `AI-Tests: not-recorded`. Its draft PR includes a `star-ai-run` receipt. That records a proposal action; it does not certify tests, independent human review, a merge, deployment or a stronger model.

The trusted-base `STAR attributable activity` workflow does not check out or execute PR code. Before adding `actor:star-ai`, it requires all of:

- The PR author is a Bot whose numeric user ID matches owner variable `STAR_DEVELOPER_BOT_ID`.
- GitHub's issue metadata reports the configured `STAR_DEVELOPER_APP_ID` as the application that performed the action.
- The PR contains a well-formed runtime run receipt.

Missing configuration or mismatched identities cannot be silently called Star AI. A falsely applied Star label is replaced with `actor:unverified`. GitHub App identity establishes the credential principal; a textual receipt alone is not cryptographic proof of model authorship. For stronger provenance, use separately controlled signed execution traces and artifact attestations, not agent-written claims.

`actor:chatgpt` and `actor:claude` identify owner-declared assistant involvement. The changes in this migration were made by ChatGPT through the owner's connection, **not by Star AI improving itself autonomously**. Do not retrospectively relabel them as Star work.

Stages reflect GitHub facts: draft proposal, ready for review, and merged. They do not automatically become tested or released. Labels and milestones are organizational metadata, never permissions. The workflows create planned `v1.0.1 — Public update delivery` and `v1.1.0 — Verified AI activity` milestones without claiming either is released. Only known migration PRs and properly attributed new Star proposals are automatically assigned, not the unrelated backlog.

## Automatic updates after controlled integration

The first public migration release requires the existing owner-controlled Windows release workflow, proper publishing credentials and successful native CI. `auto-patch-release.yml` provides a bounded follow-on handoff when owner variable `STAR_AUTO_PATCH_RELEASE=true`:

1. Only a successful PUSH-triggered Windows build on private main is eligible; PR builds, foreign repositories and stale commits are rejected.
2. Read the source version as data from that exact SHA; do not execute fetched code.
3. Read the public release baseline WITHOUT the private token. Only exactly the next patch in the same major/minor series qualifies.
4. Dispatch the existing trusted main release workflow. It rebuilds/rechecks, verifies source/hash constraints and only then obtains its separate public publishing token.
5. Manual workflows cannot recursively trigger another handoff. Existing tags remain immutable. A first release, missing public baseline, skipped patch, minor or major change stays manual.

This is release handoff, not autonomous main-branch merging, model-weight training or proof of human-quality output. A dispatcher receipt means a build was requested, not that an installer exists. The initial rebuilding handoff favors an easily audited trust boundary over maximum speed; a future optimization can reuse exact immutable artifacts after equivalent provenance review.

## Remote host setup and limitations

During inspection the Linux hosts `starai` and `alexbuz1` were reachable; the Windows `Main` machine was offline. Neither Linux host had GitHub CLI authentication. The `starai` learning service environment had no GitHub App settings. The ChatGPT GitHub connection is separate from a token on those servers.

GitHub CLI 2.102.0 was installed under `/home/star/.local/opt/gh-2.102.0/bin/gh`, with a link in `/home/star/.local/bin`, after verifying the official archive SHA-256. No root package changes, model/server restarts, existing working-tree overwrites or credential migration were performed. A separate public checkout is under `/home/star/star-github-workspaces/public`; its Git push URL is deliberately disabled so it cannot accidentally become a source mirror.

For the **developer runtime**, the owner must configure an external, permission-restricted key file and these variables in a dedicated worker environment, not a public file:

```
STAR_GITHUB_REPO=oncoursemail/Star-AI-Private
STAR_GITHUB_BASE_BRANCH=star/next
STAR_GITHUB_APP_ID=<developer App numeric ID>
STAR_GITHUB_INSTALLATION_ID=<private repository installation ID>
STAR_GITHUB_PRIVATE_KEY_FILE=<owner-only PEM path outside the checkout>
```

For **publishing**, configure the separate `STAR_PUBLIC_RELEASE_APP_CLIENT_ID` variable and `STAR_PUBLIC_RELEASE_APP_PRIVATE_KEY` Actions secret in the private repository. For attribution, configure `STAR_DEVELOPER_BOT_ID` and `STAR_DEVELOPER_APP_ID`. A label or saved repository name cannot substitute for these authorizations. Do not paste keys or tokens into chat. The source-check doctor reports missing credentials instead of borrowing an unrelated service's API key.

## GitHub Codespaces: useful development capacity, not a production AI host

Codespaces provides a reproducible Linux development environment accessible in a browser, VS Code or GitHub CLI. For STAR it is useful for editing private code from a phone when Main is offline, Python/TypeScript tests, reviewing branches and a private frontend preview. It does not replace native Windows/Qt installer validation, local GPU inference or a durable always-on learning service.

The committed `.devcontainer/devcontainer.json` selects Python 3.11, Node 22, GitHub CLI and a small machine baseline. The private repo is the source workspace; the only extra repository permission requested is **Contents: read** for public Star-AI. The owner reviews Codespaces permissions at creation. No release key, broad repository wildcard, Docker socket, production mount, automatic model download or training service is configured. Keep forwarded ports private. No Codespace or paid prebuild was created by this change.

Inside an explicitly created Codespace:

```
. .venv/bin/activate
python -m pip install -r requirements-desktop.txt -r requirements-dev.txt
npm install --prefix frontend --no-audit --no-fund
python -m pytest -q tests/test_github_write_scope.py tests/test_repository_roles.py tests/test_github_operations_contract.py
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run dev --prefix frontend -- --host 0.0.0.0
```

Full Linux/headless dependencies may need adjustment after the first actual container build; this configuration has not been native-Windows-validated or used to claim a passing Codespaces build. A Codespace created from an unreviewed branch can execute that branch's setup: review the configuration before creating it.

Current published personal quotas are 120 included core-hours / 15 GB-month on Free and 180 / 20 on Pro. A two-core hour consumes two quota hours, so these correspond to roughly 60 or 90 two-core running hours. Beyond quota, GitHub lists $0.18 per two-core hour and $0.07/GB-month storage. Stopped instances still occupy storage. Set a spending-stop budget, short idle timeout and retention limit; do not create an unlimited swarm or assume included usage remains unused.

## Primary sources checked

- GitHub App authentication inside Actions: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow
- GITHUB_TOKEN scope: https://docs.github.com/en/actions/concepts/security/github_token
- Secure workflow design: https://docs.github.com/en/actions/reference/security/secure-use
- Codespaces environment and Linux limitation: https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces
- Extra repository access: https://docs.github.com/en/codespaces/managing-your-codespaces/managing-repository-access-for-your-codespaces
- Codespaces security and private forwarding: https://docs.github.com/en/codespaces/reference/security-in-github-codespaces
- Current billing: https://docs.github.com/en/billing/concepts/product-billing/github-codespaces

## What improvement claims require

Track exact source/model revisions, run IDs, useful-task success, latency, resource use, regression counts and separate human UX acceptance. Keep fixed development suites separate from untouched confirmation tasks. Repeatedly tuning on the same holdout does not make a result independently verified. Preserve negative results, rollback and old release hashes. Adding tools, labels, prompts or a private repository does not itself change model weights or prove a capability gain.
