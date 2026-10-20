"""Hand-written seed tasks with their own harnesses: Unity C# logic with stand-in types, Unreal C++ logic with
stand-in types, Godot GDScript classes, Roblox Luau animation/VFX (pattern checks + the night-school Luau static
check at attempt time), shaders (glslang compile check + required names), design patterns."""
from __future__ import annotations

SEEDS: list[dict] = []


def seed(file, language, topic, prompt, reference, trivial, tests="", require=(), forbid=(), expect=None, run_s=10, category=None):
    SEEDS.append({"file": file, "language": language, "topic": topic, "prompt": prompt, "reference": reference, "trivial": trivial,
                  "tests": tests, "require": list(require), "forbid": list(forbid), "expect": expect, "run_s": run_s,
                  "category": category or "multi-" + file})


def _cs_harness(cases: str, n: int) -> str:
    return ("public static class Program {\n    static int passed = 0;\n    static void Check(string name, bool ok, string detail) {\n"
            "        if (ok) { passed++; System.Console.WriteLine(\"@@PASS \" + name); } else System.Console.WriteLine(\"@@FAIL \" + name + \": \" + detail);\n    }\n"
            "    public static void Main() {\n" + cases + f"\n        System.Console.WriteLine(\"@@DONE \" + passed + \"/{n}\");\n    }}\n}}\n")


# ---------------------------------------------------------------- Unity C# with stand-in types
UNITY_STANDINS = '''// Stand-ins for the UnityEngine types used here (the real engine is not available in the judge).
public struct Vector3 {
    public float x, y, z;
    public Vector3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
    public static Vector3 operator +(Vector3 a, Vector3 b) => new Vector3(a.x + b.x, a.y + b.y, a.z + b.z);
    public static Vector3 operator -(Vector3 a, Vector3 b) => new Vector3(a.x - b.x, a.y - b.y, a.z - b.z);
    public static Vector3 operator *(Vector3 a, float s) => new Vector3(a.x * s, a.y * s, a.z * s);
    public float magnitude => (float)System.Math.Sqrt(x * x + y * y + z * z);
    public Vector3 normalized { get { float m = magnitude; return m > 1e-6f ? new Vector3(x / m, y / m, z / m) : new Vector3(0, 0, 0); } }
    public static float Distance(Vector3 a, Vector3 b) => (a - b).magnitude;
    public static Vector3 zero => new Vector3(0, 0, 0);
}
public static class Mathf {
    public static float Clamp(float v, float lo, float hi) => v < lo ? lo : v > hi ? hi : v;
    public static float Clamp01(float v) => Clamp(v, 0f, 1f);
    public static float Lerp(float a, float b, float t) => a + (b - a) * Clamp01(t);
    public static float Abs(float v) => System.Math.Abs(v);
    public static float Max(float a, float b) => System.Math.Max(a, b);
    public static float Min(float a, float b) => System.Math.Min(a, b);
}
'''
seed("unity-csharp", "csharp", "health-component",
     "Unity C# gameplay logic (engine-independent, testable without UnityEngine). Write a `public class Health` with:\n"
     "- constructor `Health(float max)` (current starts at max);\n- `public float Current { get; }` and `public float Max { get; }`;\n"
     "- `public bool IsDead => Current <= 0f;`\n- `public void TakeDamage(float amount)`: ignores amounts <= 0, never goes below 0, and does nothing when already dead;\n"
     "- `public void Heal(float amount)`: ignores amounts <= 0, never exceeds Max, and does nothing when dead;\n"
     "- `public event System.Action<float> OnDamaged;` raised with the damage actually applied (after clamping) whenever TakeDamage changes Current.\n\n"
     "Do not reference UnityEngine (not available in the tests); plain C# only. Reply with exactly one fenced ```csharp block containing only the class.",
     '''public class Health {
    public float Current { get; private set; }
    public float Max { get; private set; }
    public bool IsDead => Current <= 0f;
    public event System.Action<float> OnDamaged;
    public Health(float max) { Max = max; Current = max; }
    public void TakeDamage(float amount) {
        if (amount <= 0f || IsDead) return;
        float applied = System.Math.Min(amount, Current);
        Current -= applied;
        OnDamaged?.Invoke(applied);
    }
    public void Heal(float amount) {
        if (amount <= 0f || IsDead) return;
        Current = System.Math.Min(Max, Current + amount);
    }
}
''',
     "public class Health {\n    public float Current { get; private set; }\n    public float Max { get; private set; }\n    public bool IsDead => Current <= 0f;\n    public event System.Action<float> OnDamaged;\n    public Health(float max) { Max = max; Current = max; }\n    public void TakeDamage(float amount) { Current -= amount; OnDamaged?.Invoke(amount); }\n    public void Heal(float amount) { Current += amount; }\n}\n",
     tests=UNITY_STANDINS + _cs_harness('''        var h = new Health(100f);
        float last = -1f; int events = 0;
        h.OnDamaged += d => { last = d; events++; };
        h.TakeDamage(30f);
        Check("damage", h.Current == 70f && last == 30f && events == 1, "current " + h.Current + " last " + last);
        h.TakeDamage(-5f);
        Check("negative_ignored", h.Current == 70f && events == 1, "current " + h.Current);
        h.Heal(50f);
        Check("heal_clamped", h.Current == 100f, "current " + h.Current);
        h.TakeDamage(250f);
        Check("clamped_to_zero", h.Current == 0f && h.IsDead && last == 100f, "current " + h.Current + " last " + last);
        h.Heal(10f);
        Check("dead_stays_dead", h.Current == 0f && h.IsDead, "current " + h.Current);
        h.TakeDamage(10f);
        Check("no_event_when_dead", events == 2, "events " + events);''', 6),
     require=[{"id": "event", "re": r"event\s+System\.Action<float>\s+OnDamaged|event\s+Action<float>\s+OnDamaged", "why": "declare the OnDamaged event"}],
     forbid=[{"id": "no_unityengine", "re": r"using\s+UnityEngine", "why": "UnityEngine is not available in the tests"}], expect=6)

