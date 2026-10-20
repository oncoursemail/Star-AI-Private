"""Test harnesses for the problem bank: one function, typed arguments, expected results, rendered in every judge
language. Types: int, float, bool, str, int[], str[], float[]. The harness prints "@@PASS name" / "@@FAIL name: ..."
and "@@DONE passed/total" (read by nightschool.judge)."""
from __future__ import annotations

import json

LANGS = ["python", "javascript", "typescript", "cpp", "csharp", "java", "go", "rust", "lua", "gdscript"]


def camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(w.capitalize() for w in rest)


def pascal(snake: str) -> str:
    return "".join(w.capitalize() for w in snake.split("_"))


def fn_name(lang: str, snake: str) -> str:
    if lang in ("javascript", "typescript", "java", "cpp"):
        return camel(snake)
    if lang in ("csharp", "go"):
        return pascal(snake)
    return snake


def _f(v) -> str:
    """A float literal that every language reads as a float."""
    text = repr(float(v))
    if "e" in text or "E" in text:
        text = format(float(v), ".10f").rstrip("0")
        if text.endswith("."):
            text += "0"
    return text


def lit(lang: str, typ: str, v) -> str:
    if typ == "int":
        return str(int(v))
    if typ == "float":
        return _f(v)
    if typ == "bool":
        return {"python": ("True" if v else "False"), "gdscript": ("true" if v else "false")}.get(lang, "true" if v else "false")
    if typ == "str":
        s = json.dumps(v)
        if lang == "rust":
            return s                                   # &str literal; owned where needed by the caller
        return s
    if typ.endswith("[]"):
        inner = typ[:-2]
        items = [lit(lang, inner, x) for x in v]
        joined = ", ".join(items)
        if lang in ("python", "javascript", "typescript", "gdscript"):
            return "[" + joined + "]"
        if lang == "lua":
            return "{" + joined + "}"
        if lang == "cpp":
            return "std::vector<%s>{%s}" % (cpp_type(inner), joined)
        if lang == "csharp":
            return "new %s[]{%s}" % (cs_type(inner), joined)
        if lang == "java":
            return "new %s[]{%s}" % (java_type(inner), joined)
        if lang == "go":
            return "[]%s{%s}" % (go_type(inner), joined)
        if lang == "rust":
            if inner == "str":
                return "vec![" + ", ".join("String::from(%s)" % i for i in items) + "]"
            return "vec![" + joined + "]"
    raise ValueError(typ)


def cpp_type(typ: str) -> str:
    base = {"int": "int", "float": "double", "bool": "bool", "str": "std::string"}
    if typ.endswith("[]"):
        return "std::vector<%s>" % base[typ[:-2]]
    return base[typ]


def cs_type(typ: str) -> str:
    base = {"int": "int", "float": "double", "bool": "bool", "str": "string"}
    return base[typ[:-2]] + "[]" if typ.endswith("[]") else base[typ]


def java_type(typ: str) -> str:
    base = {"int": "int", "float": "double", "bool": "boolean", "str": "String"}
    return base[typ[:-2]] + "[]" if typ.endswith("[]") else base[typ]


def go_type(typ: str) -> str:
    base = {"int": "int", "float": "float64", "bool": "bool", "str": "string"}
    return "[]" + base[typ[:-2]] if typ.endswith("[]") else base[typ]


def rust_param(typ: str) -> str:
    base = {"int": "i64", "float": "f64", "bool": "bool", "str": "&str"}
    if typ.endswith("[]"):
        return {"int": "&[i64]", "float": "&[f64]", "str": "&[String]", "bool": "&[bool]"}[typ[:-2]]
    return base[typ]


def rust_ret(typ: str) -> str:
    base = {"int": "i64", "float": "f64", "bool": "bool", "str": "String"}
    if typ.endswith("[]"):
        return "Vec<%s>" % {"int": "i64", "float": "f64", "str": "String", "bool": "bool"}[typ[:-2]]
    return base[typ]


