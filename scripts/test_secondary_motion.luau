--!strict
-- Portable numerical tests, NOT Roblox native performance or visual acceptance.
local X = require("../star/skill_packs/roblox-secondary-motion-lab/assets/StarSpringXPBD")
local F = require("../star/skill_packs/roblox-secondary-motion-lab/assets/FixedStepper")
local passed, failed = 0, 0
local function test(name: string, run: () -> ())
    local ok, detail = pcall(run)
    if ok then passed += 1; print("PASS", name)
    else failed += 1; print("FAIL", name, detail) end
end
local function close(a: number, b: number, tolerance: number?)
    assert(math.abs(a-b) <= (tolerance or 1e-8), `expected {b}, got {a}`)
end
local function refuses(run: () -> ()) assert(not pcall(run), "invalid input accepted") end
local function pair(compliance: number?, iterations: number?, bothFree: boolean?)
    return X.new({{x=0,y=0,z=0,inverseMass=if bothFree then 1 else 0}, {x=2,y=0,z=0,inverseMass=1}},
        {{a=1,b=2,rest=1,compliance=compliance or 0}}, {h=1/64,iterations=iterations or 8,damping=2})
end

test("rigid distance repairs stretch", function()
    local s=pair(); X.step(s,0,0,0,{}); close(s.x[1],0); close(s.x[2],1); close(X.residual(s),0)
end)
test("pins ignore external acceleration", function()
    local s=pair(); X.step(s,30,-200,5,{}); close(s.x[1],0); close(s.y[1],0); close(s.z[1],0)
end)
test("compliance matches one-constraint analytical update", function()
    local s=pair(0.0001,1); X.step(s,0,0,0,{}); close(s.x[2],2-1/(1+0.0001/(s.h*s.h)))
end)
test("lambda persists across iterations", function()
    local a,b=pair(0.0001,1),pair(0.0001,32); X.step(a,0,0,0,{}); X.step(b,0,0,0,{}); close(a.x[2],b.x[2])
end)
test("free pair preserves center of mass", function()
    local s=pair(0,8,true); X.step(s,0,0,0,{}); close((s.x[1]+s.x[2])/2,1); close(X.residual(s),0)
end)
test("inverse masses weight corrections", function()
    local s=pair(0,1,true); s.w[1]=3; X.step(s,0,0,0,{}); close(s.x[1],0.75); close(s.x[2],1.75)
end)
test("coincident endpoints separate without NaN", function()
    local s=pair(); s.x[2]=0; X.step(s,0,0,0,{}); close(math.abs(s.x[2]),1)
end)
test("all-pinned constraint remains finite and reports residual", function()
    local s=pair(); s.w[2]=0; X.step(s,0,-200,0,{}); close(s.x[2],2); close(X.residual(s),1)
end)
test("pin update is explicit", function()
    local s=pair(); X.setPin(s,1,1,2,3); close(s.x[1],1); close(s.y[1],2); close(s.z[1],3)
end)
test("cannot repin dynamic point implicitly", function() refuses(function() X.setPin(pair(),2,0,0,0) end) end)
test("teleport clears momentum and preserves shape", function()
    local s=pair(); X.step(s,0,0,0,{}); local residual=X.residual(s); X.translate(s,10,20,30)
    close(s.x[1],10); close(s.y[2],20); close(s.vx[2],0); close(X.residual(s),residual)
end)
test("teleport validates every destination before mutation", function()
    local s=pair(); refuses(function() X.translate(s,1e6,0,0) end); close(s.x[1],0); close(s.x[2],2)
end)
test("static sphere excludes a dynamic point", function()
    local s=pair(); s.links={}; X.step(s,0,0,0,{{x=2,y=0,z=0,radius=0.5}}); close(s.x[2],2.5)
end)
test("colliders do not relocate a pin", function()
    local s=pair(); X.step(s,0,0,0,{{x=0,y=0,z=0,radius=0.5}}); close(s.x[1],0)
end)
test("bad collider rejected before integrating", function()
    local s=pair(); refuses(function() X.step(s,0,-200,0,{{x=0,y=0,z=0,radius=0/0}}) end); close(s.x[2],2); close(s.y[2],0)
end)
test("NaN and infinite acceleration refused", function()
    refuses(function() X.step(pair(),0/0,0,0,{}) end); refuses(function() X.step(pair(),math.huge,0,0,{}) end)
end)
test("constructor copies link definitions", function()
    local p={{x=0,y=0,z=0,inverseMass=0},{x=2,y=0,z=0,inverseMass=1}}
    local links={{a=1,b=2,rest=1,compliance=0}}; local s=X.new(p,links,{h=1/64,iterations=2,damping=0})
    p[2].x=99; links[1].rest=20; X.step(s,0,0,0,{}); close(s.x[2],1)
end)
test("sparse collider arrays refused", function()
    refuses(function() X.step(pair(),0,0,0,{[2]={x=0,y=0,z=0,radius=1}}) end)
end)
test("invalid rest and endpoints refused", function()
    for _, link in ipairs({{a=1,b=1,rest=1,compliance=0},{a=1,b=3,rest=1,compliance=0},{a=1,b=2,rest=0,compliance=0}}) do
        refuses(function() X.new({{x=0,y=0,z=0,inverseMass=0},{x=1,y=0,z=0,inverseMass=1}}, {link}, {h=1/64,iterations=2,damping=0}) end)
    end
end)
test("bounded long-run chain remains finite", function()
    local p, links = {}, {}
    for i=1,12 do
        p[i]={x=i-1,y=0,z=0,inverseMass=if i==1 then 0 else 1}
        if i>1 then links[i-1]={a=i-1,b=i,rest=1,compliance=0.00001} end
    end
    local s=X.new(p,links,{h=1/120,iterations=16,damping=4})
    for _=1,1200 do X.step(s,0,-20,0,{}) end
    close(s.x[1],0); assert(X.residual(s)<0.02, "chain residual grew")
end)
test("fixed step keeps fractional time", function()
    local s=F.new(1/64,4); local a=F.advance(s,1/128); assert(a.steps==0); close(a.alpha,0.5)
    local b=F.advance(s,1/128); assert(b.steps==1); close(b.alpha,0)
end)
test("fixed step accounts for discarded debt", function()
    local s=F.new(1/64,4); local a=F.advance(s,10.5/64); assert(a.steps==4)
    close(a.dropped,6/64); close(a.alpha,0.5); close(s.dropped,6/64)
end)
test("equal accepted timeline yields equal substeps", function()
    local a,b=F.new(1/64,4),F.new(1/64,4); local countA,countB=0,0
    for _=1,64 do countA+=F.advance(a,1/64).steps end
    for _=1,32 do countB+=F.advance(b,1/32).steps end
    assert(countA==64 and countB==64)
end)
test("stepper rejects invalid time and budget", function()
    for _, dt in ipairs({-1,0/0,math.huge,61}) do refuses(function() F.advance(F.new(1/64,4),dt) end) end
    refuses(function() F.new(0,4) end); refuses(function() F.new(1/64,0) end)
end)
test("stepper reset accounts for fractional discard", function()
    local s=F.new(1/64,4); F.advance(s,1/128); close(F.reset(s),1/128); close(s.accumulator,0); close(s.dropped,1/128)
end)
print(`RESULT passed={passed} failed={failed} environment=portable_luau native_studio_tested=false`)
assert(failed==0, `{failed} portable test(s) failed`)