seed("unity-csharp", "csharp", "move-towards-target",
     "Unity C# movement logic with stand-in types (a `Vector3` struct with +, -, * float, `magnitude`, `normalized`, `Vector3.Distance`, and `Mathf.Clamp/Lerp` are provided by the tests; "
     "do not declare them and do not use UnityEngine). Write `public static class Mover` with\n"
     "`public static Vector3 Step(Vector3 position, Vector3 target, float speed, float deltaTime)` that moves `position` toward `target` by at most `speed * deltaTime` "
     "and never overshoots (returns `target` when within reach), like Vector3.MoveTowards.\n\nReply with exactly one fenced ```csharp block containing only the class.",
     '''public static class Mover {
    public static Vector3 Step(Vector3 position, Vector3 target, float speed, float deltaTime) {
        Vector3 to = target - position;
        float dist = to.magnitude;
        float maxStep = speed * deltaTime;
        if (dist <= maxStep || dist < 1e-6f) return target;
        return position + to.normalized * maxStep;
    }
}
''',
     "public static class Mover {\n    public static Vector3 Step(Vector3 position, Vector3 target, float speed, float deltaTime) {\n        return position + (target - position) * (speed * deltaTime);\n    }\n}\n",
     tests=UNITY_STANDINS + _cs_harness('''        var p = Mover.Step(new Vector3(0, 0, 0), new Vector3(10, 0, 0), 5f, 0.5f);
        Check("partial", System.Math.Abs(p.x - 2.5f) < 1e-4 && p.y == 0 && p.z == 0, "x " + p.x);
        var q = Mover.Step(new Vector3(9, 0, 0), new Vector3(10, 0, 0), 5f, 1f);
        Check("no_overshoot", q.x == 10f, "x " + q.x);
        var r = Mover.Step(new Vector3(0, 0, 0), new Vector3(3, 4, 0), 1f, 1f);
        Check("diagonal", System.Math.Abs(r.x - 0.6f) < 1e-4 && System.Math.Abs(r.y - 0.8f) < 1e-4, "r " + r.x + "," + r.y);
        var s = Mover.Step(new Vector3(1, 1, 1), new Vector3(1, 1, 1), 3f, 0.1f);
        Check("already_there", s.x == 1f && s.y == 1f && s.z == 1f, "s " + s.x);''', 4),
     forbid=[{"id": "no_unityengine", "re": r"using\s+UnityEngine", "why": "UnityEngine is not available in the tests"},
             {"id": "no_standin_redeclared", "re": r"struct\s+Vector3|class\s+Mathf", "why": "the stand-in types are provided by the tests"}], expect=4)

seed("unity-csharp", "csharp", "animator-state-logic",
     "Unity Animator logic as plain C# (no UnityEngine). Write `public class LocomotionState` that decides the animation state name from parameters, the way an Animator "
     "controller's transitions would:\n- `public string Next(string current, float speed, bool grounded, bool jumpPressed)` returns: \"Jump\" when `jumpPressed && grounded`; "
     "otherwise \"Fall\" when `!grounded`; otherwise \"Run\" when `speed >= 4f`; \"Walk\" when `speed > 0.1f`; else \"Idle\".\n"
     "- `public bool Changed { get; }` is true after a call whose result differs from `current`.\n\nReply with exactly one fenced ```csharp block containing only the class.",
     '''public class LocomotionState {
    public bool Changed { get; private set; }
    public string Next(string current, float speed, bool grounded, bool jumpPressed) {
        string next;
        if (jumpPressed && grounded) next = "Jump";
        else if (!grounded) next = "Fall";
        else if (speed >= 4f) next = "Run";
        else if (speed > 0.1f) next = "Walk";
        else next = "Idle";
        Changed = next != current;
        return next;
    }
}
''',
     "public class LocomotionState {\n    public bool Changed { get; private set; }\n    public string Next(string current, float speed, bool grounded, bool jumpPressed) { Changed = false; return \"Idle\"; }\n}\n",
     tests=_cs_harness('''        var s = new LocomotionState();
        Check("idle", s.Next("Idle", 0f, true, false) == "Idle" && !s.Changed, "idle");
        Check("walk", s.Next("Idle", 1f, true, false) == "Walk" && s.Changed, "walk");
        Check("run", s.Next("Walk", 4f, true, false) == "Run", "run");
        Check("jump", s.Next("Run", 4f, true, true) == "Jump", "jump");
        Check("fall", s.Next("Jump", 4f, false, true) == "Fall", "fall");
        Check("fall_over_run", s.Next("Run", 9f, false, false) == "Fall", "fall over run");''', 6),
     forbid=[{"id": "no_unityengine", "re": r"using\s+UnityEngine", "why": "UnityEngine is not available in the tests"}], expect=6)

# ---------------------------------------------------------------- Unreal C++ with stand-in types
UNREAL_STANDINS = '''// Stand-ins for the Unreal types used here (the engine is not available in the judge).
#include <cmath>
#include <iostream>
#include <string>
#include <vector>
struct FVector {
    float X, Y, Z;
    FVector() : X(0), Y(0), Z(0) {}
    FVector(float x, float y, float z) : X(x), Y(y), Z(z) {}
    FVector operator+(const FVector& o) const { return FVector(X + o.X, Y + o.Y, Z + o.Z); }
    FVector operator-(const FVector& o) const { return FVector(X - o.X, Y - o.Y, Z - o.Z); }
    FVector operator*(float s) const { return FVector(X * s, Y * s, Z * s); }
    float Size() const { return std::sqrt(X * X + Y * Y + Z * Z); }
    FVector GetSafeNormal() const { float m = Size(); return m > 1e-6f ? FVector(X / m, Y / m, Z / m) : FVector(); }
    static float Dist(const FVector& a, const FVector& b) { return (a - b).Size(); }
};
namespace FMath {
    inline float Clamp(float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; }
    inline float Lerp(float a, float b, float t) { return a + (b - a) * t; }
    inline float Abs(float v) { return std::fabs(v); }
    inline float Max(float a, float b) { return a > b ? a : b; }
    inline float Min(float a, float b) { return a < b ? a : b; }
}
'''


def _cpp_harness(cases: str, n: int) -> str:
    return ("static int passed = 0;\nstatic void check(const std::string& name, bool ok, const std::string& detail) {\n"
            "    if (ok) { ++passed; std::cout << \"@@PASS \" << name << \"\\n\"; } else std::cout << \"@@FAIL \" << name << \": \" << detail << \"\\n\";\n}\n"
            "int main() {\n" + cases + f"\n    std::cout << \"@@DONE \" << passed << \"/{n}\" << std::endl;\n    return 0;\n}}\n")


seed("unreal-cpp", "cpp", "finterp-to",
     "Unreal C++ gameplay math (engine-independent; the tests provide stand-ins `FVector` and `FMath::Clamp/Lerp/Abs/Max/Min`, do not declare them or include engine headers). "
     "Write a free function `float FInterpTo(float Current, float Target, float DeltaTime, float InterpSpeed)` with Unreal's semantics: if `InterpSpeed <= 0` return `Target`; "
     "compute `Dist = Target - Current`; if `Dist * Dist < 1e-8f` return `Target`; otherwise move by `Dist * FMath::Clamp(DeltaTime * InterpSpeed, 0.f, 1.f)` and return the new value.\n\n"
     "Reply with exactly one fenced ```cpp block containing only the function.",
     "float FInterpTo(float Current, float Target, float DeltaTime, float InterpSpeed) {\n    if (InterpSpeed <= 0.f) return Target;\n    const float Dist = Target - Current;\n"
     "    if (Dist * Dist < 1e-8f) return Target;\n    const float DeltaMove = Dist * FMath::Clamp(DeltaTime * InterpSpeed, 0.f, 1.f);\n    return Current + DeltaMove;\n}\n",
     "float FInterpTo(float Current, float Target, float DeltaTime, float InterpSpeed) {\n    return Current + (Target - Current) * DeltaTime * InterpSpeed;\n}\n",
     tests=_cpp_harness('''    check("half", std::fabs(FInterpTo(0.f, 10.f, 0.1f, 5.f) - 5.f) < 1e-4f, std::to_string(FInterpTo(0.f, 10.f, 0.1f, 5.f)));
    check("clamped", FInterpTo(0.f, 10.f, 1.f, 5.f) == 10.f, std::to_string(FInterpTo(0.f, 10.f, 1.f, 5.f)));
    check("speed_zero", FInterpTo(3.f, 10.f, 0.1f, 0.f) == 10.f, "speed zero");
    check("at_target", FInterpTo(10.f, 10.f, 0.1f, 5.f) == 10.f, "at target");
    check("negative", std::fabs(FInterpTo(10.f, 0.f, 0.5f, 1.f) - 5.f) < 1e-4f, std::to_string(FInterpTo(10.f, 0.f, 0.5f, 1.f)));''', 5),
     require=[{"id": "uses_fmath_clamp", "re": r"FMath::Clamp\s*\(", "why": "clamp the step with FMath::Clamp"}],
     forbid=[{"id": "no_engine_headers", "re": r'#include\s*[<"](?:CoreMinimal|Engine|GameFramework)', "why": "engine headers are not available in the tests"}],
     expect=5)
