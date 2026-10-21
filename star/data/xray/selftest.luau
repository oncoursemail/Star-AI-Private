--[[
Unit checks of the X-ray math on hand-built cases with known answers (run: lune run lune_runner.luau selftest OUT).
Each case returns ok + what it measured, so a failure says what went wrong.
]]

local SelfTest = {}

function SelfTest.run(R: any, Xray: any): { [string]: any }
	local results = {}
	local function check(name: string, ok: boolean, got: any)
		table.insert(results, { name = name, ok = ok, got = tostring(got) })
	end
	local function near(a: number, b: number, tol: number?): boolean
		return math.abs(a - b) <= (tol or 1e-6)
	end
	local function part(parent: any, name: string, size: any, cf: any): any
		local p = R.Instance.new("Part")
		p.Name = name
		p.Anchored = true
		p.Size = size
		p.CFrame = cf
		p.Parent = parent
		return p
	end
	local function rec(p: any): any
		local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = p.CFrame:GetComponents()
		return { cx = x, cy = y, cz = z, ax = { r00, r10, r20, r01, r11, r21, r02, r12, r22 }, h = { p.Size.X / 2, p.Size.Y / 2, p.Size.Z / 2 } }
	end
	local V, CF = R.Vector3.new, R.CFrame.new

	-- separating-axis distances
	local folder = R.Instance.new("Folder")
	local a = part(folder, "A", V(2, 2, 2), CF(0, 0, 0))
	local b = part(folder, "B", V(2, 2, 2), CF(2.5, 0, 0))
	check("sat gap 0.5", near(Xray._obbSep(rec(a), rec(b)), 0.5, 1e-4), Xray._obbSep(rec(a), rec(b)))
	b.CFrame = CF(1.7, 0, 0)
	check("sat penetration 0.3", near(Xray._obbSep(rec(a), rec(b)), -0.3, 1e-4), Xray._obbSep(rec(a), rec(b)))
	b.CFrame = CF(3, 0, 0) * R.CFrame.Angles(0, math.rad(45), 0)
	check("sat rotated 45 gap", near(Xray._obbSep(rec(a), rec(b)), 3 - 1 - math.sqrt(2), 1e-4), Xray._obbSep(rec(a), rec(b)))
	b.CFrame = CF(2.2, 0, 0) * R.CFrame.Angles(0, 0, math.rad(45))
	local edge = Xray._obbSep(rec(a), rec(b))
	check("sat rotated edge penetration", near(edge, 2.2 - 1 - math.sqrt(2), 1e-4), edge)

	-- contrast (WCAG reference values)
	check("contrast white/black 21", near(Xray.contrastRatio(1, 1, 1, 0, 0, 0), 21, 1e-9), Xray.contrastRatio(1, 1, 1, 0, 0, 0))
	local grey = 0x77 / 255
	local g = Xray.contrastRatio(grey, grey, grey, 1, 1, 1)
	check("contrast #777 on white 4.48", near(g, 4.48, 0.01), g)

	-- UDim2 layout at a viewport, with the top-bar inset and a list layout
	local sg = R.Instance.new("ScreenGui")
	local f = R.Instance.new("Frame")
	f.AnchorPoint = R.Vector2.new(0.5, 0.5)
	f.Position = R.UDim2.new(0.5, 0, 0.5, 0)
	f.Size = R.UDim2.new(0.5, 0, 0, 100)
	f.Parent = sg
	local list = R.Instance.new("UIListLayout")
	list.Padding = R.UDim.new(0, 10)
	list.SortOrder = R.Enum.SortOrder.LayoutOrder
	list.Parent = f
	local c1 = R.Instance.new("TextButton")
	c1.LayoutOrder = 1
	c1.Size = R.UDim2.new(1, 0, 0, 30)
	c1.Parent = f
	local c2 = R.Instance.new("TextButton")
	c2.LayoutOrder = 2
	c2.Size = R.UDim2.new(0.5, 0, 0, 30)
	c2.Parent = f
	local boxes = Xray.layout(sg, 1000, 600)
	local fb = boxes[f]
	check("layout frame x/w", near(fb.x, 250) and near(fb.w, 500), string.format("%s %s", fb.x, fb.w))
	check("layout frame y with 58 px inset", near(fb.y, 58 + (600 - 58) / 2 - 50), fb.y)
	check("layout list second child below first", near(boxes[c2].y, fb.y + 40) and near(boxes[c2].w, 250), boxes[c2].y)

	-- detectors on tiny scenes
	local function scan(root: any, detectors: { string }): any
		return (Xray.scan(root, { detectors = detectors, fixes = true }, { mode = "lune" }))
	end
	local scene = R.Instance.new("Folder")
	part(scene, "Ground", V(40, 1, 40), CF(0, -0.5, 0))
	local turn = R.CFrame.Angles(0, math.rad(30), 0)
	part(scene, "Base", V(4, 2, 4), CF(0, 1, 0) * turn)
	part(scene, "Lid", V(4, 0.5, 4), CF(0, 2.25 + 0.05, 0) * turn) -- rotated stack with a 0.05 gap
	local r = scan(scene, { "near_miss_gap" })
	local gap = r.findings[1]
	check("rotated near-miss gap 0.05", gap ~= nil and near(gap.value, 0.05, 1e-4), if gap then gap.value else "none")
	check("gap fix moves the lid down 0.05", r.changes[1] ~= nil and near(r.changes[1].dy, -0.05, 1e-4),
		if r.changes[1] then r.changes[1].dy else "none")

	local float = R.Instance.new("Folder")
	part(float, "Ground", V(40, 1, 40), CF(0, -0.5, 0))
	local post = part(float, "Post", V(1, 6, 1), CF(0, 3, 0))
	local sign = part(float, "Sign", V(3, 2, 0.2), CF(0, 5, 2)) -- 1.4 studs from the post, held by a weld
	local weld = R.Instance.new("WeldConstraint")
	weld.Part0, weld.Part1 = sign, post
	weld.Parent = sign
	local loose = part(float, "Balloon", V(1, 1, 1), CF(8, 6, 8))
	r = scan(float, { "floating" })
	local names = {}
	for _, fd in r.findings do
		table.insert(names, fd.path)
	end
	check("floating: welded sign is supported, loose balloon floats",
		#r.findings == 1 and r.findings[1].path == loose:GetFullName() and near(r.findings[1].value, 5.5), table.concat(names, ","))

	local z = R.Instance.new("Folder")
	part(z, "Wall", V(10, 8, 1), CF(0, 4, 0))
	part(z, "Sign", V(2, 2, 0.5), CF(0, 4, -0.25)) -- front face flush with the wall's front face
	r = scan(z, { "z_fighting" })
	check("z-fighting flush sign", #r.findings == 1 and near(r.findings[1].value, 4, 1e-6), #r.findings)
	check("z-fighting fix nudges the sign outward (-z)", r.changes[1] ~= nil and near(r.changes[1].dz, -0.02, 1e-6),
		if r.changes[1] then r.changes[1].dz else "none")

	local ok = true
	for _, res in results do
		ok = ok and res.ok
	end
	return { ok = ok, results = results }
end

return SelfTest
