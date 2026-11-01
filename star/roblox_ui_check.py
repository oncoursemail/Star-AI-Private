"""Measured checks for Roblox game UI, run in a real Studio playtest (STAR Test Place through the guarded session).

Any UI script (STAR's or anyone's) is installed as a LocalScript next to a lab LocalScript. The lab waits for the
UI, then simulates three screens by moving the UI's ScreenGui contents into a device frame of exact size
(desktop = the whole 1452x795 viewport, tablet 1024x768, phone 844x390; Roblox's 58 px top bar is kept unless the
UI opts out of the inset) and measures with Roblox's own layout engine (AbsolutePosition/AbsoluteSize, TextFits):

  offscreen       a visible element sticks out of the screen (not inside a clipping/scrolling container)
  text_cut        a text element whose text does not fit (TextFits false)
  small_text      rendered text below 10 px (phone/tablet) or 11 px (desktop)
  small_target    a button smaller than 32 px on a touch screen (phone/tablet)
  button_overlap  two separate buttons overlapping by more than 30 % of the smaller one
  text_overlap    two separate texts overlapping by more than 30 % of the smaller one
  low_contrast    text vs. its real background (or outline) below 3:1
  covered_text    a text whose centre is drawn under an opaque frame (ZIndex / order mistake)
  topbar_clash    an interactive element under Roblox's top-bar buttons when the UI ignores the inset
  empty           nothing visible at all

Each device prints one marked JSON line; the runner captures a screenshot per device and crops the device area.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

MARK = "[StarUiLab]"
DEVICES = [("desktop", 0, 0), ("tablet", 1024, 768), ("phone", 844, 390)]  # 0 = whole viewport
ISSUES = ["offscreen", "text_cut", "small_text", "small_target", "button_overlap", "text_overlap", "low_contrast",
          "covered_text", "topbar_clash", "empty"]
WEIGHTS = {"offscreen": 2, "text_cut": 1, "small_text": 1, "small_target": 1, "button_overlap": 3,
           "text_overlap": 2, "low_contrast": 2, "covered_text": 2, "topbar_clash": 2, "empty": 50}

LAB_CLIENT = r"""
local RUN = "__RUN__"
local SKIP = __SKIP__
local DEVICES = __DEVICES__
local Players = game:GetService("Players")
local HttpService = game:GetService("HttpService")
local player = Players.LocalPlayer
local pg = player:WaitForChild("PlayerGui")
local function say(s) print("[StarUiLab] " .. RUN .. " " .. s) end
for _, g in ipairs(game:GetService("StarterGui"):GetChildren()) do
	if g:IsA("ScreenGui") then
		SKIP[g.Name] = true
		local copy = pg:FindFirstChild(g.Name)
		if copy and copy:IsA("ScreenGui") then copy.Enabled = false end
	end
end
say("client-ready")
local cam = workspace.CurrentCamera
task.spawn(function()
	for _ = 1, 40 do
		cam.CameraType = Enum.CameraType.Scriptable
		cam.CFrame = CFrame.lookAt(Vector3.new(0, 18, 60), Vector3.new(0, 26, -80))
		task.wait(0.25)
	end
end)
task.wait(__SETTLE__)
for _, g in ipairs(game:GetService("StarterGui"):GetChildren()) do
	local copy = g:IsA("ScreenGui") and pg:FindFirstChild(g.Name)
	if copy and copy:IsA("ScreenGui") then copy.Enabled = false end
end
local sources = {}
for _, g in ipairs(pg:GetChildren()) do
	if g:IsA("ScreenGui") and g.Enabled and not SKIP[g.Name] and string.sub(g.Name, 1, 12) ~= "StarUiVfxLab" then
		table.insert(sources, g)
	end