SEEDS[-1]["prelude"] = UNREAL_STANDINS

seed("unreal-cpp", "cpp", "mapped-range-clamped",
     "Unreal C++ math (stand-ins for `FMath::Clamp/Lerp` are provided; include nothing from the engine). Write `float GetMappedRangeValueClamped(float InMin, float InMax, float OutMin, float OutMax, float Value)` "
     "with Unreal's semantics: the percentage of `Value` within [InMin, InMax] clamped to [0, 1], then mapped linearly onto [OutMin, OutMax] (when InMax == InMin the percentage is 0).\n\n"
     "Reply with exactly one fenced ```cpp block containing only the function.",
     "float GetMappedRangeValueClamped(float InMin, float InMax, float OutMin, float OutMax, float Value) {\n    const float Range = InMax - InMin;\n"
     "    const float Pct = Range == 0.f ? 0.f : FMath::Clamp((Value - InMin) / Range, 0.f, 1.f);\n    return FMath::Lerp(OutMin, OutMax, Pct);\n}\n",
     "float GetMappedRangeValueClamped(float InMin, float InMax, float OutMin, float OutMax, float Value) {\n    return OutMin + (Value - InMin) / (InMax - InMin) * (OutMax - OutMin);\n}\n",
     tests=_cpp_harness('''    check("middle", std::fabs(GetMappedRangeValueClamped(0.f, 10.f, 0.f, 100.f, 5.f) - 50.f) < 1e-4f, "middle");
    check("below", GetMappedRangeValueClamped(0.f, 10.f, 0.f, 100.f, -5.f) == 0.f, "below");
    check("above", GetMappedRangeValueClamped(0.f, 10.f, 0.f, 100.f, 25.f) == 100.f, "above");
    check("inverted_out", std::fabs(GetMappedRangeValueClamped(0.f, 10.f, 1.f, 0.f, 2.5f) - 0.75f) < 1e-4f, "inverted");
    check("degenerate", GetMappedRangeValueClamped(5.f, 5.f, 3.f, 7.f, 5.f) == 3.f, "degenerate");''', 5),
     expect=5)
SEEDS[-1]["prelude"] = UNREAL_STANDINS

seed("unreal-cpp", "cpp", "homing-step",
     "Unreal C++ projectile logic with the stand-in `FVector` (members X, Y, Z; +, -, * float; `Size()`, `GetSafeNormal()`, `FVector::Dist`) provided by the tests. "
     "Write `FVector HomingVelocity(const FVector& Position, const FVector& Velocity, const FVector& TargetPosition, float HomingAcceleration, float DeltaTime)`: "
     "add `(TargetPosition - Position).GetSafeNormal() * HomingAcceleration * DeltaTime` to `Velocity`, then rescale the result to the ORIGINAL speed (`Velocity.Size()`) so homing only turns the projectile. "
     "If the original speed is 0 return `Velocity` unchanged.\n\nReply with exactly one fenced ```cpp block containing only the function.",
     "FVector HomingVelocity(const FVector& Position, const FVector& Velocity, const FVector& TargetPosition, float HomingAcceleration, float DeltaTime) {\n"
     "    const float Speed = Velocity.Size();\n    if (Speed <= 0.f) return Velocity;\n    const FVector Steer = (TargetPosition - Position).GetSafeNormal() * (HomingAcceleration * DeltaTime);\n"
     "    return (Velocity + Steer).GetSafeNormal() * Speed;\n}\n",
     "FVector HomingVelocity(const FVector& Position, const FVector& Velocity, const FVector& TargetPosition, float HomingAcceleration, float DeltaTime) {\n"
     "    return Velocity + (TargetPosition - Position).GetSafeNormal() * (HomingAcceleration * DeltaTime);\n}\n",
     tests=_cpp_harness('''    FVector v = HomingVelocity(FVector(0, 0, 0), FVector(10, 0, 0), FVector(0, 100, 0), 50.f, 0.2f);
    check("speed_kept", std::fabs(v.Size() - 10.f) < 1e-3f, std::to_string(v.Size()));
    check("turned_toward", v.Y > 0.f && v.X > 0.f && v.X < 10.f, std::to_string(v.X) + "," + std::to_string(v.Y));
    FVector w = HomingVelocity(FVector(0, 0, 0), FVector(0, 0, 0), FVector(1, 0, 0), 50.f, 0.2f);
    check("zero_speed", w.X == 0.f && w.Y == 0.f && w.Z == 0.f, "zero speed");
    FVector u = HomingVelocity(FVector(0, 0, 0), FVector(5, 0, 0), FVector(100, 0, 0), 50.f, 1.f);
    check("same_direction", std::fabs(u.X - 5.f) < 1e-3f && std::fabs(u.Y) < 1e-4f, std::to_string(u.X));''', 4),
     require=[{"id": "safe_normal", "re": r"GetSafeNormal\s*\(", "why": "use GetSafeNormal (the Unreal name)"}], expect=4)
SEEDS[-1]["prelude"] = UNREAL_STANDINS

# ---------------------------------------------------------------- Godot GDScript (headless)
GD_TEST = '''extends SceneTree
var passed := 0
func check(name: String, ok: bool, detail: String) -> void:
\tif ok:
\t\tpassed += 1
\t\tprint("@@PASS " + name)
\telse:
\t\tprint("@@FAIL " + name + ": " + detail)
func _init():
\tvar S = load("res://solution.gd")
\tif S == null:
\t\tprint("@@FAIL load: solution.gd did not load")
\telse:
@@CASES@@
\tprint("@@DONE %d/@@N@@" % passed)
\tquit()
'''


def _gd(cases: str, n: int) -> str:
    return GD_TEST.replace("@@CASES@@", cases).replace("@@N@@", str(n))


