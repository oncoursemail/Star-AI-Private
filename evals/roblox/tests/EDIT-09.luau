local ret, env = load_answer()
local P = ret
local function near(a, b) return math.abs(a - b) < 1e-6 end
local p = P.new({ x = 0, y = 0, z = 0 }, { x = 10, y = 0, z = 0 })
p:step(0.5)
check("gravity is scaled by dt", near(p.velocity.y, -30))
check("position moves by velocity * dt", near(p.position.x, 5) and near(p.position.y, -15))
local a = P.new({ x = 0, y = 0, z = 0 }, { x = 0, y = 0, z = 0 })
local b = P.new({ x = 0, y = 0, z = 0 }, { x = 0, y = 0, z = 0 })
for _ = 1, 10 do a:step(0.1) end
for _ = 1, 100 do b:step(0.01) end
check("the fall speed does not depend on the step size", near(a.velocity.y, b.velocity.y) and near(a.velocity.y, -60))
local far = P.new({ x = 0, y = 0, z = 0 }, { x = 100, y = 0, z = 0 })
far.velocity.y = 0
local steps, alive = 0, true
P.GRAVITY = 0
while alive and steps < 100 do alive = far:step(1); steps += 1 end
check("step returns false after MAX_RANGE", alive == false and steps == 4)
local x = far.position.x
check("a dead ball does not move", far:step(1) == false and far.position.x == x)
P.GRAVITY = -60
local t = P.new({ x = 0, y = 0, z = 0 }, { x = 50, y = 0, z = 0 }):trace(100, 0.5)
check("trace stops at max range", #t > 0 and #t < 200)
