--!strict
-- Original, bounded, portable XPBD distance-constraint kernel. NOT a drop-in
-- SmartBone replacement: no Bone binding, angular limits, CCD or self-collision.
-- Numeric structure-of-arrays: the inner solve loop creates no vector tables.
local StarSpring = {}
export type Point = { x: number, y: number, z: number, inverseMass: number }
export type Link = { a: number, b: number, rest: number, compliance: number }
export type Sphere = { x: number, y: number, z: number, radius: number }
export type Options = { h: number, iterations: number, damping: number }
export type State = {
    count: number, h: number, iterations: number, damping: number,
    x: {number}, y: {number}, z: {number},
    oldX: {number}, oldY: {number}, oldZ: {number},
    vx: {number}, vy: {number}, vz: {number}, w: {number},
    links: {Link}, lambda: {number},
}
local function finite(n: number): boolean
    return type(n) == "number" and n == n and math.abs(n) < math.huge
end
local function bounded(n: number, limit: number): boolean
    return finite(n) and math.abs(n) <= limit
end
local function dense(t: any, maximum: number): number
    assert(type(t) == "table", "expected array")
    local n = #t
    assert(n <= maximum, "array exceeds budget")
    local count = 0
    for k in pairs(t) do
        assert(type(k) == "number" and k % 1 == 0 and k >= 1 and k <= n, "array must be dense")
        count += 1
    end
    assert(count == n, "array must be dense")
    return n
end
function StarSpring.new(points: {Point}, links: {Link}, opts: Options): State
    local n = dense(points, 256)
    assert(n >= 2, "need at least two points")
    dense(links, 1024)
    assert(finite(opts.h) and opts.h >= 1/240 and opts.h <= 1/15, "invalid fixed step")
    assert(finite(opts.iterations) and opts.iterations % 1 == 0 and opts.iterations >= 1 and opts.iterations <= 32, "invalid iteration budget")
    assert(finite(opts.damping) and opts.damping >= 0 and opts.damping <= 100, "invalid damping")
    local s: State = {
        count = n, h = opts.h, iterations = opts.iterations, damping = opts.damping,
        x = {}, y = {}, z = {}, oldX = {}, oldY = {}, oldZ = {},
        vx = {}, vy = {}, vz = {}, w = {}, links = {}, lambda = {},
    }
    for i, p in ipairs(points) do
        assert(bounded(p.x, 1e6) and bounded(p.y, 1e6) and bounded(p.z, 1e6), "invalid point")
        assert(finite(p.inverseMass) and p.inverseMass >= 0 and p.inverseMass <= 1000, "invalid inverse mass")
        s.x[i], s.y[i], s.z[i] = p.x, p.y, p.z
        s.oldX[i], s.oldY[i], s.oldZ[i] = p.x, p.y, p.z
        s.vx[i], s.vy[i], s.vz[i], s.w[i] = 0, 0, 0, p.inverseMass
    end
    for i, c in ipairs(links) do
        assert(finite(c.a) and finite(c.b) and c.a % 1 == 0 and c.b % 1 == 0 and c.a >= 1 and c.a <= n and c.b >= 1 and c.b <= n and c.a ~= c.b, "invalid link endpoints")
        assert(finite(c.rest) and c.rest > 1e-8 and c.rest <= 1e4, "invalid rest length")
        assert(finite(c.compliance) and c.compliance >= 0 and c.compliance <= 1, "invalid compliance")
        s.links[i] = { a = c.a, b = c.b, rest = c.rest, compliance = c.compliance }
        s.lambda[i] = 0
    end
    return s
end
function StarSpring.setPin(s: State, i: number, x: number, y: number, z: number)
    assert(finite(i) and i % 1 == 0 and i >= 1 and i <= s.count and s.w[i] == 0, "not a pinned point")
    assert(bounded(x, 1e6) and bounded(y, 1e6) and bounded(z, 1e6), "invalid pin position")
    s.x[i], s.y[i], s.z[i] = x, y, z
    s.oldX[i], s.oldY[i], s.oldZ[i] = x, y, z
    s.vx[i], s.vy[i], s.vz[i] = 0, 0, 0