seed("godot-gdscript", "gdscript", "cooldown-timer",
     "Godot 4 GDScript (runs headless, no scene tree needed). Write a script that `extends RefCounted` with `class_name Cooldown` and:\n"
     "- `var duration: float` set by `func _init(d: float)`; `var remaining: float = 0.0`\n- `func ready() -> bool`: true when `remaining <= 0.0`\n"
     "- `func trigger() -> bool`: if ready, sets `remaining = duration` and returns true; otherwise returns false\n"
     "- `func tick(delta: float) -> void`: subtracts delta, never below 0.0\n- `signal finished` emitted exactly once when `tick` makes `remaining` reach 0 from above.\n\n"
     "Reply with exactly one fenced ```gdscript block containing only the script.",
     '''extends RefCounted
class_name Cooldown
signal finished
var duration: float
var remaining: float = 0.0
func _init(d: float) -> void:
\tduration = d
func ready() -> bool:
\treturn remaining <= 0.0
func trigger() -> bool:
\tif ready():
\t\tremaining = duration
\t\treturn true
\treturn false
func tick(delta: float) -> void:
\tif remaining <= 0.0:
\t\treturn
\tremaining = maxf(0.0, remaining - delta)
\tif remaining == 0.0:
\t\tfinished.emit()
''',
     "extends RefCounted\nclass_name Cooldown\nsignal finished\nvar duration: float\nvar remaining: float = 0.0\nfunc _init(d: float) -> void:\n\tduration = d\nfunc ready() -> bool:\n\treturn true\nfunc trigger() -> bool:\n\treturn true\nfunc tick(delta: float) -> void:\n\tremaining -= delta\n",
     tests=_gd('''\t\tvar c = S.new(2.0)
\t\tvar fired := [0]
\t\tc.finished.connect(func(): fired[0] += 1)
\t\tcheck("ready_at_start", c.ready(), "not ready")
\t\tcheck("trigger_once", c.trigger() and not c.trigger(), "double trigger")
\t\tc.tick(0.5)
\t\tcheck("remaining", abs(c.remaining - 1.5) < 1e-6, str(c.remaining))
\t\tc.tick(5.0)
\t\tcheck("clamped_and_signal", c.remaining == 0.0 and fired[0] == 1, "remaining %s fired %d" % [str(c.remaining), fired[0]])
\t\tc.tick(1.0)
\t\tcheck("signal_once", fired[0] == 1, "fired %d" % fired[0])
\t\tcheck("ready_again", c.ready() and c.trigger(), "not ready again")''', 6),
     require=[{"id": "signal", "re": r"^signal\s+finished", "why": "declare the finished signal", "flags": "m"}], expect=6)

seed("godot-gdscript", "gdscript", "animation-track-sampler",
     "Godot 4 GDScript. Write a script (`extends RefCounted`, `class_name TrackSampler`) that samples a keyframed float track the way AnimationPlayer interpolates linear tracks:\n"
     "- `func _init(times: Array, values: Array)` (ascending times, same length as values)\n"
     "- `func sample(t: float) -> float`: before the first key return the first value, after the last key return the last value, otherwise interpolate linearly between the surrounding keys.\n\n"
     "Reply with exactly one fenced ```gdscript block containing only the script.",
     '''extends RefCounted
class_name TrackSampler
var times: Array
var values: Array
func _init(t: Array, v: Array) -> void:
\ttimes = t
\tvalues = v
func sample(t: float) -> float:
\tif t <= times[0]:
\t\treturn values[0]
\tif t >= times[times.size() - 1]:
\t\treturn values[values.size() - 1]
\tfor i in range(times.size() - 1):
\t\tif t >= times[i] and t <= times[i + 1]:
\t\t\tvar f: float = (t - times[i]) / (times[i + 1] - times[i])
\t\t\treturn lerpf(values[i], values[i + 1], f)
\treturn values[values.size() - 1]
''',
     "extends RefCounted\nclass_name TrackSampler\nvar times: Array\nvar values: Array\nfunc _init(t: Array, v: Array) -> void:\n\ttimes = t\n\tvalues = v\nfunc sample(t: float) -> float:\n\treturn values[0]\n",
     tests=_gd('''\t\tvar s = S.new([0.0, 1.0, 3.0], [0.0, 10.0, 20.0])
\t\tcheck("before", s.sample(-1.0) == 0.0, str(s.sample(-1.0)))
\t\tcheck("key", s.sample(1.0) == 10.0, str(s.sample(1.0)))
\t\tcheck("between", abs(s.sample(0.5) - 5.0) < 1e-6, str(s.sample(0.5)))
\t\tcheck("second_span", abs(s.sample(2.0) - 15.0) < 1e-6, str(s.sample(2.0)))
\t\tcheck("after", s.sample(9.0) == 20.0, str(s.sample(9.0)))''', 5), expect=5)

# ---------------------------------------------------------------- Roblox Luau animation / VFX (pattern checks + static Luau check at attempt time)
def luau(topic, prompt, reference, trivial, require, forbid=()):
    SEEDS.append({"file": "roblox-animation-vfx", "language": "", "luau": True, "topic": topic, "prompt": prompt, "reference": reference,
                  "trivial": trivial, "require": list(require), "forbid": list(forbid), "category": "multi-roblox-animation-vfx"})


luau("tween-door",
     "In my Roblox game: write a server Script that tweens a door Part named \"Door\" in workspace open and closed. Use TweenService:Create with a TweenInfo of 1 second, "
     "Enum.EasingStyle.Quad and Enum.EasingDirection.Out, tween the CFrame to door.CFrame * CFrame.new(0, 8, 0), play it, wait for Completed with tween.Completed:Wait(), "
     "then tween back. Do not use the deprecated global wait(); use task.wait() if you need a delay.",
     '''```lua
local TweenService = game:GetService("TweenService")
local door = workspace:WaitForChild("Door") :: BasePart
local info = TweenInfo.new(1, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
local closed = door.CFrame
local open = closed * CFrame.new(0, 8, 0)

local function slide(target: CFrame)
\tlocal tween = TweenService:Create(door, info, { CFrame = target })
\ttween:Play()
\ttween.Completed:Wait()
end

slide(open)
task.wait(2)
slide(closed)
```
''',
     "```lua\nlocal door = workspace.Door\ndoor.CFrame = door.CFrame * CFrame.new(0, 8, 0)\nwait(2)\n```\n",
     require=[{"id": "tweenservice", "re": r'GetService\("TweenService"\)', "why": "use TweenService"},
              {"id": "tweeninfo", "re": r"TweenInfo\.new\(\s*1\b.*Enum\.EasingStyle\.Quad.*Enum\.EasingDirection\.Out", "why": "the given TweenInfo"},
              {"id": "create", "re": r":Create\(", "why": "TweenService:Create"}, {"id": "play", "re": r":Play\(\)", "why": "play the tween"},
              {"id": "completed", "re": r"Completed:Wait\(\)", "why": "wait for Completed"}],
     forbid=[{"id": "no_wait", "re": r"(?<![.\w])wait\s*\(", "why": "no deprecated global wait()"}])

luau("particle-burst",
     "In my Roblox game: write a ModuleScript function `burst(part: BasePart, count: number)` that finds the ParticleEmitter child of `part` with FindFirstChildOfClass(\"ParticleEmitter\") "
     "and calls `emitter:Emit(count)`; if there is no emitter it should warn and return. Also set `emitter.Enabled = false` so it only emits on bursts. Return the module table.",
     '''```lua
local Burst = {}

function Burst.burst(part: BasePart, count: number)
\tlocal emitter = part:FindFirstChildOfClass("ParticleEmitter")
\tif not emitter then
\t\twarn("no ParticleEmitter under", part:GetFullName())
\t\treturn
\tend
\temitter.Enabled = false
\temitter:Emit(count)
end

return Burst
```
''',
     "```lua\nlocal Burst = {}\nfunction Burst.burst(part, count)\n\tpart.ParticleEmitter.Rate = count\nend\nreturn Burst\n```\n",
     require=[{"id": "find", "re": r'FindFirstChildOfClass\("ParticleEmitter"\)', "why": "find the emitter"}, {"id": "emit", "re": r":Emit\(\s*count\s*\)", "why": "Emit(count)"},
              {"id": "disabled", "re": r"\.Enabled\s*=\s*false", "why": "Enabled = false"}, {"id": "warn", "re": r"\bwarn\(", "why": "warn when missing"},
              {"id": "returns", "re": r"return\s+Burst", "why": "return the module"}])

