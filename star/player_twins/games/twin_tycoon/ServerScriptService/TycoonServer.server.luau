--!strict
-- Twin Tycoon server: cash from droppers and clicking, a chain of shop buttons, an obby side path,
-- rebirths and a DataStore save. All state is server-owned; clients only send requests.
local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Config = require(ReplicatedStorage.Shared.Config)
local Rules = require(script.Parent.Rules)

local store = DataStoreService:GetDataStore(Config.DATASTORE)

local remotes = Instance.new("Folder")
remotes.Name = "Remotes"
remotes.Parent = ReplicatedStorage

local function remote(className: string, name: string)
	local r = Instance.new(className)
	r.Name = name
	r.Parent = remotes
	return r
end

local Work = remote("RemoteEvent", "Work")
local Buy = remote("RemoteEvent", "Buy")
local ClearStage = remote("RemoteEvent", "ClearStage")
local Rebirth = remote("RemoteEvent", "Rebirth")
local GetShop = remote("RemoteFunction", "GetShop")
local GetStages = remote("RemoteFunction", "GetStages")

local itemsById = {}
for _, item in Config.ITEMS do
	itemsById[item.id] = item
end

type Data = {
	cash: number,
	owned: { [string]: boolean },
	stage: number,
	rebirths: number,
	multiplier: number,
}

local sessions: { [Player]: { data: Data, loaded: boolean, pending: number, lastStage: number, workWindow: number, workCount: number, stats: Folder } } = {}

local function defaultData(): Data
	return { cash = 0, owned = {}, stage = 0, rebirths = 0, multiplier = 1 }
end

local function incomePerSecond(data: Data): number
	local base = 0
	for id in data.owned do
		local item = itemsById[id]
		if item and item.income then
			base += item.income
		end
	end
	return base * data.multiplier * (1 + Config.REBIRTH_BONUS * data.rebirths)
end

local function sync(player: Player)
	local s = sessions[player]
	if not s then
		return
	end
	(s.stats:FindFirstChild("Cash") :: IntValue).Value = s.data.cash;
	(s.stats:FindFirstChild("Stage") :: IntValue).Value = s.data.stage;
	(s.stats:FindFirstChild("Rebirths") :: IntValue).Value = s.data.rebirths
end

local function load(player: Player): (boolean, Data?)
	for attempt = 1, 3 do
		local ok, result = pcall(function()
			return store:GetAsync("u_" .. player.UserId)
		end)
		if ok then
			return true, result
		end
		task.wait(attempt)
	end
	return false, nil
end

local function save(player: Player)
	local s = sessions[player]
	if not s or not s.loaded then
		return -- never overwrite a save we failed to read
	end
	local snapshot = table.clone(s.data)
	snapshot.owned = table.clone(s.data.owned)
	for attempt = 1, 3 do
		local ok = pcall(function()
			store:SetAsync("u_" .. player.UserId, snapshot)
		end)
		if ok then
			return
		end
		task.wait(attempt)
	end
	warn("save failed for", player.UserId)
end

Players.PlayerAdded:Connect(function(player: Player)
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	for _, name in { "Cash", "Stage", "Rebirths" } do
		local v = Instance.new("IntValue")
		v.Name = name
		v.Parent = stats
	end
	local ok, saved = load(player)
	local data = defaultData()
	if ok and type(saved) == "table" then
		data.cash = tonumber(saved.cash) or 0
		data.stage = tonumber(saved.stage) or 0
		data.rebirths = tonumber(saved.rebirths) or 0
		data.multiplier = tonumber(saved.multiplier) or 1
		if type(saved.owned) == "table" then
			for id, v in saved.owned do
				if itemsById[id] and v == true then
					data.owned[id] = true
				end
			end
		end
	end
	if player.Parent ~= Players then
		return
	end
	sessions[player] = { data = data, loaded = ok, pending = 0, lastStage = -math.huge, workWindow = -1, workCount = 0, stats = stats }
	stats.Parent = player
	sync(player)
end)