def ts_type(typ: str) -> str:
    base = {"int": "number", "float": "number", "bool": "boolean", "str": "string"}
    return base[typ[:-2]] + "[]" if typ.endswith("[]") else base[typ]


def gd_type(typ: str) -> str:
    base = {"int": "int", "float": "float", "bool": "bool", "str": "String"}
    return "Array" if typ.endswith("[]") else base[typ]


def signature(lang: str, fn: str, params: list[tuple[str, str]], ret: str) -> str:
    """The declaration line the prompt shows (and the stub uses)."""
    name = fn_name(lang, fn)
    if lang == "python":
        return "def %s(%s)" % (name, ", ".join(p for p, _ in params))
    if lang == "javascript":
        return "function %s(%s)" % (name, ", ".join(p for p, _ in params))
    if lang == "typescript":
        return "function %s(%s): %s" % (name, ", ".join("%s: %s" % (p, ts_type(t)) for p, t in params), ts_type(ret))
    if lang == "cpp":
        def param(t):
            return cpp_type(t) if t in ("int", "float", "bool") else "const " + cpp_type(t) + "&"
        return "%s %s(%s)" % (cpp_type(ret), name, ", ".join("%s %s" % (param(t), p) for p, t in params))
    if lang == "csharp":
        return "public static %s %s(%s)" % (cs_type(ret), name, ", ".join("%s %s" % (cs_type(t), p) for p, t in params))
    if lang == "java":
        return "public static %s %s(%s)" % (java_type(ret), name, ", ".join("%s %s" % (java_type(t), p) for p, t in params))
    if lang == "go":
        return "func %s(%s) %s" % (name, ", ".join("%s %s" % (p, go_type(t)) for p, t in params), go_type(ret))
    if lang == "rust":
        return "fn %s(%s) -> %s" % (name, ", ".join("%s: %s" % (p, rust_param(t)) for p, t in params), rust_ret(ret))
    if lang == "lua":
        return "function %s(%s)" % (name, ", ".join(p for p, _ in params))
    if lang == "gdscript":
        return "static func %s(%s) -> %s" % (name, ", ".join("%s: %s" % (p, gd_type(t)) for p, t in params), gd_type(ret))
    raise ValueError(lang)


def container(lang: str) -> str:
    """Where the function lives, for the prompt."""
    return {"csharp": "a `public static class Solution`", "java": "a `public class Solution`",
            "gdscript": "a script (solution.gd) that will be loaded with `load()`; use `static func`",
            "go": "`package main`", "rust": "the top level (no `main`)", "lua": "the top level (a global function)",
            }.get(lang, "the top level")


def _default(lang: str, typ: str) -> str:
    """A wrong-but-compiling return value (the trivial answer that must fail)."""
    if typ == "int":
        return "0"
    if typ == "float":
        return "0.0"
    if typ == "bool":
        return lit(lang, "bool", False)
    if typ == "str":
        if lang == "rust":
            return "String::new()"
        return '""'
    return lit(lang, typ, [])


def stub(lang: str, fn: str, params: list[tuple[str, str]], ret: str) -> str:
    sig = signature(lang, fn, params, ret)
    d = _default(lang, ret)
    if lang == "python":
        return sig + ":\n    return " + d + "\n"
    if lang in ("javascript", "typescript", "cpp", "go", "rust"):
        return sig + " {\n    return " + d + ";\n}\n" if lang != "rust" else sig + " {\n    " + d + "\n}\n"
    if lang == "csharp":
        return "public static class Solution {\n    " + sig + " { return " + d + "; }\n}\n"
    if lang == "java":
        return "public class Solution {\n    " + sig + " { return " + d + "; }\n}\n"
    if lang == "lua":
        return sig + "\n    return " + d + "\nend\n"
    if lang == "gdscript":
        return sig + ":\n\treturn " + d + "\n"
    raise ValueError(lang)