luau("animation-priority",
     "In my Roblox game: write a LocalScript that loads an attack animation (AnimationId \"rbxassetid://9876543210\") on the local player's Humanoid Animator "
     "(Humanoid:WaitForChild(\"Animator\") then Animator:LoadAnimation), sets `track.Priority = Enum.AnimationPriority.Action`, and plays it with a fade time of 0.1 when the "
     "player presses the F key (UserInputService.InputBegan, ignore when gameProcessed is true). Do not use Humanoid:LoadAnimation (deprecated).",
     '''```lua
local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")

local player = Players.LocalPlayer
local character = player.Character or player.CharacterAdded:Wait()
local humanoid = character:WaitForChild("Humanoid") :: Humanoid
local animator = humanoid:WaitForChild("Animator") :: Animator

local animation = Instance.new("Animation")
animation.AnimationId = "rbxassetid://9876543210"
local track = animator:LoadAnimation(animation)
track.Priority = Enum.AnimationPriority.Action

UserInputService.InputBegan:Connect(function(input, gameProcessed)
\tif gameProcessed then
\t\treturn
\tend
\tif input.KeyCode == Enum.KeyCode.F then
\t\ttrack:Play(0.1)
\tend
end)
```
''',
     "```lua\nlocal humanoid = script.Parent:WaitForChild(\"Humanoid\")\nlocal track = humanoid:LoadAnimation(Instance.new(\"Animation\"))\ntrack:Play()\n```\n",
     require=[{"id": "animator", "re": r'WaitForChild\("Animator"\)', "why": "get the Animator"}, {"id": "load", "re": r"animator:LoadAnimation|Animator:LoadAnimation", "why": "LoadAnimation on the Animator", "flags": "i"},
              {"id": "priority", "re": r"\.Priority\s*=\s*Enum\.AnimationPriority\.Action", "why": "Action priority"}, {"id": "fade", "re": r":Play\(\s*0\.1\s*\)", "why": "fade time 0.1"},
              {"id": "input", "re": r"InputBegan:Connect", "why": "InputBegan"}, {"id": "gp", "re": r"gameProcessed", "why": "respect gameProcessed"}, {"id": "key", "re": r"Enum\.KeyCode\.F\b", "why": "the F key"}],
     forbid=[{"id": "no_humanoid_load", "re": r"[Hh]umanoid\s*:\s*LoadAnimation", "why": "Humanoid:LoadAnimation is deprecated"}])

luau("beam-between-parts",
     "In my Roblox game: write a function `connect(a: BasePart, b: BasePart): Beam` that creates an Attachment in each part, a Beam parented to `a` with Attachment0 and Attachment1 set to them, "
     "Width0 and Width1 of 0.5, a Color of ColorSequence.new(Color3.fromRGB(0, 170, 255)) and returns the Beam. Use Instance.new for every object and set Parent last.",
     '''```lua
local function connect(a: BasePart, b: BasePart): Beam
\tlocal a0 = Instance.new("Attachment")
\ta0.Parent = a
\tlocal a1 = Instance.new("Attachment")
\ta1.Parent = b
\tlocal beam = Instance.new("Beam")
\tbeam.Attachment0 = a0
\tbeam.Attachment1 = a1
\tbeam.Width0 = 0.5
\tbeam.Width1 = 0.5
\tbeam.Color = ColorSequence.new(Color3.fromRGB(0, 170, 255))
\tbeam.Parent = a
\treturn beam
end

return connect
```
''',
     "```lua\nlocal function connect(a, b)\n\tlocal beam = Instance.new(\"Beam\", a)\n\treturn beam\nend\nreturn connect\n```\n",
     require=[{"id": "attachments", "re": r'Instance\.new\("Attachment"\)[\s\S]*Instance\.new\("Attachment"\)', "why": "two attachments"}, {"id": "beam", "re": r'Instance\.new\("Beam"\)', "why": "a Beam"},
              {"id": "a0", "re": r"\.Attachment0\s*=", "why": "Attachment0"}, {"id": "a1", "re": r"\.Attachment1\s*=", "why": "Attachment1"},
              {"id": "width", "re": r"\.Width0\s*=\s*0\.5[\s\S]*\.Width1\s*=\s*0\.5", "why": "widths 0.5"}, {"id": "color", "re": r"ColorSequence\.new\(Color3\.fromRGB\(0,\s*170,\s*255\)\)", "why": "the colour"}],
     forbid=[{"id": "parent_arg", "re": r'Instance\.new\("\w+",\s*\w', "why": "do not pass the parent to Instance.new; set Parent last"}])

luau("trail-on-sword",
     "In my Roblox game: write a server Script for a Tool named \"Sword\" (script.Parent) that creates a Trail on the tool's Handle: two Attachments at the top and bottom of the blade "
     "(Position Vector3.new(0, 2, 0) and Vector3.new(0, -2, 0)), a Trail with Attachment0/Attachment1, Lifetime 0.3, and that is Enabled only while the tool is equipped "
     "(Tool.Equipped sets Enabled = true, Tool.Unequipped sets Enabled = false).",
     '''```lua
local tool = script.Parent :: Tool
local handle = tool:WaitForChild("Handle") :: BasePart

local top = Instance.new("Attachment")
top.Position = Vector3.new(0, 2, 0)
top.Parent = handle
local bottom = Instance.new("Attachment")
bottom.Position = Vector3.new(0, -2, 0)
bottom.Parent = handle

local trail = Instance.new("Trail")
trail.Attachment0 = top
trail.Attachment1 = bottom
trail.Lifetime = 0.3
trail.Enabled = false
trail.Parent = handle

tool.Equipped:Connect(function()
\ttrail.Enabled = true
end)
tool.Unequipped:Connect(function()
\ttrail.Enabled = false
end)
```
''',
     "```lua\nlocal trail = Instance.new(\"Trail\")\ntrail.Parent = script.Parent.Handle\ntrail.Enabled = true\n```\n",
     require=[{"id": "trail", "re": r'Instance\.new\("Trail"\)', "why": "a Trail"}, {"id": "positions", "re": r"Vector3\.new\(0,\s*2,\s*0\)[\s\S]*Vector3\.new\(0,\s*-2,\s*0\)", "why": "the two positions"},
              {"id": "lifetime", "re": r"\.Lifetime\s*=\s*0\.3", "why": "Lifetime 0.3"}, {"id": "equipped", "re": r"Equipped:Connect[\s\S]*Enabled\s*=\s*true", "why": "enable on Equipped"},
              {"id": "unequipped", "re": r"Unequipped:Connect[\s\S]*Enabled\s*=\s*false", "why": "disable on Unequipped"}])

