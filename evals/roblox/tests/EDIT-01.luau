local ret, env = load_answer()
local A = ret
local p = {}
for _ = 1, 20 do A.fire(p) end
local s = A.get(p)
s.reserve = 5
check("reload with 5 left moves 5", A.reload(p) == 5)
check("magazine 5 and reserve 0 after that reload", s.magazine == 5 and s.reserve == 0)
check("reload with an empty reserve moves nothing", A.reload(p) == 0 and s.magazine == 5 and s.reserve == 0)
local q = {}
A.fire(q); A.fire(q); A.fire(q)
check("a normal reload still refills 3", A.reload(q) == 3 and A.get(q).magazine == 20 and A.get(q).reserve == 57)
check("reload with a full magazine moves nothing", A.reload(q) == 0)
A.addReserve(q, 500)
check("addReserve caps the reserve at 120", A.get(q).reserve == 120)
A.reset(q)
A.addReserve(q, 10)
check("addReserve below the cap adds normally", A.get(q).reserve == 70)
check("fire still works", A.fire(q) == true and A.get(q).magazine == 19)