Players.PlayerRemoving:Connect(function(player: Player)
	save(player)
	sessions[player] = nil
end)

game:BindToClose(function()
	for _, player in Players:GetPlayers() do
		save(player)
	end
end)

RunService.Heartbeat:Connect(function(dt: number)
	for player, s in sessions do
		s.pending += incomePerSecond(s.data) * dt
		if s.pending >= 1 then
			local whole = math.floor(s.pending)
			s.pending -= whole
			s.data.cash += whole
			sync(player)
		end
	end
end)

task.spawn(function()
	while true do
		task.wait(Config.AUTOSAVE_SECONDS)
		for _, player in Players:GetPlayers() do
			save(player)
		end
	end
end)

Work.OnServerEvent:Connect(function(player: Player)
	local s = sessions[player]
	if not s then
		return
	end
	local window = math.floor(os.clock())
	if window ~= s.workWindow then
		s.workWindow = window
		s.workCount = 0
	end
	s.workCount += 1
	if s.workCount > Config.WORK_MAX_PER_SECOND then
		return
	end
	s.data.cash += Config.WORK_REWARD * s.data.multiplier * (1 + Config.REBIRTH_BONUS * s.data.rebirths)
	s.data.cash = math.floor(s.data.cash)
	sync(player)
end)

Buy.OnServerEvent:Connect(function(player: Player, id: unknown)
	local s = sessions[player]
	if not s or type(id) ~= "string" then
		return
	end
	local item = itemsById[id]
	if not item or s.data.owned[id] then
		return
	end
	if item.requires and not s.data.owned[item.requires] then
		return
	end
	if s.data.cash < item.price then
		return
	end
	s.data.cash -= item.price
	if item.multiplier then
		Rules.applyUpgrade(s.data, item)
	else
		s.data.owned[id] = true
	end
	sync(player)
end)

ClearStage.OnServerEvent:Connect(function(player: Player, stage: unknown)
	local s = sessions[player]
	if not s or type(stage) ~= "number" or stage % 1 ~= 0 then
		return
	end
	if not Rules.validStageClear(s.data, stage, #Config.STAGES) then
		return
	end
	local now = os.clock()
	if now - s.lastStage < Config.STAGE_MIN_SECONDS then
		return
	end
	s.lastStage = now
	s.data.stage = stage
	s.data.cash += Config.STAGE_REWARD * stage
	sync(player)
end)

Rebirth.OnServerEvent:Connect(function(player: Player)
	local s = sessions[player]
	if not s then
		return
	end
	if not s.data.owned.dropper5 or s.data.cash < Config.REBIRTH_COST then
		return
	end
	Rules.applyRebirth(s.data)
	sync(player)
end)

GetShop.OnServerInvoke = function(player: Player)
	local s = sessions[player]
	if not s then
		return nil
	end
	local list = {}
	for _, item in Config.ITEMS do
		table.insert(list, {
			id = item.id,
			name = item.name,
			price = item.price,
			income = item.income,
			multiplier = item.multiplier,
			owned = s.data.owned[item.id] == true,
			available = item.requires == nil or s.data.owned[item.requires] == true,
		})
	end
	return {
		items = list,
		income = incomePerSecond(s.data),
		rebirth = {
			cost = Config.REBIRTH_COST,
			unlocked = s.data.owned.dropper5 == true,
			available = s.data.owned.dropper5 == true and s.data.cash >= Config.REBIRTH_COST,
		},
	}
end

GetStages.OnServerInvoke = function(player: Player)
	local s = sessions[player]
	if not s then
		return nil
	end
	local list = {}
	for i, difficulty in Config.STAGES do
		table.insert(list, { stage = i, difficulty = difficulty, reward = Config.STAGE_REWARD * i, cleared = i <= s.data.stage })
	end
	return list
end