def wrap_reference(lang: str, code: str) -> str:
    """Bank references are bare functions; C#/Java tasks need the class around them."""
    if lang == "csharp" and "class Solution" not in code:
        return "using System;\nusing System.Collections.Generic;\nusing System.Linq;\n\npublic static class Solution {\n" + code.rstrip("\n") + "\n}\n"
    if lang == "java" and "class Solution" not in code:
        return "import java.util.*;\n\npublic class Solution {\n" + code.rstrip("\n") + "\n}\n"
    return code


# --- harness renderers ----------------------------------------------------------------------------------------

def _call(lang: str, fn: str, params, args) -> str:
    name = fn_name(lang, fn)
    rendered = []
    for (p, t), a in zip(params, args):
        value = lit(lang, t, a)
        if lang == "rust" and t.endswith("[]"):
            value = "&" + value
        rendered.append(value)
    if lang == "gdscript":
        return "S.%s(%s)" % (name, ", ".join(rendered))
    if lang in ("csharp", "java"):
        return "Solution.%s(%s)" % (name, ", ".join(rendered))
    return "%s(%s)" % (name, ", ".join(rendered))


def render(lang: str, fn: str, params, ret: str, cases: list) -> str:
    """cases: list of (args tuple, expected)."""
    calls = [(f"case{i + 1}", _call(lang, fn, params, args), lit(lang, ret, want)) for i, (args, want) in enumerate(cases)]
    n = len(cases)
    if lang == "python":
        body = "\n".join(f"__check({n!r}, lambda: {c}, {w})" for n, c, w in calls)
        return PY_HARNESS + body + f"\nprint('@@DONE %d/{n}' % __passed[0])\n"
    if lang in ("javascript", "typescript"):
        body = "\n".join(f"__check({n!r}, () => {c}, {w});" for n, c, w in calls)
        return (TS_HARNESS if lang == "typescript" else JS_HARNESS) + body + f"\nconsole.log('@@DONE ' + __passed + '/{n}');\n"
    if lang == "lua":
        body = "\n".join(f"__check({n!r}, function() return {c} end, {w})" for n, c, w in calls)
        return LUA_HARNESS + body + f"\nprint(('@@DONE %d/{n}'):format(__passed))\n"
    if lang == "gdscript":
        body = "\n".join(f"\t__check({n!r}, {c}, {w})" for n, c, w in calls)
        return GD_HARNESS.replace("@@CASES@@", body).replace("@@N@@", str(n))
    if lang == "cpp":
        body = "\n".join(f"    __check({n!r}, [&]{{ return {c}; }}, {w});" for n, c, w in calls)
        return CPP_HARNESS.replace("@@CASES@@", body).replace("@@N@@", str(n))
    if lang == "csharp":
        body = "\n".join(f"        Check({n!r}, () => {c}, {w});" for n, c, w in calls)
        return CS_HARNESS.replace("@@CASES@@", body).replace("@@N@@", str(n))
    if lang == "java":
        body = "\n".join(f"        check({n!r}, () -> {c}, {w});" for n, c, w in calls)
        return JAVA_HARNESS.replace("@@CASES@@", body).replace("@@N@@", str(n))
    if lang == "go":
        body = "\n".join(f"\tcheck({n!r}, func() interface{{}} {{ return {c} }}, {w})" for n, c, w in calls)
        return GO_HARNESS.replace("@@CASES@@", body).replace("@@N@@", str(n))
    if lang == "rust":
        body = "\n".join(f"    check({n!r}, || {c}, {w});" for n, c, w in calls)
        return RUST_HARNESS.replace("@@CASES@@", body).replace("@@N@@", str(n))
    raise ValueError(lang)


