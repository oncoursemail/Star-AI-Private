# STAR — Roblox Studio MCP/Open Cloud Permissions and Creator Workflow Research

**Research date:** 2026-11-10  
**Implementation:** updated the opt-in `roblox-studio-mcp-workflow` skill pack and its official-source record.  
**Scope:** least-privilege guidance for interactive Studio MCP work. This is not a permission mutator, API client, or approval to touch a live experience.

## Executive finding

Roblox Studio MCP now provides a first-party bridge from an external MCP client into selected Open Cloud operations through the currently open published game. The important architectural distinction is that Studio owns the permission boundary: the client does not receive an API key, permissions are saved per game and per person, and only the owner can change them.

This is materially different from STAR's existing direct Open Cloud integration in `star/roblox_cloud.py`, which uses an owner-configured key and an owner-approved private test experience for headless workflows. The two paths should remain distinct:

| Workflow | Preferred path | Boundary |
|---|---|---|
| Interactive edits to the currently open game | Studio MCP | Per-game, per-person Studio permissions |
| Inspect/edit current Studio place | Studio MCP tools | Current Studio instance and its permission state |
| Headless CI or remote server tests | Existing direct Open Cloud client | Separate narrowly scoped key, private test universe and explicit approval |
| Live experience changes | Neither by default | Separate owner review and exact operation approval |

Do not pass a direct Open Cloud key into a model prompt or MCP tool result. Do not attempt to extract Studio-managed credentials.

## 1. What Studio MCP adds

The Studio MCP server exposes `open_cloud_invoke` for selected Open Cloud APIs. It can perform supported operations such as reading game information, editing supported place instances, uploading assets from approved folders, managing selected game resources and other scoped operations.

Prerequisites:
- Studio MCP is enabled and the external client is connected.
- A place belonging to a published game is open.
- The owner or group role has permission to manage the requested resource.
- The owner explicitly enables the required permissions in Studio's MCP Permissions UI.

Important properties:
- Permissions are saved for each game.
- Each collaborator configures their own permission set.
- The client can only use scopes enabled for the current game.
- The client cannot enable or widen its own permissions.
- Studio enforces permission checks on every request.
- These permissions apply to external MCP clients; they do not alter the separate in-Studio Assistant capability set.

## 2. Access levels and risk

Roblox exposes four permission states:

| Level | Meaning | STAR recommendation |
|---|---|---|
| Safe | Low-risk scopes only; most permissions disabled | Default starting point for inspection |
| Balanced | Low- and moderate-risk scopes | Use only when the current task requires them |
| Full access | All scopes, including high-risk operations | Never request for routine work |
| Custom | Appears after individual permissions are changed | Preferred for repeatable least-privilege workflows |

Roblox assigns the risk level to each scope. The user should inspect the exact scopes enabled, not rely only on the level label.

### Permission categories

| Category | Representative scopes/capabilities | Engineering policy |
|---|---|---|
| Look at your game | `universe:read`, `universe.place:read`, `universe.analytics:read`, `universe.place.instance:read` | Suitable for inspection when needed |
| Edit your game | `universe:write`, `universe.place:write`, `universe.place.instance:write` | Grant only the exact edit capability |
| Save and load data | `universe-datastores.*`, `universe.ordered-data-store.*`, `memory-store.*` | Treat as access to real player/game data |
| Connect to the internet | Network capability; `universe-messaging-service:publish` | Explicit domain allowlist; no broad network access |
| Publish and manage assets | `asset:*`, `asset-permissions:write`, `creator-store-product:*`, `universe-places:write`, `universe.thumbnail:*` | Owner review; use approved upload folders |
| Money and monetization | `developer-product:*`, `game-pass:*`, `ad.campaign:*` | Separate financial approval |
| Player consequences | `universe.user-restriction:*` | Separate moderation approval |
| Security and credentials | `universe.secret:*`, `universe.place.luau-execution-session:*` | Critical; never grant for ordinary building |

The table is a planning aid, not a substitute for the live scope reference. Individual endpoint requirements can change, and some endpoints may reject the Studio-managed token even when a matching scope is enabled.

## 3. Data-store and HTTP hazards

### DataStoreService and MemoryStoreService

Studio-executed Luau can access DataStoreService and MemoryStoreService when the relevant scopes are enabled. Data-store reads require the objects read scope; writes require the objects update scope. The separate Studio Access to API Services setting must also be enabled.

The dangerous detail is that Studio may access the same live data stores used by players. A test script that writes an inventory, currency balance, quest state or session record can therefore corrupt production data.

STAR policy:
1. Create a separate private test experience and test universe.
2. Use synthetic test accounts and synthetic records.
3. Enable Studio API Services access only for that test experience.
4. Keep production data-store access disabled during ordinary Studio work.
5. Test both reads and writes with explicit fixtures and rollback/recovery procedures.
6. Never use a live player's real data as a convenient test fixture.