luau("spring-camera-shake",
     "In my Roblox game: write a LocalScript that applies camera shake with RunService.RenderStepped: keep a `trauma` number (0 to 1) that decays by 1.5 per second (never below 0), "
     "and every frame offset `workspace.CurrentCamera.CFrame` by `CFrame.new(math.random() - 0.5, math.random() - 0.5, 0) * (trauma * trauma * 0.5)` (multiply the offset vector, "
     "i.e. use CFrame.new((math.random() - 0.5) * amp, (math.random() - 0.5) * amp, 0) with amp = trauma * trauma * 0.5). Expose a function `shake(amount: number)` that adds to trauma and clamps it with math.clamp(…, 0, 1). "
     "Use math.clamp, RunService.RenderStepped and the deltaTime argument; do not use wait().",
     '''```lua
local RunService = game:GetService("RunService")

local camera = workspace.CurrentCamera
local trauma = 0

local function shake(amount: number)
\ttrauma = math.clamp(trauma + amount, 0, 1)
end

RunService.RenderStepped:Connect(function(deltaTime: number)
\ttrauma = math.max(0, trauma - 1.5 * deltaTime)
\tlocal amp = trauma * trauma * 0.5
\tcamera.CFrame = camera.CFrame * CFrame.new((math.random() - 0.5) * amp, (math.random() - 0.5) * amp, 0)
end)

return shake
```
''',
     "```lua\nlocal camera = workspace.CurrentCamera\nwhile true do\n\tcamera.CFrame = camera.CFrame * CFrame.new(math.random(), math.random(), 0)\n\twait()\nend\n```\n",
     require=[{"id": "renderstepped", "re": r"RenderStepped:Connect", "why": "RenderStepped"}, {"id": "clamp", "re": r"math\.clamp\(", "why": "math.clamp"},
              {"id": "decay", "re": r"1\.5\s*\*\s*\w*[dD]elta", "why": "decay 1.5 per second using deltaTime"}, {"id": "amp", "re": r"trauma\s*\*\s*trauma\s*\*\s*0\.5", "why": "trauma squared times 0.5"},
              {"id": "shake_fn", "re": r"function\s+shake\s*\(", "why": "the shake function"}],
     forbid=[{"id": "no_wait", "re": r"(?<![.\w])wait\s*\(", "why": "no deprecated global wait()"}])

# ---------------------------------------------------------------- shaders (glslang compile check + required names)
seed("shaders-glsl", "glsl", "fragment-tint",
     "Write a GLSL 450 fragment shader (Vulkan style, `#version 450`) that reads `layout(location = 0) in vec2 uv;`, samples `layout(set = 0, binding = 0) uniform sampler2D albedo;`, "
     "multiplies the sampled colour by a push-constant tint `layout(push_constant) uniform Push { vec4 tint; } pc;` and writes `layout(location = 0) out vec4 outColor;`. "
     "It must compile with glslangValidator. Reply with exactly one fenced ```glsl block.",
     "#version 450\nlayout(location = 0) in vec2 uv;\nlayout(set = 0, binding = 0) uniform sampler2D albedo;\nlayout(push_constant) uniform Push { vec4 tint; } pc;\nlayout(location = 0) out vec4 outColor;\n"
     "void main() {\n    outColor = texture(albedo, uv) * pc.tint;\n}\n",
     "#version 450\nlayout(location = 0) out vec4 outColor;\nvoid main() {\n    outColor = vec4(1.0);\n}\n",
     tests="frag", require=[{"id": "sampler", "re": r"uniform\s+sampler2D\s+albedo", "why": "the albedo sampler"}, {"id": "texture", "re": r"texture\s*\(\s*albedo\s*,\s*uv\s*\)", "why": "sample with texture()"},
                            {"id": "tint", "re": r"pc\.tint", "why": "multiply by the push-constant tint"}, {"id": "out", "re": r"layout\s*\(\s*location\s*=\s*0\s*\)\s*out\s+vec4\s+outColor", "why": "the output"}])

seed("shaders-glsl", "glsl", "vertex-mvp",
     "Write a GLSL 450 vertex shader: inputs `layout(location = 0) in vec3 inPosition;` and `layout(location = 1) in vec3 inNormal;`, a uniform block "
     "`layout(set = 0, binding = 0) uniform Camera { mat4 model; mat4 view; mat4 proj; } cam;`, outputs `layout(location = 0) out vec3 worldNormal;`. "
     "Set `gl_Position = cam.proj * cam.view * cam.model * vec4(inPosition, 1.0)` and `worldNormal = mat3(cam.model) * inNormal`. Must compile with glslangValidator. "
     "Reply with exactly one fenced ```glsl block.",
     "#version 450\nlayout(location = 0) in vec3 inPosition;\nlayout(location = 1) in vec3 inNormal;\nlayout(set = 0, binding = 0) uniform Camera { mat4 model; mat4 view; mat4 proj; } cam;\n"
     "layout(location = 0) out vec3 worldNormal;\nvoid main() {\n    gl_Position = cam.proj * cam.view * cam.model * vec4(inPosition, 1.0);\n    worldNormal = mat3(cam.model) * inNormal;\n}\n",
     "#version 450\nlayout(location = 0) in vec3 inPosition;\nvoid main() {\n    gl_Position = vec4(inPosition, 1.0);\n}\n",
     tests="vert", require=[{"id": "mvp", "re": r"cam\.proj\s*\*\s*cam\.view\s*\*\s*cam\.model", "why": "proj * view * model order"}, {"id": "normal", "re": r"mat3\s*\(\s*cam\.model\s*\)\s*\*\s*inNormal", "why": "transform the normal"},
                            {"id": "block", "re": r"uniform\s+Camera\s*\{", "why": "the Camera uniform block"}])

seed("shaders-glsl", "glsl", "compute-fade",
     "Write a GLSL 450 compute shader with `layout(local_size_x = 64) in;` that reads `layout(std430, set = 0, binding = 0) buffer Ages { float age[]; };` and "
     "`layout(std430, set = 0, binding = 1) buffer Alphas { float alpha[]; };`, a push constant `layout(push_constant) uniform Push { float lifetime; uint count; } pc;` and, for "
     "`uint i = gl_GlobalInvocationID.x;` when `i < pc.count`, writes `alpha[i] = clamp(1.0 - age[i] / pc.lifetime, 0.0, 1.0);`. Must compile with glslangValidator. Reply with exactly one fenced ```glsl block.",
     "#version 450\nlayout(local_size_x = 64) in;\nlayout(std430, set = 0, binding = 0) buffer Ages { float age[]; };\nlayout(std430, set = 0, binding = 1) buffer Alphas { float alpha[]; };\n"
     "layout(push_constant) uniform Push { float lifetime; uint count; } pc;\nvoid main() {\n    uint i = gl_GlobalInvocationID.x;\n    if (i < pc.count) {\n        alpha[i] = clamp(1.0 - age[i] / pc.lifetime, 0.0, 1.0);\n    }\n}\n",
     "#version 450\nlayout(local_size_x = 64) in;\nvoid main() {\n}\n",
     tests="comp", require=[{"id": "bounds", "re": r"gl_GlobalInvocationID\.x", "why": "use the invocation id"}, {"id": "guard", "re": r"<\s*pc\.count", "why": "bounds check against count"},
                            {"id": "clamp", "re": r"clamp\s*\(\s*1\.0\s*-\s*age\[i\]\s*/\s*pc\.lifetime", "why": "the fade formula"}])