end
local names = {}
for _, g in ipairs(sources) do table.insert(names, g.Name) end
say("sources " .. #sources .. " " .. table.concat(names, ","))
local masks = Instance.new("ScreenGui")
masks.Name = "StarUiVfxLab_Mask"
masks.IgnoreGuiInset = true
masks.ScreenInsets = Enum.ScreenInsets.None
masks.DisplayOrder = 1000
masks.Parent = pg
local function mask(name)
	local f = Instance.new("Frame")
	f.Name = name
	f.BackgroundColor3 = Color3.fromRGB(24, 24, 28)
	f.BorderSizePixel = 0
	f.Parent = masks
	return f
end
local mt, mb, ml, mr = mask("T"), mask("B"), mask("L"), mask("R")
local devices = {}
for _, src in ipairs(sources) do
	local host = Instance.new("ScreenGui")
	host.Name = "StarUiVfxLab_Host_" .. src.Name
	host.IgnoreGuiInset = true
	host.ScreenInsets = Enum.ScreenInsets.None
	host.ZIndexBehavior = src.ZIndexBehavior
	host.DisplayOrder = src.DisplayOrder
	host.ResetOnSpawn = false
	local device = Instance.new("Frame")
	device.Name = "Device"
	device.BackgroundTransparency = 1
	device.ClipsDescendants = true
	device.AnchorPoint = Vector2.new(0.5, 0.5)
	device.Position = UDim2.fromScale(0.5, 0.5)
	device.Size = UDim2.fromScale(1, 1)
	device.Parent = host
	local inset = Instance.new("Frame")
	inset.Name = "Inset"
	inset.BackgroundTransparency = 1
	local usesInset = (not src.IgnoreGuiInset) or src.ScreenInsets == Enum.ScreenInsets.CoreUISafeInsets
		or src.ScreenInsets == Enum.ScreenInsets.TopbarSafeInsets
	inset.Position = UDim2.fromOffset(0, usesInset and 58 or 0)
	inset.Size = UDim2.new(1, 0, 1, usesInset and -58 or 0)
	inset.Parent = device
	for _, child in ipairs(src:GetChildren()) do
		child.Parent = inset
	end
	host.Parent = pg
	table.insert(devices, { device = device, inset = inset, usesInset = usesInset, name = src.Name })
end

local function rectOf(o, origin)
	local p, s = o.AbsolutePosition - origin, o.AbsoluteSize
	return { p.X, p.Y, p.X + s.X, p.Y + s.Y }
end
local function inter(a, b)
	local w = math.min(a[3], b[3]) - math.max(a[1], b[1])
	local h = math.min(a[4], b[4]) - math.max(a[2], b[2])
	if w <= 0 or h <= 0 then return 0 end
	return w * h
end
local function area(a) return math.max(0, a[3] - a[1]) * math.max(0, a[4] - a[2]) end
local function lum(c)
	local function ch(v) return v <= 0.04045 and v / 12.92 or ((v + 0.055) / 1.055) ^ 2.4 end
	return 0.2126 * ch(c.R) + 0.7152 * ch(c.G) + 0.0722 * ch(c.B)
end
local function ratio(a, b)
	local x, y = lum(a), lum(b)
	if x < y then x, y = y, x end
	return (x + 0.05) / (y + 0.05)
end
local function isText(o) return o:IsA("TextLabel") or o:IsA("TextButton") or o:IsA("TextBox") end
local function hasInk(o)
	if isText(o) and o.TextTransparency < 0.9 and string.gsub(o.Text, "%s", "") ~= "" then return true end
	if (o:IsA("ImageLabel") or o:IsA("ImageButton")) and o.Image ~= "" and o.ImageTransparency < 0.9 then return true end
	return o.BackgroundTransparency < 0.9
end

local function measure(dev, W, H, deviceName)
	local origin = dev.device.AbsolutePosition
	local counts, examples, n = {}, {}, 0
	for _, k in ipairs({ "offscreen", "text_cut", "small_text", "small_target", "button_overlap", "text_overlap",
		"low_contrast", "covered_text", "topbar_clash", "empty" }) do counts[k] = 0 end
	local function flag(kind, o, extra)
		counts[kind] += 1
		examples[kind] = examples[kind] or {}
		if #examples[kind] < 4 then
			local name = string.gsub(o:GetFullName(), "^.-Inset%.", "")
			table.insert(examples[kind], string.sub(string.gsub(name .. (extra and (" " .. extra) or ""), '"', ""), 1, 120))
		end
	end
	local visible, texts, btns, opaque = {}, {}, {}, {}
	for _, o in ipairs(dev.inset:GetDescendants()) do
		if o:IsA("GuiObject") then
			local ok, clip, scale, a = o.Visible, nil, 1, o.Parent
			local walker = o
			while walker and walker ~= dev.inset do
				local parent = walker.Parent
				if parent and parent:IsA("GuiObject") and parent ~= dev.inset then
					if not parent.Visible then ok = false break end
					if (parent.ClipsDescendants or parent:IsA("ScrollingFrame")) and not clip then clip = parent end
				end
				for _, c in ipairs(walker:GetChildren()) do
					if c:IsA("UIScale") and walker ~= o then scale *= c.Scale end
				end
				if parent and parent:IsA("CanvasGroup") and parent.GroupTransparency > 0.9 then ok = false break end
				walker = parent
			end
			for _, c in ipairs(o:GetChildren()) do
				if c:IsA("UIScale") then scale *= c.Scale end
			end
			local r = rectOf(o, origin)
			if ok and area(r) > 0 and hasInk(o) then
				local vr = r
				if clip then
					local cr = rectOf(clip, origin)
					vr = { math.max(r[1], cr[1]), math.max(r[2], cr[2]), math.min(r[3], cr[3]), math.min(r[4], cr[4]) }
				end
				if area(vr) > 0 then
					n += 1
					local item = { o = o, r = vr, full = r, clip = clip, scale = scale }
					table.insert(visible, item)
					if not clip then
						local outside = area(r) - inter(r, { 0, 0, W, H })
						if outside > 0.1 * area(r) and (r[1] < -4 or r[2] < -4 or r[3] > W + 4 or r[4] > H + 4) then
							flag("offscreen", o)
						end
					end
					if isText(o) and o.TextTransparency < 0.9 and string.gsub(o.Text, "%s", "") ~= "" then
						table.insert(texts, item)
					end
					if o:IsA("GuiButton") and o.Active then table.insert(btns, item) end
					if o.BackgroundTransparency < 0.15 and not isText(o) then table.insert(opaque, item) end
				end
			end
		end
	end
	local touch = deviceName ~= "desktop"
	for _, t in ipairs(texts) do
		local o = t.o
		if not o.TextFits then flag("text_cut", o, "[" .. string.gsub(string.sub(o.Text, 1, 24), '"', "") .. "]") end
		local px = o.TextScaled and math.min(o.TextBounds.Y * t.scale, o.AbsoluteSize.Y) or o.TextSize * t.scale
		if o.TextScaled then
			for _, c in ipairs(o:GetChildren()) do
				if c:IsA("UITextSizeConstraint") then px = math.min(px, c.MaxTextSize * t.scale) end
			end
		end
		if px < (touch and 10 or 11) then flag("small_text", o, string.format("%.1fpx", px)) end
		local bg, walker = nil, o
		while walker and walker ~= dev.inset do
			if walker:IsA("GuiObject") and walker.BackgroundTransparency < 0.4 then bg = walker.BackgroundColor3 break end
			walker = walker.Parent
		end
		local best = bg and ratio(o.TextColor3, bg) or 1
		for _, c in ipairs(o:GetChildren()) do
			if c:IsA("UIStroke") and c.Transparency < 0.5 and c.ApplyStrokeMode == Enum.ApplyStrokeMode.Contextual then
				best = math.max(best, ratio(o.TextColor3, c.Color))
			end
		end
		if o.TextStrokeTransparency < 0.5 then best = math.max(best, ratio(o.TextColor3, o.TextStrokeColor3)) end
		if best < 3 then flag("low_contrast", o, string.format("%.1f", best)) end
		if dev.usesInset == false and o:IsA("GuiButton") then
			if t.r[2] < 58 and (t.r[1] < 140 or t.r[3] > W - 140) then flag("topbar_clash", o) end
		end
	end
	for _, b in ipairs(btns) do
		local w, h = b.full[3] - b.full[1], b.full[4] - b.full[2]  -- real size, even when scrolled half out of view
		if touch and math.min(w, h) < 32 then flag("small_target", b.o, string.format("%dx%d", w, h)) end
		if not dev.usesInset and b.r[2] < 58 and (b.r[1] < 140 or b.r[3] > W - 140) and not isText(b.o) then
			flag("topbar_clash", b.o)
		end
	end
	local function related(a, b) return a:IsDescendantOf(b) or b:IsDescendantOf(a) end
	for i = 1, #btns do
		for j = i + 1, #btns do
			local a, b = btns[i], btns[j]
			if not related(a.o, b.o) and inter(a.r, b.r) > 0.3 * math.min(area(a.r), area(b.r)) then
				flag("button_overlap", a.o, "x " .. b.o.Name)
			end
		end
	end
	local function inkRect(t)
		local o, r = t.o, t.r
		local tb = o.TextBounds * t.scale
		local w, h = math.min(tb.X, r[3] - r[1]), math.min(tb.Y, r[4] - r[2])
		local x = o.TextXAlignment == Enum.TextXAlignment.Center and r[1] + (r[3] - r[1] - w) / 2
			or o.TextXAlignment == Enum.TextXAlignment.Right and r[3] - w or r[1]
		local y = o.TextYAlignment == Enum.TextYAlignment.Center and r[2] + (r[4] - r[2] - h) / 2
			or o.TextYAlignment == Enum.TextYAlignment.Bottom and r[4] - h or r[2]
		return { x, y, x + w, y + h }
	end
	for i = 1, #texts do
		for j = i + 1, #texts do
			local a, b = texts[i], texts[j]
			if not related(a.o, b.o) then
				local ra, rb = inkRect(a), inkRect(b)
				if area(ra) > 0 and area(rb) > 0 and inter(ra, rb) > 0.3 * math.min(area(ra), area(rb)) then
					flag("text_overlap", a.o, "x " .. b.o.Name)
				end
			end
		end
	end
	-- covered text: an opaque non-ancestor frame drawn later/higher contains the text's centre
	local function above(f, t)
		local fa, ta = {}, {}
		local w = f
		while w do table.insert(fa, w) w = w.Parent end
		w = t
		local lca
		local index = {}
		for k, v in ipairs(fa) do index[v] = k end
		local child_t = t
		w = t
		while w and not index[w] do child_t = w w = w.Parent end
		lca = w
		if not lca then return false end
		local child_f = fa[index[lca] - 1]
		if not child_f or not child_t or child_f == lca or child_t == lca then return false end
		local zf = child_f:IsA("GuiObject") and child_f.ZIndex or 0
		local zt = child_t:IsA("GuiObject") and child_t.ZIndex or 0
		local global = false
		local sg = t:FindFirstAncestorWhichIsA("LayerCollector")
		if sg and sg:IsA("ScreenGui") and sg.ZIndexBehavior == Enum.ZIndexBehavior.Global then
			global = true
			zf, zt = f.ZIndex, t.ZIndex
		end
		if zf ~= zt then return zf > zt end
		if global then return false end
		local kids = lca:GetChildren()
		return (table.find(kids, child_f) or 0) > (table.find(kids, child_t) or 0)
	end
	for _, t in ipairs(texts) do
		local ir = inkRect(t)
		local cx, cy = (ir[1] + ir[3]) / 2, (ir[2] + ir[4]) / 2
		for _, f in ipairs(opaque) do
			if f.o ~= t.o and not related(f.o, t.o) and cx > f.r[1] and cx < f.r[3] and cy > f.r[2] and cy < f.r[4] then
				if above(f.o, t.o) then flag("covered_text", t.o, "under " .. f.o.Name) break end
			end
		end
	end
	return { elements = n, counts = counts, examples = examples }
end

local view = cam.ViewportSize
for _, d in ipairs(DEVICES) do
	local name, W, H = d[1], d[2], d[3]
	if W == 0 then W, H = view.X, view.Y end
	local x0, y0 = math.floor((view.X - W) / 2), math.floor((view.Y - H) / 2)
	for _, dev in ipairs(devices) do
		dev.device.Size = UDim2.fromOffset(W, H)
	end
	mt.Position, mt.Size = UDim2.fromOffset(0, 0), UDim2.fromOffset(view.X, y0)
	mb.Position, mb.Size = UDim2.fromOffset(0, y0 + H), UDim2.fromOffset(view.X, view.Y - y0 - H)
	ml.Position, ml.Size = UDim2.fromOffset(0, y0), UDim2.fromOffset(x0, H)
	mr.Position, mr.Size = UDim2.fromOffset(x0 + W, y0), UDim2.fromOffset(view.X - x0 - W, H)
	task.wait(1.6)
	local result = { device = name, w = W, h = H, x0 = x0, y0 = y0, vw = view.X, vh = view.Y, guis = #devices, per = {} }
	local total = { elements = 0, counts = {}, examples = {} }
	for _, dev in ipairs(devices) do
		local ok, m = pcall(measure, dev, W, H, name)
		if ok then
			total.elements += m.elements
			for k, v in pairs(m.counts) do total.counts[k] = (total.counts[k] or 0) + v end
			for k, v in pairs(m.examples) do total.examples[k] = v end
		else
			say("measure-error " .. tostring(m))
		end
	end
	if #devices == 0 then total.counts.empty = 1 end
	if total.elements == 0 then total.counts.empty = 1 end
	result.elements, result.counts, result.examples = total.elements, total.counts, total.examples
	say("measure " .. HttpService:JSONEncode(result))
	say("READY " .. name)
	task.wait(__HOLD__)
end
say("done")
"""


def lab_client(run: str, skip: list[str], *, settle: float = 7.0, hold: float = 3.5) -> str:
    skip_table = "{ " + ", ".join(f'["{re.sub(r"[^A-Za-z0-9_ ]", "", s)}"] = true' for s in skip) + " }"
    devices = "{ " + ", ".join(f'{{ "{n}", {w}, {h} }}' for n, w, h in DEVICES) + " }"
    return (LAB_CLIENT.replace("__RUN__", run).replace("__SKIP__", skip_table).replace("__DEVICES__", devices)
            .replace("__SETTLE__", f"{settle:g}").replace("__HOLD__", f"{hold:g}"))


def _lua_long(text: str) -> str:
    level = 1
    while ("]" + "=" * level + "]") in text:
        level += 1
    eq = "=" * level
    return f"[{eq}[\n{text}]{eq}]"


def install_luau(item_source: str, run: str, *, settle: float = 7.0) -> str:
    """Edit-DataModel Luau: install the item and lab LocalScripts in StarterPlayerScripts (nothing else is changed;
    the lab hides the place's own StarterGui screens on the client during play only)."""
    return f"""
local sps = game:GetService("StarterPlayer"):WaitForChild("StarterPlayerScripts")
local sg = game:GetService("StarterGui")
for _, holder in ipairs({{sps, sg}}) do
	for _, name in ipairs({{"StarUiVfx_Item", "StarUiVfx_Lab"}}) do
		local old = holder:FindFirstChild(name)
		if old then old:Destroy() end
	end
end
-- The UI script goes where UI LocalScripts usually live (StarterGui -> PlayerGui), the lab beside the player scripts.
local item = Instance.new("LocalScript")
item.Name = "StarUiVfx_Item"
item.Source = {_lua_long(item_source)}
item.Parent = sg
local lab = Instance.new("LocalScript")
lab.Name = "StarUiVfx_Lab"
lab.Source = {_lua_long(lab_client(run, ["Freecam"], settle=settle))}
lab.Parent = sps
return "{MARK}_INSTALL {run}"
"""


def remove_luau() -> str:
    return f"""
local sps = game:GetService("StarterPlayer"):WaitForChild("StarterPlayerScripts")
local removed = 0
for _, holder in ipairs({{sps, game:GetService("StarterGui")}}) do
	for _, name in ipairs({{"StarUiVfx_Item", "StarUiVfx_Lab"}}) do
		local old = holder:FindFirstChild(name)
		if old then old:Destroy() removed += 1 end
	end
end
return "{MARK}_REMOVE removed=" .. removed
"""


def parse_console(console: str, run: str) -> dict:
    """Measurements, device-ready markers and script errors for one run from the Studio console text."""
    out: dict[str, Any] = {"measures": {}, "ready": [], "errors": [], "sources": None}
    tag = f"{MARK} {run} "
    lines = console.splitlines()
    # Studio keeps only the last ~20k characters of output across runs: this run starts after the last lab line
    # of an earlier run (script errors of this run can come before its own client-ready line).
    mine = next((i for i, line in enumerate(lines) if tag + "client-ready" in line), None)
    if mine is not None:
        for i in range(mine - 1, -1, -1):
            if (MARK + " ") in lines[i] and tag not in lines[i]:
                lines = lines[i + 1:]
                break
    for line in lines:
        at = line.find(tag)
        if at >= 0:
            rest = line[at + len(tag):]
            if rest.startswith("measure "):
                try:
                    m = json.loads(rest[len("measure "):])
                    out["measures"][m["device"]] = m
                except (ValueError, KeyError):
                    pass
            elif rest.startswith("READY "):
                out["ready"].append(rest[6:].strip())
            elif rest.startswith("sources "):
                parts = rest.split()
                out["sources"] = int(parts[1]) if parts[1].isdigit() else None
                out["source_names"] = parts[2].split(",") if len(parts) > 2 else []
            elif rest.startswith("measure-error"):
                out["errors"].append(rest[:300])
        elif "StarUiVfx_Item" in line and not line.strip().startswith(MARK):
            out["errors"].append(line.strip()[:300])
    return out


def score(measures: dict) -> dict:
    """Weighted issue score per device and in total (lower is better)."""
    per = {}
    total = 0
    for name, m in measures.items():
        counts = m.get("counts", {})
        s = sum(WEIGHTS.get(k, 1) * min(int(v), 10) for k, v in counts.items())
        per[name] = s
        total += s
    missing = [d for d, _, _ in DEVICES if d not in measures]
    total += 50 * len(missing)
    return {"total": total, "per_device": per, "missing": missing}


def crop(jpeg: bytes, m: dict) -> bytes:
    """The device area of a viewport capture (the capture may be scaled relative to the viewport)."""
    from PIL import Image
    image = Image.open(io.BytesIO(jpeg)).convert("RGB")
    sx, sy = image.width / max(1, m.get("vw", image.width)), image.height / max(1, m.get("vh", image.height))
    box = (round(m["x0"] * sx), round(m["y0"] * sy), round((m["x0"] + m["w"]) * sx), round((m["y0"] + m["h"]) * sy))
    buffer = io.BytesIO()
    image.crop(box).save(buffer, "JPEG", quality=92)
    return buffer.getvalue()


class UiLab:
    """Install -> playtest -> per-device measure + capture -> stop -> remove, on an opened GuardedStudio."""

    def __init__(self, guarded, *, log=print, sleep=asyncio.sleep, clock=time.monotonic):
        self.guarded, self.log, self.sleep, self.clock = guarded, log, sleep, clock

    async def _luau(self, code: str) -> tuple[bool, str]:
        from .studio_loop import EDIT_MARK, _marked_json, result_failed, result_text
        result = await self.guarded.call_tool("execute_luau", {"studio_id": self.guarded.studio_id,
                                                               "datamodel_type": "Edit", "code": code})
        text = result_text(result)
        receipt = _marked_json(text, EDIT_MARK) or {}
        got = receipt.get("result")
        return (not result_failed(result) and receipt.get("ok") is True), (got if isinstance(got, str) else text)

    async def _call(self, name: str, **arguments):
        return await self.guarded.call_tool(name, {"studio_id": self.guarded.studio_id, **arguments})

    async def _console(self) -> str:
        from .studio_loop import result_text
        return result_text(await self._call("get_console_output"))

    async def remove(self) -> tuple[bool, str]:
        return await self._luau(remove_luau())

    async def run(self, source: str, out_dir: Path, *, label: str = "") -> dict:
        from .studio_loop import result_failed, result_text
        run = secrets.token_hex(4)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        report: dict[str, Any] = {"run": run, "label": label, "started": time.strftime("%H:%M:%SZ", time.gmtime())}
        ok, text = await self._luau(install_luau(source, run))
        report["install"] = {"ok": ok and f"{MARK}_INSTALL {run}" in text, "detail": text[:200]}
        if not report["install"]["ok"]:
            await self.remove()
            return report
        before = await self._console()  # the console keeps earlier runs: only read what this run adds
        started = await self._call("start_stop_play", is_start=True)
        report["play"] = not result_failed(started)
        if not report["play"]:
            report["play_detail"] = result_text(started)[:300]
            await self.remove()
            return report
        shots: dict[str, bytes] = {}
        parsed: dict[str, Any] = {}
        try:
            deadline = self.clock() + 75
            while self.clock() < deadline:
                await self.sleep(0.6)
                text = await self._console()
                parsed = parse_console(text[len(before):] if text.startswith(before) else text, run)
                for device in parsed["ready"]:
                    if device not in shots and device in parsed["measures"]:
                        shot = await self._call("screen_capture", capture_id=f"StarUi_{run}_{device}")
                        data = _image(shot)
                        if data:
                            shots[device] = crop(data, parsed["measures"][device])
                            (out_dir / f"{device}.jpg").write_bytes(shots[device])
                if len(shots) == len(DEVICES):
                    break
        finally:
            await self._call("start_stop_play", is_start=False)
            await self.sleep(1.0)
            report["remove"] = (await self.remove())[1][:120]
        report["measures"] = parsed.get("measures", {})
        report["errors"] = parsed.get("errors", [])[:12]
        report["sources"] = parsed.get("sources")
        report["source_names"] = parsed.get("source_names")
        report["score"] = score(report["measures"])
        report["shots"] = sorted(shots)
        (out_dir / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        return report


def _image(result) -> bytes | None:
    import base64
    for c in getattr(result, "content", []) or []:
        if getattr(c, "type", "") == "image":
            return base64.b64decode(c.data)
    return None
