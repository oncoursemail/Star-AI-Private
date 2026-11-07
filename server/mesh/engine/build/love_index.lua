-- love_api.lua (love2d-community/love-api, version of LOVE 11.x) -> compact JSON on stdout.
-- usage: lua5.4 love_index.lua /path/to/love-api-master > love-index.json
-- Keeps names, argument names/types, return types and enum members; the wiki descriptions are dropped.
local dir = arg[1] or "."
package.path = dir .. "/?.lua;" .. dir .. "/?/init.lua;" .. package.path
local api = require("love_api")

local BS = string.char(92)
local function esc(s) return '"' .. tostring(s):gsub('[%c"' .. BS .. BS .. ']', function(c)
  return BS .. string.format("u%04x", c:byte()) end) .. '"' end
local function enc(v)
  local t = type(v)
  if t == "table" then
    if #v > 0 or next(v) == nil then
      local o = {}
      for _, x in ipairs(v) do o[#o + 1] = enc(x) end
      return "[" .. table.concat(o, ",") .. "]"
    end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys)
    local o = {}
    for _, k in ipairs(keys) do o[#o + 1] = esc(k) .. ":" .. enc(v[k]) end
    return "{" .. table.concat(o, ",") .. "}"
  elseif t == "string" then return esc(v)
  elseif t == "number" or t == "boolean" then return tostring(v)
  end
  return "null"
end

local function func(f)
  local vs = {}
  for _, v in ipairs(f.variants or {}) do
    local a, r = {}, {}
    for _, x in ipairs(v.arguments or {}) do a[#a + 1] = x.name .. ":" .. x.type .. (x.default and ("=" .. tostring(x.default)) or "") end
    for _, x in ipairs(v.returns or {}) do r[#r + 1] = x.type end
    vs[#vs + 1] = {a = a, r = r}
  end
  return {n = f.name, v = vs}
end

local out = {version = api.version, functions = {}, callbacks = {}, types = {}, enums = {}, modules = {}}
for _, f in ipairs(api.functions or {}) do out.functions[#out.functions + 1] = func(f) end
for _, f in ipairs(api.callbacks or {}) do out.callbacks[#out.callbacks + 1] = func(f) end
for _, m in ipairs(api.modules or {}) do
  local mo = {name = m.name, functions = {}, types = {}, enums = {}}
  for _, f in ipairs(m.functions or {}) do mo.functions[#mo.functions + 1] = func(f) end
  for _, t in ipairs(m.types or {}) do
    local to = {name = t.name, supertypes = t.supertypes or {}, functions = {}}
    for _, f in ipairs(t.functions or {}) do to.functions[#to.functions + 1] = func(f) end
    mo.types[#mo.types + 1] = to
  end
  for _, e in ipairs(m.enums or {}) do
    local eo = {name = e.name, constants = {}}
    for _, c in ipairs(e.constants or {}) do eo.constants[#eo.constants + 1] = c.name end
    mo.enums[#mo.enums + 1] = eo
  end
  out.modules[#out.modules + 1] = mo
end
io.write(enc(out), "\n")
