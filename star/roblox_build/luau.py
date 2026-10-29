"""Compiled parts -> Luau that builds them in Studio (under Workspace/MapDrafts/<name>), lighting Luau, removal Luau.

The data goes in as a Luau table literal, chunked so one execute_luau call stays small. Nothing here touches the
network or the file system; the caller sends the code through STAR's guarded Studio session.
"""
from __future__ import annotations

import re

ROOT = "MapDrafts"
CHUNK_PARTS = 700
_NAME = re.compile(r"^[A-Za-z0-9_]{1,48}$")
MARK = "RB_DONE "


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)[:40] or "Build"
    if not _NAME.fullmatch(cleaned):
        raise ValueError("bad build name")
    return cleaned


def _quote(text: str) -> str:
    """A Luau string literal using only safe ASCII escapes (decimal escapes for anything unusual)."""
    out = ['"']
    for ch in text:
        code = ord(ch)
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif 32 <= code < 127:
            out.append(ch)
        elif code < 256:
            out.append(f"\\{code:03d}")
        else:
            out.append("?")
    out.append('"')
    return "".join(out)


def _n(v: float) -> str:
    text = f"{v:.3f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _row(p: dict, lights: list, texts: list, meshes: dict | None = None) -> str:
    sx, sy, sz = p["z"]
    x, y, z = p["p"]
    rx, ry, rz = p.get("r", (0, 0, 0))
    r, g, b = p["c"]
    flags = (1 if p.get("cc", True) else 0) | (0 if p.get("cast", True) is False else 2) | (4 if p.get("studs") else 0)
    li = 0
    if p.get("light"):
        lights.append(p["light"])
        li = len(lights)
    ti = 0
    if isinstance(p.get("text"), str) and p["text"]:
        texts.append(p["text"])
        ti = len(texts)
    mi = 0
    if p.get("mesh") and meshes is not None:
        key = repr(p["mesh"])
        if key not in meshes:
            meshes[key] = (len(meshes) + 1, p["mesh"])
        mi = meshes[key][0]
    return ("{" + ",".join([_quote(p["s"]), _n(sx), _n(sy), _n(sz), _n(x), _n(y), _n(z), _n(rx), _n(ry), _n(rz),
                            str(int(r)), str(int(g)), str(int(b)), _quote(p["m"]), _n(p.get("t", 0)), str(flags), str(li),
                            str(ti), str(mi)]) + "}")


