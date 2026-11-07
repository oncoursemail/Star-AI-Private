# GitHub repository discovery and source reads

STAR can enumerate the repositories visible to an explicitly selected existing
GitHub credential, keep their stable IDs alongside current names, and read
bounded source files from a verified commit. The reader supports the owner's
[canonical Metallic and STAR projects](METALLIC_PROJECT_NAMES.md) and other
repositories that the same credential exposes.

The desktop connector is **off by default**. It is a curated in-process reader
with four fixed tools. It does not mint tokens, change GitHub scopes, perform
writes, replace the existing draft-PR publisher, or promote retrieved source to
trusted lessons. Source is reference data for the current task.

## Use from a source checkout

The commands below require this change in the checkout and STAR's normal Python
dependencies. The CLI reader uses `httpx`; CLI setup also uses `python-dotenv`.

```bash
python -m star.cli project-catalog
python -m star.cli github-inventory --credential-source gh
python -m star.cli github-resolve --repository-id 1420186760 --credential-source gh
python -m star.cli github-read --repository-id 1420186760 --credential-source gh README.md
```

`project-catalog` is offline. The other commands use the GitHub CLI account
already selected for `github.com` in the account running STAR. `gh` must be on
that process's PATH and signed in with the intended account. STAR runs only the
fixed command `gh auth token --hostname github.com`, captures its result in
memory, suppresses its stderr, and never prints or stores the token. No shell
string or model-supplied subprocess command is accepted. The GitHub CLI's own
credential selection rules still apply:
[gh auth token](https://cli.github.com/manual/gh_auth_token).

Select a branch or commit explicitly when a task requires reproducible source:

```bash
python -m star.cli github-resolve --repository-id 1420186760 --revision main --credential-source gh
python -m star.cli github-read --repository-id 1420186760 --revision COMMIT_SHA --credential-source gh README.md
```

Replace `COMMIT_SHA` with the `commit_sha` returned by resolve. Without an
explicit revision, the reader resolves `HEAD` to a commit before requesting the
file. Every successful source result includes its repository ID, current full
name, commit SHA, file path, verified Git blob hash, and source URL.

CLI JSON can contain private repository names or source text. Handle its output
as project data. Error messages omit upstream response bodies and credential
values.

## Credential choices

| Setting | Meaning |
| --- | --- |
| `--credential-source gh` | Explicitly use this process account's existing GitHub CLI credential. |
| `--credential-source env` | Use only the explicitly configured `STAR_GITHUB_READ_TOKEN`. |
| `STAR_GITHUB_READ_CREDENTIAL_SOURCE` | CLI / external stdio default when no CLI override is present: `env` or `gh`; default `env`. |
| `STAR_GITHUB_READ_TOKEN` | Existing credential for the `env` reader. Keep its value out of source control, chat, and settings JSON. |
| `STAR_GITHUB_READ_TOKEN_KIND` | `user` by default; use `installation` only with a matching existing installation access token. |

The environment reader does not automatically fall back to `GH_TOKEN`,
`GITHUB_TOKEN`, a private key file, another account, or the publisher's token.
Explicit `gh` selection delegates to the GitHub CLI's existing account/store;
the CLI itself may use environment credentials according to its own rules.
An installation credential must already be valid; this reader does not create
or refresh one.

User credentials enumerate `GET /user/repos` with all visibility and the owner,
collaborator, and organization-member affiliations. Installation credentials
enumerate `GET /installation/repositories`. GitHub determines the visible set.
An app installation configured for all repositories is still limited by its
approved permissions and the token in use. Access available to a ChatGPT
connector is not automatically access available to STAR on another machine.

Relevant GitHub documentation:

- [Repositories for the authenticated user](https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user)
- [Repositories accessible to an app installation](https://docs.github.com/en/rest/apps/installations#list-repositories-accessible-to-the-app-installation)
- [REST pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api)

Inventory records report `visibility` and the available `pull`, `push`, `admin`,
`maintain`, and `triage` fields. Missing permission fields remain `null`.
Metadata visibility or a reported role does not prove that a particular file
can be read or that a write operation would succeed. The connector exposes
only reads even when its existing credential has broader rights.

## Use in the desktop

After building and deploying a STAR version containing this change, open
**Tools → Connected research tools**, enable **GitHub repositories**, select
**GitHub CLI account (gh)** or the configured reader environment, and press
**Save connector settings**. Then use **Check repositories** to verify enumeration.
The new fields are:

```json
{
  "mcp_github_repositories": false,
  "github_repository_access_source": "gh"
}
```

These fields hold an opt-in flag and a credential-source label. They never hold
a token. On Windows, the desktop settings file is normally
`%APPDATA%\STAR\settings.json`. The UI uses the existing settings allowlist,
validation, save workflow, and connection test action. A successful test reports
the credential-visible repository count only when enumeration completes.
Individual source reads are verified separately.

Ask STAR, for example: “List my GitHub repositories and the current Metallic
names,” then “Read Metallic-RC's README using its repository ID.” The existing
MCP search-and-disclose step runs before tool calls. Tool schemas, the task call
budget, and read-only restrictions remain in force.

| Tool | Result |
| --- | --- |
| `metallic_project_names` | Offline owner-confirmed names, purposes, stable IDs, and domain statement. |
| `github_repository_inventory` | Fresh inventory metadata and a bounded slice of repository records; use its explicit remaining count and next offset. |
| `github_repository_resolve` | Current repository name and a selected branch/revision pinned to a commit. |
| `github_repository_read` | A supported bounded text file, verified against its Git blob identity. |

An older installed STAR executable does not gain these tools by adding settings
keys. The source CLI can be used independently while a reviewed desktop build
is pending. The separately saved owner name/domain facts are available through
the installed desktop's existing knowledge store.

## Optional external MCP clients

External clients that support stdio MCP servers can explicitly launch:

```bash
python -m star.github_inventory_mcp
```

Set that child process's `STAR_GITHUB_READ_CREDENTIAL_SOURCE` to `gh` to select
the existing CLI credential, or configure the explicit environment reader.
The stdio adapter exposes the same four tools and starts no network listener.
STAR's desktop uses its curated in-process connector; it has no generic stdio
server registration schema. This module does not register or start itself.

## Identity, consistency, and bounds

Each reader operation refreshes GitHub's inventory. It binds the selected
numeric repository ID to the returned global node ID, then queries the node
directly and checks its numeric ID again. A rename, transfer, or reuse of an
old name therefore cannot silently switch the selected repository. Live node
metadata refreshes the full name, visibility, archive state, default branch,
and selected commit. See GitHub's
[global node ID guide](https://docs.github.com/en/graphql/guides/using-global-node-ids),
[repository GraphQL reference](https://docs.github.com/en/graphql/reference/repos),
and [Git object reference](https://docs.github.com/en/graphql/reference/git).

The source query uses the selected node ID and the pinned `commit:path`
expression. It verifies the complete returned text against its byte size and
Git blob hash before truncating context. No API mutation is exposed. Requests
go to fixed GitHub endpoints, redirects are disabled, and pagination links must
match the expected GitHub host, route, and next page. Credentials are not
forwarded to redirect targets or arbitrary URLs.

- Inventory: up to 100 pages of 100 records, with repeated IDs, name collisions,
  changing installation totals, and page limits explicitly reported as
  incomplete. An incomplete inventory cannot select a repository for a read.
- `complete: true` means pagination ended without a detected inconsistency.
  GitHub pagination is not an atomic snapshot: concurrent repository changes
  may escape detection. Refresh after a known change. MCP offsets select a
  slice of a newly refreshed inventory on every call.
- API responses: at most 2 MB; each reader operation has a 60-second overall
  deadline and network requests have a 15-second timeout. Desktop tool calls
  retain the gateway's 30-second deadline.
- Source: supported text files up to 65,000 bytes; hidden, traversal, binary,
  and credential-related paths are excluded. CLI content is at most 18,000
  characters; MCP content begins with a 7,000-character limit and is further
  reduced if needed to keep the whole tool result within 11,000 characters.
  Truncation and omitted inventory records are explicit and JSON stays valid.
- Missing repository IDs and failed authorization stop the operation. They do
  not trigger a same-name fallback, scope change, token search, or public clone.

## Validation record, 2026-10-19

Implementation started from private STAR main
`80bf8540b75633c065437036baf75614afe68f74`. Reader tests use mocked GitHub
transport and cover pagination, missing access, rename and old-name reuse,
fixed credential selection, redirect rejection, hash mismatches, bounds, and
sanitized failures. Gateway tests exercise the actual Settings and MCPGateway,
including default-off behavior, discovery before calls, connection checks, and
existing publisher/MCP regressions. UI coverage checks the save boundary and
the difference between verified inventory, incomplete results, and failures.
The focused runs passed **329 Python tests** and **10 frontend tests**, including
six new connector UI tests and four existing wording tests. Frontend typechecking,
compilation of the changed Python modules, and linting of the new reader modules
and tests passed. This was targeted source validation, not a full Windows package
build or a claim that the full repository test suite ran.

The standalone reader was also exercised on the owner's **Main PC**, using its
existing signed-in `gh` credential and isolated staged source. All three CLI
commands completed with exit code 0:

| Live check | Observed result |
| --- | --- |
| Inventory | `complete: true`, 1 page, 29 credential-visible repositories; all six canonical Metallic/STAR repository IDs present with expected visibility. |
| Resolve Metallic-RC | ID `1420186760` resolved to `oncoursemail/Metallic-RC`, commit `20abe16e8137874615c4cd04fe8c3d4986d0ed6c`. |
| Read Metallic-RC README | The same pinned commit supplied `README.md`; Git blob `e432919d01b4410859be6e2bbcd1ab9c155c0fe8` verified. |

This validates the real credential and source-read path at the observed time.
It does not claim that every repository's files were read, that write access
was exercised, or that the installed desktop has been rebuilt. Token values
and private source contents are omitted from this record.
