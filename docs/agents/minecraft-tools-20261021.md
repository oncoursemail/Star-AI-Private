# minecraft-tools (PR #487 + #504 folded onto star/next, 2026-10-21)

Branch `star/minecraft-tools-20261021`. Sources: origin/star/minecraft-engineering-20261018 (#487) and
origin/star/chatgpt-minecraft-compat-20261019 (#504, stacked), squash-merged onto origin/star/next.

## What it is
- `star/minecraft_assets.py`: offline audit of a Java resource-pack folder/ZIP or `.bbmodel`, deterministic ZIP
  packaging, 2D item pack scaffold from the user's own PNG. #504: PNG chunk CRC check, the packaged ZIP is built from the
  same byte snapshot that was validated (one folder read), injected guide trimmed to the skill budget (body 4594 <= 4600).
- `star/minecraft_server_inventory.py`: static read-only inventory of ONE folder the user names (JAR metadata, family
  hints, allowlisted server.properties). No network, no server connection, no JAR execution, no credentials returned.
- `star/minecraft_tools.py` (new): the four tools as an opt-in tool group like `debug_evidence`. Replaces the #487 hooks in
  `star/workspace.py` (reverted to star/next) so nothing is offered unless the owner turns it on.
- `scripts/install-blockbench-windows.ps1`: reviewed. Default run only checks and prints; `-Install` runs
  `winget install --exact --id JannisX11.Blockbench --source winget` (pinned id, winget checks the manifest hash). No
  download commands, no `-Force`, no auto-accepted agreements, execution policy hint changed from Bypass to RemoteSigned.
- Skill pack `engine-minecraft` + `references/server-assets.md`, research doc `docs/research/minecraft_asset_engineering_2026-10-18.md`.

## Wiring
Setting `minecraft_tools_enabled` (default false; `desktop_core.Settings`, `react_shell` allowed keys, Settings page
switch) -> `MinecraftTools` in `desktop_core` (needs a workspace; write tools only with `workspace_edit`) -> `agent.execute(minecraft_tools=)`
offers tools only for a Minecraft-looking prompt, authorizes per turn, runs in a thread. Read tools are in
`UNTRUSTED_SOURCE_TOOLS` (plugin metadata and file names are untrusted text; full Luau stays off for that turn).
`inspect` requires an explicit `path`.

## Tests (tests/test_minecraft_tools_integration.py, plus the two #487 files adapted)
Agent loop offers/dispatches/rejects, write gating, unknown args, path escape, Luau-after-untrusted, sticky tool
memory, setting default/round trip, desktop route matrix, snapshot packaging, skill pack names real tools + budget,
installer has no silent download. Symlink tests skip when the account lacks the privilege.

## Not verified
Java resource-pack format numbers for 26.x versions come from the research doc; not checked against Mojang data. Nothing was
loaded in a real Minecraft client or server. Blockbench installer was not executed.