seed("shaders-hlsl", "hlsl", "pixel-rim-light",
     "Write an HLSL pixel shader function `float4 main(float3 normal : NORMAL, float3 viewDir : TEXCOORD0) : SV_Target` that computes a rim light: "
     "`float rim = 1.0 - saturate(dot(normalize(normal), normalize(viewDir)));` then `rim = pow(rim, 3.0);` and returns `float4(rim.xxx, 1.0)`. "
     "It must compile with glslangValidator in HLSL mode. Reply with exactly one fenced ```hlsl block.",
     "float4 main(float3 normal : NORMAL, float3 viewDir : TEXCOORD0) : SV_Target {\n    float rim = 1.0 - saturate(dot(normalize(normal), normalize(viewDir)));\n    rim = pow(rim, 3.0);\n    return float4(rim.xxx, 1.0);\n}\n",
     "float4 main() : SV_Target {\n    return float4(1, 1, 1, 1);\n}\n",
     require=[{"id": "saturate", "re": r"saturate\s*\(\s*dot\s*\(", "why": "saturate(dot(...))"}, {"id": "pow", "re": r"pow\s*\(\s*rim\s*,\s*3", "why": "pow(rim, 3)"},
              {"id": "semantics", "re": r":\s*NORMAL[\s\S]*:\s*TEXCOORD0[\s\S]*:\s*SV_Target", "why": "the semantics"}])

seed("shaders-hlsl", "hlsl", "pixel-dissolve",
     "Write an HLSL pixel shader `float4 main(float2 uv : TEXCOORD0) : SV_Target` using `Texture2D noiseTex : register(t0); SamplerState samp : register(s0);` and "
     "`cbuffer Params : register(b0) { float threshold; float3 edgeColor; }`: sample `float n = noiseTex.Sample(samp, uv).r;`, `clip(n - threshold);` (discard dissolved pixels), "
     "and return `edgeColor` as the rgb when `n - threshold < 0.05`, otherwise white; alpha 1. Must compile with glslangValidator in HLSL mode. Reply with exactly one fenced ```hlsl block.",
     "Texture2D noiseTex : register(t0);\nSamplerState samp : register(s0);\ncbuffer Params : register(b0) { float threshold; float3 edgeColor; }\n"
     "float4 main(float2 uv : TEXCOORD0) : SV_Target {\n    float n = noiseTex.Sample(samp, uv).r;\n    clip(n - threshold);\n    float3 rgb = (n - threshold < 0.05) ? edgeColor : float3(1, 1, 1);\n    return float4(rgb, 1.0);\n}\n",
     "float4 main(float2 uv : TEXCOORD0) : SV_Target {\n    return float4(1, 1, 1, 1);\n}\n",
     require=[{"id": "clip", "re": r"clip\s*\(\s*n\s*-\s*threshold\s*\)", "why": "clip(n - threshold)"}, {"id": "sample", "re": r"noiseTex\.Sample\s*\(\s*samp\s*,\s*uv\s*\)", "why": "sample the noise"},
              {"id": "cbuffer", "re": r"cbuffer\s+Params", "why": "the constant buffer"}])

# ---------------------------------------------------------------- design patterns (python / typescript, class harnesses)
PY_H = ("\n__passed = [0]\ndef __check(name, ok, detail=''):\n    if ok:\n        __passed[0] += 1\n        print('@@PASS ' + name)\n    else:\n        print('@@FAIL %s: %s' % (name, detail))\n")
seed("patterns-python", "python", "observer-event-bus",
     "Design pattern (Observer) in Python 3. Write `class EventBus` with `subscribe(event: str, handler) -> callable` (returns an unsubscribe function), "
     "`publish(event: str, *args) -> int` (calls every handler subscribed to that event in subscription order with the args; returns how many were called; unknown events return 0). "
     "A handler unsubscribed during publish must not be called again later; a handler that raises must not stop the others (swallow the exception). "
     "Reply with exactly one fenced ```python block containing only the class.",
     '''class EventBus:
    def __init__(self):
        self._handlers = {}

    def subscribe(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

        def unsubscribe():
            handlers = self._handlers.get(event, [])
            if handler in handlers:
                handlers.remove(handler)
        return unsubscribe

    def publish(self, event, *args):
        called = 0
        for handler in list(self._handlers.get(event, [])):
            if handler not in self._handlers.get(event, []):
                continue
            try:
                handler(*args)
            except Exception:
                pass
            called += 1
        return called
''',
     "class EventBus:\n    def subscribe(self, event, handler):\n        return lambda: None\n\n    def publish(self, event, *args):\n        return 0\n",
     tests=PY_H + '''
bus = EventBus()
log = []
off_a = bus.subscribe("hit", lambda d: log.append(("a", d)))
bus.subscribe("hit", lambda d: log.append(("b", d)))
n = bus.publish("hit", 5)
__check("both_called", n == 2 and log == [("a", 5), ("b", 5)], repr((n, log)))
__check("unknown_event", bus.publish("nope") == 0)
off_a()
log.clear()
bus.publish("hit", 1)
__check("unsubscribed", log == [("b", 1)], repr(log))
def boom(_):
    raise ValueError("x")
bus.subscribe("hit", boom)
bus.subscribe("hit", lambda d: log.append(("c", d)))
log.clear()
n = bus.publish("hit", 2)
__check("exception_swallowed", ("c", 2) in log and n == 3, repr((n, log)))
print("@@DONE %d/4" % __passed[0])
''', expect=4)

seed("patterns-python", "python", "object-pool",
     "Design pattern (Object Pool) in Python 3. Write `class Pool` with `__init__(self, factory, size: int)` that pre-creates `size` objects with `factory()`, "
     "`acquire()` returning a free object (creating a new one with `factory()` when none is free), `release(obj)` putting it back (ignoring objects not from this pool and double releases), "
     "and properties `free` (count of free objects) and `created` (total objects ever created). Reply with exactly one fenced ```python block containing only the class.",
     '''class Pool:
    def __init__(self, factory, size):
        self._factory = factory
        self._free = [factory() for _ in range(size)]
        self._all = set(id(o) for o in self._free)
        self._in_use = set()
        self.created = size

    def acquire(self):
        if self._free:
            obj = self._free.pop()
        else:
            obj = self._factory()
            self._all.add(id(obj))
            self.created += 1
        self._in_use.add(id(obj))
        return obj

    def release(self, obj):
        if id(obj) not in self._all or id(obj) not in self._in_use:
            return
        self._in_use.discard(id(obj))
        self._free.append(obj)

    @property
    def free(self):
        return len(self._free)
''',
     "class Pool:\n    def __init__(self, factory, size):\n        self._factory = factory\n        self.created = 0\n        self.free = 0\n\n    def acquire(self):\n        self.created += 1\n        return self._factory()\n\n    def release(self, obj):\n        pass\n",
     tests=PY_H + '''
count = [0]
def make():
    count[0] += 1
    return {"id": count[0]}
p = Pool(make, 2)
__check("precreated", p.created == 2 and p.free == 2, repr((p.created, p.free)))
a = p.acquire(); b = p.acquire()
__check("two_out", p.free == 0 and a is not b)
c = p.acquire()
__check("grows", p.created == 3 and count[0] == 3, repr(p.created))
p.release(a); p.release(a)
__check("double_release_ignored", p.free == 1, repr(p.free))
p.release({"id": 99})
__check("foreign_ignored", p.free == 1, repr(p.free))
d = p.acquire()
__check("reuses", d is a and p.created == 3)
print("@@DONE %d/6" % __passed[0])
''', expect=6)

