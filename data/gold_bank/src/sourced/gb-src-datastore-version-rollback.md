---
id: gb-src-datastore-version-rollback
category: datastore-safety
topics: DataStore versioning, ListVersionsAsync, GetVersionAsync, rollback, DataStoreSetOptions, metadata
source: adapted
source_id: creator-docs
source_path: content/en-us/cloud-services/data-stores/versioning-listing-and-caching.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
A bug yesterday at about 14:00 UTC wiped some players' inventories. Data stores keep old versions, right? How can I write an admin function that restores a player's data to the last version saved before a given time?

# Answer
List the key's versions newest first up to the cutoff time with `ListVersionsAsync` (the max date is in milliseconds), read the first one with `GetVersionAsync`, and write it back as the current value, keeping its user ids and metadata. Use `UpdateAsync` for the write so it is a normal, versioned change you can undo again.

```lua
--!strict
local DataStoreService = game:GetService("DataStoreService")

local store = DataStoreService:GetDataStore("PlayerData")

local Rollback = {}

function Rollback.restoreBefore(key: string, cutoff: DateTime): (boolean, string)
	local okList, pages = pcall(function()
		return store:ListVersionsAsync(key, Enum.SortDirection.Descending, nil, cutoff.UnixTimestampMillis)
	end)
	if not okList then
		return false, "list failed: " .. tostring(pages)
	end
	local versions = pages:GetCurrentPage()
	if #versions == 0 then
		return false, "no version before the cutoff"
	end

	local version = versions[1]
	local okGet, value, info = pcall(function()
		return store:GetVersionAsync(key, version.Version)
	end)
	if not okGet then
		return false, "read failed: " .. tostring(value)
	end
	if value == nil then
		return false, "that version is a deletion"
	end

	local okSet, err = pcall(function()
		store:UpdateAsync(key, function()
			return value, info:GetUserIds(), info:GetMetadata()
		end)
	end)
	if not okSet then
		return false, "write failed: " .. tostring(err)
	end
	return true, "restored version " .. version.Version
end

return Rollback
```

Usage from an admin command: `Rollback.restoreBefore("Player_" .. userId, DateTime.fromUniversalTime(2026, 10, 19, 14, 0))`. Do it while the player is offline, or their session will save over the restore.

- Versions are kept for 30 days, so restores must happen within that window.
- Returning user ids and metadata from the transform keeps GDPR tagging and any custom metadata intact.
- The restore is itself a new version, so a wrong restore can be rolled back the same way.