_BUILDER = """
local LI, TX, MS = {lights}, {texts}, {meshes}
local AS = game:GetService("AssetService")
local made = 0
local templates = {}
local function meshpart(i)
	if templates[i] then return templates[i]:Clone() end
	local m = MS[i]
	local prof, seg = m[1], m[2]
	local ok, mp = pcall(function()
		local em = AS:CreateEditableMesh()
		local rings = {}
		for k, pt in ipairs(prof) do
			rings[k] = {}
			for j = 0, seg - 1 do
				local a = 2 * math.pi * j / seg
				rings[k][j] = em:AddVertex(Vector3.new(math.cos(a) * pt[1], pt[2], math.sin(a) * pt[1]))
			end
		end
		for k = 1, #prof - 1 do
			for j = 0, seg - 1 do
				local j2 = (j + 1) % seg
				em:AddTriangle(rings[k][j], rings[k + 1][j], rings[k + 1][j2])
				em:AddTriangle(rings[k][j], rings[k + 1][j2], rings[k][j2])
			end
		end
		local function cap(k, up)
			if prof[k][1] <= 0.001 then return end
			local c = em:AddVertex(Vector3.new(0, prof[k][2], 0))
			for j = 0, seg - 1 do
				local j2 = (j + 1) % seg
				if up then em:AddTriangle(c, rings[k][j2], rings[k][j]) else em:AddTriangle(c, rings[k][j], rings[k][j2]) end
			end
		end
		cap(1, false)
		cap(#prof, true)
		return AS:CreateMeshPartAsync(Content.fromObject(em))
	end)
	if not ok then return nil end
	templates[i] = mp
	return mp:Clone()
end
for _, e in ipairs(D) do
	local shape = e[1]
	local p
	if shape == "M" then p = meshpart(e[19]) or Instance.new("Part") end
	if p then
	elseif shape == "W" then p = Instance.new("WedgePart")
	elseif shape == "CW" then p = Instance.new("CornerWedgePart")
	else p = Instance.new("Part") end
	if shape == "C" then p.Shape = Enum.PartType.Cylinder end
	p.Size = Vector3.new(e[2], e[3], e[4])
	p.CFrame = CFrame.new(O + Vector3.new(e[5], e[6], e[7])) * CFrame.Angles(math.rad(e[8]), math.rad(e[9]), math.rad(e[10]))
	p.Color = Color3.fromRGB(e[11], e[12], e[13])
	local okm, mat = pcall(function() return Enum.Material[e[14]] end)
	p.Material = okm and mat or Enum.Material.SmoothPlastic
	p.Transparency = e[15]
	p.Anchored = true
	p.CanCollide = bit32.band(e[16], 1) ~= 0
	p.CastShadow = bit32.band(e[16], 2) ~= 0
	if bit32.band(e[16], 4) ~= 0 then
		p.TopSurface = Enum.SurfaceType.Studs
		p.BottomSurface = Enum.SurfaceType.Inlet
	else
		p.TopSurface = Enum.SurfaceType.Smooth
		p.BottomSurface = Enum.SurfaceType.Smooth
	end
	if shape == "S" then
		local m = Instance.new("SpecialMesh")
		m.MeshType = Enum.MeshType.Sphere
		m.Parent = p
	end
	if e[17] > 0 then
		local L = LI[e[17]]
		local l
		if L[1] == "spot" then l = Instance.new("SpotLight"); l.Angle = L[5]; l.Face = Enum.NormalId[L[6]]
		elseif L[1] == "surface" then l = Instance.new("SurfaceLight"); l.Angle = L[5]; l.Face = Enum.NormalId[L[6]]
		else l = Instance.new("PointLight") end
		l.Color = Color3.fromRGB(L[2], L[3], L[4])
		l.Brightness = L[7]
		l.Range = L[8]
		l.Shadows = L[9]
		l.Parent = p
	end
	if e[18] > 0 then
		local g = Instance.new("SurfaceGui")
		g.Face = Enum.NormalId.Front
		g.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
		g.PixelsPerStud = 40
		local t = Instance.new("TextLabel")
		t.Size = UDim2.fromScale(1, 1)
		t.BackgroundTransparency = 1
		t.Text = TX[e[18]]
		t.TextScaled = true
		t.Font = Enum.Font.GothamBold
		t.TextColor3 = Color3.fromRGB(250, 244, 230)
		t.Parent = g
		g.Parent = p
	end
	p.Parent = F
	made += 1
end
"""