### HTTP requests

Allowing HTTP requests grants the Network script capability. The owner must explicitly allow each destination domain. Studio denies requests to domains outside that allowlist.

STAR policy:
- Add one exact domain only when the current task needs it.
- Never use wildcard domains as a convenience.
- Treat response bodies as untrusted input.
- Keep credentials in the Roblox secrets store or another host-managed secret facility, never in Luau source, prompts or logs.
- Do not infer that Network capability implies permission to use every Open Cloud endpoint.

### Asset uploads

The external MCP client can upload only from folders the owner explicitly approves. It cannot copy arbitrary files into an approved folder to bypass the restriction.

STAR policy:
- Export generated assets into a dedicated staging folder.
- Keep source files, temporary renders and final upload artifacts separate.
- Verify the asset file and moderation/status response before referencing it in a game.
- Do not grant asset-sharing or creator-store listing scopes merely because a task needs a basic asset upload.

## 4. Unavailable permissions and endpoint failures

Some scopes cannot be granted to Studio MCP clients, including badge scopes, `universe-datastores.control:*`, `universe-datastores.objects:create`, analytics-alert scopes and legacy scopes. Some endpoints may also reject the Studio-managed token despite a matching scope being enabled.

STAR must:
- stop on a clear permission-denied response;
- report the exact scope or endpoint limitation;
- distinguish an unavailable permission from an invalid request or temporary service error;
- never silently fall back to a broader credential;
- use the Creator Dashboard or a separately configured, owner-approved API-key workflow only when the operation truly requires it.

## 5. Recommended STAR Creator workflow

1. Identify the exact Studio instance and current place/universe.
2. Inspect the current scene, scripts, dependencies and existing changes.
3. Produce a task plan and classify every operation as read, edit, data, network, asset, financial, moderation or security.
4. Calculate the smallest permission set required.
5. Ask the owner to enable only those scopes in the Studio MCP Permissions UI.
6. Build in Edit mode with the source repository as the source of truth.
7. Run static checks and dependency-closure checks.
8. Test in a private experience with synthetic data.
9. Capture visual evidence from the real Studio window and inspect runtime output.
10. Repair failures and rerun the same acceptance tests.
11. Present the diff, test evidence and exact remaining permissions to the owner.
12. Keep any high-impact action as a separate explicit approval step.

This complements STAR's existing Studio workflow rules: select the correct Studio instance after restart, install only in Edit mode, verify require coverage, check critical models before saving, and verify the actual save confirmation.

## 6. Broader research implications for Star

This permissions update fits a larger generalist Creator architecture:

- A planning model decomposes the request into inspect/build/test tasks.
- A read-only Studio observer gathers scene and script state.
- A source-first code worker edits Luau in an isolated worktree.
- A deterministic permission planner recommends the minimum scopes.
- A host-owned Studio MCP adapter executes only the already-approved operation.
- Static analysis, server/client tests and visual QA evaluate the result.
- A reviewer compares the final game state against the original requirements.
- A learning system stores only verified fixes and reusable procedures.

Do not equate additional MCP tools with additional intelligence. The quality gain comes from accurate inspection, correct task decomposition, narrow permissions, real playtesting and reliable repair.

The same principle applies to game-playing: Star should learn mechanics through practice in private environments, evaluate on unseen scenarios, and transfer verified skills between games. A scripted demonstration or a paused-game score is not evidence of live-clock mastery.

## 7. Acceptance tests for the integration

Before enabling the Studio MCP workflow in STAR's desktop:
- the pack remains opt-in and off by default;
- unrelated prompts do not receive this skill text;
- the exact Studio instance and current game are identified by the host;
- missing scopes produce a stop and a clear owner-facing explanation;
- the model cannot change MCP permissions;
- data-store tests are restricted to the private test experience;
- asset upload paths remain inside owner-approved folders;
- Network capability is restricted to explicit domains;
- no API key, secret value or private credential enters model context or logs;
- high-impact operations remain separately owner-approved;
- the source diff and test receipts are preserved for review.

## Sources

1. Roblox Creator Hub, [Use Open Cloud with the Studio MCP server](https://create.roblox.com/docs/studio/mcp-open-cloud) — current tool, per-game/per-person permissions, access levels, scope categories, approved upload folders, Network capability, data stores and unavailable scopes.
2. Roblox Creator Hub, [Open Cloud scopes](https://create.roblox.com/docs/cloud/reference/scopes) — scope names, target types and supported endpoints.
3. Roblox Creator Hub, [Data stores](https://create.roblox.com/docs/cloud-services/data-stores) — Studio API Services access and the shared live-data-store warning.
4. Roblox Creator Hub, [Studio MCP server](https://create.roblox.com/docs/studio/mcp) — connecting an external MCP client to Studio.
5. Roblox, [Agentic Studio workflows](https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic) — structured planning, implementation and playtesting direction; April 15, 2026.