end
function StarSpring.translate(s: State, dx: number, dy: number, dz: number)
    assert(bounded(dx, 1e6) and bounded(dy, 1e6) and bounded(dz, 1e6), "invalid translation")
    -- Explicit teleport policy: translate the entire cosmetic state, clear velocity.
    -- Validate all destinations BEFORE mutating any of them.
    for i = 1, s.count do
        assert(bounded(s.x[i] + dx, 1e6) and bounded(s.y[i] + dy, 1e6) and bounded(s.z[i] + dz, 1e6), "translation exceeds range")
    end
    for i = 1, s.count do
        s.x[i] += dx; s.y[i] += dy; s.z[i] += dz
        s.oldX[i], s.oldY[i], s.oldZ[i] = s.x[i], s.y[i], s.z[i]
        s.vx[i], s.vy[i], s.vz[i] = 0, 0, 0
    end
    table.clear(s.lambda)
    for i = 1, #s.links do s.lambda[i] = 0 end
end
function StarSpring.step(s: State, ax: number, ay: number, az: number, spheres: {Sphere})
    assert(bounded(ax, 1e4) and bounded(ay, 1e4) and bounded(az, 1e4), "invalid acceleration")
    dense(spheres, 32)
    -- Validate the complete collider list before integration changes state.
    for _, c in ipairs(spheres) do
        assert(bounded(c.x, 1e6) and bounded(c.y, 1e6) and bounded(c.z, 1e6) and finite(c.radius) and c.radius > 0 and c.radius <= 1e4, "invalid collider")
    end
    local h = s.h
    local decay = math.exp(-s.damping * h) -- velocity damping, not a Rayleigh model
    for i = 1, s.count do
        s.oldX[i], s.oldY[i], s.oldZ[i] = s.x[i], s.y[i], s.z[i]
        if s.w[i] > 0 then
            s.vx[i] = s.vx[i] * decay + ax * h
            s.vy[i] = s.vy[i] * decay + ay * h
            s.vz[i] = s.vz[i] * decay + az * h
            s.x[i] += s.vx[i] * h; s.y[i] += s.vy[i] * h; s.z[i] += s.vz[i] * h
        end
    end
    for i = 1, #s.links do s.lambda[i] = 0 end -- reset per substep, NOT per iteration
    for _ = 1, s.iterations do
        for i, c in ipairs(s.links) do
            local a, b = c.a, c.b
            local w = s.w[a] + s.w[b]
            if w > 0 then
                local dx, dy, dz = s.x[a] - s.x[b], s.y[a] - s.y[b], s.z[a] - s.z[b]
                local length = math.sqrt(dx*dx + dy*dy + dz*dz)
                -- Distance gradient is undefined at coincidence. Deterministic
                -- fallback axis repairs separation but is not physically unique.
                local nx, ny, nz = 1, 0, 0
                if length > 1e-10 then nx, ny, nz = dx/length, dy/length, dz/length end
                local alpha = c.compliance / (h*h)
                local dl = (-(length - c.rest) - alpha*s.lambda[i]) / (w + alpha)
                s.lambda[i] += dl
                local da, db = s.w[a]*dl, s.w[b]*dl
                s.x[a] += nx*da; s.y[a] += ny*da; s.z[a] += nz*da
                s.x[b] -= nx*db; s.y[b] -= ny*db; s.z[b] -= nz*db
            end
        end
        -- Discrete, static, frictionless point/sphere projection. No CCD; no
        -- segment thickness; incompatible contacts/links may retain residual.
        for _, c in ipairs(spheres) do
            for i = 1, s.count do
                if s.w[i] > 0 then
                    local dx, dy, dz = s.x[i]-c.x, s.y[i]-c.y, s.z[i]-c.z
                    local length = math.sqrt(dx*dx + dy*dy + dz*dz)
                    if length < c.radius then
                        if length > 1e-10 then
                            local k = c.radius / length
                            s.x[i], s.y[i], s.z[i] = c.x + dx*k, c.y + dy*k, c.z + dz*k
                        else
                            s.x[i], s.y[i], s.z[i] = c.x + c.radius, c.y, c.z
                        end
                    end
                end
            end
        end
    end
    for i = 1, s.count do
        s.vx[i], s.vy[i], s.vz[i] = (s.x[i]-s.oldX[i])/h, (s.y[i]-s.oldY[i])/h, (s.z[i]-s.oldZ[i])/h
        assert(bounded(s.x[i], 1e6) and bounded(s.y[i], 1e6) and bounded(s.z[i], 1e6), "solver exceeded range; discard state")
    end
end
function StarSpring.residual(s: State): number
    local peak = 0
    for _, c in ipairs(s.links) do
        local dx, dy, dz = s.x[c.a]-s.x[c.b], s.y[c.a]-s.y[c.b], s.z[c.a]-s.z[c.b]
        peak = math.max(peak, math.abs(math.sqrt(dx*dx + dy*dy + dz*dz) - c.rest))
    end
    return peak
end
return StarSpring