def build_chunks(name: str, parts: list[dict], origin=(0.0, 0.0, 0.0)) -> list[str]:
    """Luau programs: the first clears the old draft of this name; each returns 'RB_DONE <count>'."""
    name = safe_name(name)
    chunks = []
    for start in range(0, max(1, len(parts)), CHUNK_PARTS):
        rows, lights, texts, meshes = [], [], [], {}
        for p in parts[start:start + CHUNK_PARTS]:
            rows.append(_row(p, lights, texts, meshes))
        light_rows = ",".join("{" + ",".join([_quote(L["k"]), str(L["c"][0]), str(L["c"][1]), str(L["c"][2]), _n(L["a"]),
                                               _quote(L["f"]), _n(L["b"]), _n(L["r"]), "true" if L["sh"] else "false"]) + "}"
                              for L in lights)
        text_rows = ",".join(_quote(t) for t in texts)
        mesh_rows = ",".join("{{" + ",".join("{" + _n(r) + "," + _n(y) + "}" for r, y in m["lathe"]) + "}," + str(int(m["seg"])) + "}"
                             for _i, m in sorted(meshes.values(), key=lambda v: v[0]))
        head = [f"local O = Vector3.new({_n(origin[0])}, {_n(origin[1])}, {_n(origin[2])})",
                f'local R = workspace:FindFirstChild("{ROOT}") or Instance.new("Folder")',
                f'R.Name = "{ROOT}"', "R.Parent = workspace"]
        if start == 0:
            head += [f'local old = R:FindFirstChild("{name}")', "if old then old:Destroy() end",
                     "local F = Instance.new(\"Model\")", f'F.Name = "{name}"', "F.Parent = R"]
        else:
            head += [f'local F = R:FindFirstChild("{name}")', f'if not F then error("draft {name} missing") end']
        body = "local D = {" + ",\n".join(rows) + "}"
        code = "\n".join(head) + "\n" + body + _BUILDER.replace("{lights}", "{" + light_rows + "}").replace(
            "{texts}", "{" + text_rows + "}").replace("{meshes}", "{" + mesh_rows + "}") + f'\nreturn "{MARK}" .. made'
        chunks.append(code)
    return chunks


def lighting_luau(preset: dict) -> str:
    """Set Lighting + our own Atmosphere/post effects (named StarBuild_*); other post effects are disabled, not deleted."""
    def c3(rgb):
        return f"Color3.fromRGB({int(rgb[0])}, {int(rgb[1])}, {int(rgb[2])})"
    a, cc, bl, sr = preset["Atmosphere"], preset["CC"], preset["Bloom"], preset["SunRays"]
    return f"""local L = game:GetService("Lighting")
pcall(function() L.Technology = Enum.Technology.Future end)
L.ClockTime = {_n(preset["ClockTime"])}
L.Brightness = {_n(preset["Brightness"])}
L.Ambient = {c3(preset["Ambient"])}
L.OutdoorAmbient = {c3(preset["OutdoorAmbient"])}
L.ShadowSoftness = {_n(preset["ShadowSoftness"])}
L.EnvironmentDiffuseScale = {_n(preset["EnvDiffuse"])}
L.EnvironmentSpecularScale = {_n(preset["EnvSpecular"])}
L.GlobalShadows = true
pcall(function() game:GetService("StarterGui").ShowDevelopmentGui = false end)
for _, c in ipairs(L:GetChildren()) do
	if (c:IsA("PostEffect") or c:IsA("Atmosphere")) and string.sub(c.Name, 1, 10) ~= "StarBuild_" then
		if c:IsA("PostEffect") then c.Enabled = false else
			local st = game:GetService("ServerStorage"):FindFirstChild("StarBuild_Stash") or Instance.new("Folder")
			st.Name = "StarBuild_Stash"; st.Parent = game:GetService("ServerStorage"); c.Parent = st
		end
	end
end
local function get(cls, name)
	local x = L:FindFirstChild(name)
	if not x then x = Instance.new(cls); x.Name = name; x.Parent = L end
	return x
end
local at = get("Atmosphere", "StarBuild_Atmosphere")
at.Density = {_n(a["Density"])}; at.Offset = {_n(a["Offset"])}; at.Color = {c3(a["Color"])}; at.Decay = {c3(a["Decay"])}
at.Glare = {_n(a["Glare"])}; at.Haze = {_n(a["Haze"])}
local cc = get("ColorCorrectionEffect", "StarBuild_CC")
cc.Enabled = true; cc.Brightness = {_n(cc["Brightness"])}; cc.Contrast = {_n(cc["Contrast"])}; cc.Saturation = {_n(cc["Saturation"])}; cc.TintColor = {c3(cc["Tint"])}
local bl = get("BloomEffect", "StarBuild_Bloom")
bl.Enabled = true; bl.Intensity = {_n(bl["Intensity"])}; bl.Size = {_n(bl["Size"])}; bl.Threshold = {_n(bl["Threshold"])}
local sr = get("SunRaysEffect", "StarBuild_SunRays")
sr.Enabled = true; sr.Intensity = {_n(sr["Intensity"])}; sr.Spread = {_n(sr["Spread"])}
return "{MARK}lighting"
"""


