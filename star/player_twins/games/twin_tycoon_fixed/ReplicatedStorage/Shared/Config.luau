--!strict
-- Twin Tycoon tuning. Buttons form a chain: each item needs the one named in `requires`.
local Config = {}

Config.DATASTORE = "TwinTycoon_v1"
Config.AUTOSAVE_SECONDS = 60
Config.WORK_REWARD = 1
Config.WORK_MAX_PER_SECOND = 12
Config.STAGE_MIN_SECONDS = 4
Config.STAGE_REWARD = 40
Config.REBIRTH_COST = 100000
Config.REBIRTH_BONUS = 0.5

Config.ITEMS = {
	{ id = "dropper1", name = "Starter Dropper", price = 25, income = 1 },
	{ id = "dropper2", name = "Basic Dropper", price = 150, income = 3, requires = "dropper1" },
	{ id = "dropper3", name = "Steel Dropper", price = 900, income = 10, requires = "dropper2" },
	{ id = "dropper4", name = "Gold Dropper", price = 4000, income = 35, requires = "dropper3" },
	{ id = "conveyor", name = "Fast Conveyor", price = 12000, multiplier = 1.5, requires = "dropper4" },
	{ id = "dropper5", name = "Diamond Dropper", price = 30000, income = 120, requires = "dropper4" },
}

-- Obby side path: one stage at a time, harder each stage.
Config.STAGES = { 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.6, 4.2, 4.8, 5.5 }

return Config
