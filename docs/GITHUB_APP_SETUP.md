# STAR GitHub access — private development and public distribution

**Development source:** [`oncoursemail/Star-AI-Private`](https://github.com/oncoursemail/Star-AI-Private).
**Public downloads and support:** [`oncoursemail/Star-AI`](https://github.com/oncoursemail/Star-AI).
The public repository distributes reviewed installers and public materials; it is
not a destination for STAR's development source, internal research, or private data.

## Read repository context across renames

The optional repository reader discovers the repositories visible to an existing
credential and retains their stable numeric IDs. It refreshes their current names
and default branches before selecting source. If a former name is reused by a
different repository, the reader continues to require the original ID. This is
separate from STAR's narrowly scoped draft-writing GitHub App.

From a source checkout containing this feature:

```powershell
python main.py project-catalog
python main.py github-inventory --credential-source gh
python main.py github-resolve --repository-id 1412474221 --credential-source gh
python main.py github-read --repository-id 1412474221 --credential-source gh README.md
```

`gh` means the owner explicitly selected the existing GitHub CLI credential for
`github.com`. The reader captures it in memory using a fixed command; it does not
print it or save a copy. The alternative `env` source uses `STAR_GITHUB_READ_TOKEN`
and `STAR_GITHUB_READ_TOKEN_KIND` (`user` or `installation`). It does not fall back
to another token when the selected source fails.

The desktop integration is a curated in-process connector, disabled by default.
In a build containing this feature, open **Tools → Connected research tools →
GitHub repositories**, enable it, choose the credential source, and click **Save
connector settings**. Then use **Check repositories** to check the saved source.
It exposes only project names, repository inventory, identity resolution, and
bounded text reads through the existing discovery-before-call MCP gateway. It does
not accept arbitrary server URLs or general subprocess configuration. See
[repository discovery](GITHUB_REPOSITORY_DISCOVERY.md) for exact settings, tool
contracts, credential scope, and limits. The optional stdio entry point is for
external MCP clients; it is not a generic desktop registration mechanism.

An inventory is limited to the repositories visible to its credential. GitHub
installation selection, account access, and token scopes still apply; metadata
visibility or a reported role does not prove contents or write access. Pagination
completion is not an atomic snapshot of a changing account. No discovery result
grants new permissions or changes the writer's allowlist.

## Existing draft-writing GitHub App

The source writer remains a separate, restricted capability. Its configured
repository and base branch must pass the installed writer's executable checks.
Broad repository read access does not authorize source publishing, merges, releases,
workflow changes, or administration.

**Migration checkpoint:** the older writer and older instructions assumed public
development in `Star-AI`. The owner has since moved development to
`Star-AI-Private`. The separate [private/public migration PR #489](https://github.com/oncoursemail/Star-AI-Private/pull/489)
owns that writer migration. Before configuring the writer, inspect the installed
implementation and the migration's actual status. This reader addition does not
deploy that migration. If the installed writer still accepts only `Star-AI`, stop
the source-publishing path and update through the reviewed migration; do not point
private source at the public distribution repository to satisfy an old check.

For a reviewed writer that supports the private development repository:

1. Keep the GitHub App restricted to the intended development installation. Its
   existing development permissions are Contents read/write, Pull requests
   read/write, and Metadata read. Do not expand the App's own privileges from
   model-generated instructions.
2. Install the development App on the intended private development repository.
   Keep its private key outside every repository, and record only the key's local
   path in ignored operator configuration.
3. Configure the real App ID, installation ID, key path,
   `STAR_GITHUB_REPO=oncoursemail/Star-AI-Private`, and an existing
   `STAR_GITHUB_BASE_BRANCH=star/<work-branch>` that the writer permits.
4. Verify read access before proposing a draft change. Retain the installed
   restrictions on branch names, allowed upload paths, and review requirements.

The existing writer contract permits only candidate `star/skills/*.py` modules
(excluding the package `__init__.py`) and `docs/skills/*.md` on its allowed work
branches. It refuses `main`, tests, evaluation files, dependencies, workflows, and
other source paths. This document does not widen that contract.

## Public releases

Official Windows downloads come from [public STAR Releases](https://github.com/oncoursemail/Star-AI/releases).
Ordinary installations need no private-repository credential to check those
releases or download published assets. Use the separately reviewed release
migration and current release workflow for publication; do not assume a private
repository's ordinary job token can publish to another repository.

Do not restore the retired `Star-Intelligence-Downloads` mirror. Do not paste keys,
tokens, private logs, or operator configuration into issues, chat, or public files.

See [the repository map](REPOSITORY_GUIDE.md),
[Metallic project names](METALLIC_PROJECT_NAMES.md),
[Metallic domain readiness](METALLIC_DOMAIN_READINESS_20261019.md), and
[GitHub's installation authentication documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation).
