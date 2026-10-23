# Metallic and STAR project identities

The owner confirmed these product names and purposes on **2026-10-19**. Use them
in new user-facing text, project references, and repository research.

| Canonical product name | Owner's meaning | Repository | Stable repository ID |
| --- | --- | --- | --- |
| **Metallic-RC** | Our own Rec Room | [oncoursemail/Metallic-RC](https://github.com/oncoursemail/Metallic-RC) | `1420186760` |
| **Metallic-MC** | Minecraft | [oncoursemail/Metallic-MC](https://github.com/oncoursemail/Metallic-MC) | `1424831109` |
| **Metallic-RB** | Roblox Rec Room | [oncoursemail/Metallic-RB](https://github.com/oncoursemail/Metallic-RB) | `1408973704` |
| **Metallic-PX** | Progress | [oncoursemail/Metallic-PX](https://github.com/oncoursemail/Metallic-PX) | `1410841343` |

The earlier repository name `oncoursemail/Metallic` belongs to **Metallic-RC**.
The repository was renamed while retaining ID `1420186760` and private
visibility. The old name is kept only as a historical alias in the catalog;
it is never used to select a repository or authorize an operation.

STAR has two repository roles:

| Role | Repository | Stable repository ID |
| --- | --- | --- |
| Private source and development | [oncoursemail/Star-AI-Private](https://github.com/oncoursemail/Star-AI-Private) | `1412474221` |
| Public distribution | [oncoursemail/Star-AI](https://github.com/oncoursemail/Star-AI) | `1424898960` |

These labels describe project identity. They do not change the existing
GitHub App publishing configuration or its permission gates. See
[GitHub App setup](GITHUB_APP_SETUP.md) for that separate configuration.

## How STAR uses the names

`star/project_catalog.py` is the machine-readable catalog. It supplies the
offline `project-catalog` CLI command and `metallic_project_names` tool.
The reader attaches a catalog entry only when a fresh GitHub record has the
matching numeric repository ID.

Treat `expected_full_name` as the last owner-confirmed repository path. Refresh
the actual `full_name` from the credential-visible GitHub inventory before
reading source. If a repository is renamed or transferred, its current name is
metadata; its selected identity is still its repository ID. A deleted repository
recreated under the same name has a different identity and must not inherit the
old project's binding automatically.

This avoids relying on rename redirects. GitHub documents that reusing an old
repository name can stop the redirect to the renamed repository:
[Renaming a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).
The reader then uses GitHub's
[global node IDs](https://docs.github.com/en/graphql/guides/using-global-node-ids)
to bind subsequent queries to the repository found in the inventory.

The installed desktop's `project` setting is also a conversation and knowledge
namespace. A product rename is not a request to rename that namespace or move
existing chat history. On 2026-10-19 the exact four owner-confirmed product facts
and the domain purchase fact were stored and reviewed through the existing
knowledge API in the desktop's `STAR` namespace, after a database backup.
No inferred research lesson or model training was included in that operation.

## Domain

The owner reports purchasing **Metallic.club**. Its normalized domain name is
`metallic.club`. Purchase, DNS configuration, a deployed application, and the
ability to connect remotely are separate facts.

The static catalog records the purchase statement without claiming to verify
DNS or deployment; hosting decisions are the owner's and are not recorded here.

## Retrieval and access

Use [GitHub repository discovery](GITHUB_REPOSITORY_DISCOVERY.md) for fresh
enumeration, explicit credential selection, current-name resolution, and
commit-pinned source reads. Neither a familiar product name nor a catalog ID
grants access to a private repository. The selected GitHub credential must
actually expose that repository, and the requested source read must succeed.
