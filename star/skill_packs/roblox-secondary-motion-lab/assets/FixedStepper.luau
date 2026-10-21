--!strict
-- Pure scheduler: no RunService connection, clocks, Instance writes or silent debt.
local FixedStepper = {}
export type State = { h: number, cap: number, accumulator: number, dropped: number }
export type Tick = { steps: number, alpha: number, dropped: number }
local function finite(n: number): boolean
    return type(n) == "number" and n == n and math.abs(n) < math.huge
end
function FixedStepper.new(h: number, cap: number): State
    assert(finite(h) and h >= 1 / 240 and h <= 1 / 15, "step must be 1/240..1/15 seconds")
    assert(finite(cap) and cap % 1 == 0 and cap >= 1 and cap <= 16, "cap must be 1..16")
    return { h = h, cap = cap, accumulator = 0, dropped = 0 }
end
function FixedStepper.advance(s: State, dt: number): Tick
    assert(finite(dt) and dt >= 0 and dt <= 60, "dt must be finite, 0..60 seconds")
    -- Cosmetic policy: preserve a fractional step, explicitly discard whole overdue
    -- steps above the per-frame cap. This is not a gameplay/network clock.
    local total = s.accumulator + dt
    local whole = math.floor(total / s.h)
    local steps = math.min(whole, s.cap)
    local dropped = (whole - steps) * s.h
    s.accumulator = total - whole * s.h
    s.dropped += dropped
    return { steps = steps, alpha = s.accumulator / s.h, dropped = dropped }
end
function FixedStepper.reset(s: State): number
    local discarded = s.accumulator
    s.accumulator = 0
    s.dropped += discarded
    return discarded
end
return FixedStepper