PY_HARNESS = '''
import math as __math
__passed = [0]
def __eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return __math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(__eq(x, y) for x, y in zip(a, b))
    return a == b
def __check(name, call, want):
    try:
        got = call()
    except Exception as exc:
        print("@@FAIL %s: raised %s: %s" % (name, type(exc).__name__, str(exc)[:80]))
        return
    if __eq(got, want):
        __passed[0] += 1
        print("@@PASS " + name)
    else:
        print("@@FAIL %s: got %r, want %r" % (name, got, want))
'''

JS_HARNESS = '''
let __passed = 0;
function __eq(a, b) {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-6 + 1e-6 * Math.abs(b);
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => __eq(x, b[i]));
  return a === b;
}
function __check(name, call, want) {
  let got;
  try { got = call(); } catch (e) { console.log("@@FAIL " + name + ": threw " + String(e).slice(0, 80)); return; }
  if (__eq(got, want)) { __passed++; console.log("@@PASS " + name); }
  else console.log("@@FAIL " + name + ": got " + JSON.stringify(got) + ", want " + JSON.stringify(want));
}
'''
TS_HARNESS = JS_HARNESS.replace("function __eq(a, b)", "function __eq(a: any, b: any): boolean").replace(
    "function __check(name, call, want)", "function __check(name: string, call: () => any, want: any): void").replace(
    "  let got;", "  let got: any;")

LUA_HARNESS = '''
local __passed = 0
local function __eq(a, b)
  if type(a) == "number" and type(b) == "number" then return math.abs(a - b) <= 1e-6 + 1e-6 * math.abs(b) end
  if type(a) == "table" and type(b) == "table" then
    if #a ~= #b then return false end
    for i = 1, #a do if not __eq(a[i], b[i]) then return false end end
    return true
  end
  return a == b
end
local function __show(v)
  if type(v) == "table" then local t = {} for i = 1, #v do t[#t+1] = __show(v[i]) end return "{" .. table.concat(t, ", ") .. "}" end
  return tostring(v)
end
local function __check(name, call, want)
  local ok, got = pcall(call)
  if not ok then print("@@FAIL " .. name .. ": error " .. tostring(got):sub(1, 80)) return end
  if __eq(got, want) then __passed = __passed + 1 print("@@PASS " .. name)
  else print("@@FAIL " .. name .. ": got " .. __show(got) .. ", want " .. __show(want)) end
end
'''

GD_HARNESS = '''extends SceneTree
var __passed := 0
var S = load("res://solution.gd")
func __eq(a, b) -> bool:
\tif (a is int or a is float) and (b is int or b is float):
\t\treturn abs(float(a) - float(b)) <= 1e-6 + 1e-6 * abs(float(b))
\tif a is Array and b is Array:
\t\tif a.size() != b.size():
\t\t\treturn false
\t\tfor i in range(a.size()):
\t\t\tif not __eq(a[i], b[i]):
\t\t\t\treturn false
\t\treturn true
\treturn a == b
func __check(name: String, got, want) -> void:
\tif __eq(got, want):
\t\t__passed += 1
\t\tprint("@@PASS " + name)
\telse:
\t\tprint("@@FAIL " + name + ": got " + str(got) + ", want " + str(want))
func _init():
\tif S == null:
\t\tprint("@@FAIL load: solution.gd did not load")
\telse:
@@CASES@@
\tprint("@@DONE %d/@@N@@" % __passed)
\tquit()
'''