TS_H = ("\nlet __passed = 0;\nfunction __check(name: string, ok: boolean, detail: string = \"\"): void {\n  if (ok) { __passed++; console.log(\"@@PASS \" + name); } else console.log(\"@@FAIL \" + name + \": \" + detail);\n}\n")
seed("patterns-typescript", "typescript", "state-machine",
     "Design pattern (State) in TypeScript (strict). Write `class StateMachine<S extends string, E extends string>` with constructor `(initial: S, transitions: Array<[S, E, S]>)`, "
     "a readonly getter `state: S`, `can(event: E): boolean`, `fire(event: E): boolean` (applies the transition for the current state and returns true, or returns false and keeps the state), "
     "and `onEnter(state: S, cb: (from: S) => void): void` whose callbacks run after entering that state. Reply with exactly one fenced ```typescript block containing only the class.",
     '''class StateMachine<S extends string, E extends string> {
  private current: S;
  private readonly table = new Map<string, S>();
  private readonly enter = new Map<S, Array<(from: S) => void>>();

  constructor(initial: S, transitions: Array<[S, E, S]>) {
    this.current = initial;
    for (const [from, event, to] of transitions) this.table.set(from + "|" + event, to);
  }

  get state(): S { return this.current; }

  can(event: E): boolean { return this.table.has(this.current + "|" + event); }

  fire(event: E): boolean {
    const next = this.table.get(this.current + "|" + event);
    if (next === undefined) return false;
    const from = this.current;
    this.current = next;
    for (const cb of this.enter.get(next) ?? []) cb(from);
    return true;
  }

  onEnter(state: S, cb: (from: S) => void): void {
    const list = this.enter.get(state) ?? [];
    list.push(cb);
    this.enter.set(state, list);
  }
}
''',
     "class StateMachine<S extends string, E extends string> {\n  private current: S;\n  constructor(initial: S, transitions: Array<[S, E, S]>) { this.current = initial; }\n  get state(): S { return this.current; }\n  can(event: E): boolean { return false; }\n  fire(event: E): boolean { return false; }\n  onEnter(state: S, cb: (from: S) => void): void {}\n}\n",
     tests=TS_H + '''
type S = "idle" | "run" | "jump";
type E = "move" | "stop" | "hop" | "land";
const m = new StateMachine<S, E>("idle", [["idle", "move", "run"], ["run", "stop", "idle"], ["run", "hop", "jump"], ["idle", "hop", "jump"], ["jump", "land", "idle"]]);
const entered: string[] = [];
m.onEnter("jump", (from) => entered.push("jump<-" + from));
__check("initial", m.state === "idle");
__check("can", m.can("move") && !m.can("land"));
__check("fire", m.fire("move") && m.state === "run");
__check("bad_event", !m.fire("land") && m.state === "run");
__check("enter_cb", m.fire("hop") && entered.length === 1 && entered[0] === "jump<-run", JSON.stringify(entered));
__check("land", m.fire("land") && m.state === "idle");
console.log("@@DONE " + __passed + "/6");
''', expect=6)

seed("patterns-typescript", "typescript", "command-undo",
     "Design pattern (Command) in TypeScript (strict). Write `interface Command { execute(): void; undo(): void; }` and `class History` with `run(cmd: Command): void` (executes and records it, "
     "clearing any redo entries), `undo(): boolean`, `redo(): boolean` (return false when nothing to undo/redo) and a getter `size: number` (commands that can be undone). "
     "Reply with exactly one fenced ```typescript block containing the interface and the class.",
     '''interface Command { execute(): void; undo(): void; }

class History {
  private done: Command[] = [];
  private undone: Command[] = [];

  run(cmd: Command): void {
    cmd.execute();
    this.done.push(cmd);
    this.undone = [];
  }

  undo(): boolean {
    const cmd = this.done.pop();
    if (!cmd) return false;
    cmd.undo();
    this.undone.push(cmd);
    return true;
  }

  redo(): boolean {
    const cmd = this.undone.pop();
    if (!cmd) return false;
    cmd.execute();
    this.done.push(cmd);
    return true;
  }

  get size(): number { return this.done.length; }
}
''',
     "interface Command { execute(): void; undo(): void; }\nclass History {\n  run(cmd: Command): void { cmd.execute(); }\n  undo(): boolean { return false; }\n  redo(): boolean { return false; }\n  get size(): number { return 0; }\n}\n",
     tests=TS_H + '''
let value = 0;
const add = (n: number): Command => ({ execute: () => { value += n; }, undo: () => { value -= n; } });
const h = new History();
h.run(add(5)); h.run(add(3));
__check("executed", value === 8 && h.size === 2, String(value));
__check("undo", h.undo() && value === 5 && h.size === 1, String(value));
__check("redo", h.redo() && value === 8, String(value));
__check("undo_twice_then_empty", h.undo() && h.undo() && !h.undo() && value === 0, String(value));
h.redo(); h.run(add(10));
__check("run_clears_redo", !h.redo() && value === 15, String(value));
console.log("@@DONE " + __passed + "/5");
''', expect=5)


def make_tasks(date: str) -> list[dict]:
    tasks = []
    for s in SEEDS:
        tid = f"multi-{s['file']}-{s['topic']}"
        if s.get("luau"):
            auto = {"strict": False, "require": s["require"], **({"forbid": s["forbid"]} if s["forbid"] else {})}
            tasks.append({"id": tid, "category": s["category"], "difficulty": 2, "goal": s["topic"].replace("-", " "), "prompt": s["prompt"],
                          "run_mode": "automated", "hard_fail": ["A required behaviour is missing"], "auto": auto, "source": "multi-school-" + date,
                          "family": "roblox-animation-vfx", "topic": s["topic"], "required_evidence": ["answer.md", "check-results.json"],
                          "pass_conditions": ["Luau static check passes and every required pattern is present"],
                          "_reference": s["reference"], "_trivial": s["trivial"], "_file": s["file"]})
            continue
        lang = s["language"]
        tag = {"cpp": "cpp", "csharp": "csharp"}.get(lang, lang)
        judge = {"tests": s["tests"], "run_s": s["run_s"]}
        if s["expect"] is not None:
            judge["expect"] = s["expect"]
        if s.get("prelude"):
            judge["prelude"] = s["prelude"]
        auto = {"language": lang, "code": False, "compile": False, "judge": judge}
        if s["require"]:
            auto["require"] = s["require"]
        if s["forbid"]:
            auto["forbid"] = s["forbid"]
        tasks.append({"id": tid, "category": s["category"], "difficulty": 2, "goal": s["topic"].replace("-", " "), "prompt": s["prompt"],
                      "run_mode": "judge", "hard_fail": ["unit tests fail in the judge"], "auto": auto, "source": "multi-school-" + date,
                      "family": s["file"], "topic": s["topic"], "required_evidence": ["answer.md", "check-results.json"],
                      "pass_conditions": ["compiles and every check passes in the judge container"],
                      "_reference": f"```{tag}\n{s['reference'].rstrip()}\n```\n", "_trivial": f"```{tag}\n{s['trivial'].rstrip()}\n```\n", "_file": s["file"]})
    return tasks