def remove_luau(name: str) -> str:
    name = safe_name(name)
    return f"""local R = workspace:FindFirstChild("{ROOT}")
local m = R and R:FindFirstChild("{name}")
if m then m:Destroy() end
pcall(function() game:GetService("StarterGui").ShowDevelopmentGui = true end)
return "{MARK}removed"
"""


LOCK_ATTR = "StarStudioLock"
_LIGHT_PROPS = ("ClockTime", "Brightness", "Ambient", "OutdoorAmbient", "ShadowSoftness", "EnvironmentDiffuseScale",
                "EnvironmentSpecularScale")


def lock_luau(owner: str, stale_s: int = 180) -> str:
    """Take the shared Studio capture lock (a Workspace attribute "<owner>|<os.time()>"), atomically in one call.
    Returns RB_DONE taken | RB_DONE busy <holder>. Lanes sharing brain 2's Studio use the same attribute."""
    owner = safe_name(owner)
    return f"""local v = workspace:GetAttribute("{LOCK_ATTR}")
if v then
	local who, t = string.match(v, "^(.-)|(%d+)$")
	if who and who ~= "{owner}" and t and os.time() - tonumber(t) < {int(stale_s)} then
		return "{MARK}busy " .. who
	end
end
workspace:SetAttribute("{LOCK_ATTR}", "{owner}|" .. os.time())
return "{MARK}taken"
"""


def unlock_luau(owner: str) -> str:
    owner = safe_name(owner)
    return f"""local v = workspace:GetAttribute("{LOCK_ATTR}")
if v and string.sub(v, 1, {len(owner) + 1}) == "{owner}|" then workspace:SetAttribute("{LOCK_ATTR}", nil) end
return "{MARK}unlocked"
"""


def save_lighting_luau() -> str:
    """Snapshot Lighting (properties, Atmosphere, enabled post effects) into ServerStorage/StarBuild_LightSave."""
    props = ", ".join(f'"{p}"' for p in _LIGHT_PROPS)
    return f"""local L = game:GetService("Lighting")
local SS = game:GetService("ServerStorage")
local old = SS:FindFirstChild("StarBuild_LightSave")
if old then old:Destroy() end
local f = Instance.new("Folder")
f.Name = "StarBuild_LightSave"
for _, p in ipairs({{{props}}}) do f:SetAttribute(p, L[p]) end
for _, c in ipairs(L:GetChildren()) do
	if c:IsA("PostEffect") then f:SetAttribute("fx_" .. c.Name, c.Enabled) end
end
f.Parent = SS
return "{MARK}saved"
"""


def restore_lighting_luau() -> str:
    props = ", ".join(f'"{p}"' for p in _LIGHT_PROPS)
    return f"""local L = game:GetService("Lighting")
local SS = game:GetService("ServerStorage")
local f = SS:FindFirstChild("StarBuild_LightSave")
if not f then return "{MARK}nothing" end
for _, p in ipairs({{{props}}}) do local v = f:GetAttribute(p); if v ~= nil then L[p] = v end end
for _, c in ipairs(L:GetChildren()) do
	if string.sub(c.Name, 1, 10) == "StarBuild_" then c:Destroy()
	elseif c:IsA("PostEffect") then local v = f:GetAttribute("fx_" .. c.Name); if v ~= nil then c.Enabled = v end end
end
local st = SS:FindFirstChild("StarBuild_Stash")
if st then for _, c in ipairs(st:GetChildren()) do c.Parent = L end; st:Destroy() end
f:Destroy()
pcall(function() game:GetService("StarterGui").ShowDevelopmentGui = true end)
return "{MARK}restored"
"""
