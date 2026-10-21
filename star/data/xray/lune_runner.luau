--[[
Headless X-ray Eyes on Lune (@lune/roblox). Called by star/xray.py; every command writes JSON to OUT.

  lune run lune_runner.luau scan    OUT PLACE [OPTIONS_JSON] [APPLY_TO]   scan a .rbxl/.rbxlx/.rbxm/.rbxmx file
  lune run lune_runner.luau sample  OUT PLACE_OUT [HOUSES]                write the clean sample place
  lune run lune_runner.luau defects OUT PLACE_OUT SEED                    sample place + one planted defect per type
  lune run lune_runner.luau exam    OUT TRIALS SEED                       the planted-defect exam
  lune run lune_runner.luau perf    OUT HOUSES                            build HOUSES houses in memory and time a scan
  lune run lune_runner.luau selftest OUT                                  unit checks with known answers
  lune run lune_runner.luau compile OUT FILE                              syntax-check a Luau file

APPLY_TO writes a COPY of the place with the report's change list applied; the input file is never changed.
]]

local fs = require("@lune/fs")
local process = require("@lune/process")
local roblox = require("@lune/roblox")
local serde = require("@lune/serde")

local Xray = require("./xray")
local Sample = require("./sample_place")
local Exam = require("./exam")
local SelfTest = require("./selftest")

local R = {
	Instance = roblox.Instance,
	Vector3 = roblox.Vector3,
	Vector2 = roblox.Vector2,
	CFrame = roblox.CFrame,
	Color3 = roblox.Color3,
	UDim2 = roblox.UDim2,
	UDim = roblox.UDim,
	Enum = roblox.Enum,
}
local ENV = { mode = "lune" }

local args = process.args
local command, out = args[1], args[2]

local function write(value: any)
	fs.writeFile(out, serde.encode("json", value))
end

local function isXml(path: string): boolean
	local lower = string.lower(path)
	return string.sub(lower, -6) == ".rbxlx" or string.sub(lower, -6) == ".rbxmx"
end

local function isModel(path: string): boolean
	local lower = string.lower(path)
	return string.sub(lower, -5) == ".rbxm" or string.sub(lower, -6) == ".rbxmx"
end

local function newGame(): any
	return roblox.Instance.new("DataModel") -- metallic:allow: Lune creates a DataModel headlessly (not creatable inside Roblox)
end

local function load(path: string): (any, boolean)
	local data = fs.readFile(path)
	if isModel(path) then
		local folder = roblox.Instance.new("Folder")
		folder.Name = "Model"
		for _, inst in roblox.deserializeModel(data) do
			inst.Parent = folder
		end
		return folder, true
	end
	return roblox.deserializePlace(data), false
end

local function save(game: any, path: string)
	fs.writeFile(path, roblox.serializePlace(game, isXml(path)))
end

if command == "scan" then
	local placePath, optionsJson, applyTo = args[3], args[4], args[5]
	local root, model = load(placePath)
	local options = if optionsJson and optionsJson ~= "" then serde.decode("json", optionsJson) else {}
	local t = os.clock()
	local report, targets = Xray.scan(root, options, ENV)
	report.scanSeconds = os.clock() - t
	if applyTo and applyTo ~= "" then
		for k, change in report.changes do
			local inst = targets[k]
			inst.CFrame = inst.CFrame + roblox.Vector3.new(change.dx, change.dy, change.dz)
		end
		if model then
			fs.writeFile(applyTo, roblox.serializeModel(root:GetChildren(), isXml(applyTo)))
		else
			save(root, applyTo)
		end
		report.appliedTo = applyTo
		report.applied = #report.changes
	end
	write(report)
elseif command == "sample" then
	local game = newGame()
	Sample.build(game, R, tonumber(args[4]) or 1)
	save(game, args[3])
	write({ written = args[3], parts = #game:GetService("Workspace"):GetDescendants() })
elseif command == "defects" then
	local game = newGame()
	local meta = Sample.build(game, R, 1)
	local origin = meta.parts.Floor.CFrame.Position
	meta.originX, meta.originZ = origin.X - 12, origin.Z - 10
	local plants = Exam.plant(R, Xray, meta, Exam.lcg(tonumber(args[4]) or 1))
	save(game, args[3])
	write({ written = args[3], plants = plants })
elseif command == "exam" then
	write(Exam.run(R, Xray, Sample, newGame, tonumber(args[3]) or 20, tonumber(args[4]) or 1, ENV))
elseif command == "trial" then
	write(Exam.trial(R, Xray, Sample, newGame, tonumber(args[3]) or 1, tonumber(args[4]) or 1, ENV))
elseif command == "selftest" then
	write(SelfTest.run(R, Xray))
elseif command == "compile" then
	-- syntax check of a Luau file (used for the generated Studio snippet)
	local luau = require("@lune/luau")
	local ok, err = pcall(luau.compile, fs.readFile(args[3]))
	write({ ok = ok, error = if ok then nil else tostring(err) })
elseif command == "perf" then
	local game = newGame()
	local t = os.clock()
	Sample.build(game, R, tonumber(args[3]) or 220)
	local built = os.clock() - t
	t = os.clock()
	local report = Xray.scan(game, nil, ENV)
	write({
		parts = report.parts,
		pairs = report.pairs,
		buildSeconds = built,
		scanSeconds = os.clock() - t,
		ms = report.ms,
		total = report.total,
		counts = report.counts,
		sample = report.findings[1],
	})
else
	error("unknown command: " .. tostring(command))
end
