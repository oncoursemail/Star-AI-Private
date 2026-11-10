---
name: roblox-studio-mcp-workflow
description: Field-tested Roblox Studio MCP workflow - pick the right Studio, install code from files in Edit, require coverage, confirmed cloud saves, real screenshots and keeping a place safe from accidental deletes.
---
# roblox-studio-mcp-workflow
## When to use
Use when driving Roblox Studio through MCP or plugins to install scripts from files, save a place, take QA screenshots or test multiplayer. Distilled from a large Studio port project where these steps failed in practice. [F1][F2]

## Ten concrete rules
1. Studio instance IDs change on every restart; list the open Studios again and pick yours by place name. Play clients appear as extra instances. [F1]
2. Install only in Edit with Play stopped; Play changes are discarded. Restore any temporary module swaps afterwards. [F1][F3]
3. Keep code on disk as the source of truth and install it with a script; never hand-edit generated data modules, change the builder and regenerate. [F1]
4. Before every install, check require coverage: every module an installed module requires must be installed too. A missing one broke production startup. [F1][F3]
5. When others have unfinished edits, install only the named modules plus their dependency closure; fail loudly on dynamic or unknown requires. [F3]
6. A cloud save counts only when the Studio output shows a fresh "Saved new changes ... to Roblox." line after the save. [F1]
7. Right before saving, assert the critical models exist; save tools cannot see inside the place. Studio can auto-update and reopen from the last save, so save after each verified step. [F1][F4]
8. Studio MCP screen capture can render SurfaceAppearance white and can be stale; judge colours and textures from a real window capture at fixed camera anchors. [F1]
9. Lock big static models (BasePart.Locked), never send Delete or clipboard keys to an Edit viewport, and run a guard that re-parents the map if it is removed. [F1][F4]
10. Runtime folders get Archivable = false, so Play-time clones never end up in a saved place. Yield inside long Studio loops to avoid script timeouts. [F4]

## Studio MCP permissions

For an eligible game place, the Studio MCP server exposes the `open_cloud_invoke` tool. Permissions are per game and per person; each collaborator manages their own permission set, and the external client never receives credentials. The user's group role must allow the requested operation. These permissions do not change the separate in-Studio Assistant capability set. [S7]

- Start with Safe or a narrow Custom selection. Do not use Full access for routine code, scene inspection or playtesting.
- Request only the scopes needed for the current task. Read-only inspection may need `universe:read`, `universe.place:read`, `universe.analytics:read` or `universe.place.instance:read`; remote script edits may need `universe.place.instance:write`.
- Keep settings, asset-sharing, money, player-consequence and security permissions off unless the owner explicitly needs that exact operation.
- Asset uploads are limited to folders the owner approved. Keep build exports in a dedicated folder.
- Studio-executed Luau can reach live data stores when the relevant scopes and Studio API Services setting are enabled. Use a separate private test experience; never experiment against production player data.
- HTTP requests require the Network capability and an explicit domain allowlist. Add only the domains required by the task.
- If Studio denies a scope, stop and report the exact missing permission. Never work around the denial with another account, hidden credential or broader unrelated permission.

## Three common mistakes
1. Installing a new module without adding it to the installer list; the next server start fails on require. [F1]
2. Reporting "saved" after pressing Ctrl+S without reading the confirmation line, or saving while the map was missing. [F1][F4]
3. Filing "all textures are white" bugs from an MCP screen capture instead of a real window screenshot. [F1]

## Three correct Luau examples
These run in the Edit datamodel. They check state and do not save the place.

### Example 1: pre-save check
~~~luau
local RunService = game:GetService("RunService")
local function preSaveCheck(path)
    if RunService:IsRunning() then
        return false, "Stop Play before saving"
    end
    local node = workspace
    for _, name in ipairs(path) do
        local child = node:FindFirstChild(name)
        if child == nil then
            return false, "Missing " .. name .. "; do not save"
        end
        node = child
    end
    return true, node:GetFullName()
end
print(preSaveCheck({ "Map", "Arena" }))
~~~
Run it right before every save; a false result blocks the save. [F1]

### Example 2: map guard and part locking
~~~luau
local map = workspace:FindFirstChild("Map")
if map then
    local home = map.Parent
    for _, item in ipairs(map:GetDescendants()) do
        if item:IsA("BasePart") then
            item.Locked = true
        end
    end
    map.AncestryChanged:Connect(function(_, parent)
        if parent == nil and home ~= nil then
            task.defer(function()
                map.Parent = home
                warn("Guard restored " .. map.Name)
            end)
        end
    end)
end
~~~
Run once per Studio launch; Edit history undo stays the first recovery step. [F1]

### Example 3: verify an install
~~~luau
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local function verifyInstalled(container, names)
    local missing = {}
    for _, name in ipairs(names) do
        local found = container:FindFirstChild(name)
        if found == nil then
            table.insert(missing, name)
        elseif not found:IsA("ModuleScript") then
            table.insert(missing, name .. " (wrong class)")
        end
    end
    return #missing == 0, missing
end
local ok, missing = verifyInstalled(ReplicatedStorage, { "Config", "Teams", "Rounds" })
print(ok, table.concat(missing, ", "))
~~~
List every module the installed code requires; any missing name fails the install. [F3]

## Checklist
- [ ] Right Studio picked by place name after this restart
- [ ] Edit datamodel, Play stopped, temporary swaps restored
- [ ] Require coverage passes for every installed module
- [ ] Critical models asserted present right before the save
- [ ] Fresh save confirmation line seen in the output
- [ ] Visual QA from a real window capture, not MCP screen capture

## Sources
Field evidence and official pages: [references/sources.md](references/sources.md). Labels F1-F4 refer to it.