CPP_HARNESS = '''
#include <iostream>
#include <string>
#include <vector>
#include <cmath>
#include <functional>
static int __passed = 0;
static bool __eq(int a, int b) { return a == b; }
static bool __eq(long long a, long long b) { return a == b; }
static bool __eq(bool a, bool b) { return a == b; }
static bool __eq(double a, double b) { return std::fabs(a - b) <= 1e-6 + 1e-6 * std::fabs(b); }
static bool __eq(const std::string& a, const std::string& b) { return a == b; }
template <class T> static bool __eq(const std::vector<T>& a, const std::vector<T>& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); ++i) if (!__eq(a[i], b[i])) return false;
    return true;
}
static std::string __show(int v) { return std::to_string(v); }
static std::string __show(long long v) { return std::to_string(v); }
static std::string __show(bool v) { return v ? "true" : "false"; }
static std::string __show(double v) { return std::to_string(v); }
static std::string __show(const std::string& v) { return "\\"" + v + "\\""; }
template <class T> static std::string __show(const std::vector<T>& v) {
    std::string s = "["; for (size_t i = 0; i < v.size(); ++i) { if (i) s += ", "; s += __show(v[i]); } return s + "]";
}
template <class F, class W> static void __check(const std::string& name, F call, const W& want) {
    try {
        auto got = call();
        if (__eq(got, want)) { ++__passed; std::cout << "@@PASS " << name << "\\n"; }
        else std::cout << "@@FAIL " << name << ": got " << __show(got) << ", want " << __show(want) << "\\n";
    } catch (const std::exception& e) { std::cout << "@@FAIL " << name << ": threw " << e.what() << "\\n"; }
    catch (...) { std::cout << "@@FAIL " << name << ": threw\\n"; }
}
int main() {
@@CASES@@
    std::cout << "@@DONE " << __passed << "/@@N@@" << std::endl;
    return 0;
}
'''

CS_HARNESS = '''
public static class Program {
    static int passed = 0;
    static bool Eq(object a, object b) {
        if (a is double da && b is double db) return System.Math.Abs(da - db) <= 1e-6 + 1e-6 * System.Math.Abs(db);
        if (a is double dd && b is int ib) return System.Math.Abs(dd - ib) <= 1e-6;
        if (a is System.Array aa && b is System.Array ab) {
            if (aa.Length != ab.Length) return false;
            for (int i = 0; i < aa.Length; i++) if (!Eq(aa.GetValue(i), ab.GetValue(i))) return false;
            return true;
        }
        return object.Equals(a, b);
    }
    static string Show(object v) {
        if (v is System.Array arr) { var parts = new System.Collections.Generic.List<string>(); foreach (var x in arr) parts.Add(Show(x)); return "[" + string.Join(", ", parts) + "]"; }
        if (v is string s) return "\\"" + s + "\\"";
        return v == null ? "null" : v.ToString();
    }
    static void Check<T>(string name, System.Func<T> call, T want) {
        T got;
        try { got = call(); } catch (System.Exception e) { System.Console.WriteLine("@@FAIL " + name + ": threw " + e.GetType().Name); return; }
        if (Eq(got, want)) { passed++; System.Console.WriteLine("@@PASS " + name); }
        else System.Console.WriteLine("@@FAIL " + name + ": got " + Show(got) + ", want " + Show(want));
    }
    public static void Main() {
@@CASES@@
        System.Console.WriteLine("@@DONE " + passed + "/@@N@@");
    }
}
'''

JAVA_HARNESS = '''import java.util.*;
import java.util.function.Supplier;

public class Main {
    static int passed = 0;
    static boolean eq(Object a, Object b) {
        if (a instanceof Number && b instanceof Number) {
            double x = ((Number) a).doubleValue(), y = ((Number) b).doubleValue();
            return Math.abs(x - y) <= 1e-6 + 1e-6 * Math.abs(y);
        }
        if (a instanceof int[] && b instanceof int[]) return Arrays.equals((int[]) a, (int[]) b);
        if (a instanceof double[] && b instanceof double[]) {
            double[] x = (double[]) a, y = (double[]) b;
            if (x.length != y.length) return false;
            for (int i = 0; i < x.length; i++) if (!eq(x[i], y[i])) return false;
            return true;
        }
        if (a instanceof Object[] && b instanceof Object[]) return Arrays.deepEquals((Object[]) a, (Object[]) b);
        return Objects.equals(a, b);
    }
    static String show(Object v) {
        if (v instanceof int[]) return Arrays.toString((int[]) v);
        if (v instanceof double[]) return Arrays.toString((double[]) v);
        if (v instanceof Object[]) return Arrays.deepToString((Object[]) v);
        if (v instanceof String) return "\\"" + v + "\\"";
        return String.valueOf(v);
    }
    static void check(String name, Supplier<Object> call, Object want) {
        Object got;
        try { got = call.get(); } catch (Throwable t) { System.out.println("@@FAIL " + name + ": threw " + t.getClass().getSimpleName()); return; }
        if (eq(got, want)) { passed++; System.out.println("@@PASS " + name); }
        else System.out.println("@@FAIL " + name + ": got " + show(got) + ", want " + show(want));
    }
    public static void main(String[] args) {
@@CASES@@
        System.out.println("@@DONE " + passed + "/@@N@@");
    }
}
'''

GO_HARNESS = '''package main

import (
\t"fmt"
\t"math"
\t"reflect"
)

var passed = 0

func eq(a, b interface{}) bool {
\tswitch x := a.(type) {
\tcase float64:
\t\ty, ok := b.(float64)
\t\tif !ok {
\t\t\tif yi, oki := b.(int); oki {
\t\t\t\ty, ok = float64(yi), true
\t\t\t}
\t\t}
\t\treturn ok && math.Abs(x-y) <= 1e-6+1e-6*math.Abs(y)
\tcase []float64:
\t\ty, ok := b.([]float64)
\t\tif !ok || len(x) != len(y) {
\t\t\treturn false
\t\t}
\t\tfor i := range x {
\t\t\tif !eq(x[i], y[i]) {
\t\t\t\treturn false
\t\t\t}
\t\t}
\t\treturn true
\t}
\treturn reflect.DeepEqual(a, b)
}

func check(name string, call func() interface{}, want interface{}) {
\tdefer func() {
\t\tif r := recover(); r != nil {
\t\t\tfmt.Println("@@FAIL " + name + ": panic " + fmt.Sprint(r))
\t\t}
\t}()
\tgot := call()
\tif eq(got, want) {
\t\tpassed++
\t\tfmt.Println("@@PASS " + name)
\t} else {
\t\tfmt.Printf("@@FAIL %s: got %v, want %v\\n", name, got, want)
\t}
}

func main() {
@@CASES@@
\tfmt.Printf("@@DONE %d/@@N@@\\n", passed)
}
'''

RUST_HARNESS = '''
trait Near { fn near(&self, other: &Self) -> bool; }
impl Near for i64 { fn near(&self, o: &Self) -> bool { self == o } }
impl Near for bool { fn near(&self, o: &Self) -> bool { self == o } }
impl Near for String { fn near(&self, o: &Self) -> bool { self == o } }
impl Near for f64 { fn near(&self, o: &Self) -> bool { (self - o).abs() <= 1e-6 + 1e-6 * o.abs() } }
impl<T: Near> Near for Vec<T> {
    fn near(&self, o: &Self) -> bool { self.len() == o.len() && self.iter().zip(o.iter()).all(|(a, b)| a.near(b)) }
}
static mut PASSED: i64 = 0;
fn check<T: Near + std::fmt::Debug, F: FnOnce() -> T + std::panic::UnwindSafe>(name: &str, call: F, want: T) {
    match std::panic::catch_unwind(call) {
        Ok(got) => {
            if got.near(&want) { unsafe { PASSED += 1; } println!("@@PASS {}", name); }
            else { println!("@@FAIL {}: got {:?}, want {:?}", name, got, want); }
        }
        Err(_) => println!("@@FAIL {}: panicked", name),
    }
}
fn main() {
    std::panic::set_hook(Box::new(|_| {}));
@@CASES@@
    println!("@@DONE {}/@@N@@", unsafe { PASSED });
}
'''
